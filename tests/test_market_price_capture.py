#!/usr/bin/env python3
"""Offline price capture, immutable replay and capitalization integration fixtures."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/stock-research/scripts'))
import market_price_capture as capture
import market_capitalization as capitalization
import market_notes
import market_prices


class PriceCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='.market-price-capture-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.vault = self.root / 'vault'; self.vault.mkdir()
        self.work = self.root / '.obsidian-skills-tmp-fixture'; self.work.mkdir()
        self.plan = self.work / 'price-plan.json'
        self.now = datetime(2024, 5, 1, 16, 0, 0, 400000, timezone.utc)
        self.items = [self.item('AAA')]
        self.save_plan()
        self.failure, self.bar_mode, self.calendar_mode = None, None, None
        self.secret = 'private-fixture-credential'
        self.client = SimpleNamespace(env={'ALPACA_API_KEY': self.secret, 'ALPACA_SECRET_KEY': 'another-fixture-secret'},
                                      requests=[], redaction_values=(self.secret,), get_json=self.get_json)
        self.clock_patch = patch.object(market_prices, 'utc_now', side_effect=lambda: self.now)
        self.clock_patch.start(); self.addCleanup(self.clock_patch.stop)

    def item(self, symbol):
        return {'symbol': symbol, 'class_id': 'A', 'identity_source_url': 'https://example.com/filing',
                'identity_available_at': '2024-04-30T17:00:00Z', 'reason': 'Previously collected feed nominee'}

    def save_plan(self):
        self.plan.write_text(json.dumps(self.items), encoding='utf-8')

    def get_json(self, url, params=None, headers=None):
        if self.failure and (self.failure[0] == 'all' or (self.failure[0] == 'bars' and url == market_prices.BARS_URL)):
            raise capture.DataError(self.failure[1], 'Provider unavailable ' + self.secret)
        if url == market_prices.CALENDAR_URL:
            day, last = capture.parse_date(params['start']), capture.parse_date(params['end'])
            payload = []
            while day <= last:
                if day.weekday() < 5:
                    close = '13:00' if self.calendar_mode == 'early_close' else '16:00'
                    payload.append({'date': day.isoformat(), 'open': '09:30', 'close': close})
                day += timedelta(days=1)
            if self.calendar_mode == 'empty':
                payload = []
            elif self.calendar_mode == 'duplicate':
                payload.append(deepcopy(payload[-1]))
        else:
            end = capture.history._time(params['end'])
            stamp = end - timedelta(minutes=1)
            bar = {'t': capture._iso(stamp), 'o': 30, 'h': 31, 'l': 29, 'c': 30, 'v': 1000, 'n': 100, 'vw': 30}
            bars = {symbol: [deepcopy(bar)] for symbol in params['symbols'].split(',')}
            payload = {'bars': bars, 'next_page_token': None}
            if self.bar_mode == 'missing':
                bars[next(iter(bars))] = []
            elif self.bar_mode == 'duplicate':
                bars[next(iter(bars))].append(deepcopy(bar))
            elif self.bar_mode == 'partial_page':
                payload['next_page_token'] = 'another-page'
            elif self.bar_mode == 'bad_symbol':
                bars[next(iter(bars))][0]['c'] = -1
            elif self.bar_mode == 'future_interval':
                for rows in bars.values():
                    rows[0]['t'] = capture._iso(end)
            elif self.bar_mode == 'auction_extra':
                auction = dict(bar, t=capture._iso(end), o=300, c=300, l=299, h=301, vw=300)
                for rows in bars.values():
                    rows.append(auction)
            elif self.bar_mode == 'last_missing':
                for rows in bars.values():
                    rows[0]['t'] = capture._iso(end - timedelta(minutes=2))
        raw = capture.evidence.canonical(payload)
        self.client.requests.append({'url': url + '?' + urlencode(params), 'retrieved_at': capture._iso(self.now),
                                     'status': 200, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
        return payload

    def sleep(self, seconds):
        self.now += timedelta(seconds=seconds)

    def run_capture(self, **kwargs):
        return capture.capture(self.vault, self.plan, client=self.client, clock=lambda: self.now, sleep=self.sleep, **kwargs)

    def replay(self, **kwargs):
        return capture.select(self.vault, self.items, capture._iso(self.now), current=self.now, **kwargs)

    def test_capture_then_real_manual_prepare_and_capitalization(self):
        result = self.run_capture()
        prepared = market_notes.prepare(self.vault, self.work, now=self.now, mode='manual')
        self.assertTrue(result['complete'])
        # The same whole-second rule used by prepare cannot precede first save.
        cutoff = prepared['as_of']
        self.assertEqual(capture.history._time(cutoff), self.now.replace(microsecond=0))
        selected = capture.select(self.vault, self.items, cutoff, current=self.now)
        price = selected['items'][0]['price']
        plan = {'symbol': 'AAA', 'issuer_cik': '0000000001', 'share_count_basis': 'outstanding_common',
                'price': price, 'classes': [{'class_id': 'A', 'shares': 100000000, 'uncertainty_shares': 0,
                'precision_basis': 'Exact whole-share fixture disclosure', 'observed_on': '2024-04-30',
                'available_at': '2024-04-30T17:00:00Z', 'source_url': 'https://example.com/filing',
                'conversion': {'kind': 'same_common', 'shares_per_price_unit': 1,
                'available_at': '2024-04-30T17:00:00Z', 'source_url': 'https://example.com/filing',
                'basis': 'One quoted A common share.'}}], 'changes': [],
                'review': {'through': price['as_of'], 'available_at': '2024-04-30T17:00:00Z',
                'source_urls': ['https://example.com/filing'], 'basis': 'Synthetic complete common-share review.',
                'latest_filings_checked': True, 'all_common_classes_included': True,
                'corporate_actions_checked': True, 'unquantified_changes': False, 'unsupported_complexity': False}}
        measured = capitalization.calculate([plan], cutoff)
        self.assertTrue(measured['complete'])
        self.assertEqual(measured['market_caps'][0]['market_cap_usd'], 3000000000)
        self.assertTrue(Path(prepared['run_receipt']).is_file())

    def test_fixed_scheduled_cutoff_remains_1130(self):
        fixed = market_notes.scheduled_cutoff(self.now.astimezone(capture._ny()))
        result = self.run_capture(as_of=fixed.isoformat())
        self.assertEqual(capture.history._time(result['as_of']), fixed)
        self.assertEqual(result['items'][0]['status'], 'future_only')
        self.assertIsNone(result['items'][0]['price'])

    def test_manual_reuse_of_same_second_frozen_capture_crosses_boundary(self):
        fixed = capture._iso(self.now - timedelta(minutes=1))
        late = self.run_capture(as_of=fixed)
        self.assertEqual(late['items'][0]['status'], 'future_only')
        self.assertEqual(self.now.microsecond, 400000)
        count = len(self.client.requests)
        manual = self.run_capture()
        self.assertTrue(manual['complete'])
        self.assertEqual(len(self.client.requests), count)
        self.assertEqual(self.now.microsecond, 0)
        replayed = capture.select(self.vault, self.items, self.now.replace(microsecond=0).isoformat(), current=self.now)
        self.assertIsNotNone(replayed['items'][0]['price'])

    def test_eligible_earlier_archive_wins_over_late_capture(self):
        first = self.run_capture(); fixed = capture._iso(self.now)
        self.now += timedelta(minutes=31)
        self.run_capture()
        replayed = capture.select(self.vault, self.items, fixed, current=self.now)
        self.assertEqual(replayed['items'][0]['price'], first['items'][0]['price'])

    def test_freshness_boundary_and_weekend_replay(self):
        first = self.run_capture()
        self.now = capture.history._time(first['items'][0]['price']['as_of']) + timedelta(minutes=45)
        self.assertTrue(self.replay()['complete'])
        self.now += timedelta(minutes=1)
        self.assertEqual(self.replay()['items'][0]['status'], 'stale')
        self.now = datetime(2024, 5, 3, 22, tzinfo=timezone.utc)
        self.run_capture()
        self.now += timedelta(days=2)
        self.assertTrue(self.replay()['complete'])
        self.now += timedelta(days=1)
        self.assertEqual(self.replay()['items'][0]['status'], 'stale')

    def test_early_close_and_auction_minute_exclusion(self):
        self.now = datetime(2024, 5, 1, 18, tzinfo=timezone.utc)
        self.calendar_mode, self.bar_mode = 'early_close', 'auction_extra'
        result = self.run_capture()
        self.assertTrue(result['complete'])
        price = result['items'][0]['price']
        self.assertEqual(capture.history._time(price['as_of']).hour, 17)
        self.assertEqual(price['usd'], 30)

    def test_last_missing_minute_is_a_dated_observation_not_an_inferred_close(self):
        self.bar_mode = 'last_missing'
        result = self.run_capture()
        self.assertTrue(result['complete'])
        self.assertEqual(capture.history._time(result['items'][0]['price']['as_of']).minute, 44)

    def test_missing_invalid_partial_duplicate_and_future_bars_never_archive(self):
        for mode in ('missing', 'bad_symbol', 'partial_page', 'duplicate', 'future_interval'):
            with self.subTest(mode=mode):
                self.bar_mode = mode
                result = self.run_capture()
                self.assertFalse(result['complete'])
                self.assertIsNone(result['items'][0]['price'])
                self.assertFalse(self.vault.joinpath(*capture.FOLDER).exists())

    def test_mixed_missing_rejected_and_duplicate_targets_preserve_valid_symbols(self):
        self.items = [self.item('AAA'), self.item('BBB')]; self.save_plan()
        for mode in ('missing', 'bad_symbol', 'duplicate'):
            with self.subTest(mode=mode):
                self.bar_mode = mode
                result = self.run_capture()
                self.assertFalse(result['complete'])
                self.assertIsNone(result['items'][0]['price'])
                self.assertIsNotNone(result['items'][1]['price'])
                self.assertEqual(self.now.microsecond, 0)
                cutoff = self.now.replace(microsecond=0).isoformat()
                replayed = capture.select(self.vault, self.items, cutoff, current=self.now)
                self.assertIsNotNone(replayed['items'][1]['price'])
                self.now += timedelta(minutes=31, microseconds=400000)

    def test_empty_or_invalid_calendar_does_not_create_price_archive(self):
        for mode in ('empty', 'duplicate'):
            with self.subTest(mode=mode):
                self.calendar_mode = mode
                result = self.run_capture()
                self.assertFalse(result['complete'])
                self.assertEqual(result['price_batch_calls'], 0)

    def test_provider_error_is_bounded_and_eligible_archive_stays_usable(self):
        self.run_capture()
        self.items.append(self.item('BBB')); self.save_plan()
        self.failure = ('bars', 'rate_limited')
        result = self.run_capture()
        self.assertIsNotNone(result['items'][0]['price'])
        self.assertEqual(result['items'][1]['capture_error'], 'rate_limited')
        self.assertIsNone(result['items'][1]['price'])
        self.assertNotIn(self.secret, json.dumps(result))

    def test_priority_budget_and_zero_call_replay(self):
        self.items = [self.item('BBB'), self.item('AAA')]; self.save_plan()
        result = self.run_capture(max_symbols=1)
        self.assertEqual(result['items'][1]['status'], 'budget_deferred')
        before = len(self.client.requests)
        result = self.run_capture(max_symbols=0)
        self.assertIsNotNone(result['items'][0]['price'])
        self.assertIsNone(result['items'][1]['price'])
        self.assertEqual(len(self.client.requests), before)

    def test_read_only_empty_select_does_not_create_folders(self):
        self.assertFalse(self.replay()['complete'])
        self.assertFalse((self.vault / 'Investments').exists())

    def test_unreceipted_observation_is_not_eligible(self):
        original = capture.evidence.write
        def fail_receipt(value, *args, **kwargs):
            if 'price_receipt' in value:
                raise RuntimeError('Synthetic receipt failure')
            return original(value, *args, **kwargs)
        with patch.object(capture.evidence, 'write', side_effect=fail_receipt):
            with self.assertRaises(RuntimeError):
                self.run_capture()
        self.assertEqual(self.replay()['items'][0]['status'], 'missing')
        self.assertEqual(len(list(self.vault.joinpath(*capture.FOLDER).glob('*.json'))), 1)

    def test_symlink_alias_and_malformed_plan_are_rejected_without_writes(self):
        alias = self.root / 'alias'; alias.symlink_to(self.vault, target_is_directory=True)
        with self.assertRaises(ValueError):
            capture.select(alias, self.items, capture._iso(self.now), current=self.now)
        self.plan.write_text('[{"symbol":"AAA","symbol":"BBB"}]', encoding='utf-8')
        with self.assertRaises(capture.DataError):
            self.run_capture()
        self.assertFalse((self.vault / 'Investments').exists())

    def test_future_identity_cutoff_and_duplicate_symbol_are_rejected(self):
        with self.assertRaises(capture.DataError):
            capture.select(self.vault, self.items, capture._iso(self.now + timedelta(seconds=1)), current=self.now)
        self.items[0]['identity_available_at'] = '2030-01-01T00:00:00Z'; self.save_plan()
        with self.assertRaises(capture.DataError):
            self.run_capture()
        self.items = [self.item('AAA'), self.item('AAA')]; self.save_plan()
        with self.assertRaises(capture.DataError):
            self.run_capture()

    def test_unsupported_currency_adjustment_and_incomplete_envelope(self):
        original = capture.Acquisition.fetch
        for field, value in (('currency', 'EUR'), ('adjustment', 'split'), ('feed', 'iex')):
            def change(run, argv):
                result = original(run, argv)
                if argv[0] == 'prices':
                    result['query'][field] = value
                return result
            with self.subTest(field=field), patch.object(capture.Acquisition, 'fetch', change):
                self.assertFalse(self.run_capture()['complete'])

    def test_changed_plan_after_acquisition_retains_evidence(self):
        original = capture.archive
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            self.items[0]['reason'] = 'Late edited plan'; self.save_plan()
            return result
        with patch.object(capture, 'archive', side_effect=changed):
            with self.assertRaises(capture.DataError):
                self.run_capture()
        self.assertTrue(self.replay()['complete'])


if __name__ == '__main__':
    unittest.main()
