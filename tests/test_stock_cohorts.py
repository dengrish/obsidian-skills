#!/usr/bin/env python3
"""Prospective nominee cohorts from actual published journal fixtures; offline only."""
import copy
from datetime import datetime, timedelta
import hashlib
import json
import re
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/stock-research/scripts'))
import stock_cohorts as cohorts
import market_notes
import test_stock_coverage as coverage_fixtures
from test_market_comparison import calendar_fixture, prices_fixture, bar

CUTOFF = coverage_fixtures.CUTOFF


def stamp(value):
    return market_notes.iso_time(value)


class CohortTests(unittest.TestCase):
    def setUp(self):
        self.fixture = coverage_fixtures.CoverageTests('test_new_posts_need_disposition')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.vault = self.fixture.vault
        self.launch = stamp('2026-09-08T11:29:00-04:00')
        self.formed = stamp('2026-09-08T11:40:00-04:00')
        self.later = '2026-09-25T11:30:00-04:00'

    def activate(self):
        return cohorts.start(self.vault, self.launch)

    def publish(self, *, ticker='ABC', group='unfinished', as_of=CUTOFF, history=None, sources='10',
                state='queued', disposition='nominated', fingerprint=None):
        day = market_notes.ny_now(stamp(as_of)).strftime('%Y-%m-%d')
        current = market_notes.ny_now(stamp(as_of)).strftime('%Y-%m-%d-%H%M%S-stock-research')
        security = 'NASDAQ:' + ticker
        post = self.fixture.post(disposition=disposition, securities=security,
            due=(stamp(as_of) + timedelta(days=1)).isoformat() if disposition in cohorts.coverage.UNRESOLVED else '-')
        post['Fingerprint'] = fingerprint or post['Fingerprint']
        post['Post'] = 'https://x.com/i/web/status/' + sources.split(',')[0].strip()
        if history is None:
            history = self.fixture.anchors(as_of)
        candidate = group != 'unfinished'
        job = self.fixture.job(state='assessed' if candidate else state,
            due='-' if candidate else (stamp(as_of) + timedelta(days=1)).isoformat(), source=sources,
            assessment='[[' + 'Investments/' + current + '#' + security + ' — Example Inc.]]' if candidate else '-')
        job['Security'] = security
        ledger = 'No active theses.'
        if group in {'ready', 'watch'}:
            ledger = ('| Thesis | State | Update / next check |\n|---|---|---|\n| ' + security + '@' + day
                      + ' | ' + group + ' | 2027-09-08 |')
        path = self.fixture.note(as_of=as_of, posts=[post], jobs=[job], history=history,
                                 candidates=candidate, ledger=ledger, name=current + '.md')
        if candidate:
            data = path.read_text(encoding='utf-8').replace('NASDAQ:ABC', security).replace('/ABC]]', '/' + ticker + ']]')
            data = data.replace('Status: watch', 'Status: ' + group)
            path.write_text(data, encoding='utf-8')
        return path

    def form_one(self, **kwargs):
        self.activate()
        path = self.publish(**kwargs)
        result = cohorts.form(self.vault, self.formed)
        context = cohorts.context(self.vault, self.formed.isoformat())
        return path, result, context['cohorts'][0]

    def bundle(self, symbols=('ABC', 'SPY'), *, cutoff=None, baseline='2026-09-09', endpoint='2026-09-23'):
        values = {symbol: [bar(baseline, 100), bar(endpoint, 130 if symbol != 'SPY' else 110)] for symbol in symbols}
        return {'stock_nominee_input': 1, 'as_of': cutoff or self.later,
                'sessions': calendar_fixture('2026-09-08', (cutoff or self.later)[:10]),
                'prices': [prices_fixture(values, '2026-09-08T04:00:00Z', (cutoff or self.later)[:10] + 'T03:59:59Z', mapping='2026-09-08')],
                'corporate_actions': {symbol: {'status': 'verified', 'source': 'https://example.invalid/actions',
                    'note': 'Synthetic unchanged USD security identity and no actions.'} for symbol in symbols}}

    def frozen(self, **kwargs):
        _, _, card = self.form_one(**kwargs)
        return cohorts._replay(self.vault, cohorts._events(self.vault), cohorts._reports(self.vault, self.formed))[2][card['cohort']]

    def partial_pair(self):
        """Two verified assessments plus an unmapped residual in one blocked source."""
        path = self.publish(group='watch', disposition='blocked')
        text = path.read_text(encoding='utf-8')
        text = text.replace('| blocked | NASDAQ:ABC |', '| blocked | NASDAQ:ABC, NASDAQ:DEF |')
        text = text.replace('Verified lead.', 'ABC and DEF verified; $UNKNOWN remains unidentified.')
        job = next(line for line in text.splitlines() if line.startswith('| NASDAQ:ABC |'))
        text = text.replace(job, job + '\n' + job.replace('NASDAQ:ABC', 'NASDAQ:DEF'))
        detail = ('#### NASDAQ:DEF — Example Inc.\n\nStatus: rejected\n\n[[Investments/Stocks/DEF]]\n\n'
                  'The initial valuation leaves no supported buying case.\n\n')
        text = text.replace('### Thesis updates', detail + '### Thesis updates')
        path.write_text(text, encoding='utf-8')
        return path

    def legacy_partial_formation(self, path):
        """Fixed v1 output for the partial-pair fixture, not the current derivation."""
        report = next(row for row in cohorts._reports(self.vault, self.formed) if row['relative'].endswith(path.name))
        events = cohorts._events(self.vault)
        value = cohorts._new('report', self.formed, events,
            source_report=report['relative'], source_sha256=report['sha256'],
            source_as_of=report['as_of'], published_at=report['generated_at'], formation_delay_seconds=300.0,
            cohort='feed-nominees-v1@' + report['sha256'][:24], members=[], observations=[],
            excluded_prior_securities=[], coverage={'posts': 1, 'nominated_posts': 0,
                'unresolved_posts': 1, 'queued': 0, 'blocked': 0})
        return cohorts.evidence.write(value, self.vault, cohorts.FOLDER)

    def test_partial_source_enrolls_every_verified_security_without_hiding_residual(self):
        self.activate(); self.partial_pair()
        result = cohorts.form(self.vault, self.formed)
        current = cohorts.context(self.vault, self.formed.isoformat())
        self.assertEqual(result['new_members'], 2)
        self.assertEqual(result['recovered_members'], 0)
        self.assertEqual(current['counts']['unresolved_posts'], 1)
        card = current['cohorts'][0]
        self.assertEqual(card['enrollment_kind'], 'report-v2')
        self.assertEqual(card['coverage']['partial_nomination_posts'], 1)
        self.assertEqual(card['coverage']['nominated_posts'], 0)
        self.assertEqual([(row['security'], row['disposition']['group']) for row in card['members']],
                         [('NASDAQ:ABC', 'watch'), ('NASDAQ:DEF', 'rejected')])
        self.assertTrue(all(row['origins'][0]['post_id'] == '10' for row in card['members']))
        self.assertEqual(cohorts.form(self.vault, self.formed + timedelta(minutes=1))['status'], 'unchanged')

    def test_pending_partial_source_can_enroll_an_explicit_unfinished_job(self):
        self.activate(); self.publish(disposition='pending', state='blocked')
        self.assertEqual(cohorts.form(self.vault, self.formed)['new_members'], 1)
        current = cohorts.context(self.vault, self.formed.isoformat())
        member = current['cohorts'][0]['members'][0]
        self.assertEqual(member['disposition']['group'], 'unfinished')
        self.assertEqual(member['disposition']['work_state'], 'blocked')
        self.assertEqual(current['counts']['unresolved_posts'], 1)

    def test_paused_partial_journal_needs_matching_job_and_source_before_enrollment(self):
        self.activate()
        path = self.fixture.note(name='2026-09-08-113000-stock-research.md',
            posts=[self.fixture.post('pending', 'NASDAQ:ABC, NASDAQ:DEF', due='2026-09-09T12:00:00-04:00')],
            jobs=[self.fixture.job(source='user')])
        result = cohorts.form(self.vault, self.formed)
        current = cohorts.context(self.vault, self.formed.isoformat())
        self.assertEqual(result['new_members'], 0)
        self.assertEqual(current['counts']['unresolved_posts'], 1)
        self.assertEqual(current['counts']['enrolled'], 0)
        self.assertFalse(current['formation_due'])
        self.assertTrue(path.is_file())

    def test_legacy_omissions_recover_once_without_rewriting_history_or_backdating(self):
        self.activate(); path = self.partial_pair()
        old = self.legacy_partial_formation(path)
        original_events = cohorts._events(self.vault)
        source = path.read_bytes()
        old_context = cohorts.context(self.vault, self.formed.isoformat())
        self.assertEqual(old_context['counts']['enrolled'], 0)
        self.assertEqual(old_context['counts']['pending_recovery_members'], 2)
        self.assertTrue(old_context['formation_due'])
        self.assertEqual(old_context['unformed_reports'], [])
        recovered_at = stamp('2026-09-10T11:40:00-04:00')
        result = cohorts.form(self.vault, recovered_at)
        self.assertEqual((result['new_members'], result['recovered_members'], result['new_cohorts']), (2, 2, 1))
        self.assertEqual(result['processed_reports'], [])
        self.assertEqual(result['recovered_reports'], ['Investments/' + path.name])
        self.assertEqual(cohorts._events(self.vault)[:2], original_events)
        self.assertEqual(path.read_bytes(), source)
        current = cohorts.context(self.vault, recovered_at.isoformat())
        card = current['cohorts'][0]
        self.assertEqual(card['enrollment_kind'], 'recovery-v2')
        self.assertEqual(card['recovered_from'], old['sha256'])
        self.assertEqual(card['recorded_at'], recovered_at.isoformat())
        self.assertEqual(card['source_as_of'], CUTOFF)
        self.assertEqual(card['formation_delay_seconds'], 173100)
        self.assertEqual(current['counts']['enrolled'], 2)
        self.assertEqual(current['counts']['unresolved_posts'], 1)
        self.assertEqual(current['counts']['observations'], 0)
        self.assertEqual(current['counts']['checkpoints_pending'], 5)
        self.assertFalse(current['recovery_due'])
        self.assertFalse(current['formation_due'])
        self.assertEqual(cohorts.form(self.vault, recovered_at + timedelta(minutes=1))['status'], 'unchanged')
        # Later recovery is invisible before its actual time; no frozen initial
        # or baseline is silently inserted into the old historical context.
        self.assertEqual(cohorts.context(self.vault, self.formed.isoformat()), old_context)
        bundle = self.bundle(symbols=('ABC', 'DEF', 'SPY'), baseline='2026-09-11', endpoint='2026-09-25',
                             cutoff='2026-09-26T11:30:00-04:00')
        bundle['sessions'] = calendar_fixture('2026-09-10', '2026-09-26')
        bundle['prices'][0]['query']['asof'] = '2026-09-10'
        result = cohorts.calculate(card, bundle, '2w')
        self.assertEqual(result['baseline_at'], '2026-09-11T13:30:00+00:00')
        self.assertEqual(result['target_date'], '2026-09-25')

    def test_recovery_keeps_original_assessment_before_later_decision(self):
        self.activate(); path = self.partial_pair(); self.legacy_partial_formation(path)
        newer = self.publish(group='rejected', as_of='2026-09-09T11:30:00-04:00')
        later = stamp('2026-09-10T11:40:00-04:00')
        result = cohorts.form(self.vault, later)
        current = cohorts.context(self.vault, later.isoformat())
        self.assertEqual(result['new_members'], 2)
        self.assertEqual(result['observations'], 1)
        self.assertEqual(result['processed_reports'], ['Investments/' + newer.name])
        initial = current['cohorts'][0]['members'][0]
        self.assertEqual(initial['disposition']['group'], 'watch')
        replay = cohorts._replay(self.vault, cohorts._events(self.vault), cohorts._reports(self.vault, later))
        self.assertEqual(replay[1]['NASDAQ:ABC']['group'], 'rejected')

    def test_later_v1_enrollment_is_preserved_and_only_remaining_omission_recovers(self):
        self.activate(); self.legacy_partial_formation(self.partial_pair())
        newer = self.publish(group='rejected', as_of='2026-09-09T11:30:00-04:00')
        later_v1_time = stamp('2026-09-09T11:40:00-04:00')
        reports = cohorts._reports(self.vault, later_v1_time)
        events = cohorts._events(self.vault)
        enrolled, latest, _, _ = cohorts._replay(self.vault, events, reports)
        report = next(row for row in reports if row['relative'].endswith(newer.name))
        legacy = cohorts._new('report', later_v1_time, events,
            source_report=report['relative'], source_sha256=report['sha256'],
            source_as_of=report['as_of'], published_at=report['generated_at'], formation_delay_seconds=300.0,
            cohort='feed-nominees-v1@' + report['sha256'][:24],
            **cohorts._derive(report, enrolled, events[0][1]['excluded_securities'], latest))
        cohorts.evidence.write(legacy, self.vault, cohorts.FOLDER)
        before = cohorts._events(self.vault)
        original = cohorts.context(self.vault, later_v1_time.isoformat())['cohorts'][0]
        later = stamp('2026-09-10T11:40:00-04:00')
        result = cohorts.form(self.vault, later)
        self.assertEqual((result['new_members'], result['recovered_members'], result['observations']), (1, 1, 0))
        current = cohorts.context(self.vault, later.isoformat())
        self.assertEqual(current['cohorts'][0], original)
        self.assertEqual(cohorts._events(self.vault)[:len(before)], before)
        self.assertEqual(current['cohorts'][1]['members'][0]['security'], 'NASDAQ:DEF')
        self.assertEqual(current['counts']['enrolled'], 2)
        # Recovery reads the older blocked report but cannot rewind the newer
        # source coverage census or an existing member's initial/latest group.
        self.assertEqual(current['counts']['unresolved_posts'], 0)
        latest = cohorts._replay(self.vault, cohorts._events(self.vault), cohorts._reports(self.vault, later))[1]
        self.assertEqual(latest['NASDAQ:ABC']['group'], 'rejected')

    def test_paused_partial_mapping_enrolls_only_after_its_job_is_published(self):
        self.activate()
        self.fixture.note(name='2026-09-08-113000-stock-research.md',
            posts=[self.fixture.post('pending', 'NASDAQ:ABC', due='2026-09-09T12:00:00-04:00')])
        self.assertEqual(cohorts.form(self.vault, self.formed)['new_members'], 0)
        self.publish(group='watch', disposition='blocked', as_of='2026-09-09T11:30:00-04:00')
        later = stamp('2026-09-09T11:40:00-04:00')
        self.assertEqual(cohorts.form(self.vault, later)['new_members'], 1)
        current = cohorts.context(self.vault, later.isoformat())
        self.assertEqual(current['cohorts'][0]['source_as_of'], '2026-09-09T11:30:00-04:00')
        self.assertEqual(current['cohorts'][0]['members'][0]['disposition']['group'], 'watch')
        self.assertEqual(current['counts']['unresolved_posts'], 1)

    def test_partial_nomination_never_reenrolls_activation_exclusions(self):
        path = self.partial_pair()
        cohorts.start(self.vault, self.formed)
        original = path.read_bytes()
        self.publish(group='watch', disposition='blocked', as_of='2026-09-09T11:30:00-04:00')
        later = stamp('2026-09-09T11:40:00-04:00')
        self.assertEqual(cohorts.form(self.vault, later)['new_members'], 0)
        self.assertEqual(cohorts.context(self.vault, later.isoformat())['counts']['enrolled'], 0)
        self.assertEqual(path.read_bytes(), original)

    def test_recovery_tampering_cannot_change_original_members_or_source(self):
        self.activate(); self.legacy_partial_formation(self.partial_pair())
        later = stamp('2026-09-10T11:40:00-04:00')
        cohorts.form(self.vault, later)
        digest, value = cohorts._events(self.vault)[-1]
        self.vault.joinpath(*cohorts.FOLDER, digest + '.json').unlink()
        value['members'] = value['members'][:1]
        cohorts.evidence.write(value, self.vault, cohorts.FOLDER)
        with self.assertRaisesRegex(ValueError, 'pool or initial decisions'):
            cohorts.context(self.vault, later.isoformat())

    def test_context_is_readonly_and_start_is_idempotent(self):
        before = {p.relative_to(self.vault): p.read_bytes() for p in self.vault.rglob('*') if p.is_file()}
        result = cohorts.context(self.vault, CUTOFF)
        self.assertTrue(result['launch_due'])
        self.assertEqual(before, {p.relative_to(self.vault): p.read_bytes() for p in self.vault.rglob('*') if p.is_file()})
        first = self.activate()
        self.assertEqual(cohorts.start(self.vault, self.formed)['status'], 'unchanged')
        self.assertEqual(len(cohorts._events(self.vault)), 1)
        self.assertEqual(cohorts.context(self.vault, CUTOFF)['launch_at'], first['launch_at'])

    def test_form_requires_activation_before_published_recommendations(self):
        self.publish()
        with self.assertRaisesRegex(ValueError, 'activate'):
            cohorts.form(self.vault, self.formed)
        cohorts.start(self.vault, self.formed)
        result = cohorts.form(self.vault, self.formed + timedelta(seconds=1))
        self.assertEqual(result['new_members'], 0)
        self.assertEqual(cohorts.context(self.vault, self.later)['counts']['enrolled'], 0)

    def test_queued_member_origin_and_timing_are_frozen_and_retry_is_unchanged(self):
        path, result, card = self.form_one()
        member = card['members'][0]
        self.assertEqual(member['disposition']['group'], 'unfinished')
        self.assertEqual(member['disposition']['work_state'], 'queued')
        self.assertEqual(member['origins'][0]['post_id'], '10')
        self.assertEqual(card['source_sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(card['recorded_at'], self.formed.isoformat())
        self.assertEqual(card['formation_delay_seconds'], 300)
        self.assertEqual(result['new_members'], 1)
        before = len(cohorts._events(self.vault))
        self.assertEqual(cohorts.form(self.vault, self.formed + timedelta(minutes=20))['status'], 'unchanged')
        self.assertEqual(len(cohorts._events(self.vault)), before)

    def test_blocked_and_rejected_are_retained_without_readiness_requirement(self):
        _, _, first = self.form_one(state='blocked')
        self.assertEqual(first['members'][0]['disposition']['work_state'], 'blocked')
        self.publish(ticker='DEF', group='rejected', as_of='2026-09-09T11:30:00-04:00')
        # Carry the old blocked queue to meet history continuity.
        path = self.vault / 'Investments/2026-09-09-113000-stock-research.md'
        data = path.read_text(encoding='utf-8')
        old = '| NASDAQ:ABC | ' + CUTOFF + ' | blocked | new | 2026-09-10T11:30:00-04:00 | 10 | - | Still blocked. |\n'
        data = re.sub(r'\n+### Candidate assessments', '\n' + old + '\n### Candidate assessments', data)
        path.write_text(data, encoding='utf-8')
        result = cohorts.form(self.vault, stamp('2026-09-09T11:40:00-04:00'))
        self.assertEqual(result['new_members'], 1)
        current = cohorts.context(self.vault, '2026-09-09T11:40:00-04:00')
        self.assertEqual(current['cohorts'][1]['members'][0]['disposition']['group'], 'rejected')

    def test_new_arguments_and_later_decisions_do_not_reenroll_or_relabel(self):
        _, _, card = self.form_one()
        self.publish(group='watch', as_of='2026-09-09T11:30:00-04:00', fingerprint='f' * 64)
        result = cohorts.form(self.vault, stamp('2026-09-09T11:40:00-04:00'))
        self.assertEqual(result['new_members'], 0)
        self.assertEqual(result['observations'], 1)
        current = cohorts.context(self.vault, '2026-09-10T11:30:00-04:00')
        self.assertEqual(current['cohorts'][0]['members'], card['members'])
        self.assertEqual(current['counts']['enrolled'], 1)

    def test_multiple_nominating_posts_dedupe_security_without_losing_origins(self):
        self.activate(); path = self.publish(sources='10, 11')
        data = path.read_text(encoding='utf-8')
        row = next(line for line in data.splitlines() if line.startswith('| https://x.com/'))
        path.write_text(data.replace(row, row + '\n' + row.replace('/10 |', '/11 |')), encoding='utf-8')
        self.assertEqual(cohorts.form(self.vault, self.formed)['new_members'], 1)
        members = cohorts.context(self.vault, self.formed.isoformat())['cohorts'][0]['members']
        self.assertEqual([row['post_id'] for row in members[0]['origins']], ['10', '11'])

    def test_altered_source_report_blocks_replay(self):
        path, _, _ = self.form_one()
        path.write_text(path.read_text(encoding='utf-8').replace('Verified lead.', 'Changed historical lead.'), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'source report.*changed'):
            cohorts.context(self.vault, self.later)

    def test_strategy_or_member_tampering_is_detected_even_with_new_digest(self):
        self.form_one()
        events = cohorts._events(self.vault)
        old_hash, changed = events[-1]
        changed['members'] = []
        old = self.vault.joinpath(*cohorts.FOLDER, old_hash + '.json')
        old.unlink()
        cohorts.evidence.write(changed, self.vault, cohorts.FOLDER)
        with self.assertRaisesRegex(ValueError, 'pool or initial decisions'):
            cohorts.context(self.vault, self.later)

    def test_fixed_two_week_price_math_spy_and_early_pending(self):
        card = self.frozen()
        result = cohorts.calculate(card, self.bundle(), '2w')
        self.assertEqual(result['state'], 'observed')
        self.assertEqual(result['baseline_at'], '2026-09-09T13:30:00+00:00')
        self.assertEqual(result['target_date'], '2026-09-23')
        self.assertAlmostEqual(result['groups']['all']['return_value'], 0.3)
        self.assertAlmostEqual(result['groups']['unfinished']['excess_spy'], 0.2)
        self.assertIsNone(result['groups']['ready']['return_value'])
        self.assertIsNone(result['ready_minus_pool'])
        early = self.bundle(cutoff='2026-09-23T11:30:00-04:00')
        self.assertEqual(cohorts.calculate(card, early, '2w')['state'], 'pending')
        evening = self.bundle(cutoff='2026-09-23T17:00:00-04:00')
        self.assertEqual(cohorts.calculate(card, evening, '2w')['state'], 'pending')

    def test_missing_benchmark_is_unavailable_never_zero(self):
        card = self.frozen()
        bundle = self.bundle()
        del bundle['prices'][0]['data']['bars']['SPY']
        result = cohorts.calculate(card, bundle, '2w')
        self.assertEqual(result['state'], 'unavailable')
        self.assertAlmostEqual(result['groups']['all']['return_value'], 0.3)
        self.assertIsNone(result['benchmark_return'])
        self.assertIsNone(result['groups']['all']['excess_spy'])

    def test_target_date_reviews_surface_due_work_before_and_after_close(self):
        card = self.frozen()
        before_target = cohorts.context(self.vault, '2026-09-22T17:00:00-04:00')
        self.assertEqual(before_target['due_checkpoints'], [])
        for cutoff in ('2026-09-23T11:30:00-04:00', '2026-09-23T17:00:00-04:00'):
            with self.subTest(cutoff=cutoff):
                current = cohorts.context(self.vault, cutoff)
                self.assertEqual([(row['cohort'], row['horizon'], row['target_not_before'])
                                  for row in current['due_checkpoints']], [(card['cohort'], '2w', '2026-09-23')])
                self.assertEqual(current['due_checkpoints'][0]['state'], 'pending')
                # A due candidate is not an observed close. Full daily bars are
                # still pending even after this session's scheduled close.
                observed = cohorts.evaluate(self.vault, card['cohort'], self.bundle(cutoff=cutoff),
                                            '2w', now=stamp(cutoff))
                self.assertEqual(observed['state'], 'pending')
                self.assertEqual(cohorts.context(self.vault, cutoff)['checkpoints'], [])
        next_day = cohorts.evaluate(self.vault, card['cohort'], self.bundle(cutoff='2026-09-24T11:30:00-04:00'),
                                    '2w', now=stamp('2026-09-24T11:30:00-04:00'))
        self.assertEqual(next_day['state'], 'observed')

    def test_due_lower_bound_on_weekend_does_not_invent_a_session(self):
        self.activate(); self.publish()
        friday = stamp('2026-09-11T11:40:00-04:00')
        cohorts.form(self.vault, friday)
        card = next(iter(cohorts._replay(self.vault, cohorts._events(self.vault),
                                        cohorts._reports(self.vault, friday))[2].values()))
        cutoff = '2026-09-26T17:00:00-04:00'
        current = cohorts.context(self.vault, cutoff)
        self.assertEqual(current['due_checkpoints'][0]['target_not_before'], '2026-09-26')
        self.assertIn('not a trading calendar', current['due_checkpoints'][0]['reason'])
        bundle = self.bundle(cutoff=cutoff, baseline='2026-09-14', endpoint='2026-09-28')
        bundle['prices'][0]['query']['asof'] = '2026-09-11'
        observed = cohorts.calculate(card, bundle, '2w')
        self.assertEqual(observed['state'], 'pending')
        self.assertEqual(observed['baseline_at'][:10], '2026-09-14')
        self.assertEqual(observed['target_date'], '2026-09-28')

    def test_delisted_missing_member_never_dropped_or_renormalized(self):
        card = self.frozen()
        extra = copy.deepcopy(card['members'][0]); extra['security'] = 'NASDAQ:DEF'
        extra['disposition']['group'] = 'ready'
        card['members'].append(extra)
        result = cohorts.calculate(card, self.bundle(), '2w')
        self.assertEqual(len(result['rows']), 2)
        self.assertEqual(result['groups']['all']['enrolled'], 2)
        self.assertEqual(result['groups']['all']['observed'], 1)
        self.assertIsNone(result['groups']['all']['return_value'])
        self.assertIsNone(result['groups']['ready']['return_value'])
        self.assertAlmostEqual(result['groups']['unfinished']['return_value'], 0.3)

    def test_ready_minus_pool_uses_same_original_cohort(self):
        card = self.frozen()
        extra = copy.deepcopy(card['members'][0]); extra['security'] = 'NASDAQ:DEF'
        extra['disposition']['group'] = 'ready'; card['members'].append(extra)
        bundle = self.bundle(('ABC', 'DEF', 'SPY'))
        bundle['prices'][0]['data']['bars']['DEF'][-1] = bar('2026-09-23', 150)
        result = cohorts.calculate(card, bundle, '2w')
        self.assertAlmostEqual(result['groups']['all']['return_value'], 0.4)
        self.assertAlmostEqual(result['ready_minus_pool'], 0.1)

    def test_unverified_action_or_wrong_mapping_cannot_create_observed_return(self):
        card = self.frozen()
        bundle = self.bundle(); bundle['corporate_actions'].pop('ABC')
        self.assertIsNone(cohorts.calculate(card, bundle, '2w')['groups']['all']['return_value'])
        bundle = self.bundle(); bundle['prices'][0]['query']['asof'] = '2026-09-09'
        with self.assertRaisesRegex(ValueError, 'mapping'):
            cohorts.calculate(card, bundle, '2w')

    def test_delayed_form_uses_actual_form_date_not_historical_report_date(self):
        self.activate(); self.publish()
        delayed = stamp('2026-09-15T11:40:00-04:00')
        cohorts.form(self.vault, delayed)
        card = next(iter(cohorts._replay(self.vault, cohorts._events(self.vault), cohorts._reports(self.vault, delayed))[2].values()))
        bundle = self.bundle(cutoff='2026-10-01T11:30:00-04:00', baseline='2026-09-16', endpoint='2026-09-30')
        bundle['prices'][0]['query']['asof'] = '2026-09-15'
        result = cohorts.calculate(card, bundle, '2w')
        self.assertEqual(result['baseline_at'][:10], '2026-09-16')
        self.assertGreater(result['formation_delay_seconds'], 6 * 86400)

    def test_unavailable_checkpoint_retains_full_census_and_can_resolve(self):
        card = self.frozen()
        missing = {'stock_nominee_input': 1, 'as_of': self.later, 'unavailable_reason': 'Saved provider evidence unavailable.'}
        first = cohorts.evaluate(self.vault, card['cohort'], missing, '2w', now=stamp(self.later))
        self.assertEqual(first['groups']['all']['enrolled'], 1)
        self.assertIsNone(first['rows'][0]['return_value'])
        result = cohorts.evaluate(self.vault, card['cohort'], self.bundle(), '2w', now=stamp(self.later))
        self.assertEqual(result['state'], 'observed')
        self.assertEqual(cohorts.evaluate(self.vault, card['cohort'], self.bundle(), '2w', now=stamp(self.later))['status'], 'unchanged')
        current = cohorts.context(self.vault, self.later)
        self.assertEqual(current['counts']['checkpoints_observed'], 1)
        self.assertEqual(len([value for _, value in cohorts._events(self.vault) if value['kind'] == 'checkpoint']), 2)

    def test_observed_correction_requires_exact_prior_evidence(self):
        card = self.frozen(); bundle = self.bundle()
        first = cohorts.evaluate(self.vault, card['cohort'], bundle, '2w', now=stamp(self.later))
        bundle['prices'][0]['data']['bars']['ABC'][-1] = bar('2026-09-23', 140)
        with self.assertRaisesRegex(ValueError, 'exact evidence'):
            cohorts.evaluate(self.vault, card['cohort'], bundle, '2w', now=stamp(self.later))
        corrected = cohorts.evaluate(self.vault, card['cohort'], bundle, '2w', first['evidence_attachment']['sha256'], now=stamp(self.later))
        self.assertAlmostEqual(corrected['groups']['all']['return_value'], 0.4)
        self.assertEqual(cohorts.context(self.vault, self.later)['counts']['checkpoints_observed'], 1)

    def test_symlinked_evidence_never_followed_or_overwritten(self):
        self.activate(); digest, _ = cohorts._events(self.vault)[0]
        path = self.vault.joinpath(*cohorts.FOLDER, digest + '.json')
        outside = self.fixture.root / 'outside.json'; original = path.read_bytes(); outside.write_bytes(original)
        path.unlink(); path.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'non-symlink'):
            cohorts.start(self.vault, self.formed)
        self.assertEqual(outside.read_bytes(), original)

    def test_two_competing_append_events_fail_visibly(self):
        self.activate(); events = cohorts._events(self.vault)
        # Valid content addressing alone does not make two successors ordered.
        for number in (1, 2):
            value = cohorts._new('checkpoint', self.formed, events, cohort=str(number), formation_sha256='a' * 64,
                                 horizon='2w', replaces=None, input={}, result={})
            cohorts.evidence.write(value, self.vault, cohorts.FOLDER)
        with self.assertRaisesRegex(ValueError, 'competing'):
            cohorts._events(self.vault)

    def test_cli_has_no_historical_write_clock_or_member_list(self):
        script = ROOT / 'skills/stock-research/scripts/stock_cohorts.py'
        for command in ('start', 'form'):
            result = subprocess.run([sys.executable, '-B', str(script), command, '--vault', str(self.vault),
                                     '--as-of', CUTOFF], capture_output=True, text=True, encoding='utf-8')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('unrecognized arguments', result.stderr)
        self.assertEqual(cohorts._events(self.vault), [])

    def test_existing_and_new_legacy_history_is_preserved_with_explicit_gap(self):
        old = self.fixture.note(as_of='2026-09-07T11:30:00-04:00', schema=1,
                                name='2026-09-07-113000-stock-research.md')
        old.write_text(old.read_text(encoding='utf-8').replace('stock_research:', 'market_research:').replace('# Stock research', '# Market research'), encoding='utf-8')
        before = old.read_bytes()
        self.activate()
        newer = self.fixture.note(schema=1, name='2026-09-08-113000-stock-research.md')
        result = cohorts.form(self.vault, self.formed)
        self.assertEqual(result['processed_reports'], ['Investments/' + newer.name])
        self.assertEqual(result['new_members'], 0)
        current = cohorts.context(self.vault, self.later)
        self.assertEqual(current['counts']['legacy_report_gaps'], 1)
        self.assertIsNone(current['counts']['unresolved_posts'])
        self.assertEqual(old.read_bytes(), before)

    def test_ready_is_initial_group_only_when_current_assessment_and_ledger_agree(self):
        _, _, card = self.form_one(group='ready')
        self.assertEqual(card['members'][0]['disposition']['group'], 'ready')
        self.assertEqual(card['initial_counts']['ready'], 1)

    def test_incomplete_calendar_and_wrong_first_endpoint_cannot_supply_returns(self):
        card = self.frozen(); bundle = self.bundle()
        bundle['sessions']['complete'] = False
        with self.assertRaises(ValueError):
            cohorts.calculate(card, bundle, '2w')
        bundle = self.bundle(endpoint='2026-09-24')
        result = cohorts.calculate(card, bundle, '2w')
        self.assertEqual(result['state'], 'unavailable')
        self.assertEqual(result['observed_at'][:10], '2026-09-23')
        self.assertIsNone(result['rows'][0]['return_value'])

    def test_calendar_closure_and_month_end_target_are_used_exactly(self):
        card = self.frozen()
        # A synthetic closure on the otherwise first following session moves
        # every original member and SPY together, using the retained calendar.
        bundle = self.bundle(baseline='2026-09-10', endpoint='2026-09-24')
        bundle['sessions']['data']['sessions'] = [row for row in bundle['sessions']['data']['sessions'] if row['date'] != '2026-09-09']
        result = cohorts.calculate(card, bundle, '2w')
        self.assertEqual(result['baseline_at'][:10], '2026-09-10')
        self.assertEqual(result['target_date'], '2026-09-24')
        self.assertEqual(market_notes.horizon_target(stamp('2026-01-31T10:00:00Z').date(), '1m').isoformat(), '2026-02-28')

    def test_competing_supported_writer_is_blocked_before_any_append(self):
        import fcntl
        import os
        descriptor = os.open(self.vault, os.O_RDONLY)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, 'another market publication'):
                self.activate()
            self.assertEqual(cohorts._events(self.vault), [])
        finally:
            os.close(descriptor)

    def test_boolean_version_and_unknown_fields_are_rejected(self):
        self.activate(); digest, value = cohorts._events(self.vault)[0]
        path = self.vault.joinpath(*cohorts.FOLDER, digest + '.json'); path.unlink()
        value['stock_nominees'] = True
        cohorts.evidence.write(value, self.vault, cohorts.FOLDER)
        with self.assertRaisesRegex(ValueError, 'invalid nominee event'):
            cohorts._events(self.vault)


if __name__ == '__main__':
    unittest.main()
