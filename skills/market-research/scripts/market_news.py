#!/usr/bin/env python3
"""Read Alpha Vantage news and earnings calendars through market_data.py.

This provider module makes no file writes and never places trades. Credentials
come from ALPHA_VANTAGE_API_KEY, via the shared read-only transport. Run this
file with --test for offline fixtures; use market_data.py for live requests.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import io
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from market_http import DataError, parse_date, parse_time, required_env, utc_now

API = 'https://www.alphavantage.co/query'
TOPICS = frozenset(('blockchain', 'earnings', 'ipo', 'mergers_and_acquisitions',
                    'financial_markets', 'economy_fiscal', 'economy_monetary',
                    'economy_macro', 'energy_transportation', 'finance',
                    'life_sciences', 'manufacturing', 'real_estate',
                    'retail_wholesale', 'technology'))
CALENDAR_FIELDS = ('symbol', 'name', 'reportDate', 'fiscalDateEnding',
                   'estimate', 'currency')


def _iso(value):
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def _symbol(value):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9.-]{0,14}', value):
        raise DataError('invalid_input', 'Provide one U.S. stock symbol; ticker lists are not supported.')
    return value.upper()


def _provider_error(payload):
    """Never echo API error text: it can contain query credentials."""
    if not isinstance(payload, dict):
        raise DataError('invalid_response', 'Alpha Vantage returned an unexpected response shape.')
    for field in ('Error Message', 'Information', 'Note'):
        if field not in payload:
            continue
        message = str(payload[field]).lower()
        if any(term in message for term in ('rate limit', 'call frequency', 'requests per',
                                            'request per', 'calls per', '25 requests',
                                            'api call volume')):
            raise DataError('rate_limited', 'Alpha Vantage reports a request quota limit; do not retry this run.')
        if any(term in message for term in ('apikey', 'api key', 'api-key', 'premium',
                                            'subscription', 'entitlement')):
            raise DataError('access_denied', 'Alpha Vantage reports unavailable credentials or endpoint access.')
        raise DataError('provider_error', 'Alpha Vantage did not return the requested data; check access and query parameters.')


def _text(value, *, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError('invalid text field')
    return value


def _number(value):
    """Preserve decimal precision in JSON; blanks mean missing, never zero."""
    if value is None or value == '':
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError('invalid numeric field')
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError('invalid numeric field') from exc
    if not number.is_finite():
        raise ValueError('nonfinite numeric field')
    return str(value)


def _news_item(row):
    if not isinstance(row, dict):
        raise ValueError('invalid article')
    raw_time = row.get('time_published')
    if not isinstance(raw_time, str) or not re.fullmatch(r'\d{8}T\d{6}', raw_time):
        raise ValueError('invalid publication time')
    published = datetime.strptime(raw_time, '%Y%m%dT%H%M%S').replace(tzinfo=timezone.utc)
    url = _text(row.get('url'), required=True)
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('invalid publisher URL')
    authors = row.get('authors', [])
    if not isinstance(authors, list) or not all(isinstance(item, str) for item in authors):
        raise ValueError('invalid authors')
    tickers = row.get('ticker_sentiment', [])
    topics = row.get('topics', [])
    if not isinstance(tickers, list) or not isinstance(topics, list):
        raise ValueError('invalid provider classifications')
    ticker_scores = []
    for ticker in tickers:
        if not isinstance(ticker, dict):
            raise ValueError('invalid ticker classification')
        ticker_scores.append({
            'ticker': _text(ticker.get('ticker'), required=True),
            'relevance_score': _number(ticker.get('relevance_score')),
            'sentiment_score': _number(ticker.get('ticker_sentiment_score')),
            'sentiment_label': _text(ticker.get('ticker_sentiment_label')),
        })
    topic_scores = []
    for topic in topics:
        if not isinstance(topic, dict):
            raise ValueError('invalid topic classification')
        topic_scores.append({'topic': _text(topic.get('topic'), required=True),
                             'relevance_score': _number(topic.get('relevance_score'))})
    return published, {
        'title': _text(row.get('title'), required=True),
        'url': url,
        'published_at': _iso(published),
        'provider_time_published': raw_time,
        'summary': _text(row.get('summary')),
        'authors': authors,
        'publisher': _text(row.get('source')),
        'publisher_domain': _text(row.get('source_domain')),
        'overall_sentiment_score': _number(row.get('overall_sentiment_score')),
        'overall_sentiment_label': _text(row.get('overall_sentiment_label')),
        'ticker_sentiment': ticker_scores,
        'topics': topic_scores,
    }


def alpha_news(client, args):
    """Retrieve one provider result set; saturation never implies full coverage."""
    symbol = _symbol(getattr(args, 'symbol', None))
    since, as_of = parse_time(args.since), parse_time(args.as_of)
    if since > as_of:
        raise DataError('invalid_input', 'News since must be at or before as_of.')
    if as_of > utc_now():
        raise DataError('invalid_input', 'News as_of cannot be in the future.')
    limit = getattr(args, 'limit', 200)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise DataError('invalid_input', 'News limit must be an integer from 1 through 1000.')
    sort = getattr(args, 'sort', 'EARLIEST')
    if sort not in ('LATEST', 'EARLIEST'):
        raise DataError('invalid_input', 'News sort must be LATEST or EARLIEST.')
    raw_topics = getattr(args, 'topics', None)
    topics = []
    if raw_topics is not None:
        if not isinstance(raw_topics, str):
            raise DataError('invalid_input', 'News topics must be a comma-separated list of documented topic names.')
        topics = raw_topics.split(',')
        if not topics or any(topic not in TOPICS for topic in topics) or len(set(topics)) != len(topics):
            raise DataError('invalid_input', 'News topics must contain distinct documented topic names, joined by commas.')
    # The API accepts minutes, whereas article timestamps have seconds. Request
    # the entire final minute and then enforce the exact inclusive cutoff below.
    since_minute = since.astimezone(timezone.utc).replace(second=0, microsecond=0)
    try:
        end_minute = as_of.astimezone(timezone.utc).replace(second=0, microsecond=0) + timedelta(minutes=1)
    except OverflowError as exc:
        raise DataError('invalid_input', 'News cutoff is outside the supported date range.') from exc
    params = {'function': 'NEWS_SENTIMENT',
              'time_from': since_minute.strftime('%Y%m%dT%H%M'),
              'time_to': end_minute.strftime('%Y%m%dT%H%M'),
              'sort': sort, 'limit': limit}
    if symbol:
        params['tickers'] = symbol
    if topics:
        params['topics'] = ','.join(topics)
    payload = client.get_json(API, params={**params, 'apikey': required_env(client.env, 'ALPHA_VANTAGE_API_KEY')})
    retrieved = utc_now()
    _provider_error(payload)
    feed = payload.get('feed')
    if not isinstance(feed, list):
        raise DataError('invalid_response', 'Alpha Vantage news response is missing the article list.')
    data, invalid, outside, unmatched = [], 0, 0, 0
    for row in feed:
        try:
            published, item = _news_item(row)
        except (ValueError, TypeError, OverflowError):
            invalid += 1
            continue
        if symbol and not any(ticker['ticker'] == symbol for ticker in item['ticker_sentiment']):
            unmatched += 1
            continue
        if not since <= published <= as_of:
            outside += 1
            continue
        data.append(item)
    data.sort(key=lambda item: item['published_at'], reverse=(sort == 'LATEST'))
    saturated = len(feed) >= limit
    warnings = [
        'Coverage is the Alpha Vantage news collection, not every announcement or publisher.',
        'Sentiment and relevance scores are provider classifications, not this skill’s investment judgment.',
        'Publication cutoff filtering does not prove the current article text, scores, or indexing existed at that cutoff.',
    ]
    if topics:
        warnings.append('Multiple topics use AND matching: an article must cover every requested topic.')
    if saturated:
        warnings.append('The response reached the requested limit; coverage may be truncated. Narrow the time window within the request budget; this endpoint has no pagination cursor.')
    if invalid:
        warnings.append('%d malformed article record(s) were omitted.' % invalid)
    if unmatched:
        warnings.append('%d article record(s) lacked an exact requested ticker classification and were omitted; the provider symbol filter was not fully verified.' % unmatched)
    reported = payload.get('items')
    count_mismatch = False
    if reported is not None:
        if isinstance(reported, bool) or not re.fullmatch(r'\d+', str(reported)):
            count_mismatch = True
        elif int(reported) != len(feed):
            count_mismatch = True
        if count_mismatch:
            warnings.append('The provider article count is malformed or differs from the returned feed length.')
    return {
        'source': {'provider': 'alpha_vantage', 'endpoint': API, 'function': 'NEWS_SENTIMENT'},
        'query': {'symbol': symbol, 'topics': topics, 'topic_matching': 'AND',
                  'since': _iso(since), 'as_of': _iso(as_of), 'inclusive': True,
                  'provider_time_from': params['time_from'], 'provider_time_to': params['time_to'],
                  'sort': sort, 'limit': limit},
        'retrieved_at': _iso(retrieved),
        'complete': not (saturated or invalid or unmatched or count_mismatch),
        'warnings': warnings, 'provider_record_count': len(feed),
        'returned_record_count': len(data), 'outside_cutoff_count': outside,
        'invalid_record_count': invalid, 'symbol_mismatch_count': unmatched, 'data': data,
    }


def alpha_calendar(client, args):
    """Retrieve the current schedule, never a historical consensus snapshot."""
    symbol = _symbol(getattr(args, 'symbol', None))
    horizon = getattr(args, 'horizon', '3month')
    if horizon not in ('3month', '6month', '12month'):
        raise DataError('invalid_input', 'Calendar horizon must be 3month, 6month, or 12month.')
    cutoff_value = getattr(args, 'as_of', None)
    cutoff = parse_time(cutoff_value) if cutoff_value is not None else None
    if cutoff is not None and cutoff > utc_now():
        raise DataError('invalid_input', 'Calendar as_of cannot be in the future.')
    params = {'function': 'EARNINGS_CALENDAR', 'horizon': horizon}
    if symbol:
        params['symbol'] = symbol
    raw = client.get_text(API, params={**params, 'apikey': required_env(client.env, 'ALPHA_VANTAGE_API_KEY')})
    retrieved = utc_now()
    if not isinstance(raw, str):
        raise DataError('invalid_response', 'Alpha Vantage calendar response is not text.')
    raw = raw.lstrip('\ufeff')
    if raw.lstrip().startswith(('{', '[')):
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise DataError('invalid_response', 'Alpha Vantage returned malformed calendar error data.') from exc
        _provider_error(payload)
        raise DataError('invalid_response', 'Alpha Vantage returned JSON instead of a calendar CSV.')
    data = []
    try:
        rows = csv.DictReader(io.StringIO(raw, newline=''), strict=True)
        fields = rows.fieldnames
        if not fields or len(fields) != len(set(fields)) or not set(CALENDAR_FIELDS).issubset(fields):
            raise ValueError('invalid calendar header')
        count, excluded = 0, 0
        for row in rows:
            count += 1
            if None in row or any(value is None for value in row.values()):
                raise ValueError('ragged calendar row')
            item_symbol = _text(row['symbol'], required=True).strip().upper()
            if not re.fullmatch(r'[A-Z0-9][A-Z0-9.^:-]{0,31}', item_symbol):
                raise ValueError('invalid calendar symbol')
            # Additional documented columns can be added without breaking the
            # known fields. No unvalidated extra value is promoted into output.
            item = {'symbol': item_symbol, 'name': _text(row['name'], required=True),
                    'report_date': parse_date(row['reportDate']).isoformat(),
                    'fiscal_date_ending': parse_date(row['fiscalDateEnding']).isoformat() if row['fiscalDateEnding'] else None,
                    'estimate': _number(row['estimate'].strip()),
                    'currency': row['currency'].strip() or None,
                    'announcement_time': None, 'estimate_as_of': None}
            if item['currency'] and not re.fullmatch(r'[A-Z]{3}', item['currency']):
                raise ValueError('invalid currency')
            if symbol and item_symbol != symbol:
                excluded += 1
                continue
            data.append(item)
    except (csv.Error, ValueError, TypeError, DataError) as exc:
        raise DataError('invalid_response', 'Alpha Vantage returned a malformed earnings calendar; no partial schedule is reported.') from exc
    warnings = [
        'An unfiltered calendar is the provider universe, not a U.S.-only liquid-stock screen; intersect with the verified security directory.',
        'Report dates are provider estimates and can change; verify the issuer announcement.',
        'Calendar dates do not identify premarket/after-hours announcement time.',
        'The current calendar has no historical vintage or estimate timestamp; do not treat estimates as pre-announcement consensus for a historical earnings surprise.',
    ]
    late_snapshot = cutoff is not None and retrieved > cutoff
    if late_snapshot:
        warnings.append('This schedule was retrieved after the requested cutoff; it is not verified evidence available at that cutoff.')
    if excluded:
        warnings.append('The provider returned %d row(s) for other symbols; these were excluded.' % excluded)
    return {
        'source': {'provider': 'alpha_vantage', 'endpoint': API, 'function': 'EARNINGS_CALENDAR'},
        'query': {'symbol': symbol, 'horizon': horizon, 'as_of': _iso(cutoff) if cutoff else None},
        'retrieved_at': _iso(retrieved), 'point_in_time_verified': False,
        'complete': not (late_snapshot or excluded), 'warnings': warnings,
        'provider_record_count': count, 'returned_record_count': len(data),
        'data': sorted(data, key=lambda item: (item['report_date'], item['symbol'])),
    }


def run_self_test():
    import unittest
    from types import SimpleNamespace
    from unittest.mock import patch

    class Client:
        env = {'ALPHA_VANTAGE_API_KEY': 'fixture-secret-not-a-real-key'}

        def __init__(self, payload):
            self.payload, self.calls = payload, []

        def get_json(self, url, params=None, headers=None):
            self.calls.append((url, params, headers))
            return self.payload

        get_text = get_json

    class Tests(unittest.TestCase):
        def news_args(self, **changes):
            values = dict(symbol='ABC', topics=None, since='2026-09-04T08:00:30-04:00',
                          as_of='2026-09-04T09:00:15-04:00', limit=200, sort='LATEST')
            return SimpleNamespace(**{**values, **changes})

        def article(self, stamp='20260904T123000', **changes):
            return {'time_published': stamp, 'title': 'Synthetic announcement',
                    'url': 'https://example.org/announcement', 'summary': 'Fixture only.',
                    'source': 'Example issuer', 'overall_sentiment_score': '-0.1234567890123456789',
                    'ticker_sentiment': [{'ticker': 'ABC', 'relevance_score': '0.8',
                                          'ticker_sentiment_score': '0.1', 'ticker_sentiment_label': 'Neutral'}],
                    **changes}

        def calendar_args(self, **changes):
            return SimpleNamespace(**{'symbol': None, 'horizon': '3month', 'as_of': None, **changes})

        def calendar_csv(self, row='ABC,"Example, Inc.",2026-10-01,2026-09-30,1.234567890123456789,USD\n'):
            return ','.join(CALENDAR_FIELDS) + '\n' + row

        def test_exact_cutoff_and_minute_query(self):
            client = Client({'feed': [self.article(stamp) for stamp in
                            ('20260904T120029', '20260904T120030', '20260904T130015', '20260904T130016')]})
            result = alpha_news(client, self.news_args())
            self.assertEqual([item['published_at'] for item in result['data']],
                             ['2026-09-04T13:00:15Z', '2026-09-04T12:00:30Z'])
            self.assertEqual(client.calls[0][1]['time_from'], '20260904T1200')
            self.assertEqual(client.calls[0][1]['time_to'], '20260904T1301')
            self.assertEqual(result['outside_cutoff_count'], 2)

        def test_sort_order_and_provider_scores(self):
            client = Client({'feed': [self.article('20260904T123000'), self.article('20260904T120100')]})
            result = alpha_news(client, self.news_args(sort='EARLIEST'))
            self.assertEqual(result['data'][0]['published_at'], '2026-09-04T12:01:00Z')
            self.assertEqual(result['data'][0]['overall_sentiment_score'], '-0.1234567890123456789')

        def test_one_symbol_and_topic_and_semantics(self):
            client = Client({'feed': []})
            result = alpha_news(client, self.news_args(topics='technology,ipo'))
            self.assertEqual(result['query']['topic_matching'], 'AND')
            self.assertEqual(client.calls[0][1]['topics'], 'technology,ipo')
            with self.assertRaises(DataError):
                alpha_news(client, self.news_args(symbol='ABC,XYZ'))
            self.assertEqual(len(client.calls), 1)

        def test_general_news_without_symbol(self):
            client = Client({'feed': []})
            result = alpha_news(client, self.news_args(symbol=None))
            self.assertNotIn('tickers', client.calls[0][1])
            self.assertTrue(result['complete'])

        def test_filtered_news_requires_exact_requested_ticker_classification(self):
            for tickers in ([], [{'ticker': 'XYZ'}], [{'ticker': 'ABCD'}]):
                with self.subTest(tickers=tickers):
                    client = Client({'feed': [self.article(), self.article(ticker_sentiment=tickers)]})
                    result = alpha_news(client, self.news_args())
                    self.assertFalse(result['complete'])
                    self.assertEqual(result['symbol_mismatch_count'], 1)
                    self.assertEqual(result['invalid_record_count'], 0)
                    self.assertEqual(len(result['data']), 1)

        def test_unfiltered_news_keeps_other_and_unclassified_articles(self):
            client = Client({'feed': [self.article(ticker_sentiment=[]),
                                       self.article(ticker_sentiment=[{'ticker': 'XYZ'}])]})
            result = alpha_news(client, self.news_args(symbol=None))
            self.assertTrue(result['complete'])
            self.assertEqual(result['symbol_mismatch_count'], 0)
            self.assertEqual(len(result['data']), 2)

        def test_saturation_before_cutoff_filter(self):
            result = alpha_news(Client({'feed': [self.article('20260904T130016')]}), self.news_args(limit=1))
            self.assertFalse(result['complete'])
            self.assertEqual(result['data'], [])
            self.assertEqual(result['provider_record_count'], 1)

        def test_malformed_news_is_counted(self):
            result = alpha_news(Client({'feed': [self.article(), self.article(time_published='bad'),
                                                       self.article(overall_sentiment_score='NaN')]}), self.news_args())
            self.assertFalse(result['complete'])
            self.assertEqual(result['invalid_record_count'], 2)
            self.assertEqual(len(result['data']), 1)

        def test_news_publisher_url_is_safe(self):
            for url in ('javascript:alert(1)', 'https://user:password@example.org/', 'not a URL'):
                with self.subTest(url=url):
                    result = alpha_news(Client({'feed': [self.article(url=url)]}), self.news_args())
                    self.assertEqual(result['invalid_record_count'], 1)

        def test_provider_record_count_mismatch(self):
            for count in ('2', 'bad', True):
                with self.subTest(count=count):
                    self.assertFalse(alpha_news(Client({'feed': [self.article()], 'items': count}), self.news_args())['complete'])

        def test_missing_feed_is_not_empty_success(self):
            with self.assertRaises(DataError):
                alpha_news(Client({'items': '0'}), self.news_args())

        def test_quota_response_is_sanitized(self):
            client = Client({'Information': 'The fixture-secret-not-a-real-key exceeded 25 requests per day'})
            with self.assertRaises(DataError) as caught:
                alpha_news(client, self.news_args())
            self.assertNotIn('fixture-secret', str(caught.exception))
            self.assertIn('quota', str(caught.exception))
            self.assertEqual(len(client.calls), 1)

        def test_access_error_is_sanitized(self):
            for field in ('Error Message', 'Information', 'Note'):
                with self.subTest(field=field), self.assertRaises(DataError) as caught:
                    alpha_news(Client({field: 'Invalid apikey fixture-secret-not-a-real-key'}), self.news_args())
                self.assertNotIn('fixture-secret', str(caught.exception))

        def test_no_key_in_provider_result(self):
            result = alpha_news(Client({'feed': [self.article()]}), self.news_args())
            self.assertNotIn('fixture-secret', json.dumps(result))
            self.assertNotIn('apikey', json.dumps(result))

        def test_invalid_queries_make_no_requests(self):
            client = Client({'feed': []})
            for changes in ({'limit': 0}, {'limit': 1001}, {'limit': True}, {'sort': 'RELEVANCE'},
                            {'since': '2026-09-05T00:00:00Z'}, {'topics': 'technology,unknown'},
                            {'topics': 'technology,technology'}, {'symbol': '../ABC'}):
                with self.subTest(changes=changes), self.assertRaises(DataError):
                    alpha_news(client, self.news_args(**changes))
            self.assertEqual(client.calls, [])

        def test_calendar_precision_quoted_name_and_current_snapshot(self):
            client = Client(self.calendar_csv())
            result = alpha_calendar(client, self.calendar_args())
            item = result['data'][0]
            self.assertEqual(item['name'], 'Example, Inc.')
            self.assertEqual(item['estimate'], '1.234567890123456789')
            self.assertIsNone(item['announcement_time'])
            self.assertIsNone(item['estimate_as_of'])
            self.assertTrue(result['complete'])
            self.assertFalse(result['point_in_time_verified'])
            self.assertNotIn('symbol', client.calls[0][1])

        def test_calendar_missing_values_are_not_zero(self):
            result = alpha_calendar(Client(self.calendar_csv('ABC,Example,2026-10-01,,,\n')), self.calendar_args())
            self.assertIsNone(result['data'][0]['estimate'])
            self.assertIsNone(result['data'][0]['fiscal_date_ending'])
            self.assertIsNone(result['data'][0]['currency'])

        def test_calendar_blank_header_only_is_valid(self):
            result = alpha_calendar(Client(self.calendar_csv('')), self.calendar_args())
            self.assertEqual(result['data'], [])
            self.assertTrue(result['complete'])

        def test_calendar_preserves_foreign_provider_symbols_without_us_claim(self):
            result = alpha_calendar(Client(self.calendar_csv('0005.HK,Example,2026-10-01,2026-09-30,1,HKD\n')), self.calendar_args())
            self.assertEqual(result['data'][0]['symbol'], '0005.HK')
            self.assertTrue(result['complete'])
            self.assertIn('not a U.S.-only', result['warnings'][0])

        def test_future_cutoffs_make_no_requests(self):
            client = Client({'feed': []})
            with self.assertRaises(DataError):
                alpha_news(client, self.news_args(as_of='9999-12-30T00:00:00Z'))
            with self.assertRaises(DataError):
                alpha_calendar(client, self.calendar_args(as_of='9999-12-30T00:00:00Z'))
            self.assertEqual(client.calls, [])

        def test_calendar_cutoff_cannot_create_a_historical_snapshot(self):
            with patch(__name__ + '.utc_now', return_value=datetime(2026, 9, 4, 13, 1, tzinfo=timezone.utc)):
                result = alpha_calendar(Client(self.calendar_csv()), self.calendar_args(as_of='2026-09-04T13:00:00Z'))
            self.assertFalse(result['complete'])
            self.assertFalse(result['point_in_time_verified'])

        def test_calendar_does_not_leak_other_symbols(self):
            result = alpha_calendar(Client(self.calendar_csv()), self.calendar_args(symbol='XYZ'))
            self.assertEqual(result['data'], [])
            self.assertFalse(result['complete'])

        def test_calendar_rejects_ragged_and_malformed_rows(self):
            for content in ('', 'symbol,name\nABC,Example\n', self.calendar_csv('ABC,Example\n'),
                            self.calendar_csv('ABC,Example,2026-02-30,2026-01-01,1,USD\n'),
                            self.calendar_csv('ABC,Example,2026-10-01,2026-09-30,NaN,USD\n'),
                            self.calendar_csv('ABC,"unclosed,2026-10-01,2026-09-30,1,USD\n'),
                            self.calendar_csv('ABC,Example,2026-10-01,2026-09-30,1,USD,extra\n')):
                with self.subTest(content=content), self.assertRaises(DataError):
                    alpha_calendar(Client(content), self.calendar_args())

        def test_calendar_json_error_instead_of_csv(self):
            with self.assertRaises(DataError) as caught:
                alpha_calendar(Client(json.dumps({'Note': '25 requests per day fixture-secret-not-a-real-key'})), self.calendar_args())
            self.assertNotIn('fixture-secret', str(caught.exception))
            self.assertIn('quota', str(caught.exception))

        def test_calendar_invalid_horizon_makes_no_request(self):
            client = Client(self.calendar_csv())
            with self.assertRaises(DataError):
                alpha_calendar(client, self.calendar_args(horizon='1month'))
            self.assertEqual(client.calls, [])

    result = unittest.TextTestRunner(stream=sys.stderr).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    failed = sum(len(items) for items in (result.failures, result.errors, result.skipped,
                                        result.expectedFailures, result.unexpectedSuccesses))
    print('%d/%d self-test cases pass' % (result.testsRun - failed, result.testsRun))
    return result.wasSuccessful() and failed == 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', action='store_true', help='Run offline provider fixtures; no credentials or network required.')
    args = parser.parse_args(argv)
    if args.test:
        return 0 if run_self_test() else 1
    parser.print_help()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
