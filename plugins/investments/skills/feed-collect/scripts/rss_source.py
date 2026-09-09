#!/usr/bin/env python3
"""Bounded public RSS/Atom acquisition and literal, safe source rendering.

No authentication, article crawling, inference, vault writes or remote embeds.
Feed content is what the publisher supplied, never a claim of a complete article.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import html
import http.client
from html.parser import HTMLParser
import ipaddress
import queue
import re
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET

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


import feed_media

FEED_LIMIT = 8 * 1024 * 1024
ENTRY_LIMIT = 1000
NODE_LIMIT = 50000
DEPTH_LIMIT = 64
ATOM = 'http://www.w3.org/2005/Atom'
CONTENT = 'http://purl.org/rss/1.0/modules/content/'
DC = 'http://purl.org/dc/elements/1.1/'
MEDIA = 'http://search.yahoo.com/mrss/'
XML_BASE = '{http://www.w3.org/XML/1998/namespace}base'


class RSSSourceError(Exception):
    def __init__(self, message, *, requests=0):
        super().__init__(message)
        self.requests = requests


def canonical_url(value, base=None):
    """Canonical public HTTPS identity without DNS or dropping query semantics."""
    if not isinstance(value, str) or not value.strip():
        raise RSSSourceError('invalid_public_feed_url')
    value = urllib.parse.urljoin(base, value.strip()) if base else value.strip()
    if len(value) > 8192 or any(ord(char) <= 32 or ord(char) == 127 for char in value):
        raise RSSSourceError('invalid_public_feed_url')
    try:
        parts = urllib.parse.urlsplit(value)
        if (parts.scheme.lower() != 'https' or not parts.hostname
                or parts.username is not None or parts.password is not None
                or parts.port not in (None, 443) or parts.netloc.endswith(':')
                or '%' in parts.hostname):
            raise ValueError()
        host = parts.hostname.encode('idna').decode('ascii').lower()
        if host.endswith('.'):
            host = host[:-1]
        if not host or host == 'localhost' or host.endswith(('.localhost', '.local', '.internal')):
            raise ValueError()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if ('.' not in host or not re.fullmatch(r'[a-z0-9.-]+', host)
                    or any(not part or len(part) > 63 or part.startswith('-') or part.endswith('-')
                           for part in host.split('.'))
                    or re.fullmatch(r'[0-9.]+', host) or host.startswith('0x')):
                raise ValueError() from None
        else:
            if not feed_media._public_ip(str(address)):
                raise ValueError()
        authority = '[' + host + ']' if ':' in host else host
        path = urllib.parse.quote(parts.path or '/', safe="/%:@!$&'()*+,;=-._~")
        query = urllib.parse.quote(parts.query, safe="/%?:@!$&'()*+,;=-._~")
        return urllib.parse.urlunsplit(('https', authority, path, query, ''))
    except (ValueError, UnicodeError):
        raise RSSSourceError('invalid_public_feed_url') from None


def _validator(value):
    if value is None:
        return None
    if (not isinstance(value, str) or not value or len(value) > 2048
            or any(ord(char) < 32 or ord(char) > 126 for char in value)):
        raise RSSSourceError('invalid_feed_cache_validator')
    return value


def _resolve_target(url, deadline):
    """Bound a system resolver stall; a late DNS answer can never issue HTTP."""
    completed = queue.Queue(maxsize=1)

    def resolve():
        try:
            completed.put((True, feed_media._target(url)))
        except Exception as exc:
            completed.put((False, exc))

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RSSSourceError('feed_download_timeout')
    threading.Thread(target=resolve, daemon=True).start()
    try:
        success, value = completed.get(timeout=remaining)
    except queue.Empty:
        raise RSSSourceError('feed_resolver_timeout') from None
    if not success:
        raise value
    return value


def fetch_feed(url, *, etag=None, last_modified=None, max_bytes=FEED_LIMIT,
               timeout=30, max_requests=5):
    """Conditional GET through public pinned HTTPS sockets, at most five hops."""
    attempts = {'requests': 0}
    try:
        return _fetch_feed(url, etag=etag, last_modified=last_modified, max_bytes=max_bytes,
                           timeout=timeout, max_requests=max_requests, attempts=attempts)
    except RSSSourceError as exc:
        exc.requests = attempts['requests']
        raise


def _fetch_feed(url, *, etag, last_modified, max_bytes, timeout, max_requests, attempts):
    url = canonical_url(url)
    etag, last_modified = _validator(etag), _validator(last_modified)
    if (type(max_bytes) is not int or not 1 <= max_bytes <= FEED_LIMIT
            or isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not 0 < timeout <= 120 or type(max_requests) is not int or not 1 <= max_requests <= 5):
        raise RSSSourceError('invalid_feed_fetch_limits')
    deadline = time.monotonic() + timeout
    original_url = url
    visited, requests = set(), 0
    for _ in range(max_requests):
        if url in visited:
            raise RSSSourceError('feed_redirect_loop')
        visited.add(url)
        headers = {'Accept': 'application/atom+xml, application/rss+xml, application/xml, text/xml'}
        # A cache validator belongs to one resource. The caller can retain the
        # final URL and poll it directly on later runs, without forwarding an
        # old resource's validators through a changed redirect target.
        conditional = url == original_url
        if conditional and etag:
            headers['If-None-Match'] = etag
        if conditional and last_modified:
            headers['If-Modified-Since'] = last_modified
        try:
            host, path, addresses = _resolve_target(url, deadline)
            if time.monotonic() >= deadline:
                raise RSSSourceError('feed_download_timeout')
            requests += 1
            attempts['requests'] = requests
            connection, response, _wire = feed_media._request(host, path, addresses, deadline,
                                                              extra_headers=headers)
        except feed_media.MediaError as exc:
            raise RSSSourceError(str(exc)) from None
        except (OSError, ValueError, http.client.HTTPException) as exc:
            raise RSSSourceError('feed_request_failed') from exc
        try:
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader('Location')
                if not location:
                    raise RSSSourceError('feed_redirect_missing_location')
                url = canonical_url(location, url)
                continue
            new_etag = _validator(response.getheader('ETag'))
            new_modified = _validator(response.getheader('Last-Modified'))
            if response.status == 304:
                if not conditional or not (etag or last_modified):
                    raise RSSSourceError('unsolicited_feed_not_modified')
                return {'status': 'not_modified', 'final_url': url, 'etag': new_etag or etag,
                        'last_modified': new_modified or last_modified, 'body': None,
                        'requests': requests, 'bytes': 0}
            if response.status != 200:
                raise RSSSourceError('feed_http_' + str(response.status))
            if response.getheader('Content-Encoding', 'identity').lower() not in {'', 'identity'}:
                raise RSSSourceError('feed_compressed_transfer_refused')
            length = response.getheader('Content-Length')
            if length is not None and (not length.isdigit() or int(length) > max_bytes):
                raise RSSSourceError('feed_invalid_or_oversized_length')
            chunks, size = [], 0
            while True:
                if time.monotonic() >= deadline:
                    raise RSSSourceError('feed_download_timeout')
                chunk = response.read1(min(65536, max_bytes + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > max_bytes:
                    raise RSSSourceError('feed_body_too_large')
            if length is not None and size != int(length):
                raise RSSSourceError('feed_body_length_mismatch')
            return {'status': 'modified', 'final_url': url, 'etag': new_etag,
                    'last_modified': new_modified, 'body': b''.join(chunks),
                    'requests': requests, 'bytes': size}
        except (OSError, ValueError, http.client.HTTPException) as exc:
            raise RSSSourceError('feed_response_failed') from exc
        finally:
            try:
                response.close()
            finally:
                connection.close()
    raise RSSSourceError('feed_redirect_limit')


def _safe_text(value):
    value = html.escape(value, quote=False)
    value = re.sub(r'([\\`*_{}\[\]!#|^~+\-])', r'\\\1', value)
    return re.sub(r'(?m)^(\s*\d+)\.', r'\1\\.', value)


def _markdown_link(label, url):
    target = url.replace('(', '%28').replace(')', '%29')
    return '[' + label + '](' + target + ')'


def _url_or_none(value, base, diagnostics):
    try:
        if not isinstance(value, str):
            raise RSSSourceError('invalid_source_url')
        absolute = urllib.parse.urljoin(base, value.strip())
        parts = urllib.parse.urlsplit(absolute)
        if parts.scheme not in {'http', 'https'}:
            raise RSSSourceError('invalid_source_url')
        if parts.scheme == 'http':
            if parts.port not in (None, 80):
                raise RSSSourceError('invalid_source_url')
            authority = parts.netloc[:-3] if parts.netloc.endswith(':80') else parts.netloc
            transport_value = urllib.parse.urlunsplit(('https', authority, parts.path, parts.query, ''))
        else:
            transport_value = absolute
        result = canonical_url(transport_value)
        if parts.scheme == 'http':
            result = 'http:' + result[len('https:'):]
        if parts.fragment:
            result += '#' + urllib.parse.quote(parts.fragment, safe="/%?:@!$&'()*+,;=-._~")
        return result
    except (RSSSourceError, ValueError):
        diagnostics.append('unsupported_or_unsafe_url_omitted')
        return None


def _attachment(found, kind, url, alt=''):
    key = (kind, url)
    if key not in found:
        label = 'Image: ' + _safe_text(re.sub(r'\s+', ' ', alt or 'source image')) if kind == 'image' else 'PDF'
        found[key] = {'kind': kind, 'url': url, 'alt': alt,
                      'markdown': _markdown_link(label, url)}
    return found[key]['markdown']


def _HTMLTree():
    class Parser(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.root = ['root', {}, []]
            self.stack = [self.root]
            self.count = 0

        def handle_starttag(self, tag, attrs):
            self.count += 1
            if self.count > NODE_LIMIT or len(self.stack) > DEPTH_LIMIT:
                raise RSSSourceError('feed_html_structure_limit')
            node = [tag, dict(attrs), []]
            self.stack[-1][2].append(node)
            if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}:
                self.stack.append(node)

        def handle_startendtag(self, tag, attrs):
            self.handle_starttag(tag, attrs)
            self.handle_endtag(tag)

        def handle_endtag(self, tag):
            for index in range(len(self.stack) - 1, 0, -1):
                if self.stack[index][0] == tag:
                    del self.stack[index:]
                    break

        def handle_data(self, data):
            self.stack[-1][2].append(data)

    return Parser()


def _render_html(content, base, found, diagnostics):
    parser = _HTMLTree()
    parser.feed(content)
    parser.close()

    def literal(node):
        return node if isinstance(node, str) else ''.join(literal(child) for child in node[2])

    def join(parts):
        combined = ''
        for part in parts:
            if combined.endswith('\n') and part.startswith('\n'):
                combined = combined.rstrip('\n') + '\n\n' + part.lstrip('\n')
            else:
                combined += part
        return combined

    def render(node, depth=0):
        if isinstance(node, str):
            return _safe_text(re.sub(r'\s+', ' ', node))
        tag, attrs, children = node
        if tag in {'script', 'style', 'iframe', 'object', 'embed', 'form', 'input', 'button', 'svg', 'noscript'}:
            diagnostics.append('active_or_unsupported_html_omitted')
            return ''
        if tag == 'pre':
            # Indented code preserves whitespace and literal Markdown/HTML;
            # source backticks cannot close a generated fence.
            return '\n\n' + '\n'.join('    ' + line for line in literal(node).split('\n')) + '\n\n'
        if tag == 'code':
            value = literal(node).replace('\n', ' ')
            longest = max((len(match[0]) for match in re.finditer(r'`+', value)), default=0)
            delimiter = '`' * (longest + 1)
            return delimiter + ' ' + value + ' ' + delimiter
        if tag in {'ul', 'ol'}:
            try:
                ordinal = int(attrs.get('start', '1'))
            except (TypeError, ValueError):
                ordinal = 1
            lines = []
            for child in children:
                if not isinstance(child, list) or child[0] != 'li':
                    if isinstance(child, str) and not child.strip():
                        continue
                    lines.append(render(child))
                    continue
                if tag == 'ol' and child[1].get('value') is not None:
                    try:
                        ordinal = int(child[1]['value'])
                    except (TypeError, ValueError):
                        pass
                marker = str(ordinal) + '. ' if tag == 'ol' else '- '
                body = join(render(value) for value in child[2]).strip('\n').split('\n')
                lines.append(marker + body[0])
                lines.extend(' ' * len(marker) + line if line else '' for line in body[1:])
                ordinal += 1
            return '\n\n' + '\n'.join(lines) + '\n\n'
        if tag == 'table':
            rows, has_header, spans = [], False, []
            def visit(value):
                nonlocal has_header
                if not isinstance(value, list):
                    return
                if value[0] == 'tr':
                    cells = [cell for cell in value[2] if isinstance(cell, list) and cell[0] in {'td', 'th'}]
                    if any(cell[1].get('colspan', '1') != '1' or cell[1].get('rowspan', '1') != '1' for cell in cells):
                        diagnostics.append('table_spans_flattened')
                    if cells:
                        if not rows:
                            has_header = any(cell[0] == 'th' for cell in cells)
                        rows.append([render(cell).strip().replace('\n', ' ') for cell in cells])
                        spans.append([{'colspan': cell[1].get('colspan', '1'),
                                       'rowspan': cell[1].get('rowspan', '1')} for cell in cells])
                else:
                    for child in value[2]:
                        visit(child)
            visit(node)
            if not rows:
                return join(render(child) for child in children)
            if any(cell['colspan'] != '1' or cell['rowspan'] != '1' for row in spans for cell in row):
                # A guessed rectangular grid can assign a value to the wrong
                # heading. Preserve explicit source rows and span metadata.
                lines = ['Table with merged cells (source row/cell order):']
                for index, row in enumerate(rows):
                    for column, text in enumerate(row):
                        span = spans[index][column]
                        lines.append('- Row ' + str(index + 1) + ', cell ' + str(column + 1)
                                     + ' (colspan ' + _safe_text(span['colspan']) + ', rowspan '
                                     + _safe_text(span['rowspan']) + '): ' + text)
                return '\n\n' + '\n'.join(lines) + '\n\n'
            width = max(map(len, rows))
            if not has_header:
                rows.insert(0, [''] * width)
            padded = [row + [''] * (width - len(row)) for row in rows]
            lines = ['| ' + ' | '.join(row) + ' |' for row in padded]
            lines.insert(1, '| ' + ' | '.join(['---'] * width) + ' |')
            return '\n\n' + '\n'.join(lines) + '\n\n'
        inner = join(render(child, depth + (tag in {'ul', 'ol'})) for child in children)
        if tag == 'img':
            if (attrs.get('width') in {'0', '1'} and attrs.get('height') in {'0', '1'}):
                diagnostics.append('tracking_sized_image_omitted')
                return ''
            if re.search(r'(?:^|/)missing-image\.[a-z0-9]+(?:[?#]|$)', attrs.get('src') or '', re.IGNORECASE):
                diagnostics.append('unavailable_source_image_placeholder')
                return 'Source image unavailable.'
            url = _url_or_none(attrs.get('src'), base, diagnostics)
            if url and not url.startswith('https:'):
                diagnostics.append('http_image_not_archived')
                return _markdown_link('Image: ' + _safe_text(attrs.get('alt') or 'source image'), url)
            return _attachment(found, 'image', url, attrs.get('alt') or '') if url else ''
        if tag == 'a':
            url = _url_or_none(attrs.get('href'), base, diagnostics)
            if not url:
                return inner
            if url.startswith('https:') and urllib.parse.unquote(urllib.parse.urlsplit(url).path).lower().endswith('.pdf'):
                _attachment(found, 'pdf', url)
            # Image labels already contain a safe link; avoid nesting links.
            return inner if any(isinstance(child, list) and child[0] == 'img' for child in children) else _markdown_link(inner.strip() or _safe_text(url), url)
        if tag in {'strong', 'b'}:
            return '**' + inner + '**' if inner.strip() else inner
        if tag in {'em', 'i'}:
            return '*' + inner + '*' if inner.strip() else inner
        if tag in {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}:
            return '\n\n' + '#' * min(6, int(tag[1]) + 2) + ' ' + inner.strip() + '\n\n'
        if tag == 'br':
            return '  \n'
        if tag == 'blockquote':
            quoted = inner.strip('\n')
            return '\n\n' + '\n'.join('> ' + line if line else '>' for line in quoted.split('\n')) + '\n\n'
        if tag == 'li':
            return '\n' + '  ' * max(0, depth - 1) + '- ' + inner.strip() + '\n'
        if tag in {'p', 'div', 'section', 'article', 'header', 'footer', 'hr', 'dl', 'dt', 'dd'}:
            return '\n\n' + inner.strip('\n') + '\n\n'
        return inner

    rendered = render(parser.root)
    return rendered.strip('\n')


def _date(value, diagnostics, field):
    if not value or not value.strip():
        return None
    try:
        try:
            parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
        except ValueError:
            parsed = parsedate_to_datetime(value.strip())
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    except (TypeError, ValueError, OverflowError):
        diagnostics.append('invalid_' + field)
        return None


def _text(element):
    return ''.join(element.itertext()).strip() if element is not None else ''


def _first(parent, names):
    return next((element for element in parent if element.tag in names), None)


def _authors(parent, atom=False):
    values = []
    for child in parent:
        if child.tag == '{' + ATOM + '}author' and atom:
            value = _text(child.find('{' + ATOM + '}name'))
        elif child.tag in {'author', '{' + DC + '}creator'} and not atom:
            value = _text(child)
        else:
            continue
        if value and value not in values:
            values.append(value)
    return values


def _base_map(root, initial):
    result, count = {}, 0
    def walk(node, base, depth):
        nonlocal count
        count += 1
        if count > NODE_LIMIT or depth > DEPTH_LIMIT:
            raise RSSSourceError('feed_xml_structure_limit')
        result[node] = urllib.parse.urljoin(base, node.get(XML_BASE, ''))
        for child in node:
            walk(child, result[node], depth + 1)
    walk(root, initial, 0)
    return result


def _BoundedXML():
    class Parser(ET.TreeBuilder):
        def __init__(self):
            super().__init__()
            self.count = 0
            self.depth = 0

        def start(self, tag, attrs):
            self.count += 1
            self.depth += 1
            if self.count > NODE_LIMIT or self.depth > DEPTH_LIMIT:
                raise RSSSourceError('feed_xml_structure_limit')
            return super().start(tag, attrs)

        def end(self, tag):
            self.depth -= 1
            return super().end(tag)

        def doctype(self, name, pubid, system):
            raise RSSSourceError('feed_dtd_or_entity_forbidden')

    return Parser()


def _fragment(node, bases=None):
    """Semantic XML fragment with local XHTML names for the HTML renderer."""
    def serialize(element):
        tag = element.tag.rsplit('}', 1)[-1]
        attrs = ''.join(' ' + key.rsplit('}', 1)[-1] + '="' + html.escape(
                           urllib.parse.urljoin(bases[element], value)
                           if bases and key in {'href', 'src'} else value, quote=True) + '"'
                        for key, value in element.attrib.items() if key != XML_BASE)
        return ('<' + tag + attrs + '>' + html.escape(element.text or '')
                + ''.join(serialize(child) + html.escape(child.tail or '') for child in element)
                + '</' + tag + '>')
    return (node.text or '') + ''.join(serialize(child) + html.escape(child.tail or '') for child in node)


def parse_feed(raw, feed_url):
    """Parse RSS 2.0 or Atom; return literal source entries, never follow links."""
    feed_url = canonical_url(feed_url)
    if not isinstance(raw, bytes) or not raw or len(raw) > FEED_LIMIT:
        raise RSSSourceError('invalid_or_oversized_feed_body')
    # Removing NULs also catches UTF-16/32 declarations before XML expansion.
    if re.search(br'<!\s*(?:DOCTYPE|ENTITY)\b', raw.replace(b'\x00', b''), re.IGNORECASE):
        raise RSSSourceError('feed_dtd_or_entity_forbidden')
    try:
        root = ET.fromstring(raw, parser=ET.XMLParser(target=_BoundedXML()))
    except (ET.ParseError, ValueError, LookupError):
        raise RSSSourceError('invalid_feed_xml') from None
    bases = _base_map(root, feed_url)
    atom = root.tag == '{' + ATOM + '}feed'
    if atom:
        channel, entry_tag, title_tag = root, '{' + ATOM + '}entry', '{' + ATOM + '}title'
    elif root.tag == 'rss' and root.get('version') == '2.0' and root.find('channel') is not None:
        channel, entry_tag, title_tag = root.find('channel'), 'item', 'title'
    else:
        raise RSSSourceError('unsupported_feed_format')
    entries = list(channel.findall(entry_tag))
    if len(entries) > ENTRY_LIMIT:
        raise RSSSourceError('feed_entry_limit')
    diagnostics, items = [], []
    authors = _authors(channel, atom)

    def entry_url(element, errors):
        if atom:
            links = [child for child in element if child.tag == '{' + ATOM + '}link'
                     and child.get('rel', 'alternate') == 'alternate']
            links.sort(key=lambda child: child.get('type') not in (None, 'text/html', 'application/xhtml+xml'))
            candidates = [(child.get('href'), bases[child]) for child in links]
        else:
            link = element.find('link')
            guid = element.find('guid')
            candidates = [(link.text, bases[link])] if link is not None and link.text else []
            if guid is not None and guid.get('isPermaLink', 'true').lower() != 'false' and guid.text:
                candidates.append((guid.text, bases[guid]))
        for value, base in candidates:
            try:
                return canonical_url(value, base)
            except RSSSourceError:
                continue
        errors.append('canonical_url_unavailable')
        return None

    site_url = entry_url(channel, [])
    for index, entry in enumerate(entries):
        errors = []
        url = entry_url(entry, errors)
        if url is None:
            diagnostics.append('entry_' + str(index + 1) + ':canonical_url_unavailable')
            continue
        identity = _text(entry.find('{' + ATOM + '}id' if atom else 'guid')) or None
        title = _text(entry.find(title_tag))
        published = _date(_text(_first(entry, ('{' + ATOM + '}published',) if atom else ('pubDate', '{' + DC + '}date'))), errors, 'published_at')
        updated = _date(_text(entry.find('{' + ATOM + '}updated')), errors, 'updated_at')
        if not published and not updated:
            errors.append('publication_date_unavailable')
        full = _first(entry, ('{' + ATOM + '}content',) if atom else ('{' + CONTENT + '}encoded',))
        summary = entry.find('{' + ATOM + '}summary' if atom else 'description')
        if full is not None and full.get('src'):
            errors.append('external_content_not_fetched')
            full = None
        content_node = full if full is not None else summary
        scope = 'feed_content' if full is not None else 'summary_only'
        content_type = content_node.get('type', 'text') if atom and content_node is not None else 'html'
        if content_type in {'text/html', 'html'}:
            content_type = 'html'
        elif content_type in {'application/xhtml+xml', 'xhtml'}:
            content_type = 'xhtml'
        elif content_type in {'text', 'text/plain'}:
            content_type = 'text'
        else:
            errors.append('unsupported_content_type_rendered_as_text')
            content_type = 'text'
        if content_node is None:
            content = ''
            errors.append('feed_content_unavailable')
        elif len(content_node):
            content = _fragment(content_node, bases)
            errors.append('xml_content_fragment_serialized')
        else:
            content = content_node.text or ''
        found = {}
        content_base = bases[content_node] if content_node is not None else bases[entry]
        markdown = (_render_html(content, content_base, found, errors)
                    if content_type in {'html', 'xhtml'} else _safe_text(content))
        for child in entry.iter():
            if child.tag in {'enclosure', '{' + ATOM + '}link'}:
                if child.tag != 'enclosure' and child.get('rel') != 'enclosure':
                    continue
                target, mime = child.get('url', child.get('href')), child.get('type', '')
            elif child.tag == '{' + MEDIA + '}thumbnail':
                errors.append('media_thumbnail_not_archived')
                continue
            elif child.tag == '{' + MEDIA + '}content':
                target, mime = child.get('url'), child.get('type', '')
                if child.get('medium') == 'image':
                    mime = 'image/'
            else:
                continue
            asset_url = _url_or_none(target, bases[child], errors)
            if not asset_url:
                continue
            if not asset_url.startswith('https:'):
                errors.append('http_attachment_not_archived')
                continue
            kind = ('image' if mime.startswith('image/') else 'pdf'
                    if mime == 'application/pdf' or urllib.parse.unquote(urllib.parse.urlsplit(asset_url).path).lower().endswith('.pdf') else None)
            if kind:
                token = _attachment(found, kind, asset_url)
                if token not in markdown:
                    markdown += '\n\n' + token
        items.append({'id': hashlib.sha256(url.encode('utf-8')).hexdigest(), 'canonical_url': url,
                      'guid': identity, 'title': title, 'authors': _authors(entry, atom) or authors,
                      'published_at': published, 'updated_at': updated, 'content': content,
                      'content_type': content_type, 'content_scope': scope, 'markdown': markdown.strip('\n'),
                      'attachments': list(found.values()), 'diagnostics': sorted(set(errors))})
    return {'format': 'atom' if atom else 'rss2', 'feed_url': feed_url,
            'title': _text(channel.find(title_tag)), 'site_url': site_url, 'authors': authors,
            'items': items, 'diagnostics': diagnostics}


def run_self_test():
    import unittest

    class SourceTests(unittest.TestCase):
        def test_rss(self):
            raw = b'<rss version="2.0"><channel><title>Test</title><item><link>https://example.com/a</link><description>Text</description></item></channel></rss>'
            item = parse_feed(raw, 'https://example.com/feed')['items'][0]
            self.assertEqual(item['content_scope'], 'summary_only')
            self.assertIn('publication_date_unavailable', item['diagnostics'])

        def test_dtd(self):
            with self.assertRaises(RSSSourceError):
                parse_feed(b'<!DOCTYPE rss [<!ENTITY x "unsafe">]><rss/>', 'https://example.com/feed')

        def test_safe_render(self):
            attachments, diagnostics = {}, []
            result = _render_html('<h1>Header</h1><p>![[bad]]</p><img src="/photo.png"><script>bad()</script>',
                                  'https://example.com/feed', attachments, diagnostics)
            self.assertIn('### Header', result)
            self.assertNotIn('![[', result)
            self.assertNotIn('bad()', result)
            self.assertEqual(len(attachments), 1)

        def test_canonical(self):
            self.assertEqual(canonical_url('HTTPS://EXAMPLE.COM:443/a?q=1#section'), 'https://example.com/a?q=1')
            with self.assertRaises(RSSSourceError):
                canonical_url('https://127.0.0.1/feed')

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(SourceTests)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    passed = result.testsRun - len(result.errors) - len(result.failures)
    print(str(passed) + '/' + str(result.testsRun) + ' self-test cases pass')
    return result.wasSuccessful()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', action='store_true', help='Run offline self-tests')
    args = parser.parse_args()
    if args.test:
        return 0 if run_self_test() else 1
    parser.error('this parser is imported by feed collection; use --test for validation')


if __name__ == '__main__':
    raise SystemExit(main())
