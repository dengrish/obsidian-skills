#!/usr/bin/env python3
"""Bounded FRED v1 series vintages and release calendars; no file writes.

Use market_data.py for retrieval; --test runs synthetic offline fixtures.
Daily real-time periods do not establish availability at an intraday cutoff.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from market_http import DataError, parse_date, required_env, utc_now


SERIES_URL = 'https://api.stlouisfed.org/fred/series'
OBSERVATIONS_URL = SERIES_URL + '/observations'
RELEASES_URL = 'https://api.stlouisfed.org/fred/releases/dates'
RELEASE_URL = 'https://api.stlouisfed.org/fred/release/dates'
DOCS = 'https://fred.stlouisfed.org/docs/api/fred/'
PAGE_SIZE = 1000


def _iso(value):
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def _integer(value, minimum, maximum):
    return not isinstance(value, bool) and isinstance(value, int) and minimum <= value <= maximum


def _bounds(args):
    start, end = parse_date(args.start), parse_date(args.end)
    if start > end:
        raise DataError('invalid_input', 'start must not follow end.')
    pages, limit = getattr(args, 'max_pages', 10), getattr(args, 'limit', 1000)
    if not _integer(pages, 1, 100) or not _integer(limit, 1, 100000):
        raise DataError('invalid_input', 'Use max_pages from 1 through 100 and a total limit from 1 through 100000.')
    return start, end, pages, limit


def _get(client, url, params):
    payload = client.get_json(url, params=dict(params, api_key=required_env(client.env, 'FRED_API_KEY'),
                                               file_type='json'))
    if not isinstance(payload, dict):
        raise DataError('invalid_response', 'FRED returned a non-object response.')
    if 'error_code' in payload or 'error_message' in payload:
        # Error bodies can echo the query key. Classify, but never return them.
        code, message = payload.get('error_code'), str(payload.get('error_message', '')).lower()
        if code in (401, 403) or any(term in message for term in ('api_key', 'api key', 'api-key')):
            raise DataError('access_denied', 'FRED denied the API key or endpoint access.')
        if code == 429 or any(term in message for term in ('rate limit', 'too many requests')):
            raise DataError('rate_limited', 'FRED reports a request limit; stop this source and retry later.')
        raise DataError('provider_error', 'FRED did not return the requested data; check the query and access.')
    return payload


def _text(value, *, optional=False):
    if optional and (value is None or value == ''):
        return value
    if not isinstance(value, str) or not value.strip():
        raise DataError('invalid_response', 'FRED returned a missing or malformed text field.')
    return value


def _date(value):
    try:
        return parse_date(value)
    except DataError:
        raise DataError('invalid_response', 'FRED returned an invalid calendar date.') from None


def _period(payload, start, end):
    if (_date(payload.get('realtime_start')) != start
            or _date(payload.get('realtime_end')) != end):
        raise DataError('invalid_response', 'FRED returned a different real-time date range.')


def _number(value):
    """FRED supplies decimal strings; retain exact spelling, including precision."""
    if value == '.':
        return None
    if not isinstance(value, str) or not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', value):
        raise DataError('invalid_response', 'FRED returned an invalid observation value.')
    try:
        valid = Decimal(value).is_finite()
    except InvalidOperation:
        valid = False
    if not valid:
        raise DataError('invalid_response', 'FRED returned a nonfinite observation value.')
    return value


def _metadata(payload, series, vintage):
    _period(payload, vintage, vintage)
    rows = payload.get('seriess')
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise DataError('invalid_response', 'FRED did not return exactly one requested series metadata record.')
    raw = rows[0]
    if raw.get('id') != series:
        raise DataError('invalid_response', 'FRED returned metadata for a different series.')
    _period(raw, vintage, vintage)
    if _date(raw.get('observation_start')) > _date(raw.get('observation_end')):
        raise DataError('invalid_response', 'FRED metadata observation bounds are reversed.')
    result = {key: _text(raw.get(key)) for key in (
        'id', 'title', 'realtime_start', 'realtime_end', 'observation_start', 'observation_end',
        'frequency', 'frequency_short', 'units', 'units_short',
        'seasonal_adjustment', 'seasonal_adjustment_short', 'last_updated')}
    stamp = result['last_updated']
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:[+-]\d{2}(?::?\d{2})?|Z)', stamp):
        raise DataError('invalid_response', 'FRED metadata update timestamp lacks a valid explicit offset.')
    try:
        # Python 3.10 needs the minutes in FRED's documented hour-only offset.
        normalized = re.sub(r'([+-]\d{2})$', r'\1:00', stamp.replace('Z', '+00:00'))
        normalized = re.sub(r'([+-]\d{2})(\d{2})$', r'\1:\2', normalized)
        result['provider_last_updated_at'] = _iso(datetime.fromisoformat(normalized))
    except ValueError:
        raise DataError('invalid_response', 'FRED metadata update timestamp is invalid.') from None
    result['notes'] = _text(raw.get('notes'), optional=True)
    result['source_url'] = 'https://fred.stlouisfed.org/series/' + series
    return result


def _pages(client, url, params, field, max_pages, limit, decode, identity, order):
    """Validate each page before retaining it; changed offsets/counts never complete."""
    rows, warnings, seen = [], [], set()
    total, pages, complete = None, 0, False
    failure = None
    for _ in range(max_pages):
        offset, page_limit = len(rows), min(PAGE_SIZE, limit - len(rows))
        try:
            payload = _get(client, url, dict(params, offset=offset, limit=page_limit))
            count, returned_limit = payload.get('count'), payload.get('limit')
            if (not _integer(count, 0, 1000000000) or not _integer(payload.get('offset'), 0, 1000000000)
                    or payload['offset'] != offset or not _integer(returned_limit, 1, page_limit)):
                raise DataError('invalid_response', 'FRED pagination count, offset, or limit is invalid.')
            if total is not None and count != total:
                raise DataError('changed_response', 'FRED result count changed between pages.')
            raw = payload.get(field)
            if (not isinstance(raw, list) or offset > count
                    or len(raw) != min(returned_limit, count - offset)):
                raise DataError('invalid_response', 'FRED page length conflicts with its pagination metadata.')
            parsed = decode(payload, raw)
            keys = [identity(row) for row in parsed]
            if len(set(keys)) != len(keys) or any(key in seen for key in keys):
                raise DataError('changed_response', 'FRED repeated a record within or across pages.')
            ordered = ([order(rows[-1])] if rows else []) + [order(row) for row in parsed]
            if ordered != sorted(ordered):
                raise DataError('changed_response', 'FRED records are not in the requested date order.')
        except DataError as error:
            if not pages:
                raise
            warnings.append('A later FRED page failed retrieval or validation; validated earlier pages '
                            f'are retained ({error.code}).')
            failure = {'code': error.code, 'message': str(error)}
            break
        rows.extend(parsed)
        seen.update(keys)
        total, pages = count, pages + 1
        if len(rows) == total:
            complete = True
            break
        if len(rows) >= limit:
            warnings.append('Total record limit reached with more FRED records available.')
            break
    else:
        warnings.append('Page budget reached with more FRED records available.')
    pagination = {'pages': pages, 'returned': len(rows), 'provider_count': total, 'exhausted': complete}
    if failure is not None:
        pagination['error'] = failure
    return rows, complete, warnings, pagination


def fred_series(client, args):
    """Native-frequency, untransformed observations at one explicit daily vintage."""
    start, end, pages, limit = _bounds(args)
    series = getattr(args, 'series', None)
    if not isinstance(series, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', series):
        raise DataError('invalid_input', 'Provide one FRED series ID, without a URL or list.')
    vintage = parse_date(getattr(args, 'vintage_date', None))
    today = utc_now().astimezone(ZoneInfo('America/Chicago')).date()
    if vintage > today:
        raise DataError('invalid_input', 'vintage_date must not be a future St. Louis calendar date.')
    common = {'series_id': series, 'realtime_start': vintage.isoformat(), 'realtime_end': vintage.isoformat()}
    metadata = _metadata(_get(client, SERIES_URL, common), series, vintage)
    params = dict(common, observation_start=start.isoformat(), observation_end=end.isoformat(),
                  units='lin', output_type=1, sort_order='asc')

    def decode(payload, raw):
        _period(payload, vintage, vintage)
        if (_date(payload.get('observation_start')) != start or _date(payload.get('observation_end')) != end
                or payload.get('units') != 'lin' or not _integer(payload.get('output_type'), 1, 1)
                or payload.get('sort_order') != 'asc' or payload.get('order_by') != 'observation_date'):
            raise DataError('invalid_response', 'FRED observation query metadata does not match the requested scope.')
        result = []
        for row in raw:
            if not isinstance(row, dict):
                raise DataError('invalid_response', 'FRED observation is not an object.')
            _period(row, vintage, vintage)
            observation = _date(row.get('date'))
            if not start <= observation <= end:
                raise DataError('invalid_response', 'FRED observation is outside the requested date range.')
            result.append({'observation_date': observation.isoformat(), 'value': _number(row.get('value')),
                           'realtime_start': row['realtime_start'], 'realtime_end': row['realtime_end']})
        return result

    rows, complete, warnings, pagination = _pages(
        client, OBSERVATIONS_URL, params, 'observations', pages, limit, decode,
        lambda row: row['observation_date'], lambda row: row['observation_date'])
    warnings.extend([
        'Observation dates describe measured periods, not publication dates; values may be revised across vintages.',
        'The explicit vintage has daily precision and does not establish availability at an intraday cutoff.',
        'Returned real-time bounds may be clipped to the requested vintage; they are not actual revision or release dates.',
        'The series metadata last_updated is a provider update time, not each observation\'s first publication time.',
    ])
    if vintage == today:
        warnings.append('Today\'s vintage is still a changing daily snapshot; same-day intraday availability is unverified.')
    missing = sum(row['value'] is None for row in rows)
    if missing:
        warnings.append(f'{missing} observation values are missing; FRED dots are returned as null, never zero.')
    if not rows:
        warnings.append('No observations were returned for this query; this does not establish zero activity or full history.')
    return {'provider': 'fred', 'resource': 'series', 'complete': complete, 'warnings': warnings,
            'retrieved_at': _iso(utc_now()), 'point_in_time_verified': False, 'pagination': pagination,
            'source': {'url': OBSERVATIONS_URL, 'metadata_url': SERIES_URL,
                       'documentation': DOCS + 'series_observations.html', 'source_url': metadata['source_url'],
                       'time_resolution': 'date', 'coverage': 'requested FRED series, observation range, and daily vintage'},
            'query': dict(params, vintage_date=vintage.isoformat(), max_pages=pages, limit=limit),
            'data': {'series': metadata, 'observations': rows}}


def fred_releases(client, args):
    """Date-only source release calendar as retrieved now, including scheduled dates."""
    start, end, pages, limit = _bounds(args)
    release_id = getattr(args, 'release_id', None)
    if release_id is not None and not _integer(release_id, 1, 2147483647):
        raise DataError('invalid_input', 'release_id must be a positive integer.')
    url = RELEASES_URL if release_id is None else RELEASE_URL
    params = {'realtime_start': start.isoformat(), 'realtime_end': end.isoformat(), 'sort_order': 'asc',
              'include_release_dates_with_no_data': 'true'}
    if release_id is None:
        params['order_by'] = 'release_date'
    else:
        params['release_id'] = release_id

    def decode(payload, raw):
        _period(payload, start, end)
        if payload.get('order_by') != 'release_date' or payload.get('sort_order') != 'asc':
            raise DataError('invalid_response', 'FRED release query metadata does not match the requested sort.')
        result = []
        for row in raw:
            if not isinstance(row, dict) or not _integer(row.get('release_id'), 1, 2147483647):
                raise DataError('invalid_response', 'FRED returned an invalid release record.')
            identity, released = row['release_id'], _date(row.get('date'))
            if not start <= released <= end or (release_id is not None and identity != release_id):
                raise DataError('invalid_response', 'FRED release is outside the requested scope.')
            result.append({'release_id': identity, 'release_date': released.isoformat(),
                           'release_name': _text(row.get('release_name'), optional=release_id is not None),
                           'release_last_updated': _text(row.get('release_last_updated'), optional=True),
                           'source_url': 'https://fred.stlouisfed.org/release?rid=' + str(identity)})
        return result

    rows, complete, warnings, pagination = _pages(
        client, url, params, 'release_dates', pages, limit, decode,
        lambda row: (row['release_date'], row['release_id']), lambda row: row['release_date'])
    warnings.extend([
        'Release dates are date-only source publication dates; they do not establish when data became available on FRED or ALFRED.',
        'This is the calendar as retrieved now, not a historical calendar snapshot; scheduled dates can change.',
        'Dates with no data are included; a calendar entry or release_last_updated does not verify a particular value at an intraday cutoff.',
    ])
    return {'provider': 'fred', 'resource': 'releases', 'complete': complete, 'warnings': warnings,
            'retrieved_at': _iso(utc_now()), 'point_in_time_verified': False, 'pagination': pagination,
            'source': {'url': url, 'documentation': DOCS + ('releases_dates.html' if release_id is None else 'release_dates.html'),
                       'time_resolution': 'date', 'coverage': 'requested FRED release-calendar date range'},
            'query': dict(params, start=start.isoformat(), end=end.isoformat(), max_pages=pages, limit=limit),
            'data': {'release_dates': rows}}


def run_self_test():
    import copy
    import json
    from types import SimpleNamespace
    import unittest
    from unittest.mock import patch

    now = datetime(2026, 9, 5, 13, tzinfo=timezone.utc)
    vintage = '2026-09-04'

    class Client:
        def __init__(self, *responses, env=None):
            self.responses, self.calls = list(responses), []
            self.env = {'FRED_API_KEY': 'fixture-secret-not-a-real-key'} if env is None else env

        def get_json(self, url, params=None):
            self.calls.append((url, copy.deepcopy(params)))
            result = self.responses.pop(0)
            if isinstance(result, Exception):
                raise result
            return copy.deepcopy(result)

    def args(**changes):
        return SimpleNamespace(**dict({'series': 'FIXTURE', 'start': '2026-01-01', 'end': '2026-03-01',
                                      'vintage_date': vintage, 'max_pages': 10, 'limit': 1000,
                                      'release_id': None}, **changes))

    def meta():
        return {'realtime_start': vintage, 'realtime_end': vintage, 'seriess': [
            {'id': 'FIXTURE', 'title': 'Synthetic fixture series', 'realtime_start': vintage,
             'realtime_end': vintage, 'observation_start': '2026-01-01', 'observation_end': '2026-03-01',
             'frequency': 'Monthly', 'frequency_short': 'M', 'units': 'Fixture units', 'units_short': 'FU',
             'seasonal_adjustment': 'Not Seasonally Adjusted', 'seasonal_adjustment_short': 'NSA',
             'last_updated': '2026-09-04 08:30:00-05'}]}

    def observation(day='2026-01-01', value='1.234567890123456789'):
        return {'date': day, 'value': value, 'realtime_start': vintage, 'realtime_end': vintage}

    def observations(rows=None, **changes):
        rows = [observation()] if rows is None else rows
        return dict({'realtime_start': vintage, 'realtime_end': vintage, 'observation_start': '2026-01-01',
                     'observation_end': '2026-03-01', 'units': 'lin', 'output_type': 1, 'order_by': 'observation_date',
                     'sort_order': 'asc', 'count': len(rows), 'offset': 0, 'limit': 1000, 'observations': rows}, **changes)

    def releases(rows=None, **changes):
        rows = [{'release_id': 7, 'release_name': 'Synthetic fixture release', 'date': '2026-02-01'}] if rows is None else rows
        return dict({'realtime_start': '2026-01-01', 'realtime_end': '2026-03-01', 'order_by': 'release_date',
                     'sort_order': 'asc', 'count': len(rows), 'offset': 0, 'limit': 1000, 'release_dates': rows}, **changes)

    class FredTests(unittest.TestCase):
        def test_daily_vintage_metadata_precision_and_missingness(self):
            client = Client(meta(), observations([observation(), observation('2026-02-01', '.'),
                                                 observation('2026-03-01', '-2.00')]))
            result = fred_series(client, args())
            self.assertTrue(result['complete'])
            self.assertFalse(result['point_in_time_verified'])
            self.assertEqual([row['value'] for row in result['data']['observations']], ['1.234567890123456789', None, '-2.00'])
            self.assertEqual(result['data']['series']['provider_last_updated_at'], '2026-09-04T13:30:00Z')
            self.assertEqual(result['data']['series']['units'], 'Fixture units')
            self.assertEqual(result['retrieved_at'], '2026-09-05T13:00:00Z')
            self.assertNotIn('fixture-secret', json.dumps(result))
            for url, params in client.calls:
                self.assertIn(url, (SERIES_URL, OBSERVATIONS_URL))
                self.assertEqual(params['realtime_start'], vintage)
                self.assertEqual(params['realtime_end'], vintage)
                self.assertEqual(params['file_type'], 'json')

        def test_optional_notes_and_provider_offsets(self):
            for offset, expected in (('-05', '13:30:00Z'), ('-0500', '13:30:00Z'),
                                     ('-05:00', '13:30:00Z'), ('Z', '08:30:00Z'),
                                     ('+05:30', '03:00:00Z')):
                raw = meta()
                raw['seriess'][0].update(notes='', last_updated='2026-09-04 08:30:00' + offset)
                with self.subTest(offset=offset):
                    result = fred_series(Client(raw, observations()), args())['data']['series']
                    self.assertEqual(result['notes'], '')
                    self.assertEqual(result['provider_last_updated_at'], '2026-09-04T' + expected)
            for stamp in ('2026-09-04 08:30:00', '2026-09-04 08:30:00-25', '2026-02-30 08:30:00-05'):
                raw = meta()
                raw['seriess'][0]['last_updated'] = stamp
                with self.subTest(stamp=stamp), self.assertRaises(DataError):
                    fred_series(Client(raw), args())

        def test_invalid_input_precedes_network(self):
            for change in ({'series': 'A,B'}, {'series': 'https://example.com'}, {'vintage_date': None},
                           {'vintage_date': '2026-09-06'}, {'vintage_date': '2026-09-04T09:00:00Z'},
                           {'vintage_date': '2026-02-30'}, {'start': '2026-04-01'}, {'end': '2026-02-30'},
                           {'limit': True}, {'limit': 0}, {'max_pages': 101}):
                client = Client()
                with self.subTest(change=change), self.assertRaises(DataError):
                    fred_series(client, args(**change))
                self.assertFalse(client.calls)
            for invalid in (True, 0, -1, '7'):
                client = Client()
                with self.assertRaises(DataError):
                    fred_releases(client, args(release_id=invalid))
                self.assertFalse(client.calls)

        def test_today_is_daily_only_and_chicago_date_guards_future(self):
            with patch(__name__ + '.utc_now', return_value=datetime(2026, 9, 4, 1, tzinfo=timezone.utc)):
                with self.assertRaises(DataError):
                    fred_series(Client(), args())
            with patch(__name__ + '.utc_now', return_value=datetime(2026, 9, 4, 20, tzinfo=timezone.utc)):
                result = fred_series(Client(meta(), observations()), args())
                self.assertTrue(any('changing daily snapshot' in warning for warning in result['warnings']))
                self.assertFalse(result['point_in_time_verified'])

        def test_schema_and_query_echo_fail_closed(self):
            bad_meta = meta()
            bad_meta['seriess'][0]['id'] = 'OTHER'
            with self.assertRaises(DataError):
                fred_series(Client(bad_meta), args())
            bad_pages = [observations(count=True), observations(offset=1), observations(count=2),
                         observations(observation_end='2026-03-02'), observations(units='pch'),
                         observations(output_type=4), observations(realtime_start='2026-09-03'),
                         observations(order_by='unknown'), observations(observations=None), []]
            for page in bad_pages:
                with self.subTest(page=page), self.assertRaises(DataError):
                    fred_series(Client(meta(), page), args())
            for value in (None, 0, False, 'NaN', 'Infinity', '', '1,000', ' 3'):
                with self.subTest(value=value), self.assertRaises(DataError):
                    fred_series(Client(meta(), observations([observation(value=value)])), args())
            for row in (observation('2025-12-31'), observation('2026-02-30'),
                        dict(observation(), realtime_end='2026-09-05')):
                with self.assertRaises(DataError):
                    fred_series(Client(meta(), observations([row])), args())

        def test_pagination_and_total_cap(self):
            with patch(__name__ + '.PAGE_SIZE', 1):
                first = observations(count=2, limit=1)
                second = observations([observation('2026-02-01')], count=2, offset=1, limit=1)
                client = Client(meta(), first, second)
                result = fred_series(client, args())
                self.assertTrue(result['complete'])
                self.assertEqual(result['pagination']['pages'], 2)
                self.assertEqual([call[1]['offset'] for call in client.calls[1:]], [0, 1])
                capped = fred_series(Client(meta(), first), args(limit=1))
                self.assertFalse(capped['complete'])
                self.assertFalse(capped['pagination']['exhausted'])
                self.assertFalse(fred_series(Client(meta(), first), args(max_pages=1))['complete'])
                exact = fred_series(Client(meta(), observations(count=1, limit=1)), args(limit=1))
                self.assertTrue(exact['complete'])

        def test_later_failures_duplicates_and_changed_pages_retain_only_valid_pages(self):
            with patch(__name__ + '.PAGE_SIZE', 1):
                first = observations(count=2, limit=1)
                failures = [DataError('access_denied', 'Access unavailable.'),
                            DataError('request_budget', 'Bound exhausted.'),
                            observations(count=2, offset=0, limit=1),
                            observations(count=2, offset=1, limit=1),
                            observations([observation('2026-02-01')], count=3, offset=1, limit=1),
                            observations([], count=2, offset=1, limit=1)]
                for failure in failures:
                    with self.subTest(failure=failure):
                        result = fred_series(Client(meta(), first, failure), args())
                        self.assertFalse(result['complete'])
                        self.assertFalse(result['pagination']['exhausted'])
                        self.assertEqual(len(result['data']['observations']), 1)
                        if isinstance(failure, DataError):
                            self.assertEqual(result['pagination']['error']['code'], failure.code)
            for rows in ([observation(), observation()], [observation('2026-02-01'), observation()]):
                with self.assertRaises(DataError):
                    fred_series(Client(meta(), observations(rows)), args())

        def test_access_errors_are_safe_and_empty_count_is_scoped(self):
            for code, message, expected in ((400, 'api_key fixture-secret-not-a-real-key invalid', 'access_denied'),
                                            (429, 'fixture-secret-not-a-real-key quota', 'rate_limited'),
                                            (400, 'fixture-secret-not-a-real-key bad series', 'provider_error')):
                with self.assertRaises(DataError) as result:
                    fred_series(Client({'error_code': code, 'error_message': message}), args())
                self.assertEqual(result.exception.code, expected)
                self.assertNotIn('fixture-secret', str(result.exception))
            client = Client(env={})
            with self.assertRaises(DataError) as result:
                fred_series(client, args())
            self.assertEqual(result.exception.code, 'missing_credentials')
            self.assertFalse(client.calls)
            empty = fred_series(Client(meta(), observations([])), args())
            self.assertTrue(empty['complete'])
            self.assertFalse(empty['point_in_time_verified'])
            self.assertEqual(empty['data']['observations'], [])

        def test_release_calendar_all_and_one_with_future_date(self):
            client = Client(releases())
            result = fred_releases(client, args())
            self.assertTrue(result['complete'])
            self.assertFalse(result['point_in_time_verified'])
            self.assertEqual(client.calls[0][0], RELEASES_URL)
            self.assertEqual(client.calls[0][1]['include_release_dates_with_no_data'], 'true')
            self.assertEqual(client.calls[0][1]['sort_order'], 'asc')
            self.assertEqual(result['data']['release_dates'][0]['release_date'], '2026-02-01')
            future = releases([{'release_id': 7, 'date': '2027-02-01'}],
                              realtime_start='2027-01-01', realtime_end='2027-03-01')
            client = Client(future)
            result = fred_releases(client, args(start='2027-01-01', end='2027-03-01', release_id=7))
            self.assertTrue(result['complete'])
            self.assertIsNone(result['data']['release_dates'][0]['release_name'])
            self.assertEqual(client.calls[0][0], RELEASE_URL)
            self.assertEqual(client.calls[0][1]['release_id'], 7)
            self.assertNotIn('order_by', client.calls[0][1])

        def test_release_scope_duplicates_and_later_failure(self):
            for rows in ([{'release_id': 7, 'release_name': 'Fixture', 'date': '2026-04-01'}],
                         [{'release_id': False, 'release_name': 'Fixture', 'date': '2026-02-01'}],
                         [{'release_id': 7, 'date': '2026-02-01'}]):
                with self.assertRaises(DataError):
                    fred_releases(Client(releases(rows)), args())
            with self.assertRaises(DataError):
                fred_releases(Client(releases()), args(release_id=8))
            raw = releases()['release_dates'][0]
            with self.assertRaises(DataError):
                fred_releases(Client(releases([raw, raw])), args())
            with patch(__name__ + '.PAGE_SIZE', 1):
                first = releases(count=2, limit=1)
                repeated = releases(count=2, offset=1, limit=1)
                for later in (repeated, DataError('rate_limited', 'Quota reached.')):
                    result = fred_releases(Client(first, later), args())
                    self.assertFalse(result['complete'])
                    self.assertEqual(len(result['data']['release_dates']), 1)
                    self.assertEqual(result['pagination']['error']['code'],
                                     'rate_limited' if isinstance(later, DataError) else 'changed_response')
                other = dict(raw, release_id=9)
                second = releases([other], count=2, offset=1, limit=1)
                self.assertTrue(fred_releases(Client(first, second), args())['complete'])

    with patch(__name__ + '.utc_now', return_value=now):
        result = unittest.TextTestRunner(verbosity=0).run(unittest.defaultTestLoader.loadTestsFromTestCase(FredTests))
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print(f'{passed}/{result.testsRun} self-test cases pass')
    return result.wasSuccessful()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', action='store_true')
    options = parser.parse_args()
    if options.test:
        raise SystemExit(0 if run_self_test() else 1)
    parser.print_help()
