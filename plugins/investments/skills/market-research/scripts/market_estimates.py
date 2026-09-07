#!/usr/bin/env python3
"""Read current Alpha Vantage estimates without inventing historical vintages.

Import through market_data.py; --test runs offline provider fixtures. This
module never writes files. market_estimate_history.py separately preserves
explicitly selected observations for later, cutoff-aware comparison.
"""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from market_http import DataError, parse_date, parse_time, required_env, utc_now
from market_news import API, _iso, _provider_error, _symbol

SOURCE = {'provider': 'alpha_vantage', 'endpoint': API, 'function': 'EARNINGS_ESTIMATES'}
ESTIMATE_FIELDS = (
    'eps_estimate_average', 'eps_estimate_high', 'eps_estimate_low',
    'eps_estimate_analyst_count', 'eps_estimate_average_7_days_ago',
    'eps_estimate_average_30_days_ago', 'eps_estimate_average_60_days_ago',
    'eps_estimate_average_90_days_ago', 'eps_estimate_revision_up_trailing_7_days',
    'eps_estimate_revision_down_trailing_7_days', 'eps_estimate_revision_up_trailing_30_days',
    'eps_estimate_revision_down_trailing_30_days', 'revenue_estimate_average',
    'revenue_estimate_high', 'revenue_estimate_low', 'revenue_estimate_analyst_count',
)
HORIZONS = ('fiscal quarter', 'fiscal year')


def _decimal(value, count=False):
    if value is None or value == '':
        return None
    if (not isinstance(value, str) or len(value) > 80
            or not re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[Ee][+-]?[0-9]{1,3})?', value)):
        raise ValueError('invalid estimate number')
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError('invalid estimate number') from exc
    if (not number.is_finite() or number.copy_abs() > Decimal('1e30')
            or (count and (number < 0 or number != number.to_integral_value()))):
        raise ValueError('invalid estimate number or analyst count')
    return value


def validate_estimate_row(row):
    """One normalized period; shared with the immutable snapshot reader."""
    try:
        if (not isinstance(row, dict) or set(row) != {
                'fiscal_period_end', 'horizon', 'currency', 'accounting_basis', 'values'}
                or row['horizon'] not in HORIZONS or row['accounting_basis'] is not None
                or (row['currency'] is not None and (not isinstance(row['currency'], str)
                    or not re.fullmatch(r'[A-Z]{3}', row['currency'])))
                or not isinstance(row['values'], dict) or set(row['values']) != set(ESTIMATE_FIELDS)):
            raise ValueError('invalid estimate row schema')
        period = parse_date(row['fiscal_period_end']).isoformat()
        values = {name: _decimal(row['values'][name], name.endswith('_count') or '_revision_' in name)
                  for name in ESTIMATE_FIELDS}
        for prefix in ('eps', 'revenue'):
            low, mean, high = (values[prefix + '_estimate_' + suffix] for suffix in ('low', 'average', 'high'))
            if ((low is not None and high is not None and Decimal(low) > Decimal(high))
                    or (low is not None and mean is not None and Decimal(low) > Decimal(mean))
                    or (high is not None and mean is not None and Decimal(mean) > Decimal(high))):
                raise ValueError('contradictory estimate bounds')
        return dict(row, fiscal_period_end=period, values=values)
    except (ValueError, TypeError, KeyError, InvalidOperation) as exc:
        raise DataError('invalid_response', 'Invalid estimate period, definition, number or bounds.') from exc


def has_current_estimate(row):
    """Counts and trailing averages alone are not a current estimate."""
    return any(row['values'][prefix + '_estimate_' + kind] is not None
               for prefix in ('eps', 'revenue') for kind in ('average', 'high', 'low'))


def alpha_estimates(client, args):
    """Capture current reported values; period ends are never availability dates."""
    symbol = _symbol(args.symbol)
    if symbol is None:
        raise DataError('invalid_input', 'An estimates request needs one ticker.')
    periods = getattr(args, 'period', None) or []
    if not isinstance(periods, list) or len(periods) > 8:
        raise DataError('invalid_input', 'Select at most eight fiscal period ends.')
    periods = sorted({parse_date(value).isoformat() for value in periods})
    cutoff_value = getattr(args, 'as_of', None)
    cutoff = parse_time(cutoff_value) if cutoff_value is not None else None
    if cutoff is not None and cutoff > utc_now():
        raise DataError('invalid_input', 'Estimates as_of cannot be in the future.')
    payload = client.get_json(API, params={
        'function': SOURCE['function'], 'symbol': symbol,
        'apikey': required_env(client.env, 'ALPHA_VANTAGE_API_KEY')})
    observed = utc_now()
    _provider_error(payload)
    if (payload.get('symbol') != symbol or not isinstance(payload.get('estimates'), list)
            or len(payload['estimates']) > 1000):
        raise DataError('invalid_response', 'Alpha Vantage returned an unexpected estimate identity or list.')
    data, seen, ambiguous, invalid = [], set(), set(), 0
    for raw in payload['estimates']:
        try:
            if not isinstance(raw, dict) or not any(name in raw for name in ESTIMATE_FIELDS):
                raise ValueError('missing estimate fields')
            if raw.get('horizon') not in HORIZONS:
                raise ValueError('unsupported estimate horizon')
            identity = parse_date(raw.get('date')).isoformat(), raw['horizon']
            if identity in seen:
                ambiguous.add(identity)
                raise ValueError('duplicate estimate identity')
            seen.add(identity)
            item = validate_estimate_row({
                'fiscal_period_end': raw.get('date'), 'horizon': raw.get('horizon'),
                'currency': raw.get('currency'), 'accounting_basis': None,
                'values': {name: raw.get(name) for name in ESTIMATE_FIELDS},
            })
        except (ValueError, TypeError, KeyError):
            invalid += 1
            continue
        if not periods or item['fiscal_period_end'] in periods:
            data.append(item)
    data = [row for row in data if (row['fiscal_period_end'], row['horizon']) not in ambiguous]
    missing = sorted(set(periods) - {row['fiscal_period_end'] for row in data})
    empty = sum(not has_current_estimate(row) for row in data)
    coverage = bool(data) and not invalid and not missing and not empty
    within_cutoff = cutoff is None or observed <= cutoff
    warnings = [
        'These are current provider estimates. Fiscal period ends are not observation dates; no historical vintage or publication timestamp is supplied.',
        'Trailing 7/30/60/90-day averages and revision counts are provider-reported summaries observed now, not independently preserved historical snapshots.',
        'Currency and EPS accounting basis may be absent; verify comparable units, basis, period and instrument before computing a beat or economic revision.',
        'Null values are unavailable estimates or counts, not zero. Analyst counts and revisions are provider coverage, not the whole market.',
    ]
    if not within_cutoff:
        warnings.append('Observed after the requested evidence cutoff: preserve separately for later reviews, never use this snapshot in the earlier edition.')
    if invalid:
        warnings.append('%d malformed or duplicate estimate row(s); coverage is incomplete.' % invalid)
    if missing:
        warnings.append('Requested fiscal periods are missing; coverage is incomplete.')
    if empty:
        warnings.append('One or more selected periods has no current EPS or revenue estimate; coverage is unavailable for those periods.')
    if not data:
        warnings.append('No usable estimates returned; this is unavailable coverage, not zero expectations.')
    return {
        'source': dict(SOURCE), 'query': {'symbol': symbol, 'periods': periods, 'as_of': _iso(cutoff) if cutoff else None},
        'observed_at': _iso(observed), 'provider_as_of': None, 'within_cutoff': within_cutoff,
        'coverage_complete': coverage, 'complete': coverage and within_cutoff, 'warnings': warnings,
        'provider_record_count': len(payload['estimates']), 'invalid_record_count': invalid,
        'missing_periods': missing, 'data': sorted(data, key=lambda row: (row['fiscal_period_end'], row['horizon'])),
    }


def run_self_test():
    import copy
    from datetime import datetime, timezone
    from types import SimpleNamespace
    import unittest
    from unittest.mock import Mock, patch

    class Tests(unittest.TestCase):
        def setUp(self):
            self.now = datetime(2026, 9, 7, 15, 30, tzinfo=timezone.utc)
            self.args = SimpleNamespace(symbol='IBM', period=None, as_of=None)
            self.row = {'date': '2026-09-30', 'horizon': 'fiscal quarter',
                        'eps_estimate_average': '2.50', 'eps_estimate_low': '2.20', 'eps_estimate_high': '2.90',
                        'eps_estimate_analyst_count': '24.0000', 'revenue_estimate_average': '12000000000.00',
                        'eps_estimate_revision_down_trailing_7_days': None}
            self.client = SimpleNamespace(env={'ALPHA_VANTAGE_API_KEY': 'fixture-only-key'},
                                          get_json=Mock(return_value={'symbol': 'IBM', 'estimates': [self.row]}))

        def call(self):
            with patch(__name__ + '.utc_now', return_value=self.now):
                return alpha_estimates(self.client, self.args)

        def test_current_period_precision_and_unknown_definitions(self):
            result = self.call()
            self.assertTrue(result['complete'])
            self.assertEqual(result['data'][0]['values']['eps_estimate_analyst_count'], '24.0000')
            self.assertIsNone(result['data'][0]['currency'])
            self.assertIsNone(result['provider_as_of'])
            self.assertEqual(self.client.get_json.call_args.kwargs['params']['function'], 'EARNINGS_ESTIMATES')

        def test_historical_period_does_not_make_current_estimate_available_earlier(self):
            self.row['date'] = '2020-03-31'
            self.args.as_of = '2026-09-07T15:29:59Z'
            result = self.call()
            self.assertFalse(result['complete'])
            self.assertFalse(result['within_cutoff'])
            self.assertTrue(result['coverage_complete'])
            self.assertEqual(result['observed_at'], '2026-09-07T15:30:00Z')

        def test_future_cutoff_and_bad_period_fail_before_network(self):
            for kwargs in ({'as_of': '2026-09-08T15:30:00Z'}, {'period': ['2026-02-30']}):
                self.args = SimpleNamespace(symbol='IBM', **kwargs)
                with self.subTest(kwargs=kwargs), self.assertRaises(DataError):
                    self.call()
            self.client.get_json.assert_not_called()

        def test_period_filter_and_missing_period(self):
            self.args.period = ['2026-09-30']
            self.assertTrue(self.call()['complete'])
            self.args.period.append('2027-03-31')
            self.assertFalse(self.call()['coverage_complete'])

        def test_repeated_period_never_produces_complete_capture(self):
            for value in ('2.50', '2.70', 'bad number'):
                self.client.get_json.return_value['estimates'] = [copy.deepcopy(self.row),
                    dict(self.row, eps_estimate_average=value)]
                result = self.call()
                self.assertFalse(result['coverage_complete'])
                self.assertEqual(result['data'], [])

        def test_magnitude_boundary_is_exact_and_numbers_are_ascii(self):
            self.assertEqual(_decimal('1e30'), '1e30')
            for value in ('1000000000000000000000000000000.0000000001',
                          '-1000000000000000000000000000000.0000000001', '١.٢'):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    _decimal(value)

        def test_annual_and_quarterly_same_date_stay_distinct(self):
            other = dict(self.row, horizon='fiscal year')
            self.client.get_json.return_value['estimates'].append(other)
            self.assertEqual(len(self.call()['data']), 2)

        def test_invalid_numbers_counts_and_bounds_stay_incomplete(self):
            for field, value in (('eps_estimate_average', 'NaN'), ('eps_estimate_average', True),
                                 ('eps_estimate_analyst_count', '1.5'), ('eps_estimate_analyst_count', '-1'),
                                 ('eps_estimate_low', '9'), ('eps_estimate_average', '1e999')):
                row = dict(self.row, **{field: value})
                self.client.get_json.return_value['estimates'] = [row]
                with self.subTest(field=field, value=value):
                    self.assertFalse(self.call()['coverage_complete'])

        def test_negative_eps_is_valid_and_blank_is_missing(self):
            self.row.update(eps_estimate_average='-0.25', eps_estimate_low='-0.30', eps_estimate_high='-0.20',
                            revenue_estimate_average='')
            result = self.call()
            self.assertTrue(result['coverage_complete'])
            self.assertIsNone(result['data'][0]['values']['revenue_estimate_average'])

        def test_empty_and_unrecognized_payloads_do_not_imply_no_opportunity(self):
            for rows in ([], [{}], [dict(self.row, horizon='unknown')]):
                self.client.get_json.return_value['estimates'] = rows
                self.assertFalse(self.call()['coverage_complete'])
            self.client.get_json.return_value = {'symbol': 'OTHER', 'estimates': [self.row]}
            with self.assertRaises(DataError):
                self.call()

        def test_all_null_estimates_or_counts_alone_are_unavailable(self):
            for extra in ({}, {'eps_estimate_analyst_count': '0'}, {'eps_estimate_average_7_days_ago': '2.5'}):
                self.client.get_json.return_value['estimates'] = [dict(
                    date='2026-09-30', horizon='fiscal quarter', eps_estimate_average=None, **extra)]
                result = self.call()
                self.assertFalse(result['coverage_complete'])
                self.assertTrue(any('no current EPS' in warning for warning in result['warnings']))

        def test_quota_and_entitlement_errors_never_echo_provider_text(self):
            for value, code in (('premium fixture-only-key', 'access_denied'), ('25 requests per day fixture-only-key', 'rate_limited')):
                self.client.get_json.return_value = {'Information': value}
                with self.subTest(code=code), self.assertRaises(DataError) as caught:
                    self.call()
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn('fixture-only-key', str(caught.exception))

    result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    print('%d/%d self-tests passed' % (result.testsRun - len(result.failures) - len(result.errors), result.testsRun))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', action='store_true')
    args = parser.parse_args()
    if args.test:
        raise SystemExit(run_self_test())
    parser.print_help()
