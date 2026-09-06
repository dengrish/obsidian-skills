#!/usr/bin/env python3
"""Retrieve stock research evidence through official, read-only data endpoints.

Outputs one JSON object. Exit 0 means complete within the declared query scope;
exit 2 means invalid input, unavailable access or explicitly incomplete coverage.
No accounts, trades, subscriptions, files or persistent caches are created.
Use check offline first; check --live makes bounded access probes. Neither
configured keys nor a successful probe establishes comprehensive coverage.
"""

from __future__ import annotations

import argparse
from datetime import timedelta
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo

# Keep sibling imports independent of the host's working directory/import loader.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from market_http import DataError, HttpClient, redact, required_env, utc_now


REQUIRED = {
    'sec': ('SEC_USER_AGENT',),
    'nasdaq': (),
    'alpaca': ('ALPACA_API_KEY', 'ALPACA_SECRET_KEY'),
    'alpha_vantage': ('ALPHA_VANTAGE_API_KEY',),
    'fred': ('FRED_API_KEY',),
}


def parser():
    class SafeParser(argparse.ArgumentParser):
        def error(self, message):
            # Do not echo mistakenly pasted keys, arbitrary argument values, or URLs.
            raise DataError('invalid_input', 'Invalid command arguments. Use --help for the selected command.')

    root = SafeParser(description=__doc__)
    root.add_argument('--test', action='store_true', help='run offline CLI tests')
    commands = root.add_subparsers(dest='command', parser_class=SafeParser)
    check = commands.add_parser('check', help='check local setup without network access by default')
    check.add_argument('--live', action='store_true', help='probe configured sources; consumes API requests')
    check.add_argument('--source', choices=tuple(REQUIRED), help='check only this source')
    for name in ('sec-company', 'sec-facts'):
        sub = commands.add_parser(name, help='retrieve SEC filing history' if name == 'sec-company' else 'retrieve SEC XBRL facts')
        identity = sub.add_mutually_exclusive_group(required=True)
        identity.add_argument('--symbol', help='provider ticker, resolved to a company CIK')
        identity.add_argument('--cik', help='SEC company identifier')
        sub.add_argument('--as-of', required=True, help='evidence cutoff with seconds and timezone')
        sub.add_argument('--since', help='earliest filing date or timestamp; enables older-page retrieval')
        sub.add_argument('--forms', help='comma-separated filing forms')
        sub.add_argument('--max-pages', type=int, default=10, help='maximum older submission pages')
        sub.add_argument('--limit', type=int, default=1000, help='maximum returned records')
        if name == 'sec-facts':
            sub.add_argument('--concepts', help='comma-separated XBRL concepts; defaults to a small financial set')
            sub.add_argument('--taxonomy', default='us-gaap', help='XBRL taxonomy, e.g. us-gaap or ifrs-full')
    symbols = commands.add_parser('symbols', help='retrieve current Nasdaq and other-exchange security directories')
    symbols.add_argument('--symbols', help='optional comma-separated symbol filter')
    symbols.add_argument('--limit', type=int, default=20000)
    halts = commands.add_parser('halts', help='retrieve the official Nasdaq trading-halt RSS feed')
    halts.add_argument('--symbols', help='optional comma-separated symbol filter')
    halts.add_argument('--as-of', help='optional cutoff with seconds and timezone')
    halts.add_argument('--date', help='optional historical halt date, YYYY-MM-DD')
    prices = commands.add_parser('prices', help='retrieve Alpaca historical bars with an explicit feed and time window')
    prices.add_argument('--symbols', required=True, help='comma-separated provider symbols')
    prices.add_argument('--start', required=True, help='inclusive start timestamp with timezone')
    prices.add_argument('--end', required=True, help='end timestamp with timezone; daily bars use completed prior dates')
    prices.add_argument('--feed', choices=('sip', 'iex'), default='sip')
    prices.add_argument('--timeframe', choices=('1Day', '1Min'), default='1Day')
    prices.add_argument('--adjustment', choices=('raw', 'split', 'dividend', 'spin-off', 'all'), default='raw')
    prices.add_argument('--asof', help='ticker-mapping date; not a historical knowledge cutoff')
    prices.add_argument('--max-pages', type=int, default=20)
    actions = commands.add_parser('actions', help='retrieve Alpaca corporate actions by process date')
    actions.add_argument('--symbols', required=True)
    actions.add_argument('--start', required=True, help='first process date, YYYY-MM-DD')
    actions.add_argument('--end', required=True, help='last process date, YYYY-MM-DD')
    actions.add_argument('--types', help='optional comma-separated action types')
    actions.add_argument('--max-pages', type=int, default=20)
    sessions = commands.add_parser('sessions', help='retrieve Alpaca exchange-session dates and boundaries')
    sessions.add_argument('--start', required=True, help='YYYY-MM-DD')
    sessions.add_argument('--end', required=True, help='YYYY-MM-DD')
    news = commands.add_parser('news', help='retrieve a bounded provider news window')
    news.add_argument('--provider', choices=('alpha_vantage', 'alpaca'), default='alpha_vantage')
    news.add_argument('--symbol', help='one ticker only; omit for topic/general discovery')
    news.add_argument('--topics', help='comma-separated topics; multiple topics mean AND')
    news.add_argument('--since', required=True, help='inclusive start timestamp with timezone')
    news.add_argument('--as-of', required=True, help='inclusive cutoff timestamp with timezone')
    news.add_argument('--limit', type=int, help='Alpha Vantage: 1–1000, default 200; Alpaca: 1–50, default 50')
    news.add_argument('--sort', choices=('EARLIEST', 'LATEST'), default='EARLIEST')
    news.add_argument('--include-content', action='store_true', help='Alpaca only: request article bodies when available')
    earnings = commands.add_parser('earnings', help='retrieve the current Alpha Vantage earnings calendar')
    earnings.add_argument('--symbol', help='optional one-symbol filter')
    earnings.add_argument('--horizon', choices=('3month', '6month', '12month'), default='3month')
    earnings.add_argument('--as-of', help='optional historical cutoff; current calendar cannot verify its vintage')
    macro = commands.add_parser('fred-series', help='retrieve one FRED series at an explicit daily vintage')
    macro.add_argument('--series', required=True, help='FRED series ID, e.g. DGS10')
    macro.add_argument('--start', required=True, help='first observation date, YYYY-MM-DD')
    macro.add_argument('--end', required=True, help='last observation date, YYYY-MM-DD')
    macro.add_argument('--vintage-date', required=True, help='daily knowledge date; does not establish intraday availability')
    releases = commands.add_parser('fred-releases', help='retrieve FRED source release dates, not intraday release times')
    releases.add_argument('--start', required=True, help='first source release date, YYYY-MM-DD')
    releases.add_argument('--end', required=True, help='last source release date, YYYY-MM-DD')
    releases.add_argument('--release-id', type=int, help='optional one-release filter')
    for sub in (macro, releases):
        sub.add_argument('--max-pages', type=int, default=10, help='maximum observation or release-date pages')
        sub.add_argument('--limit', type=int, default=1000, help='maximum total records, 1–100000')
    for sub in commands.choices.values():
        sub.add_argument('--max-requests', type=int, default=100, help='per-command HTTP attempt budget, 1–500')
        sub.add_argument('--max-seconds', type=int, default=120, help='per-command transport budget, 1–600 seconds')
    return root


def handlers():
    # Imports work from either host and any current directory; every sibling ships together.
    from market_public import sec_company, sec_facts, nasdaq_symbols, nasdaq_halts
    from market_prices import alpaca_bars, alpaca_actions, alpaca_calendar
    from market_news import news, alpha_calendar
    from market_fred import fred_series, fred_releases
    return {
        'sec-company': sec_company, 'sec-facts': sec_facts, 'symbols': nasdaq_symbols,
        'halts': nasdaq_halts, 'prices': alpaca_bars, 'actions': alpaca_actions,
        'sessions': alpaca_calendar, 'news': news, 'earnings': alpha_calendar,
        'fred-series': fred_series, 'fred-releases': fred_releases,
    }


def check_sources(client, args):
    selected = [args.source] if args.source else list(REQUIRED)
    rows = []
    for source in selected:
        missing = []
        for name in REQUIRED[source]:
            try:
                required_env(client.env, name)
            except DataError:
                missing.append(name)
        if source == 'sec' and not missing:
            from market_public import validate_sec_credentials
            try:
                validate_sec_credentials(client.env)
            except DataError:
                missing.append('SEC_USER_AGENT')
        row = {'source': source, 'configured': not missing, 'missing_or_invalid': missing,
               'access': 'not_tested', 'coverage': 'not_established'}
        rows.append(row)
        if not args.live or missing:
            continue
        try:
            common = {'max_pages': 1, 'limit': 10}
            end = utc_now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
            if source == 'sec':
                result = handlers()['sec-company'](client, SimpleNamespace(
                    **common, cik='0000320193', symbol=None, since=None, forms=None,
                    as_of=utc_now().isoformat()))
            elif source == 'nasdaq':
                result = handlers()['symbols'](client, SimpleNamespace(symbols='AAPL', limit=10))
            elif source == 'alpaca':
                result = handlers()['prices'](client, SimpleNamespace(
                    symbols='SPY', start=(end - timedelta(days=10)).isoformat(), end=end.isoformat(),
                    timeframe='1Day', feed='sip', adjustment='raw', asof=None, max_pages=1))
            elif source == 'alpha_vantage':
                result = handlers()['earnings'](client, SimpleNamespace(symbol='IBM', horizon='3month', as_of=None))
            else:
                vintage = utc_now().astimezone(ZoneInfo('America/Chicago')).date() - timedelta(days=1)
                result = handlers()['fred-series'](client, SimpleNamespace(
                    series='DGS10', start=(vintage - timedelta(days=10)).isoformat(),
                    end=vintage.isoformat(), vintage_date=vintage.isoformat(),
                    max_pages=1, limit=10))
            row.update(access='reachable', sample_complete=result['complete'], warnings=result.get('warnings', []))
            row['scope'] = {'sec': 'company submissions only', 'nasdaq': 'symbol directories only',
                            'alpaca': 'old SIP daily bars only', 'alpha_vantage': 'earnings calendar only',
                            'fred': 'one DGS10 metadata and daily-vintage observation sample only'}[source]
        except DataError as exc:
            row.update(access='unavailable', error={'code': exc.code, 'message': str(exc)})
    return {'data': rows, 'complete': all(row['configured'] and (not args.live or row['access'] == 'reachable')
                                         for row in rows),
            'warnings': ['Configuration is not endpoint entitlement. A sample does not verify all endpoints, current data or source accuracy.',
                         'Rate budgets are per command; account quotas also apply across runs.']}


def main(argv=None, client=None):
    args = None
    env = dict(os.environ if client is None else client.env)
    try:
        args = parser().parse_args(argv)
        if args.test:
            return run_self_test()
        if args.command is None:
            raise DataError('invalid_input', 'Choose a command; use --help to see the available sources.')
        client = client or HttpClient(env, max_requests=args.max_requests, max_seconds=args.max_seconds)
        result = check_sources(client, args) if args.command == 'check' else handlers()[args.command](client, args)
        if not isinstance(result, dict) or not isinstance(result.get('complete'), bool):
            raise DataError('invalid_response', 'Provider adapter returned an invalid result.')
        result = dict(result, market_data=1, operation=args.command, requests=client.requests)
        code = 0 if result['complete'] else 2
    except DataError as exc:
        result = {'market_data': 1, 'operation': getattr(args, 'command', None), 'complete': False,
                  'error': {'code': exc.code, 'message': str(exc)},
                  'requests': client.requests if client is not None else []}
        code = 2
    except (ValueError, TypeError, KeyError, OSError, OverflowError) as exc:
        # Provider schema surprises and local errors never echo secret-bearing payloads.
        result = {'market_data': 1, 'operation': getattr(args, 'command', None), 'complete': False,
                  'error': {'code': 'invalid_response', 'message': 'Unexpected provider data or local input; no complete result was assumed.'},
                  'requests': client.requests if client is not None else []}
        code = 2
    print(json.dumps(redact(result, env), ensure_ascii=False, allow_nan=False))
    return code


def run_self_test():
    import contextlib
    import io
    import unittest
    from unittest.mock import Mock, patch

    class CliTests(unittest.TestCase):
        def call(self, args, env=None, handler_map=None):
            client = SimpleNamespace(env=env or {}, requests=[])
            output = io.StringIO()
            with contextlib.redirect_stdout(output), patch(__name__ + '.handlers', return_value=handler_map or {}):
                code = main(args, client)
            return code, json.loads(output.getvalue())

        def test_offline_check_does_not_fetch(self):
            code, result = self.call(['check'])
            self.assertEqual(code, 2)
            self.assertEqual(result['requests'], [])
            self.assertEqual(next(row for row in result['data'] if row['source'] == 'nasdaq')['configured'], True)
            self.assertTrue(all(row['access'] == 'not_tested' for row in result['data']))

        def test_configured_check_does_not_claim_live_access(self):
            code, result = self.call(['check', '--source', 'alpaca'],
                                    {'ALPACA_API_KEY': 'dummyid', 'ALPACA_SECRET_KEY': 'dummysecret'})
            self.assertEqual(code, 0)
            self.assertEqual(result['data'][0]['access'], 'not_tested')
            self.assertNotIn('dummy', json.dumps(result))

        def test_fred_missing_key_does_not_fetch(self):
            handler = Mock()
            code, result = self.call(['check', '--live', '--source', 'fred'],
                                    handler_map={'fred-series': handler})
            self.assertEqual(code, 2)
            self.assertEqual(result['data'][0]['missing_or_invalid'], ['FRED_API_KEY'])
            handler.assert_not_called()

        def test_fred_access_check_is_narrow_and_uses_a_prior_vintage(self):
            handler = Mock(return_value={'complete': True, 'data': {}, 'warnings': []})
            code, result = self.call(['check', '--live', '--source', 'fred'],
                                    {'FRED_API_KEY': 'fixture-fred-secret'}, {'fred-series': handler})
            self.assertEqual(code, 0)
            self.assertEqual(handler.call_count, 1)
            args = handler.call_args.args[1]
            self.assertEqual(args.series, 'DGS10')
            self.assertLess(args.vintage_date, utc_now().date().isoformat())
            self.assertEqual(result['data'][0]['coverage'], 'not_established')

        def test_fred_command_routes_and_redacts_provider_echo(self):
            handler = Mock(return_value={'complete': True, 'data': {'notes': 'fixture-fred-secret'}})
            code, result = self.call(['fred-series', '--series', 'DGS10', '--start', '2026-08-01',
                                     '--end', '2026-09-03', '--vintage-date', '2026-09-03'],
                                    {'FRED_API_KEY': 'fixture-fred-secret'}, {'fred-series': handler})
            self.assertEqual(code, 0)
            self.assertEqual(handler.call_args.args[1].vintage_date, '2026-09-03')
            self.assertNotIn('fixture-fred-secret', json.dumps(result))

        def test_live_probe_missing_keys_does_not_call_provider(self):
            handler = Mock()
            code, result = self.call(['check', '--live', '--source', 'alpha_vantage'],
                                    handler_map={'earnings': handler})
            self.assertEqual(code, 2)
            handler.assert_not_called()

        def test_offline_sec_contact_validation_matches_retrieval(self):
            code, result = self.call(['check', '--source', 'sec'], {'SEC_USER_AGENT': 'not-a-contact'})
            self.assertEqual(code, 2)
            self.assertEqual(result['data'][0]['missing_or_invalid'], ['SEC_USER_AGENT'])
            self.assertEqual(result['requests'], [])

        def test_live_probe_has_narrow_declared_scope(self):
            handler = Mock(return_value={'complete': True, 'data': [], 'warnings': []})
            code, result = self.call(['check', '--live', '--source', 'alpha_vantage'],
                                    {'ALPHA_VANTAGE_API_KEY': 'dummysecret'}, {'earnings': handler})
            self.assertEqual(code, 0)
            self.assertEqual(handler.call_count, 1)
            self.assertEqual(result['data'][0]['scope'], 'earnings calendar only')
            self.assertEqual(result['data'][0]['coverage'], 'not_established')

        def test_partial_provider_result_stays_incomplete(self):
            code, result = self.call(['symbols'], handler_map={'symbols': Mock(return_value={
                'complete': False, 'data': ['AAPL'], 'warnings': ['Truncated sample.']})})
            self.assertEqual(code, 2)
            self.assertEqual(result['data'], ['AAPL'])
            self.assertFalse(result['complete'])

        def test_parser_does_not_echo_pasted_keys(self):
            for args in (['news', '--apikey', 'DUMMY_PRIVATE_KEY'], ['prices', '--feed', 'DUMMY_PRIVATE_KEY']):
                code, result = self.call(args)
                self.assertEqual(code, 2)
                self.assertNotIn('DUMMY_PRIVATE_KEY', json.dumps(result))

        def test_provider_errors_and_echoes_are_redacted(self):
            key = 'DUMMY_PRIVATE_KEY'
            for handler in (Mock(side_effect=DataError('test', key)),
                            Mock(return_value={'complete': True, 'data': {'echo': key}})):
                code, result = self.call(['symbols'], {'ALPHA_VANTAGE_API_KEY': key}, {'symbols': handler})
                self.assertNotIn(key, json.dumps(result))

        def test_invalid_payload_error_is_not_echoed(self):
            code, result = self.call(['symbols'], handler_map={'symbols': Mock(side_effect=ValueError('private response'))})
            self.assertEqual(code, 2)
            self.assertNotIn('private response', json.dumps(result))

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CliTests)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    print('%d/%d self-tests passed' % (result.testsRun - len(result.failures) - len(result.errors), result.testsRun))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
