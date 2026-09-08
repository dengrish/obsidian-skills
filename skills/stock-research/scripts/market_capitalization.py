#!/usr/bin/env python3
"""Calculate dated capitalization proxies from reviewed saved share evidence.

Reads --input '<plan.json>' (a list) and --as-of '<cutoff>'. Prints compatible
market-cap rows to stdout and coverage/unresolved diagnostics to stderr. Exit 2
means invalid or unresolved evidence. No network, credentials or file writes.
"""
from __future__ import annotations

import argparse
import copy
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from market_http import DataError, parse_date, parse_time, utc_now

METHOD = 'latest_disclosed_shares_price_proxy'
MAX_INPUT_BYTES = 4 * 1024 * 1024
SYMBOL = re.compile(r'[A-Z][A-Z0-9./-]{0,19}\Z')
CLASS = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,49}\Z')


def _ny():
    return ZoneInfo('America/New_York')


def _fail(message):
    raise DataError('unresolved_capitalization', message)


def _object(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys.split()):
        _fail(label + ' has missing or unsupported fields; use the reviewed-plan schema.')


def _text(value, label):
    if (not isinstance(value, str) or not value.strip() or len(value) > 2000
            or any(ord(ch) < 32 for ch in value)):
        _fail(label + ' requires nonblank evidence text without control characters.')
    return value


def _url(value):
    _text(value, 'Source URL')
    try:
        parts = urlsplit(value)
        if (parts.scheme != 'https' or not parts.hostname or parts.username is not None
                or parts.password is not None or parts.port not in (None, 443)
                or re.search(r'(?i)(?:[?&])(?:api_?key|token|access_token|secret|key)=', value)
                or any(ch.isspace() for ch in value)):
            _fail('Source URL must be public HTTPS without credentials.')
    except ValueError:
        _fail('Source URL must be public HTTPS without credentials.')
    return value


def _number(value, label, *, signed=False, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(label + ' must be a finite reviewed number.')
    try:
        out = Decimal(str(value))
        if (not out.is_finite() or (not signed and out <= 0)
                or (integer and out != out.to_integral_value()) or abs(out) > Decimal('1e18')):
            _fail(label + ' has an invalid amount or unit.')
    except (InvalidOperation, ValueError):
        _fail(label + ' must be a finite reviewed number.')
    return out


def _stamp(value, label, cutoff):
    try:
        stamp = parse_time(value)
    except DataError:
        _fail(label + ' requires a verified timestamp with seconds and a timezone.')
    if stamp > cutoff:
        _fail(label + ' is after the evidence cutoff.')
    return stamp


def _iso(value):
    return value.isoformat().replace('+00:00', 'Z')


def _range_float(value, *, lower):
    """Round a precision-range endpoint outwards when converting to JSON float."""
    result = float(value)
    if math.isfinite(result):
        represented = Decimal.from_float(result)
        if lower and represented > value:
            result = math.nextafter(result, -math.inf)
        elif not lower and represented < value:
            result = math.nextafter(result, math.inf)
    return result


def _policy(as_of, max_share_age_days):
    cutoff = parse_time(as_of)
    if cutoff > utc_now():
        _fail('The evidence cutoff cannot be in the future.')
    if type(max_share_age_days) is not int or not 1 <= max_share_age_days <= 365:
        _fail('Maximum share age must be an explicit whole number from 1 to 365 days.')
    return cutoff


def _calculate_item(plan, cutoff, max_share_age_days):
    _object(plan, 'symbol issuer_cik share_count_basis classes price review changes', 'Capitalization item')
    symbol = plan['symbol']
    if not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol):
        _fail('Capitalization symbol is invalid.')
    if (not isinstance(plan['issuer_cik'], str) or not re.fullmatch(r'\d{10}', plan['issuer_cik'])
            or int(plan['issuer_cik']) == 0):
        _fail('Use the verified issuer CIK as ten digits.')
    if plan['share_count_basis'] != 'outstanding_common':
        _fail('Use actual outstanding common shares, excluding treasury shares; EPS weighted averages, float and diluted potential shares are unsupported.')
    price = plan['price']
    _object(price, 'symbol class_id usd currency adjustment as_of available_at source_url', 'Price')
    if price['symbol'] != symbol or not isinstance(price['class_id'], str) or not CLASS.fullmatch(price['class_id']):
        _fail('The price must identify the requested symbol and its priced share class or ADS.')
    if price['currency'] != 'USD' or price['adjustment'] != 'raw':
        _fail('Use a timestamped unadjusted USD price matching the declared share basis.')
    price_usd = _number(price['usd'], 'USD price')
    measured = _stamp(price['as_of'], 'Price measurement', cutoff)
    price_available = _stamp(price['available_at'], 'Price availability', cutoff)
    if price_available < measured:
        _fail('Price availability cannot precede its measurement timestamp.')
    source_urls = {_url(price['source_url'])}
    available = [price_available]

    review = plan['review']
    _object(review, 'through available_at latest_filings_checked all_common_classes_included corporate_actions_checked unquantified_changes unsupported_complexity source_urls basis', 'Review')
    for key in ('latest_filings_checked', 'all_common_classes_included', 'corporate_actions_checked'):
        if review[key] is not True:
            _fail('Review must verify latest filings, the entire issuer common-share total and corporate actions.')
    for key in ('unquantified_changes', 'unsupported_complexity'):
        if review[key] is not False:
            _fail('Unquantified issuance, buybacks, splits or complex capital structures remain unresolved.')
    if _stamp(review['through'], 'Review coverage', cutoff) != measured:
        _fail('Review coverage must reach exactly the price measurement timestamp.')
    # This is evidence availability, never the time the analyst ran the review.
    available.append(_stamp(review['available_at'], 'Review-source availability', cutoff))
    _text(review['basis'], 'Review basis')
    if not isinstance(review['source_urls'], list) or not 1 <= len(review['source_urls']) <= 50:
        _fail('Review needs the source URLs checked for latest filings and corporate actions.')
    source_urls.update(_url(url) for url in review['source_urls'])

    classes = plan['classes']
    if not isinstance(classes, list) or not 1 <= len(classes) <= 20:
        _fail('Declare every outstanding common/economic share class of the issuer.')
    balances, uncertainties, class_dates, conversions, calculations = {}, {}, {}, {}, []
    for item in classes:
        _object(item, 'class_id shares uncertainty_shares precision_basis observed_on available_at source_url conversion', 'Share class')
        class_id = item['class_id']
        if not isinstance(class_id, str) or not CLASS.fullmatch(class_id) or class_id in balances:
            _fail('Share-class identities must be valid and distinct.')
        shares = _number(item['shares'], 'Outstanding share count', integer=True)
        uncertainty = _number(item['uncertainty_shares'], 'Share-count precision uncertainty', signed=True, integer=True)
        if uncertainty < 0 or uncertainty >= shares:
            _fail('Share-count uncertainty must be nonnegative and smaller than the disclosed count.')
        _text(item['precision_basis'], 'Source-backed share-count precision explanation')
        try:
            observed = parse_date(item['observed_on'])
        except DataError:
            _fail('Each outstanding share count needs its actual YYYY-MM-DD observation date.')
        disclosed = _stamp(item['available_at'], 'Share-count disclosure availability', cutoff)
        if observed > measured.astimezone(_ny()).date() or observed > disclosed.astimezone(_ny()).date():
            _fail('Share observation cannot follow the price date or its disclosure.')
        age = (measured.astimezone(_ny()).date() - observed).days
        if age > max_share_age_days:
            _fail('Outstanding shares exceed the declared freshness policy; obtain a newer count.')
        conversion = item['conversion']
        _object(conversion, 'kind shares_per_price_unit available_at source_url basis', 'Share/price conversion')
        if conversion['kind'] not in ('same_common', 'equivalent_common', 'adr'):
            _fail('Only matching common shares, evidenced equivalent common classes, or an explicit ADR ratio are supported.')
        ratio = _number(conversion['shares_per_price_unit'], 'Shares per priced unit')
        if conversion['kind'] == 'same_common' and (ratio != 1 or class_id != price['class_id']):
            _fail('Same-common pricing requires the same class identity and exactly one share per priced unit.')
        if conversion['kind'] == 'equivalent_common' and class_id == price['class_id']:
            _fail('Use same_common for the priced common class itself.')
        if conversion['kind'] == 'adr' and class_id == price['class_id']:
            _fail('ADR conversion must distinguish underlying ordinary shares from the priced ADS.')
        _text(conversion['basis'], 'Economic equivalence or ADR-ratio basis')
        available.extend((disclosed, _stamp(conversion['available_at'], 'Conversion-source availability', cutoff)))
        source_urls.update((_url(item['source_url']), _url(conversion['source_url'])))
        balances[class_id], class_dates[class_id], conversions[class_id] = shares, observed, ratio
        uncertainties[class_id] = uncertainty
        calculations.append({'class_id': class_id, 'base_shares': int(shares), 'observed_on': observed.isoformat(),
                             'share_age_days': age, 'shares_per_price_unit': float(ratio),
                             'base_uncertainty_shares': int(uncertainty)})
    kinds = {item['conversion']['kind'] for item in classes}
    if not kinds.intersection(('same_common', 'adr')) or {'same_common', 'adr'} <= kinds:
        _fail('Include the outstanding priced common class or the ADR underlying class; do not combine ADS counts with underlying common shares.')

    changes = plan['changes']
    if not isinstance(changes, list) or len(changes) > 200:
        _fail('Changes must explicitly list quantified share changes after each base observation, or be an empty list after review.')
    events, seen = [], set()
    for item in changes:
        _object(item, 'class_id kind value effective_at available_at source_url', 'Share change')
        class_id = item['class_id']
        if not isinstance(class_id, str) or class_id not in balances or item['kind'] not in ('share_delta', 'split'):
            _fail('A share change must identify a declared class and a supported quantified delta or split.')
        effective = _stamp(item['effective_at'], 'Share-change effective time', cutoff)
        if effective > measured or effective.astimezone(_ny()).date() <= class_dates[class_id]:
            _fail('Changes must occur after the base observation date and no later than the price; same-day ambiguity requires a new verified base.')
        if (class_id, effective) in seen:
            _fail('Multiple same-time changes to one class have ambiguous order; provide a new verified base count.')
        seen.add((class_id, effective))
        value = _number(item['value'], 'Share change', signed=item['kind'] == 'share_delta', integer=item['kind'] == 'share_delta')
        if value == 0:
            _fail('A listed share change cannot have a zero amount.')
        available.append(_stamp(item['available_at'], 'Share-change source availability', cutoff))
        source_urls.add(_url(item['source_url']))
        events.append((effective, class_id, item['kind'], value))
    for _, class_id, kind, value in sorted(events):
        balances[class_id] = balances[class_id] * value if kind == 'split' else balances[class_id] + value
        if kind == 'split':
            uncertainties[class_id] *= value
        if balances[class_id] <= 0 or balances[class_id] != balances[class_id].to_integral_value():
            _fail('Share changes produce an invalid or fractional aggregate count; reconcile the actual outstanding shares.')
        if balances[class_id] <= uncertainties[class_id]:
            _fail('Share changes leave an uncertainty range that cannot support positive outstanding shares.')
    total, total_uncertainty = Decimal(0), Decimal(0)
    for item in calculations:
        class_id = item['class_id']
        units = balances[class_id] / conversions[class_id]
        total += units
        total_uncertainty += uncertainties[class_id] / conversions[class_id]
        item.update(adjusted_outstanding_shares=int(balances[class_id]), equivalent_priced_units=float(units),
                    adjusted_uncertainty_shares=float(uncertainties[class_id]))
    cap = float(total * price_usd)
    estimate_range = {'low': _range_float((total - total_uncertainty) * price_usd, lower=True),
                      'high': _range_float((total + total_uncertainty) * price_usd, lower=False)}
    if any(not math.isfinite(value) or value <= 0 for value in (cap, *estimate_range.values())):
        _fail('Calculated capitalization must be finite and positive.')
    retained = copy.deepcopy(plan)
    digest = hashlib.sha256(json.dumps(retained, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    return {'symbol': symbol, 'market_cap_usd': cap, 'currency': 'USD', 'as_of': _iso(measured),
            'available_at': _iso(max(available)), 'source_url': classes[0]['source_url'],
            'basis': 'Entire-issuer outstanding common/economic shares, with reviewed intervening changes and explicit class/ADR conversions, times a matching raw USD price.',
            'method': METHOD, 'estimate': True, 'label': 'Estimated issuer common-equity capitalization',
            'estimate_range_usd': estimate_range,
            'calculation': {'plan': retained, 'input_sha256': digest, 'max_share_age_days': max_share_age_days,
                            'classes': calculations, 'equivalent_priced_units': float(total),
                            'price_usd': float(price_usd), 'source_urls': sorted(source_urls),
                            'formula': 'sum(adjusted outstanding class shares / shares per priced unit) * raw USD price'},
            'warnings': ['A reviewed latest-disclosed-share proxy is an estimate, not exact current capitalization or a lower bound.',
                         'The estimate range covers declared share-count precision only; it is not a guaranteed range for actual capitalization.',
                         'Freshness limits and review declarations do not prove the absence of unreported share changes; the source interpretation remains the reviewer responsibility.']}


def calculate(plan, as_of, max_share_age_days=120):
    """Return valid cap rows and safe diagnostics; one unresolved issuer yields no row."""
    cutoff = _policy(as_of, max_share_age_days)
    if not isinstance(plan, list) or not 1 <= len(plan) <= 100:
        _fail('Input must be a reviewed list of 1–100 issuer capitalization plans.')
    symbols = [row.get('symbol') for row in plan if isinstance(row, dict) and isinstance(row.get('symbol'), str)]
    duplicate_symbols = {symbol for symbol in symbols if symbols.count(symbol) > 1}
    rows, unresolved = [], []
    for index, item in enumerate(plan, 1):
        try:
            if isinstance(item, dict) and isinstance(item.get('symbol'), str) and item['symbol'] in duplicate_symbols:
                _fail('Duplicate symbol plans are ambiguous; provide one reviewed issuer basis.')
            rows.append(_calculate_item(item, cutoff, max_share_age_days))
        except (DataError, ValueError, TypeError, KeyError, OverflowError, InvalidOperation) as exc:
            # The precise safe DataError is collected without exposing arbitrary
            # source values, provider errors or local paths.
            diagnostic = {'item': index, 'code': exc.code if isinstance(exc, DataError) else 'invalid_input',
                          'message': str(exc) if isinstance(exc, DataError) else 'Invalid reviewed capitalization evidence.'}
            if isinstance(item, dict) and isinstance(item.get('symbol'), str) and SYMBOL.fullmatch(item['symbol']):
                diagnostic['symbol'] = item['symbol']
            unresolved.append(diagnostic)
    return {'market_capitalization': 1, 'complete': not unresolved, 'as_of': _iso(cutoff),
            'market_caps': rows, 'unresolved': unresolved,
            'coverage': {'requested': len(plan), 'calculated': len(rows), 'unresolved': len(unresolved)}}


def validate_proxy_row(row, cutoff):
    """Recompute a retained proxy row before another calculator relies on it."""
    if (not isinstance(row, dict) or not isinstance(row.get('calculation'), dict)
            or row.get('method') != METHOD or row.get('estimate') is not True):
        _fail('Proxy capitalization needs its complete retained calculation plan.')
    calculation = row['calculation']
    policy = calculation.get('max_share_age_days')
    stamp = _policy(cutoff, policy)
    expected = _calculate_item(calculation.get('plan'), stamp, policy)
    if row != expected:
        _fail('Proxy capitalization row differs from its retained reviewed calculation.')
    return row


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail('Duplicate JSON keys are invalid.')
        result[key] = value
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', action='store_true')
    parser.add_argument('--input', help='Reviewed capitalization-plan JSON list.')
    parser.add_argument('--as-of', help='Evidence cutoff timestamp with timezone.')
    parser.add_argument('--max-share-age-days', type=int, default=120)
    args = parser.parse_args(argv)
    if args.test:
        return self_test()
    try:
        if not args.input or not args.as_of:
            _fail('Provide --input and --as-of.')
        with Path(args.input).open('rb') as handle:
            raw = handle.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            _fail('Reviewed input exceeds 4 MiB.')
        plan = json.loads(raw.decode(), object_pairs_hook=_unique,
                          parse_constant=lambda value: _fail('Nonfinite JSON numbers are invalid.'))
        result = calculate(plan, args.as_of, args.max_share_age_days)
        rows = result.pop('market_caps')
    except (DataError, OSError, ValueError, TypeError, OverflowError, RecursionError) as exc:
        rows = []
        result = {'market_capitalization': 1, 'complete': False,
                  'error': {'code': exc.code if isinstance(exc, DataError) else 'invalid_input',
                            'message': str(exc) if isinstance(exc, DataError) else 'Invalid or unreadable reviewed evidence.'}}
    print(json.dumps(rows, allow_nan=False))
    print(json.dumps(result, allow_nan=False), file=sys.stderr)
    return 0 if result['complete'] else 2


def self_test():
    """Synthetic offline evidence checks arithmetic, temporal scope and refusal."""
    import contextlib
    import io
    import tempfile
    import unittest

    cutoff = '2025-04-01T21:00:00Z'
    filing = 'https://www.sec.gov/Archives/edgar/data/1/000000000125000001/fixture.htm'
    measured = '2025-04-01T20:00:00Z'

    def fixture():
        return {'symbol': 'FIX', 'issuer_cik': '0000000001', 'share_count_basis': 'outstanding_common',
                'classes': [{'class_id': 'common', 'shares': 100000000, 'uncertainty_shares': 0,
                             'precision_basis': 'The cover page reports an exact outstanding count without rounding.',
                             'observed_on': '2025-02-01',
                             'available_at': '2025-02-10T12:00:00Z', 'source_url': filing,
                             'conversion': {'kind': 'same_common', 'shares_per_price_unit': 1,
                                            'available_at': '2025-02-10T12:00:00Z', 'source_url': filing,
                                            'basis': 'The price is for one share of this sole outstanding common class.'}}],
                'price': {'symbol': 'FIX', 'class_id': 'common', 'usd': 30, 'currency': 'USD', 'adjustment': 'raw',
                          'as_of': measured, 'available_at': '2025-04-01T20:15:00Z',
                          'source_url': 'https://data.alpaca.markets/v2/stocks/bars'},
                'review': {'through': measured, 'available_at': '2025-04-01T19:00:00Z',
                           'latest_filings_checked': True, 'all_common_classes_included': True,
                           'corporate_actions_checked': True, 'unquantified_changes': False,
                           'unsupported_complexity': False, 'source_urls': [filing],
                           'basis': 'Latest cover-page count, all common classes and subsequent issuer filings/actions reviewed through the price time.'},
                'changes': []}

    class Cases(unittest.TestCase):
        def row(self, plan):
            result = calculate([plan], cutoff)
            self.assertTrue(result['complete'], result['unresolved'])
            return result['market_caps'][0]

        def unresolved(self, plan):
            result = calculate([plan], cutoff)
            self.assertFalse(result['complete'])
            self.assertEqual(result['market_caps'], [])
            self.assertEqual(result['unresolved'][0]['item'], 1)

        def test_simple_and_recomputation(self):
            row = self.row(fixture())
            self.assertEqual(row['market_cap_usd'], 3000000000)
            self.assertEqual(row['available_at'], '2025-04-01T20:15:00Z')
            self.assertTrue(row['estimate'])
            self.assertEqual(validate_proxy_row(row, cutoff), row)

        def test_equivalent_common_classes(self):
            plan = fixture()
            second = copy.deepcopy(plan['classes'][0])
            second.update(class_id='B', shares=20000000)
            second['conversion'].update(kind='equivalent_common', shares_per_price_unit=0.5,
                                        basis='One B share has the same economic participation as two priced A/common shares.')
            plan['classes'].append(second)
            self.assertEqual(self.row(plan)['market_cap_usd'], 4200000000)

        def test_adr_uses_entire_underlying_issuer(self):
            plan = fixture()
            plan['price']['class_id'] = 'ADS'
            plan['classes'][0]['conversion'].update(kind='adr', shares_per_price_unit=2,
                                                   basis='The deposit agreement states one ADS represents two underlying ordinary shares.')
            self.assertEqual(self.row(plan)['market_cap_usd'], 1500000000)

        def test_rounded_counts_preserve_threshold_uncertainty(self):
            plan = fixture()
            plan['classes'][0].update(shares=66667000, uncertainty_shares=500,
                                      precision_basis='The disclosure rounds common shares to the nearest thousand.')
            row = self.row(plan)
            self.assertEqual(row['market_cap_usd'], 2000010000)
            self.assertEqual(row['estimate_range_usd'], {'low': 1999995000, 'high': 2000025000})
            self.assertEqual(validate_proxy_row(row, cutoff), row)

        def test_quantified_splits_and_issuance_are_chronological(self):
            plan = fixture()
            plan['classes'][0].update(uncertainty_shares=1000,
                                      precision_basis='Disclosed count precision supports plus or minus one thousand shares.')
            plan['changes'] = [{'class_id': 'common', 'kind': 'share_delta', 'value': 10000000,
                                'effective_at': '2025-03-20T13:30:00Z', 'available_at': '2025-03-20T12:00:00Z', 'source_url': filing},
                               {'class_id': 'common', 'kind': 'split', 'value': 2,
                                'effective_at': '2025-03-10T13:30:00Z', 'available_at': '2025-03-09T12:00:00Z', 'source_url': filing}]
            row = self.row(plan)
            self.assertEqual(row['market_cap_usd'], 6300000000)
            self.assertEqual(row['estimate_range_usd'], {'low': 6299940000, 'high': 6300060000})

        def test_staleness_uses_observation_not_disclosure(self):
            plan = fixture()
            plan['classes'][0]['observed_on'] = '2024-10-01'
            plan['classes'][0]['available_at'] = '2025-03-31T12:00:00Z'
            self.unresolved(plan)

        def test_unsupported_measures(self):
            for basis in ('eps_weighted_average', 'diluted', 'float', 'treasury', 'issued_including_treasury'):
                with self.subTest(basis=basis):
                    plan = fixture()
                    plan['share_count_basis'] = basis
                    self.unresolved(plan)

        def test_incomplete_review_and_complexity(self):
            for key, value in (('latest_filings_checked', False), ('all_common_classes_included', False),
                               ('corporate_actions_checked', False), ('unquantified_changes', True),
                               ('unsupported_complexity', True), ('basis', '')):
                with self.subTest(key=key):
                    plan = fixture()
                    plan['review'][key] = value
                    self.unresolved(plan)

        def test_price_identity_adjustment_and_class_basis(self):
            for key, value in (('symbol', 'OTHER'), ('class_id', 'B'), ('currency', 'EUR'), ('adjustment', 'split')):
                with self.subTest(key=key):
                    plan = fixture()
                    plan['price'][key] = value
                    self.unresolved(plan)

        def test_postcutoff_sources_and_future_observation(self):
            for section in ('price', 'review', 'shares', 'conversion'):
                with self.subTest(section=section):
                    plan = fixture()
                    item = plan[section] if section in ('price', 'review') else plan['classes'][0]
                    if section == 'conversion':
                        item = item['conversion']
                    item['available_at'] = '2025-04-02T12:00:00Z'
                    self.unresolved(plan)
            plan = fixture()
            plan['classes'][0]['observed_on'] = '2025-04-02'
            self.unresolved(plan)

        def test_no_guessed_publication_timestamp(self):
            plan = fixture()
            plan['classes'][0]['available_at'] = '2025-02-10'
            self.unresolved(plan)

        def test_share_values_and_conversion_require_numbers(self):
            for value in (True, None, 0, -1, 1.5, float('nan')):
                with self.subTest(value=value):
                    plan = fixture()
                    plan['classes'][0]['shares'] = value
                    self.unresolved(plan)
            plan = fixture()
            plan['classes'][0]['conversion']['shares_per_price_unit'] = 2
            self.unresolved(plan)
            for uncertainty in (-1, 100000000, True, None):
                plan = fixture()
                plan['classes'][0]['uncertainty_shares'] = uncertainty
                self.unresolved(plan)

        def test_priced_class_cannot_be_omitted_or_double_counted(self):
            plan = fixture()
            plan['classes'][0]['class_id'] = 'B'
            plan['classes'][0]['conversion']['kind'] = 'equivalent_common'
            self.unresolved(plan)
            plan = fixture()
            adr = copy.deepcopy(plan['classes'][0])
            adr['class_id'] = 'underlying'
            adr['conversion']['kind'] = 'adr'
            plan['classes'].append(adr)
            self.unresolved(plan)

        def test_ambiguous_or_impossible_changes(self):
            for value, effective in ((-100000000, '2025-03-01T12:00:00Z'),
                                     (1, '2025-02-01T12:00:00Z'), (1, '2025-04-01T20:30:00Z')):
                with self.subTest(value=value, effective=effective):
                    plan = fixture()
                    plan['changes'] = [{'class_id': 'common', 'kind': 'share_delta', 'value': value,
                                        'effective_at': effective, 'available_at': '2025-03-01T12:00:00Z', 'source_url': filing}]
                    self.unresolved(plan)

        def test_duplicate_classes_and_symbols(self):
            plan = fixture()
            plan['classes'].append(copy.deepcopy(plan['classes'][0]))
            self.unresolved(plan)
            result = calculate([fixture(), fixture()], cutoff)
            self.assertFalse(result['complete'])
            self.assertEqual(result['market_caps'], [])

        def test_tampered_proxy_rejected(self):
            for key, value in (('market_cap_usd', 9000000000), ('estimate', False), ('method', 'exact'), ('available_at', measured)):
                with self.subTest(key=key):
                    row = self.row(fixture())
                    row[key] = value
                    with self.assertRaises(DataError):
                        validate_proxy_row(row, cutoff)

        def test_unresolved_item_does_not_remove_other_results(self):
            bad = fixture()
            bad['symbol'] = 'OTHER'
            result = calculate([fixture(), bad], cutoff)
            self.assertEqual([r['symbol'] for r in result['market_caps']], ['FIX'])
            self.assertEqual(result['unresolved'][0]['item'], 2)

        def test_private_urls_and_unknown_fields_rejected(self):
            for url in ('https://secret@example.invalid/report', 'https://example.invalid/report?apikey=private', 'file:///private/report'):
                with self.subTest(url=url):
                    plan = fixture()
                    plan['classes'][0]['source_url'] = url
                    self.unresolved(plan)
            plan = fixture()
            plan['guessed_shares'] = 100
            self.unresolved(plan)

        def test_cli_lists_stdout_diagnostics_stderr(self):
            with tempfile.TemporaryDirectory() as root:
                path = Path(root) / 'plan.json'
                path.write_text(json.dumps([fixture()]), encoding='utf-8')
                output, diagnostics = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(diagnostics):
                    self.assertEqual(main(['--input', str(path), '--as-of', cutoff]), 0)
                self.assertEqual(len(json.loads(output.getvalue())), 1)
                self.assertTrue(json.loads(diagnostics.getvalue())['complete'])
                path.write_text('[{"private":1,"private":2}]', encoding='utf-8')
                output, diagnostics = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(diagnostics):
                    self.assertEqual(main(['--input', str(path), '--as-of', cutoff]), 2)
                self.assertEqual(json.loads(output.getvalue()), [])
                self.assertNotIn('private', diagnostics.getvalue())

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Cases)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    passed = result.testsRun - len(result.errors) - len(result.failures)
    print(f'{passed}/{result.testsRun} self-tests passed')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
