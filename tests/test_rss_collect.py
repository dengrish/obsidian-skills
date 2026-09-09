#!/usr/bin/env python3
"""Offline forward tests for independent RSS persistence and research handoff."""
from copy import deepcopy
import json
import os
from pathlib import Path
import re
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

    def capture_legacy(self, raw, markdown, *, max_downloads=0):
        """Frozen v1 evidence contract, independent of the active renderer."""
        parsed = rss.rss_source.parse_feed(raw, URL)
        for article in parsed['items']:
            for key in ('rendering_version', 'render_base', 'linked_media'):
                article.pop(key, None)
            article['markdown'] = markdown
            article['diagnostics'] = ['active_or_unsupported_html_omitted']
            for attachment in article['attachments']:
                if attachment['kind'] == 'pdf':
                    attachment['markdown'] = '[PDF](' + attachment['url'] + ')'
        legacy = {'markdown': markdown, 'markdown_sha256': rss.common.digest(markdown.encode('utf-8')),
                  'rendering_version': 1, 'attachments': parsed['items'][0]['attachments'],
                  'occurrences': [], 'diagnostics': []}
        with patch.object(rss.rss_source, 'parse_feed', return_value=parsed), \
                patch.object(rss.rss_source, 'render_current', return_value=legacy):
            return self.collect(Fetch(raw), max_downloads=max_downloads)

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

    def test_default_collection_downloads_finite_backlog_beyond_previous_run_cap(self):
        source = ''.join('<img src="https://example.com/image-' + str(index) + '.png">' for index in range(41))
        observed_budgets = []

        def fetch_image(url, kind, budget):
            observed_budgets.append((budget['maximum'], budget['max_bytes']))
            return self.asset_fetch(url, kind, budget)

        result = rss.collect(self.vault, fetch=Fetch(body(item(text=source))), asset_fetch=fetch_image)
        self.assertEqual(result['assets']['downloaded'], 41)
        self.assertEqual(result['assets']['unavailable'], 0)
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(observed_budgets, [(None, None)] * 41)
        args = rss.parser().parse_args(['collect', '--vault', str(self.vault)])
        self.assertIsNone(args.max_downloads)
        self.assertIsNone(args.max_attachment_bytes)
        for invalid in (True, -1, 0.5, '10'):
            with self.assertRaises(rss.RSSError), patch.object(rss.rss_source, 'fetch_feed',
                    side_effect=AssertionError('Invalid budget cannot trigger feed request')):
                rss.collect(self.vault, max_downloads=invalid)
            with self.assertRaises(rss.RSSError):
                rss.collect_attachments(self.vault, max_bytes=invalid)
        rss.validate_attachment_budgets(1000, 2 * 1024 ** 3)

    def test_attachment_only_command_fills_saved_urls_without_feed_read_or_archive_changes(self):
        source = '<img src="https://example.com/one.png"><a href="https://example.com/report.pdf">Read report</a>'
        self.collect(Fetch(body(item(text=source))), max_downloads=0)
        old = self.state()
        version = deepcopy(self.entry()['versions'][0])
        archive = (self.vault / version['archive_relative']).read_bytes()
        self.clock.return_value = LATER
        args = rss.parser().parse_args(['attachments', '--vault', str(self.vault)])
        with patch.object(rss.rss_source, 'fetch_feed', side_effect=AssertionError('No feed request')), \
                patch.object(rss, 'apply_pending', side_effect=AssertionError('No feed response application')), \
                patch.object(rss.feed_media, 'fetch_asset', side_effect=self.asset_fetch):
            result = rss.execute(args)
            repeated = rss.execute(args)
        self.assertEqual(result['feed_requests'], 0)
        self.assertEqual(result['requests'], 2)
        self.assertEqual(result['assets']['downloaded'], 2)
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(repeated['requests'], 0)
        self.assertEqual(repeated['published_notes'], 0)
        self.assertEqual(repeated['assets']['reused'], 2)
        self.assertEqual(self.entry()['versions'], [version])
        self.assertEqual(self.state()['feeds'], old['feeds'])
        self.assertEqual((self.vault / version['archive_relative']).read_bytes(), archive)
        note = (self.vault / self.entry()['note_relative']).read_text(encoding='utf-8')
        self.assertIn('![[Sources/Images/', note)
        self.assertIn('[Read report](../../../../Sources/PDFs/', note)
        self.assertEqual(rss.context(self.vault, FIRST)['status'], 'incomplete')
        self.assertEqual(rss.context(self.vault, LATER)['status'], 'ready')

    def test_explicit_attachment_budgets_keep_deferred_sources_incomplete(self):
        source = '<img src="https://example.com/one.png"><img src="https://example.com/two.png">'
        first = self.collect(Fetch(body(item(text=source))), max_downloads=1)
        self.assertEqual(first['assets']['downloaded'], 1)
        self.assertEqual(first['assets']['deferred'], 1)
        snapshot = rss.context(self.vault, FIRST)
        self.assertEqual(snapshot['status'], 'incomplete')
        self.assertTrue(snapshot['items'][0]['note_available'])
        self.assertEqual(snapshot['diagnostics'][-1]['images'], 1)
        with patch.object(rss.feed_media, 'fetch_asset', side_effect=AssertionError('Zero byte budget')):
            result = rss.collect_attachments(self.vault, max_bytes=0)
        self.assertEqual(result['requests'], 0)
        self.assertEqual(result['assets']['deferred'], 1)
        self.assertEqual(result['assets']['failed'], 0)
        self.assertEqual(result['status'], 'incomplete')
        filled = rss.collect_attachments(self.vault, asset_fetch=self.asset_fetch)
        self.assertEqual(filled['assets']['downloaded'], 1)
        self.assertEqual(filled['status'], 'ready')

    def test_attachment_failures_require_explicit_retry_without_automatic_repeat_requests(self):
        source = '<img src="https://example.com/failure.png"><img src="https://example.com/good.png">'
        self.collect(Fetch(body(item(text=source))), max_downloads=0)
        calls = []

        def fails_once(url, kind, budget):
            calls.append(url)
            if url.endswith('/failure.png'):
                budget['requests'] += 1
                raise rss.feed_media.MediaError('fixture_download_failed')
            return self.asset_fetch(url, kind, budget)

        first = rss.collect_attachments(self.vault, asset_fetch=fails_once)
        self.assertEqual(first['assets']['failed'], 1)
        self.assertEqual(first['assets']['deferred'], 0)
        self.assertEqual(first['assets']['downloaded'], 1)
        self.assertEqual(first['requests'], 2)
        with patch.object(rss.feed_media, 'fetch_asset', side_effect=AssertionError('No automatic failed retry')):
            repeated = rss.collect_attachments(self.vault)
        self.assertEqual(repeated['requests'], 0)
        self.assertEqual(repeated['assets']['failed'], 1)
        retried = rss.collect_attachments(self.vault, asset_fetch=self.asset_fetch, retry_attachments=True)
        self.assertEqual(retried['requests'], 1)
        self.assertEqual(retried['assets']['failed'], 0)
        self.assertEqual(retried['status'], 'ready')

    def test_missing_downloaded_image_is_incomplete_and_explicit_retry_restores_it(self):
        self.collect(Fetch(body(item(text='<img src="https://example.com/one.png">'))))
        receipt = next(iter(self.state()['assets'].values()))
        path = self.vault / receipt['path']
        path.unlink()
        self.assertEqual(rss.context(self.vault, FIRST)['status'], 'incomplete')
        with patch.object(rss.feed_media, 'fetch_asset', side_effect=AssertionError('No implicit repeat download')):
            result = rss.collect_attachments(self.vault)
        self.assertEqual(result['assets']['failed'], 1)
        self.assertEqual(result['requests'], 0)
        self.assertFalse(path.exists())
        result = rss.collect_attachments(self.vault, asset_fetch=self.asset_fetch, retry_attachments=True)
        self.assertTrue(path.is_file())
        self.assertEqual(result['status'], 'ready')

    def test_attachment_only_leaves_pending_feed_response_and_uses_prior_saved_urls(self):
        self.collect(Fetch(body(item(text='<img src="https://example.com/old.png">'))), max_downloads=0)
        original_apply = rss.apply_pending

        def interrupt(store):
            if store.data['pending']:
                raise RuntimeError('Saved response must remain pending')
            return original_apply(store)

        with patch.object(rss, 'apply_pending', side_effect=interrupt), self.assertRaises(RuntimeError):
            self.collect(Fetch(body(item(text='<img src="https://example.com/new.png">'))), max_downloads=0)
        pending = deepcopy(self.state()['pending'])
        version = deepcopy(self.entry()['versions'])
        result = rss.collect_attachments(self.vault, asset_fetch=self.asset_fetch)
        self.assertEqual(self.asset_fetch.calls, ['https://example.com/old.png'])
        self.assertEqual(self.state()['pending'], pending)
        self.assertEqual(self.entry()['versions'], version)
        self.assertTrue(result['pending_feed_response_unchanged'])
        self.assertEqual(result['status'], 'incomplete')

    def test_attachment_only_does_not_activate_paused_sources(self):
        self.collect(Fetch(body(item(text='<img src="https://example.com/one.png">'))), max_downloads=0)
        note = self.vault / self.entry()['note_relative']
        note.unlink()
        self.roster.write_text('- [ ] ' + URL + '\n', encoding='utf-8')
        before = (self.vault / rss.STATE_REL / 'state.json').read_bytes()
        with patch.object(rss.feed_media, 'fetch_asset', side_effect=AssertionError('Paused source')):
            result = rss.collect_attachments(self.vault)
        self.assertEqual(result['status'], 'not_configured')
        self.assertFalse(note.exists())
        self.assertEqual((self.vault / rss.STATE_REL / 'state.json').read_bytes(), before)

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
        self.assertIn('[Report](../../../../Sources/PDFs/rss-', note)
        self.assertEqual(len(self.asset_fetch.calls), 2)
        snapshot = rss.context(self.vault, FIRST)['items'][0]
        self.assertTrue(all(asset['eligible'] for asset in snapshot['assets']))
        self.assertNotIn('![[', snapshot['content'])  # Immutable source keeps safe original links.
        self.assertEqual(rss.context(self.vault, '2026-09-08T11:59:59Z')['items'], [])

    def test_structural_local_links_preserve_pdf_labels_and_positions_without_replacing_source_code(self):
        source = ('<p>Before.</p><figure><a href="https://example.com/full.png"><div><picture>'
                  '<img src="https://example.com/figure.png"></picture></div></a>'
                  '<figcaption>Chart caption.</figcaption></figure>'
                  '<p>Read <a href="https://example.com/report.pdf"><strong>Source report</strong></a> here.</p>'
                  '<pre>[PDF](https://example.com/report.pdf)</pre>'
                  '<p>Again <a href="https://example.com/report.pdf">Download</a>. After.</p>'
                  '<iframe src="https://www.youtube.com/embed/example"></iframe>')
        self.collect(Fetch(body(item(text=source))))
        note = (self.vault / self.entry()['note_relative']).read_text(encoding='utf-8')
        self.assertEqual(len(self.asset_fetch.calls), 2)
        self.assertNotIn('[![[', note)
        self.assertRegex(note, r'!\[\[Sources/Images/[^\n]+\]\]\s*\n\n\[Image source\][^\n]+\n\nChart caption\.')
        self.assertIn('[**Source report**](../../../../Sources/PDFs/rss-', note)
        self.assertIn('[Download](../../../../Sources/PDFs/rss-', note)
        self.assertIn('    [PDF](https://example.com/report.pdf)', note)
        self.assertIn('https://www.youtube.com/embed/example', note)
        targets = re.findall(r'\]\((\.\./[^)]+\.pdf)\)', note)
        self.assertEqual(len(targets), 2)
        self.assertEqual(targets[0], targets[1])
        self.assertTrue((self.vault / self.entry()['note_relative']).parent.joinpath(targets[0]).resolve().is_file())

    def test_offline_render_repair_preserves_legacy_revision_archive_cutoff_and_receipts(self):
        source = ('<figure><a href="https://example.com/full.png"><div><picture>'
                  '<img src="https://example.com/figure.png"></picture></div></a>'
                  '<figcaption>Caption.</figcaption></figure>'
                  '<p><a href="https://example.com/report.pdf">Download report</a></p>'
                  '<iframe src="https://www.youtube.com/embed/example"></iframe>')
        legacy = ('[[Image: source image](https://example.com/figure.png)](https://example.com/full.png)Caption.\n\n'
                  '[Download report](https://example.com/report.pdf)')
        raw = body(item(text=source))
        self.capture_legacy(raw, legacy, max_downloads=2)
        entry = self.entry()
        version = deepcopy(entry['versions'][0])
        archive_path = self.vault / version['archive_relative']
        archive_bytes = archive_path.read_bytes()
        before = rss.context(self.vault, FIRST)['items'][0]
        asset_bytes = {row['path']: (self.vault / row['path']).read_bytes()
                       for row in self.state()['assets'].values() if row['status'] == 'downloaded'}
        self.clock.return_value = LATER
        with patch.object(rss.rss_source, 'fetch_feed', side_effect=AssertionError('No feed fetch')), \
                patch.object(rss.feed_media, 'fetch_asset', side_effect=AssertionError('No media fetch')):
            result = rss.execute(rss.parser().parse_args(['publish', '--vault', str(self.vault)]))
            repeat = rss.execute(rss.parser().parse_args(['publish', '--vault', str(self.vault)]))
        self.assertEqual(result['requests'], 0)
        self.assertEqual(result['published_notes'], 1)
        self.assertEqual(repeat['published_notes'], 0)
        self.assertEqual(self.entry()['versions'], [version])
        self.assertEqual(archive_path.read_bytes(), archive_bytes)
        self.assertEqual(asset_bytes, {path: (self.vault / path).read_bytes() for path in asset_bytes})
        after = rss.context(self.vault, FIRST)['items'][0]
        self.assertEqual(after, before)
        self.assertEqual(after['content'], legacy)
        self.assertEqual(after['content_basis'], 'immutable_revision_archive')
        self.assertFalse(after['current_note_is_historical_evidence'])
        self.assertEqual(after['evidence_rendering_version'], 1)
        self.assertEqual(rss.context(self.vault, '2026-09-08T11:59:59Z')['items'], [])
        current = (self.vault / entry['note_relative']).read_text(encoding='utf-8')
        self.assertNotIn('[[Image:', current)
        self.assertIn('[Download report](../../../../Sources/PDFs/', current)
        self.assertIn('https://www.youtube.com/embed/example', current)
        self.assertNotIn('youtube', archive_bytes.decode('utf-8'))
        self.assertNotIn('evidence_revision:', current)
        self.assertNotIn('rendering_version:', current)
        self.assertEqual(self.collect(Fetch(raw), max_downloads=0)['new_revisions'], 0)
        self.assertEqual(self.entry()['versions'], [version])

    def test_legacy_renderer_upgrade_keeps_real_source_changes_and_reversion_distinct(self):
        first = body(item(text='<p>First source.</p>'))
        self.capture_legacy(first, 'First source.')
        original = self.entry()['versions'][0]['revision_sha256']
        self.clock.return_value = LATER
        self.assertEqual(self.collect(Fetch(first))['new_revisions'], 0)
        self.assertEqual(self.collect(Fetch(body(item(text='<p>Changed source.</p>'))))['new_revisions'], 1)
        self.assertEqual(self.collect(Fetch(first))['new_revisions'], 1)
        versions = self.entry()['versions']
        self.assertEqual(len({version['revision_sha256'] for version in versions}), 3)
        self.assertEqual(versions[0]['revision_sha256'], original)
        self.assertEqual(versions[-1]['rendering_version'], 2)
        self.assertEqual(versions[-1]['previous_revision_sha256'], versions[-2]['revision_sha256'])

    def test_legacy_relative_base_is_not_guessed_during_offline_repair(self):
        raw = body(item(text='<img src="figure.png"><p><a href="relative-page">Source</a></p>'))
        legacy = '[Image: source image](https://example.com/figure.png)\n\n[Source](https://example.com/relative-page)'
        self.capture_legacy(raw, legacy, max_downloads=1)
        receipt = next(iter(self.state()['assets'].values()))
        with rss.Store(self.vault) as store:
            entry = next(iter(store.data['articles'].values()))
            note_path = self.vault / entry['note_relative']
            previous_publication = note_path.read_bytes().replace(
                receipt['markdown'].encode('utf-8'), ('![[' + receipt['path'] + ']]').encode('utf-8'))
            rss.guarded_publish(store, self.vault, entry['note_relative'], previous_publication, entry)
        before = deepcopy(self.entry()['versions'])
        result = rss.execute(rss.parser().parse_args(['publish', '--vault', str(self.vault)]))
        self.assertEqual(note_path.read_bytes(), previous_publication)
        self.assertIn(('![[' + receipt['path'] + ']]').encode('utf-8'), note_path.read_bytes())
        self.assertEqual(result['published_notes'], 0)
        self.assertEqual(result['rendering_limitations'][0]['reason'], 'legacy_render_base_unavailable')
        self.assertEqual(rss.context(self.vault, FIRST)['items'][0]['current_note_rendering_limitation'],
                         'legacy_render_base_unavailable')
        self.assertEqual(self.entry()['versions'], before)

    def test_duplicate_raw_article_with_different_known_bases_is_ambiguous(self):
        first = item(text='<a href="relative-page">Source link</a>').replace(
            '<content:encoded>', '<content:encoded xml:base="https://example.com/first/">')
        second = first.replace('https://example.com/first/', 'https://example.com/second/')
        result = self.collect(Fetch(body(first, second)))
        self.assertEqual(result['new_revisions'], 0)
        self.assertEqual(self.state()['articles'], {})
        self.assertEqual(result['errors'][0]['reason'], 'ambiguous_duplicate_rss_article')

    def test_local_pdf_page_fragment_is_preserved(self):
        self.collect(Fetch(body(item(text='<a href="https://example.com/report.pdf#page=3)">Page three</a>'))))
        note = (self.vault / self.entry()['note_relative']).read_text(encoding='utf-8')
        self.assertRegex(note, r'\[Page three\]\(\.\./\.\./\.\./\.\./Sources/PDFs/rss-[0-9a-f]+\.pdf#page=3%29\)')
        self.assertNotIn('.pdf#page=3))', note)

    def test_invalid_generated_attachment_span_cannot_overwrite_published_view(self):
        self.collect(Fetch(body(item(text='<p>Original.</p>'))))
        note = self.vault / self.entry()['note_relative']
        before = note.read_bytes()
        rendered = rss.rss_source.render_current(self.entry()['versions'][0])
        rendered['occurrences'] = [{'start': 0, 'end': 1, 'kind': 'pdf', 'url': 'https://example.com/file.pdf',
                                    'label': 'Injected', 'markdown': 'Different generated token'}]
        with patch.object(rss.rss_source, 'render_current', return_value=rendered), \
                self.assertRaisesRegex(rss.RSSError, 'invalid_rss_attachment_occurrence'):
            rss.execute(rss.parser().parse_args(['publish', '--vault', str(self.vault)]))
        self.assertEqual(note.read_bytes(), before)

    def test_unknown_renderer_or_changed_render_base_is_not_adopted(self):
        self.collect(Fetch(body(item())))
        for value in (True, 9):
            state = deepcopy(self.state())
            next(iter(state['articles'].values()))['versions'][0]['rendering_version'] = value
            with self.assertRaisesRegex(rss.RSSError, 'unsupported_rss_evidence_rendering'):
                rss.validate(state)
        state = deepcopy(self.state())
        next(iter(state['articles'].values()))['versions'][0]['render_base'] = 'https://changed.example.com/'
        with self.assertRaisesRegex(rss.RSSError, 'invalid_rss_revision'):
            rss.validate(state)

    def test_newly_observed_video_enclosure_enriches_legacy_evidence_without_backfill_or_download(self):
        original_item = item(text='<p>Saved source.</p>')
        enclosed = original_item.replace('</item>', '<enclosure url="https://example.com/talk.mp4" type="video/mp4"/></item>')
        raw = body(enclosed)
        self.capture_legacy(raw, 'Saved source.')
        old = deepcopy(self.entry()['versions'][0])
        archive = (self.vault / old['archive_relative']).read_bytes()
        self.clock.return_value = LATER
        with patch.object(rss.feed_media, 'fetch_asset', side_effect=AssertionError('No video download')):
            result = self.collect(Fetch(raw))
        self.assertEqual(result['new_revisions'], 1)
        self.assertEqual(result['assets']['requests'], 0)
        self.assertEqual(self.asset_fetch.calls, [])
        self.assertEqual(self.entry()['versions'][0], old)
        self.assertEqual((self.vault / old['archive_relative']).read_bytes(), archive)
        previous = rss.context(self.vault, FIRST)['items'][0]
        latest = rss.context(self.vault, LATER, since=LATER)['items'][0]
        self.assertEqual(previous['linked_media'], [])
        self.assertNotIn('talk.mp4', previous['content'])
        self.assertEqual(latest['linked_media'], [{'url': 'https://example.com/talk.mp4',
                         'media_type': 'video', 'mime_type': 'video/mp4'}])
        self.assertEqual(latest['assets'], [])
        self.assertIn('[Video enclosure](https://example.com/talk.mp4)', latest['content'])
        self.assertEqual(self.collect(Fetch(raw))['new_revisions'], 0)
        self.assertEqual(self.collect(Fetch(body(enclosed.replace('talk.mp4', 'next.mp4'))))['new_revisions'], 1)
        state = deepcopy(self.state())
        next(iter(state['articles'].values()))['versions'][-1]['linked_media'][0]['url'] = 'https://example.com/tampered.mp4'
        with self.assertRaisesRegex(rss.RSSError, 'invalid_rss_revision'):
            rss.validate(state)

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
