#!/usr/bin/env python3
"""Independent offline forward tests for paid X collection and vault safety."""
from copy import deepcopy
import html
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/feed-collect/scripts'))
import feed_collect as feed

RECORD = {'skill': 'investments:feed-collect', 'plugin_version': '1.7.0',
          'source_commit': None, 'source_url': None, 'source_status': 'uncommitted',
          'runtime_sha256': '0' * 64}
FIRST = '2026-09-07T12:00:00Z'
LATER = '2026-09-07T14:00:00Z'


def post(identity, created='2026-09-07T11:00:00Z', text='Literal source post.'):
    return {'id': str(identity), 'author_id': '12', 'created_at': created, 'text': text}


def page(rows, next_token=None):
    meta = {'result_count': len(rows)}
    if next_token:
        meta['next_token'] = next_token
    return {'data': rows, 'meta': meta}


class Provider:
    def __init__(self, *pages):
        self.pages = list(pages)
        self.calls = []

    def __call__(self, path, query, bearer):
        self.calls.append((path, deepcopy(query)))
        if '/by/username/' in path:
            return {'data': {'id': '12', 'username': path.rsplit('/', 1)[1]}}
        if not self.pages:
            raise AssertionError('Unexpected additional paid post request')
        result = self.pages.pop(0)
        if isinstance(result, BaseException):
            raise result
        return deepcopy(result)


class FeedCollectionTests(unittest.TestCase):
    def test_accounts_override_cannot_walk_outside_vault(self):
        with self.assertRaises(feed.FeedError):
            feed.selected(self.args(accounts_note='Investments/../../outside.md'))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='obsidian-feed-forward-')
        self.addCleanup(self.tmp.cleanup)
        self.vault = Path(self.tmp.name).resolve()
        (self.vault / 'Investments').mkdir()
        self.roster = self.vault / 'Investments/x-accounts.md'
        self.roster.write_text('# Accounts\n\n```markdown\n- [x] @example\n```\n'
                               '- [x] @Actual\n- [ ] @Paused\n', encoding='utf-8')
        self.roster_bytes = self.roster.read_bytes()
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {'X_BEARER_TOKEN': 'offline-fixture-not-a-real-token'}).start()
        patch.object(feed, 'provenance', return_value=RECORD).start()

    def args(self, command='collect', until=FIRST, **values):
        args = feed.parser().parse_args([command, '--vault', str(self.vault), '--until', until])
        for key, value in values.items():
            setattr(args, key, value)
        return args

    def collect(self, provider, **values):
        return feed.collect(self.args(**values), fetch=provider, record=RECORD)

    @property
    def note(self):
        return self.vault / 'Investments/Sources/X/actual.md'

    @property
    def state_path(self):
        return self.vault / 'Investments/Sources/.feed-collect/state.json'

    def state(self):
        return json.loads(self.state_path.read_text(encoding='utf-8'))

    def test_resume_then_incremental_run_does_not_purchase_known_pages(self):
        provider = Provider(page([post(105), post(104)], 'page-two'))
        first = self.collect(provider, max_requests=2)
        self.assertEqual(provider.calls[1][1]['exclude'], 'retweets,replies')
        self.assertEqual(first['partial_accounts'], 1)
        self.assertIsNone(self.state()['accounts']['actual']['since_id'])
        resume = Provider(page([post(103)]))
        self.collect(resume, max_requests=1)
        self.assertEqual(len(resume.calls), 1)
        self.assertEqual(resume.calls[0][1]['pagination_token'], 'page-two')
        self.assertEqual(resume.calls[0][1]['exclude'], 'retweets,replies')
        self.assertEqual(self.state()['accounts']['actual']['since_id'], '105')
        original_note = self.note.read_bytes()
        none = Provider()
        self.collect(none)
        self.assertEqual(none.calls, [])
        self.assertEqual(self.note.read_bytes(), original_note)
        fresh = Provider(page([post(106, '2026-09-07T13:00:00Z')]))
        self.collect(fresh, until=LATER)
        self.assertEqual(fresh.calls[0][1]['since_id'], '105')
        self.assertEqual(fresh.calls[0][1]['exclude'], 'retweets,replies')
        self.assertNotIn('pagination_token', fresh.calls[0][1])
        self.assertEqual(set(self.state()['accounts']['actual']['posts']), {'103', '104', '105', '106'})
        self.assertEqual(self.roster.read_bytes(), self.roster_bytes)
        self.assertEqual([p.name for p in self.note.parent.glob('*.md')], ['actual.md'])

    def test_only_original_and_quote_posts_are_recorded_despite_provider_leaks(self):
        quote = post(106, text='Original quote commentary')
        quote['referenced_posts'] = [{'id': '80', 'type': 'quoted'}]
        reply = post(107, text='Excluded reply body')
        reply['referenced_tweets'] = [{'id': '81', 'type': 'replied_to'}]
        repost = post(108, text='Excluded repost body')
        repost['referenced_posts'] = [{'id': '82', 'type': 'retweeted'}]
        quote_reply = post(109, text='Excluded quote reply body')
        quote_reply['referenced_tweets'] = [*quote['referenced_posts'], *reply['referenced_tweets']]
        result = self.collect(Provider(page([post(105), quote, reply, repost, quote_reply])), max_posts=5)
        account = self.state()['accounts']['actual']
        self.assertEqual(set(account['posts']), {'105', '106'})
        self.assertEqual(account['since_id'], '109')
        self.assertEqual(result['returned_posts'], 5)
        self.assertEqual(result['newly_stored_posts'], 2)
        self.assertIn('Original quote commentary', self.note.read_text(encoding='utf-8'))
        for raw in (reply, repost, quote_reply):
            self.assertNotIn(raw['text'], self.state_path.read_text(encoding='utf-8'))
            self.assertNotIn(raw['text'], self.note.read_text(encoding='utf-8'))
        fresh = Provider(page([]))
        self.collect(fresh, until=LATER)
        self.assertEqual(fresh.calls[0][1]['since_id'], '109')

    def test_withheld_reply_is_excluded_without_requiring_its_body(self):
        withheld_reply = post(105)
        del withheld_reply['text']
        withheld_reply.update(withheld={'country_codes': ['US']},
                               referenced_posts=[{'id': '81', 'type': 'replied_to'}])
        self.collect(Provider(page([withheld_reply])))
        account = self.state()['accounts']['actual']
        self.assertEqual(account['posts'], {})
        self.assertEqual(account['since_id'], '105')

    def test_incompatible_saved_filter_blocks_without_repeating_paid_pages(self):
        self.collect(Provider(page([post(105)], 'page-two')), max_requests=2)
        original = self.state()
        for incompatible in (None, 'retweets'):
            with self.subTest(exclude=incompatible):
                state = deepcopy(original)
                state['accounts']['actual']['window']['exclude'] = incompatible
                self.state_path.write_text(json.dumps(state), encoding='utf-8')
                before = self.state_path.read_bytes()
                provider = Provider()
                with self.assertRaisesRegex(feed.FeedError, 'incompatible_saved_timeline_filter'):
                    self.collect(provider)
                self.assertEqual(provider.calls, [])
                self.assertEqual(self.state_path.read_bytes(), before)

    def test_incompatible_pending_filter_is_not_replayed(self):
        with self.assertRaises(feed.FeedError):
            self.collect(Provider(TimeoutError()))
        state = self.state()
        state['pending']['query'].pop('exclude')
        self.state_path.write_text(json.dumps(state), encoding='utf-8')
        before = self.state_path.read_bytes()
        provider = Provider()
        with self.assertRaisesRegex(feed.FeedError, 'incompatible_saved_timeline_filter'):
            self.collect(provider)
        self.assertEqual(provider.calls, [])
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_saved_success_is_replayed_offline_after_processing_interruption(self):
        provider = Provider(page([post(105)]))
        real_apply = feed.apply_response

        def interrupted(store):
            if store.data['pending']['kind'] == 'timeline':
                raise RuntimeError('simulated crash after response was durably stored')
            return real_apply(store)

        with patch.object(feed, 'apply_response', side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                self.collect(provider)
        self.assertIn('response', self.state()['pending'])
        with patch.object(feed, 'request_json', side_effect=AssertionError('Offline publish made network call')):
            result = feed.execute(self.args(command='publish'))
        self.assertEqual(result['requests'], 0)
        self.assertIsNone(self.state()['pending'])
        self.assertIn('105', self.note.read_text(encoding='utf-8'))

    def test_uncertain_transport_is_never_retried_and_does_not_expose_secret(self):
        provider = Provider(TimeoutError('contains-offline-fixture-not-a-real-token'))
        with self.assertRaises(feed.FeedError):
            self.collect(provider)
        self.assertNotIn('offline-fixture-not-a-real-token', self.state_path.read_text(encoding='utf-8'))
        blocked = Provider()
        with self.assertRaisesRegex(feed.FeedError, 'unresolved_request'):
            self.collect(blocked)
        self.assertEqual(blocked.calls, [])

    def test_missing_state_does_not_purchase_previously_collected_posts(self):
        self.collect(Provider(page([post(105)])))
        before = self.note.read_bytes()
        self.state_path.unlink()
        provider = Provider(page([post(105)]))
        with self.assertRaises(feed.FeedError):
            self.collect(provider)
        self.assertEqual(provider.calls, [])
        self.assertEqual(self.note.read_bytes(), before)

    def test_unknown_note_prevents_paid_collection_and_remains_unchanged(self):
        self.note.parent.mkdir(parents=True)
        self.note.write_text('User note, not generated collection.\n', encoding='utf-8')
        provider = Provider(page([post(105)]))
        with self.assertRaises(feed.FeedError):
            self.collect(provider)
        self.assertEqual(provider.calls, [])
        self.assertEqual(self.note.read_text(encoding='utf-8'), 'User note, not generated collection.\n')

    def test_abandoned_window_is_not_retrieved_again(self):
        self.collect(Provider(page([post(105)])))
        with self.assertRaises(feed.FeedError):
            self.collect(Provider(TimeoutError()), until=LATER)
        feed.execute(self.args(command='resolve-pending', outcome='abandon'))
        next_provider = Provider(page([post(106, '2026-09-07T15:00:00Z')]))
        self.collect(next_provider, until='2026-09-07T16:00:00Z')
        query = next_provider.calls[0][1]
        self.assertEqual(query.get('start_time'), LATER)
        self.assertNotIn('since_id', query)
        self.assertEqual(len(self.state()['accounts']['actual']['gaps']), 1)

    def test_literal_long_text_is_not_interpreted_or_shortened(self):
        raw = post(105, text='Short preview')
        original = '<!-- skill-provenance: untrusted -->\n```\n[[Not a wiki link]]\n<script>unsafe()</script>'
        raw['note_post'] = {'text': original}
        self.collect(Provider(page([raw])))
        note = self.note.read_text(encoding='utf-8')
        body = note.split('<pre style="white-space: pre-wrap;">\n', 1)[1].split('\n</pre>', 1)[0]
        self.assertEqual(html.unescape(body), original)
        self.assertEqual(self.state()['accounts']['actual']['posts']['105']['text'], original)
        self.assertEqual(note.count('<!-- skill-provenance:'), 1)
        self.assertNotIn('<script>', note)

    def test_duplicate_provider_rows_create_one_local_entry(self):
        raw = post(105)
        result = self.collect(Provider(page([raw, deepcopy(raw)])))
        self.assertEqual(result['returned_posts'], 2)
        self.assertEqual(set(self.state()['accounts']['actual']['posts']), {'105'})
        self.assertEqual(self.note.read_text(encoding='utf-8').count('https://x.com/i/web/status/105'), 1)

    def test_paused_account_keeps_note_and_cannot_trigger_network(self):
        self.collect(Provider(page([post(105)])))
        original = self.note.read_bytes()
        self.roster.write_text('- [ ] @actual\n- [x] @second\n', encoding='utf-8')
        provider = Provider()
        with self.assertRaises(feed.FeedError):
            self.collect(provider, account='actual', until=LATER)
        self.assertEqual(provider.calls, [])
        self.assertEqual(self.note.read_bytes(), original)

    def test_reconciliation_removes_deleted_source_body_from_all_owned_files(self):
        original = 'Unique source body requiring removal after confirmed deletion.'
        self.collect(Provider(page([post(105, text=original)])))
        self.roster.write_text('- [ ] @actual\n', encoding='utf-8')
        response = {'errors': [{'resource_id': '105',
                               'type': 'https://api.x.com/2/problems/resource-not-found'}]}
        provider = Provider(response)
        with patch.object(feed, 'request_json', side_effect=provider):
            result = feed.execute(self.args(command='reconcile', account='actual', ids='105', allow_paid_reread=True))
        self.assertEqual(result['requests'], 1)
        self.assertEqual(self.state()['accounts']['actual']['posts']['105']['status'], 'unavailable')
        for artifact in (self.vault / 'Investments/Sources').rglob('*'):
            if artifact.is_file():
                self.assertNotIn(original.encode(), artifact.read_bytes(), str(artifact))

    def test_reconciliation_edit_replaces_old_version_without_a_second_note(self):
        with patch.object(feed, 'now', return_value=FIRST):
            self.collect(Provider(page([post(105, text='Original version before correction.')])))
        edited = post(110, text='Corrected source version.')
        edited['edit_history_post_ids'] = ['105', '110']
        with patch.object(feed, 'request_json', side_effect=Provider({'data': [edited]})), \
                patch.object(feed, 'now', return_value=LATER):
            feed.execute(self.args(command='reconcile', account='actual', ids='105', allow_paid_reread=True))
        posts = self.state()['accounts']['actual']['posts']
        self.assertEqual(set(posts), {'110'})
        self.assertEqual(posts['110']['first_retrieved_at'], LATER)
        self.assertNotIn('Original version before correction.', self.note.read_text(encoding='utf-8'))
        self.assertEqual([p.name for p in self.note.parent.glob('*.md')], ['actual.md'])

    def test_concurrent_editor_change_survives_render_and_failed_stage_is_named(self):
        self.collect(Provider(page([post(105)])))
        real_render = feed.render

        def editor_writes_during_render(account):
            output = real_render(account)
            self.note.write_text('A newer editor change.\n', encoding='utf-8')
            return output

        with patch.object(feed, 'render', side_effect=editor_writes_during_render):
            with self.assertRaisesRegex(feed.FeedError, 'retained_recovery: ') as failure:
                self.collect(Provider(page([post(106, '2026-09-07T13:00:00Z')])), until=LATER)
        self.assertEqual(self.note.read_text(encoding='utf-8'), 'A newer editor change.\n')
        recovery = Path(str(failure.exception).split('retained_recovery: ')[1].split('; ')[0])
        self.assertTrue(recovery.is_dir())
        self.assertEqual(recovery.parent, self.note.parent.parent)
        self.assertNotEqual(recovery.parent, self.note.parent)

    def test_replacement_preserves_existing_note_permissions(self):
        self.collect(Provider(page([post(105)])))
        self.note.chmod(0o640)
        self.collect(Provider(page([post(106, '2026-09-07T13:00:00Z')])), until=LATER)
        self.assertEqual(self.note.stat().st_mode & 0o777, 0o640)
        self.assertEqual(list(self.note.parent.parent.glob('.feed-stage-*')), [])

    def test_indented_code_and_commented_examples_do_not_enable_accounts(self):
        self.roster.write_text('- [x] @actual\n\n    - [x] @code_example\n\n'
                               '<!--\n- [x] @comment_example\n-->\n', encoding='utf-8')
        self.assertEqual(feed.roster(self.roster), [{'handle': 'actual', 'id': None}])

    def test_verified_rename_preserves_identity_filename_and_existing_posts(self):
        self.collect(Provider(page([post(105)])))
        self.roster.write_text('- [x] @renamed <!-- x-user-id: 12 -->\n', encoding='utf-8')
        provider = Provider(page([post(106, '2026-09-07T13:00:00Z')]))
        self.collect(provider, until=LATER)
        self.assertEqual([call[0] for call in provider.calls], ['/2/users/12/tweets'])
        self.assertEqual([item.name for item in self.note.parent.glob('*.md')], ['actual.md'])
        state = self.state()['accounts']['actual']
        self.assertEqual(state['handle'], 'renamed')
        self.assertEqual(set(state['posts']), {'105', '106'})

    def test_wrong_author_response_is_saved_but_not_attributed_or_retried(self):
        raw = post(105)
        raw['author_id'] = '13'
        with self.assertRaisesRegex(feed.FeedError, 'identity_mismatch'):
            self.collect(Provider(page([raw])))
        self.assertIn('response', self.state()['pending'])
        self.assertEqual(self.state()['accounts']['actual']['posts'], {})
        blocked = Provider()
        with self.assertRaisesRegex(feed.FeedError, 'identity_mismatch'):
            self.collect(blocked)
        self.assertEqual(blocked.calls, [])

    def test_empty_existing_state_is_not_adopted_as_a_fresh_collection(self):
        self.collect(Provider(page([post(105)])))
        self.state_path.write_bytes(b'')
        provider = Provider(page([post(105)]))
        with self.assertRaises(feed.FeedError):
            self.collect(provider)
        self.assertEqual(provider.calls, [])
        self.assertEqual(self.state_path.read_bytes(), b'')

    def test_source_timestamp_retains_fraction_and_original_representation(self):
        original_time = '2026-09-07T13:59:59.987654+02:00'
        self.collect(Provider(page([post(105, original_time)])))
        saved = self.state()['accounts']['actual']['posts']['105']
        self.assertEqual(saved['created_at'], '2026-09-07T11:59:59.987654Z')
        self.assertEqual(saved['source_created_at'], original_time)

    def test_incremental_timeline_accepts_an_edit_with_original_creation_time(self):
        with patch.object(feed, 'now', return_value=FIRST):
            self.collect(Provider(page([post(105, text='Source before a later edit.')])))
        edited = post(110, text='Updated source returned directly by the timeline.')
        edited['edit_history_post_ids'] = ['105', '110']
        with patch.object(feed, 'now', return_value=LATER):
            self.collect(Provider(page([edited])), until=LATER)
        posts = self.state()['accounts']['actual']['posts']
        self.assertEqual(set(posts), {'110'})
        self.assertEqual(posts['110']['first_retrieved_at'], LATER)
        self.assertNotIn('Source before a later edit.', self.note.read_text(encoding='utf-8'))

    def test_old_version_lookup_exposes_explicit_latest_version_followup(self):
        original_text = 'Old source that the provider now confirms was superseded.'
        self.collect(Provider(page([post(105, text=original_text)])))
        old_version = post(105, text=original_text)
        old_version['edit_history_post_ids'] = ['105', '110']
        provider = Provider({'data': [old_version]})
        with patch.object(feed, 'request_json', side_effect=provider):
            feed.execute(self.args(command='reconcile', account='actual', ids='105', allow_paid_reread=True))
        self.assertEqual(len(provider.calls), 1)
        old = self.state()['accounts']['actual']['posts']['105']
        self.assertEqual(old['status'], 'superseded')
        self.assertEqual(old['latest_post_id'], '110')
        self.assertNotIn('text', old)
        self.assertNotIn(original_text, self.note.read_text(encoding='utf-8'))
        latest = post(110, text='Actual latest version body.')
        latest['edit_history_post_ids'] = ['105', '110']
        with patch.object(feed, 'request_json', side_effect=Provider({'data': [latest]})), \
                patch.object(feed, 'now', return_value=LATER):
            feed.execute(self.args(command='reconcile', account='actual', ids='110', allow_paid_reread=True))
        saved = self.state()['accounts']['actual']['posts']
        self.assertEqual(set(saved), {'110'})
        self.assertEqual(saved['110']['first_retrieved_at'], LATER)
        self.assertEqual(saved['110']['text'], latest['text'])

    def test_old_version_or_missing_predecessor_never_erases_a_newer_version(self):
        latest = post(110, text='Already observed latest version.')
        latest['edit_history_post_ids'] = ['105', '110']
        self.collect(Provider(page([latest])))
        old = post(105, text='Superseded body must not return to the note.')
        old['edit_history_post_ids'] = ['105', '110']
        for response in ({'data': [old]}, {'errors': [{'resource_id': '105',
                          'type': 'https://api.x.com/2/problems/resource-not-found'}]}):
            with patch.object(feed, 'request_json', side_effect=Provider(response)):
                feed.execute(self.args(command='reconcile', account='actual', ids='105', allow_paid_reread=True))
            saved = self.state()['accounts']['actual']['posts']
            self.assertEqual(set(saved), {'110'})
            self.assertEqual(saved['110']['text'], latest['text'])
            self.assertNotIn(old['text'], self.note.read_text(encoding='utf-8'))

    def test_conflicting_duplicate_rows_block_before_attribution(self):
        rows = [post(105, text='First conflicting body.'), post(105, text='Second conflicting body.')]
        with self.assertRaisesRegex(feed.FeedError, 'conflicting_duplicate'):
            self.collect(Provider(page(rows)))
        self.assertEqual(self.state()['accounts']['actual']['posts'], {})
        self.assertIn('response', self.state()['pending'])


if __name__ == '__main__':
    unittest.main()
