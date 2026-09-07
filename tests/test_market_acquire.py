#!/usr/bin/env python3
"""Fixture-driven discovery from complete directories through the real screen.

No accounts, network requests, live vaults or copied production data are used.
"""
from datetime import date, datetime, time, timedelta, timezone
import contextlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/market-research/scripts'))
import market_acquire as acquire
import market_public

NY = ZoneInfo('America/New_York')
AS_OF = '2024-05-01T11:30:00-04:00'
SINCE = '2024-04-30T16:00:00-04:00'
NOW = datetime.fromisoformat('2024-05-01T11:45:00-04:00')


def utc(value):
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def directory():
    nasdaq = ('Symbol|Security Name|Market Category|Test Issue|Round Lot Size|ETF\n'
              'AAA|Fixture A Common Stock|Q|N|100|N\n'
              'BBB|Fixture B Common Stock|Q|N|100|N\n'
              'DDD|Fixture D Ordinary Shares|Q|N|100|N\n'
              'LOW|Thin Fixture Common Stock|Q|N|100|N\n'
              'PREF|Fixture Preferred Stock|Q|N|100|N\n'
              'File Creation Time: 0430202421:31|||||\n')
    other = ('ACT Symbol|Security Name|Exchange|ETF|Round Lot Size|Test Issue\n'
             'CCC|Fixture C Common Stock|N|N|100|N\n'
             'FUND|Fixture Fund|N|Y|100|N\n'
             'File Creation Time: 0430202421:31|||||\n')
    rows, files = [], []
    for name, raw in (('nasdaqlisted.txt', nasdaq), ('otherlisted.txt', other)):
        securities, creation = market_public._directory(raw, name)
        rows.extend(securities)
        files.append(creation)
    return {'market_data': 1, 'operation': 'symbols', 'provider': 'nasdaq', 'resource': 'symbols',
            'complete': True, 'query': {'symbols': [], 'scope': 'current_directory'},
            'data': {'files': files, 'securities': rows}, 'warnings': []}


def calendar(args):
    first, last = date.fromisoformat(args.start), date.fromisoformat(args.end)
    sessions = []
    while first <= last:
        if first.weekday() < 5:
            sessions.append({'date': first.isoformat(),
                             'open_at': utc(datetime.combine(first, time(9, 30), NY)),
                             'close_at': utc(datetime.combine(first, time(16), NY))})
        first += timedelta(days=1)
    return {'market_data': 1, 'operation': 'sessions', 'provider': 'alpaca', 'resource': 'calendar',
            'complete': True, 'query': {'start': args.start, 'end': args.end},
            'source': {'url': 'https://paper-api.alpaca.markets/v2/calendar'},
            'data': {'sessions': sessions}, 'warnings': []}


def prices(args):
    beginning, ending = datetime.fromisoformat(args.start), datetime.fromisoformat(args.end)
    symbols = args.symbols.split(',')
    bars = {}
    for symbol in symbols:
        rows, day = [], beginning.astimezone(NY).date()
        while day <= ending.astimezone(NY).date():
            opened = datetime.combine(day, time.min, NY)
            closed = datetime.combine(day + timedelta(days=1), time.min, NY)
            if day.weekday() < 5 and beginning <= opened and closed <= ending:
                growth = 0.0002 if symbol == 'SPY' else 0.001
                price = 100 * (1 + growth) ** (day - date(2023, 1, 1)).days
                rows.append({'t': utc(opened), 'interval_start': utc(opened), 'interval_end': utc(closed),
                             'new_york_date': day.isoformat(), 'o': price, 'c': price,
                             'h': price, 'l': price, 'vw': price, 'v': 1000 if symbol == 'LOW' else 1000000})
            day += timedelta(days=1)
        bars[symbol] = rows
    return {'market_data': 1, 'operation': 'prices', 'provider': 'alpaca', 'resource': 'bars',
            'complete': True, 'query': {'symbols': args.symbols, 'start': args.start, 'end': args.end,
                                      'requested_end': args.end, 'asof': args.asof, 'timeframe': '1Day',
                                      'feed': 'sip', 'adjustment': 'split', 'currency': 'USD'},
            'source': {'url': 'https://data.alpaca.markets/v2/stocks/bars', 'feed': 'sip'},
            'data': {'bars': bars, 'requested_symbols': symbols}, 'warnings': []}


class FixtureProvider:
    def __init__(self, *, news_error=None, request_budget=None, history_missing=None, all_illiquid=False):
        self.client = SimpleNamespace(env={'ALPACA_API_KEY': 'not-a-real-fixture-key'}, requests=[],
                                      redaction_values=('not-a-real-fixture-key',))
        self.calls = []
        self.news_error = news_error
        self.request_budget = request_budget
        self.history_missing = history_missing
        self.all_illiquid = all_illiquid

    def invoke(self, client, args):
        if self.request_budget is not None and len(self.calls) >= self.request_budget:
            raise acquire.DataError('request_budget', 'Synthetic request budget exhausted.')
        self.calls.append({'operation': args.command, 'symbols': getattr(args, 'symbols', None),
                           'start': getattr(args, 'start', None), 'end': getattr(args, 'end', None)})
        client.requests.append({'url': 'https://example.invalid/fixture', 'status': 200,
                                'observed_at': NOW.isoformat()})
        if args.command == 'symbols':
            return directory()
        if args.command == 'sessions':
            return calendar(args)
        if args.command == 'news':
            if self.news_error:
                raise acquire.DataError(self.news_error, 'Synthetic news endpoint failure.')
            return {'market_data': 1, 'operation': 'news', 'provider': 'alpaca', 'resource': 'news',
                    'complete': True, 'query': {'since': args.since, 'as_of': args.as_of},
                    'data': [], 'warnings': []}
        result = prices(args)
        if self.all_illiquid:
            for rows in result['data']['bars'].values():
                for row in rows:
                    row['v'] = 1000
        if self.history_missing and (NOW - datetime.fromisoformat(args.start)).days > 100:
            result['data']['bars'].pop(self.history_missing, None)
            result['complete'] = False
        return result

    def handlers(self):
        return {operation: self.invoke for operation in ('symbols', 'sessions', 'news', 'prices')}


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='.market-acquire-tests-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.vault, self.work = self.base / 'vault', self.base / '.obsidian-skills-tmp-fixture'
        self.vault.mkdir()
        self.work.mkdir()
        (self.vault / '.obsidian').mkdir()

    def discover(self, provider=None, **kwargs):
        provider = provider or FixtureProvider()
        with patch.object(acquire, 'handlers', side_effect=provider.handlers):
            result = acquire.discover(provider.client, self.vault, self.work, AS_OF, SINCE,
                                      batch_size=2, now=NOW, **kwargs)
        return result, provider

    def read(self, result, name):
        return json.loads(Path(result['outputs'][name]).read_text(encoding='utf-8'))

    def test_directory_prefilter_histories_and_real_screen_work_end_to_end(self):
        result, provider = self.discover()
        self.assertTrue(result['complete'], result)
        screen = self.read(result, 'screen')
        self.assertTrue(screen['complete'])
        self.assertEqual({row['symbol'] for row in screen['candidates']}, {'AAA', 'BBB', 'CCC', 'DDD'})
        calls = [call for call in provider.calls if call['operation'] == 'prices']
        self.assertTrue(any((NOW - datetime.fromisoformat(call['start'])).days < 100 for call in calls))
        self.assertTrue(any((NOW - datetime.fromisoformat(call['start'])).days > 360 for call in calls))
        histories = [call for call in calls if (NOW - datetime.fromisoformat(call['start'])).days > 360]
        self.assertTrue(all('SPY' in call['symbols'].split(',') for call in histories))
        self.assertFalse(any('LOW' in call['symbols'].split(',') for call in histories))
        filtered = self.read(result, 'prefilter')
        self.assertEqual(len(filtered['required_sessions']), 20)
        self.assertEqual(result['liquidity_start'][:10], filtered['required_sessions'][0])
        for batch in result['preliminary_batches']:
            envelope = json.loads(Path(batch['path']).read_text(encoding='utf-8'))
            self.assertTrue(all(len(rows) == 20 for rows in envelope['data']['bars'].values()))
        self.assertEqual(list(self.vault.iterdir()), [self.vault / '.obsidian'])
        self.assertEqual(self.read(result, 'manifest'), result)

    def test_news_entitlement_failure_keeps_accessible_price_screen_but_coverage_partial(self):
        result, provider = self.discover(FixtureProvider(news_error='access_denied'))
        self.assertFalse(result['complete'])
        self.assertIn('screen', result['outputs'])
        self.assertTrue(self.read(result, 'screen')['complete'])
        self.assertFalse(self.read(result, 'news')['complete'])
        self.assertTrue(any(call['operation'] == 'prices' for call in provider.calls))
        self.assertEqual(result['stopped_sources'].get('alpaca:news'), 'access_denied')

    def test_news_outage_does_not_suppress_price_access(self):
        result, provider = self.discover(FixtureProvider(news_error='network_error'))
        self.assertFalse(result['complete'])
        self.assertTrue(self.read(result, 'screen')['complete'])
        self.assertTrue(any(call['operation'] == 'prices' for call in provider.calls))

    def test_partial_budget_preserves_full_directory_and_unresolved_security_ids(self):
        result, provider = self.discover(FixtureProvider(request_budget=4))
        self.assertFalse(result['complete'])
        self.assertEqual(len(provider.calls), 4)
        self.assertEqual(result['stopped_sources'].get('alpaca'), 'request_budget')
        original = self.read(result, 'directory')
        self.assertEqual({row['symbol'] for row in original['data']['securities']},
                         {'AAA', 'BBB', 'CCC', 'DDD', 'LOW', 'PREF', 'FUND'})
        self.assertEqual({row['symbol'] for row in self.read(result, 'universe')['universe']['instruments']},
                         {'AAA', 'BBB', 'CCC', 'DDD', 'LOW'})
        filtered = self.read(result, 'prefilter')
        requested = {symbol for call in provider.calls if call['operation'] == 'prices'
                     for symbol in call['symbols'].split(',')}
        missing = {'AAA', 'BBB', 'CCC', 'DDD', 'LOW'} - requested
        self.assertEqual({row['symbol'] for row in filtered['unavailable']}, missing)
        self.assertEqual(filtered['coverage']['unavailable'], len(missing))
        self.assertFalse(filtered['complete'])
        self.assertFalse(result['history_batches'])

    def test_partial_history_is_missing_coverage_not_a_smaller_successful_universe(self):
        result, _ = self.discover(FixtureProvider(history_missing='DDD'))
        self.assertFalse(result['complete'])
        screen = self.read(result, 'screen')
        self.assertFalse(screen['complete'])
        self.assertIn('DDD', json.dumps(screen))
        self.assertGreater(screen['coverage']['unavailable'], 0)

    def test_complete_zero_passes_are_empty_eligibility_not_missing_histories(self):
        result, provider = self.discover(FixtureProvider(all_illiquid=True))
        self.assertTrue(result['complete'], result)
        self.assertTrue(result['eligibility_empty'])
        self.assertFalse(result['history_batches'])
        self.assertFalse(self.read(result, 'prefilter')['batches'])
        self.assertNotIn('screen', result['outputs'])
        self.assertEqual(result['coverage_basis'],
                         'complete preliminary eligibility assessment; no full-history screen required')
        self.assertIn('outside the checked eligibility rules', result['reason'])
        self.assertFalse(any(call['operation'] == 'prices'
                             and (NOW - datetime.fromisoformat(call['start'])).days > 360
                             for call in provider.calls))

    def test_empty_eligibility_with_failed_news_still_has_partial_overall_coverage(self):
        result, _ = self.discover(FixtureProvider(all_illiquid=True, news_error='access_denied'))
        self.assertFalse(result['complete'])
        self.assertTrue(result['eligibility_empty'])
        self.assertFalse(self.read(result, 'news')['complete'])

    def test_scratch_artifacts_are_private_exclusive_and_never_contain_credentials(self):
        result, _ = self.discover()
        root = Path(result['scratch'])
        self.assertTrue(root.is_relative_to(self.work))
        self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
        for file in root.iterdir():
            self.assertTrue(file.is_file())
            self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)
            self.assertNotIn('not-a-real-fixture-key', file.read_text(encoding='utf-8'))
        self.assertNotIn('not-a-real-fixture-key', json.dumps(result))

    def test_saved_input_bound_matches_the_screen_reader(self):
        scratch = acquire.Scratch(self.work, self.vault)
        with patch.object(acquire, 'MAX_INPUT_BYTES', 16):
            with self.assertRaisesRegex(ValueError, 'screen input byte bound'):
                scratch.save('too-large.json', {'payload': 'more than sixteen bytes'})
        self.assertEqual(list(scratch.root.iterdir()), [])

    def test_benchmark_slots_preserve_every_symbol_without_oversized_requests(self):
        scratch = acquire.Scratch(self.work, self.vault)
        provider = FixtureProvider()
        run = acquire.Acquisition(provider.client)
        names = ['X%03d' % index for index in range(200)]
        with patch.object(acquire, 'handlers', side_effect=provider.handlers):
            _, attempted = acquire._batches(run, {'batches': [names]}, '2024-04-30T00:00:00-04:00',
                                             AS_OF, '2024-05-01', scratch, 'history', ('SPY',))
        self.assertEqual([len(call['symbols'].split(',')) for call in provider.calls], [200, 2])
        self.assertEqual([name for row in attempted for name in row['symbols']], names)
        self.assertEqual(len({row['path'] for row in attempted}), 2)

    def test_scratch_replacement_during_write_never_returns_a_false_output_path(self):
        scratch = acquire.Scratch(self.work, self.vault)
        displaced = self.work / 'displaced'
        original_fsync = os.fsync
        def swap(descriptor):
            original_fsync(descriptor)
            scratch.root.rename(displaced)
            scratch.root.mkdir()
        with patch.object(acquire.os, 'fsync', side_effect=swap):
            with self.assertRaisesRegex(ValueError, 'scratch changed during publication'):
                scratch.save('evidence.json', {'fixture': True})
        self.assertEqual(json.loads((displaced / 'evidence.json').read_text(encoding='utf-8')), {'fixture': True})
        self.assertEqual(list(scratch.root.iterdir()), [])

    def test_later_stage_failure_keeps_manifest_paths_operations_and_no_payload(self):
        import market_universe
        provider = FixtureProvider()
        with patch.object(market_universe, 'prefilter', side_effect=ValueError('DO-NOT-ECHO-private-provider-payload')):
            result, _ = self.discover(provider)
        self.assertFalse(result['complete'])
        self.assertEqual(result['failed_stage'], 'prefilter')
        self.assertEqual(result['last_completed_stage'], 'liquidity-proxy')
        self.assertTrue(Path(result['scratch']).is_dir())
        self.assertEqual(self.read(result, 'manifest'), result)
        self.assertTrue(result['preliminary_batches'])
        self.assertTrue(result['operations'])
        self.assertNotIn('DO-NOT-ECHO', json.dumps(result))

    def test_oversized_duplicate_input_retains_full_measured_screen_and_original_batches(self):
        original_save = acquire.Scratch.save
        def bounded_save(scratch, name, value):
            if name == 'screen-input.json':
                raise acquire.ArtifactTooLarge('Synthetic aggregate boundary.')
            return original_save(scratch, name, value)
        with patch.object(acquire.Scratch, 'save', new=bounded_save):
            result, _ = self.discover()
        self.assertFalse(result['complete'])
        self.assertTrue(result['price_screen_complete'])
        self.assertFalse(result['comparison_input_available'])
        self.assertIn('128 MiB', result['assembly_limitation'])
        self.assertNotIn('screen_input', result['outputs'])
        self.assertEqual({row['symbol'] for row in self.read(result, 'screen')['candidates']},
                         {'AAA', 'BBB', 'CCC', 'DDD'})
        self.assertTrue(all(Path(row['path']).is_file() for row in result['history_batches']))
        self.assertEqual(self.read(result, 'manifest'), result)

    def test_invalid_completion_types_never_become_truthy_success(self):
        provider = FixtureProvider()
        with patch.object(acquire, 'handlers', return_value={'symbols': lambda c, a: {'complete': 'false'}}):
            result = acquire.Acquisition(provider.client).fetch(['symbols'])
        self.assertIs(result['complete'], False)
        self.assertEqual(result['error']['code'], 'invalid_response')

    def test_invalid_cli_arguments_and_repeated_credential_paths_never_echo_values(self):
        base = ['discover', '--vault', str(self.vault), '--work-dir', str(self.work),
                '--as-of', AS_OF, '--news-since', SINCE]
        secret = 'DO-NOT-ECHO-pasted-token'
        for tail in (['--unknown-flag', secret], ['--batch-size', secret],
                     ['--credentials-file', secret, '--credentials-file', secret + '-two']):
            stdout, stderr = io.StringIO(), io.StringIO()
            with self.subTest(tail=tail), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                with patch.object(acquire, 'load_credentials') as loader:
                    code = acquire.main(base + tail)
            self.assertEqual(code, 2)
            self.assertFalse(json.loads(stdout.getvalue())['complete'])
            self.assertNotIn(secret, stdout.getvalue() + stderr.getvalue())
            loader.assert_not_called()
            self.assertEqual(stderr.getvalue(), '')


if __name__ == '__main__':
    unittest.main()
