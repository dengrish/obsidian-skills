#!/usr/bin/env python3
"""Stock snapshots, historical cutoffs and interrupted publication in fake vaults."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/stock-research/scripts'))
import stock_dossiers as dossiers

PROVENANCE = {'skill': 'investments:stock-research', 'plugin_version': '1.11.0',
              'runtime_sha256': 'a' * 64, 'source_status': 'unavailable',
              'source_commit': None, 'source_url': None}


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='stock-dossier-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.vault = self.base / 'vault'
        self.vault.mkdir()
        self.work = self.base / 'work'
        self.work.mkdir()
        (self.vault / 'Investments').mkdir()

    def daily(self, day='2026-09-08', ticker='ABC', status='watch', company='Example Inc.',
              company_id=None, exchange='NASDAQ', suffix='', prose='Evidence remains preliminary.'):
        body = ('---\nstock_research: 1\ndate: ' + day
                + '\nas_of: "' + day + 'T11:30:00-04:00"\ngenerated_at: "' + day
                + 'T11:35:00-04:00"\nsession: intraday\ncoverage: normal\n---\n\n'
                + '# Stock research — ' + day + '\n\n## Decision brief\n\nWait for confirmation.\n\n'
                + '### Buying opportunities\n\nNo qualifying opportunity.\n\n'
                + '### Next checks\n\nVerify the next session.\n\n## Research record\n\n'
                + '### Screening and sources\n\nSynthetic fixture only.\n\n### Candidate assessments\n\n'
                + '#### ' + exchange + ':' + ticker + ' — ' + company + '\n\nStatus: ' + status
                + ('\nCompany ID: ' + company_id if company_id else '')
                + '\n\n[[Investments/Stocks/' + ticker + ']]\n\n' + prose
                + '\n\n### Thesis updates\n\nNo active theses.\n\n### Outcome review\n\nNo observations are due.\n')
        path = self.vault / 'Investments' / (day + suffix + '-stock-research.md')
        path.write_text(dossiers.note_provenance.stamp_text(body, PROVENANCE), encoding='utf-8')
        return path

    def plan(self, daily, ticker='ABC'):
        path = self.work / ('plan-' + str(len(list(self.work.iterdir()))) + '.json')
        dossiers.prepare(self.vault, daily, ticker, draft=path)
        return path

    def publish(self, daily, ticker='ABC'):
        return dossiers.publish(self.vault, self.plan(daily, ticker), PROVENANCE)

    def note(self):
        return self.vault / 'Investments/Stocks/ABC.md'

    def receipt(self):
        return self.vault / 'Investments/.stock-research/dossiers/ABC.json'

    def test_create_all_statuses_and_verbatim_assessment(self):
        daily = self.daily(status='rejected', prose='No audited revenue supports this claim.')
        original = daily.read_bytes()
        self.assertEqual(self.publish(daily)['status'], 'created')
        text = self.note().read_text(encoding='utf-8')
        self.assertIn('status: "rejected"', text)
        self.assertIn('No audited revenue supports this claim.', text)
        self.assertIn('created: "2026-09-08T11:35:00-04:00"', text)
        self.assertIn('[[Investments/2026-09-08-stock-research#NASDAQ:ABC — Example Inc.]]', text)
        self.assertEqual(daily.read_bytes(), original)
        self.assertEqual(dossiers.note_provenance.split_provenance(text)[1]['generated_by'], PROVENANCE)
        self.assertEqual(self.receipt().stat().st_mode & 0o777, 0o600)

    def test_update_preserves_creation_history_and_creator(self):
        first = self.daily()
        self.publish(first)
        second = self.daily('2026-09-09', status='ready')
        later = {**PROVENANCE, 'plugin_version': '1.12.0', 'runtime_sha256': 'b' * 64}
        self.assertEqual(dossiers.publish(self.vault, self.plan(second), later)['status'], 'updated')
        text = self.note().read_text(encoding='utf-8')
        self.assertIn('created: "2026-09-08T11:35:00-04:00"', text)
        self.assertIn('updated: "2026-09-09T11:35:00-04:00"', text)
        self.assertIn('2026-09-08T11:30:00-04:00 — watch', text)
        provenance = dossiers.note_provenance.split_provenance(text)[1]
        self.assertEqual(provenance['generated_by'], PROVENANCE)
        self.assertEqual(provenance['updated_by'], later)

    def test_retry_is_unchanged_even_with_original_plan(self):
        plan = self.plan(self.daily())
        dossiers.publish(self.vault, plan, PROVENANCE)
        before = self.note().read_bytes()
        self.assertEqual(dossiers.publish(self.vault, plan, PROVENANCE)['status'], 'unchanged')
        self.assertEqual(self.note().read_bytes(), before)

    def test_cutoff_hides_mutable_future_but_keeps_eligible_history(self):
        self.publish(self.daily())
        self.publish(self.daily('2026-09-09'))
        historical = dossiers.context(self.vault, 'ABC', '2026-09-08T12:00:00-04:00')
        self.assertEqual(historical['status'], 'newer-than-cutoff')
        self.assertIsNone(historical['current'])
        self.assertEqual(len(historical['history']), 1)
        current = dossiers.context(self.vault, 'ABC', '2026-09-09T12:00:00-04:00')
        self.assertEqual(current['status'], 'current')
        self.assertIn('Latest assessment', current['current'])

    def test_stale_and_equal_cutoff_do_not_replace_current(self):
        self.publish(self.daily('2026-09-09'))
        current = self.note().read_bytes()
        for path in (self.daily(), self.daily('2026-09-09', suffix='-113001')):
            with self.assertRaisesRegex(ValueError, 'stale|cutoff'):
                self.publish(path)
        self.assertEqual(self.note().read_bytes(), current)

    def test_already_synced_older_report_retry_succeeds_without_regression(self):
        old = self.daily()
        old_plan = self.plan(old)
        dossiers.publish(self.vault, old_plan, PROVENANCE)
        self.publish(self.daily('2026-09-09', status='ready'))
        before = self.note().read_bytes()
        retry = dossiers.publish(self.vault, old_plan, PROVENANCE)
        self.assertEqual(retry['status'], 'unchanged')
        self.assertTrue(retry['superseded'])
        sync = dossiers.sync(self.vault, old, self.work, PROVENANCE)
        self.assertTrue(sync['complete'])
        self.assertEqual(self.note().read_bytes(), before)

    def test_report_generated_after_cutoff_is_not_historical_context(self):
        self.publish(self.daily())
        result = dossiers.context(self.vault, 'ABC', '2026-09-08T11:31:00-04:00')
        self.assertEqual(result['status'], 'newer-than-cutoff')
        self.assertIsNone(result['current'])
        self.assertEqual(result['history'], [])

    def test_manual_edits_are_preserved(self):
        self.publish(self.daily())
        self.note().write_text(self.note().read_text(encoding='utf-8') + '\nMy own annotation.\n', encoding='utf-8')
        edited = self.note().read_bytes()
        with self.assertRaisesRegex(ValueError, 'changed outside'):
            self.publish(self.daily('2026-09-09'))
        self.assertEqual(self.note().read_bytes(), edited)

    def test_unmanaged_existing_note_is_not_adopted(self):
        self.note().parent.mkdir()
        self.note().write_text('Existing user stock note.\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'unmanaged'):
            self.plan(self.daily())

    def test_changed_daily_bytes_are_not_copied(self):
        daily = self.daily()
        plan = self.plan(daily)
        daily.write_text(daily.read_text(encoding='utf-8').replace('preliminary', 'changed'), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'daily report changed'):
            dossiers.publish(self.vault, plan, PROVENANCE)
        self.assertFalse(self.note().exists())

    def test_company_collision_blocks_reused_ticker(self):
        self.publish(self.daily(company_id='SEC:0000000001'))
        for kwargs in ({'company_id': 'SEC:0000000002'}, {'company': 'Different Inc.'}, {'exchange': 'NYSE'}):
            with self.assertRaisesRegex(ValueError, 'company|exchange'):
                self.plan(self.daily('2026-09-09', **kwargs))

    def test_matching_stable_company_id_allows_verified_name_change(self):
        self.publish(self.daily(company_id='SEC:0000000001'))
        self.publish(self.daily('2026-09-09', company='Renamed Inc.', company_id='SEC:0000000001'))
        self.assertIn('Renamed Inc.', self.note().read_text(encoding='utf-8'))

    def test_historic_retry_does_not_revalidate_later_company_rename(self):
        earliest = self.daily()
        self.publish(earliest)
        self.publish(self.daily('2026-09-09', company_id='SEC:0000000001'))
        self.publish(self.daily('2026-09-10', company='Renamed Inc.', company_id='SEC:0000000001'))
        before = self.note().read_bytes()
        result = dossiers.sync(self.vault, earliest, self.work, PROVENANCE)
        self.assertTrue(result['complete'], result)
        self.assertTrue(result['results'][0]['superseded'])
        self.assertEqual(self.note().read_bytes(), before)

    def test_prepare_rejects_unpublished_or_external_daily(self):
        with self.assertRaisesRegex(ValueError, 'publish the immutable'):
            self.plan(self.vault / 'Investments/2026-09-08-stock-research.md')
        with self.assertRaisesRegex(ValueError, 'inside this vault'):
            self.plan(self.work / '2026-09-08-stock-research.md')

    def test_old_plan_cannot_overwrite_concurrent_newer_assessment(self):
        self.publish(self.daily())
        next_day = self.daily('2026-09-10')
        plan = self.plan(next_day)
        self.publish(self.daily('2026-09-09'))
        with self.assertRaisesRegex(ValueError, 'changed after planning'):
            dossiers.publish(self.vault, plan, PROVENANCE)

    def interrupted(self, phase):
        daily = self.daily()
        plan = self.plan(daily)
        original = dossiers.Store.write
        def fail(store, fd, name, data, expected, private=False):
            if (phase == 'before-note' and name.endswith('.md')) or (phase == 'before-final-receipt' and name.endswith('.json') and json.loads(data)['pending'] is None):
                raise RuntimeError('synthetic interrupted publication')
            return original(store, fd, name, data, expected, private)
        with patch.object(dossiers.Store, 'write', fail):
            with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                dossiers.publish(self.vault, plan, PROVENANCE)
        self.assertIsNotNone(json.loads(self.receipt().read_text(encoding='utf-8'))['pending'])
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            dossiers.context(self.vault, 'ABC', '2026-09-08T12:00:00-04:00')
        self.assertEqual(dossiers.publish(self.vault, plan, PROVENANCE)['status'], 'created')
        self.assertIsNone(json.loads(self.receipt().read_text(encoding='utf-8'))['pending'])
        self.assertEqual(len(json.loads(self.receipt().read_text(encoding='utf-8'))['committed']['history']), 1)

    def test_recovery_after_pending_receipt_before_note(self):
        self.interrupted('before-note')

    def test_recovery_after_note_before_final_receipt(self):
        self.interrupted('before-final-receipt')

    def test_pending_other_daily_not_overwritten(self):
        original = dossiers.Store.write
        def fail(store, fd, name, data, expected, private=False):
            if name.endswith('.md'):
                raise RuntimeError('synthetic interrupt')
            return original(store, fd, name, data, expected, private)
        with patch.object(dossiers.Store, 'write', fail):
            with self.assertRaises(RuntimeError):
                self.publish(self.daily())
        with self.assertRaisesRegex(ValueError, 'another dossier update is pending'):
            self.publish(self.daily('2026-09-09'))

    def test_stock_directory_symlink_and_portable_collision_refused(self):
        self.note().parent.symlink_to(self.work, target_is_directory=True)
        with self.assertRaises(OSError):
            self.plan(self.daily())
        self.note().parent.unlink()
        (self.vault / 'Investments/stocks').mkdir()
        with self.assertRaisesRegex(ValueError, 'portable-equivalent'):
            self.plan(self.daily())

    def test_note_symlink_refused_without_reading_target(self):
        self.note().parent.mkdir()
        target = self.work / 'do-not-touch.md'
        target.write_text('private', encoding='utf-8')
        self.note().symlink_to(target)
        with self.assertRaises((OSError, ValueError)):
            self.plan(self.daily())
        self.assertEqual(target.read_text(encoding='utf-8'), 'private')

    def test_sync_handles_all_rejected_and_ready_entries_and_retries(self):
        first = self.daily(status='rejected')
        text = first.read_text(encoding='utf-8')
        body = ('#### NYSE:XYZ — Other Inc.\n\nStatus: ready\n\n[[Investments/Stocks/XYZ]]\n\n'
                'The confirmed catalyst supports further research.\n\n')
        first.write_text(text.replace('### Thesis updates', body + '### Thesis updates'), encoding='utf-8')
        result = dossiers.sync(self.vault, first, self.work, PROVENANCE)
        self.assertTrue(result['complete'], result)
        self.assertEqual(result['analyzed'], 2)
        self.assertTrue((self.vault / 'Investments/Stocks/XYZ.md').exists())
        retry = dossiers.sync(self.vault, first, self.work, PROVENANCE)
        self.assertEqual([r['status'] for r in retry['results']], ['unchanged', 'unchanged'])

    def test_sync_reports_partial_failure_preserving_success(self):
        first = self.daily()
        text = first.read_text(encoding='utf-8')
        body = '#### NYSE:XYZ — Other Inc.\n\nStatus: rejected\n\n[[Investments/Stocks/XYZ]]\n\nFailed liquidity screen.\n\n'
        first.write_text(text.replace('### Thesis updates', body + '### Thesis updates'), encoding='utf-8')
        folder = self.vault / 'Investments/Stocks'
        folder.mkdir()
        (folder / 'XYZ.md').write_text('Manual note.', encoding='utf-8')
        result = dossiers.sync(self.vault, first, self.work, PROVENANCE)
        self.assertFalse(result['complete'])
        self.assertEqual(result['analyzed'], 2)
        self.assertEqual(len(result['results']), 1)
        self.assertEqual(result['failures'][0]['ticker'], 'XYZ')
        self.assertEqual((folder / 'XYZ.md').read_text(encoding='utf-8'), 'Manual note.')

    def test_corrupt_history_is_detected_before_context_use(self):
        first = self.daily()
        self.publish(first)
        first.write_text(first.read_text(encoding='utf-8').replace('preliminary', 'unreliable'), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'history report changed'):
            dossiers.context(self.vault, 'ABC', '2026-09-08T12:00:00-04:00')

    def test_nonstock_h4_and_fenced_fake_heading_do_not_create_dossiers(self):
        source = ('### Candidate assessments\n\nNo substantive analysis.\n\n'
                  '#### Discovery triage\n\nAmbiguous mention, not an identified issuer.\n\n'
                  '```\n#### NASDAQ:FAKE — Fake\nStatus: ready\n```\n\n### Thesis updates\n')
        self.assertEqual(dossiers.candidates(source.encode()), [])

    def test_invalid_assessment_contracts_rejected(self):
        valid = '### Candidate assessments\n#### NASDAQ:ABC — Example\nStatus: watch\n\n[[Investments/Stocks/ABC]]\nDetails.\n'
        for source in (valid.replace('Status: watch', 'Status: buy'), valid.replace('Status: watch', 'Status: watch\nStatus: ready'),
                       valid + valid, valid.replace('NASDAQ:ABC —', 'NASDAQ:ABC -'), valid.replace('Stocks/ABC', 'Stocks/XYZ'),
                       valid.replace('Stocks/ABC', 'Stocks/ABCX'), valid.replace('Stocks/ABC]]', 'Stocks/ABC]')):
            with self.subTest(source=source), self.assertRaises(ValueError):
                dossiers.candidates(source.encode())

    def test_scratch_inside_vault_rejected(self):
        with self.assertRaisesRegex(ValueError, 'outside the vault'):
            dossiers.prepare(self.vault, self.daily(), 'ABC', draft=self.vault / 'plan.json')
        with self.assertRaisesRegex(ValueError, 'outside the vault'):
            dossiers.sync(self.vault, self.daily(), self.vault, PROVENANCE)


if __name__ == '__main__':
    unittest.main(verbosity=2)
