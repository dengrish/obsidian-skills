#!/usr/bin/env python3
"""Offline forward tests for independent RSS persistence and research handoff."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/feed-collect/scripts'))
import rss_collect as rss
import test_feed_media as media_fixtures

FIRST = '2026-09-08T12:00:00Z'
LATER = '2026-09-09T12:00:00Z'
URL = 'https://example.com/feed'


def item(identity='one', text='<p>Company ABC grew sales.</p>', *, guid=None, title='Original title', date=True):
    return ('<item><title>' + title + '</title><link>https://example.com/p/' + identity + '</link>'
            '<guid>' + (guid or identity) + '</guid><author>Research Author</author>'
            + ('<pubDate>Mon, 01 Jun 2026 12:00:00 GMT</pubDate>' if date else '')
            + '<content:encoded><![CDATA[' + text + ']]></content:encoded></item>')


def body(*items, title='Example Research'):
    return ('<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>'
            '<title>' + title + '</title><link>https://example.com/</link>' + ''.join(items)
            + '</channel></rss>').encode('utf-8')


class Fetch:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, **validators):
        self.calls.append((url, validators))
        if not self.responses:
            raise AssertionError('Unexpected feed request')
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return {'status': 'not_modified' if value is None else 'modified', 'body': value,
                'final_url': url, 'etag': '"version-' + str(len(self.calls)) + '"',
                'last_modified': 'Mon, 01 Jun 2026 12:00:00 GMT', 'requests': 1, 'bytes': len(value or b'')}


class RSSCollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='rss-collect-forward-')
        self.addCleanup(self.tmp.cleanup)
        self.vault = Path(self.tmp.name).resolve()
        (self.vault / 'Investments').mkdir()
        self.roster = self.vault / rss.ROSTER_REL
        self.roster.write_text('- [x] ' + URL + ' — Research\n', encoding='utf-8')
        self.addCleanup(patch.stopall)
        self.clock = patch.object(rss, 'now', return_value=FIRST).start()
        patch.object(rss.common, 'provenance', return_value={
            'skill': 'investments:feed-collect', 'plugin_version': '1.14.0',
            'source_commit': None, 'source_url': None, 'source_status': 'uncommitted',
            'runtime_sha256': '0' * 64}).start()
        self.asset_fetch = media_fixtures.Fetch()

    def collect(self, fetch, **kwargs):
        return rss.collect(self.vault, fetch=fetch, asset_fetch=self.asset_fetch, **kwargs)

    def state(self):
        return rss.read_state(self.vault)

    def entry(self):
        return next(iter(self.state()['articles'].values()))

    def test_missing_roster_does_not_read_network_or_create_rss_state(self):
        self.roster.unlink()
        fetch = Fetch()
        result = self.collect(fetch)
        self.assertEqual(result['status'], 'not_configured')
        self.assertEqual(fetch.calls, [])
        self.assertFalse((self.vault / rss.STATE_REL).exists())

    def test_roster_ignores_disabled_fences_comments_and_rejects_duplicates(self):
        self.roster.write_text('```\n- [x] https://bad.example.com/feed\n```\n'
                              '<!--\n- [x] https://other.example.com/feed\n-->\n'
                              '- [ ] https://disabled.example.com/feed\n- [x] ' + URL + '\n', encoding='utf-8')
        self.assertEqual(rss.roster(self.vault), [URL])
        self.roster.write_text('- [x] ' + URL + '\n- [x] ' + URL + '#section\n', encoding='utf-8')
        with self.assertRaisesRegex(rss.RSSError, 'duplicate_rss'):
            self.collect(Fetch())

    def test_long_or_punctuation_title_uses_bounded_label_without_losing_source_title(self):
        title = '!' * 500
        self.collect(Fetch(body(item(title=title))))
        entry = self.entry()
        self.assertTrue(Path(entry['note_relative']).name.startswith('publication-'))
        self.assertEqual(entry['versions'][0]['title'], title)

    def test_first_capture_keeps_older_items_then_uses_conditional_http_without_duplicates(self):
        fetch = Fetch(body(item()), None)
        first = self.collect(fetch)
        self.assertEqual(first['new_articles'], 1)
        entry = self.entry()
        self.assertTrue(entry['note_relative'].startswith('Investments/Sources/RSS/'))
        first_note = (self.vault / entry['note_relative']).read_bytes()
        self.clock.return_value = LATER
        second = self.collect(fetch)
        self.assertEqual(fetch.calls[1][1]['etag'], '"version-1"')
        self.assertEqual(second['new_articles'], 0)
        self.assertEqual(len(self.entry()['versions']), 1)
        self.assertEqual((self.vault / entry['note_relative']).read_bytes(), first_note)
        snapshot = rss.context(self.vault, LATER, since=FIRST)
        self.assertEqual(len(snapshot['items']), 1)
        self.assertTrue(snapshot['items'][0]['note_available'])
        self.assertEqual(snapshot['items'][0]['published_at'], '2026-06-01T12:00:00Z')
        self.assertIn('finite_feed_only', snapshot['feeds'][0]['history_limit'])

    def test_same_article_title_change_updates_stable_note_and_archives_exact_revisions(self):
        fetch = Fetch(body(item()), body(item(text='<p>Revised thesis.</p>', title='Changed title')))
        self.collect(fetch)
        before = self.entry()
        first_id = rss.context(self.vault, FIRST)['items'][0]['evidence_id']
        self.clock.return_value = LATER
        result = self.collect(fetch)
        self.assertEqual(result['new_articles'], 0)
        self.assertEqual(result['new_revisions'], 1)
        after = self.entry()
        self.assertEqual(after['note_relative'], before['note_relative'])
        self.assertEqual(len(after['versions']), 2)
        old = rss.context(self.vault, FIRST)['items'][0]
        latest = rss.context(self.vault, LATER, since=LATER)['items'][0]
        self.assertEqual(old['evidence_id'], first_id)
        self.assertIn('grew sales', old['content'])
        self.assertNotIn('Revised', old['content'])
        self.assertNotEqual(latest['evidence_id'], first_id)
        self.assertIn('Revised thesis', latest['content'])
        retained = rss.context(self.vault, LATER, since=LATER, retained_ids=[first_id])
        self.assertEqual(len(retained['items']), 2)
        self.assertTrue(all(value['note_available'] for value in retained['items']))
        self.assertIn('Revised thesis', (self.vault / after['note_relative']).read_text(encoding='utf-8'))

    def test_identical_200_response_does_not_add_revision_and_media_status_does_not_change_id(self):
        raw = body(item(text='<p>Thesis.</p><img src="https://example.com/figure.png" alt="Growth">'))
        fetch = Fetch(raw, raw)
        self.collect(fetch, max_downloads=0)
        identity = self.entry()['versions'][0]['revision_sha256']
        self.clock.return_value = LATER
        self.collect(fetch)
        self.assertEqual(len(self.entry()['versions']), 1)
        self.assertEqual(self.entry()['versions'][0]['revision_sha256'], identity)
        self.assertEqual(len(self.asset_fetch.calls), 1)

    def test_new_revision_recaptures_mutable_image_url_and_preserves_old_evidence_bytes(self):
        image = '<img src="https://example.com/chart.png">'
        fetch = Fetch(body(item(text='<p>First.</p>' + image)), body(item(text='<p>Updated.</p>' + image)))
        images = [media_fixtures.png(), media_fixtures.png(raster=b'\0\xff\0\0')]

        def changed_image(url, kind, budget):
            raw = images.pop(0)
            budget['requests'] += 1
            budget['bytes'] += len(raw)
            return {'data': raw, 'content_type': 'image/png', 'final_url': url}

        rss.collect(self.vault, fetch=fetch, asset_fetch=changed_image)
        old = rss.context(self.vault, FIRST)['items'][0]
        self.clock.return_value = LATER
        rss.collect(self.vault, fetch=fetch, asset_fetch=changed_image)
        new = rss.context(self.vault, LATER)['items'][0]
        self.assertNotEqual(old['assets'][0]['asset_key'], new['assets'][0]['asset_key'])
        self.assertNotEqual(old['assets'][0]['path'], new['assets'][0]['path'])
        self.assertNotEqual(old['assets'][0]['sha256'], new['assets'][0]['sha256'])
        self.assertTrue((self.vault / old['assets'][0]['path']).is_file())
        self.assertEqual(rss.context(self.vault, FIRST)['items'][0]['assets'], old['assets'])

    def test_images_and_pdfs_are_local_in_latest_note_and_cutoff_checked(self):
        text = '<p>Thesis.</p><img src="https://example.com/figure.png" alt="Growth"><a href="https://example.com/report.pdf">Report</a>'
        self.collect(Fetch(body(item(text=text))))
        note = (self.vault / self.entry()['note_relative']).read_text(encoding='utf-8')
        self.assertIn('![[Sources/Images/rss-', note)
        self.assertIn('[[Sources/PDFs/rss-', note)
        self.assertEqual(len(self.asset_fetch.calls), 2)
        snapshot = rss.context(self.vault, FIRST)['items'][0]
        self.assertTrue(all(asset['eligible'] for asset in snapshot['assets']))
        self.assertNotIn('![[', snapshot['content'])  # Immutable source keeps safe original links.
        self.assertEqual(rss.context(self.vault, '2026-09-08T11:59:59Z')['items'], [])

    def test_download_after_observation_does_not_enter_earlier_cutoff(self):
        self.collect(Fetch(body(item(text='<img src="https://example.com/figure.png">'))), max_downloads=0)
        self.clock.return_value = LATER
        self.collect(Fetch(None))
        self.assertFalse(rss.context(self.vault, FIRST)['items'][0]['assets'][0]['eligible'])
        self.assertNotIn('path', rss.context(self.vault, FIRST)['items'][0]['assets'][0])
        self.assertTrue(rss.context(self.vault, LATER)['items'][0]['assets'][0]['eligible'])
        note = (self.vault / self.entry()['note_relative']).read_text(encoding='utf-8')
        self.assertIn('updated: "2026-09-09"', note)
        self.assertEqual(list((self.vault / rss.STATE_REL / 'assets').iterdir()), [])

    def test_pending_parsed_response_survives_and_offline_publish_does_not_refetch(self):
        real = rss.apply_pending

        def interrupt(store):
            if store.data['pending']:
                raise RuntimeError('Interrupted after parsed data saved')
            return real(store)

        with patch.object(rss, 'apply_pending', side_effect=interrupt), self.assertRaises(RuntimeError):
            self.collect(Fetch(body(item())))
        state = self.state()
        self.assertIsNotNone(state['pending'])
        self.assertIsNone(next(iter(state['feeds'].values()))['etag'])
        args = rss.parser().parse_args(['publish', '--vault', str(self.vault)])
        with patch.object(rss.rss_source, 'fetch_feed', side_effect=AssertionError('Offline network')):
            result = rss.execute(args)
        self.assertEqual(result['requests'], 0)
        self.assertIsNone(self.state()['pending'])
        self.assertTrue(rss.context(self.vault, FIRST)['items'][0]['note_available'])

    def test_guid_rebound_blocks_without_validator_advance_or_duplicate_article(self):
        fetch = Fetch(body(item(guid='stable')), body(item('two', guid='stable')))
        self.collect(fetch)
        self.clock.return_value = LATER
        result = self.collect(fetch)
        self.assertIn('rss_guid_rebound_to_different_article', [row['reason'] for row in result['errors']])
        state = self.state()
        self.assertEqual(len(state['articles']), 1)
        self.assertIsNone(state['pending'])
        self.assertTrue(state['failed_responses'])
        self.assertEqual(next(iter(state['feeds'].values()))['etag'], '"version-1"')

    def test_unknown_note_occupant_blocks_without_overwrite(self):
        self.collect(Fetch(body(item())))
        path = self.vault / self.entry()['note_relative']
        path.write_text('My unrelated edit', encoding='utf-8')
        fetch = Fetch()
        with self.assertRaisesRegex(rss.RSSError, 'ownership_or_edit_conflict'):
            self.collect(fetch)
        self.assertEqual(fetch.calls, [])
        self.assertEqual(path.read_text(encoding='utf-8'), 'My unrelated edit')

    def test_missing_published_note_restores_from_304_without_fetching_article(self):
        self.collect(Fetch(body(item())))
        path = self.vault / self.entry()['note_relative']
        original = path.read_bytes()
        path.unlink()
        self.collect(Fetch(None))
        self.assertEqual(path.read_bytes(), original)

    def test_published_archive_conflict_is_explicit_to_consumer(self):
        self.collect(Fetch(body(item())))
        version = self.entry()['versions'][0]
        (self.vault / version['archive_relative']).write_text('Changed history', encoding='utf-8')
        snapshot = rss.context(self.vault, FIRST)
        self.assertEqual(snapshot['status'], 'incomplete')
        self.assertFalse(snapshot['items'][0]['note_available'])

    def test_finite_feed_loses_overlap_reports_gap_without_deleting_older_entry(self):
        fetch = Fetch(body(item()), body(item('two')))
        self.collect(fetch)
        self.clock.return_value = LATER
        self.collect(fetch)
        self.assertEqual(len(self.state()['articles']), 2)
        snapshot = rss.context(self.vault, LATER)
        self.assertIs(snapshot['feeds'][0]['observations'][-1]['overlap_with_previous'], False)

    def test_undated_source_is_preserved_without_fabricated_publication_date(self):
        self.collect(Fetch(body(item(date=False))))
        entry = rss.context(self.vault, FIRST)['items'][0]
        self.assertIsNone(entry['published_at'])
        self.assertEqual(entry['observed_at'], FIRST)

    def test_missing_existing_state_is_not_reinitialized(self):
        self.collect(Fetch(body(item())))
        (self.vault / rss.STATE_REL / 'state.json').unlink()
        with self.assertRaisesRegex(rss.RSSError, 'missing_rss_state'):
            rss.context(self.vault, FIRST)
        self.assertFalse((self.vault / rss.STATE_REL / 'state.json').exists())

    def test_symlink_output_is_rejected_without_network(self):
        self.collect(Fetch(body(item())))
        path = self.vault / self.entry()['note_relative']
        other = self.vault / 'private.md'
        other.write_text('Private content', encoding='utf-8')
        path.unlink()
        path.symlink_to(other)
        fetch = Fetch()
        with self.assertRaises(OSError):
            self.collect(fetch)
        self.assertEqual(fetch.calls, [])
        self.assertEqual(other.read_text(encoding='utf-8'), 'Private content')

    def test_disabled_feed_skipped_except_exact_retained_revision(self):
        self.collect(Fetch(body(item())))
        identity = rss.context(self.vault, FIRST)['items'][0]['evidence_id']
        self.roster.write_text('- [ ] ' + URL + '\n', encoding='utf-8')
        self.assertEqual(rss.context(self.vault, FIRST)['items'], [])
        self.assertEqual(len(rss.context(self.vault, FIRST, retained_ids=[identity])['items']), 1)

    def test_feed_failure_does_not_advance_conditional_validator(self):
        fetch = Fetch(body(item()), rss.rss_source.RSSSourceError('feed_http_503'))
        self.collect(fetch)
        self.clock.return_value = LATER
        result = self.collect(fetch)
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(next(iter(self.state()['feeds'].values()))['etag'], '"version-1"')
        self.assertEqual(rss.context(self.vault, LATER)['status'], 'incomplete')

    def test_state_and_lock_are_private_and_concurrent_writer_is_blocked(self):
        self.collect(Fetch(body(item())))
        self.assertEqual(os.stat(self.vault / rss.STATE_REL).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(self.vault / rss.STATE_REL / 'state.json').st_mode & 0o777, 0o600)
        with rss.Store(self.vault):
            with self.assertRaises(BlockingIOError):
                rss.Store(self.vault)

    def test_primary_reversion_has_distinct_predecessor_identity_but_unchanged_poll_does_not(self):
        first = body(item())
        fetch = Fetch(first, body(item(text='<p>Changed thesis.</p>')), first, first)
        self.collect(fetch)
        self.clock.return_value = LATER
        self.collect(fetch)
        self.clock.return_value = '2026-09-10T12:00:00Z'
        self.collect(fetch)
        versions = self.entry()['versions']
        self.assertEqual(len(versions), 3)
        self.assertEqual(versions[0]['semantic_sha256'], versions[2]['semantic_sha256'])
        self.assertNotEqual(versions[0]['revision_sha256'], versions[2]['revision_sha256'])
        self.assertEqual(versions[2]['previous_revision_sha256'], versions[1]['revision_sha256'])
        latest = rss.context(self.vault, self.clock.return_value, since=self.clock.return_value)['items']
        self.assertEqual(len(latest), 1)
        self.assertIn('grew sales', latest[0]['content'])
        self.collect(fetch)
        self.assertEqual(len(self.entry()['versions']), 3)

    def test_duplicate_canonical_article_across_feeds_deduplicates_and_stale_secondary_cannot_roll_back(self):
        secondary = 'https://example.com/category/feed'
        self.roster.write_text('- [x] ' + URL + '\n- [x] ' + secondary + '\n', encoding='utf-8')
        fetch = Fetch(body(item()), body(item()), body(item(text='<p>Newest thesis.</p>')), body(item()))
        self.collect(fetch)
        self.assertEqual(len(self.state()['articles']), 1)
        self.assertEqual(len(self.entry()['feed_ids']), 2)
        self.clock.return_value = LATER
        self.collect(fetch)
        self.assertEqual(len(self.entry()['versions']), 2)
        self.assertIn('Newest thesis', rss.context(self.vault, LATER)['items'][0]['content'])

    def test_enabled_secondary_can_take_over_inactive_primary_without_rewriting_old_attribution(self):
        secondary = 'https://example.com/category/feed'
        self.roster.write_text('- [x] ' + URL + '\n- [x] ' + secondary + '\n', encoding='utf-8')
        self.collect(Fetch(body(item()), body(item())))
        old = rss.context(self.vault, FIRST)['items'][0]
        stable_path = self.entry()['note_relative']
        self.roster.write_text('- [ ] ' + URL + '\n- [x] ' + secondary + '\n', encoding='utf-8')
        self.clock.return_value = LATER
        self.collect(Fetch(body(item(text='<p>Current source update.</p>'))))
        current = rss.context(self.vault, LATER)['items'][0]
        self.assertEqual(self.entry()['note_relative'], stable_path)
        self.assertEqual(current['feed_url'], secondary)
        self.assertIn('Current source update', current['content'])
        retained = rss.context(self.vault, LATER, retained_ids=[old['evidence_id']])['items']
        original = next(value for value in retained if value['evidence_id'] == old['evidence_id'])
        self.assertEqual(original['feed_url'], URL)
        self.assertEqual(original['feed_id'], old['feed_id'])
        self.assertIn('grew sales', original['content'])

    def test_one_rebound_entry_does_not_discard_unrelated_good_item_or_advance_validator(self):
        fetch = Fetch(body(item(guid='stable')), body(item('bad', guid='stable'), item('good')))
        self.collect(fetch)
        self.clock.return_value = LATER
        result = self.collect(fetch)
        self.assertEqual(result['new_articles'], 1)
        self.assertEqual(len(self.state()['articles']), 2)
        self.assertTrue(result['errors'])
        self.assertTrue(self.state()['failed_responses'])
        self.assertEqual(next(iter(self.state()['feeds'].values()))['etag'], '"version-1"')

    def test_conflicting_same_page_article_variants_are_both_quarantined_while_identical_rows_deduplicate(self):
        result = self.collect(Fetch(body(item(text='<p>Version A.</p>'), item(text='<p>Version B.</p>'),
                                              item('valid'), item('valid', guid='valid-alias'))))
        self.assertEqual(len(self.state()['articles']), 1)
        self.assertTrue(result['errors'])
        entry = self.entry()
        self.assertTrue(entry['canonical_url'].endswith('/valid'))
        feed = next(iter(self.state()['feeds'].values()))
        self.assertEqual(feed['guids']['valid'], feed['guids']['valid-alias'])

    def test_304_does_not_rewrite_index_or_provenance(self):
        fetch = Fetch(body(item()), None)
        self.collect(fetch)
        feed = next(iter(self.state()['feeds'].values()))
        path = self.vault / feed['index_relative']
        before = path.read_bytes()
        record = deepcopy(feed['provenance'])
        self.clock.return_value = LATER
        self.collect(fetch)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(next(iter(self.state()['feeds'].values()))['provenance'], record)
        entry = self.entry()
        self.assertEqual(entry['provenance']['generated_by']['skill'], 'investments:feed-collect')
        self.assertEqual(entry['versions'][0]['archive_receipt']['provenance']['generated_by']['plugin_version'], '1.14.0')

    def test_paused_publication_is_not_recreated_by_other_feed_run_or_offline_publish(self):
        self.collect(Fetch(body(item())))
        old = self.entry()
        old_path = self.vault / old['note_relative']
        old_path.unlink()
        self.roster.write_text('- [ ] ' + URL + '\n- [x] https://second.example.com/feed\n', encoding='utf-8')
        self.clock.return_value = LATER
        self.collect(Fetch(body(item('second'))))
        self.assertFalse(old_path.exists())
        rss.execute(rss.parser().parse_args(['publish', '--vault', str(self.vault)]))
        self.assertFalse(old_path.exists())

    def test_prepared_asset_resumes_offline_and_cleans_verified_cache(self):
        real = rss.guarded_publish

        def interrupt(store, vault, path, *args, **kwargs):
            if path.startswith('Sources/Images/'):
                raise RuntimeError('Crash before asset publication')
            return real(store, vault, path, *args, **kwargs)

        with patch.object(rss, 'guarded_publish', side_effect=interrupt), self.assertRaises(RuntimeError):
            self.collect(Fetch(body(item(text='<img src="https://example.com/chart.png">'))))
        receipt = next(iter(self.state()['assets'].values()))
        self.assertEqual(receipt['status'], 'prepared')
        self.assertTrue((self.vault / rss.STATE_REL / 'assets' / receipt['cache_name']).exists())
        with patch.object(rss.feed_media, 'fetch_asset', side_effect=AssertionError('Offline asset request')):
            result = rss.execute(rss.parser().parse_args(['publish', '--vault', str(self.vault)]))
        self.assertEqual(result['requests'], 0)
        self.assertEqual(next(iter(self.state()['assets'].values()))['status'], 'downloaded')
        self.assertEqual(list((self.vault / rss.STATE_REL / 'assets').iterdir()), [])

    def test_future_archive_publication_is_unavailable_to_earlier_cutoff(self):
        real = rss.publish

        def later_publication(*args, **kwargs):
            self.clock.return_value = LATER
            return real(*args, **kwargs)

        with patch.object(rss, 'publish', side_effect=later_publication):
            self.collect(Fetch(body(item())))
        self.assertFalse(rss.context(self.vault, FIRST)['items'][0]['note_available'])
        self.assertTrue(rss.context(self.vault, LATER)['items'][0]['note_available'])

    def test_prepared_missing_cache_requires_explicit_retry_then_uses_fresh_cache(self):
        real = rss.guarded_publish

        def interrupt(store, vault, path, *args, **kwargs):
            if path.startswith('Sources/Images/'):
                raise RuntimeError('Crash before publication')
            return real(store, vault, path, *args, **kwargs)

        with patch.object(rss, 'guarded_publish', side_effect=interrupt), self.assertRaises(RuntimeError):
            self.collect(Fetch(body(item(text='<img src="https://example.com/chart.png">'))))
        receipt = next(iter(self.state()['assets'].values()))
        cache_path = self.vault / rss.STATE_REL / 'assets' / receipt['cache_name']
        cache_path.unlink()
        self.collect(Fetch(None))
        self.assertEqual(len(self.asset_fetch.calls), 1)
        self.collect(Fetch(None), retry_attachments=True)
        self.assertEqual(len(self.asset_fetch.calls), 2)
        recovered = next(iter(self.state()['assets'].values()))
        self.assertEqual(recovered['status'], 'downloaded')
        self.assertIn(str(cache_path), recovered['recovery_paths'])

    def test_new_active_feed_and_stale_poll_are_explicit_limitations(self):
        self.collect(Fetch(body(item())))
        self.roster.write_text('- [x] ' + URL + '\n- [x] https://new.example.com/feed\n', encoding='utf-8')
        result = rss.context(self.vault, '2026-09-10T12:00:00Z')
        reasons = [value['reason'] for value in result['diagnostics']]
        self.assertIn('rss_feed_not_collected_at_cutoff', reasons)
        self.assertIn('rss_feed_check_older_than_26_hours', reasons)

    def test_state_changes_during_context_are_not_silently_mixed(self):
        self.collect(Fetch(body(item())))
        original = self.state()
        changed = deepcopy(original)
        changed['feeds'][next(iter(changed['feeds']))]['last_checked_at'] = LATER
        with patch.object(rss, 'read_state', side_effect=[original, changed]), self.assertRaisesRegex(
                rss.RSSError, 'rss_state_changed_during_context_read'):
            rss.context(self.vault, FIRST)


if __name__ == '__main__':
    unittest.main()
