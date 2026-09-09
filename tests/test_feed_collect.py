#!/usr/bin/env python3
"""Independent offline forward tests for paid X collection and vault safety."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml

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


def self_reply(identity, parent='81', conversation='80', **kwargs):
    return {**post(identity, **kwargs), 'in_reply_to_user_id': '12', 'conversation_id': conversation,
            'referenced_tweets': [{'id': parent, 'type': 'replied_to'}]}


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
        args.max_downloads = 0  # This suite mocks paid X reads, not attachment HTTP.
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
        self.assertNotIn('exclude', provider.calls[1][1])
        self.assertEqual(first['partial_accounts'], 1)
        self.assertIsNone(self.state()['accounts']['actual']['since_id'])
        resume = Provider(page([post(103)]))
        self.collect(resume, max_requests=1)
        self.assertEqual(len(resume.calls), 1)
        self.assertEqual(resume.calls[0][1]['pagination_token'], 'page-two')
        self.assertNotIn('exclude', resume.calls[0][1])
        self.assertEqual(self.state()['accounts']['actual']['since_id'], '105')
        original_note = self.note.read_bytes()
        none = Provider()
        self.collect(none)
        self.assertEqual(none.calls, [])
        self.assertEqual(self.note.read_bytes(), original_note)
        fresh = Provider(page([post(106, '2026-09-07T13:00:00Z')]))
        self.collect(fresh, until=LATER)
        self.assertEqual(fresh.calls[0][1]['start_time'], FIRST)
        self.assertNotIn('since_id', fresh.calls[0][1])
        self.assertNotIn('exclude', fresh.calls[0][1])
        self.assertNotIn('pagination_token', fresh.calls[0][1])
        self.assertEqual(set(self.state()['accounts']['actual']['posts']), {'103', '104', '105', '106'})
        self.assertEqual(self.roster.read_bytes(), self.roster_bytes)
        self.assertEqual([p.name for p in self.note.parent.glob('*.md')], ['actual.md'])

    def test_original_quote_and_repost_rows_are_recorded_but_unverified_reply_is_excluded(self):
        quote = post(106, text='Original quote commentary')
        quote['referenced_posts'] = [{'id': '80', 'type': 'quoted'}]
        reply = post(107, text='Excluded reply body')
        reply['referenced_tweets'] = [{'id': '81', 'type': 'replied_to'}]
        repost = post(108, text='RT @source: Included repost body')
        repost['referenced_posts'] = [{'id': '82', 'type': 'retweeted'}]
        quote_reply = post(109, text='Excluded quote reply body')
        quote_reply['referenced_tweets'] = [*quote['referenced_posts'], *reply['referenced_tweets']]
        repost_reply = post(110, text='Excluded repost reply body')
        repost_reply['referenced_posts'] = [*repost['referenced_posts'], *reply['referenced_tweets']]
        provider = Provider(page([post(105), quote, reply, repost, quote_reply, repost_reply]))
        result = self.collect(provider, max_posts=6)
        account = self.state()['accounts']['actual']
        self.assertEqual(set(account['posts']), {'105', '106', '108'})
        self.assertEqual(account['since_id'], '110')
        self.assertEqual(result['returned_posts'], 6)
        self.assertEqual(result['newly_stored_posts'], 3)
        self.assertIn('Original quote commentary', self.note.read_text(encoding='utf-8'))
        self.assertIn('Included repost body', self.note.read_text(encoding='utf-8'))
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(provider.calls[1][1]['expansions'], 'attachments.media_keys')
        for raw in (reply, quote_reply, repost_reply):
            self.assertNotIn(raw['text'], self.state_path.read_text(encoding='utf-8'))
            self.assertNotIn(raw['text'], self.note.read_text(encoding='utf-8'))
        fresh = Provider(page([]))
        self.collect(fresh, until=LATER)
        self.assertEqual(fresh.calls[0][1]['start_time'], FIRST)
        self.assertNotIn('since_id', fresh.calls[0][1])

    def test_self_replies_and_quote_continuations_preserve_identity_and_context(self):
        continuation = self_reply(106, text='Second part of the original thesis.')
        quote = self_reply(107, parent='106', text='Third part quotes another source.')
        quote['referenced_tweets'].append({'id': '72', 'type': 'quoted'})
        provider = Provider(page([continuation, quote, deepcopy(quote)]))
        result = self.collect(provider)
        self.assertEqual(len(provider.calls), 2)  # Never look up missing roots or parents.
        self.assertNotIn('exclude', provider.calls[1][1])
        self.assertIn('in_reply_to_user_id', provider.calls[1][1]['tweet.fields'].split(','))
        self.assertEqual(result['returned_posts'], 3)
        self.assertEqual(result['row_counts']['newly_stored_posts'], 2)
        self.assertEqual(result['row_counts']['duplicate_rows'], 1)
        saved = self.state()['accounts']['actual']['posts']
        self.assertEqual(set(saved), {'106', '107'})
        self.assertTrue(all(feed.is_self_reply(value, '12') for value in saved.values()))
        self.assertEqual(saved['107']['references'], quote['referenced_tweets'])
        note = self.note.read_text(encoding='utf-8')
        self.assertEqual(note.count('[Self-reply]'), 2)
        self.assertIn('[Parent post](https://x.com/i/web/status/81)', note)
        self.assertIn('[Parent post](https://x.com/i/web/status/106)', note)
        self.assertEqual(note.count('[Conversation](https://x.com/i/web/status/80)'), 2)
        self.assertIn('Thread context may be incomplete', note)
        none = Provider()
        self.collect(none)
        self.assertEqual(none.calls, [])

    def test_other_user_and_ambiguous_replies_are_excluded_with_exact_diagnostics(self):
        other = self_reply(101, text='@actual is mentioned, but this replies to somebody else.')
        other['in_reply_to_user_id'] = '13'
        absent = self_reply(102)
        absent.pop('in_reply_to_user_id')
        malformed = self_reply(103)
        malformed['in_reply_to_user_id'] = 12
        no_parent = self_reply(104)
        no_parent['referenced_tweets'] = []
        two_parents = self_reply(105)
        two_parents['referenced_tweets'].append({'id': '79', 'type': 'replied_to'})
        invalid_conversation = self_reply(106, conversation='80)unsafe')
        repost_reply = self_reply(107)
        repost_reply['referenced_tweets'].append({'id': '79', 'type': 'retweeted'})
        result = self.collect(Provider(page([other, absent, malformed, no_parent, two_parents,
                                            invalid_conversation, repost_reply])))
        self.assertEqual(result['returned_posts'], 7)
        self.assertEqual(result['row_counts']['excluded_replies'], 7)
        self.assertEqual(result['reply_exclusions'], {'other_account': 1, 'target_unavailable': 2,
                                                     'ambiguous_metadata': 4, 'legacy_filter': 0})
        self.assertEqual(result['unexpected_filter_rows'], 0)
        self.assertEqual(self.state()['accounts']['actual']['posts'], {})
        self.assertEqual(self.state()['accounts']['actual']['since_id'], '107')
        self.assertNotIn(other['text'], self.state_path.read_text(encoding='utf-8'))

    def test_self_reply_without_conversation_retains_parent_without_inventing_root(self):
        continuation = self_reply(106)
        continuation.pop('conversation_id')
        self.collect(Provider(page([continuation])))
        self.assertIn('[Parent post]', self.note.read_text(encoding='utf-8'))
        self.assertNotIn('[Conversation]', self.note.read_text(encoding='utf-8'))

    def test_self_reply_keeps_only_its_own_expanded_photo_attachments(self):
        continuation = self_reply(106)
        continuation['attachments'] = {'media_keys': ['3_own']}
        response = page([continuation])
        response['includes'] = {'media': [
            {'media_key': '3_own', 'type': 'photo', 'url': 'https://pbs.twimg.com/media/own.jpg'},
            {'media_key': '3_parent', 'type': 'photo', 'url': 'https://pbs.twimg.com/media/parent.jpg'}]}
        provider = Provider(response)
        self.collect(provider)
        saved = self.state()['accounts']['actual']['posts']['106']
        self.assertEqual(saved['media'], [response['includes']['media'][0]])
        self.assertEqual(saved['attachments'], continuation['attachments'])
        self.assertEqual(len(provider.calls), 2)

    def test_legacy_reply_filter_preserves_fields_and_skips_self_replies_without_backfill(self):
        self.collect(Provider(page([post(109)], 'legacy-next')), max_requests=2)
        state = self.state()
        window = state['accounts']['actual']['window']
        window['exclude'] = 'replies'
        window['fields']['tweet.fields'] = feed.LEGACY_FIELDS
        self.state_path.write_text(json.dumps(state), encoding='utf-8')
        resumed = Provider(page([self_reply(108)]))
        result = self.collect(resumed, max_requests=1)
        query = resumed.calls[0][1]
        self.assertEqual(query['exclude'], 'replies')
        self.assertEqual(query['tweet.fields'], feed.LEGACY_FIELDS)
        self.assertEqual(query['pagination_token'], 'legacy-next')
        self.assertEqual(result['reply_exclusions']['legacy_filter'], 1)
        self.assertEqual(result['unexpected_filter_rows'], 1)
        self.assertNotIn('108', self.state()['accounts']['actual']['posts'])
        fresh = Provider(page([self_reply(110, created='2026-09-07T13:00:00Z')]))
        result = self.collect(fresh, until=LATER)
        self.assertEqual(fresh.calls[0][1]['start_time'], FIRST)
        self.assertNotIn('exclude', fresh.calls[0][1])
        self.assertEqual(fresh.calls[0][1]['tweet.fields'], feed.FIELDS)
        self.assertTrue(result['accounts'][0]['reply_collection']['prior_filtered_history_not_backfilled'])
        self.assertEqual(set(self.state()['accounts']['actual']['posts']), {'109', '110'})

    def test_pending_field_selection_cannot_be_changed_to_enable_historical_reply_reads(self):
        with self.assertRaises(feed.FeedError):
            self.collect(Provider(TimeoutError()))
        state = self.state()
        state['accounts']['actual']['window']['exclude'] = 'replies'
        state['pending']['query']['exclude'] = 'replies'
        state['accounts']['actual']['window']['fields']['tweet.fields'] = feed.LEGACY_FIELDS
        self.state_path.write_text(json.dumps(state), encoding='utf-8')
        before = self.state_path.read_bytes()
        provider = Provider()
        with self.assertRaisesRegex(feed.FeedError, 'incompatible_saved_timeline_fields'):
            self.collect(provider)
        self.assertEqual(provider.calls, [])
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_saved_unfiltered_response_with_self_reply_is_consumed_offline(self):
        real_apply = feed.apply_response

        def interrupted(store):
            if store.data['pending']['kind'] == 'timeline':
                raise RuntimeError('saved unfiltered response')
            return real_apply(store)

        with patch.object(feed, 'apply_response', side_effect=interrupted), self.assertRaises(RuntimeError):
            self.collect(Provider(page([self_reply(106)])))
        query = deepcopy(self.state()['pending']['query'])
        with patch.object(feed, 'request_json', side_effect=AssertionError('Paid replay')):
            feed.execute(self.args(command='publish'))
        self.assertEqual(self.state()['requests'][-1]['query'], query)
        self.assertIn('[Self-reply]', self.note.read_text(encoding='utf-8'))

    def test_api_url_omits_exclude_instead_of_serializing_empty_or_none(self):
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, limit):
                return b'{"data": [], "meta": {"result_count": 0}}'

        with patch.object(feed.urllib.request, 'build_opener') as opener:
            opener.return_value.open.return_value = Response()
            provider = Provider(page([]))
            self.collect(provider)
            feed.request_json(provider.calls[1][0], provider.calls[1][1], 'offline-token')
            url = opener.return_value.open.call_args.args[0].full_url
        self.assertNotIn('exclude', feed.urllib.parse.parse_qs(feed.urllib.parse.urlsplit(url).query,
                                                          keep_blank_values=True))

    def test_repost_wrappers_keep_distinct_identity_and_time_without_fetching_originals(self):
        first = post(108, '2026-09-07T10:00:00Z', text='RT @source: Preserved API excerpt…')
        first['referenced_tweets'] = [{'id': '82', 'type': 'retweeted'}]
        second = post(109, '2026-09-07T11:00:00Z', text=first['text'])
        second['referenced_tweets'] = deepcopy(first['referenced_tweets'])
        provider = Provider(page([first, deepcopy(first), second]))
        result = self.collect(provider)
        self.assertEqual(len(provider.calls), 2)  # Identity lookup and one timeline page only.
        self.assertEqual(provider.calls[1][1]['expansions'], 'attachments.media_keys')
        self.assertEqual(result['newly_stored_posts'], 2)
        self.assertEqual(result['row_counts']['duplicate_rows'], 1)
        account = self.state()['accounts']['actual']
        self.assertEqual(set(account['posts']), {'108', '109'})
        self.assertEqual(account['since_id'], '109')
        for raw in (first, second):
            saved = account['posts'][raw['id']]
            self.assertEqual(saved['created_at'], raw['created_at'])
            self.assertEqual(saved['text'], raw['text'])
            self.assertEqual(saved['references'], raw['referenced_tweets'])
        note = self.note.read_text(encoding='utf-8')
        self.assertEqual(note.count('Reposted by @actual'), 2)
        self.assertEqual(note.count('[Source post](https://x.com/i/web/status/82)'), 2)
        self.assertIn('## 2026-09-07 10:00:00 UTC', note)
        self.assertIn('## 2026-09-07 11:00:00 UTC', note)
        self.assertIn('https://x.com/i/web/status/108', note)
        self.assertIn('https://x.com/i/web/status/109', note)
        self.assertRegex(note.lower(), r'incomplete|truncated')
        self.assertNotIn('replies/reposts are excluded', note.lower())

    def test_malformed_saved_repost_reference_blocks_before_paid_requests(self):
        repost = post(108, text='RT @source: Preserved repost body')
        repost['referenced_tweets'] = [{'id': '82', 'type': 'retweeted'}]
        self.collect(Provider(page([repost])))
        original = self.state()
        original_note = self.note.read_bytes()
        for malformed in ([{'id': '82)\n[unsafe](https://example.com)', 'type': 'retweeted'}],
                          [{'id': '82', 'type': ['retweeted']}],
                          [{'type': 'retweeted'}], 'not-a-reference-list'):
            with self.subTest(references=malformed):
                state = deepcopy(original)
                state['accounts']['actual']['posts']['108']['references'] = malformed
                self.state_path.write_text(json.dumps(state), encoding='utf-8')
                before = self.state_path.read_bytes()
                provider = Provider()
                with self.assertRaisesRegex(feed.FeedError, 'invalid_post_references'):
                    self.collect(provider, until=LATER)
                self.assertEqual(provider.calls, [])
                self.assertEqual(self.state_path.read_bytes(), before)
                self.assertEqual(self.note.read_bytes(), original_note)

    def test_legacy_window_resumes_original_filter_then_advances_without_backfilling(self):
        self.collect(Provider(page([post(105)], 'page-two')), max_requests=2)
        state = self.state()
        old_window = state['accounts']['actual']['window']
        old_window['exclude'] = 'retweets,replies'
        self.state_path.write_text(json.dumps(state), encoding='utf-8')
        legacy_repost = post(103, text='Repost unexpectedly returned under the old exclusion filter')
        legacy_repost['referenced_posts'] = [{'id': '82', 'type': 'retweeted'}]
        resumed = Provider(page([post(104), legacy_repost]))
        result = self.collect(resumed, max_requests=1)
        self.assertEqual(len(resumed.calls), 1)
        self.assertEqual(result['returned_posts'], 2)
        self.assertEqual(result['row_counts']['excluded_reposts'], 1)
        self.assertNotIn(legacy_repost['text'], self.note.read_text(encoding='utf-8'))
        query = resumed.calls[0][1]
        self.assertEqual(query['exclude'], 'retweets,replies')
        self.assertEqual(query['pagination_token'], 'page-two')
        self.assertEqual(query['start_time'], old_window['start'])
        self.assertEqual(query['end_time'], old_window['end'])
        self.assertEqual(self.state()['accounts']['actual']['since_id'], '105')
        no_new_window = Provider()
        self.collect(no_new_window)
        self.assertEqual(no_new_window.calls, [])
        repost = post(106, '2026-09-07T13:00:00Z', text='New repost after old collection window')
        repost['referenced_posts'] = [{'id': '82', 'type': 'retweeted'}]
        fresh = Provider(page([repost]))
        self.collect(fresh, until=LATER)
        self.assertEqual(len(fresh.calls), 1)
        self.assertNotIn('exclude', fresh.calls[0][1])
        self.assertEqual(fresh.calls[0][1]['start_time'], FIRST)
        self.assertNotIn('since_id', fresh.calls[0][1])
        self.assertNotIn('pagination_token', fresh.calls[0][1])
        self.assertEqual(set(self.state()['accounts']['actual']['posts']), {'104', '105', '106'})

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
        for incompatible in ('', 'retweets', 'replies,retweets'):
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
        state['pending']['query']['exclude'] = None
        self.state_path.write_text(json.dumps(state), encoding='utf-8')
        before = self.state_path.read_bytes()
        provider = Provider()
        with self.assertRaisesRegex(feed.FeedError, 'incompatible_saved_timeline_filter'):
            self.collect(provider)
        self.assertEqual(provider.calls, [])
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_pending_filter_must_match_window_even_when_both_values_are_supported(self):
        with self.assertRaises(feed.FeedError):
            self.collect(Provider(TimeoutError()))
        original = self.state()
        for window_filter, pending_filter in (('replies', 'retweets,replies'),
                                               ('retweets,replies', 'replies')):
            with self.subTest(window=window_filter, pending=pending_filter):
                state = deepcopy(original)
                state['accounts']['actual']['window']['exclude'] = window_filter
                state['pending']['query']['exclude'] = pending_filter
                self.state_path.write_text(json.dumps(state), encoding='utf-8')
                before = self.state_path.read_bytes()
                provider = Provider()
                with self.assertRaisesRegex(feed.FeedError, 'incompatible_saved_timeline_filter'):
                    self.collect(provider)
                self.assertEqual(provider.calls, [])
                self.assertEqual(self.state_path.read_bytes(), before)

    def test_legacy_unresolved_pending_request_still_blocks_paid_replay(self):
        with self.assertRaises(feed.FeedError):
            self.collect(Provider(TimeoutError()))
        state = self.state()
        state['accounts']['actual']['window']['exclude'] = 'retweets,replies'
        state['pending']['query']['exclude'] = 'retweets,replies'
        self.state_path.write_text(json.dumps(state), encoding='utf-8')
        before = self.state_path.read_bytes()
        provider = Provider()
        with self.assertRaisesRegex(feed.FeedError, 'unresolved_request'):
            self.collect(provider)
        self.assertEqual(provider.calls, [])
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_saved_legacy_response_is_consumed_offline_without_changing_its_query(self):
        repost = post(105, text='Unexpected repost saved before the filter migration')
        repost['referenced_tweets'] = [{'id': '82', 'type': 'retweeted'}]
        provider = Provider(page([repost]))
        real_apply = feed.apply_response

        def interrupted(store):
            if store.data['pending']['kind'] == 'timeline':
                raise RuntimeError('saved legacy response awaiting processing')
            return real_apply(store)

        with patch.object(feed, 'apply_response', side_effect=interrupted), self.assertRaises(RuntimeError):
            self.collect(provider)
        state = self.state()
        state['accounts']['actual']['window']['exclude'] = 'retweets,replies'
        state['pending']['query']['exclude'] = 'retweets,replies'
        self.state_path.write_text(json.dumps(state), encoding='utf-8')
        with patch.object(feed, 'request_json', side_effect=AssertionError('Offline publish made a paid call')):
            result = feed.execute(self.args(command='publish'))
        self.assertEqual(result['requests'], 0)
        state = self.state()
        self.assertIsNone(state['pending'])
        self.assertEqual(state['requests'][-1]['query']['exclude'], 'retweets,replies')
        self.assertEqual(state['requests'][-1]['row_counts']['excluded_reposts'], 1)
        self.assertEqual(state['accounts']['actual']['since_id'], '105')
        self.assertEqual(state['accounts']['actual']['posts'], {})
        self.assertNotIn(repost['text'], self.note.read_text(encoding='utf-8'))

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

    def test_account_note_case_alias_blocks_paid_reads_without_changing_occupant(self):
        self.collect(Provider(page([post(105)])))
        alias = self.note.with_name('Actual.md')
        self.note.rename(alias)
        before = alias.read_bytes()
        provider = Provider(page([post(106, '2026-09-07T13:00:00Z')]))
        with self.assertRaises(feed.FeedError):
            self.collect(provider, until=LATER)
        self.assertEqual(provider.calls, [])
        self.assertEqual(alias.read_bytes(), before)

    def test_case_aliased_state_is_not_reported_as_an_empty_collection(self):
        self.collect(Provider(page([post(105)])))
        alias = self.state_path.with_name('State.json')
        self.state_path.rename(alias)
        before = alias.read_bytes()
        with self.assertRaises(feed.FeedError):
            feed.execute(self.args(command='status'))
        self.assertEqual(alias.read_bytes(), before)

    def test_plan_and_status_report_lost_state_instead_of_empty_history(self):
        self.collect(Provider(page([post(105)])))
        before = self.note.read_bytes()
        self.state_path.unlink()
        for command in ('plan', 'status'):
            with self.assertRaisesRegex(feed.FeedError, 'missing_existing_state_requires_recovery'):
                feed.execute(self.args(command=command))
        self.assertEqual(self.note.read_bytes(), before)
        self.assertFalse(self.state_path.exists())

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
        self.assertNotIn('<pre', note)
        self.assertIn(r'\`\`\`', note)
        self.assertIn(r'\[\[Not a wiki link\]\]', note)
        self.assertIn('&lt;script&gt;unsafe()&lt;/script&gt;', note)
        self.assertEqual(self.state()['accounts']['actual']['posts']['105']['text'], original)
        self.assertEqual(note.count('<!-- skill-provenance:'), 0)
        self.assertNotIn('<script>', note)

    def test_readable_properties_keep_identity_and_check_times_in_state(self):
        self.collect(Provider(page([post(105, text='A brief original post.\nSecond line.')])))
        note = self.note.read_text(encoding='utf-8')
        meta = yaml.safe_load(note.split('---', 2)[1])
        self.assertEqual(meta['sources'], ['X'])
        self.assertEqual(meta['authors'], ['[@actual](https://x.com/actual)'])
        self.assertEqual(set(meta), {'sources', 'authors', 'created', 'updated', 'description'})
        self.assertEqual(str(meta['created']), self.state()['accounts']['actual']['note']['created'])
        self.assertEqual(meta['created'], meta['updated'])
        self.assertEqual(meta['description'], '')
        self.assertNotIn('Source metadata', note)
        self.assertTrue(note.split('---', 2)[2].lstrip().startswith('## 2026-'))
        self.assertNotIn('First retrieved:', note)
        self.assertNotIn('Last checked:', note)
        self.assertIn('A brief original post.  \nSecond line.', note)
        account = self.state()['accounts']['actual']
        self.assertEqual(account['id'], '12')
        saved = account['posts']['105']
        self.assertTrue(saved['first_retrieved_at'])
        self.assertTrue(saved['last_checked_at'])

    def test_description_is_offline_sourced_and_safely_serialized(self):
        self.collect(Provider(page([post(105)])))
        description = 'Public author: studies \"AI\".\n---\nauthors: [intruder]'
        with patch.object(feed, 'request_json', side_effect=AssertionError('no paid profile request')):
            result = feed.execute(self.args(command='describe', account='actual', description=description,
                                           description_source=['https://example.org/author']))
        self.assertEqual(result['requests'], 0)
        meta = yaml.safe_load(self.note.read_text(encoding='utf-8').split('\n---\n', 1)[0].removeprefix('---\n'))
        self.assertEqual(meta['description'], description)
        self.assertEqual(meta['authors'], ['[@actual](https://x.com/actual)'])
        self.assertEqual(self.state()['accounts']['actual']['profile']['sources'], ['https://example.org/author'])
        self.assertNotIn('https://example.org/author', self.note.read_text(encoding='utf-8'))
        self.assertEqual(feed.execute(self.args(command='plan'))['missing_descriptions'], [])

    def test_description_without_evidence_preserves_note_and_state(self):
        self.collect(Provider(page([post(105)])))
        before = self.state_path.read_bytes(), self.note.read_bytes()
        for sources in ([], ['file:///etc/passwd'], ['https://user:password@example.org']):
            with self.subTest(sources=sources), self.assertRaises(feed.FeedError):
                feed.execute(self.args(command='describe', account='actual', description='Background.', description_source=sources))
            self.assertEqual((self.state_path.read_bytes(), self.note.read_bytes()), before)

    def test_plan_reuses_verified_renamed_account_description_without_writing(self):
        self.collect(Provider(page([post(105)])))
        feed.execute(self.args(command='describe', account='actual', description='Public research author.',
                               description_source=['https://example.org/author']))
        self.roster.write_text('- [x] @NewHandle <!-- x-user-id: 12 -->\n', encoding='utf-8')
        before = self.state_path.read_bytes(), self.note.read_bytes()
        for command in ('plan', 'status'):
            result = feed.execute(self.args(command=command))
            self.assertEqual(result['missing_descriptions'], [])
            self.assertEqual(result['requests'], 0)
        self.assertEqual((self.state_path.read_bytes(), self.note.read_bytes()), before)

    def test_note_dates_and_provenance_change_only_with_visible_content(self):
        with patch.object(feed, 'now', return_value=FIRST):
            self.collect(Provider(page([post(105)])))
        original = self.note.read_bytes()
        first = deepcopy(self.state()['accounts']['actual']['note'])
        self.assertEqual(first['created'], '2026-09-07')
        self.assertEqual(first['updated'], '2026-09-07')
        self.assertEqual(first['provenance']['generated_by'], RECORD)
        newer = dict(RECORD, runtime_sha256='1' * 64)
        with patch.object(feed, 'now', return_value='2026-09-08T12:00:00Z'):
            with feed.Store(self.vault) as store:
                self.assertFalse(feed.publish_account(store, store.data['accounts']['actual'], self.vault, newer))
            self.assertEqual(self.note.read_bytes(), original)
            self.assertEqual(self.state()['accounts']['actual']['note'], first)
            with patch.object(feed, 'provenance', return_value=newer):
                feed.execute(self.args(command='describe', account='actual', description='A public research author.',
                                       description_source=['https://example.org/author']))
        current = self.state()['accounts']['actual']['note']
        self.assertEqual(current['created'], first['created'])
        self.assertEqual(current['updated'], '2026-09-08')
        self.assertEqual(current['provenance']['generated_by'], RECORD)
        self.assertEqual(current['provenance']['updated_by'], newer)
        self.assertNotIn('skill-provenance', self.note.read_text(encoding='utf-8'))

    def test_owned_legacy_footer_migrates_to_state_without_losing_creator(self):
        self.collect(Provider(page([post(105)])))
        legacy = feed.note_provenance.stamp_text('# @actual\n\nOld introduction.\n', RECORD)
        self.note.write_text(legacy, encoding='utf-8')
        with feed.Store(self.vault) as store:
            account = store.data['accounts']['actual']
            account.pop('note')
            account['published_sha256'] = feed.digest(legacy.encode())
            store.save()
        newer = dict(RECORD, runtime_sha256='2' * 64)
        with patch.object(feed, 'provenance', return_value=newer):
            feed.execute(self.args(command='publish'))
        current = self.state()['accounts']['actual']['note']
        self.assertEqual(current['provenance']['generated_by'], RECORD)
        self.assertEqual(current['provenance']['updated_by'], newer)
        self.assertNotIn('skill-provenance', self.note.read_text(encoding='utf-8'))
        self.assertNotIn('Old introduction', self.note.read_text(encoding='utf-8'))
        self.assertIn('Literal source post.', self.note.read_text(encoding='utf-8'))

    def test_unscoped_publish_does_not_recreate_paused_notes(self):
        self.collect(Provider(page([post(105)])))
        self.roster.write_text('- [ ] @Actual\n- [x] @Other\n', encoding='utf-8')
        self.note.unlink()
        self.assertEqual(feed.execute(self.args(command='publish'))['published_notes'], 0)
        self.assertFalse(self.note.exists())
        self.assertEqual(feed.execute(self.args(command='publish', account='actual'))['published_notes'], 1)
        self.assertTrue(self.note.exists())

    def test_offline_regeneration_preserves_note_dates_and_producer(self):
        with patch.object(feed, 'now', return_value=FIRST):
            self.collect(Provider(page([post(105)])))
        before = self.note.read_bytes()
        metadata = self.state()['accounts']['actual']['note']
        self.note.unlink()
        with patch.object(feed, 'now', return_value='2026-09-10T12:00:00Z'):
            result = feed.execute(self.args(command='publish'))
        self.assertEqual(result['published_notes'], 1)
        self.assertEqual(self.note.read_bytes(), before)
        self.assertEqual(self.state()['accounts']['actual']['note'], metadata)

    def test_publication_recovery_commits_prepared_dates_without_rewriting(self):
        with patch.object(feed, 'now', return_value=FIRST):
            self.collect(Provider(page([post(105)])))
        original_save = feed.Store.save
        prepared = False
        def interrupt_closeout(store):
            nonlocal prepared
            account = store.data['accounts']['actual']
            if 'prepared_note' in account:
                prepared = True
            elif prepared:
                raise OSError('simulated interruption before state closeout')
            return original_save(store)
        with patch.object(feed.Store, 'save', interrupt_closeout):
            with self.assertRaisesRegex(OSError, 'before state closeout'):
                feed.execute(self.args(command='describe', account='actual', description='Public researcher.',
                                       description_source=['https://example.org/bio']))
        before = self.note.read_bytes()
        prepared = self.state()['accounts']['actual']['prepared_note']
        with patch.object(feed, 'now', return_value='2026-09-10T12:00:00Z'):
            result = feed.execute(self.args(command='publish'))
        self.assertEqual(result['published_notes'], 0)
        self.assertEqual(self.note.read_bytes(), before)
        account = self.state()['accounts']['actual']
        self.assertNotIn('prepared_note', account)
        self.assertEqual(account['note'], prepared)

    def test_duplicate_provider_rows_create_one_local_entry(self):
        raw = post(105)
        result = self.collect(Provider(page([raw, deepcopy(raw)])))
        self.assertEqual(result['returned_posts'], 2)
        self.assertEqual(set(self.state()['accounts']['actual']['posts']), {'105'})
        self.assertEqual(self.note.read_text(encoding='utf-8').count('https://x.com/i/web/status/105'), 1)

    def test_source_urls_remain_clickable_without_requests_or_remote_embeds(self):
        url = 'https://example.com/report_name?q=a_b&next=%2Fpath#section_2'
        original = 'Read (' + url + ').\n![chart](https://example.com/chart.png)\nhttps://t.co/Example'
        provider = Provider(page([post(105, text=original)]))
        self.collect(provider)
        note = self.note.read_text(encoding='utf-8')
        self.assertIn('<https://example.com/report_name?q=a_b&next=%2Fpath#section_2>', note)
        self.assertIn(r'!\[chart\](<https://example.com/chart.png>)', note)
        self.assertIn('<https://t.co/Example>', note)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(self.state()['accounts']['actual']['posts']['105']['text'], original)

    def test_known_url_entity_preserves_trailing_url_punctuation(self):
        source = post(105, text='Read https://example.com/path. and https://example.com/a_(b).')
        source['entities'] = {'urls': [{'url': 'https://example.com/path.'}]}
        self.collect(Provider(page([source])))
        note = self.note.read_text(encoding='utf-8')
        self.assertIn('<https://example.com/path.>', note)
        self.assertIn('<https://example.com/a_(b)>.', note)

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

        def editor_writes_during_render(account, assets=None):
            output = real_render(account, assets)
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

    def test_duplicate_known_roster_aliases_fail_before_paid_collection(self):
        self.collect(Provider(page([post(105)])))
        self.roster.write_text('- [x] @actual\n- [x] @renamed <!-- x-user-id: 12 -->\n', encoding='utf-8')
        before_state, before_note = self.state_path.read_bytes(), self.note.read_bytes()
        provider = Provider()
        with self.assertRaisesRegex(feed.FeedError, 'duplicate_account_identity'):
            self.collect(provider, until=LATER)
        self.assertEqual(provider.calls, [])
        self.assertEqual(self.state_path.read_bytes(), before_state)
        self.assertEqual(self.note.read_bytes(), before_note)

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

    def test_id_based_sample_updates_accept_an_edit_with_original_creation_time(self):
        with patch.object(feed, 'now', return_value=FIRST):
            self.collect(Provider(page([post(105, text='Source before a later edit.')])), latest=1)
        edited = post(110, text='Updated source returned directly by the timeline.')
        edited['edit_history_post_ids'] = ['105', '110']
        with patch.object(feed, 'now', return_value=LATER):
            self.collect(Provider(page([edited])), until=LATER, latest=1)
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

    def test_reconciliation_batch_distinguishes_missing_edit_from_returned_version(self):
        original = post(105, text='Old source body.')
        latest = post(110, text='Current source body.')
        for row in (original, latest):
            row['edit_history_post_ids'] = ['105', '110']
        self.collect(Provider(page([latest])))
        missing = lambda identity: {'resource_id': str(identity),
                                   'type': 'https://api.x.com/2/problems/resource-not-found'}
        for returned, absent, expected_status in ((latest, 105, 'available'), (original, 110, 'unavailable')):
            with self.subTest(returned=returned['id'], missing=absent):
                provider = Provider({'data': [returned], 'errors': [missing(absent)]})
                with patch.object(feed, 'request_json', side_effect=provider):
                    result = feed.execute(self.args(command='reconcile', account='actual', ids='105,110',
                                                    allow_paid_reread=True))
                self.assertEqual(len(provider.calls), 1)
                self.assertEqual(result['returned_posts'], 1)
                self.assertIsNone(self.state()['pending'])
                saved = self.state()['accounts']['actual']['posts']
                self.assertEqual(set(saved), {'110'})
                self.assertEqual(saved['110']['status'], expected_status)
                self.assertNotIn(original['text'], self.note.read_text(encoding='utf-8'))
                if expected_status == 'unavailable':
                    self.assertNotIn(latest['text'], self.state_path.read_text(encoding='utf-8'))
                    self.assertNotIn(latest['text'], self.note.read_text(encoding='utf-8'))

    def test_reconciliation_still_rejects_direct_returned_and_missing_contradiction(self):
        latest = post(110)
        latest['edit_history_post_ids'] = ['105', '110']
        self.collect(Provider(page([latest])))
        provider = Provider({'data': [latest], 'errors': [{'resource_id': '110',
                             'type': 'https://api.x.com/2/problems/resource-not-found'}]})
        with patch.object(feed, 'request_json', side_effect=provider), \
                self.assertRaisesRegex(feed.FeedError, 'contradictory_reconciliation_response'):
            feed.execute(self.args(command='reconcile', account='actual', ids='105,110', allow_paid_reread=True))
        self.assertIn('response', self.state()['pending'])
        self.assertEqual(self.state()['accounts']['actual']['posts']['110']['status'], 'available')

    def test_latest_sample_reads_beyond_seven_days_and_parks_older_cursor(self):
        rows = [post(identity, '2026-08-01T12:00:00Z') for identity in range(110, 100, -1)]
        provider = Provider(page(rows, 'older-pages'))
        result = self.collect(provider, latest=10)
        query = provider.calls[1][1]
        self.assertNotIn('start_time', query)
        self.assertEqual(query['max_results'], 10)
        self.assertEqual(query['expansions'], 'attachments.media_keys')
        account = self.state()['accounts']['actual']
        self.assertEqual(account['sample']['status'], 'target_reached')
        self.assertEqual(account['sample']['deferred_window']['next_token'], 'older-pages')
        self.assertIsNone(account['window'])
        self.assertEqual(account['since_id'], '110')
        self.assertEqual(result['partial_accounts'], 0)
        self.assertEqual(result['accounts'][0]['sample_status'], 'target_reached')
        again = Provider()
        self.collect(again, latest=10)
        self.assertEqual(again.calls, [])
        fresh = Provider(page([post(111, '2026-09-07T13:00:00Z')]))
        self.collect(fresh, latest=10, until=LATER)
        self.assertEqual(fresh.calls[0][1]['since_id'], '110')
        self.assertNotIn('pagination_token', fresh.calls[0][1])
        self.assertEqual(len(self.state()['accounts']['actual']['posts']), 11)

    def test_latest_target_is_per_account_but_rows_have_one_invocation_budget(self):
        self.roster.write_text('- [x] @actual\n- [x] @second\n', encoding='utf-8')
        calls = []
        def provider(path, query, bearer):
            calls.append((path, deepcopy(query)))
            if '/by/username/' in path:
                name = path.rsplit('/', 1)[1]
                return {'data': {'id': '12' if name == 'actual' else '13', 'username': name}}
            rows = [post(value) for value in range(110, 100, -1)]
            if '/13/' in path:
                for row in rows:
                    row['author_id'] = '13'
                    row['id'] = str(int(row['id']) + 100)
            return page(rows, 'older')
        result = self.collect(provider, latest=10, max_posts=20)
        self.assertEqual(result['returned_posts'], 20)
        self.assertEqual([len(a['posts']) for a in self.state()['accounts'].values()], [10, 10])
        self.assertEqual([query['max_results'] for path, query in calls if '/tweets' in path], [10, 10])

    def test_latest_filters_short_pages_then_keeps_minimum_page_overshoot(self):
        reply = post(109, text='Must not be archived')
        reply['referenced_tweets'] = [{'id': '30', 'type': 'replied_to'}]
        first = Provider(page([reply, *[post(value) for value in range(108, 101, -1)]], 'two'))
        result = self.collect(first, latest=10, max_posts=10)
        self.assertEqual(result['returned_posts'], 8)
        self.assertEqual(self.state()['accounts']['actual']['sample']['status'], 'in_progress')
        second = Provider(page([post(value) for value in range(101, 96, -1)], 'three'))
        result = self.collect(second, latest=10, max_posts=5)
        self.assertEqual(second.calls[0][1]['pagination_token'], 'two')
        self.assertEqual(second.calls[0][1]['max_results'], 5)
        self.assertEqual(result['stored_posts'], 12)
        self.assertEqual(self.state()['accounts']['actual']['sample']['status'], 'target_reached')

    def test_latest_exhausted_quiet_account_reports_shortfall_without_repeating(self):
        result = self.collect(Provider(page([post(105, '2026-01-01T00:00:00Z')])), latest=10)
        account = self.state()['accounts']['actual']
        self.assertEqual(account['sample']['status'], 'available_history_exhausted')
        self.assertEqual(result['stored_posts'], 1)
        again = Provider()
        self.collect(again, latest=10)
        self.assertEqual(again.calls, [])

    def test_latest_sample_counts_repost_wrappers_toward_target_without_extra_paid_pages(self):
        repost = post(109, text='RT @source: A repost counts as one retained account event')
        repost['referenced_tweets'] = [{'id': '82', 'type': 'retweeted'}]
        provider = Provider(page([repost, post(108)], 'older-not-needed'))
        result = self.collect(provider, latest=2)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(result['returned_posts'], 2)
        self.assertEqual(result['stored_posts'], 2)
        self.assertEqual(self.state()['accounts']['actual']['sample']['status'], 'target_reached')
        again = Provider()
        self.collect(again, latest=2)
        self.assertEqual(again.calls, [])

    def test_resumed_sample_reaches_target_then_checks_current_requested_cutoff(self):
        self.collect(Provider(page([post(110)], 'older')), latest=2, max_requests=2)
        provider = Provider(page([post(109)], 'intentionally-omitted'),
                            page([post(111, '2026-09-07T13:00:00Z')]))
        result = self.collect(provider, latest=2, until=LATER)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(provider.calls[0][1]['pagination_token'], 'older')
        self.assertEqual(provider.calls[0][1]['end_time'], FIRST)
        self.assertEqual(provider.calls[1][1]['since_id'], '110')
        self.assertEqual(provider.calls[1][1]['end_time'], LATER)
        self.assertNotIn('pagination_token', provider.calls[1][1])
        account = self.state()['accounts']['actual']
        self.assertEqual(account['sample']['status'], 'target_reached')
        self.assertEqual(account['sample']['cutoff'], FIRST)
        self.assertEqual(account['sample']['deferred_window']['next_token'], 'intentionally-omitted')
        self.assertEqual(account['completed_at'], LATER)
        self.assertEqual(account['since_id'], '111')
        row = result['accounts'][0]
        self.assertEqual(row['status'], 'initial_sample_target_reached')
        self.assertEqual(row['forward_status'], 'complete')
        self.assertEqual(row['requested_through'], LATER)
        self.assertEqual(result['deferred_accounts'], [])

    def test_resumed_sample_reports_current_cutoff_deferred_when_request_budget_ends(self):
        self.collect(Provider(page([post(110)], 'older')), latest=2, max_requests=2)
        result = self.collect(Provider(page([post(109)], 'omitted')), latest=2, until=LATER, max_requests=1)
        row = result['accounts'][0]
        self.assertEqual(row['sample_status'], 'target_reached')
        self.assertEqual(row['status'], 'partial')
        self.assertEqual(row['forward_status'], 'pending')
        self.assertEqual(row['completed_through'], FIRST)
        self.assertEqual(row['requested_through'], LATER)
        self.assertIn('requested_cutoff_not_reached', row['deferred_reasons'])
        self.assertIn('request_budget_exhausted', row['deferred_reasons'])
        self.assertEqual(result['deferred_accounts'], ['actual'])
        self.assertEqual(result['partial_accounts'], 1)
        self.assertNotIn('Collection status:', self.note.read_text(encoding='utf-8'))
        self.assertEqual(feed.execute(self.args(command='status'))['accounts'][0]['forward_status'], 'pending')

    def test_resumed_normal_window_requeues_forward_interval_before_reporting_complete(self):
        self.collect(Provider(page([post(110)], 'older')), max_requests=2)
        provider = Provider(page([post(109)]), page([post(111, '2026-09-07T13:00:00Z')]))
        result = self.collect(provider, until=LATER)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(provider.calls[1][1]['start_time'], FIRST)
        self.assertNotIn('since_id', provider.calls[1][1])
        self.assertEqual(result['accounts'][0]['status'], 'bounded_window_complete')
        self.assertEqual(result['accounts'][0]['completed_through'], LATER)

    def test_active_empty_sample_has_in_progress_status_and_fixed_target(self):
        result = self.collect(Provider(page([], 'older')), latest=10, max_requests=2)
        row = result['accounts'][0]
        self.assertEqual(row['status'], 'initial_sample_in_progress')
        self.assertIn('initial_sample_incomplete', row['deferred_reasons'])
        provider = Provider()
        with self.assertRaisesRegex(feed.FeedError, 'initial_sample_target_already_fixed'):
            self.collect(provider, latest=20)
        self.assertEqual(provider.calls, [])

    def test_legacy_partial_window_keeps_query_fields_and_cursor_then_expands_older_history(self):
        self.collect(Provider(page([post(110), post(109)], 'old-page')), max_requests=2)
        state = self.state()
        window = state['accounts']['actual']['window']
        window.pop('fields')  # Exact released 1.7.0 window layout.
        window.pop('since_id')
        window['exclude'] = 'retweets,replies'
        self.state_path.write_text(json.dumps(state), encoding='utf-8')
        original_start = window['start']
        resumed = Provider(page([post(108)]), page([post(value, '2026-08-01T12:00:00Z') for value in range(107, 100, -1)], 'older'))
        self.collect(resumed, latest=10)
        self.assertEqual(resumed.calls[0][1]['pagination_token'], 'old-page')
        self.assertEqual(resumed.calls[0][1]['start_time'], original_start)
        self.assertEqual(resumed.calls[0][1]['exclude'], 'retweets,replies')
        self.assertNotIn('expansions', resumed.calls[0][1])
        self.assertEqual(resumed.calls[1][1]['end_time'], original_start)
        self.assertNotIn('exclude', resumed.calls[1][1])
        self.assertNotIn('start_time', resumed.calls[1][1])
        self.assertNotIn('since_id', resumed.calls[1][1])
        self.assertEqual(resumed.calls[1][1]['expansions'], 'attachments.media_keys')
        account = self.state()['accounts']['actual']
        self.assertEqual(len(account['posts']), 10)
        self.assertEqual(account['since_id'], '110')
        self.assertEqual(account['completed_at'], FIRST)

    def test_legacy_satisfied_partial_sample_is_parked_without_any_paid_reads(self):
        self.collect(Provider(page([post(105)], 'old-page')), max_requests=2)
        before = self.state()['accounts']['actual']['window']
        provider = Provider()
        self.collect(provider, latest=1)
        self.assertEqual(provider.calls, [])
        account = self.state()['accounts']['actual']
        self.assertEqual(account['sample']['deferred_window'], before)
        self.assertEqual(account['since_id'], '105')

    def test_sample_adoption_does_not_skip_pending_forward_posts_using_old_history(self):
        self.collect(Provider(page([post(value) for value in range(110, 100, -1)])))
        self.collect(Provider(page([post(120, '2026-09-07T13:00:00Z')], 'remaining-new-posts')),
                     until=LATER, max_requests=1)
        pending = self.state()['accounts']['actual']['window']
        provider = Provider(page([post(value, '2026-09-07T12:30:00Z') for value in range(119, 110, -1)]))
        # A new target cannot drop the unfinished forward interval, even when
        # old saved posts already exceed the target. Page minimums still apply.
        result = self.collect(provider, latest=10, until=LATER)
        self.assertEqual(len(provider.calls), 1)
        query = provider.calls[0][1]
        self.assertEqual(query['pagination_token'], pending['next_token'])
        self.assertEqual(query['start_time'], FIRST)
        self.assertNotIn('since_id', query)
        account = self.state()['accounts']['actual']
        self.assertEqual(set(account['posts']), {str(value) for value in range(101, 121)})
        self.assertEqual(account['completed_at'], LATER)
        self.assertEqual(account['sample']['status'], 'target_reached')
        self.assertNotIn('deferred_window', account['sample'])
        self.assertEqual(result['accounts'][0]['forward_status'], 'complete')

    def test_sample_adoption_keeps_oldest_boundary_after_draining_forward_window(self):
        self.collect(Provider(page([post(110)])))
        oldest_boundary = self.state()['accounts']['actual']['history_before']
        self.collect(Provider(page([post(120, '2026-09-07T13:00:00Z')], 'remaining-new-posts')),
                     until=LATER, max_requests=1)
        provider = Provider(page([post(119, '2026-09-07T12:30:00Z')]),
                            page([post(100, '2026-08-01T12:00:00Z')]))
        self.collect(provider, latest=10, until=LATER)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(provider.calls[0][1]['pagination_token'], 'remaining-new-posts')
        self.assertEqual(provider.calls[1][1]['end_time'], oldest_boundary)
        self.assertNotIn('since_id', provider.calls[1][1])
        self.assertNotIn('start_time', provider.calls[1][1])
        account = self.state()['accounts']['actual']
        self.assertEqual(account['completed_at'], LATER)
        self.assertEqual(account['sample']['status'], 'available_history_exhausted')

    def test_legacy_completed_empty_window_requires_known_nonoverlapping_bound(self):
        self.collect(Provider(page([])))
        state = self.state()
        state['accounts']['actual'].pop('history_before')
        self.state_path.write_text(json.dumps(state), encoding='utf-8')
        provider = Provider()
        with self.assertRaisesRegex(feed.FeedError, 'requires_history_before'):
            self.collect(provider, latest=10)
        self.assertEqual(provider.calls, [])
        boundary = '2026-08-31T12:00:00Z'
        older = Provider(page([post(105, '2026-08-01T12:00:00Z')]))
        self.collect(older, latest=10, history_before=boundary)
        self.assertEqual(older.calls[0][1]['end_time'], boundary)
        self.assertNotIn('since_id', older.calls[0][1])
        self.assertEqual(self.state()['accounts']['actual']['sample']['status'], 'available_history_exhausted')

    def test_saved_latest_response_is_consumed_without_charging_its_rows_again(self):
        provider = Provider(page([post(105, '2026-08-01T12:00:00Z')], 'older'))
        real_apply = feed.apply_response
        def crash(store):
            if store.data['pending']['kind'] == 'timeline':
                raise RuntimeError('offline interruption')
            return real_apply(store)
        with patch.object(feed, 'apply_response', side_effect=crash), self.assertRaises(RuntimeError):
            self.collect(provider, latest=1)
        no_calls = Provider()
        result = self.collect(no_calls, latest=1)
        self.assertEqual(no_calls.calls, [])
        self.assertEqual(result['returned_posts'], 0)
        self.assertEqual(result['resumed_returned_posts'], 1)
        self.assertEqual(result['processed_rows'], 1)
        self.assertEqual(sum(result['row_counts'].values()), 1)

    def test_abandoned_older_sample_does_not_reset_forward_progress(self):
        self.collect(Provider(page([post(105)])))
        with self.assertRaises(feed.FeedError):
            self.collect(Provider(TimeoutError()), latest=10)
        self.assertLess(feed.instant(self.state()['accounts']['actual']['window']['end']), feed.instant(FIRST))
        feed.execute(self.args(command='resolve-pending', outcome='abandon'))
        account = self.state()['accounts']['actual']
        self.assertEqual(account['sample']['status'], 'abandoned')
        self.assertEqual(account['completed_at'], FIRST)
        fresh = Provider(page([post(106, '2026-09-07T13:00:00Z')]))
        self.collect(fresh, latest=10, until=LATER)
        self.assertEqual(fresh.calls[0][1]['start_time'], FIRST)
        self.assertNotIn('since_id', fresh.calls[0][1])

    def test_legacy_accounting_is_reported_unknown_without_reconstructing_paid_rows(self):
        self.collect(Provider(page([post(105)])))
        state = self.state()
        for request in state['requests']:
            request.pop('row_counts', None)
            request.pop('reply_exclusions', None)
            request.pop('query', None)
        self.state_path.write_text(json.dumps(state), encoding='utf-8')
        before = self.state_path.read_bytes()
        status = feed.execute(self.args(command='status'))
        account = status['accounts'][0]
        self.assertEqual(account['legacy_unclassified_rows'], 1)
        self.assertEqual(account['accounted_returned_rows'], 1)
        self.assertEqual(sum(account['row_counts'].values()), 0)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_row_accounting_is_mutually_exclusive_and_retains_safe_query(self):
        initial = post(105)
        self.collect(Provider(page([initial], 'two')), max_requests=2)
        edited = post(106, text='Edited source')
        edited['edit_history_post_ids'] = ['105', '106']
        reply = post(110)
        reply['referenced_tweets'] = [{'id': '30', 'type': 'retweeted'}, {'id': '31', 'type': 'replied_to'}]
        repost = post(109)
        repost['referenced_tweets'] = [{'id': '30', 'type': 'retweeted'}]
        rows = [initial, edited, reply, deepcopy(reply), repost, post(108), post(108)]
        result = self.collect(Provider(page(rows)))
        expected = {'excluded_replies': 2, 'excluded_reposts': 0, 'duplicate_rows': 2,
                    'merged_versions': 1, 'newly_stored_posts': 2, 'updated_existing_posts': 0}
        self.assertEqual(result['row_counts'], expected)
        self.assertEqual(sum(expected.values()), result['returned_posts'])
        self.assertEqual(result['unexpected_filter_rows'], 0)
        request = self.state()['requests'][-1]
        self.assertEqual(request['row_counts'], expected)
        self.assertNotIn('exclude', request['query'])
        self.assertEqual(request['query']['pagination_token'], 'two')
        self.assertNotIn(initial['text'], json.dumps(request))
        self.assertNotIn(edited['text'], json.dumps(request))

    def test_historical_excluded_repost_counts_remain_readable_and_unchanged(self):
        excluded = post(105, text='Historical excluded row body')
        excluded['referenced_tweets'] = [{'id': '30', 'type': 'replied_to'}]
        self.collect(Provider(page([excluded])))
        state = self.state()
        request = state['requests'][-1]
        request['query']['exclude'] = 'retweets,replies'
        request.pop('reply_exclusions', None)
        request['row_counts']['excluded_replies'] = 0
        request['row_counts']['excluded_reposts'] = 1
        self.state_path.write_text(json.dumps(state), encoding='utf-8')
        before = self.state_path.read_bytes()
        status = feed.execute(self.args(command='status'))
        self.assertEqual(status['accounts'][0]['row_counts']['excluded_reposts'], 1)
        self.assertEqual(status['accounts'][0]['accounted_returned_rows'], 1)
        self.assertEqual(self.state_path.read_bytes(), before)
        repost = post(106, '2026-09-07T13:00:00Z', text='Current included repost body')
        repost['referenced_tweets'] = [{'id': '30', 'type': 'retweeted'}]
        result = self.collect(Provider(page([repost])), until=LATER)
        self.assertEqual(result['row_counts']['excluded_reposts'], 0)
        self.assertEqual(result['row_counts']['newly_stored_posts'], 1)
        self.assertEqual(self.state()['requests'][-2], request)
        self.assertEqual(set(self.state()['accounts']['actual']['posts']), {'106'})

    def test_capacity_headroom_refuses_before_any_paid_request(self):
        provider = Provider()
        with feed.Store(self.vault, create=True) as store:
            before = self.state_path.read_bytes()
            with patch.object(feed, 'API_RESPONSE_LIMIT', 1024), patch.object(feed, 'LIMIT', len(before) + 2048):
                with self.assertRaisesRegex(feed.FeedError, 'state_capacity_headroom_required; no_api_request_made'):
                    feed.paid_request(store, 'user', 'actual', '/2/users/by/username/actual', {},
                                      'offline-token', provider)
            self.assertIsNone(store.data['pending'])
            self.assertEqual(provider.calls, [])
            self.assertEqual(self.state_path.read_bytes(), before)

    def test_oversized_successful_response_is_durable_in_private_recovery(self):
        nested = 'Received source text must survive.'
        for _ in range(90):
            nested = [nested]
        response = {'data': {'id': '12', 'username': 'actual'}, 'extra_metadata': nested}
        self.assertLess(len(json.dumps(response, separators=(',', ':')).encode()), 1024)
        calls = []
        def provider(path, query, bearer):
            calls.append(path)
            return deepcopy(response)
        with feed.Store(self.vault, create=True) as store:
            limit = len(self.state_path.read_bytes()) + 9000
            with patch.object(feed, 'API_RESPONSE_LIMIT', 1024), patch.object(feed, 'LIMIT', limit):
                with self.assertRaisesRegex(feed.FeedError, 'state_capacity_reached; preserved_recovery=') as caught:
                    feed.paid_request(store, 'user', 'actual', '/2/users/by/username/actual', {},
                                      'offline-token', provider)
            recovery = Path(str(caught.exception).split('preserved_recovery=', 1)[1])
            self.assertTrue(recovery.is_relative_to(self.state_path.parent))
            self.assertEqual(recovery.stat().st_mode & 0o777, 0o700)
            saved = recovery / 'state.json'
            self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
            self.assertGreater(saved.stat().st_size, limit)
            recovered = json.loads(saved.read_text(encoding='utf-8'))
            self.assertEqual(recovered['pending']['response'], response)
            disk = self.state()
            self.assertNotIn('response', disk['pending'])
            self.assertEqual(recovered['pending']['request_id'], disk['pending']['request_id'])
            self.assertEqual(len(calls), 1)
        with feed.Store(self.vault) as reopened:
            with self.assertRaisesRegex(feed.FeedError, 'unresolved_request_blocks_network'):
                feed.paid_request(reopened, 'user', 'actual', '/2/users/by/username/actual', {},
                                  'offline-token', provider)
        self.assertEqual(len(calls), 1)

    def test_only_primary_post_photo_expansions_are_saved_and_reused(self):
        raw = post(105)
        raw['attachments'] = {'media_keys': ['photo', 'video']}
        raw['referenced_tweets'] = [{'id': '90', 'type': 'quoted'}]
        response = page([raw])
        response['includes'] = {'media': [
            {'media_key': 'photo', 'type': 'photo', 'url': 'https://pbs.twimg.com/media/original.jpg', 'alt_text': 'Source alt'},
            {'media_key': 'video', 'type': 'video', 'preview_image_url': 'https://pbs.twimg.com/preview.jpg'},
            {'media_key': 'quoted', 'type': 'photo', 'url': 'https://pbs.twimg.com/quoted.jpg'}]}
        self.collect(Provider(response))
        saved = self.state()['accounts']['actual']['posts']['105']
        self.assertEqual([item['media_key'] for item in saved['media']], ['photo', 'video'])
        self.assertNotIn('preview_image_url', saved['media'][1])
        with patch.object(feed, 'request_json', side_effect=Provider({'data': [raw]})):
            feed.execute(self.args(command='reconcile', account='actual', ids='105', allow_paid_reread=True))
        self.assertEqual(self.state()['accounts']['actual']['posts']['105']['media'], saved['media'])


if __name__ == '__main__':
    unittest.main()
