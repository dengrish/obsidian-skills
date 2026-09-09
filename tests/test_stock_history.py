#!/usr/bin/env python3
"""Offline provider, archive and budget regressions for targeted history preflight."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/stock-research/scripts'))
import stock_history as history
import stock_acquire as acquire
import market_http
import market_prices
import market_universe
from market_acquire import Scratch
from test_stock_acquire import Response


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='.stock-history-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = self.root / 'vault'; self.vault.mkdir()
        self.work = self.root / 'work'; self.work.mkdir()
        self.now = datetime(2026, 9, 9, 6, 0, 0, 400000, timezone.utc)
        self.seen, self.mode = [], None
        for module in (market_http, market_prices):
            patcher = patch.object(module, 'utc_now', side_effect=lambda: self.now)
            patcher.start(); self.addCleanup(patcher.stop)

    def request(self, **changes):
        return dict({'timeframe': '1Min', 'start': '2026-09-08T13:30:00Z', 'end': '2026-09-08T20:00:00Z',
                     'adjustment': 'raw', 'asof': '2026-09-08', 'max_pages': 2, 'reason': 'Regular-session liquidity'}, **changes)

    def item(self, symbol='AAA', requests=None, **changes):
        return dict({'symbol': symbol, 'class_id': 'common', 'identity_source_url': 'https://example.com/issuer',
                     'identity_available_at': '2026-09-01T00:00:00Z', 'reason': 'Known feed nominee',
                     'history': requests or [self.request()]}, **changes)

    def open(self, request, timeout=None):
        endpoint = request.full_url.split('?', 1)[0]
        params = {key: values[0] for key, values in parse_qs(urlparse(request.full_url).query).items()}
        self.seen.append((endpoint, params))
        if endpoint == market_prices.CALENDAR_URL:
            day, end = acquire.parse_date(params['start']), acquire.parse_date(params['end'])
            payload = []
            while day <= end:
                if day.weekday() < 5:
                    payload.append({'date': day.isoformat(), 'open': '09:30', 'close': '16:00'})
                day += timedelta(days=1)
        elif endpoint == market_prices.BARS_URL:
            if self.mode == 'page_error' and params.get('page_token'):
                return Response({'bars': []})
            stamp = '2026-09-08T13:30:00Z' if params['timeframe'] == '1Min' else '2026-09-08T04:00:00Z'
            bar = {'t': stamp, 'o': 10, 'h': 11, 'l': 9, 'c': 10, 'vw': 10, 'v': 100, 'n': 2}
            bars = {symbol: [deepcopy(bar)] for symbol in params['symbols'].split(',')}
            if self.mode == 'missing':
                bars['BBB'] = []
            elif self.mode == 'rejected':
                bars['BBB'][0]['c'] = -1
            elif self.mode == 'duplicate':
                bars['BBB'].append(deepcopy(bar))
            token = 'next' if self.mode in {'page_error', 'page_limit'} else None
            payload = {'bars': bars, 'next_page_token': token}
        else:
            self.fail('Unexpected history resource')
        return Response(payload)

    def client(self, budget=20):
        client = acquire.HttpClient({'ALPACA_API_KEY': 'synthetic-key', 'ALPACA_SECRET_KEY': 'synthetic-secret'},
                                   opener=self, max_requests=100, sleeper=lambda seconds: None)
        return acquire.RunClient(client, budget, Scratch(self.work, self.vault))

    def capture(self, plan=None, budget=20, cutoff=None):
        client = self.client(budget)
        result = history.capture(self.vault, plan or [self.item()], client, lambda: self.now, cutoff)
        return result, client

    def test_offline_inspect_does_not_create_anything(self):
        rows = history.inspect(self.vault, [self.item()], self.now)
        self.assertEqual(rows[0]['status'], 'planned')
        self.assertEqual(list(self.vault.iterdir()), [])
        self.assertEqual(list(self.work.iterdir()), [])
        self.assertEqual(self.seen, [])

    def test_batch_calendar_and_history_share_transport_and_reuse_no_requests(self):
        plan = [self.item('AAA'), self.item('BBB')]
        rows, client = self.capture(plan)
        self.assertEqual([row['status'] for row in rows], ['captured', 'captured'])
        self.assertEqual(len(client.actual), 2)
        self.assertEqual(self.seen[1][1]['symbols'], 'AAA,BBB')
        first = rows[0]
        payload = json.loads(Path(first['snapshot']).read_text(encoding='utf-8'))
        receipt = json.loads(Path(first['receipt']).read_text(encoding='utf-8'))
        self.assertEqual(payload['bars'][0]['v'], 100)
        self.assertEqual(payload['calendar']['sessions'][0]['date'], '2026-09-08')
        self.assertLessEqual(history.parse_time(payload['observed_at']), history.parse_time(receipt['available_at']))
        self.assertEqual(receipt['snapshot_sha256'], Path(first['snapshot']).stem)
        replay, client = self.capture(plan)
        self.assertEqual([row['status'] for row in replay], ['reused', 'reused'])
        self.assertEqual(len(client.actual), 0)
        self.assertEqual(len(self.seen), 2)

    def test_old_cutoff_keeps_new_capture_future_only_without_refetch(self):
        cutoff = self.now - timedelta(seconds=1)
        rows, _ = self.capture(cutoff=cutoff)
        self.assertEqual(rows[0]['status'], 'captured_future_only')
        self.assertFalse(rows[0]['eligible_at_cutoff'])
        rows, client = self.capture(cutoff=cutoff)
        self.assertEqual(rows[0]['status'], 'reused_future_only')
        self.assertEqual(len(client.actual), 0)
        self.now += timedelta(hours=25)
        history.recheck(self.vault, rows, self.now, cutoff)
        self.assertEqual(rows[0]['status'], 'reused_future_only')
        rows, client = self.capture(cutoff=cutoff)
        self.assertEqual(rows[0]['status'], 'reused_future_only')
        self.assertEqual(len(client.actual), 0)

    def test_provider_budget_exhaustion_does_not_assume_history_complete(self):
        rows, client = self.capture(budget=1)
        self.assertEqual(len(client.actual), 1)
        self.assertEqual(rows[0]['status'], 'unavailable')
        self.assertEqual(rows[0]['error_code'], 'request_budget')
        self.assertFalse(rows[0]['complete'])
        self.assertEqual(list(self.vault.iterdir()), [])

    def test_per_symbol_failures_preserve_good_symbols_and_reuse_partial_evidence(self):
        for mode in ('missing', 'duplicate', 'rejected'):
            with self.subTest(mode=mode):
                self.vault = self.root / mode; self.vault.mkdir()
                self.mode = mode
                rows, _ = self.capture([self.item('AAA'), self.item('BBB')])
                self.assertEqual(rows[0]['status'], 'captured')
                self.assertEqual(rows[1]['status'], 'partial')
                self.assertFalse(rows[1]['complete'])
                replay, client = self.capture([self.item('AAA'), self.item('BBB')])
                self.assertEqual(replay[1]['status'], 'reused_partial')
                self.assertEqual(len(client.actual), 0)

    def test_page_budget_and_later_bad_page_keep_validated_partial_history(self):
        for mode in ('page_limit', 'page_error'):
            with self.subTest(mode=mode):
                self.vault = self.root / mode; self.vault.mkdir()
                self.mode = mode
                plan = [self.item(requests=[self.request(max_pages=1 if mode == 'page_limit' else 2)])]
                rows, _ = self.capture(plan)
                self.assertEqual(rows[0]['status'], 'partial')
                value = json.loads(Path(rows[0]['snapshot']).read_text(encoding='utf-8'))
                self.assertEqual(len(value['bars']), 1)
                self.assertFalse(rows[0]['coverage']['exhausted'])
                self.assertEqual(rows[0]['error_code'], 'pagination_incomplete' if mode == 'page_limit' else 'invalid_response')

    def test_daily_window_matches_adapter_cutoff_and_shared_calendar(self):
        request = self.request(timeframe='1Day', start='2026-09-08T04:00:00Z', end='2026-09-09T04:00:00Z', adjustment='split')
        rows, _ = self.capture([self.item('AAA', [request]), self.item('BBB', [request])])
        self.assertEqual([row['status'] for row in rows], ['captured', 'captured'])
        self.assertEqual(self.seen[1][1]['end'], '2026-09-09T03:59:59.999999Z')
        value = json.loads(Path(rows[0]['snapshot']).read_text(encoding='utf-8'))
        self.assertEqual(value['bars'][0]['interval_end'], '2026-09-09T04:00:00Z')

    def test_receipt_publication_sets_availability_after_snapshot(self):
        original = history.evidence.write
        observed = self.now
        def advancing(value, *args, **kwargs):
            result = original(value, *args, **kwargs)
            self.now += timedelta(seconds=1)
            return result
        with patch.object(history.evidence, 'write', side_effect=advancing):
            rows, _ = self.capture()
        self.assertGreater(history.parse_time(rows[0]['available_at']), observed)

    def test_class_or_query_change_does_not_reuse_unrelated_evidence(self):
        self.capture()
        rows = history.inspect(self.vault, [self.item(class_id='B')], self.now)
        self.assertEqual(rows[0]['status'], 'planned')
        rows = history.inspect(self.vault, [self.item(requests=[self.request(max_pages=20, reason='Same evidence')])], self.now)
        self.assertEqual(rows[0]['status'], 'reused')

    def test_export_feeds_existing_liquidity_calculator_and_rejects_late_receipts(self):
        request = self.request(adjustment='split', asof='2026-09-09')
        rows, _ = self.capture([self.item(requests=[request])])
        row = rows[0]
        exported = history.payloads(self.vault, row['snapshot'], row['receipt'], history.dates._iso(self.now), self.now)
        calculated = market_universe.liquidity([exported['prices']], exported['sessions'],
            history.dates._iso(self.now), ['AAA'], session_count=1, minimum=1)
        self.assertTrue(calculated['candidates'][0]['liquidity_threshold_verified'])
        self.assertFalse(calculated['candidates'][0]['regular_liquidity_complete'])
        self.assertFalse(calculated['candidates'][0]['eligibility_verified'])
        self.assertEqual(exported['prices']['evidence']['available_at'], row['available_at'])
        self.assertEqual(exported['sessions']['query']['end'], '2026-09-09')
        with self.assertRaises(history.DataError) as raised:
            history.payloads(self.vault, row['snapshot'], row['receipt'], history.dates._iso(self.now - timedelta(seconds=1)), self.now)
        self.assertEqual(raised.exception.code, 'history_future_only')

    def test_zero_page_provider_envelope_is_unavailable_not_a_run_failure(self):
        fetch = history.Acquisition.fetch
        def zero_page(run, argv):
            payload = fetch(run, argv)
            if argv[0] == 'prices':
                payload['pagination'] = {'pages': 0, 'exhausted': False, 'error': {'code': 'access_denied'}}
                payload['complete'] = False
                payload['data']['bars']['AAA'] = []
            return payload
        with patch.object(history.Acquisition, 'fetch', zero_page):
            rows, _ = self.capture()
        self.assertEqual(rows[0]['status'], 'unavailable')
        self.assertEqual(rows[0]['error_code'], 'access_denied')
        self.assertNotIn('snapshot', rows[0])
        rows = history.inspect(self.vault, [self.item(requests=[self.request(adjustment='split')])], self.now)
        self.assertEqual(rows[0]['status'], 'planned')

    def test_changed_snapshot_and_symlink_cannot_be_reused(self):
        rows, _ = self.capture()
        path = Path(rows[0]['snapshot'])
        original = path.read_bytes()
        path.write_bytes(original + b' ')
        with self.assertRaises(history.DataError):
            history.inspect(self.vault, [self.item()], self.now)
        path.unlink(); path.symlink_to(self.root / 'outside')
        with self.assertRaises((history.DataError, ValueError)):
            history.inspect(self.vault, [self.item()], self.now)

    def test_final_recheck_expiry_and_receipt_integrity_without_network(self):
        rows, _ = self.capture()
        before = len(self.seen)
        self.now += timedelta(hours=25)
        history.recheck(self.vault, rows, self.now)
        self.assertEqual(rows[0]['status'], 'stale')
        self.assertEqual(rows[0]['error_code'], 'history_stale')
        self.assertEqual(len(self.seen), before)

    def test_validation_rejects_unbounded_duplicate_or_future_history(self):
        for invalid in ([self.request()] * 5,
                        [self.request(), self.request(reason='Different prose, same request')],
                        [self.request(start='2026-07-01T00:00:00Z')],
                        [self.request(timeframe='1Day')],
                        [self.request(end=history.dates._iso(self.now))],
                        [self.request(max_pages=True)], [self.request(unexpected='field')]):
            with self.subTest(invalid=invalid), self.assertRaises((history.DataError, ValueError)):
                history.validate_requests(invalid, self.now)


if __name__ == '__main__':
    unittest.main()
