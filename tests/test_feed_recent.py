#!/usr/bin/env python3
"""Offline rolling-window regressions for paid X collection and safe recovery."""
from copy import deepcopy
from datetime import datetime
import json
import unittest
from unittest.mock import patch

import test_feed_collect as fixtures

feed = fixtures.feed
FIRST = fixtures.FIRST
Provider = fixtures.Provider
page = fixtures.page
post = fixtures.post
FLOOR = '2026-09-04T12:00:00Z'


class RecentFeedTests(unittest.TestCase):
    # Reuse only fixture plumbing, not the original test class/test methods.
    setUp = fixtures.FeedCollectionTests.setUp
    args = fixtures.FeedCollectionTests.args
    collect = fixtures.FeedCollectionTests.collect
    state = fixtures.FeedCollectionTests.state
    note = fixtures.FeedCollectionTests.note
    state_path = fixtures.FeedCollectionTests.state_path

    def save(self, state):
        self.state_path.write_text(json.dumps(state), encoding='utf-8')

    def test_normal_defaults_have_no_roster_wide_request_or_post_ceiling(self):
        args = self.args()
        self.assertIsNone(args.max_requests)
        self.assertIsNone(args.max_posts)

    def test_fresh_collection_accepts_exact_three_day_boundary_and_avoids_id_override(self):
        provider = Provider(page([post(105), post(101, FLOOR)]))
        result = self.collect(provider)
        query = provider.calls[1][1]
        self.assertEqual(query['start_time'], FLOOR)
        self.assertEqual(query['end_time'], FIRST)
        self.assertNotIn('since_id', query)
        self.assertEqual(query['exclude'], 'replies')
        self.assertEqual(set(self.state()['accounts']['actual']['posts']), {'101', '105'})
        self.assertEqual(result['deferred_accounts'], [])
        none = Provider()
        original = self.note.read_bytes()
        self.collect(none)
        self.assertEqual(none.calls, [])
        self.assertEqual(self.note.read_bytes(), original)

    def test_live_default_floor_uses_actual_start_time_not_thirty_second_cutoff_lag(self):
        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls.fromisoformat('2026-09-07T12:00:30+00:00').astimezone(tz)

        args = self.args()
        args.until = None
        provider = Provider(page([]))
        with patch.object(feed, 'datetime', FixedDateTime):
            feed.collect(args, fetch=provider, record=fixtures.RECORD)
        query = provider.calls[1][1]
        self.assertEqual(query['start_time'], '2026-09-04T12:00:30Z')
        self.assertEqual(query['end_time'], FIRST)

    def test_out_of_window_response_is_retained_for_recovery_not_archived(self):
        provider = Provider(page([post(101, '2026-09-04T11:59:59Z')]))
        with self.assertRaisesRegex(feed.FeedError, 'post_outside_requested_window'):
            self.collect(provider)
        state = self.state()
        self.assertIn('response', state['pending'])
        self.assertEqual(state['accounts']['actual']['posts'], {})
        blocked = Provider()
        with self.assertRaisesRegex(feed.FeedError, 'post_outside_requested_window'):
            self.collect(blocked)
        self.assertEqual(blocked.calls, [])

    def test_exclusive_end_time_row_is_rejected_without_archiving_or_retrying(self):
        provider = Provider(page([post(105, FIRST)]))
        with self.assertRaisesRegex(feed.FeedError, 'post_outside_requested_window'):
            self.collect(provider)
        state = self.state()
        self.assertIn('response', state['pending'])
        self.assertEqual(state['accounts']['actual']['posts'], {})
        blocked = Provider()
        with self.assertRaisesRegex(feed.FeedError, 'post_outside_requested_window'):
            self.collect(blocked)
        self.assertEqual(blocked.calls, [])

    def test_long_downtime_starts_at_new_floor_and_preserves_older_saved_posts(self):
        self.collect(Provider(page([post(105)])))
        until = '2026-09-12T12:00:00Z'
        provider = Provider(page([post(110, '2026-09-11T11:00:00Z')]))
        self.collect(provider, until=until)
        self.assertEqual(len(provider.calls), 1)
        query = provider.calls[0][1]
        self.assertEqual(query['start_time'], '2026-09-09T12:00:00Z')
        self.assertEqual(query['end_time'], until)
        self.assertNotIn('since_id', query)
        self.assertNotIn('pagination_token', query)
        self.assertEqual(set(self.state()['accounts']['actual']['posts']), {'105', '110'})
        self.assertIn('2026-09-07 11:00:00 UTC', self.note.read_text(encoding='utf-8'))

    def test_edited_sample_frontier_does_not_make_unread_recent_posts_look_expired(self):
        edited = post(110, '2026-08-01T11:00:00Z')
        edited['edit_history_post_ids'] = ['90', '110']
        self.collect(Provider(page([edited], 'unread-tail')), latest=1)
        provider = Provider(page([post(105)]))
        self.collect(provider)
        self.assertEqual(len(provider.calls), 1)
        query = provider.calls[0][1]
        self.assertEqual(query['start_time'], FLOOR)
        self.assertEqual(query['until_id'], '110')
        self.assertNotIn('pagination_token', query)
        self.assertEqual(set(self.state()['accounts']['actual']['posts']), {'105', '110'})

    def test_empty_feed_advances_watermark_and_same_cutoff_is_free(self):
        provider = Provider(page([]))
        result = self.collect(provider)
        self.assertEqual(result['returned_posts'], 0)
        self.assertEqual(result['deferred_accounts'], [])
        self.assertEqual(self.state()['accounts']['actual']['completed_at'], FIRST)
        none = Provider()
        self.collect(none)
        self.assertEqual(none.calls, [])
        fresh = Provider(page([]))
        self.collect(fresh, until=fixtures.LATER)
        self.assertEqual(fresh.calls[0][1]['start_time'], FIRST)
        self.assertNotIn('since_id', fresh.calls[0][1])

    def test_entire_roster_finishes_beyond_both_former_default_budgets(self):
        self.roster.write_text(''.join(f'- [x] @account{index}\n' for index in range(26)), encoding='utf-8')
        calls = []

        def provider(path, query, bearer):
            calls.append((path, deepcopy(query)))
            if '/by/username/' in path:
                name = path.rsplit('/', 1)[1]
                return {'data': {'id': str(100 + int(name.removeprefix('account'))), 'username': name}}
            user_id = path.split('/')[-2]
            rows = [post(int(user_id) * 1000 + offset) for offset in range(40)]
            for row in rows:
                row['author_id'] = user_id
            return page(rows)

        result = self.collect(provider)
        self.assertEqual(result['requests'], 52)
        self.assertEqual(result['returned_posts'], 1040)
        self.assertEqual(result['newly_stored_posts'], 1040)
        self.assertEqual(result['deferred_accounts'], [])
        self.assertEqual(len(list(self.note.parent.glob('*.md'))), 26)
        timeline_queries = [query for path, query in calls if '/tweets' in path]
        self.assertEqual(len(timeline_queries), 26)
        self.assertTrue(all(query['start_time'] == FLOOR for query in timeline_queries))
        self.assertTrue(all('since_id' not in query for query in timeline_queries))
        none = Provider()
        self.collect(none)
        self.assertEqual(none.calls, [])

    def test_explicit_request_budget_still_preserves_pagination_for_resume(self):
        first = Provider(page([post(105)], 'unread-page'))
        result = self.collect(first, max_requests=2)
        self.assertEqual(result['requests'], 2)
        self.assertIn('request_budget_exhausted', result['accounts'][0]['deferred_reasons'])
        resume = Provider(page([post(104)]))
        result = self.collect(resume)
        self.assertEqual(len(resume.calls), 1)
        self.assertEqual(resume.calls[0][1]['pagination_token'], 'unread-page')
        self.assertEqual(result['newly_stored_posts'], 1)
        self.assertEqual(result['deferred_accounts'], [])

    def test_explicit_post_budget_still_limits_paid_rows(self):
        provider = Provider(page([post(value) for value in range(105, 100, -1)], 'unread-page'))
        result = self.collect(provider, max_posts=5)
        self.assertEqual(provider.calls[1][1]['max_results'], 5)
        self.assertEqual(result['returned_posts'], 5)
        self.assertIn('post_budget_below_minimum_page', result['accounts'][0]['deferred_reasons'])
        self.assertEqual(self.state()['accounts']['actual']['window']['next_token'], 'unread-page')

    def test_aging_partial_rebases_only_unread_rows_using_excluded_row_frontier(self):
        reply = post(180, '2026-09-06T17:00:00Z', 'Excluded reply still advances the paid-page frontier.')
        reply['referenced_tweets'] = [{'id': '150', 'type': 'replied_to'}]
        self.collect(Provider(page([post(200), post(190, '2026-09-06T18:00:00Z'), reply], 'old-cursor')),
                     max_requests=2)
        window = self.state()['accounts']['actual']['window']
        self.assertEqual(window['oldest_id'], '180')
        self.assertEqual(window['oldest_at'], reply['created_at'])
        self.assertNotIn('180', self.state()['accounts']['actual']['posts'])
        until = '2026-09-09T12:00:00Z'
        provider = Provider(page([post(179, '2026-09-06T16:00:00Z')]),
                            page([post(201, '2026-09-08T11:00:00Z')]))
        result = self.collect(provider, until=until)
        self.assertEqual(len(provider.calls), 2)
        tail = provider.calls[0][1]
        self.assertEqual(tail['start_time'], '2026-09-06T12:00:00Z')
        self.assertEqual(tail['end_time'], FIRST)
        self.assertEqual(tail['until_id'], '180')
        self.assertNotIn('since_id', tail)
        self.assertNotIn('pagination_token', tail)
        forward = provider.calls[1][1]
        self.assertEqual(forward['start_time'], FIRST)
        self.assertEqual(forward['end_time'], until)
        self.assertNotIn('since_id', forward)
        self.assertNotIn('until_id', forward)
        self.assertEqual(result['newly_stored_posts'], 2)
        self.assertEqual(result['deferred_accounts'], [])
        self.assertEqual(set(self.state()['accounts']['actual']['posts']), {'179', '190', '200', '201'})

    def test_fully_expired_partial_is_retired_without_reading_its_saved_cursor(self):
        self.collect(Provider(page([post(105)], 'old-cursor')), max_requests=2)
        provider = Provider(page([post(110, '2026-09-10T11:00:00Z')]))
        until = '2026-09-11T12:00:00Z'
        result = self.collect(provider, until=until)
        self.assertEqual(len(provider.calls), 1)
        query = provider.calls[0][1]
        self.assertEqual(query['start_time'], '2026-09-08T12:00:00Z')
        self.assertNotIn('pagination_token', query)
        self.assertNotIn('until_id', query)
        account = self.state()['accounts']['actual']
        self.assertTrue(account['retired_windows'])
        self.assertEqual(set(account['posts']), {'105', '110'})
        self.assertEqual(result['deferred_accounts'], [])

    def test_unread_tail_below_floor_is_retired_even_while_window_end_is_recent(self):
        self.collect(Provider(page([post(105), post(101, '2026-09-04T13:00:00Z')], 'expired-tail')),
                     max_requests=2)
        provider = Provider(page([post(110, '2026-09-08T11:00:00Z')]))
        result = self.collect(provider, until='2026-09-08T12:00:00Z')
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0][1]['start_time'], FIRST)
        self.assertNotIn('pagination_token', provider.calls[0][1])
        self.assertTrue(self.state()['accounts']['actual']['retired_windows'])
        self.assertEqual(result['deferred_accounts'], [])

    def test_legacy_cursor_without_paid_frontier_is_reported_without_network_replay(self):
        self.collect(Provider(page([post(105)], 'legacy-cursor')), max_requests=2)
        state = self.state()
        window = state['accounts']['actual']['window']
        window.pop('oldest_id', None)
        window.pop('oldest_at', None)
        self.save(state)
        provider = Provider()
        result = self.collect(provider, until='2026-09-08T12:00:00Z')
        self.assertEqual(provider.calls, [])
        self.assertIn('legacy_cursor_needs_recent_boundary', result['accounts'][0]['deferred_reasons'])
        self.assertEqual(result['deferred_accounts'], ['actual'])
        self.assertEqual(self.state()['accounts']['actual']['window']['next_token'], 'legacy-cursor')

    def test_switch_from_partial_initial_sample_does_not_continue_out_of_scope_history(self):
        self.collect(Provider(page([post(105, '2026-08-01T12:00:00Z')], 'old-sample')),
                     latest=10, max_requests=2)
        provider = Provider()
        result = self.collect(provider)
        self.assertEqual(provider.calls, [])
        account = self.state()['accounts']['actual']
        self.assertEqual(account['sample']['status'], 'superseded_by_recent_window')
        self.assertEqual(set(account['posts']), {'105'})
        self.assertIsNone(account['window'])
        self.assertEqual(result['deferred_accounts'], [])

    def test_completed_sample_recent_tail_is_collected_without_replaying_forward_history(self):
        self.collect(Provider(page([post(200), post(190, '2026-09-06T18:00:00Z')], 'parked-sample')),
                     latest=2)
        self.collect(Provider(page([post(201, '2026-09-07T13:00:00Z')])),
                     latest=2, until=fixtures.LATER)
        provider = Provider(page([post(180, '2026-09-06T17:00:00Z')]))
        result = self.collect(provider, until=fixtures.LATER)
        self.assertEqual(len(provider.calls), 1)
        query = provider.calls[0][1]
        self.assertEqual(query['start_time'], '2026-09-04T14:00:00Z')
        self.assertEqual(query['end_time'], FIRST)
        self.assertEqual(query['until_id'], '190')
        self.assertNotIn('pagination_token', query)
        self.assertNotIn('since_id', query)
        account = self.state()['accounts']['actual']
        self.assertEqual(account['completed_at'], fixtures.LATER)
        self.assertEqual(set(account['posts']), {'180', '190', '200', '201'})
        self.assertEqual(result['deferred_accounts'], [])
        none = Provider()
        self.collect(none, until=fixtures.LATER)
        self.assertEqual(none.calls, [])

    def test_abandoned_sample_never_replays_its_uncertain_page_when_switching_to_recent(self):
        self.collect(Provider(page([post(105)], 'uncertain-next-page')), latest=10, max_requests=2)
        with self.assertRaises(feed.FeedError):
            self.collect(Provider(TimeoutError('simulated uncertain paid sample page')), latest=10)
        feed.execute(self.args(command='resolve-pending', outcome='abandon'))
        resolved = self.state()['accounts']['actual']
        abandoned_window = deepcopy(resolved['sample']['deferred_window'])
        gaps = deepcopy(resolved['gaps'])
        self.assertEqual(abandoned_window['next_token'], 'uncertain-next-page')
        self.assertEqual(len(gaps), 1)

        provider = Provider()
        result = self.collect(provider)
        self.assertEqual(provider.calls, [])
        account = self.state()['accounts']['actual']
        self.assertEqual(account['sample']['status'], 'abandoned')
        self.assertEqual(account['sample']['deferred_window'], abandoned_window)
        self.assertEqual(account['gaps'], gaps)
        self.assertEqual(account['completed_at'], FIRST)
        self.assertIsNone(account['window'])
        self.assertIn('known_collection_gaps', result['accounts'][0]['deferred_reasons'])

        fresh = Provider(page([post(110, '2026-09-07T13:00:00Z')]))
        self.collect(fresh, until=fixtures.LATER)
        self.assertEqual(len(fresh.calls), 1)
        query = fresh.calls[0][1]
        self.assertEqual(query['start_time'], FIRST)
        self.assertEqual(query['end_time'], fixtures.LATER)
        self.assertNotIn('pagination_token', query)
        self.assertNotIn('until_id', query)
        self.assertNotIn('since_id', query)
        account = self.state()['accounts']['actual']
        self.assertEqual(account['sample']['deferred_window'], abandoned_window)
        self.assertEqual(account['gaps'], gaps)
        self.assertEqual(set(account['posts']), {'105', '110'})

    def test_saved_paid_page_is_consumed_offline_before_recent_policy_retires_old_tail(self):
        real_apply = feed.apply_response

        def crash_before_timeline_application(store):
            if store.data['pending'] and store.data['pending']['kind'] == 'timeline':
                raise OSError('simulated crash after durable response save')
            return real_apply(store)

        provider = Provider(page([post(105)], 'old-cursor'))
        with patch.object(feed, 'apply_response', side_effect=crash_before_timeline_application):
            with self.assertRaisesRegex(OSError, 'simulated crash'):
                self.collect(provider)
        self.assertIn('response', self.state()['pending'])
        resume = Provider(page([post(110, '2026-09-10T11:00:00Z')]))
        result = self.collect(resume, until='2026-09-11T12:00:00Z')
        self.assertEqual(len(resume.calls), 1)
        self.assertEqual(resume.calls[0][1]['start_time'], '2026-09-08T12:00:00Z')
        self.assertNotIn('pagination_token', resume.calls[0][1])
        self.assertEqual(result['resumed_returned_posts'], 1)
        self.assertEqual(set(self.state()['accounts']['actual']['posts']), {'105', '110'})
        self.assertIsNone(self.state()['pending'])

    def test_uncertain_paid_request_still_blocks_when_its_window_has_aged_out(self):
        with self.assertRaises(feed.FeedError):
            self.collect(Provider(TimeoutError('simulated uncertain paid read')))
        pending = deepcopy(self.state()['pending'])
        provider = Provider()
        with self.assertRaisesRegex(feed.FeedError, 'unresolved_request_blocks_network'):
            self.collect(provider, until='2026-09-11T12:00:00Z')
        self.assertEqual(provider.calls, [])
        self.assertEqual(self.state()['pending'], pending)


if __name__ == '__main__':
    unittest.main()
