#!/usr/bin/env python3
"""Independent offline coverage of attachment acquisition and ownership."""
from copy import deepcopy
import base64
import io
import json
import os
from pathlib import Path
import socket
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/feed-collect/scripts'))
import feed_media as media


def png(*, raster=b'\0\x80\x80\x80', compressed=None, header=(1, 1, 8, 2, 0, 0, 0)):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', *header))
            + chunk(b'IDAT', zlib.compress(raster) if compressed is None else compressed)
            + chunk(b'IEND', b''))


def pdf():
    body = b'%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n'
    return body + b'xref\n0 2\n0000000000 65535 f\n0000000009 00000 n\ntrailer\n<< /Size 2 /Root 1 0 R >>\nstartxref\n' + str(len(body)).encode() + b'\n%%EOF\n'


def post(identity='123', media_key='3_456', url='https://pbs.twimg.com/media/a.png'):
    return {'id': identity, 'status': 'available', 'attachments': {'media_keys': [media_key]},
            'media': [{'media_key': media_key, 'type': 'photo', 'url': url, 'alt_text': 'Original image description.'}]}


class Fetch:
    def __init__(self):
        self.calls = []

    def __call__(self, url, kind, budget):
        self.calls.append(url)
        data = png() if kind == 'image' else pdf()
        budget['requests'] += 1
        budget['bytes'] += len(data)
        return {'data': data, 'content_type': 'image/png' if kind == 'image' else 'application/pdf', 'final_url': url}


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='feed-media-test-')
        self.addCleanup(self.temp.cleanup)
        self.vault = Path(self.temp.name).resolve()
        self.posts = [post()]
        self.receipts = {}
        self.fetch = Fetch()
        self.saved = []

    def save(self):
        self.saved.append(deepcopy(self.receipts))

    def collect(self, **values):
        return media.collect_assets(self.vault, self.posts, self.receipts, self.save, fetch=self.fetch, **values)

    def asset(self):
        return self.vault / next(iter(self.receipts.values()))['path']

    def test_photo_pdf_once_flat_and_local_links(self):
        self.posts[0]['entities'] = {'urls': [{'expanded_url': 'https://example.com/report.PDF?edition=1'}]}
        first = self.collect()
        self.assertEqual(first['downloaded'], 2)
        self.assertEqual(self.collect()['reused'], 2)
        self.assertEqual(len(self.fetch.calls), 2)
        lines = '\n'.join(media.render_assets(self.posts[0], self.receipts))
        self.assertIn('![[Sources/Images/x-123-', lines)
        self.assertIn('[[Sources/PDFs/x-123-', lines)
        self.assertFalse(list((self.vault / 'Sources/Images').glob('.*')))
        self.assertFalse(list((self.vault / media.CACHE_REL).iterdir()))
        self.assertEqual(os.stat(self.asset()).st_mode & 0o777, 0o600)

    def test_only_own_photos_never_card_or_quote_images(self):
        self.posts[0]['media'].append({'media_key': '3_foreign', 'type': 'photo', 'url': 'https://example.com/foreign.png'})
        self.posts[0]['entities'] = {'urls': [{'expanded_url': 'https://example.com/article',
                                             'images': [{'url': 'https://example.com/card.png'}]}]}
        self.collect()
        self.assertEqual(self.fetch.calls, ['https://pbs.twimg.com/media/a.png'])

    def test_existing_metadata_gap_does_not_fetch(self):
        self.posts[0].pop('media')
        self.posts[0]['media_metadata'] = [{'media_key': '3_456'}]
        result = self.collect()
        self.assertEqual(result['metadata_unavailable'], 1)
        self.assertEqual(self.fetch.calls, [])
        self.assertIn('no downloadable photo', '\n'.join(media.render_assets(self.posts[0], self.receipts)))
        self.posts[0]['media'] = post()['media']
        self.assertEqual(self.collect()['downloaded'], 1)

    def test_video_is_not_downloaded_as_preview_image(self):
        self.posts[0]['media'][0].update(type='video', preview_image_url='https://example.com/preview.png')
        self.assertEqual(self.collect()['unsupported'], 1)
        self.assertEqual(self.fetch.calls, [])

    def test_long_form_pdf_and_opaque_unwound_link(self):
        self.posts[0]['long_post_entities'] = {'urls': [{'unwound_url': 'https://example.com/download?id=1',
                                                       'expanded_url': 'https://example.com/report.pdf'}]}
        self.assertEqual(self.collect()['downloaded'], 2)

    def test_global_duplicate_asset_uses_one_download(self):
        self.posts.append(post(identity='124'))
        self.assertEqual(self.collect()['downloaded'], 1)
        self.assertEqual(self.posts[0]['assets'], self.posts[1]['assets'])
        self.assertEqual(len(self.fetch.calls), 1)

    def test_pdf_url_captured_per_post_and_deduplicated_within_post(self):
        url = {'expanded_url': 'https://example.com/current-report.pdf'}
        self.posts = [{'id': '123', 'entities': {'urls': [url]}, 'long_post_entities': {'urls': [url]}},
                      {'id': '124', 'entities': {'urls': [url]}}]
        calls = []
        def fetch(url, kind, budget):
            calls.append(url)
            raw = pdf().replace(b'/Catalog', b'/Catalog /Version /One' if len(calls) == 1 else b'/Catalog /Version /Two')
            # Rebuild the xref byte offset after changing object length.
            offset = raw.index(b'xref\n')
            raw = raw[:raw.index(b'startxref\n')] + b'startxref\n' + str(offset).encode() + b'\n%%EOF\n'
            budget['requests'] += 1
            budget['bytes'] += len(raw)
            return {'data': raw, 'content_type': 'application/pdf'}
        self.fetch = fetch
        self.assertEqual(self.collect()['downloaded'], 2)
        self.assertNotEqual(self.posts[0]['assets'], self.posts[1]['assets'])
        records = list(self.receipts.values())
        self.assertNotEqual(records[0]['sha256'], records[1]['sha256'])
        self.assertTrue(all(record['retrieved_at'].endswith('Z') for record in records))
        self.assertEqual(self.collect()['reused'], 2)
        self.assertEqual(len(calls), 2)

    def test_modified_owned_file_is_preserved_without_refetch(self):
        self.collect()
        self.asset().write_bytes(b'manual replacement')
        self.assertEqual(self.collect()['failed'], 1)
        self.assertEqual(self.asset().read_bytes(), b'manual replacement')
        self.assertEqual(len(self.fetch.calls), 1)
        self.assertNotIn('![[', '\n'.join(media.render_assets(self.posts[0], self.receipts)))

    def test_missing_download_needs_explicit_asset_only_retry(self):
        self.collect()
        self.asset().unlink()
        self.assertEqual(self.collect(max_downloads=0)['failed'], 1)
        self.assertEqual(len(self.fetch.calls), 1)
        self.assertEqual(self.collect(retry=True)['downloaded'], 1)
        self.assertEqual(len(self.fetch.calls), 2)
        self.assertIn('![[', '\n'.join(media.render_assets(self.posts[0], self.receipts)))

    def test_unknown_same_bytes_are_never_adopted(self):
        descriptor = media.discover_assets(self.posts[0])[0]
        path = self.vault / ('Sources/Images/x-123-' + descriptor['key'][:24] + '.png')
        path.parent.mkdir(parents=True)
        path.write_bytes(png())
        identity = os.stat(path).st_ino
        self.assertEqual(self.collect()['failed'], 1)
        self.assertEqual(os.stat(path).st_ino, identity)
        self.assertEqual(next(iter(self.receipts.values()))['status'], 'prepared')

    def test_retirement_preserves_unknown_same_byte_occupant(self):
        descriptor = media.discover_assets(self.posts[0])[0]
        path = self.vault / ('Sources/Images/x-123-' + descriptor['key'][:24] + '.png')
        path.parent.mkdir(parents=True)
        path.write_bytes(png())
        before = media._snapshot(path)
        self.assertEqual(self.collect()['failed'], 1)
        receipt = next(iter(self.receipts.values()))
        cached = self.vault / media.CACHE_REL / receipt['cache_name']
        self.posts[0].update(status='unavailable', assets=[])
        self.assertEqual(media.retire_assets(self.vault, self.posts, self.receipts, self.save),
                         {'removed': 0, 'blocked': 1})
        self.assertEqual(media._snapshot(path), before)
        self.assertTrue(cached.exists())
        cached.unlink()
        self.assertEqual(media.retire_assets(self.vault, self.posts, self.receipts, self.save)['blocked'], 1)
        self.assertEqual(media._snapshot(path), before)

    def test_case_collision_and_symlink_preserved(self):
        descriptor = media.discover_assets(self.posts[0])[0]
        path = self.vault / ('Sources/Images/X-123-' + descriptor['key'][:24] + '.PNG')
        path.parent.mkdir(parents=True)
        path.write_bytes(b'unknown')
        self.assertEqual(self.collect()['failed'], 1)
        self.assertEqual(path.read_bytes(), b'unknown')
        self.assertEqual(len(list(path.parent.iterdir())), 1)

    def test_symlinked_public_folder_is_refused(self):
        outside = self.vault / 'outside'
        outside.mkdir()
        (self.vault / 'Sources').mkdir()
        (self.vault / 'Sources/Images').symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.collect()['failed'], 1)
        self.assertEqual(list(outside.iterdir()), [])

    def test_prepared_publication_resumes_without_http(self):
        with patch.object(media, '_publish', side_effect=OSError('publication interrupted')):
            self.assertEqual(self.collect()['failed'], 1)
        self.assertEqual(next(iter(self.receipts.values()))['status'], 'prepared')
        self.assertEqual(self.collect()['reused'], 1)
        self.assertEqual(len(self.fetch.calls), 1)
        self.assertEqual(self.asset().read_bytes(), png())

    def test_interrupted_published_hardlink_is_recognized(self):
        normal_save = self.save
        fired = False
        def save():
            nonlocal fired
            if not fired and any(item.get('status') == 'downloaded' for item in self.receipts.values()):
                fired = True
                raise RuntimeError('process interrupted before final state save')
            normal_save()
        with self.assertRaises(RuntimeError):
            media.collect_assets(self.vault, self.posts, self.receipts, save, fetch=self.fetch)
        self.receipts = deepcopy(self.saved[-1])
        self.assertEqual(next(iter(self.receipts.values()))['status'], 'prepared')
        self.assertEqual(self.collect()['reused'], 1)
        self.assertEqual(len(self.fetch.calls), 1)

    def test_prepared_receipt_is_saved_before_cache_creation(self):
        def save():
            if any(item.get('status') == 'prepared' for item in self.receipts.values()):
                self.saved.append(deepcopy(self.receipts))
                raise RuntimeError('interrupted before cache creation')
            self.save()
        with self.assertRaises(RuntimeError):
            media.collect_assets(self.vault, self.posts, self.receipts, save, fetch=self.fetch)
        self.assertFalse((self.vault / media.CACHE_REL).exists())
        self.receipts = self.saved[-1]
        self.assertEqual(self.collect()['failed'], 1)
        self.assertEqual(len(self.fetch.calls), 1)
        self.assertEqual(self.collect(retry=True)['downloaded'], 1)
        self.assertEqual(len(self.fetch.calls), 2)

    def test_interrupted_partial_cache_explicit_retry_preserves_recovery_bytes(self):
        original = os.fdopen
        class InterruptedOutput:
            def __init__(self, output):
                self.output = output
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.output.close()
            def write(self, data):
                self.output.write(data[:12])
                self.output.flush()
                raise OSError('interrupted after partial cache write')
        with patch.object(media.os, 'fdopen', side_effect=lambda fd, mode: InterruptedOutput(original(fd, mode))):
            self.assertEqual(self.collect()['failed'], 1)
        receipt = next(iter(self.receipts.values()))
        partial = self.vault / media.CACHE_REL / receipt['cache_name']
        before = media._snapshot(partial)
        self.receipts = deepcopy(self.saved[-1])
        self.assertEqual(self.collect()['failed'], 1)
        self.assertEqual(len(self.fetch.calls), 1)
        result = self.collect(retry=True)
        self.assertEqual(result['downloaded'], 1)
        self.assertEqual(result['recovery_paths'], [str(partial)])
        self.assertEqual(len(self.fetch.calls), 2)
        self.assertEqual(self.asset().read_bytes(), png())
        self.assertEqual(media._snapshot(partial), before)
        receipt = next(iter(self.receipts.values()))
        self.assertEqual(receipt['recovery_paths'], [str(partial)])
        self.assertEqual(receipt['recovery_path'], str(partial))
        self.posts[0].update(status='unavailable', assets=[])
        result = media.retire_assets(self.vault, self.posts, self.receipts, self.save)
        self.assertEqual(result['removed'], 1)
        self.assertEqual(result['recovery_paths'], [str(partial)])
        self.assertEqual(receipt['recovery_paths'], [str(partial)])
        self.assertEqual(media._snapshot(partial), before)

    def test_failed_retry_and_retirement_retain_cache_recovery_locator(self):
        with patch.object(media, '_publish', side_effect=OSError('interrupted before publication')):
            self.collect()
        receipt = next(iter(self.receipts.values()))
        cached = self.vault / media.CACHE_REL / receipt['cache_name']
        cached.write_bytes(b'partial cache')
        before = media._snapshot(cached)
        self.fetch = lambda *args: (_ for _ in ()).throw(OSError('retry failed'))
        result = self.collect(retry=True)
        self.assertEqual(result['failed'], 1)
        self.assertEqual(result['recovery_paths'], [str(cached)])
        self.posts[0].update(status='unavailable', assets=[])
        result = media.retire_assets(self.vault, self.posts, self.receipts, self.save)
        self.assertEqual(result['recovery_paths'], [str(cached)])
        self.assertEqual(next(iter(self.receipts.values()))['recovery_paths'], [str(cached)])
        self.assertEqual(media._snapshot(cached), before)

    def test_retry_preserves_changed_cache_and_unknown_public_file(self):
        with patch.object(media, '_publish', side_effect=OSError('interrupted before publication')):
            self.collect()
        receipt = next(iter(self.receipts.values()))
        cached = self.vault / media.CACHE_REL / receipt['cache_name']
        cached.write_bytes(b'local cache replacement')
        changed = media._snapshot(cached)
        self.asset().parent.mkdir(parents=True)
        self.asset().write_bytes(png())
        unknown = media._snapshot(self.asset())
        self.assertEqual(self.collect(retry=True)['failed'], 1)
        self.assertEqual(len(self.fetch.calls), 2)
        self.assertEqual(media._snapshot(cached), changed)
        self.assertEqual(media._snapshot(self.asset()), unknown)
        self.assertEqual(next(iter(self.receipts.values()))['recovery_paths'], [str(cached)])

    def test_retirement_of_interrupted_owned_publication_preserves_proof_on_block(self):
        def save():
            if any(item.get('status') == 'downloaded' for item in self.receipts.values()):
                raise RuntimeError('interrupted before ownership save')
            self.save()
        with self.assertRaises(RuntimeError):
            media.collect_assets(self.vault, self.posts, self.receipts, save, fetch=self.fetch)
        self.receipts = deepcopy(self.saved[-1])
        path = self.asset()
        (self.vault / 'Reference.md').write_text('![[%s]]' % path.name, encoding='utf-8')
        self.posts[0].update(status='unavailable', assets=[])
        self.assertEqual(media.retire_assets(self.vault, self.posts, self.receipts, self.save)['blocked'], 1)
        self.assertEqual(next(iter(self.receipts.values()))['status'], 'downloaded')
        (self.vault / 'Reference.md').unlink()
        self.assertEqual(media.retire_assets(self.vault, self.posts, self.receipts, self.save)['removed'], 1)
        self.assertFalse(path.exists())

    def test_budget_defers_without_pending_failure(self):
        self.assertEqual(self.collect(max_downloads=0)['deferred'], 1)
        self.assertEqual(self.fetch.calls, [])
        self.assertEqual(self.collect()['downloaded'], 1)

    def test_failures_require_explicit_retry(self):
        self.fetch = lambda *args: (_ for _ in ()).throw(OSError('https://private-query.example/?secret=not-to-log'))
        self.assertEqual(self.collect()['failed'], 1)
        self.assertEqual(next(iter(self.receipts.values()))['error'], 'OSError')
        self.fetch = Fetch()
        self.assertEqual(self.collect()['failed'], 1)
        self.assertEqual(self.fetch.calls, [])
        self.assertEqual(self.collect(retry=True)['downloaded'], 1)

    def test_retire_owned_unused_media_and_scrub_source_metadata(self):
        self.collect()
        path = self.asset()
        self.posts[0].update(status='unavailable', assets=[])
        result = media.retire_assets(self.vault, self.posts, self.receipts, self.save)
        self.assertEqual(result, {'removed': 1, 'blocked': 0})
        self.assertFalse(path.exists())
        receipt = next(iter(self.receipts.values()))
        self.assertEqual(receipt['status'], 'retired')
        self.assertNotIn('url', receipt)
        self.assertNotIn('alt_text', receipt)

    def test_other_note_reference_blocks_retirement(self):
        self.collect()
        path = self.asset()
        (self.vault / 'My note.md').write_text('![[%s]]' % path.name, encoding='utf-8')
        self.posts[0].update(status='withheld', assets=[])
        self.assertEqual(media.retire_assets(self.vault, self.posts, self.receipts, self.save)['blocked'], 1)
        self.assertTrue(path.exists())

    def test_canvas_reference_and_unreadable_canvas_block_retirement(self):
        self.collect()
        path = self.asset()
        relative = str(path.relative_to(self.vault))
        canvas = self.vault / 'Board.canvas'
        canvas.write_text(json.dumps({'nodes': [{'id': '1', 'type': 'file', 'file': relative,
                                                 'x': 0, 'y': 0, 'width': 300, 'height': 300}],
                                      'edges': []}).replace('x-123-', r'\u0078-123-'), encoding='utf-8')
        self.posts[0].update(status='unavailable', assets=[])
        self.assertEqual(media.retire_assets(self.vault, self.posts, self.receipts, self.save)['blocked'], 1)
        self.assertTrue(path.exists())
        canvas.write_text('{"nodes": [', encoding='utf-8')
        self.assertEqual(media.retire_assets(self.vault, self.posts, self.receipts, self.save)['blocked'], 1)
        self.assertTrue(path.exists())
        canvas.write_text('{"nodes": [], "edges": []}', encoding='utf-8')
        self.assertEqual(media.retire_assets(self.vault, self.posts, self.receipts, self.save)['removed'], 1)

    def test_unreadable_subtree_blocks_retirement(self):
        self.collect()
        path = self.asset()
        hidden = self.vault / 'Unreachable'
        hidden.mkdir()
        (hidden / 'Note.md').write_text('![[%s]]' % path.name, encoding='utf-8')
        self.posts[0].update(status='unavailable', assets=[])
        original = os.scandir
        def scandir(folder):
            if Path(folder) == hidden:
                raise PermissionError('cannot scan a vault subtree')
            return original(folder)
        with patch.object(os, 'scandir', side_effect=scandir):
            result = media.retire_assets(self.vault, self.posts, self.receipts, self.save)
        self.assertEqual(result['blocked'], 1)
        self.assertTrue(path.exists())

    def test_still_shared_media_is_not_retired(self):
        self.posts.append(post(identity='124'))
        self.collect()
        self.posts[0].update(status='unavailable', assets=[])
        self.assertEqual(media.retire_assets(self.vault, self.posts, self.receipts, self.save)['removed'], 0)
        self.assertTrue(self.asset().exists())

    def test_reference_added_during_retirement_restores_owned_file(self):
        self.collect()
        path = self.asset()
        self.posts[0].update(status='unavailable', assets=[])
        original = media.atomic_move.remove_expected
        def remove(*args, **kwargs):
            result = original(*args, **kwargs)
            (self.vault / 'Concurrent.md').write_text('![[%s]]' % path.name, encoding='utf-8')
            return result
        with patch.object(media.atomic_move, 'remove_expected', side_effect=remove):
            result = media.retire_assets(self.vault, self.posts, self.receipts, self.save)
        self.assertEqual(result['blocked'], 1)
        self.assertEqual(path.read_bytes(), png())

    def test_restored_file_clears_previous_conflict_marker(self):
        self.collect()
        self.asset().write_bytes(b'temporary local edit')
        self.collect()
        self.asset().write_bytes(png())
        self.assertEqual(self.collect()['reused'], 1)
        self.assertIn('![[', '\n'.join(media.render_assets(self.posts[0], self.receipts)))


class NetworkTests(unittest.TestCase):
    def test_public_https_and_mixed_dns_fail_closed(self):
        for url in ('http://example.com/x.pdf', 'https://u:p@example.com/x.pdf',
                    'https://127.0.0.1/x.pdf', 'https://example.com:8443/x.pdf',
                    'https://0177.0.0.1/x.pdf', 'https://example.com/\r\nx.pdf'):
            with self.subTest(url=url), self.assertRaises(media.MediaError):
                media._target(url)
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443)),
                     (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.1.1.1', 443))]
        with patch.object(socket, 'getaddrinfo', return_value=addresses), self.assertRaises(media.MediaError):
            media._target('https://example.com/x.pdf')

    def test_ipv6_transition_private_endpoints(self):
        for value in ('::ffff:127.0.0.1', '::127.0.0.1', '2002:7f00:1::',
                      '64:ff9b::7f00:1', 'fec0::1', 'ff02::1'):
            self.assertFalse(media._public_ip(value), value)

    def test_file_type_integrity_not_extension(self):
        self.assertEqual(media.extension(png(), 'image', 'image/png'), 'png')
        self.assertEqual(media.extension(pdf(), 'pdf', 'application/pdf'), 'pdf')
        for data, kind, mime in ((b'<svg/>', 'image', 'image/svg+xml'),
                                 (png(), 'image', 'text/html'),
                                 (png()[:-1], 'image', 'image/png'),
                                 (b'\xff\xd8\xff<html>evil</html>\xff\xd9', 'image', 'image/jpeg'),
                                 (b'%PDF-1.4\n<html/>\nstartxref\n0\n%%EOF', 'pdf', 'application/pdf')):
            with self.subTest(kind=kind, mime=mime), self.assertRaises(media.MediaError):
                media.extension(data, kind, mime)

    def test_png_requires_complete_nonempty_raster(self):
        # Chunk lengths and CRCs are correct in every fixture; only the actual
        # compressed raster is absent, truncated, corrupt or the wrong length.
        compressed = zlib.compress(b'\0\x80\x80\x80')
        invalid = [png(compressed=b''), png(compressed=compressed[:-1]),
                   png(compressed=compressed[:-1] + bytes([compressed[-1] ^ 1])),
                   png(raster=b''), png(raster=b'\0\x80\x80'),
                   png(raster=b'\0\x80\x80\x80\x80'),
                   png(compressed=compressed + zlib.compress(b'extra'))]
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(media.MediaError):
                media.extension(raw, 'image', 'image/png')
        self.assertEqual(media.extension(png(), 'image'), 'png')
        # One-bit grayscale rows and a 2x2 Adam7 image retain their different
        # row packing. This protects valid formats from the size check.
        self.assertEqual(media.extension(png(raster=b'\0\x80', header=(1, 1, 1, 0, 0, 0, 0)), 'image'), 'png')
        interlaced = b'\0\xff\0\0' + b'\0\0\xff\0' + b'\0\0\0\xff\xff\xff\xff'
        self.assertEqual(media.extension(png(raster=interlaced, header=(2, 2, 8, 2, 0, 0, 1)), 'image'), 'png')

    def test_png_raster_expansion_is_bounded(self):
        # Reject a huge claimed canvas before inflating; cap expansion even
        # when the tiny canvas claims far fewer bytes than its payload emits.
        huge = png(header=(2 ** 31 - 1, 2 ** 31 - 1, 16, 6, 0, 0, 0))
        with patch.object(media.zlib, 'decompressobj', side_effect=AssertionError('should not inflate')):
            with self.assertRaises(media.MediaError):
                media.extension(huge, 'image')
        with self.assertRaises(media.MediaError):
            media.extension(png(raster=b'\0' * (1024 * 1024)), 'image')

    def test_gif_and_webp_require_bounded_raster_payloads(self):
        # Small encoder-generated images cover GIF and lossy, lossless, alpha,
        # and animated WebP without requiring an image decoder at runtime.
        fixtures = {
            'gif': ['R0lGODdhAgACAIEAAP8AAAAAAAAAAAAAACwAAAAAAgACAAAIBgABCAQQEAA7'],
            'webp': ['UklGRjwAAABXRUJQVlA4IDAAAADQAQCdASoCAAIAAUAmJaACdLoB+AADsAD+8ut//NgVzXPv9//S4P0uD9Lg/9KQAAA=',
                     'UklGRhwAAABXRUJQVlA4TA8AAAAvAUAAEAcQ/Y+SBSKi/wEA',
                     'UklGRlwAAABXRUJQVlA4WAoAAAAQAAAAAQAAAQAAQUxQSAUAAAAAZGRkZABWUDggMAAAANABAJ0BKgIAAgABQCYloAJ0ugH4AAOwAP7y63/82BXNc+/3/9Lg/S4P0uD/0pAAAA==',
                     'UklGRsQAAABXRUJQVlA4WAoAAAACAAAAAQAAAQAAQU5JTQYAAAAAAAAAAABBTk1GSgAAAAAAAAAAAAEAAAEAAGQAAAJWUDggMgAAADABAJ0BKgIAAgABQCYloAADcAD+8ut///mwP/bz/wR6Af//0uD//pcH//S4P/SkAAAAQU5NRkYAAAAAAAAAAAABAAABAABkAAAAVlA4IC4AAAA0AQCdASoCAAIAAAAmJaAAA3AA/vtV4///S4P/+lwf/9Lg/9Lg//rV5Vesq6AA']}
        for suffix, examples in fixtures.items():
            for encoded in examples:
                data = base64.b64decode(encoded)
                with self.subTest(suffix=suffix, data=data):
                    self.assertEqual(media.extension(data, 'image'), suffix)
                    with self.assertRaises(media.MediaError):
                        media.extension(data[:-1], 'image')
        malformed = [b'GIF89a' + struct.pack('<HH', 1, 1) + b'\x00\x00\x00;',
                     b'RIFF' + struct.pack('<I', 12) + b'WEBPVP8 ' + struct.pack('<I', 0),
                     b'RIFF' + struct.pack('<I', 12) + b'WEBPVP8L' + struct.pack('<I', 999),
                     b'RIFF' + struct.pack('<I', 22) + b'WEBPVP8X' + struct.pack('<I', 10) + bytes(10)]
        for data in malformed:
            with self.subTest(data=data), self.assertRaises(media.MediaError):
                media.extension(data, 'image')

    def test_redirect_is_revalidated_before_second_connection(self):
        class Response:
            status = 302
            def close(self):
                pass
            def getheader(self, name, default=None):
                return 'https://127.0.0.1/private.pdf' if name == 'Location' else default
        class Connection:
            def close(self):
                pass
        original = media._target
        def target(url):
            return ('example.com', '/file.pdf', []) if 'example.com' in url else original(url)
        budget = {'maximum': 4, 'requests': 0, 'bytes': 0, 'max_bytes': media.RUN_LIMIT}
        with patch.object(media, '_target', side_effect=target), patch.object(media, '_request',
                return_value=(Connection(), Response(), None)) as request, self.assertRaises(media.MediaError):
            media.fetch_asset('https://example.com/file.pdf', 'pdf', budget)
        self.assertEqual(request.call_count, 1)

    def test_total_bytes_and_truncation(self):
        class Response:
            status = 200
            def __init__(self, data, declared):
                self.stream, self.declared = io.BytesIO(data), declared
            def getheader(self, name, default=None):
                return str(self.declared) if name == 'Content-Length' else default
            def read1(self, maximum):
                return self.stream.read(maximum)
            def close(self):
                pass
        class Connection:
            def close(self):
                pass
        class Wire:
            def settimeout(self, seconds):
                pass
        for maximum, declared in ((5, 8), (100, 20)):
            budget = {'maximum': 1, 'requests': 0, 'bytes': 0, 'max_bytes': maximum}
            with patch.object(media, '_target', return_value=('example.com', '/file.pdf', [])), \
                    patch.object(media, '_request', return_value=(Connection(), Response(b'12345678', declared), Wire())), \
                    self.assertRaises(media.MediaError):
                media.fetch_asset('https://example.com/file.pdf', 'pdf', budget)
            self.assertLessEqual(budget['bytes'], maximum + 1)

    def test_slow_drip_headers_cannot_restart_total_deadline(self):
        ticks = [0]
        class Raw(io.RawIOBase):
            def readable(self):
                return True
            def readinto(self, buffer):
                ticks[0] += 1
                buffer[0] = ord('H')
                return 1
        class Wire:
            def settimeout(self, value):
                pass
            def makefile(self, mode, buffering):
                return Raw()
        with patch.object(media.time, 'monotonic', side_effect=lambda: ticks[0]):
            stream = media._deadline_socket(Wire(), deadline=3).makefile('rb')
            with self.assertRaises(media.MediaError):
                stream.readline()
            stream.close()
        self.assertEqual(ticks[0], 3)


if __name__ == '__main__':
    unittest.main()
