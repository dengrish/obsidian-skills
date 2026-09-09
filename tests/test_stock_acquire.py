#!/usr/bin/env python3
"""Offline full-adapter regressions for explicitly nominated stock acquisition."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/stock-research/scripts'))
import stock_acquire as acquire
import market_http
import market_prices
import market_estimates


class Response:
    status = 200
    headers = {}

    def __init__(self, payload):
        self.data = io.BytesIO(json.dumps(payload).encode())

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read1(self, size):
        return self.data.read(size)


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='.stock-acquire-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = self.root / 'vault'; self.vault.mkdir()
        self.work = self.root / '.obsidian-skills-tmp-fixture'; self.work.mkdir()
        self.path = self.work / 'nominees.json'
        self.now = datetime(2024, 5, 1, 16, 0, 0, 400000, timezone.utc)
        self.monotonic = 100.0
        self.seen, self.failures = [], {}
        self.secret = 'synthetic-paid-credential'
        for module in (market_http, market_prices, market_estimates):
            patcher = patch.object(module, 'utc_now', side_effect=lambda: self.now)
            patcher.start(); self.addCleanup(patcher.stop)

    def item(self, symbol, estimates=False):
        return {'symbol': symbol, 'class_id': 'A', 'identity_source_url': 'https://example.com/filing',
                'identity_available_at': '2024-04-30T17:00:00Z', 'reason': 'Verified feed nominee',
                'origins': [{'kind': 'feed', 'source': 'Investments/Sources/X/account.md; https://x.com/i/web/status/1234567890123456789',
                             'available_at': '2024-04-30T18:00:00Z'}],
                'estimates': [{'period': '2024-11-30', 'horizon': 'fiscal quarter',
                              'reason': 'Explicitly identified next reported quarter'}] if estimates else []}

    def sleep(self, seconds):
        self.now += timedelta(seconds=seconds)
        self.monotonic += seconds

    def open(self, request, timeout=None):
        url = request.full_url
        endpoint = url.split('?', 1)[0]
        params = {key: values[0] for key, values in parse_qs(urlparse(url).query).items()}
        self.seen.append((endpoint, params))
        failure = self.failures.get(endpoint)
        if isinstance(failure, list):
            failure = failure.pop(0) if failure else None
        if failure:
            raise HTTPError(url, failure, 'fixture failure', {}, io.BytesIO())
        if endpoint == market_prices.CALENDAR_URL:
            day, last = acquire.parse_date(params['start']), acquire.parse_date(params['end'])
            payload = []
            while day <= last:
                if day.weekday() < 5:
                    payload.append({'date': day.isoformat(), 'open': '09:30', 'close': '16:00'})
                day += timedelta(days=1)
        elif endpoint == market_prices.BARS_URL:
            end = acquire.parse_time(params['end'])
            bar = {'t': acquire.history._iso(end - timedelta(minutes=1)), 'o': 30, 'h': 31,
                   'l': 29, 'c': 30, 'v': 1000, 'n': 100, 'vw': 30}
            payload = {'bars': {symbol: [deepcopy(bar)] for symbol in params['symbols'].split(',')},
                       'next_page_token': None}
        elif params.get('function') == 'EARNINGS_ESTIMATES':
            payload = {'symbol': params['symbol'], 'estimates': [
                {'date': '2024-11-30', 'horizon': 'fiscal quarter', 'eps_estimate_average': '2.50', 'currency': 'USD'},
                {'date': '2025-02-28', 'horizon': 'fiscal quarter', 'eps_estimate_average': '2.75', 'currency': 'USD'}]}
        else:
            self.fail('Unexpected provider endpoint; targeted acquisition must not discover assets.')
        return Response(payload)

    def run_acquire(self, items=None, **kwargs):
        if items is not None:
            self.path.write_text(json.dumps(items, ensure_ascii=False), encoding='utf-8')
        client = acquire.HttpClient({'ALPACA_API_KEY': self.secret, 'ALPACA_SECRET_KEY': 'fixture-secret',
                                     'ALPHA_VANTAGE_API_KEY': self.secret}, opener=self,
                                   clock=lambda: self.monotonic, sleeper=self.sleep)
        return acquire.acquire(self.vault, self.path, self.work, client=client,
            clock=lambda: self.now, sleep=self.sleep, **kwargs)

    def test_offline_plan_has_no_network_or_writes_or_credentials(self):
        items = [self.item('S%02d' % n, estimates=True) for n in range(13)]
        result = self.run_acquire(items)
        self.assertFalse(result['executed'])
        self.assertEqual(result['target_count'], 13)
        self.assertEqual(self.seen, [])
        self.assertEqual(list(self.vault.iterdir()), [])
        self.assertEqual(list(self.work.iterdir()), [self.path])
        self.assertIsNone(result['ready_to_freeze_after'])
        output = io.StringIO()
        with patch.object(acquire, 'HttpClient', side_effect=AssertionError('offline client')):
            with patch.object(acquire, 'load_credentials', side_effect=AssertionError('offline credentials')):
                with patch('sys.stdout', output):
                    self.assertEqual(acquire.main(['--vault', str(self.vault), '--plan', str(self.path),
                                                  '--work-dir', str(self.work)]), 0)

    def test_all_65_explicit_nominees_share_calendar_and_one_attempt_ledger(self):
        result = self.run_acquire([self.item('S%02d' % n) for n in range(65)], execute=True)
        self.assertTrue(result['complete'])
        self.assertEqual([row['symbol'] for row in result['targets']], ['S%02d' % n for n in range(65)])
        self.assertEqual(len(self.seen), 4)
        self.assertEqual([len(params['symbols'].split(',')) for endpoint, params in self.seen
                          if endpoint == market_prices.BARS_URL], [30, 30, 5])
        self.assertEqual(result['budget']['http_attempts'], 4)
        self.assertEqual(len(result['requests']), 4)
        self.assertEqual(result['budget']['memoized_requests'], 2)
        ready = acquire.parse_time(result['ready_to_freeze_after'])
        self.assertLessEqual(ready, self.now)
        self.assertTrue(all(acquire.parse_time(row['price']['available_at']) <= ready.replace(microsecond=0)
                            for row in result['prices']))
        self.assertEqual(result['continuation'], [])
        self.assertNotIn(self.secret, (Path(result['scratch']) / 'result.json').read_text(encoding='utf-8'))
        before = len(self.seen)
        replay = self.run_acquire(execute=True)
        self.assertTrue(replay['complete'])
        self.assertEqual(len(self.seen), before)
        self.assertEqual(replay['budget']['http_attempts'], 0)

    def test_global_budget_covers_retries_calendar_and_both_providers(self):
        self.failures[market_prices.BARS_URL] = [503, None]
        result = self.run_acquire([self.item('S%02d' % n, estimates=True) for n in range(35)],
                                  execute=True, max_requests=3, max_estimate_calls=20)
        self.assertFalse(result['complete'])
        self.assertEqual(result['budget']['http_attempts'], 3)
        self.assertEqual(len(self.seen), 3)
        self.assertEqual([event['status'] for event in result['requests']], [200, 503, 200])
        self.assertEqual(sum(row['status'] == 'selected' for row in result['prices']), 30)
        self.assertTrue(any(row.get('capture_error') == 'request_budget' for row in result['prices']))
        self.assertTrue(any(row.get('error_code') == 'request_budget' for row in result['estimates']))
        self.assertIsNotNone(result['ready_to_freeze_after'])
        continuation = json.loads(Path(result['continuation_plan']).read_text(encoding='utf-8'))
        self.assertEqual(len(continuation), 35)
        self.assertEqual(sum(endpoint == market_prices.BARS_URL for endpoint, _ in self.seen), 2)

    def test_estimate_periods_share_a_symbol_call_and_global_unique_call_limit(self):
        items = [self.item('S%02d' % n, estimates=True) for n in range(13)]
        items[0]['estimates'].append({'period': '2025-02-28', 'horizon': 'fiscal quarter', 'reason': 'Next fiscal quarter'})
        result = self.run_acquire(items, execute=True, max_estimate_calls=11)
        self.assertEqual(result['budget']['http_attempts'], 13)
        self.assertEqual(result['budget']['estimate_symbol_calls'], 11)
        self.assertEqual(sum(row['status'] == 'captured' for row in result['estimates']), 12)
        self.assertEqual(sum(row['status'] == 'budget_deferred' for row in result['estimates']), 2)
        self.assertEqual(len([params for _, params in self.seen if params.get('symbol') == 'S00']), 1)
        previous = len(self.seen)
        retry = self.run_acquire(execute=True, max_estimate_calls=11)
        self.assertTrue(retry['complete'])
        self.assertEqual(len(self.seen) - previous, 2)

    def test_alpaca_access_failure_does_not_block_estimates_or_repeat_bars(self):
        self.failures[market_prices.BARS_URL] = 403
        result = self.run_acquire([self.item('S%02d' % n, estimates=n == 0) for n in range(35)], execute=True)
        self.assertEqual(result['budget']['http_attempts'], 3)
        self.assertEqual(sum(endpoint == market_prices.BARS_URL for endpoint, _ in self.seen), 1)
        self.assertEqual(result['estimates'][0]['status'], 'captured')
        self.assertTrue(all(row.get('capture_error') == 'access_denied' for row in result['prices']))

    def test_estimate_quota_cooldown_survives_new_execution_without_paid_retries(self):
        self.failures['https://www.alphavantage.co/query'] = 429
        items = [self.item('S%02d' % n, estimates=True) for n in range(13)]
        result = self.run_acquire(items, execute=True, max_estimate_calls=20)
        self.assertTrue(result['cooldown']['active'])
        self.assertEqual(result['budget']['http_attempts'], 3)
        previous = len(self.seen)
        repeated = self.run_acquire(execute=True, max_estimate_calls=20)
        self.assertEqual(len(self.seen), previous)
        self.assertTrue(all(row['status'] == 'cooldown' for row in repeated['estimates']))

    def test_fixed_cutoff_keeps_late_prices_and_estimates_future_only_on_retry(self):
        cutoff = acquire.history._iso(self.now - timedelta(seconds=1))
        result = self.run_acquire([self.item('AAA', estimates=True)], execute=True, as_of=cutoff)
        self.assertFalse(result['complete'])
        self.assertEqual(result['as_of'], cutoff)
        self.assertIsNone(result['ready_to_freeze_after'])
        self.assertEqual(result['prices'][0]['status'], 'future_only')
        self.assertEqual(result['estimates'][0]['status'], 'captured_future_only')
        self.assertEqual(result['continuation'], [])
        previous = len(self.seen)
        repeated = self.run_acquire(execute=True, as_of=cutoff)
        self.assertEqual(len(self.seen), previous)
        self.assertEqual(repeated['estimates'][0]['status'], 'reused_future_only')
        self.assertFalse(repeated['complete'])

    def test_zero_budget_and_invalid_identity_make_no_network_calls(self):
        result = self.run_acquire([self.item('AAA', estimates=True)], execute=True, max_requests=0, max_seconds=1)
        self.assertFalse(result['complete'])
        self.assertEqual(self.seen, [])
        self.assertEqual(result['budget']['http_attempts'], 0)
        self.assertIsNone(result['budget']['max_seconds'])
        saved_budget = json.loads((Path(result['scratch']) / 'budget.json').read_text(encoding='utf-8'))
        self.assertIsNone(saved_budget['max_seconds'])
        item = self.item('AAA')
        item['class_id'] = ''
        with self.assertRaises(acquire.DataError):
            self.run_acquire([item], execute=True)
        self.assertEqual(self.seen, [])

    def test_interrupted_request_retains_intent_without_false_completion(self):
        with patch.object(self, 'open', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_acquire([self.item('AAA')], execute=True)
        scratch = next(self.work.glob('acquisition-*'))
        self.assertTrue((scratch / 'request-001-intent.json').is_file())
        self.assertFalse((scratch / 'request-001-complete.json').exists())
        self.assertFalse((scratch / 'result.json').exists())
        self.assertNotIn(self.secret, (scratch / 'request-001-intent.json').read_text(encoding='utf-8'))

    def test_fresh_ready_time_follows_last_actual_snapshot_save(self):
        saved_at = []
        original = acquire.history.save_snapshot

        def slow_save(*args, **kwargs):
            result = original(*args, **kwargs)
            self.sleep(2.8)
            saved_at.append(self.now)
            return result

        with patch.object(acquire.history, 'save_snapshot', side_effect=slow_save):
            result = self.run_acquire([self.item('AAA', estimates=True)], execute=True)
        ready = acquire.parse_time(result['ready_to_freeze_after'])
        self.assertGreaterEqual(ready, max(saved_at))
        self.assertEqual(ready, self.now)
        self.assertTrue(result['complete'])

    def test_batching_also_respects_existing_helpers_utf8_byte_limits(self):
        items = [self.item('S%02d' % n, estimates=True) for n in range(25)]
        for row in items:
            row['reason'] = '\U0001f4c8' * 400
            row['identity_source_url'] = 'https://example.com/' + 'a' * 1900
            row['estimates'][0]['reason'] = '\U0001f4c8' * 400
            row['estimates'].append({'period': '2025-02-28', 'horizon': 'fiscal quarter', 'reason': '\U0001f4c8' * 400})
        result = self.run_acquire(items, execute=True, max_estimate_calls=25, max_requests=40)
        self.assertTrue(result['complete'])
        self.assertEqual(len(result['estimates']), 50)
        scratch = Path(result['scratch'])
        self.assertTrue(all(path.stat().st_size <= 32768 for path in scratch.glob('*-plan.json')
                            if path.name != 'continuation-plan.json'))

    def test_reused_estimate_expiring_during_later_work_becomes_continuation(self):
        seeded = self.run_acquire([self.item('AAA', estimates=True)], execute=True)
        snapshot = seeded['estimates'][0]['snapshot']
        observed = acquire.parse_time(json.loads(Path(snapshot).read_text(encoding='utf-8'))['observed_at'])
        until_expiry = observed + timedelta(hours=24, seconds=-20)
        self.sleep((until_expiry - self.now).total_seconds())
        items = [self.item('AAA', estimates=True)] + [self.item('S%02d' % n, estimates=True) for n in range(1, 11)]
        original = self.open

        def late_response(request, timeout=None):
            params = parse_qs(urlparse(request.full_url).query)
            if params.get('symbol') == ['S10']:
                self.sleep(25)
            return original(request, timeout=timeout)

        previous = len(self.seen)
        with patch.object(self, 'open', side_effect=late_response):
            result = self.run_acquire(items, execute=True, max_requests=12, max_estimate_calls=10)
        self.assertFalse(result['complete'])
        expired = result['estimates'][0]
        self.assertEqual(expired['status'], 'stale')
        self.assertEqual(expired['acquisition_status'], 'reused')
        self.assertEqual(expired['error_code'], 'estimate_stale')
        self.assertEqual(expired['snapshot'], snapshot)
        self.assertTrue(all(row['status'] == 'captured' for row in result['estimates'][1:]))
        self.assertEqual([row['symbol'] for row in result['continuation']], ['AAA'])
        self.assertEqual(result['continuation'][0]['estimates'], items[0]['estimates'])
        self.assertEqual(result['budget']['http_attempts'], 12)
        self.assertFalse(any(params.get('symbol') == 'AAA' for _, params in self.seen[previous:]))

    def test_cli_records_its_real_time_budget_and_freshness_in_both_artifacts(self):
        self.path.write_text(json.dumps([self.item('AAA', estimates=True)]), encoding='utf-8')
        original_acquire, original_client = acquire.acquire, acquire.HttpClient
        supplied_seconds = []

        def client_factory(env, **kwargs):
            supplied_seconds.append(kwargs['max_seconds'])
            return original_client(env, opener=self, clock=lambda: self.monotonic,
                                   sleeper=self.sleep, **kwargs)

        def configured_acquire(*args, **kwargs):
            return original_acquire(*args, clock=lambda: self.now, sleep=self.sleep, **kwargs)

        output = io.StringIO()
        env = {'ALPACA_API_KEY': self.secret, 'ALPACA_SECRET_KEY': 'fixture-secret',
               'ALPHA_VANTAGE_API_KEY': self.secret}
        with patch.object(acquire, 'HttpClient', side_effect=client_factory):
            with patch.object(acquire, 'acquire', side_effect=configured_acquire):
                with patch.dict(acquire.os.environ, env):
                    with patch('sys.stdout', output):
                        self.assertEqual(acquire.main(['--vault', str(self.vault), '--plan', str(self.path),
                            '--work-dir', str(self.work), '--execute', '--max-seconds', '37', '--reuse-hours', '5']), 0)
        result = json.loads(output.getvalue())
        self.assertTrue(result['complete'])
        self.assertEqual(supplied_seconds, [37])
        for record in (result, json.loads((Path(result['scratch']) / 'result.json').read_text(encoding='utf-8'))):
            self.assertEqual(record['budget']['max_seconds'], 37)
            self.assertEqual(record['budget']['reuse_hours'], 5)
        saved = json.loads((Path(result['scratch']) / 'budget.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['max_seconds'], 37)
        self.assertEqual(saved['reuse_hours'], 5)
        self.assertEqual(result['budget']['http_attempts'], 3)


if __name__ == '__main__':
    unittest.main()
