#!/usr/bin/env python3
"""Bounded, credential-redacting GET transport for market research providers.

This import library has no arbitrary-URL command and writes no files. Run
market_data.py for retrieval; --test here runs offline transport checks.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import http.client
import json
import math
import os
import re
import ssl
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request


class DataError(ValueError):
    """A public, nonsecret error code and deliberately safe explanation."""
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def utc_now():
    return datetime.now(timezone.utc)


def parse_time(value):
    if not isinstance(value, str) or not re.fullmatch(
            r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)', value):
        raise DataError('invalid_input', 'Use an ISO timestamp with seconds and an explicit timezone offset.')
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)
    except ValueError as exc:
        raise DataError('invalid_input', 'Invalid timestamp.') from exc


def parse_date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise DataError('invalid_input', 'Use a YYYY-MM-DD date.')
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise DataError('invalid_input', 'Invalid calendar date.') from exc


def required_env(env, key):
    value = env.get(key, '')
    if any(unicodedata.category(ch) == 'Cc' for ch in value):
        raise DataError('invalid_credentials', key + ' contains control characters.')
    value = value.strip()
    if not value:
        raise DataError('missing_credentials', 'Configure ' + key + ' in the selected credentials file or local environment before using this source.')
    return value


SECRET_FIELDS = {'apikey', 'api_key', 'token', 'access_token', 'secret', 'key'}
CREDENTIAL_NAMES = ('ALPACA_API_KEY', 'ALPACA_SECRET_KEY', 'ALPHA_VANTAGE_API_KEY', 'SEC_USER_AGENT', 'FRED_API_KEY')


def redact(value, env=None, *, extra_values=(), price_bars=False):
    """Sanitize payloads; only validated prices callers may opt in to ticker keys.

    The exception is confined to a normalized Alpaca envelope's data.bars map.
    Its row contents still receive ordinary credential and string redaction.
    """
    ticker_keys = False
    if (price_bars is True and isinstance(value, dict)
            and value.get('operation') == 'prices' and value.get('provider') == 'alpaca'
            and value.get('resource') == 'bars' and isinstance(value.get('data'), dict)
            and isinstance(value.get('query'), dict)):
        symbols, bars = value['data'].get('requested_symbols'), value['data'].get('bars')
        ticker_keys = (isinstance(symbols, list) and 1 <= len(symbols) <= 200
                       and all(isinstance(symbol, str) and re.fullmatch(r'[A-Z][A-Z0-9./-]{0,19}', symbol)
                               for symbol in symbols)
                       and len(set(symbols)) == len(symbols)
                       and value['query'].get('symbols') == ','.join(symbols)
                       and isinstance(bars, dict) and not set(bars) - set(symbols)
                       and all(isinstance(rows, list) and all(isinstance(row, dict) for row in rows)
                               for rows in bars.values()))
    values = [str((env or {}).get(key, '')) for key in CREDENTIAL_NAMES] + list(extra_values)
    secrets = sorted({spelling for value in values for spelling in (str(value), str(value).strip())
                      if spelling}, key=len, reverse=True)
    spellings = set()
    for secret in secrets:
        json_spellings = [json.dumps(secret, ensure_ascii=ascii_only)[1:-1] for ascii_only in (False, True)]
        spellings.update((secret, urllib.parse.quote(secret, safe=''), urllib.parse.quote_plus(secret),
                          *json_spellings, *(value.replace('/', '\\/') for value in json_spellings)))
    spellings = sorted(spellings, key=len, reverse=True)
    def clean(item, path=()):
        if isinstance(item, dict):
            symbol_map = ticker_keys and path == ('data', 'bars')
            return {clean(str(key)): ('[redacted]' if str(key).lower() in SECRET_FIELDS and not symbol_map
                                     else clean(val, path + (str(key),)))
                    for key, val in item.items()}
        if isinstance(item, (list, tuple)):
            return [clean(val, path + (index,)) for index, val in enumerate(item)]
        if not isinstance(item, str):
            return item
        for spelling in spellings:
            item = item.replace(spelling, '[redacted]')
        return re.sub(r'(?i)([?&](?:apikey|api_key|token|access_token|secret|key)=)[^&#\s]*',
                      r'\1[redacted]', item)
    return clean(value)


def allowed_url(url):
    """Only fixed provider resources; no user hosts, credentials, or redirects."""
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or parsed.username is not None or parsed.password is not None
            or parsed.fragment or parsed.port not in (None, 443) or parsed.query):
        raise DataError('unsafe_url', 'Retrieval requires an approved HTTPS provider resource.')
    patterns = {
        'www.sec.gov': r'(?:/files/company_tickers(?:_exchange)?\.json|/Archives/edgar/data/[1-9][0-9]{0,9}/[0-9]{18}/(?![^/]*\.\.)[A-Za-z0-9][A-Za-z0-9_.-]{0,199}\.(?:html?|xml))',
        'data.sec.gov': r'(?:/submissions/CIK\d{10}(?:-submissions-\d+)?\.json|/api/xbrl/companyfacts/CIK\d{10}\.json)',
        'www.nasdaqtrader.com': r'(?:/dynamic/[Ss]ym[Dd]ir/(?:nasdaqlisted|otherlisted)\.txt|/rss\.aspx)',
        'data.alpaca.markets': r'(?:/v2/stocks/bars|/v1/corporate-actions|/v1beta1/news)',
        'paper-api.alpaca.markets': r'/v2/calendar',
        'www.alphavantage.co': r'/query',
        'api.stlouisfed.org': r'/fred/(?:series(?:/observations)?|releases/dates|release/dates)',
    }
    if parsed.hostname not in patterns or not re.fullmatch(patterns[parsed.hostname], parsed.path):
        raise DataError('unsafe_url', 'This resource is outside the read-only provider allowlist.')
    return parsed.hostname


def no_redirect_handler():
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise DataError('redirect', 'Provider redirected the request; update the verified endpoint before retrying.')
    return NoRedirect()


class HttpClient:
    """One bounded command; no disk cache, proxy inheritance or key persistence."""
    def __init__(self, env=None, *, max_requests=100, max_seconds=120, max_bytes=20 * 1024 * 1024,
                 opener=None, clock=time.monotonic, sleeper=time.sleep, redaction_values=()):
        if (not isinstance(max_requests, int) or not 1 <= max_requests <= 500
                or not isinstance(max_seconds, (int, float)) or not math.isfinite(max_seconds)
                or not 1 <= max_seconds <= 600 or not 1 <= max_bytes <= 50 * 1024 * 1024):
            raise DataError('invalid_input', 'Invalid request, duration or response-size budget.')
        self.env = dict(os.environ if env is None else env)
        self.redaction_values = tuple(redaction_values)
        self.max_requests, self.max_bytes = max_requests, max_bytes
        self.clock, self.sleep = clock, sleeper
        self.deadline = clock() + max_seconds
        self.requests, self.last_request = [], {}
        self.attempts = 0
        self.opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}), no_redirect_handler(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()))

    def _budget(self):
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise DataError('request_budget', 'Retrieval exceeded its time budget; keep partial coverage explicit.')
        return remaining

    def _get(self, url, params=None, headers=None):
        host = allowed_url(url)
        params, headers = dict(params or {}), dict(headers or {})
        for key in params:
            if not isinstance(key, str) or any(ord(ch) < 32 for ch in key):
                raise DataError('invalid_input', 'Invalid query parameter name.')
        # Header credentials never go to another provider, including through an override.
        allowed_headers = {'accept', 'user-agent'}
        if host in ('data.alpaca.markets', 'paper-api.alpaca.markets'):
            allowed_headers.update(('apca-api-key-id', 'apca-api-secret-key'))
        for key, value in headers.items():
            if key.lower() not in allowed_headers or any(ord(ch) < 32 or ord(ch) == 127 for ch in str(value)):
                raise DataError('unsafe_headers', 'Unexpected request header or control character.')
        query_credentials = {key.lower() for key in params if key.lower() in SECRET_FIELDS}
        allowed_credentials = {'www.alphavantage.co': {'apikey'}, 'api.stlouisfed.org': {'api_key'}}
        if not query_credentials.issubset(allowed_credentials.get(host, set())):
            raise DataError('unsafe_credentials', 'Query credentials are not approved for this provider resource.')
        target = url + ('?' + urllib.parse.urlencode(params, doseq=True) if params else '')
        request_headers = {'User-Agent': 'obsidian-market-research/1.0', 'Accept': 'application/json,text/plain',
                           'Accept-Encoding': 'identity', **headers}
        # Space requests within a command; daily Alpha Vantage quotas remain server/account limits.
        interval = (0.2 if host.endswith('sec.gov') else 0.35 if 'alpaca.markets' in host
                    else 0.55 if host == 'api.stlouisfed.org' else 0.0)
        for retry in range(3):
            if self.attempts >= self.max_requests:
                raise DataError('request_budget', 'Request limit reached; retry only the unresolved portion.')
            remaining = self._budget()
            pause = max(0.0, self.last_request.get(host, -math.inf) + interval - self.clock())
            if pause >= remaining:
                raise DataError('request_budget', 'Insufficient time for the next rate-limited request.')
            if pause:
                self.sleep(pause)
            self.last_request[host] = self.clock()
            self.attempts += 1
            event = {'url': redact(target, self.env, extra_values=self.redaction_values),
                     'retrieved_at': utc_now().isoformat(), 'status': None}
            self.requests.append(event)
            try:
                request = urllib.request.Request(target, headers=request_headers, method='GET')
                with self.opener.open(request, timeout=min(15, self._budget())) as response:
                    event['status'] = response.status
                    if response.status != 200:
                        raise DataError('http_error', 'Provider returned an unexpected HTTP status.')
                    if response.headers.get('Content-Encoding', 'identity').lower() not in ('', 'identity'):
                        raise DataError('encoding', 'Unexpected compressed response; no decompression was attempted.')
                    length = response.headers.get('Content-Length')
                    if length is not None and (not length.isdigit() or int(length) > self.max_bytes):
                        raise DataError('response_size', 'Provider response length is invalid or exceeds the byte limit.')
                    chunks, size = [], 0
                    while True:
                        self._budget()
                        chunk = response.read1(min(65536, self.max_bytes + 1 - size))
                        self._budget()
                        if not chunk:
                            break
                        chunks.append(chunk)
                        size += len(chunk)
                        if size > self.max_bytes:
                            raise DataError('response_size', 'Provider response exceeds the byte limit.')
                    data = b''.join(chunks)
                    if length is not None and len(data) != int(length):
                        raise DataError('truncated_response', 'Provider response was shorter than its declared length.')
                    event.update(retrieved_at=utc_now().isoformat(), bytes=len(data),
                                 sha256=hashlib.sha256(data).hexdigest())
                    try:
                        return data.decode('utf-8-sig')
                    except UnicodeError as exc:
                        raise DataError('encoding', 'Provider did not return valid UTF-8 data.') from exc
            except urllib.error.HTTPError as exc:
                event['status'] = exc.code
                exc.close()  # Never print server error bodies or credential-bearing exception URLs.
                if exc.code in (401, 403):
                    raise DataError('access_denied', 'Provider denied access; check credentials and endpoint entitlement.') from None
                if exc.code == 429:
                    raise DataError('rate_limited', 'Provider quota/rate limit reached; stop this source and retry later.') from None
                no_retry = host == 'www.alphavantage.co' or (host == 'www.nasdaqtrader.com' and url.endswith('/rss.aspx'))
                if 500 <= exc.code <= 599 and retry < 2 and not no_retry:
                    if 2 ** retry >= self._budget():
                        raise DataError('request_budget', 'Insufficient time for a provider retry.') from None
                    self.sleep(2 ** retry)
                    continue
                raise DataError('http_error', 'Provider returned HTTP ' + str(exc.code) + '.') from None
            except (urllib.error.URLError, OSError, TimeoutError, http.client.HTTPException) as exc:
                # In particular, do not stringify an exception containing an API-key query.
                raise DataError('network_error', 'Provider connection failed or timed out; no result was assumed.') from None
        raise DataError('http_error', 'Provider remained unavailable after bounded retries.')

    def get_text(self, url, params=None, headers=None):
        return self._get(url, params, headers)

    def get_json(self, url, params=None, headers=None):
        def number(value):
            result = float(value)
            if not math.isfinite(result):
                raise ValueError('nonfinite')
            return result
        def constant(value):
            raise ValueError('nonfinite')
        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('duplicate object key')
                result[key] = value
            return result
        try:
            result = json.loads(self._get(url, params, headers), parse_float=number,
                                parse_constant=constant, object_pairs_hook=unique_object)
            # The JSON decoder accepts lone surrogate escapes and structures
            # too deep for downstream redaction/serialization. Reject these
            # before provider fields can escape the CLI's safe error contract.
            pending = [(result, 0)]
            while pending:
                value, depth = pending.pop()
                if isinstance(value, str):
                    value.encode('utf-8')
                elif isinstance(value, (dict, list)):
                    if depth >= 100:
                        raise ValueError('excessive JSON nesting')
                    if isinstance(value, dict):
                        for key in value:
                            key.encode('utf-8')
                        children = value.values()
                    else:
                        children = value
                    pending.extend((child, depth + 1) for child in children)
            return result
        except (ValueError, RecursionError) as exc:
            if isinstance(exc, DataError):
                raise
            raise DataError('invalid_response',
                            'Provider did not return valid, unambiguous UTF-8 JSON within supported limits.') from None


def run_self_test():
    import io
    import unittest
    from unittest.mock import Mock

    class Reply(io.BytesIO):
        def __init__(self, body=b'{}', headers=None, status=200):
            super().__init__(body)
            self.headers, self.status = headers or {}, status

    class TransportTests(unittest.TestCase):
        def client(self, responses, **kwargs):
            opener = Mock()
            opener.open.side_effect = responses
            return HttpClient(env={'ALPHA_VANTAGE_API_KEY': 'dummy+key'}, opener=opener,
                              sleeper=lambda _: None, **kwargs)

        def test_timezone_and_date_validation(self):
            self.assertEqual(parse_time('2026-09-05T09:00:00-04:00'), parse_time('2026-09-05T13:00:00Z'))
            self.assertEqual(parse_date('2024-02-29').day, 29)
            for value in ('2026-09-05T09:00:00', '2026-02-30T09:00:00Z', 'not-a-date'):
                with self.subTest(value=value), self.assertRaises(DataError):
                    parse_time(value)
            with self.assertRaises(DataError):
                parse_date('2026-02-29')

        def test_timestamp_offset_minutes_are_not_silently_normalized(self):
            for value in ('2026-09-05T09:00:00-04:99', '2026-09-05T09:00:00+00:60',
                          '2026-09-05T09:00:00+24:00'):
                with self.subTest(value=value):
                    with self.assertRaises(DataError) as error:
                        parse_time(value)
                    self.assertEqual(error.exception.code, 'invalid_input')
            self.assertEqual(parse_time('2026-09-05T09:00:00-04:59'),
                             parse_time('2026-09-05T13:59:00Z'))

        def test_credentials_are_local_and_control_safe(self):
            with self.assertRaises(DataError):
                required_env({}, 'ALPACA_API_KEY')
            with self.assertRaises(DataError):
                required_env({'ALPACA_API_KEY': 'a\r\nb'}, 'ALPACA_API_KEY')
            with self.assertRaises(DataError):
                required_env({'ALPACA_API_KEY': 'a\x85b'}, 'ALPACA_API_KEY')
            self.assertEqual(required_env({'ALPACA_API_KEY': ' abc '}, 'ALPACA_API_KEY'), 'abc')

        def test_provider_get_and_provenance(self):
            client = self.client([Reply(b'{"value":12.5}')])
            self.assertEqual(client.get_json('https://www.alphavantage.co/query',
                                            {'apikey': 'dummy+key', 'function': 'NEWS_SENTIMENT'}), {'value': 12.5})
            event = client.requests[0]
            self.assertNotIn('dummy', json.dumps(event))
            self.assertEqual(event['bytes'], 14)
            self.assertEqual(len(event['sha256']), 64)
            self.assertEqual(client.opener.open.call_args.args[0].method, 'GET')

        def test_fred_query_and_returned_text_are_redacted(self):
            client = self.client([Reply(b'{"notes":"fixture-fred-secret"}')])
            client.env = {'FRED_API_KEY': 'fixture-fred-secret'}
            result = client.get_json('https://api.stlouisfed.org/fred/series',
                                     {'series_id': 'TEST', 'api_key': 'fixture-fred-secret'})
            self.assertNotIn('fixture-fred-secret', json.dumps(client.requests))
            self.assertNotIn('fixture-fred-secret', json.dumps(redact(result, client.env)))
            self.assertIn('api_key=%5Bredacted%5D', urllib.parse.quote(client.requests[0]['url'], safe=':?=&/'))

        def test_provider_query_credentials_cannot_cross_hosts(self):
            client = self.client([])
            for url, params in (
                    ('https://data.alpaca.markets/v1beta1/news', {'api_key': 'dummy'}),
                    ('https://api.stlouisfed.org/fred/series', {'apikey': 'dummy'}),
                    ('https://www.alphavantage.co/query', {'api_key': 'dummy'})):
                with self.subTest(url=url), self.assertRaises(DataError):
                    client.get_json(url, params)
            client.opener.open.assert_not_called()

        def test_rejects_unapproved_resources_before_network(self):
            client = self.client([])
            for url in ('http://www.sec.gov/files/company_tickers.json', 'https://localhost/query',
                        'https://data.alpaca.markets/v2/orders', 'https://api.alpaca.markets/v2/account',
                        'https://user:pass@www.alphavantage.co/query', 'https://www.alphavantage.co/query?apikey=x',
                        'https://api.stlouisfed.org/fred/series/search',
                        'https://fred.stlouisfed.org/fred/series',
                        'https://api.stlouisfed.org/fred/series?api_key=x'):
                with self.subTest(url=url), self.assertRaises(DataError):
                    client.get_json(url)
            client.opener.open.assert_not_called()

        def test_raw_ownership_xml_stays_inside_exact_sec_archive(self):
            base = 'https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/'
            client = self.client([Reply(b'<ownershipDocument/>')])
            self.assertEqual(client.get_text(base + 'form4.xml'), '<ownershipDocument/>')
            client.opener.open.reset_mock()
            for tail in ('xslF345X05/form4.xml', '../form4.xml', 'form..4.xml',
                         'form4.xml?output=1', 'form4.xsl', 'form4.xml/other'):
                with self.subTest(tail=tail), self.assertRaises(DataError):
                    client.get_text(base + tail)
            client.opener.open.assert_not_called()

        def test_redirect_cannot_forward_keys(self):
            with self.assertRaises(DataError):
                no_redirect_handler().redirect_request(None, None, 302, 'redirect', {}, 'https://example.com')

        def test_sec_primary_html_allowlist_is_narrow(self):
            base = 'https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/'
            self.assertEqual(allowed_url(base + 'aapl-20260101.htm'), 'www.sec.gov')
            self.assertEqual(allowed_url(base + 'aapl_20260101.html'), 'www.sec.gov')
            for suffix in ('../private.html', 'a/filing.htm', '%2e%2e.html', 'x.htm?download=1',
                           'x.htm#fragment', '.hidden.htm', 'x..htm', 'filing.json', 'a.htm.exe'):
                with self.subTest(suffix=suffix), self.assertRaises(DataError):
                    allowed_url(base + suffix)
            for url in (base.replace('/320193/', '/0000320193/'),
                        base.replace('000032019326000001', '0000320193-26-000001'),
                        base.replace('www.sec.gov', 'data.sec.gov')):
                with self.subTest(url=url), self.assertRaises(DataError):
                    allowed_url(url + 'filing.htm')

        def test_headers_and_cross_provider_query_keys(self):
            client = self.client([])
            for headers in ({'Authorization': 'secret'}, {'User-Agent': 'a\nb'}, {'Host': 'localhost'}):
                with self.subTest(headers=headers), self.assertRaises(DataError):
                    client.get_json('https://www.sec.gov/files/company_tickers.json', headers=headers)
            with self.assertRaises(DataError):
                client.get_json('https://www.sec.gov/files/company_tickers.json', {'apikey': 'dummy+key'})

        def test_quota_and_auth_errors_do_not_retry_or_echo(self):
            for status, code in ((401, 'access_denied'), (403, 'access_denied'), (429, 'rate_limited')):
                client = self.client([urllib.error.HTTPError('https://example.com/?apikey=dummy+key', status,
                                                           'dummy+key', {}, None)])
                with self.subTest(status=status), self.assertRaises(DataError) as result:
                    client.get_json('https://www.alphavantage.co/query')
                self.assertEqual(result.exception.code, code)
                self.assertNotIn('dummy', str(result.exception))
                self.assertEqual(client.attempts, 1)

        def test_transient_retry_is_bounded(self):
            failures = [urllib.error.HTTPError('https://data.sec.gov', 503, 'unavailable', {}, None) for _ in range(3)]
            client = self.client(failures)
            with self.assertRaises(DataError):
                client.get_json('https://data.sec.gov/submissions/CIK0000320193.json')
            self.assertEqual(client.attempts, 3)

        def test_alpha_transient_error_does_not_spend_more_quota(self):
            client = self.client([urllib.error.HTTPError('https://www.alphavantage.co', 503, '', {}, None)])
            with self.assertRaises(DataError):
                client.get_json('https://www.alphavantage.co/query')
            self.assertEqual(client.attempts, 1)

        def test_halt_feed_does_not_retry_within_one_minute(self):
            client = self.client([urllib.error.HTTPError('https://www.nasdaqtrader.com/rss.aspx', 503, '', {}, None)])
            with self.assertRaises(DataError):
                client.get_text('https://www.nasdaqtrader.com/rss.aspx', {'feed': 'tradehalts'})
            self.assertEqual(client.attempts, 1)

        def test_http_protocol_errors_are_sanitized(self):
            for error in (http.client.BadStatusLine('dummy+key'), http.client.IncompleteRead(b'dummy+key')):
                client = self.client([error])
                with self.assertRaises(DataError) as result:
                    client.get_json('https://www.alphavantage.co/query')
                self.assertEqual(result.exception.code, 'network_error')
                self.assertNotIn('dummy', str(result.exception))

        def test_deep_json_is_an_incomplete_response(self):
            client = self.client([Reply(b'[' * 2000 + b'0' + b']' * 2000)])
            with self.assertRaises(DataError) as result:
                client.get_json('https://www.alphavantage.co/query')
            self.assertEqual(result.exception.code, 'invalid_response')

        def test_duplicate_json_fields_cannot_replace_provider_evidence(self):
            for payload in (b'{"cik":111,"cik":222}',
                            b'{"data":[{"close":10,"close":20}]}',
                            b'{"cik":111,"ci\\u006b":222}'):
                with self.subTest(payload=payload):
                    client = self.client([Reply(payload)])
                    with self.assertRaises(DataError) as result:
                        client.get_json('https://www.alphavantage.co/query')
                    self.assertEqual(result.exception.code, 'invalid_response')

        def test_json_strings_must_be_emittable_as_utf8(self):
            for payload in (b'{"headline":"\\ud800"}', b'{"data":["\\udfff"]}',
                            b'{"\\ud800":"value"}'):
                with self.subTest(payload=payload):
                    client = self.client([Reply(payload)])
                    with self.assertRaises(DataError) as result:
                        client.get_json('https://www.alphavantage.co/query')
                    self.assertEqual(result.exception.code, 'invalid_response')
            client = self.client([Reply(b'{"headline":"\\ud83d\\ude80"}')])
            self.assertEqual(client.get_json('https://www.alphavantage.co/query')['headline'], '\U0001f680')

        def test_json_nesting_is_safe_for_downstream_redaction(self):
            # This depth is accepted by json.loads, but was not bounded before
            # recursive output sanitization. Actual provider schemas are shallow.
            client = self.client([Reply(b'[' * 101 + b'0' + b']' * 101)])
            with self.assertRaises(DataError) as result:
                client.get_json('https://www.alphavantage.co/query')
            self.assertEqual(result.exception.code, 'invalid_response')
            client = self.client([Reply(b'[' * 100 + b'0' + b']' * 100)])
            value = client.get_json('https://www.alphavantage.co/query')
            self.assertEqual(json.dumps(redact(value)), '[' * 100 + '0' + ']' * 100)

        def test_response_bounds_encoding_and_finiteness(self):
            for reply in (Reply(b'abc', {'Content-Length': '5'}), Reply(b'\xff'),
                          Reply(b'{}', {'Content-Encoding': 'gzip'}), Reply(b'abcdef'),
                          Reply(b'NaN'), Reply(b'1e999'), Reply(b'<html>')):
                client = self.client([reply], max_bytes=5)
                with self.subTest(reply=reply), self.assertRaises(DataError):
                    client.get_json('https://www.alphavantage.co/query')

        def test_request_and_time_budget(self):
            client = self.client([Reply()], max_requests=1)
            client.get_json('https://www.alphavantage.co/query')
            with self.assertRaises(DataError):
                client.get_json('https://www.alphavantage.co/query')
            clock = Mock(side_effect=[0, 2])
            client = self.client([], clock=clock, max_seconds=1)
            with self.assertRaises(DataError):
                client.get_json('https://www.alphavantage.co/query')
            client.opener.open.assert_not_called()

        def test_nested_output_redaction(self):
            env = {'ALPHA_VANTAGE_API_KEY': 'dummy+key', 'SEC_USER_AGENT': 'Example person@example.test'}
            value = {'data': ['dummy+key', 'dummy%2Bkey', 'person Example person@example.test'],
                     'apikey': 'unknown', 'url': 'https://example.com/?token=unknown&x=2'}
            encoded = json.dumps(redact(value, env))
            self.assertNotIn('dummy', encoded)
            self.assertNotIn('person@example.test', encoded)
            self.assertNotIn('unknown', encoded)

        def test_price_ticker_keys_require_explicit_normalized_envelope_opt_in(self):
            value = {'operation': 'prices', 'provider': 'alpaca', 'resource': 'bars',
                     'query': {'symbols': 'KEY'},
                     'data': {'requested_symbols': ['KEY'], 'bars': {'KEY': []}},
                     'credentials': {'KEY': 'unknown-private-value'}}
            self.assertEqual(redact(value)['data']['bars']['KEY'], '[redacted]')
            result = redact(value, price_bars=True)
            self.assertEqual(result['data']['bars']['KEY'], [])
            self.assertEqual(result['credentials']['KEY'], '[redacted]')
            # Even an aliased copy of the same map has no exception elsewhere.
            value['other'] = value['data']['bars']
            self.assertEqual(redact(value, price_bars=True)['other']['KEY'], '[redacted]')
            self.assertEqual(redact({'KEY': 'unknown-private-value'}, price_bars=True), {'KEY': '[redacted]'})

        def test_price_ticker_rows_keep_nested_and_known_secret_redaction(self):
            value = {'operation': 'prices', 'provider': 'alpaca', 'resource': 'bars',
                     'query': {'symbols': 'KEY'}, 'data': {'requested_symbols': ['KEY'], 'bars': {'KEY': [
                         {'c': 10, 'note': 'fixture-private-value', 'nested': {'KEY': 'unknown-private-value'},
                          'url': 'https://example.invalid/?token=unknown-url-private-value'}]}}}
            result = redact(value, {'ALPACA_API_KEY': 'fixture-private-value'}, price_bars=True)
            self.assertIsInstance(result['data']['bars']['KEY'], list)
            self.assertEqual(result['data']['bars']['KEY'][0]['c'], 10)
            self.assertNotIn('private-value', json.dumps(result))

        def test_malformed_or_unrequested_price_maps_never_exempt_sensitive_fields(self):
            base = {'operation': 'prices', 'provider': 'alpaca', 'resource': 'bars',
                    'query': {'symbols': 'KEY'}, 'data': {'requested_symbols': ['KEY'], 'bars': {'KEY': []}}}
            changes = [('operation', 'symbols'), ('provider', 'untrusted'), ('resource', 'news')]
            for field, replacement in changes:
                value = json.loads(json.dumps(base)); value[field] = replacement
                self.assertEqual(redact(value, price_bars=True)['data']['bars']['KEY'], '[redacted]')
            for rows in ('unknown-private-value', {'secret': 'unknown-private-value'}, ['unknown-private-value']):
                value = json.loads(json.dumps(base)); value['data']['bars']['KEY'] = rows
                self.assertEqual(redact(value, price_bars=True)['data']['bars']['KEY'], '[redacted]')
            for symbols in ([], ['OTHER'], ['KEY', 'KEY'], ['key'], None):
                value = json.loads(json.dumps(base)); value['data']['requested_symbols'] = symbols
                self.assertEqual(redact(value, price_bars=True)['data']['bars']['KEY'], '[redacted]')
            value = json.loads(json.dumps(base)); value['query']['symbols'] = 'OTHER'
            self.assertEqual(redact(value, price_bars=True)['data']['bars']['KEY'], '[redacted]')

        def test_displaced_credentials_are_redacted_from_request_records(self):
            client = self.client([Reply()], redaction_values=('former+private-value',))
            client.get_json('https://www.alphavantage.co/query',
                            {'apikey': 'dummy+key', 'symbol': 'former+private-value'})
            self.assertNotIn('private-value', json.dumps(client.requests))
            self.assertIn('[redacted]', client.requests[0]['url'])

        def test_redaction_covers_raw_trimmed_and_encoded_credentials(self):
            secret = ' private+value '
            value = [secret, secret.strip(), urllib.parse.quote(secret, safe=''), urllib.parse.quote_plus(secret)]
            encoded = json.dumps(redact(value, extra_values=(secret,)))
            self.assertNotIn('private', encoded)

        def test_redaction_covers_json_escaped_credentials_inside_provider_text(self):
            secret = 'Test "Person" / private\\value café@example.test'
            spellings = [json.dumps(secret, ensure_ascii=ascii_only)[1:-1] for ascii_only in (False, True)]
            spellings += [value.replace('/', '\\/') for value in spellings]
            value = {'notes': ['Embedded JSON: {"echo": "' + value + '"}' for value in spellings]}
            encoded = json.dumps(redact(value, {'SEC_USER_AGENT': secret}))
            self.assertNotIn('private', encoded)
            self.assertNotIn('example.test', encoded)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TransportTests)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    print('%d/%d self-tests passed' % (result.testsRun - len(result.failures) - len(result.errors), result.testsRun))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', action='store_true', help='run offline transport tests')
    args = parser.parse_args()
    if args.test:
        raise SystemExit(run_self_test())
    parser.print_help()
