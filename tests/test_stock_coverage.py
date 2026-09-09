#!/usr/bin/env python3
"""Immutable coverage accounting over real local feed fixtures; no network."""
import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/stock-research/scripts'))
import stock_coverage as coverage
import stock_feed
import market_notes

CUTOFF = '2026-09-08T11:30:00-04:00'
LATER = '2026-09-08T12:00:00-04:00'
PUBLISHED = '2026-09-08T14:00:00Z'


def table(title, rows=()):
    fields = coverage.TABLES[title]
    return ('#### ' + title + '\n\n| ' + ' | '.join(fields) + ' |\n|'
            + '|'.join('---' for _ in fields) + '|\n'
            + ''.join('| ' + ' | '.join(row[field] for field in fields) + ' |\n' for row in rows))


class CoverageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='stock-coverage-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.vault = self.root / 'vault'
        (self.vault / 'Investments/Sources/X').mkdir(parents=True)
        (self.vault / 'Investments/Sources/.feed-collect').mkdir()
        (self.vault / 'Investments/x-accounts.md').write_text('- [x] @Example\n', encoding='utf-8')
        self.account = {'id': '1', 'handle': 'Example', 'filename': 'example.md',
                        'posts': {'10': {'id': '10', 'created_at': PUBLISHED,
                                         'first_retrieved_at': '2026-09-08T14:01:00Z',
                                         'last_checked_at': '2026-09-08T14:01:00Z',
                                         'status': 'available', 'text': '$ABC has a verified claim to investigate.',
                                         'references': [], 'assets': []}},
                        'window': None, 'completed_at': '2026-09-08T15:00:00Z', 'since_id': None,
                        'gaps': [], 'published_sha256': None, 'requested_since': '2026-09-01T00:00:00Z',
                        'requested_through': '2026-09-08T15:00:00Z', 'history_before': '2026-09-01T00:00:00Z'}
        self.publish_feed()
        self.draft = self.root / 'draft.md'

    def publish_feed(self):
        raw = stock_feed.feed.render(self.account, {}).encode('utf-8')
        (self.vault / 'Investments/Sources/X/example.md').write_bytes(raw)
        self.account['published_sha256'] = stock_feed.feed.digest(raw)
        state = {'schema': 1, 'accounts': {'example': self.account}, 'requests': [],
                 'pending': None, 'round_robin': 0, 'assets': {}}
        (self.vault / stock_feed.STATE).write_bytes(stock_feed.feed.encoded(state))

    def post(self, disposition='nominated', securities='NASDAQ:ABC', due='-', reason='Verified lead.'):
        source = stock_feed.context(self.vault, CUTOFF)['posts'][0]
        return {'Post': source['source_url'], 'Fingerprint': coverage.fingerprint(source),
                'Published': source['created_at'], 'Disposition': disposition, 'Securities': securities,
                'Due': due, 'Reason': reason}

    def job(self, state='queued', due='2026-09-09T12:00:00-04:00', assessment='-', source='10', **changes):
        value = {'Security': 'NASDAQ:ABC', 'First seen': CUTOFF, 'State': state, 'Priority': 'new',
                 'Due': due, 'Sources': source, 'Assessment': assessment, 'Reason': 'Needs issuer verification.'}
        value.update(changes)
        return value

    def note(self, *, as_of=CUTOFF, posts=(), jobs=(), history=(), candidates=False,
             ledger='No active theses.', schema=2, limit='limited', generated=None, name=None):
        date = market_notes.ny_now(coverage._time(as_of)).date().isoformat()
        generated = generated or (coverage._time(as_of) + coverage.timedelta(minutes=5)).isoformat()
        detail = ('#### NASDAQ:ABC — Example Inc.\n\nStatus: watch\n\n[[Investments/Stocks/ABC]]\n\n'
                  'The primary evidence remains preliminary; verify next earnings.\n') if candidates else 'No substantive assessments.\n'
        screening = '\n\n'.join(table(title, rows) for title, rows in (
            ('Coverage history', history), ('Feed dispositions', posts), ('Research queue', jobs))) if schema == 2 else 'Legacy notes mention ABC; review deferred company identity.'
        body = ('---\nstock_research: ' + str(schema) + '\ndate: ' + date + '\nas_of: "' + as_of
                + '"\ngenerated_at: "' + generated + '"\nsession: intraday\ncoverage: ' + limit
                + '\n---\n\n# Stock research — ' + date + '\n\n## Decision brief\n\nLimited fixture research.\n\n'
                '### Buying opportunities\n\nNo readiness claim.\n\n### Next checks\n\nVerify the next event.\n\n'
                '## Research record\n\n### Screening and sources\n\n' + screening
                + '\n\n### Candidate assessments\n\n' + detail + '\n\n### Thesis updates\n\n' + ledger
                + '\n\n### Outcome review\n\nNo observations are due.\n')
        path = self.vault / 'Investments' / name if name else self.draft
        path.write_text(body, encoding='utf-8')
        return path

    def archive(self, **kwargs):
        as_of = kwargs.get('as_of', CUTOFF)
        stamp = market_notes.ny_now(coverage._time(as_of))
        name = stamp.strftime('%Y-%m-%d-%H%M%S-stock-research.md')
        return self.note(name=name, **kwargs)

    def anchors(self, cutoff=LATER):
        return coverage.context(self.vault, cutoff)['required_history']

    def test_new_posts_need_disposition(self):
        with self.assertRaisesRegex(ValueError, 'every new or changed'):
            coverage.check(self.vault, self.note(), CUTOFF)

    def test_all_new_nominations_need_research_disposition(self):
        with self.assertRaisesRegex(ValueError, 'needs a research disposition'):
            coverage.check(self.vault, self.note(posts=[self.post()]), CUTOFF)

    def test_capacity_is_incomplete_but_valid_and_read_only(self):
        note = self.note(posts=[self.post()], jobs=[self.job()])
        before = {p.relative_to(self.vault): p.read_bytes() for p in self.vault.rglob('*') if p.is_file()}
        with patch.object(stock_feed.feed, 'collect', side_effect=AssertionError('no collection')):
            result = coverage.check(self.vault, note, CUTOFF)
        self.assertTrue(result['complete'])
        self.assertFalse(result['research_complete'])
        self.assertEqual(result['counts']['queued'], 1)
        self.assertEqual(before, {p.relative_to(self.vault): p.read_bytes() for p in self.vault.rglob('*') if p.is_file()})

    def test_normal_cannot_hide_deferred_work(self):
        with self.assertRaisesRegex(ValueError, 'normal coverage'):
            coverage.check(self.vault, self.note(posts=[self.post()], jobs=[self.job()], limit='normal'), CUTOFF)

    def test_unidentified_post_remains_unresolved_without_fabricated_security(self):
        post = self.post('pending', '-', due='2026-09-09T12:00:00-04:00', reason='Identity remains ambiguous.')
        result = coverage.check(self.vault, self.note(posts=[post]), CUTOFF)
        self.assertEqual(result['counts']['unresolved_posts'], 1)

    def test_unresolved_post_requires_retry(self):
        with self.assertRaisesRegex(ValueError, 'retry timestamp'):
            coverage.parse(self.note(posts=[self.post('blocked', '-')]).read_bytes())

    def test_queue_cannot_disappear_on_same_day_repeat(self):
        self.archive(posts=[self.post()], jobs=[self.job()])
        context = coverage.context(self.vault, LATER)
        self.assertFalse(context['new_or_changed_posts'])
        self.assertEqual(context['work'][0]['security'], 'NASDAQ:ABC')
        with self.assertRaisesRegex(ValueError, 'unfinished/due'):
            coverage.check(self.vault, self.note(as_of=LATER, history=context['required_history']), LATER)

    def test_pending_post_cannot_disappear(self):
        self.archive(posts=[self.post('blocked', '-', due=LATER)])
        with self.assertRaisesRegex(ValueError, 'unfinished feed'):
            coverage.check(self.vault, self.note(as_of=LATER, history=self.anchors()), LATER)

    def test_old_pending_source_extends_saved_window(self):
        pending = self.post('blocked', '-', due=LATER)
        self.archive(posts=[pending])
        result = coverage.context(self.vault, '2026-09-13T12:00:00-04:00')
        self.assertEqual(coverage._time(result['since']), coverage._time(PUBLISHED))
        self.assertTrue(result['unresolved_posts'][0]['source_available'])

    def test_disappeared_post_carries_blocker(self):
        pending = self.post('blocked', '-', due=LATER)
        self.archive(posts=[pending])
        self.account['posts'] = {}
        self.publish_feed()
        context = coverage.context(self.vault, LATER)
        self.assertFalse(context['unresolved_posts'][0]['source_available'])
        result = coverage.check(self.vault, self.note(as_of=LATER, posts=[pending], history=context['required_history']), LATER)
        self.assertEqual(result['counts']['unresolved_posts'], 1)

    def test_disappeared_post_cannot_become_new_nomination(self):
        pending = self.post('blocked', '-', due=LATER)
        self.archive(posts=[pending])
        self.account['posts'] = {}
        self.publish_feed()
        changed = dict(pending, Disposition='nominated', Securities='NASDAQ:ABC')
        with self.assertRaisesRegex(ValueError, 'eligible current'):
            coverage.check(self.vault, self.note(as_of=LATER, posts=[changed], jobs=[self.job()], history=self.anchors()), LATER)

    def test_legacy_requires_explicit_hash_bound_bootstrap(self):
        self.archive(schema=1)
        context = coverage.context(self.vault, LATER)
        self.assertTrue(context['bootstrap_required'])
        with self.assertRaisesRegex(ValueError, 'prior report hashes'):
            coverage.check(self.vault, self.note(as_of=LATER, posts=[self.post('no-idea', '-')]), LATER)
        result = coverage.check(self.vault, self.note(as_of=LATER, posts=[self.post('no-idea', '-')], history=context['required_history']), LATER)
        self.assertTrue(result['bootstrap_reviewed'])

    def test_invalid_hash_anchor_refused(self):
        self.archive(schema=1)
        anchors = self.anchors()
        anchors[0]['SHA256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'prior report hashes'):
            coverage.check(self.vault, self.note(as_of=LATER, history=anchors), LATER)

    def test_history_chain_detects_changed_predecessor(self):
        first = self.archive(posts=[self.post('no-idea', '-')])
        anchors = self.anchors()
        self.archive(as_of=LATER, history=anchors)
        first.write_text(first.read_text(encoding='utf-8').replace('Limited fixture research.', 'Edited fixture research.'), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'anchor is missing, changed'):
            coverage.context(self.vault, '2026-09-08T13:00:00-04:00')

    def test_history_chain_detects_deleted_predecessor(self):
        first = self.archive(posts=[self.post('no-idea', '-')])
        self.archive(as_of=LATER, history=self.anchors())
        first.unlink()
        with self.assertRaisesRegex(ValueError, 'anchor is missing, changed'):
            coverage.context(self.vault, '2026-09-08T13:00:00-04:00')

    def test_future_cutoff_and_generation_are_not_reused(self):
        self.archive(schema=1, as_of='2026-09-09T11:30:00-04:00')
        self.archive(schema=1, generated='2026-09-08T14:00:00-04:00')
        result = coverage.context(self.vault, LATER)
        self.assertEqual(result['required_history'], [])
        self.assertFalse(result['bootstrap_required'])

    def test_assessed_requires_actual_candidate_section(self):
        link = '[[Investments/2026-09-08-113000-stock-research#NASDAQ:ABC — Example Inc.]]'
        with self.assertRaisesRegex(ValueError, 'exact substantive Candidate'):
            coverage.check(self.vault, self.note(posts=[self.post()], jobs=[self.job('assessed', '-', link)]), CUTOFF)
        result = coverage.check(self.vault, self.note(posts=[self.post()], jobs=[self.job('assessed', '-', link)], candidates=True), CUTOFF)
        self.assertEqual(result['counts']['substantive_assessments'], 1)
        self.assertTrue(result['research_complete'])

    def test_assessment_link_binds_exact_edition(self):
        link = '[[Investments/2026-09-08-stock-research#NASDAQ:ABC — Example Inc.]]'
        note = self.note(posts=[self.post()], jobs=[self.job('assessed', '-', link)], candidates=True)
        with self.assertRaisesRegex(ValueError, 'exact substantive Candidate'):
            coverage.check(self.vault, note, CUTOFF)
        self.assertTrue(coverage.check(self.vault, note, CUTOFF, edition='2026-09-08-stock-research.md')['complete'])

    def test_unchanged_reuse_needs_verified_earlier_assessment_and_freshness(self):
        link = '[[Investments/2026-09-08-113000-stock-research#NASDAQ:ABC — Example Inc.]]'
        self.archive(posts=[self.post()], jobs=[self.job('assessed', assessment=link)], candidates=True)
        note = self.note(as_of=LATER, jobs=[self.job('reused', assessment=link)], history=self.anchors())
        result = coverage.check(self.vault, note, LATER)
        self.assertEqual(result['counts']['reused'], 1)

    def test_reuse_cannot_replace_due_check(self):
        link = '[[Investments/2026-09-08-113000-stock-research#NASDAQ:ABC — Example Inc.]]'
        self.archive(posts=[self.post()], jobs=[self.job('assessed', due=LATER, assessment=link)], candidates=True)
        with self.assertRaisesRegex(ValueError, 'due or unestablished'):
            coverage.check(self.vault, self.note(as_of=LATER, jobs=[self.job('reused', assessment=link)], history=self.anchors()), LATER)

    def test_changed_post_gets_new_fingerprint_and_disposition(self):
        self.archive(posts=[self.post('no-idea', '-')])
        self.account['posts']['10']['text'] = 'New substantive claim: $ABC.'
        self.account['posts']['10']['last_checked_at'] = '2026-09-08T15:40:00Z'
        self.publish_feed()
        context = coverage.context(self.vault, LATER)
        self.assertEqual(context['counts']['new_or_changed_posts'], 1)
        with self.assertRaisesRegex(ValueError, 'new or changed'):
            coverage.check(self.vault, self.note(as_of=LATER, history=context['required_history']), LATER)

    def test_unknown_post_id_cannot_nominate_stock(self):
        post = self.post()
        post['Post'] = 'https://x.com/i/web/status/99'
        with self.assertRaises(ValueError):
            coverage.check(self.vault, self.note(posts=[post], jobs=[self.job()]), CUTOFF)

    def test_changed_first_seen_refused(self):
        self.archive(posts=[self.post()], jobs=[self.job()])
        with self.assertRaisesRegex(ValueError, 'preserve first-seen'):
            coverage.check(self.vault, self.note(as_of=LATER, jobs=[self.job(**{'First seen': LATER})], history=self.anchors()), LATER)

    def test_every_active_security_requires_disposition(self):
        ledger = '| Thesis | State | Update / next check |\n|---|---|---|\n| NASDAQ:ABC@2026-09-08 | watch | Verify next event. |'
        self.archive(schema=1, ledger=ledger, candidates=True)
        with self.assertRaisesRegex(ValueError, 'every active security'):
            coverage.check(self.vault, self.note(as_of=LATER, posts=[self.post('no-idea', '-')], history=self.anchors(), ledger=ledger), LATER)

    def test_schema_two_rejects_missing_journals(self):
        note = self.note(schema=1)
        raw = note.read_bytes().replace(b'stock_research: 1', b'stock_research: 2')
        with self.assertRaisesRegex(ValueError, 'all three coverage journals'):
            coverage.parse(raw)

    def test_wrong_section_journal_refused(self):
        note = self.note()
        raw = note.read_text(encoding='utf-8').replace('### Screening and sources\n\n', '### Screening and sources\n\nSource context.\n\n')
        raw = raw.replace(table('Coverage history'), '').replace('### Outcome review\n\n', '### Outcome review\n\n' + table('Coverage history') + '\n\n')
        with self.assertRaisesRegex(ValueError, 'unique exact H4'):
            coverage.parse(raw.encode('utf-8'))

    def test_supplied_snapshot_must_match_verified_sources(self):
        snapshot = stock_feed.context(self.vault, CUTOFF)
        self.assertTrue(coverage.context(self.vault, CUTOFF, feed_snapshot=snapshot)['complete'])
        changed = copy.deepcopy(snapshot)
        changed['posts'][0]['text'] = 'Forged post.'
        with self.assertRaisesRegex(ValueError, 'no longer matches'):
            coverage.context(self.vault, CUTOFF, feed_snapshot=changed)

    def test_bad_fingerprint_rejected(self):
        post = self.post('no-idea', '-')
        post['Fingerprint'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'fingerprint/publication'):
            coverage.check(self.vault, self.note(posts=[post]), CUTOFF)

    def test_sparse_legacy_source_cannot_adopt_unmentioned_company(self):
        self.archive(schema=1)
        row = self.job(source='legacy:2026-09-08-113000-stock-research.md', Security='NASDAQ:XYZ')
        with self.assertRaisesRegex(ValueError, 'does not contain'):
            coverage.check(self.vault, self.note(as_of=LATER, posts=[self.post('no-idea', '-')], jobs=[row], history=self.anchors()), LATER)

    def test_unavailable_feed_preserves_prior_queue_and_can_publish_limited(self):
        self.archive(posts=[self.post()], jobs=[self.job()])
        (self.vault / 'Investments/x-accounts.md').unlink()
        context = coverage.context(self.vault, LATER)
        self.assertEqual(context['feed_status'], 'unavailable')
        self.assertIn('x-accounts.md', context['intake_error'])
        self.assertEqual(context['work'][0]['security'], 'NASDAQ:ABC')
        result = coverage.check(self.vault, self.note(as_of=LATER, jobs=[self.job('blocked')], history=context['required_history']), LATER)
        self.assertTrue(result['complete'])
        self.assertFalse(result['research_complete'])

    def test_empty_unavailable_feed_is_not_complete_research(self):
        (self.vault / 'Investments/x-accounts.md').unlink()
        result = coverage.check(self.vault, self.note(), CUTOFF)
        self.assertTrue(result['complete'])
        self.assertFalse(result['research_complete'])

    def test_malformed_media_and_encoding_leave_queue_available(self):
        self.archive(posts=[self.post()], jobs=[self.job()])
        for failure in (stock_feed.feed.feed_media.MediaError('invalid_attachment_fixture'),
                        UnicodeError('invalid_utf8_fixture')):
            with self.subTest(failure=type(failure).__name__), patch.object(stock_feed, 'context', side_effect=failure):
                result = coverage.context(self.vault, LATER)
                self.assertEqual(result['feed_status'], 'unavailable')
                self.assertEqual(result['work'][0]['security'], 'NASDAQ:ABC')
                self.assertIn('fixture', result['intake_error'])

    def test_inactive_unchanged_reuse_without_monitoring_due_is_valid(self):
        link = '[[Investments/2026-09-08-113000-stock-research#NASDAQ:ABC — Example Inc.]]'
        self.archive(posts=[self.post()], jobs=[self.job('assessed', '-', link)], candidates=True)
        result = coverage.check(self.vault, self.note(as_of=LATER, jobs=[self.job('reused', '-', link)], history=self.anchors()), LATER)
        self.assertEqual(result['counts']['reused'], 1)

    def test_new_active_security_requires_monitoring_disposition(self):
        ledger = '| Thesis | State | Update / next check |\n|---|---|---|\n| NASDAQ:ABC@2026-09-08 | watch | Verify next event. |'
        with self.assertRaisesRegex(ValueError, 'every active security'):
            coverage.check(self.vault, self.note(posts=[self.post('no-idea', '-')], ledger=ledger), CUTOFF)

    def test_ready_cannot_remain_ready_when_confirmation_blocked(self):
        ledger = '| Thesis | State | Update / next check |\n|---|---|---|\n| NASDAQ:ABC@2026-09-08 | ready | Verify next event. |'
        with self.assertRaisesRegex(ValueError, 'cannot retain ready'):
            coverage.check(self.vault, self.note(posts=[self.post()], jobs=[self.job('blocked')], ledger=ledger), CUTOFF)

    def test_partial_current_assessment_can_remain_blocked_after_watch_downgrade(self):
        old_ledger = '| Thesis | State | Update / next check |\n|---|---|---|\n| NASDAQ:ABC@2026-09-08 | ready | Verify next event. |'
        ledger = old_ledger.replace('| ready |', '| watch |')
        self.archive(schema=1, candidates=True, ledger=old_ledger)
        link = '[[Investments/2026-09-08-120000-stock-research#NASDAQ:ABC — Example Inc.]]'
        result = coverage.check(self.vault, self.note(as_of=LATER, posts=[self.post()], candidates=True,
            jobs=[self.job('blocked', assessment=link)], ledger=ledger, history=self.anchors()), LATER)
        self.assertTrue(result['complete'])
        self.assertFalse(result['research_complete'])
        self.assertEqual(result['counts']['substantive_assessments'], 1)
        self.assertEqual(result['counts']['completed_assessments'], 0)

    def test_next_day_active_reuse_cannot_skip_daily_monitoring(self):
        ledger = '| Thesis | State | Update / next check |\n|---|---|---|\n| NASDAQ:ABC@2026-09-08 | watch | Verify next event. |'
        link = '[[Investments/2026-09-08-113000-stock-research#NASDAQ:ABC — Example Inc.]]'
        due = '2026-09-15T11:30:00-04:00'
        self.archive(posts=[self.post()], jobs=[self.job('assessed', due, link)], candidates=True, ledger=ledger)
        tomorrow = '2026-09-09T11:30:00-04:00'
        with self.assertRaisesRegex(ValueError, 'freshness check'):
            coverage.check(self.vault, self.note(as_of=tomorrow, jobs=[self.job('reused', due, link)],
                history=self.anchors(tomorrow), ledger=ledger), tomorrow)

    def test_active_reuse_does_not_refresh_checked_time(self):
        ledger = '| Thesis | State | Update / next check |\n|---|---|---|\n| NASDAQ:ABC@2026-09-08 | watch | Verify next event. |'
        link = '[[Investments/2026-09-08-113000-stock-research#NASDAQ:ABC — Example Inc.]]'
        due = '2026-09-15T11:30:00-04:00'
        self.archive(posts=[self.post()], jobs=[self.job('assessed', due, link)], candidates=True, ledger=ledger)
        self.archive(as_of=LATER, jobs=[self.job('reused', due, link)], history=self.anchors(), ledger=ledger)
        state = coverage._state(self.vault, '2026-09-08T13:00:00-04:00')
        self.assertEqual(state[3]['NASDAQ:ABC']['checked_at'], CUTOFF)

    def test_removed_account_pending_post_is_retained_without_new_account_posts(self):
        pending = self.post('blocked', '-', due=LATER)
        self.archive(posts=[pending])
        (self.vault / 'Investments/x-accounts.md').write_text('- [ ] @Example\n', encoding='utf-8')
        self.account['posts']['11'] = dict(self.account['posts']['10'], id='11', text='$XYZ is a new stock.')
        self.publish_feed()
        context = coverage.context(self.vault, LATER)
        self.assertTrue(context['unresolved_posts'][0]['source_available'])
        self.assertEqual(context['counts']['unresolved_posts'], 1)
        self.assertEqual(context['counts']['eligible_posts'], 1)
        self.assertFalse(context['new_or_changed_posts'])
        self.assertEqual(context['retained_sources'][0]['origin'], 'retained_prior_source')
        resolved = dict(pending, Disposition='nominated', Securities='NASDAQ:ABC', Due='-', Reason='The retained original resolves its identity.')
        result = coverage.check(self.vault, self.note(as_of=LATER, posts=[resolved], jobs=[self.job()], history=context['required_history']), LATER)
        self.assertEqual(result['counts']['unresolved_posts'], 0)

    def test_missing_retained_pending_post_cannot_be_excluded_just_for_disappearing(self):
        pending = self.post('blocked', '-', due=LATER)
        self.archive(posts=[pending])
        self.account['posts'] = {}
        self.publish_feed()
        context = coverage.context(self.vault, LATER)
        excluded = dict(pending, Disposition='excluded', Due='-', Reason='The source disappeared.')
        with self.assertRaisesRegex(ValueError, 'eligible current'):
            coverage.check(self.vault, self.note(as_of=LATER, posts=[excluded], history=context['required_history']), LATER)

    def test_new_post_repeating_an_assessed_argument_can_reuse_verified_research(self):
        link = '[[Investments/2026-09-08-113000-stock-research#NASDAQ:ABC — Example Inc.]]'
        self.archive(posts=[self.post()], jobs=[self.job('assessed', assessment=link)], candidates=True)
        source = dict(self.account['posts']['10'], id='11', text='$ABC repeats its earlier argument.',
                      created_at='2026-09-08T15:40:00Z', first_retrieved_at='2026-09-08T15:41:00Z',
                      last_checked_at='2026-09-08T15:41:00Z')
        self.account['posts']['11'] = source
        self.publish_feed()
        eligible = stock_feed.context(self.vault, LATER)['posts'][-1]
        post = {'Post': eligible['source_url'], 'Fingerprint': coverage.fingerprint(eligible), 'Published': eligible['created_at'],
                'Disposition': 'repeated', 'Securities': 'NASDAQ:ABC', 'Due': '-', 'Reason': 'Repeated unchanged argument.'}
        result = coverage.check(self.vault, self.note(as_of=LATER, posts=[post], jobs=[self.job('reused', assessment=link, source='10, 11')], history=self.anchors()), LATER)
        self.assertEqual(result['counts']['reused'], 1)

    def test_quarantined_legacy_assessment_is_not_accepted_by_rehashing(self):
        import stock_dossiers
        old = self.archive(schema=1, candidates=True)
        link = '[[Investments/2026-09-08-113000-stock-research#NASDAQ:ABC — Example Inc.]]'
        note = self.note(as_of=LATER, posts=[self.post('repeated')], jobs=[self.job('reused', '-', link)], history=self.anchors())
        audit = {'history': [], 'history_diagnostics': [{'daily_note': 'Investments/' + old.name, 'reason': 'changed'}]}
        with patch.object(stock_dossiers, 'context', return_value=audit):
            with self.assertRaisesRegex(ValueError, 'quarantined without verified original'):
                coverage.check(self.vault, note, LATER)

    def test_verified_preserved_original_can_support_legacy_reuse(self):
        import stock_dossiers
        old = self.archive(schema=1, candidates=True)
        raw = old.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        archive = self.vault / 'Investments/.stock-research/dossiers/evidence' / (digest + '.md')
        archive.parent.mkdir(parents=True)
        archive.write_bytes(raw)
        link = '[[' + str(archive.relative_to(self.vault)) + '#NASDAQ:ABC — Example Inc.]]'
        note = self.note(as_of=LATER, posts=[self.post('repeated')], jobs=[self.job('reused', '-', link)], history=self.anchors())
        audit = {'history': [{'daily_note': 'Investments/' + old.name, 'daily_sha256': digest,
                              'evidence_note': str(archive.relative_to(self.vault)),
                              'as_of': CUTOFF, 'generated_at': '2026-09-08T11:35:00-04:00'}],
                 'history_diagnostics': [{'daily_note': 'Investments/' + old.name, 'reason': 'changed'}]}
        with patch.object(stock_dossiers, 'context', return_value=audit):
            self.assertEqual(coverage.check(self.vault, note, LATER)['counts']['reused'], 1)

    def test_quarantined_public_link_cannot_be_validated_with_different_archive(self):
        import stock_dossiers
        old = self.archive(schema=1, candidates=True)
        raw = old.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        archive = self.vault / 'Investments/.stock-research/dossiers/evidence' / (digest + '.md')
        archive.parent.mkdir(parents=True)
        archive.write_bytes(raw)
        old.write_text(old.read_text(encoding='utf-8').replace('#### NASDAQ:ABC — Example Inc.', '#### Altered public section'), encoding='utf-8')
        link = '[[Investments/2026-09-08-113000-stock-research#NASDAQ:ABC — Example Inc.]]'
        note = self.note(as_of=LATER, posts=[self.post('repeated')], jobs=[self.job('reused', '-', link)], history=self.anchors())
        audit = {'history': [{'daily_note': 'Investments/' + old.name, 'daily_sha256': digest,
                              'evidence_note': str(archive.relative_to(self.vault)),
                              'as_of': CUTOFF, 'generated_at': '2026-09-08T11:35:00-04:00'}],
                 'history_diagnostics': [{'daily_note': 'Investments/' + old.name, 'path': 'Investments/' + old.name, 'reason': 'changed'}]}
        with patch.object(stock_dossiers, 'context', return_value=audit):
            with self.assertRaisesRegex(ValueError, 'link the verified archive original'):
                coverage.check(self.vault, note, LATER)

    def test_orphan_archive_cannot_establish_reuse(self):
        old = self.archive(schema=1, candidates=True)
        digest = hashlib.sha256(old.read_bytes()).hexdigest()
        archive = self.vault / 'Investments/.stock-research/dossiers/evidence' / (digest + '.md')
        archive.parent.mkdir(parents=True)
        archive.write_bytes(old.read_bytes())
        link = '[[' + str(archive.relative_to(self.vault)) + '#NASDAQ:ABC — Example Inc.]]'
        note = self.note(as_of=LATER, posts=[self.post('repeated')], jobs=[self.job('reused', '-', link)], history=self.anchors())
        with self.assertRaisesRegex(ValueError, 'security-bound receipt'):
            coverage.check(self.vault, note, LATER)

    def test_old_capacity_source_extends_window(self):
        self.archive(posts=[self.post()], jobs=[self.job()])
        result = coverage.context(self.vault, '2026-09-13T12:00:00-04:00')
        self.assertEqual(coverage._time(result['since']), coverage._time(PUBLISHED))

    def test_explicit_closure_can_follow_verified_new_screening_exclusion(self):
        self.archive(posts=[self.post()], jobs=[self.job()])
        exclusion = self.post('excluded', '-', reason='Verified ineligible security class.')
        result = coverage.check(self.vault, self.note(as_of=LATER, posts=[exclusion], jobs=[self.job('closed', '-')], history=self.anchors()), LATER)
        self.assertTrue(result['research_complete'])

    def test_new_declared_material_argument_cannot_be_only_monitored(self):
        self.archive(schema=1, candidates=True)
        link = '[[Investments/2026-09-08-113000-stock-research#NASDAQ:ABC — Example Inc.]]'
        with self.assertRaisesRegex(ValueError, 'declared new/material'):
            coverage.check(self.vault, self.note(as_of=LATER, posts=[self.post()],
                jobs=[self.job('monitored', assessment=link)], history=self.anchors()), LATER)

    def test_unfinished_source_associations_cannot_be_dropped_at_completion(self):
        self.account['posts']['11'] = dict(self.account['posts']['10'], id='11', text='$ABC has another argument.')
        self.publish_feed()
        first = self.post()
        second = dict(first, Post='https://x.com/i/web/status/11',
                      Fingerprint=coverage.fingerprint(stock_feed.context(self.vault, CUTOFF)['posts'][1]))
        self.archive(posts=[first, second], jobs=[self.job(source='10, 11')])
        link = '[[Investments/2026-09-08-120000-stock-research#NASDAQ:ABC — Example Inc.]]'
        with self.assertRaisesRegex(ValueError, 'every source association'):
            coverage.check(self.vault, self.note(as_of=LATER, jobs=[self.job('assessed', '-', link)],
                candidates=True, history=self.anchors()), LATER)

    def test_legacy_report_after_structured_history_needs_new_bridge_review(self):
        self.archive(posts=[self.post('no-idea', '-')])
        self.archive(as_of=LATER, schema=1)
        later = '2026-09-08T13:00:00-04:00'
        context = coverage.context(self.vault, later)
        self.assertTrue(context['bootstrap_required'])
        self.assertEqual(len(context['required_history']), 2)
        with self.assertRaisesRegex(ValueError, 'prior report hashes'):
            coverage.check(self.vault, self.note(as_of=later, history=context['required_history'][:1]), later)
        result = coverage.check(self.vault, self.note(as_of=later, history=context['required_history']), later)
        self.assertTrue(result['bootstrap_reviewed'])


if __name__ == '__main__':
    unittest.main()
