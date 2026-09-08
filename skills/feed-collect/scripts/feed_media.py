#!/usr/bin/env python3
"""Archive direct X photo/PDF assets without further X API requests.

Imported by feed_collect. HTTP uses pinned public HTTPS sockets, no credentials,
bounded redirects/bytes/time, durable receipts and exclusive guarded publication.
Source text and link-card thumbnails are never interpreted as photo attachments.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import http.client
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import socket
import ssl
import struct
import tempfile
import time
import urllib.parse
import uuid
import zlib

_OBSIDIAN_SHARED_MODULES = ('atomic_move', 'portable_names')

# --- obsidian shared-layer bootstrap (canonical; see shared/RUNTIME.md) ---
import os as _os, sys as _sys
_here = _os.path.dirname(_os.path.realpath(__file__))
_required = tuple(_m + ".py" for _m in (
    globals().get("_OBSIDIAN_SHARED_MODULES") or ("slugify",)))
_env = _os.environ.get("OBSIDIAN_VAULT_SHARED")
if _env:                                   # explicit override: authoritative, no fallback
    _tried = [_os.path.abspath(_os.path.expanduser(_env))]
else:                                      # plugin-relative walk-up, at most 5 levels
    _tried, _d = [], _here
    for _ in range(5):
        _tried.append(_os.path.join(_d, "shared", "scripts"))
        _d = _os.path.dirname(_d)
    _tried.append(_here)                   # extracted skill with co-located helpers
_missing = {_p: [_m for _m in _required if not _os.path.isfile(_os.path.join(_p, _m))]
            for _p in _tried if _os.path.isdir(_p)}
_shared = next((_p for _p in _tried if _p in _missing and not _missing[_p]), None)
if _shared is None:
    raise SystemExit("""obsidian: cannot find the plugin's shared/scripts/ folder, which holds
the one canonical copy of the conventions this script depends on. A usable
folder must contain these required module(s): %s
Looked for:
  %s
Fix: install the whole plugin tree, or set OBSIDIAN_VAULT_SHARED to the
shared/scripts/ directory (unset it to use the plugin-relative walk-up).
Do NOT paste a second copy of the algorithm into this skill -- a divergent
copy is the bug the shared layer exists to prevent.""" % (
    ", ".join(_required), "\n  ".join(
        _p + (" (not a directory)" if _p not in _missing else
              " (missing: %s)" % ", ".join(_missing[_p]))
        for _p in _tried)))
_sys.path[:] = [_p for _p in _sys.path if _p not in (_shared, _here)]
_sys.path.insert(0, _shared)               # shared/scripts/ FIRST
if _here != _shared:
    _sys.path.insert(1, _here)              # sibling modules before unrelated paths
# --- end bootstrap ---

import atomic_move
from portable_names import portable_identity

PHOTO_LIMIT = 20 * 1024 * 1024
PDF_LIMIT = 50 * 1024 * 1024
RUN_LIMIT = 256 * 1024 * 1024
PNG_RASTER_LIMIT = 256 * 1024 * 1024
ASSET_PATH = re.compile(r'Sources/(?:Images/x-[0-9]{1,25}-[a-f0-9]{24}\.(?:jpg|png|gif|webp)|PDFs/x-[0-9]{1,25}-[a-f0-9]{24}\.pdf)\Z')
KEY = re.compile(r'[a-f0-9]{64}\Z')
CACHE_REL = 'Investments/Sources/.feed-collect/assets'


class MediaError(Exception):
    pass


def _key(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def discover_assets(post):
    """Return only own attachments and directly identified PDF links.

    Missing expansions remain explicit metadata gaps. A bare media key could
    identify a video, so it is not labelled a photo until its type is known.
    """
    if post.get('status', 'available') != 'available':
        return []
    found = {}
    keys = post.get('attachments', {}).get('media_keys', [])
    if not isinstance(keys, list) or any(not isinstance(key, str) for key in keys):
        raise MediaError('invalid_attachment_keys')
    metadata = post.get('media', [])
    legacy = post.get('media_metadata', {})
    if isinstance(legacy, dict):
        metadata = list(metadata) + [dict(value, media_key=key)
                                     for key, value in legacy.items() if isinstance(value, dict)]
    elif isinstance(legacy, list):
        metadata = list(metadata) + legacy
    by_key = {}
    for row in metadata:
        if isinstance(row, dict) and row.get('media_key') in keys:
            current = by_key.get(row['media_key'], {})
            # Prefer expanded, typed data over a later bare legacy key.
            by_key[row['media_key']] = dict(row, **current) if current.get('type') else dict(current, **row)
    for key in keys:
        row = by_key.get(key, {})
        kind = 'image' if row.get('type') == 'photo' else 'attachment'
        identity = _key('x-media:' + key)
        item = {'key': identity, 'kind': kind, 'media_key': key,
                'url': row.get('url') if kind == 'image' else None}
        if row.get('type') in {'video', 'animated_gif'}:
            item['unsupported'] = row['type']
        if isinstance(row.get('alt_text'), str):
            item['alt_text'] = row['alt_text']
        found[identity] = item
    for container in (post.get('entities', {}), post.get('long_post_entities', {})):
        rows = container.get('urls', []) if isinstance(container, dict) else []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            for url in (row.get('unwound_url'), row.get('expanded_url')):
                if not isinstance(url, str):
                    continue
                try:
                    direct = urllib.parse.unquote(urllib.parse.urlsplit(url).path).lower().endswith('.pdf')
                except ValueError:
                    continue
                if direct:
                    url = url.split('#', 1)[0]
                    identity = _key('pdf:' + str(post.get('id', '')) + ':' + url)
                    found[identity] = {'key': identity, 'kind': 'pdf', 'url': url}
                    break
    return list(found.values())


def _public_ip(value):
    address = ipaddress.ip_address(value)
    if not (address.is_global and not address.is_private and not address.is_reserved
            and not address.is_loopback and not address.is_link_local
            and not address.is_multicast and not address.is_unspecified):
        return False
    if address.version == 6:
        # Reject transition forms altogether; some Python versions classify
        # translated private IPv4 endpoints as globally routable IPv6.
        integer = int(address)
        if (address.ipv4_mapped or address.sixtofour or address.teredo
                or address.is_site_local or integer >> 32 == 0
                or integer >> 32 == 0x64FF9B0000000000000000
                or integer >> 80 == 0x64FF9B0001
                or address.packed[8:12] in (b'\0\0\x5e\xfe', b'\x02\0\x5e\xfe')):
            return False
    return True


def _target(url):
    if (not isinstance(url, str) or len(url) > 8192
            or any(ord(character) <= 32 or ord(character) == 127 for character in url)):
        raise MediaError('invalid_asset_url')
    try:
        parts = urllib.parse.urlsplit(url)
        if (parts.scheme != 'https' or not parts.hostname or parts.username is not None
                or parts.password is not None or parts.port not in (None, 443)
                or parts.netloc.endswith(':') or '%' in parts.hostname):
            raise ValueError()
        host = parts.hostname.encode('idna').decode('ascii')
        try:
            literal = socket.inet_ntoa(socket.inet_aton(host))
        except OSError:
            literal = None
        if literal is not None and literal != host:
            raise ValueError()
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(family not in (socket.AF_INET, socket.AF_INET6)
                                or not _public_ip(endpoint[0])
                                for family, _, _, _, endpoint in addresses):
            raise ValueError()
    except (ValueError, UnicodeError, OSError):
        raise MediaError('asset_host_must_resolve_only_to_public_https_addresses') from None
    path = urllib.parse.quote(parts.path or '/', safe="/%:@!$&'()*+,;=-._~")
    if '?' in url.split('#', 1)[0]:
        path += '?' + urllib.parse.quote(parts.query, safe="/%?:@!$&'()*+,;=-._~")
    return host, path, addresses


def _request(host, path, addresses, deadline):
    """Resolve once, connect to one vetted address, retain hostname TLS checks."""
    wire = None
    for family, socktype, protocol, _, endpoint in addresses:
        if time.monotonic() >= deadline:
            raise MediaError('asset_download_timeout')
        candidate = socket.socket(family, socktype, protocol)
        try:
            candidate.settimeout(max(0.01, min(15, deadline - time.monotonic())))
            candidate.connect(endpoint)
            wire = candidate
            break
        except OSError:
            candidate.close()
    if wire is None:
        raise MediaError('asset_connect_failed')
    connection = None
    try:
        wire = ssl.create_default_context().wrap_socket(wire, server_hostname=host)
        connection = http.client.HTTPConnection(host, 443)
        connection.sock = _deadline_socket(wire, deadline)
        connection.request('GET', path, headers={
            'Host': '[' + host + ']' if ':' in host else host,
            'User-Agent': 'obsidian-investments-feed-collect/1.0',
            'Accept-Encoding': 'identity', 'Connection': 'close'})
        return connection, connection.getresponse(), wire
    except Exception:
        if connection is not None:
            connection.close()
        else:
            wire.close()
        raise


def _deadline_socket(wire, deadline):
    """Apply the wall-clock deadline to header reads, including slow drips.

    Use the socket's raw makefile so its normal descriptor reference counting
    keeps response bytes readable after HTTPConnection detaches a close response.
    """
    def remaining():
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise MediaError('asset_download_timeout')
        wire.settimeout(min(15, seconds))

    class Reader(io.RawIOBase):
        def __init__(self, raw):
            self.raw = raw
        def readable(self):
            return True
        def readinto(self, buffer):
            remaining()
            return self.raw.readinto(buffer)
        def close(self):
            try:
                self.raw.close()
            finally:
                super().close()

    class DeadlineSocket:
        def makefile(self, mode):
            return io.BufferedReader(Reader(wire.makefile(mode, buffering=0)))
        def sendall(self, data):
            remaining()
            return wire.sendall(data)
        def close(self):
            wire.close()

    return DeadlineSocket()


def fetch_asset(url, kind, budget):
    """Fetch at most five public HTTPS hops; no cookies, auth or proxy env."""
    limit = PHOTO_LIMIT if kind == 'image' else PDF_LIMIT
    deadline = time.monotonic() + 60
    visited = set()
    for _ in range(5):
        if url in visited:
            raise MediaError('asset_redirect_loop')
        visited.add(url)
        host, path, addresses = _target(url)
        if budget['requests'] >= budget['maximum']:
            raise MediaError('asset_request_budget_exhausted')
        if time.monotonic() >= deadline:
            raise MediaError('asset_download_timeout')
        budget['requests'] += 1
        connection, response, _ = _request(host, path, addresses, deadline)
        try:
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader('Location')
                if not location:
                    raise MediaError('asset_redirect_missing_location')
                url = urllib.parse.urljoin(url, location)
                continue
            if response.status != 200:
                raise MediaError('asset_http_' + str(response.status))
            if response.getheader('Content-Encoding', 'identity').lower() not in {'', 'identity'}:
                raise MediaError('asset_compressed_transfer_refused')
            length = response.getheader('Content-Length')
            if length is not None and (not length.isdigit() or int(length) > limit):
                raise MediaError('asset_invalid_or_oversized_length')
            chunks, size = [], 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MediaError('asset_download_timeout')
                # HTTPResponse may have closed its file (and the detached
                # socket) after the previous read completed the body. The
                # deadline reader bounds actual socket reads; let HTTPResponse
                # return EOF without touching an already closed descriptor.
                chunk = response.read1(min(65536, limit + 1 - size,
                                           budget['max_bytes'] + 1 - budget['bytes']))
                if not chunk:
                    break
                size += len(chunk)
                budget['bytes'] += len(chunk)
                if size > limit or budget['bytes'] > budget['max_bytes']:
                    raise MediaError('asset_download_byte_limit')
                chunks.append(chunk)
            if length is not None and size != int(length):
                raise MediaError('asset_truncated_download')
            return {'data': b''.join(chunks), 'content_type': response.getheader('Content-Type', ''),
                    'final_url': url}
        finally:
            try:
                response.close()
            finally:
                connection.close()
    raise MediaError('asset_redirect_limit')


def extension(data, kind, content_type=''):
    """Validate bounded binary signatures/structure, never SVG or HTML.

    This is a download integrity check, not a PDF parser or malware scanner.
    We do not execute content, render PDFs, or decode untrusted image pixels.
    """
    if not isinstance(data, bytes) or not data or len(data) > (PHOTO_LIMIT if kind == 'image' else PDF_LIMIT):
        raise MediaError('asset_empty_or_oversized')
    mime = content_type.split(';', 1)[0].strip().lower()
    if mime in {'text/html', 'application/xhtml+xml', 'image/svg+xml'}:
        raise MediaError('asset_active_content_refused')
    if kind == 'pdf':
        trailer = re.search(br'startxref\s+([0-9]+)\s+%%EOF\s*\Z', data[-2048:])
        offset = int(trailer[1]) if trailer else 0
        xref = data[offset:offset + 512] if 0 < offset < len(data) else b''
        if (not re.match(br'%PDF-[12]\.[0-9][\r\n]', data)
                or not (xref.startswith(b'xref') or
                        re.match(br'[0-9]+\s+[0-9]+\s+obj\b', xref) and
                        re.search(br'/Type\s*/XRef\b', xref))
                or mime not in {'', 'application/pdf', 'application/octet-stream'}):
            raise MediaError('asset_not_a_valid_pdf_download')
        return 'pdf'
    result = None
    if data.startswith(b'\xff\xd8\xff') and _jpeg(data):
        result = 'jpg'
    elif data.startswith(b'\x89PNG\r\n\x1a\n'):
        offset, types, payload = 8, [], []
        header = None
        while offset + 12 <= len(data):
            count = struct.unpack('>I', data[offset:offset + 4])[0]
            block = data[offset + 4:offset + 8 + count]
            end = offset + 12 + count
            if end > len(data) or zlib.crc32(block) & 0xffffffff != struct.unpack('>I', data[end - 4:end])[0]:
                raise MediaError('asset_invalid_png_chunk')
            types.append(block[:4])
            if len(types) == 1 and (block[:4] != b'IHDR' or count != 13
                                  or 0 in struct.unpack('>II', block[4:12])):
                raise MediaError('asset_invalid_png_header')
            if len(types) == 1:
                header = struct.unpack('>IIBBBBB', block[4:])
            if block[:4] == b'IDAT':
                payload.append(block[4:])
            offset = end
            if block[:4] == b'IEND':
                if count != 0 or end != len(data):
                    raise MediaError('asset_invalid_png_end')
                break
        if (types and types[-1] == b'IEND' and offset == len(data)
                and _png_raster(payload, header)):
            result = 'png'
    elif data[:6] in {b'GIF87a', b'GIF89a'} and _gif(data):
        result = 'gif'
    elif _webp(data):
        result = 'webp'
    allowed = {'jpg': {'image/jpeg', 'image/jpg'}, 'png': {'image/png'},
               'gif': {'image/gif'}, 'webp': {'image/webp'}}
    if result is None or mime not in ({'', 'application/octet-stream'} | allowed[result]):
        raise MediaError('asset_not_a_supported_raster_download')
    return result


def _png_raster(payload, header):
    """Check the bounded zlib stream and scanline length without rendering pixels."""
    if not header or not payload:
        return False
    width, height, depth, color, compression, filtering, interlace = header
    depths = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8},
              4: {8, 16}, 6: {8, 16}}
    if depth not in depths.get(color, ()) or compression or filtering or interlace not in (0, 1):
        return False
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
    # Adam7 emits independently filtered rows for each nonempty pass.
    passes = ((0, 0, 1, 1),) if not interlace else (
        (0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
        (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))
    expected = 0
    for left, top, step_x, step_y in passes:
        columns = max(0, (width - left + step_x - 1) // step_x)
        rows = max(0, (height - top + step_y - 1) // step_y)
        if columns and rows:
            expected += rows * (1 + (columns * channels * depth + 7) // 8)
    if not 0 < expected <= PNG_RASTER_LIMIT:
        return False
    decoder, size = zlib.decompressobj(), 0
    try:
        for block in payload:
            pending = block
            while True:
                limit = min(65536, expected - size + 1)
                expanded = decoder.decompress(pending, limit)
                size += len(expanded)
                if size > expected or decoder.unused_data:
                    return False
                pending = decoder.unconsumed_tail
                if not pending and len(expanded) < limit:
                    break
    except zlib.error:
        return False
    return decoder.eof and size == expected


def _jpeg(data):
    """Require bounded marker segments, dimensions, scan data and a final EOI."""
    position, frame, scan = 2, False, False
    while position < len(data):
        if data[position] != 255:
            return False
        while position < len(data) and data[position] == 255:
            position += 1
        if position >= len(data):
            return False
        marker = data[position]
        position += 1
        if marker == 0xd9:
            return position == len(data) and frame and scan
        if marker in {0, 0xd8} or 0xd0 <= marker <= 0xd7 or position + 2 > len(data):
            return False
        length = int.from_bytes(data[position:position + 2], 'big')
        if length < 2 or position + length > len(data):
            return False
        if marker in {0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf}:
            if length < 8 or 0 in struct.unpack('>HH', data[position + 3:position + 7]):
                return False
            frame = True
        position += length
        if marker == 0xda:
            scan = True
            if not frame:
                return False
            while position < len(data):
                if data[position] == 255:
                    if position + 1 >= len(data):
                        return False
                    if data[position + 1] == 0 or 0xd0 <= data[position + 1] <= 0xd7:
                        position += 2
                        continue
                    break
                position += 1
    return False


def _gif(data):
    """Require a complete image descriptor and bounded image-data subblocks."""
    if len(data) < 14 or 0 in struct.unpack('<HH', data[6:10]):
        return False
    packed = data[10]
    position = 13 + (3 * 2 ** ((packed & 7) + 1) if packed & 0x80 else 0)
    image = False
    while position < len(data):
        marker = data[position]
        position += 1
        if marker == 0x3b:
            return image and position == len(data)
        if marker == 0x2c:
            if position + 9 > len(data) or 0 in struct.unpack('<HH', data[position + 4:position + 8]):
                return False
            packed = data[position + 8]
            position += 9 + (3 * 2 ** ((packed & 7) + 1) if packed & 0x80 else 0)
            if position >= len(data) or not 2 <= data[position] <= 8:
                return False
            position += 1
        elif marker == 0x21:
            position += 1  # Extension label precedes its subblocks.
        else:
            return False
        payload = 0
        while position < len(data):
            count = data[position]
            position += 1
            if count == 0:
                break
            payload += count
            position += count
        else:
            return False
        if position > len(data) or marker == 0x2c and payload == 0:
            return False
        image = image or marker == 0x2c
    return False


def _webp(data):
    """Check RIFF chunk boundaries and require an actual raster payload."""
    if (len(data) < 20 or data[:4] != b'RIFF' or data[8:12] != b'WEBP'
            or struct.unpack('<I', data[4:8])[0] + 8 != len(data)
            or data[12:16] not in {b'VP8 ', b'VP8L', b'VP8X'}):
        return False

    def chunks(raw, *, frame=False):
        position, image = 0, False
        while position + 8 <= len(raw):
            kind = raw[position:position + 4]
            count = struct.unpack('<I', raw[position + 4:position + 8])[0]
            start, end = position + 8, position + 8 + count
            position = end + (count & 1)
            if position > len(raw):
                return False
            payload = raw[start:end]
            if kind == b'VP8 ':
                if (count <= 10 or payload[0] & 1 or payload[3:6] != b'\x9d\x01\x2a'
                        or any(value & 0x3fff == 0 for value in struct.unpack('<HH', payload[6:10]))):
                    return False
                image = True
            elif kind == b'VP8L':
                if count <= 5 or payload[0] != 0x2f or payload[4] & 0xe0:
                    return False
                image = True
            elif kind == b'VP8X':
                if count != 10 or frame:
                    return False
            elif kind == b'ANMF':
                if frame or count <= 16 or not chunks(payload[16:], frame=True):
                    return False
                image = True
        return position == len(raw) and image

    return chunks(data[12:])


def _directory(path, create=False):
    """Open an exact directory chain, refusing links and portable aliases."""
    if '..' in Path(path).parts:
        raise MediaError('asset_unsafe_path')
    path = Path(os.path.abspath(path))
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            aliases = [name for name in os.listdir(descriptor)
                       if portable_identity(name) == portable_identity(part)]
            if aliases and aliases != [part]:
                raise MediaError('asset_directory_spelling_collision')
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _anchored(descriptor):
    @contextmanager
    def enter():
        before = os.open('.', os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fchdir(descriptor)
            yield
        finally:
            os.fchdir(before)
            os.close(before)
    return enter()


def _snapshot(path):
    info = os.lstat(path)
    if info.st_size > PDF_LIMIT:
        raise MediaError('asset_existing_file_oversized')
    return atomic_move.regular_file_snapshot(path)


def _path(receipt):
    path = receipt.get('path')
    if not isinstance(path, str) or not ASSET_PATH.fullmatch(path):
        raise MediaError('asset_invalid_receipt_path')
    return path


def verify_asset(vault, receipt):
    relative = _path(receipt)
    descriptor = _directory(Path(vault) / Path(relative).parent)
    try:
        with _anchored(descriptor):
            name = Path(relative).name
            aliases = [entry for entry in os.listdir('.')
                       if portable_identity(entry) == portable_identity(name)]
            if not aliases:
                raise FileNotFoundError(name)
            current = _snapshot(name) if aliases == [name] else None
            if current is None or current.digest != receipt.get('sha256'):
                raise MediaError('asset_ownership_or_edit_conflict')
            if receipt.get('status') != 'downloaded':
                if receipt.get('status') != 'prepared':
                    raise MediaError('asset_publication_ownership_unverified')
                try:
                    cache = _directory(Path(vault) / CACHE_REL)
                    try:
                        with _anchored(cache):
                            cached = _snapshot(_cache_path(receipt))
                    finally:
                        os.close(cache)
                except FileNotFoundError:
                    raise MediaError('asset_publication_ownership_unverified') from None
                if current != cached:
                    raise MediaError('asset_publication_ownership_unverified')
    finally:
        os.close(descriptor)
    return True


def _cache_path(receipt):
    name = receipt.get('cache_name')
    if not isinstance(name, str) or not re.fullmatch(r'[a-f0-9]{64}\.bin', name):
        raise MediaError('asset_invalid_cache_name')
    return name


def _remove_owned(folder, name, digest, after_remove=None):
    descriptor = _directory(folder)
    try:
        with _anchored(descriptor):
            expected = _snapshot(name)
            if expected.digest != digest:
                raise MediaError('asset_ownership_or_edit_conflict')
            stage = tempfile.mkdtemp(prefix='.feed-asset-remove-', dir='..')
            keep = True
            try:
                atomic_move.remove_expected(name, expected, _snapshot, stage, stage_parent='..')
                if after_remove is not None:
                    try:
                        after_remove()
                    except Exception:
                        try:
                            atomic_move.publish_new(str(Path(stage) / '.atomic-displaced'), name,
                                                    _snapshot, '..')
                        except Exception as error:
                            raise atomic_move.PublicationConflict(
                                'asset_retirement_restore_conflict',
                                recovery_path=str(Path(stage).resolve()), keep_stage=True) from error
                        keep = False
                        raise
                keep = False
            except (atomic_move.PublicationConflict, atomic_move.LinkUnavailable) as error:
                keep = error.keep_stage
                raise
            finally:
                if not keep:
                    shutil.rmtree(stage)
    finally:
        os.close(descriptor)


def _publish(vault, receipt, save):
    if receipt.get('status') == 'downloaded':
        verify_asset(vault, receipt)
        _clear_cache(vault, receipt, save)
        return
    relative = _path(receipt)
    descriptor = _directory(Path(vault) / Path(relative).parent, create=True)
    try:
        with _anchored(descriptor):
            name = Path(relative).name
            aliases = [entry for entry in os.listdir('.')
                       if portable_identity(entry) == portable_identity(name)]
            cache_fd = _directory(Path(vault) / CACHE_REL)
            stage = tempfile.mkdtemp(prefix='.feed-asset-publish-', dir='..')
            keep = True
            try:
                staged = str(Path(stage) / 'asset.bin')
                # The source directory handle anchors the cache leaf; the
                # target directory handle anchors every public path. The link
                # also supplies durable proof for interrupted publication.
                os.link(_cache_path(receipt), staged, src_dir_fd=cache_fd, follow_symlinks=False)
                cached = _snapshot(staged)
                if cached.digest != receipt['sha256']:
                    raise MediaError('asset_cache_changed')
                if aliases:
                    current = _snapshot(name) if aliases == [name] else None
                    if (current is None or current.digest != receipt['sha256']
                            or receipt.get('status') != 'downloaded' and current.identity != cached.identity):
                        raise MediaError('asset_ownership_or_edit_conflict')
                else:
                    published = atomic_move.publish_new(staged, name, _snapshot, '..')
                    if published.digest != receipt['sha256']:
                        raise MediaError('asset_publication_changed')
                    aliases = [entry for entry in os.listdir('.')
                               if portable_identity(entry) == portable_identity(name)]
                    if aliases != [name]:
                        _remove_owned('.', name, published.digest)
                        raise MediaError('asset_portable_name_collision_after_publication')
                keep = False
            except (atomic_move.PublicationConflict, atomic_move.LinkUnavailable) as error:
                keep = error.keep_stage
                if keep:
                    receipt['recovery_path'] = str(Path(stage).resolve())
                raise
            except MediaError:
                keep = False
                raise
            finally:
                os.close(cache_fd)
                if not keep:
                    shutil.rmtree(stage)
        receipt['status'] = 'downloaded'
        receipt.pop('error', None)
        save()
    finally:
        os.close(descriptor)
    _clear_cache(vault, receipt, save)


def _clear_cache(vault, receipt, save):
    if receipt.get('cache_name'):
        try:
            _remove_owned(Path(vault) / CACHE_REL, _cache_path(receipt), receipt['sha256'])
        except FileNotFoundError:
            pass  # Cleanup may have finished just before the prior save failed.
        receipt.pop('cache_name', None)
        save()


def _error(receipt, error):
    # Network error messages may echo query strings. Store structured reasons,
    # with a separate local recovery path only when the safe writer supplies it.
    receipt['error'] = str(error) if isinstance(error, MediaError) else type(error).__name__
    if getattr(error, 'recovery_path', None):
        receipt['recovery_path'] = error.recovery_path


def _report_recovery_paths(summary, receipts):
    paths = set()
    for receipt in receipts.values():
        saved = receipt.get('recovery_paths', [])
        for path in [receipt.get('recovery_path')] + (saved if isinstance(saved, list) else []):
            if isinstance(path, str):
                paths.add(path)
    if paths:
        summary['recovery_paths'] = sorted(paths)


def collect_assets(vault, posts, receipts, save, *, max_downloads=40, max_bytes=RUN_LIMIT,
                   retry=False, fetch=None):
    """Update durable receipts, then publish validated local assets.

    Failed or ambiguous asset downloads are not repeated without retry=True.
    Prepared successful downloads resume offline. X post records are never read
    by this helper, and saved missing metadata does not trigger paid X lookups.
    """
    if not isinstance(max_downloads, int) or isinstance(max_downloads, bool) or not 0 <= max_downloads <= 500:
        raise MediaError('asset_request_budget_out_of_range')
    if not isinstance(receipts, dict):
        raise MediaError('invalid_asset_receipts')
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or not 0 <= max_bytes <= 1024 * 1024 * 1024:
        raise MediaError('asset_byte_budget_out_of_range')
    vault = Path(os.path.abspath(vault))
    fetch = fetch or fetch_asset
    budget = {'maximum': max_downloads, 'requests': 0, 'bytes': 0, 'max_bytes': max_bytes}
    summary = {'downloaded': 0, 'reused': 0, 'failed': 0, 'deferred': 0,
               'metadata_unavailable': 0, 'unsupported': 0}
    handled = set()
    for post in posts:
        descriptors = discover_assets(post)
        post['assets'] = [item['key'] for item in descriptors]
        for item in descriptors:
            identity = item['key']
            if identity in handled:
                continue
            handled.add(identity)
            receipt = receipts.get(identity)
            if receipt is not None and not isinstance(receipt, dict):
                raise MediaError('invalid_asset_receipt')
            if receipt and receipt.get('status') in {'prepared', 'downloaded'}:
                missing_cache = False
                try:
                    if receipt['status'] == 'prepared' or receipt.get('cache_name'):
                        _publish(vault, receipt, save)
                    else:
                        verify_asset(vault, receipt)
                    receipt.pop('error', None)
                    summary['reused'] += 1
                except (MediaError, OSError) as error:
                    _error(receipt, error)
                    missing_cache = (retry and receipt.get('status') in {'prepared', 'downloaded'}
                                     and isinstance(error, FileNotFoundError))
                    if (retry and receipt.get('status') == 'prepared' and isinstance(error, MediaError)
                            and str(error) == 'asset_cache_changed'):
                        # A partial write and a later edit are indistinguishable.
                        # Preserve these bytes and their locator; retry into a
                        # fresh leaf instead of deleting or overwriting them.
                        recovery = str(vault / CACHE_REL / _cache_path(receipt))
                        paths = list(receipt.get('recovery_paths', []))
                        if receipt.get('recovery_path') and receipt['recovery_path'] not in paths:
                            paths.append(receipt['recovery_path'])
                        if recovery not in paths:
                            paths.append(recovery)
                        receipt.update(recovery_path=recovery, recovery_paths=paths)
                        missing_cache = True
                    if not missing_cache:
                        summary['failed'] += 1
                    save()
                if not missing_cache:
                    continue
            if not item.get('url'):
                status = 'unsupported' if item.get('unsupported') else 'metadata_unavailable'
                receipts[identity] = dict(item, status=status)
                summary[status] += 1
                continue
            if receipt and receipt.get('status') in {'pending', 'failed'} and not retry:
                summary['failed'] += 1
                continue
            if budget['requests'] >= max_downloads or budget['bytes'] >= max_bytes:
                summary['deferred'] += 1
                receipts.setdefault(identity, dict(item, status='deferred'))
                continue
            recovery = {field: receipt[field] for field in ('recovery_path', 'recovery_paths')
                        if receipt and field in receipt}
            receipt = dict(item, status='pending', post_id=post['id'], **recovery)
            receipts[identity] = receipt
            save()
            try:
                result = fetch(item['url'], item['kind'], budget)
                raw = result['data']
                suffix = extension(raw, item['kind'], result.get('content_type', ''))
                folder = 'Images' if item['kind'] == 'image' else 'PDFs'
                if not isinstance(post.get('id'), str) or not re.fullmatch(r'[0-9]{1,25}', post['id']):
                    raise MediaError('invalid_asset_post_id')
                filename = 'x-' + post['id'] + '-' + identity[:24] + '.' + suffix
                cache_name = _key(identity + ':' + uuid.uuid4().hex) + '.bin'
                # Persist the exact cache destination and digest before creating
                # bytes. A crash can leave a prepared/missing file, never an
                # unindexed successful download that every retry collides with.
                receipt.update(status='prepared', path='Sources/' + folder + '/' + filename,
                               sha256=hashlib.sha256(raw).hexdigest(), size=len(raw), cache_name=cache_name,
                               final_url=result.get('final_url', item['url']),
                               retrieved_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'))
                save()
                cache = _directory(vault / CACHE_REL, create=True)
                try:
                    handle = os.open(cache_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                     0o600, dir_fd=cache)
                    with os.fdopen(handle, 'wb') as output:
                        output.write(raw)
                        output.flush()
                        os.fsync(output.fileno())
                finally:
                    os.close(cache)
                _publish(vault, receipt, save)
                summary['downloaded'] += 1
            except (MediaError, OSError, ValueError, http.client.HTTPException) as error:
                if receipt.get('status') not in {'prepared', 'downloaded'}:
                    receipt['status'] = 'failed'
                _error(receipt, error)
                summary['failed'] += 1
                save()
    save()
    summary.update(requests=budget['requests'], bytes=budget['bytes'])
    _report_recovery_paths(summary, receipts)
    return summary


def render_assets(post, receipts):
    if post.get('status', 'available') != 'available':
        return []
    lines = []
    for key in post.get('assets', []):
        receipt = receipts.get(key, {})
        if receipt.get('status') == 'downloaded' and not receipt.get('error'):
            path = _path(receipt)
            lines.append(('![[%s]]' if receipt.get('kind') == 'image' else '[[%s]]') % path)
        elif receipt.get('status') == 'unsupported':
            lines.append('Video attachment is retained in source metadata; its media file is not downloaded.')
        elif receipt.get('status') == 'metadata_unavailable':
            lines.append('Attachment unavailable locally: saved API metadata has no downloadable photo URL/type.')
        else:
            lines.append('Attachment is not available locally: download is pending, failed, or conflicts with an existing file.')
    return [line for item in lines for line in (item, '')]


def retire_assets(vault, posts, receipts, save, *, generated_notes=()):
    """Delete only digest-owned orphan assets without other vault references.

    Call after current generated account notes have dropped unavailable source
    content. Other notes (or unverified generated edits) block deletion. Files
    without a valid receipt, symlinks and changed bytes are always preserved.
    """
    active = {key for post in posts if post.get('status', 'available') == 'available'
              for key in post.get('assets', [])}
    ignored = {str(Path(path).absolute()) for path in generated_notes}
    result = {'removed': 0, 'blocked': 0}
    for key, receipt in receipts.items():
        if key in active or receipt.get('status') == 'retired':
            continue
        if not receipt.get('path'):
            recovery = {field: receipt[field] for field in ('recovery_path', 'recovery_paths')
                        if field in receipt}
            receipt.clear()
            receipt.update(key=key, status='retired', **recovery)
            save()
            continue
        receipt.pop('alt_text', None)
        try:
            relative = _path(receipt)
            name = Path(relative).name
            # A prepared receipt proves public ownership only while the cache
            # still supplies the matching publication hardlink. Check before
            # removing that proof; matching bytes at an occupied filename do
            # not establish that the collector ever published this file.
            try:
                verify_asset(vault, receipt)
                exists = True
                if receipt.get('status') == 'prepared':
                    receipt['status'] = 'downloaded'
                    save()
            except FileNotFoundError:
                exists = False
            _clear_cache(vault, receipt, save)
            check = lambda: _assert_no_references(vault, name, ignored)
            check()
            try:
                if exists:
                    _remove_owned(Path(vault) / Path(relative).parent, name, receipt['sha256'], after_remove=check)
            except FileNotFoundError:
                pass
            retained = {field: value for field, value in receipt.items()
                        if field in {'key', 'kind', 'path', 'sha256', 'size', 'post_id',
                                     'recovery_path', 'recovery_paths'}}
            receipt.clear()
            receipt.update(retained, status='retired')
            result['removed'] += 1
        except (MediaError, OSError, UnicodeError) as error:
            _error(receipt, error)
            result['blocked'] += 1
        save()
    _report_recovery_paths(result, receipts)
    return result


def _assert_no_references(vault, name, ignored):
    def traversal_failed(_error):
        raise MediaError('asset_retirement_unreadable_vault_subtree')
    for root, folders, files in os.walk(vault, followlinks=False, onerror=traversal_failed):
        if any(Path(root, folder).is_symlink() for folder in folders):
            raise MediaError('asset_retirement_unverifiable_linked_directory')
        for filename in files:
            path = Path(root, filename)
            if path.suffix.lower() not in {'.md', '.canvas'} or str(path.absolute()) in ignored:
                continue
            if path.is_symlink() or path.stat().st_size > 16 * 1024 * 1024:
                raise MediaError('asset_retirement_unverifiable_note')
            before = _snapshot(path)
            text = path.read_text(encoding='utf-8')
            if _snapshot(path) != before:
                raise MediaError('asset_retirement_note_changed')
            if path.suffix.lower() == '.canvas':
                try:
                    text = json.dumps(json.loads(text), ensure_ascii=False)
                except ValueError:
                    raise MediaError('asset_retirement_unverifiable_canvas') from None
            # A conservative basename search catches Obsidian and Markdown
            # relative/full paths, aliases, and encoded URL spelling.
            if portable_identity(name) in portable_identity(urllib.parse.unquote(text)):
                raise MediaError('asset_retirement_other_note_reference')


def run_self_test():
    import unittest

    class Tests(unittest.TestCase):
        def test_only_own_photo_and_pdf(self):
            post = {'id': '1', 'attachments': {'media_keys': ['3_1']},
                    'media': [{'media_key': '3_1', 'type': 'photo', 'url': 'https://pbs.twimg.com/media/a.jpg'},
                              {'media_key': '3_2', 'type': 'photo', 'url': 'https://pbs.twimg.com/media/b.jpg'}],
                    'entities': {'urls': [{'expanded_url': 'https://example.com/report.pdf'}]}}
            self.assertEqual([item['kind'] for item in discover_assets(post)], ['image', 'pdf'])

        def test_refuse_html(self):
            with self.assertRaises(MediaError):
                extension(b'<html>not a PDF</html>', 'pdf', 'application/pdf')

        def test_private_endpoint(self):
            self.assertFalse(_public_ip('127.0.0.1'))
            self.assertFalse(_public_ip('64:ff9b::7f00:1'))
            self.assertTrue(_public_ip('8.8.8.8'))

    result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    print(str(result.testsRun - len(result.errors) - len(result.failures)) + '/' +
          str(result.testsRun) + ' self-test cases pass')
    return result.wasSuccessful()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', action='store_true', help='run offline media helper checks')
    args = parser.parse_args(argv)
    if args.test:
        return 0 if run_self_test() else 1
    parser.print_help()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
