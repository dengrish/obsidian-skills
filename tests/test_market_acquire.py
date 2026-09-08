#!/usr/bin/env python3
"""Fixture-driven discovery from complete directories through the real screen.

No accounts, network requests, live vaults or copied production data are used.
"""
from datetime import date, datetime, time, timedelta, timezone
import contextlib
import copy
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
sys.path.insert(0, str(ROOT / 'skills/stock-research/scripts'))
import market_acquire as acquire
import market_capitalization
import market_public
import market_universe

NY = ZoneInfo('America/New_York')
AS_OF = '2024-05-01T11:30:00-04:00'
SINCE = '2024-04-30T16:00:00-04:00'
NOW = datetime.fromisoformat('2024-05-01T11:45:00-04:00')


def utc(value):
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def directory(*, padded=False):
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
    if padded:
        nasdaq = nasdaq.replace('AAA|Fixture A Common Stock|', ' AAA | Fixture A Common Stock \t|')
        other = other.replace('CCC|Fixture C Common Stock|', '\tCCC |Fixture C Common Stock |')
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
    def __init__(self, *, news_error=None, request_budget=None, history_missing=None, all_illiquid=False,
                 padded_directory=False):
        self.client = SimpleNamespace(env={'ALPACA_API_KEY': 'not-a-real-fixture-key'}, requests=[],
                                      redaction_values=('not-a-real-fixture-key',))
        self.calls = []
        self.news_error = news_error
        self.request_budget = request_budget
        self.history_missing = history_missing
        self.all_illiquid = all_illiquid
        self.padded_directory = padded_directory

    def invoke(self, client, args):
        if self.request_budget is not None and len(self.calls) >= self.request_budget:
            raise acquire.DataError('request_budget', 'Synthetic request budget exhausted.')
        self.calls.append({'operation': args.command, 'symbols': getattr(args, 'symbols', None),
                           'start': getattr(args, 'start', None), 'end': getattr(args, 'end', None)})
        client.requests.append({'url': 'https://example.invalid/fixture', 'status': 200,
                                'observed_at': NOW.isoformat()})
        if args.command == 'symbols':
            return directory(padded=self.padded_directory)
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
        news_operation = next(item for item in result['operations'] if item['operation'] == 'news')
        self.assertEqual(news_operation['error'], {'code': 'access_denied',
                                                 'message': 'Synthetic news endpoint failure.'})
        self.assertEqual(self.read(result, 'manifest'), result)

    def test_invalid_symbol_bars_do_not_discard_unrelated_discovery_candidates(self):
        import market_prices

        class MixedBarsProvider(FixtureProvider):
            def invoke(self, client, args):
                if args.command == 'symbols':
                    result = super().invoke(client, args)
                    row = result['data']['securities'][0]
                    row['symbol'] = row['source_fields']['Symbol'] = 'KEY'
                    return result
                if args.command != 'prices':
                    return super().invoke(client, args)
                self.calls.append({'operation': 'prices', 'symbols': args.symbols,
                                   'start': args.start, 'end': args.end})
                raw = {symbol: [{key: row[key] for key in ('t', 'o', 'h', 'l', 'c', 'v', 'vw')}
                                | {'n': 120} for row in rows]
                       for symbol, rows in prices(args)['data']['bars'].items()}
                if 'BBB' in raw:
                    # Synthetic counterpart of the observed zero-volume/VWAP row.
                    raw['BBB'][0].update(v=0, n=0, vw=0)
                transport = SimpleNamespace(
                    env={'ALPACA_API_KEY': 'fixture-key', 'ALPACA_SECRET_KEY': 'fixture-secret'},
                    get_json=lambda *a, **kw: {'bars': raw, 'next_page_token': None})
                with patch.object(market_prices, 'utc_now', return_value=NOW):
                    return market_prices.alpaca_bars(transport, args)

        result, _ = self.discover(MixedBarsProvider())
        self.assertFalse(result['complete'])
        filtered = self.read(result, 'prefilter')
        self.assertEqual(filtered['coverage']['declared'], 5)
        self.assertEqual(filtered['coverage']['measured'], 4)
        self.assertEqual(filtered['coverage']['passing'], 3)
        self.assertEqual([row['symbol'] for row in filtered['unavailable']], ['BBB'])
        screen = self.read(result, 'screen')
        # KEY is a public ticker here, not a credential field to erase.
        self.assertEqual({row['symbol'] for row in screen['candidates']}, {'KEY', 'CCC', 'DDD'})
        self.assertFalse(screen['complete'])
        self.assertEqual(self.read(result, 'manifest'), result)

    def test_original_padded_directories_pass_producer_universe_and_real_screen(self):
        result, _ = self.discover(FixtureProvider(padded_directory=True))
        self.assertTrue(result['complete'], result)
        self.assertEqual({row['symbol'] for row in self.read(result, 'screen')['candidates']},
                         {'AAA', 'BBB', 'CCC', 'DDD'})
        rows = {row['symbol']: row for row in self.read(result, 'directory')['data']['securities']}
        self.assertEqual(rows['AAA']['security_name'], 'Fixture A Common Stock')
        self.assertEqual(rows['AAA']['source_fields']['Security Name'], ' Fixture A Common Stock \t')
        self.assertEqual(rows['AAA']['source_fields']['Symbol'], ' AAA ')
        self.assertEqual(rows['CCC']['source_fields']['Security Name'], 'Fixture C Common Stock ')
        self.assertEqual(rows['CCC']['source_fields']['ACT Symbol'], '\tCCC ')
        self.assertEqual(self.read(result, 'manifest'), result)

    def test_real_downstream_validation_failure_preserves_public_cause_in_manifest(self):
        envelope = directory()
        envelope['data']['securities'][0]['security_name'] = 'Conflicting fixture identity'
        with patch(__name__ + '.directory', return_value=envelope):
            result, provider = self.discover()
        self.assertFalse(result['complete'])
        self.assertEqual(result['failed_stage'], 'universe')
        self.assertEqual(result['last_completed_stage'], 'directory')
        self.assertEqual(result['error'], {'code': 'invalid_input',
            'message': 'Directory normalized values disagree with their original source fields.'})
        self.assertEqual([call['operation'] for call in provider.calls], ['symbols'])
        self.assertEqual(self.read(result, 'directory')['data'], envelope['data'])
        self.assertEqual(self.read(result, 'manifest'), result)

    def test_provider_failure_is_structured_redacted_and_retained_without_fallback_roster(self):
        provider = FixtureProvider()
        diagnostic = 'Provider refused not-a-real-fixture-key and https://example.invalid/?token=unlisted-query-secret'
        def denied(client, args):
            raise acquire.DataError('access_denied', diagnostic)
        with patch.object(acquire, 'handlers', return_value={'symbols': denied}):
            result = acquire.discover(provider.client, self.vault, self.work, AS_OF, SINCE, now=NOW)
        self.assertFalse(result['complete'])
        self.assertEqual(result['failed_stage'], 'directory')
        self.assertEqual(result['error']['code'], 'access_denied')
        self.assertEqual(result['operations'][0]['error'], result['error'])
        self.assertEqual(self.read(result, 'directory')['error'], result['error'])
        self.assertEqual(self.read(result, 'manifest'), result)
        for value in [result, *(json.loads(path.read_text(encoding='utf-8'))
                               for path in Path(result['scratch']).iterdir())]:
            self.assertNotIn('not-a-real-fixture-key', json.dumps(value))
            self.assertNotIn('unlisted-query-secret', json.dumps(value))

    def test_downstream_public_diagnostic_is_redacted_before_manifest_and_library_return(self):
        import market_universe
        provider = FixtureProvider()
        provider.client.redaction_values += ('loaded-fixture-secret',)
        error = acquire.DataError('invalid_input',
                                  'Fixture rejection: not-a-real-fixture-key / loaded-fixture-secret.')
        with patch.object(market_universe, 'universe', side_effect=error):
            result, _ = self.discover(provider)
        self.assertEqual(result['error']['message'], 'Fixture rejection: [redacted] / [redacted].')
        self.assertEqual(self.read(result, 'manifest'), result)

    def test_storage_failure_keeps_prior_batches_and_hides_native_error_payload(self):
        original_save = acquire.Scratch.save
        def disk_full(scratch, name, value):
            if name == 'liquidity-proxy-0002.json':
                raise OSError('DO-NOT-ECHO-private-storage-path not-a-real-fixture-key')
            return original_save(scratch, name, value)
        with patch.object(acquire.Scratch, 'save', new=disk_full):
            result, _ = self.discover()
        self.assertFalse(result['complete'])
        self.assertEqual(result['failed_stage'], 'liquidity-proxy')
        self.assertEqual(result['last_completed_stage'], 'calendar-windows')
        self.assertEqual(result['error']['code'], 'scratch_access')
        self.assertEqual(len(result['preliminary_batches']), 1)
        self.assertTrue(Path(result['preliminary_batches'][0]['path']).is_file())
        self.assertEqual(self.read(result, 'manifest'), result)
        self.assertNotIn('DO-NOT-ECHO', json.dumps(result))
        self.assertNotIn('not-a-real-fixture-key', json.dumps(result))

    def test_manifest_storage_failure_remains_explicit_without_losing_original_failure(self):
        envelope = directory()
        envelope['data']['securities'][0]['security_name'] = 'Conflicting fixture identity'
        original_save = acquire.Scratch.save
        def disk_full(scratch, name, value):
            if name == 'manifest.json':
                raise OSError('DO-NOT-ECHO-private-storage-path')
            return original_save(scratch, name, value)
        with patch(__name__ + '.directory', return_value=envelope), patch.object(acquire.Scratch, 'save', new=disk_full):
            result, _ = self.discover()
        self.assertFalse(result['complete'])
        self.assertEqual(result['error']['code'], 'invalid_input')
        self.assertEqual(result['manifest_error']['code'], 'scratch_access')
        self.assertFalse(Path(result['outputs']['manifest']).exists())
        self.assertTrue(Path(result['outputs']['directory']).is_file())
        self.assertEqual(result['failed_stage'], 'universe')
        self.assertNotIn('DO-NOT-ECHO', json.dumps(result))

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
        for exception_type in (ValueError, TypeError, KeyError, OSError, OverflowError,
                               RuntimeError, AttributeError, IndexError):
            with self.subTest(exception_type=exception_type):
                error = exception_type('DO-NOT-ECHO-private-provider-payload')
                with patch.object(market_universe, 'prefilter', side_effect=error):
                    result, _ = self.discover()
                self.assertFalse(result['complete'])
                self.assertEqual(result['failed_stage'], 'prefilter')
                self.assertEqual(result['last_completed_stage'], 'liquidity-proxy')
                self.assertTrue(Path(result['scratch']).is_dir())
                self.assertEqual(self.read(result, 'manifest'), result)
                self.assertTrue(result['preliminary_batches'])
                self.assertTrue(result['operations'])
                self.assertEqual(result['error']['code'], 'stage_failure')
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


class IndependentEvidenceBoundaryTests(unittest.TestCase):
    """Hand-calculated cases independent of the adapter's embedded fixtures."""

    def test_liquidity_query_shards_do_not_transfer_coverage_between_symbols(self):
        cutoff = '2026-03-10T11:30:00-04:00'
        # A deliberately synthetic pair of two-minute sessions spans the real
        # New York offset change; this fixture makes no holiday assertion.
        openings = [datetime(2026, 3, day, 9, 30, tzinfo=NY) for day in (6, 9)]
        sessions = [{'date': opened.date().isoformat(), 'open_at': utc(opened),
                     'close_at': utc(opened + timedelta(minutes=2))} for opened in openings]
        cal = {'market_data': 1, 'operation': 'sessions', 'provider': 'alpaca', 'resource': 'calendar',
               'complete': True, 'query': {'start': '2026-03-06', 'end': '2026-03-10'},
               'source': {}, 'data': {'sessions': sessions}}

        def shard(symbol, opened):
            return {'market_data': 1, 'operation': 'prices', 'provider': 'alpaca', 'resource': 'bars',
                    'complete': True, 'query': {'symbols': symbol, 'start': utc(opened),
                        'end': utc(opened + timedelta(minutes=2) - timedelta(microseconds=1)),
                        'requested_end': utc(opened + timedelta(minutes=2)), 'asof': '2026-03-10',
                        'feed': 'sip', 'timeframe': '1Min', 'adjustment': 'split', 'currency': 'USD'},
                    'source': {'feed': 'sip'}, 'data': {'requested_symbols': [symbol], 'bars': {symbol: [
                        {'t': utc(opened), 'interval_start': utc(opened),
                         'interval_end': utc(opened + timedelta(minutes=1)),
                         'new_york_date': opened.date().isoformat(), 'o': 100, 'h': 100, 'l': 100,
                         'c': 100, 'vw': 100, 'v': 500000}]}}}

        first, second = shard('AAA', openings[0]), shard('BBB', openings[1])
        result = market_universe.liquidity([first, second], cal, cutoff, ['AAA', 'BBB'], session_count=2)
        for row in result['candidates']:
            self.assertFalse(row['liquidity_source_complete'])
            self.assertIsNone(row['liquidity_eligible'])
        # One observed $50m minute on each day / two days = $50m. Identical
        # overlapping responses must not create an additional $25m contribution.
        second = shard('AAA', openings[1])
        result = market_universe.liquidity([first, second, first], cal, cutoff, ['AAA'], session_count=2)
        row = result['candidates'][0]
        self.assertTrue(row['liquidity_source_complete'])
        self.assertEqual(row['average_regular_notional_lower_bound_usd'], 50000000)
        self.assertIsNone(row['average_regular_notional_usd'])
        self.assertTrue(row['liquidity_eligible'])
        self.assertFalse(row['eligibility_verified'])  # No capitalization evidence supplied.
        self.assertEqual([session['observed_minutes'] for session in row['sessions']], [1, 1])

    def test_namespaced_rss_extension_preserves_halt_filter_and_later_schedule(self):
        # RSS 2.0 explicitly permits namespaced extension elements. The parser
        # must ignore their structure without weakening known halt-field checks.
        rss = '''<rss version="2.0" xmlns:h="http://www.nasdaqtrader.com/" xmlns:media="http://search.yahoo.com/mrss/">
<channel><title>Synthetic halts</title><link>https://example.invalid/halts</link><description>Fixture</description>
<pubDate>Mon, 09 Mar 2026 13:35:00 GMT</pubDate><h:numItems>2</h:numItems>
<item><title>Old halt</title><h:HaltDate>03/06/2026</h:HaltDate><h:HaltTime>15:59:00</h:HaltTime>
<h:IssueSymbol>OLD</h:IssueSymbol><h:IssueName><![CDATA[ Société A & B ]]></h:IssueName><h:Market>NYSE American</h:Market>
<h:ResumptionDate>03/09/2026</h:ResumptionDate><h:ResumptionQuoteTime>09:31:00</h:ResumptionQuoteTime>
<media:group><media:content url="https://example.invalid/unused.png" medium="image"/></media:group></item>
<item><title>Later halt</title><h:HaltDate>03/09/2026</h:HaltDate><h:HaltTime>09:30:00 .001</h:HaltTime>
<h:IssueSymbol>LATE</h:IssueSymbol><h:IssueName>Later Company</h:IssueName><h:Market>NASDAQ</h:Market></item>
</channel></rss>'''
        client = SimpleNamespace(get_text=lambda *args, **kwargs: rss)
        args = SimpleNamespace(date=None, as_of='2026-03-09T13:30:00Z', symbols=None, limit=20)
        result = market_public.nasdaq_halts(client, args)
        self.assertTrue(result['complete'])
        self.assertFalse(result['query']['point_in_time'])
        self.assertEqual([row['symbol'] for row in result['data']['halts']], ['OLD'])
        row = result['data']['halts'][0]
        self.assertEqual(row['source_fields']['IssueName'], ' Société A & B ')
        self.assertEqual(row['scheduled_quote_resumption_at'], '2026-03-09T09:31:00-04:00')
        self.assertTrue(any('later updates' in warning for warning in result['warnings']))


class IndependentCapitalizationBoundaryTests(unittest.TestCase):
    """Reviewed synthetic issuer cases, without provider or helper fixtures."""

    cutoff = '2025-04-02T14:00:00Z'

    def plan(self):
        source = 'https://example.invalid/issuer/common-share-disclosure'
        return {'symbol': 'ABC', 'issuer_cik': '0000000017', 'share_count_basis': 'outstanding_common',
                'classes': [{'class_id': 'A', 'shares': 100000000, 'uncertainty_shares': 0,
                             'precision_basis': 'The synthetic disclosure gives an exact integer count.',
                             'observed_on': '2025-03-01', 'available_at': '2025-03-07T14:00:00Z',
                             'source_url': source,
                             'conversion': {'kind': 'same_common', 'shares_per_price_unit': 1,
                                            'available_at': '2025-03-07T14:00:00Z', 'source_url': source,
                                            'basis': 'Quoted common class A is the issuer sole common class.'}}],
                'price': {'symbol': 'ABC', 'class_id': 'A', 'usd': 30, 'currency': 'USD',
                          'adjustment': 'raw', 'as_of': '2025-04-01T20:00:00Z',
                          'available_at': '2025-04-01T20:15:00Z', 'source_url': 'https://example.invalid/raw-quote'},
                'review': {'through': '2025-04-01T20:00:00Z', 'available_at': '2025-04-01T19:00:00Z',
                           'latest_filings_checked': True, 'all_common_classes_included': True,
                           'corporate_actions_checked': True, 'unquantified_changes': False,
                           'unsupported_complexity': False, 'source_urls': [source],
                           'basis': 'Synthetic latest filings, classes and completed share changes reviewed through price time.'},
                'changes': []}

    def calculate(self, plan):
        result = market_capitalization.calculate([plan], self.cutoff)
        self.assertTrue(result['complete'], result['unresolved'])
        return result['market_caps'][0]

    def liquidity(self, cap):
        opened = datetime(2025, 4, 1, 9, 30, tzinfo=NY)
        closed = opened + timedelta(minutes=2)
        # Deliberately tiny synthetic session; both completed minute bars carry
        # $50m, enough to isolate capitalization from liquidity uncertainty.
        cal = {'market_data': 1, 'operation': 'sessions', 'provider': 'alpaca', 'resource': 'calendar',
               'complete': True, 'query': {'start': '2025-04-01', 'end': '2025-04-02'},
               'source': {}, 'data': {'sessions': [{'date': '2025-04-01', 'open_at': utc(opened),
                                                   'close_at': utc(closed)}]}}
        bars = [{'t': utc(start), 'interval_start': utc(start), 'interval_end': utc(start + timedelta(minutes=1)),
                 'new_york_date': '2025-04-01', 'o': 100, 'h': 100, 'l': 100, 'c': 100, 'vw': 100, 'v': 500000}
                for start in (opened, opened + timedelta(minutes=1))]
        prices = {'market_data': 1, 'operation': 'prices', 'provider': 'alpaca', 'resource': 'bars',
                  'complete': True, 'query': {'symbols': 'ABC', 'start': utc(opened),
                      'end': utc(closed - timedelta(microseconds=1)), 'requested_end': utc(closed),
                      'asof': '2025-04-02', 'feed': 'sip', 'timeframe': '1Min', 'adjustment': 'split', 'currency': 'USD'},
                  'source': {'feed': 'sip'}, 'data': {'requested_symbols': ['ABC'], 'bars': {'ABC': bars}}}
        return market_universe.liquidity([prices], cal, self.cutoff, ['ABC'], session_count=1,
                                         market_caps=[cap])['candidates'][0]

    def test_two_classes_noncommutative_events_and_precision_have_hand_calculated_value(self):
        plan = self.plan()
        plan['classes'][0].update(shares=30000000, uncertainty_shares=100000,
                                  precision_basis='Thirty million shares rounded within one hundred thousand.')
        plan['classes'][0]['conversion']['basis'] = 'Price is for one class A share.'
        other = copy.deepcopy(plan['classes'][0])
        other.update(class_id='B', shares=10000000, uncertainty_shares=0,
                     precision_basis='Exact disclosed class B count.')
        other['conversion'].update(kind='equivalent_common', shares_per_price_unit=0.5,
                                   basis='Each B share has the common economic participation of two class A shares.')
        plan['classes'].append(other)
        # Input order is intentionally reversed: issuance then split gives 80m
        # class A shares, not 70m. B contributes 20m priced units: 100m * $30.
        plan['changes'] = [
            {'class_id': 'A', 'kind': 'split', 'value': 2, 'effective_at': '2025-03-20T13:30:00Z',
             'available_at': '2025-03-19T14:00:00Z', 'source_url': 'https://example.invalid/two-for-one-split'},
            {'class_id': 'A', 'kind': 'share_delta', 'value': 10000000, 'effective_at': '2025-03-10T13:30:00Z',
             'available_at': '2025-03-10T18:00:00Z', 'source_url': 'https://example.invalid/completed-issuance'}]
        original = copy.deepcopy(plan)
        cap = self.calculate(plan)
        self.assertEqual(plan, original)
        self.assertEqual(cap['market_cap_usd'], 3000000000)
        self.assertEqual(cap['estimate_range_usd'], {'low': 2994000000, 'high': 3006000000})
        self.assertEqual(market_capitalization.validate_proxy_row(cap, self.cutoff), cap)
        self.assertTrue(self.liquidity(cap)['eligibility_verified'])

    def test_rounding_range_controls_threshold_including_exact_equality(self):
        cases = [(100005000, 10000, None),  # Central estimate $2.0001bn; range crosses $2bn.
                 (100005000, 5000, True),  # Declared lower precision edge equals threshold.
                 (99995000, 4999, False),  # Upper precision edge is $20 below threshold.
                 (99995000, 5000, None)]  # Upper edge equals threshold, so cannot exclude.
        for shares, uncertainty, expected in cases:
            with self.subTest(shares=shares, uncertainty=uncertainty):
                plan = self.plan()
                plan['classes'][0].update(shares=shares, uncertainty_shares=uncertainty,
                                          precision_basis='Synthetic declared count-rounding uncertainty.')
                plan['price']['usd'] = 20
                cap = self.calculate(plan)
                self.assertEqual(cap['estimate_range_usd'],
                                 {'low': (shares - uncertainty) * 20, 'high': (shares + uncertainty) * 20})
                candidate = self.liquidity(cap)
                self.assertIs(candidate['market_cap_eligible'], expected)
                self.assertIs(candidate['eligibility_verified'], expected is True)
                self.assertTrue(cap['estimate'])

    def test_common_quote_requires_its_own_class_and_ads_cannot_be_counted_twice(self):
        plans = []
        missing = self.plan()
        missing['classes'][0]['class_id'] = 'B'
        missing['classes'][0]['conversion'].update(kind='equivalent_common',
                                                  basis='B is economically equivalent to the omitted priced A class.')
        plans.append(missing)
        doubled = self.plan()
        doubled['price']['class_id'] = 'ADS'
        doubled['classes'][0]['conversion'].update(kind='adr', shares_per_price_unit=2,
                                                  basis='One ADS represents two underlying class A ordinary shares.')
        ads = copy.deepcopy(doubled['classes'][0])
        ads.update(class_id='ADS', shares=50000000)
        ads['conversion'].update(kind='same_common', shares_per_price_unit=1,
                                 basis='These depositary receipts represent the same underlying A shares.')
        doubled['classes'].append(ads)
        plans.append(doubled)
        for plan in plans:
            with self.subTest(classes=[item['class_id'] for item in plan['classes']]):
                result = market_capitalization.calculate([plan], self.cutoff)
                self.assertFalse(result['complete'])
                self.assertEqual(result['market_caps'], [])

    def test_retroactive_disclosure_and_changes_after_price_cannot_rewrite_cutoff(self):
        for kind in ('late_disclosure', 'post_price_change', 'same_day_change', 'unquantified_changes'):
            with self.subTest(kind=kind):
                plan = self.plan()
                if kind == 'late_disclosure':
                    plan['classes'][0]['available_at'] = '2025-04-02T14:00:00.001Z'
                elif kind == 'unquantified_changes':
                    plan['review'][kind] = True
                else:
                    effective = '2025-04-01T20:00:00.001Z' if kind == 'post_price_change' else '2025-03-01T23:59:00Z'
                    plan['changes'] = [{'class_id': 'A', 'kind': 'share_delta', 'value': 10000000,
                                        'effective_at': effective, 'available_at': '2025-04-01T19:00:00Z',
                                        'source_url': 'https://example.invalid/completed-share-change'}]
                result = market_capitalization.calculate([plan], self.cutoff)
                self.assertEqual(result['market_caps'], [])
                self.assertFalse(result['complete'])

    def test_freshness_uses_observation_date_and_consumer_requires_recent_price(self):
        plan = self.plan()
        plan['classes'][0].update(observed_on='2024-12-02', available_at='2025-03-31T18:00:00Z')
        self.assertEqual(self.calculate(plan)['calculation']['classes'][0]['share_age_days'], 120)
        plan['classes'][0]['observed_on'] = '2024-12-01'
        self.assertEqual(market_capitalization.calculate([plan], self.cutoff)['market_caps'], [])
        plan = self.plan()
        plan['price'].update(as_of='2025-03-31T20:00:00Z', available_at='2025-03-31T20:15:00Z')
        plan['review'].update(through='2025-03-31T20:00:00Z', available_at='2025-03-31T19:00:00Z')
        with self.assertRaises(acquire.DataError):
            self.liquidity(self.calculate(plan))

    def test_consumer_recomputes_class_basis_digest_and_rounding_range(self):
        original = self.calculate(self.plan())
        for field in ('range', 'retained_class', 'digest', 'estimate_without_plan', 'unknown_method'):
            with self.subTest(field=field):
                cap = copy.deepcopy(original)
                if field == 'range':
                    cap['estimate_range_usd']['low'] += 1
                elif field == 'retained_class':
                    cap['calculation']['plan']['classes'][0]['shares'] += 1
                elif field == 'digest':
                    cap['calculation']['input_sha256'] = '0' * 64
                else:
                    cap.pop('calculation')
                    cap.pop('estimate_range_usd')
                    if field == 'estimate_without_plan':
                        cap.pop('method')
                    else:
                        cap.pop('estimate')
                        cap['method'] = 'approximate_shares_times_price'
                with self.assertRaises(acquire.DataError):
                    self.liquidity(cap)


if __name__ == '__main__':
    unittest.main()
