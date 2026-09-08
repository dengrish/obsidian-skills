#!/usr/bin/env python3
"""Cross-workflow tests: X response -> local attachments -> notes -> removal."""
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/feed-collect/scripts'))
import feed_collect as feed

RECORD = {'skill': 'investments:feed-collect', 'plugin_version': '1.8.0',
          'source_commit': None, 'source_url': None, 'source_status': 'uncommitted',
          'runtime_sha256': '0' * 64}


def photo_bytes():
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b'\0\0\0\0')) + chunk(b'IEND', b''))


def pdf_bytes():
    data, offsets = b'%PDF-1.4\n', [0]
    for identity, value in enumerate((b'<< /Type /Catalog /Pages 2 0 R >>',
            b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
            b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] >>'), 1):
        offsets.append(len(data))
        data += str(identity).encode() + b' 0 obj\n' + value + b'\nendobj\n'
    xref = len(data)
    data += b'xref\n0 4\n0000000000 65535 f \n'
    data += b''.join(('%010d 00000 n \n' % offset).encode() for offset in offsets[1:])
    return data + b'trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n' + str(xref).encode() + b'\n%%EOF\n'


class AttachmentWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='obsidian-feed-attachment-flow-')
        self.addCleanup(self.tmp.cleanup)
        self.vault = Path(self.tmp.name).resolve()
        (self.vault / 'Investments').mkdir()
        (self.vault / 'Investments/x-accounts.md').write_text('- [x] @actual\n', encoding='utf-8')
        self.addCleanup(patch.stopall)
        patch.object(feed, 'provenance', return_value=RECORD).start()
        patch.dict(os.environ, {'X_BEARER_TOKEN': 'offline-fixture-only'}).start()
        self.paid = []
        self.downloads = []

    def args(self, command='collect', **values):
        args = feed.parser().parse_args([command, '--vault', str(self.vault),
                                        '--until', '2026-09-07T12:00:00Z'])
        for key, value in values.items():
            setattr(args, key, value)
        return args

    def response(self):
        return {'data': [{'id': '105', 'author_id': '12', 'created_at': '2026-09-07T11:00:00Z',
                          'text': 'Exact original source text.', 'attachments': {'media_keys': ['3_105']},
                          'entities': {'urls': [{'expanded_url': 'https://files.example/report.pdf'}]}}],
                'includes': {'media': [
                    {'media_key': '3_105', 'type': 'photo', 'url': 'https://pbs.twimg.com/media/own.png'},
                    {'media_key': '3_999', 'type': 'photo', 'url': 'https://pbs.twimg.com/media/unrelated.png'}]},
                'meta': {'result_count': 1}}

    def api(self, path, query, token):
        self.paid.append((path, query))
        if '/by/username/' in path:
            return {'data': {'id': '12', 'username': 'actual'}}
        return self.response()

    def download(self, url, kind, budget):
        self.downloads.append(url)
        raw = photo_bytes() if kind == 'image' else pdf_bytes()
        budget['requests'] += 1
        budget['bytes'] += len(raw)
        return {'data': raw, 'content_type': 'image/png' if kind == 'image' else 'application/pdf', 'final_url': url}

    @property
    def note(self):
        return self.vault / 'Investments/Sources/X/actual.md'

    def state(self):
        return json.loads((self.vault / 'Investments/Sources/.feed-collect/state.json').read_text(encoding='utf-8'))

    def acquire(self, **values):
        with patch.object(feed.feed_media, 'fetch_asset', side_effect=self.download):
            return feed.collect(self.args(**values), fetch=self.api, record=RECORD)

    def test_collection_embeds_original_photo_and_links_pdf_without_extra_x_reads(self):
        result = self.acquire()
        self.assertEqual(len(self.paid), 2)
        self.assertEqual(set(self.downloads), {'https://pbs.twimg.com/media/own.png', 'https://files.example/report.pdf'})
        self.assertEqual(result['attachments']['downloaded'], 2)
        state = self.state()
        note = self.note.read_text(encoding='utf-8')
        for receipt in state['assets'].values():
            path = self.vault / receipt['path']
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), receipt['sha256'])
            prefix = '!' if receipt['kind'] == 'image' else ''
            self.assertIn(prefix + '[[' + receipt['path'] + ']]', note)
            self.assertIn('"retrieved_at": "' + receipt['retrieved_at'] + '"', note)
            self.assertIn('"sha256": "' + receipt['sha256'] + '"', note)
            if receipt['kind'] == 'pdf':
                self.assertNotIn('![[' + receipt['path'] + ']]', note)
        self.assertIn('"local_attachments":', note)
        self.assertNotIn('"cache_name":', note)
        self.assertNotIn('"recovery_path":', note)
        self.assertEqual(state['accounts']['actual']['posts']['105']['text'], 'Exact original source text.')
        original = self.note.read_bytes()
        with patch.object(feed, 'request_json', side_effect=AssertionError('Unexpected X reread')):
            with patch.object(feed.feed_media, 'fetch_asset', side_effect=AssertionError('Unexpected download')):
                again = feed.execute(self.args('attachments'))
        self.assertEqual(again['attachments']['reused'], 2)
        self.assertEqual(self.note.read_bytes(), original)

    def test_existing_urls_can_be_downloaded_later_without_x_credentials(self):
        first = self.acquire(max_downloads=0)
        self.assertEqual(first['attachments']['deferred'], 2)
        self.assertEqual(self.downloads, [])
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(feed, 'request_json', side_effect=AssertionError('Unexpected X reread')):
                with patch.object(feed.feed_media, 'fetch_asset', side_effect=self.download):
                    second = feed.execute(self.args('attachments'))
        self.assertEqual(second['attachments']['downloaded'], 2)
        self.assertEqual(len(self.paid), 2)

    def test_legacy_missing_media_url_does_not_use_a_webpage_preview(self):
        response = self.response()
        response.pop('includes')
        response['data'][0]['entities'] = {'urls': [{'expanded_url': 'https://example.com/article',
                                                   'images': [{'url': 'https://example.com/card.png'}]}]}
        response['data'][0]['media_metadata'] = {'3_105': {'media_key': '3_105'}}
        with patch.object(self, 'response', return_value=response):
            result = self.acquire()
        self.assertEqual(self.downloads, [])
        self.assertEqual(result['attachments']['metadata_unavailable'], 1)
        self.assertNotIn('![[Sources/Images/', self.note.read_text(encoding='utf-8'))

    def test_offline_publish_never_downloads_a_missing_asset(self):
        self.acquire()
        image = next(receipt for receipt in self.state()['assets'].values() if receipt['kind'] == 'image')
        (self.vault / image['path']).unlink()
        with patch.object(feed.feed_media, 'fetch_asset', side_effect=AssertionError('Offline publication fetched bytes')):
            result = feed.execute(self.args('publish'))
        self.assertEqual(result['requests'], 0)
        self.assertEqual(result['attachments']['failed'], 1)
        self.assertNotIn('![[' + image['path'] + ']]', self.note.read_text(encoding='utf-8'))

    def test_positive_removal_retires_media_after_removing_note_embeds(self):
        self.acquire()
        assets = [self.vault / item['path'] for item in self.state()['assets'].values()]
        missing = {'errors': [{'resource_id': '105', 'type': 'https://api.x.com/2/problems/resource-not-found'}]}
        with patch.object(feed, 'request_json', return_value=missing):
            with patch.object(feed.feed_media, 'fetch_asset', side_effect=AssertionError('Deletion downloaded media')):
                result = feed.execute(self.args('reconcile', ids='105', allow_paid_reread=True, account='actual'))
        self.assertEqual(result['attachment_cleanup']['removed'], 2)
        self.assertTrue(all(not path.exists() for path in assets))
        self.assertNotIn('Exact original source text.', self.note.read_text(encoding='utf-8'))
        self.assertNotIn('![[Sources/Images/', self.note.read_text(encoding='utf-8'))

    def test_foreign_note_reference_blocks_owned_asset_removal(self):
        self.acquire()
        image = next(receipt for receipt in self.state()['assets'].values() if receipt['kind'] == 'image')
        (self.vault / 'Manual.md').write_text('![[' + image['path'] + ']]\n', encoding='utf-8')
        missing = {'errors': [{'resource_id': '105', 'type': 'https://api.x.com/2/problems/resource-not-found'}]}
        with patch.object(feed, 'request_json', return_value=missing):
            result = feed.execute(self.args('reconcile', ids='105', allow_paid_reread=True, account='actual'))
        self.assertEqual(result['attachment_cleanup']['blocked'], 1)
        self.assertTrue((self.vault / image['path']).exists())


if __name__ == '__main__':
    unittest.main()
