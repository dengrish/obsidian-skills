#!/usr/bin/env python3
"""Public RSS collection; offline publish repairs owned views while preserving archived evidence."""
from __future__ import annotations

import argparse
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import posixpath
import re
import shutil
import stat
import sys
import tempfile
import uuid
from urllib.parse import quote, urlsplit

_OBSIDIAN_SHARED_MODULES = ('atomic_move', 'note_provenance', 'portable_names', 'slugify')

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

import feed_collect as common
import feed_media
import rss_source
from slugify import SlugError, slug_stem

class RSSError(ValueError):
    pass
STATE_REL = 'Investments/Sources/.rss-collect'
ROSTER_REL = 'Investments/rss-feeds.md'
OUTPUT_REL = 'Investments/Sources/RSS'
HASH = re.compile(r'[0-9a-f]{64}\Z')
ARTICLE = re.compile(r'rss:([0-9a-f]{64})\Z')
EVIDENCE = re.compile(r'rss:([0-9a-f]{64})@([0-9a-f]{64})\Z')


def now():
    return common.now()


def file_label(text):
    try:
        return slug_stem(text[:70])[:70].rstrip('-')
    except SlugError:
        return 'publication'  # The stable identity suffix disambiguates any label.


def article_id(url):
    return 'rss:' + common.digest(rss_source.canonical_url(url).encode('utf-8'))


def roster(vault):
    """Missing RSS configuration is a no-op, independent of the X roster."""
    path = Path(vault) / ROSTER_REL
    try:
        fd = common.safe_dir(path.parent)
    except FileNotFoundError:
        return []
    try:
        raw = common.read_at(fd, path.name, optional=True)
    finally:
        os.close(fd)
    if raw is None:
        return []
    result, seen, fence, comment = [], set(), None, False
    for line in raw.decode('utf-8').splitlines():
        if comment:
            comment = '-->' not in line
            continue
        if fence is None and line.lstrip().startswith('<!--'):
            comment = '-->' not in line
            continue
        marker = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if marker:
            if fence is None:
                fence = marker[1]
            elif marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                fence = None
            continue
        if fence or not re.match(r'^ {0,3}- \[[ xX]\]', line):
            continue
        match = re.fullmatch(r' {0,3}- \[([ xX])\] (https://\S+?)(?:\s+[—–-]\s+[^<>]*)?\s*', line)
        if not match:
            raise RSSError('malformed_rss_feed_entry')
        url = rss_source.canonical_url(match[2])
        if url in seen:
            raise RSSError('duplicate_rss_feed_entry')
        seen.add(url)
        if match[1].lower() == 'x':
            result.append(url)
    if len(result) > 100:
        raise RSSError('too_many_rss_feeds')
    return result


def safe_relative(value, prefix):
    if not isinstance(value, str):
        raise RSSError('invalid_rss_owned_path')
    path = Path(value)
    if path.is_absolute() or '..' in path.parts or not value.startswith(prefix + '/') or str(path) != value:
        raise RSSError('invalid_rss_owned_path')
    return path


def semantic(item):
    result = {key: item.get(key) for key in ('canonical_url', 'title', 'authors', 'published_at',
            'updated_at', 'content', 'content_type', 'content_scope', 'markdown', 'attachments', 'diagnostics')}
    # The absent discriminator is the original immutable evidence contract.
    # New rendering metadata is protected by the new revision's own digest.
    if 'rendering_version' in item:
        result.update(rendering_version=item['rendering_version'], render_base=item.get('render_base'))
    if 'linked_media' in item:
        result['linked_media'] = item['linked_media']
    return result


def source_signature(item):
    """Compare supplied source material independently of a renderer upgrade."""
    result = {key: item.get(key) for key in ('canonical_url', 'title', 'authors', 'published_at',
              'updated_at', 'content', 'content_type', 'content_scope')}
    if item.get('content_type') in {'html', 'xhtml'}:
        result['content'] = rss_source.stable_embed_content(result['content'])
    result['attachments'] = sorted({(row['kind'], row['url']) for row in item['attachments']})
    result['linked_media'] = item.get('linked_media', [])
    return common.digest(common.encoded(result))


def same_source(first, second):
    # Legacy records did not save xml:base. Do not invent a source change merely
    # because the updated parser now records that rendering context.
    return (source_signature(first) == source_signature(second)
            and (not first.get('render_base') or not second.get('render_base')
                 or first['render_base'] == second['render_base']))


def observed_content(version, observation, spans=None):
    """Reconstruct an exact display-only observation from its immutable base."""
    content = version['content']
    patch = observation.get('display_content')
    if patch is None:
        return content
    spans = rss_source.embedded_age_spans(content) if spans is None else spans
    if (not isinstance(patch, dict) or set(patch) != {'sha256', 'age_labels'}
            or not isinstance(patch['sha256'], str) or not HASH.fullmatch(patch['sha256'])
            or not isinstance(patch['age_labels'], list) or len(patch['age_labels']) != len(spans)
            or not spans or any(not isinstance(label, str) or not re.fullmatch(rss_source.EMBEDDED_AGE, label)
                                for label in patch['age_labels'])):
        raise RSSError('invalid_rss_display_observation')
    for (start, end), label in reversed(list(zip(spans, patch['age_labels']))):
        content = content[:start] + label + content[end:]
    if common.digest(content.encode('utf-8')) != patch['sha256']:
        raise RSSError('rss_display_observation_digest_mismatch')
    return content


def current_display_version(entry, version):
    """Only the maintained view uses later display labels; evidence stays fixed."""
    observation = next((row for row in reversed(entry.get('observations', []))
                        if row['revision_sha256'] == version['revision_sha256']), {})
    return dict(version, content=observed_content(version, observation))


def semantic_hash(item):
    return common.digest(common.encoded(semantic(item)))


def revision_hash(item):
    previous = item.get('previous_revision_sha256')
    return common.digest(common.encoded({'semantic_sha256': semantic_hash(item),
        'previous_revision_sha256': previous, 'source_feed_id': item.get('source_feed_id')}))


def validate_receipt(receipt):
    if not isinstance(receipt, dict):
        raise RSSError('invalid_rss_publication_receipt')
    for key in ('published_sha256', 'prepared_sha256'):
        if receipt.get(key) is not None and (not isinstance(receipt[key], str) or not HASH.fullmatch(receipt[key])):
            raise RSSError('invalid_rss_publication_receipt')
    if 'provenance' in receipt:
        payload = receipt['provenance']
        if not isinstance(payload, dict) or payload.get('schema') != 1 or 'generated_by' not in payload:
            raise RSSError('invalid_rss_provenance')
        for key in ('generated_by', 'updated_by'):
            if key in payload:
                common.note_provenance.validate_record(payload[key])


def validate(data):
    if (not isinstance(data, dict) or data.get('schema') != 1 or not isinstance(data.get('feeds'), dict)
            or not isinstance(data.get('articles'), dict) or not isinstance(data.get('assets'), dict)
            or 'pending' not in data):
        raise RSSError('invalid_rss_state')
    for identity, feed in data['feeds'].items():
        if (not HASH.fullmatch(identity) or not isinstance(feed, dict)
                or common.digest(feed['url'].encode('utf-8')) != identity
                or rss_source.canonical_url(feed['url']) != feed['url'] or not isinstance(feed.get('guids'), dict)):
            raise RSSError('invalid_rss_feed_identity')
        safe_relative(feed['index_relative'], OUTPUT_REL)
        validate_receipt(feed)
        if not isinstance(feed.get('observations'), list):
            raise RSSError('invalid_rss_feed_observations')
        for observation in feed['observations']:
            common.timestamp(observation.get('observed_at'))
            if observation.get('status') not in {'modified', 'not_modified', 'failed'}:
                raise RSSError('invalid_rss_feed_observations')
        for target in feed['guids'].values():
            if target not in data['articles']:
                raise RSSError('rss_guid_missing_article')
        for key in ('etag', 'last_modified'):
            value = feed.get(key)
            if value is not None and (not isinstance(value, str) or len(value) > 4096 or '\r' in value or '\n' in value):
                raise RSSError('invalid_rss_http_validator')
    for identity, entry in data['articles'].items():
        if (not ARTICLE.fullmatch(identity) or not isinstance(entry, dict)
                or article_id(entry['canonical_url']) != identity or entry['feed_id'] not in data['feeds']
                or not isinstance(entry.get('versions'), list) or not entry['versions']):
            raise RSSError('invalid_rss_article_identity')
        safe_relative(entry['note_relative'], OUTPUT_REL)
        validate_receipt(entry)
        if (not isinstance(entry.get('feed_ids'), list) or not entry['feed_ids']
                or entry['feed_id'] not in entry['feed_ids'] or any(source not in data['feeds'] for source in entry['feed_ids'])):
            raise RSSError('invalid_rss_article_sources')
        common.timestamp(entry['first_retrieved_at'])
        previous = None
        previous_hash = None
        hashes = set()
        for version in entry['versions']:
            rendering_version = version.get('rendering_version', 1)
            if (type(rendering_version) is not int or rendering_version not in {1, 2}
                    or rendering_version == 2 and (not isinstance(version.get('render_base'), str)
                        or not version['render_base'] or len(version['render_base']) > 8192
                        or any(ord(character) < 32 for character in version['render_base']))):
                raise RSSError('unsupported_rss_evidence_rendering')
            linked_media = version.get('linked_media', [])
            if (not isinstance(linked_media, list) or any(not isinstance(row, dict)
                    or set(row) != {'url', 'media_type', 'mime_type'} or row['media_type'] != 'video'
                    or not isinstance(row['mime_type'], str) or len(row['mime_type']) > 256
                    or any(ord(character) < 32 for character in row['mime_type'])
                    or not isinstance(row['url'], str)
                    or rss_source._url_or_none(row['url'], entry['canonical_url'], []) != row['url']
                    for row in linked_media)):
                raise RSSError('invalid_rss_linked_media')
            if (version.get('revision_sha256') != revision_hash(version)
                    or version.get('semantic_sha256') != semantic_hash(version)
                    or version.get('previous_revision_sha256') != previous_hash
                    or version.get('source_feed_id') not in data['feeds']
                    or version.get('source_feed_url') != data['feeds'][version['source_feed_id']]['url']
                    or version['revision_sha256'] in hashes or version.get('canonical_url') != entry['canonical_url']
                    or not isinstance(version.get('markdown'), str) or not isinstance(version.get('content'), str)
                    or not isinstance(version.get('authors'), list) or not isinstance(version.get('attachments'), list)
                    or version.get('content_scope') not in {'feed_content', 'summary_only'}):
                raise RSSError('invalid_rss_revision')
            observed = common.instant(version['observed_at'])
            if previous is not None and observed < previous:
                raise RSSError('rss_revision_time_reversed')
            previous = observed
            previous_hash = version['revision_sha256']
            hashes.add(version['revision_sha256'])
            safe_relative(version['archive_relative'], STATE_REL + '/revisions')
            validate_receipt(version.get('archive_receipt'))
            if version['archive_relative'] != STATE_REL + '/revisions/' + identity[4:] + '/' + version['revision_sha256'] + '.md':
                raise RSSError('rss_revision_archive_identity_mismatch')
            for key in ('published_at', 'updated_at', 'archive_published_at'):
                if version.get(key) is not None:
                    common.timestamp(version[key])
        by_revision = {version['revision_sha256']: version for version in entry['versions']}
        span_cache = {}
        for observation in entry.get('observations', []):
            common.timestamp(observation.get('observed_at'))
            version = by_revision.get(observation.get('revision_sha256'))
            if version is None or common.instant(observation['observed_at']) < common.instant(version['observed_at']):
                raise RSSError('invalid_rss_article_observation')
            if 'display_content' in observation:
                signature = version['revision_sha256']
                if signature not in span_cache:
                    span_cache[signature] = rss_source.embedded_age_spans(version['content'])
                observed_content(version, observation, span_cache[signature])
    for identity, asset in data['assets'].items():
        if (not HASH.fullmatch(identity) or not isinstance(asset, dict) or asset.get('kind') not in {'image', 'pdf'}
                or asset.get('status') not in {'pending', 'prepared', 'downloaded', 'failed', 'deferred'}):
            raise RSSError('invalid_rss_asset')
        if asset.get('path'):
            safe_relative(asset['path'], 'Sources/Images' if asset['kind'] == 'image' else 'Sources/PDFs')
        if asset.get('cache_name') and not re.fullmatch(r'[0-9a-f]{64}\.bin', asset['cache_name']):
            raise RSSError('invalid_rss_asset_cache')
        if 'publication_receipt' in asset:
            validate_receipt(asset['publication_receipt'])
        if asset.get('status') in {'prepared', 'downloaded'}:
            if not isinstance(asset.get('sha256'), str) or not HASH.fullmatch(asset['sha256']):
                raise RSSError('invalid_rss_asset_digest')
            common.timestamp(asset.get('retrieved_at'))
    if data['pending'] is not None and (not isinstance(data['pending'], dict)
            or data['pending'].get('feed_id') not in data['feeds'] or not isinstance(data['pending'].get('parsed'), dict)):
        raise RSSError('invalid_rss_pending_response')
    return data


def Store(vault, create=False):
    class RSSStore(common.Store):
        """Reuse the existing guarded state writer with an independent locked journal."""
        def __init__(self, vault, create=False):
            self.path = Path(vault) / STATE_REL
            self.fd = common.safe_dir(self.path, create)
            self.lock, self.expected = None, None
            try:
                info = os.fstat(self.fd)
                if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                    raise RSSError('rss_state_directory_must_be_private')
                common.check_spelling(self.fd, 'collector.lock')
                try:
                    self.lock = os.open('collector.lock', os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                        0o600, dir_fd=self.fd)
                    fresh = True
                except FileExistsError:
                    fresh = False
                    self.lock = os.open('collector.lock', os.O_RDWR | os.O_NOFOLLOW, dir_fd=self.fd)
                info = os.fstat(self.lock)
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid()
                        or stat.S_IMODE(info.st_mode) != 0o600):
                    raise RSSError('unsafe_rss_lock')
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with common.anchored_cwd(self.fd):
                    try:
                        self.expected = common.atomic_move.regular_file_snapshot('state.json')
                    except FileNotFoundError:
                        pass
                raw = common.read_at(self.fd, 'state.json', optional=True)
                if raw is None and not fresh:
                    raise RSSError('missing_rss_state_requires_recovery')
                if (raw is None) != (self.expected is None) or (raw is not None and (
                        self.expected.mode != 0o600 or self.expected.digest != common.digest(raw))):
                    raise RSSError('rss_state_changed_during_open')
                self.data = validate(common.decode(raw)) if raw is not None else {
                    'schema': 1, 'feeds': {}, 'articles': {}, 'assets': {}, 'pending': None}
                if raw is None:
                    self.save()
            except Exception:
                self.close()
                raise

        def save(self):
            validate(self.data)
            super().save()
    return RSSStore(vault, create)


def read_state(vault):
    try:
        fd = common.safe_dir(Path(vault) / STATE_REL)
    except FileNotFoundError:
        return None
    try:
        if stat.S_IMODE(os.fstat(fd).st_mode) != 0o700 or os.fstat(fd).st_uid != os.getuid():
            raise RSSError('rss_state_directory_must_be_private')
        with common.anchored_cwd(fd):
            expected = common.atomic_move.regular_file_snapshot('state.json') if os.path.lexists('state.json') else None
        if expected is not None and expected.mode != 0o600:
            raise RSSError('rss_state_file_must_be_private')
        raw = common.read_at(fd, 'state.json', optional=True)
        if raw is None and common.read_at(fd, 'collector.lock', optional=True) is not None:
            raise RSSError('missing_rss_state_requires_recovery')
        if (raw is None) != (expected is None) or raw is not None and common.digest(raw) != expected.digest:
            raise RSSError('rss_state_changed_during_read')
        return validate(common.decode(raw)) if raw is not None else None
    finally:
        os.close(fd)


def read_owned(vault, relative, expected=None):
    path = Path(vault) / relative
    try:
        fd = common.safe_dir(path.parent)
    except FileNotFoundError:
        return None
    try:
        raw = common.read_at(fd, path.name, optional=True)
        if raw is not None and expected is not None and common.digest(raw) != expected:
            raise RSSError('rss_ownership_or_edit_conflict')
        return raw
    finally:
        os.close(fd)


def guarded_publish(store, vault, relative, raw, owner, *, immutable=False):
    """Journal intended bytes before the same-filesystem guarded publication."""
    target = Path(vault) / relative
    fd = common.safe_dir(target.parent, create=True)
    try:
        with common.anchored_cwd(fd):
            expected = common.atomic_move.regular_file_snapshot(target.name) if os.path.lexists(target.name) else None
            old = common.read_at(fd, target.name, optional=True)
            if ((old is None) != (expected is None) or old is not None and common.digest(old) != expected.digest):
                raise RSSError('rss_publication_changed_during_read')
            allowed = {owner.get('published_sha256'), owner.get('prepared_sha256')}
            if old is not None and common.digest(old) not in allowed:
                raise RSSError('rss_ownership_or_edit_conflict')
            if old == raw:
                if common.atomic_move.regular_file_snapshot(target.name) != expected:
                    raise RSSError('rss_publication_changed_before_closeout')
                owner.update(published_sha256=common.digest(raw))
                owner.pop('prepared_sha256', None)
                store.save()
                return False
            if immutable and old is not None:
                raise RSSError('rss_immutable_revision_conflict')
            if not hasattr(store, 'record'):
                store.record = common.provenance()
            record = store.record
            provenance = owner.setdefault('provenance', {'schema': 1, 'generated_by': record})
            if old is not None:
                provenance['updated_by'] = record
            owner['prepared_sha256'] = common.digest(raw)
            store.save()
            stage = tempfile.mkdtemp(prefix='.rss-stage-', dir='..')
            keep = False
            try:
                staged = Path(stage) / 'payload'
                with staged.open('xb') as output:
                    common.atomic_move.set_private_mode(output.fileno(), expected.mode if expected else 0o600)
                    output.write(raw)
                    output.flush()
                    os.fsync(output.fileno())
                if expected is None:
                    published = common.atomic_move.publish_new(staged, target.name,
                                common.atomic_move.regular_file_snapshot, '..')
                else:
                    published = common.atomic_move.replace_expected(staged, target.name, expected,
                                common.atomic_move.regular_file_snapshot, stage, '..')
                if published.digest != common.digest(raw) or common.atomic_move.regular_file_snapshot(target.name) != published:
                    raise RSSError('rss_publication_verification_failed')
                os.fsync(fd)
            except Exception as exc:
                keep = True
                raise RSSError('rss_publication_conflict; preserved_recovery=' + str(
                    Path(getattr(exc, 'recovery_path', None) or stage).absolute())) from None
            finally:
                if not keep:
                    shutil.rmtree(stage)
            owner['published_sha256'] = common.digest(raw)
            owner.pop('prepared_sha256', None)
            store.save()
            return True
    finally:
        os.close(fd)


def feed_identity(url):
    return common.digest(url.encode('utf-8'))


def ensure_feed(store, url):
    identity = feed_identity(url)
    if identity not in store.data['feeds']:
        folder = OUTPUT_REL + '/' + file_label(url.split('/')[2]) + '-' + identity[:12]
        store.data['feeds'][identity] = {'url': url, 'title': url.split('/')[2], 'authors': [],
            'guids': {}, 'index_relative': folder + '/index.md', 'observations': [],
            'etag': None, 'last_modified': None, 'created': now()[:10]}
        store.save()
    return identity


def apply_pending(store):
    pending = store.data['pending']
    if pending is None:
        return {'new_articles': 0, 'new_revisions': 0, 'issues': []}
    updated = deepcopy(store.data)
    feed = updated['feeds'][pending['feed_id']]
    parsed, observed = pending['parsed'], pending['observed_at']
    common.timestamp(observed)
    result = {'new_articles': 0, 'new_revisions': 0, 'issues': []}
    seen = set()
    representations = {}
    for item in parsed['items']:
        # Known bases distinguish competing representations in this response;
        # cross-version comparison separately accommodates legacy absent bases.
        representations.setdefault(article_id(item['canonical_url']), set()).add(
            (source_signature(item), item.get('render_base'), common.digest(item['content'].encode('utf-8'))))
    ambiguous = {identity for identity, variants in representations.items() if len(variants) > 1}
    for item in parsed['items']:
        identity = article_id(item['canonical_url'])
        content_signature = semantic_hash(item)
        if identity in ambiguous:
            if identity not in seen:
                result['issues'].append({'reason': 'ambiguous_duplicate_rss_article', 'article_id': identity})
            seen.add(identity)
            continue
        guid = item.get('guid')
        if guid and guid in feed['guids'] and feed['guids'][guid] != identity:
            result['issues'].append({'reason': 'rss_guid_rebound_to_different_article', 'article_id': identity})
            continue
        if identity in seen:
            if guid:
                feed['guids'][guid] = identity
            continue
        seen.add(identity)
        entry = updated['articles'].get(identity)
        if entry and entry['feed_id'] != pending['feed_id']:
            entry.setdefault('feed_ids', [entry['feed_id']])
            if pending['feed_id'] not in entry['feed_ids']:
                entry['feed_ids'].append(pending['feed_id'])
            if guid:
                feed['guids'][guid] = identity
            active = getattr(store, 'active_feed_ids', set(updated['feeds']))
            if entry['feed_id'] not in active and pending['feed_id'] in active:
                entry['feed_id'] = pending['feed_id']  # Explicitly enabled source; note path stays stable.
            else:
                if not any(same_source(item, version) for version in entry['versions']):
                    result['issues'].append({'reason': 'secondary_feed_variant_not_applied', 'article_id': identity})
                continue  # Competing feeds never oscillate the primary source's text.
        if entry is None:
            path = str(Path(feed['index_relative']).parent / (file_label(item['title']) + '-' + identity[4:16] + '.md'))
            entry = {'canonical_url': item['canonical_url'], 'feed_id': pending['feed_id'],
                     'feed_ids': [pending['feed_id']],
                     'note_relative': path, 'first_retrieved_at': observed, 'versions': []}
            updated['articles'][identity] = entry
            result['new_articles'] += 1
        if guid:
            feed['guids'][guid] = identity
        if not entry['versions'] or not same_source(entry['versions'][-1], item):
            # Deterministic predecessor identity distinguishes A→B→A from an
            # unchanged poll, without using observation time in evidence IDs.
            version = {**semantic(item), 'observed_at': observed, 'semantic_sha256': content_signature,
                       'previous_revision_sha256': entry['versions'][-1]['revision_sha256'] if entry['versions'] else None,
                       'source_feed_id': pending['feed_id'], 'source_feed_url': feed['url'],
                       'archive_receipt': {}, 'publication': parsed.get('title') or feed['title']}
            signature = revision_hash(version)
            version.update(revision_sha256=signature,
                           archive_relative=STATE_REL + '/revisions/' + identity[4:] + '/' + signature + '.md')
            entry['versions'].append(version)
            result['new_revisions'] += 1
        signature = entry['versions'][-1]['revision_sha256']
        observation = {'observed_at': observed, 'revision_sha256': signature}
        version = entry['versions'][-1]
        if item['content'] != version['content']:
            # The comparison accepted only recognized generated age labels.
            # Save exact observation bytes as small, verified replacements;
            # never rewrite the original revision or duplicate its media set.
            observation['display_content'] = {
                'sha256': common.digest(item['content'].encode('utf-8')),
                'age_labels': [item['content'][start:end]
                               for start, end in rss_source.embedded_age_spans(item['content'])]}
            if observed_content(version, observation) != item['content']:
                raise RSSError('rss_display_observation_not_reconstructible')
        entry.setdefault('observations', []).append(observation)
    previous = feed.get('current_article_ids', [])
    overlap = bool(set(previous) & seen) if previous and seen else None
    feed.update(title=parsed.get('title') or feed['title'], authors=parsed.get('authors', []),
                site_url=parsed.get('site_url'), current_article_ids=sorted(seen),
                diagnostics=parsed.get('diagnostics', []) + [issue['reason'] for issue in result['issues']], last_checked_at=observed,
                final_url=pending.get('final_url'), last_error=None)
    if result['issues']:
        signature = common.digest(common.encoded({'feed_id': pending['feed_id'], 'parsed': parsed, 'issues': result['issues']}))
        failure = updated.setdefault('failed_responses', {}).setdefault(signature, {**pending, 'issues': result['issues']})
        failure['last_observed_at'] = observed
    else:
        feed.update(etag=pending.get('etag'), last_modified=pending.get('last_modified'))
    feed['observations'].append({'observed_at': observed, 'status': 'modified',
        'article_ids': sorted(seen), 'overlap_with_previous': overlap,
        'diagnostics': feed['diagnostics'],
        'history_limit': 'finite_feed_only; older_or_between_polls_posts_may_be_missing'})
    updated['pending'] = None
    validate(updated)
    original = store.data
    store.data = updated
    try:
        store.save()
    except Exception:
        store.data = original
        raise
    return result


def asset_key(item, revision):
    return common.digest((revision + ':' + item['kind'] + ':' + item['url']).encode('utf-8'))


def selected_entries(store, feed_ids):
    return [entry for entry in store.data['articles'].values()
            if set(entry.get('feed_ids', [entry['feed_id']])) & feed_ids]


def clean_cache(store, vault, receipt):
    name = receipt.get('cache_name')
    if not name:
        return
    folder = Path(vault) / STATE_REL / 'assets'
    try:
        feed_media._remove_owned(folder, name, receipt['sha256'])
    except FileNotFoundError:
        pass  # A successful previous cleanup may precede its final receipt save.
    receipt.pop('cache_name', None)
    store.save()


def validate_attachment_budgets(max_downloads, max_bytes):
    if any(value is not None and (type(value) is not int or value < 0) for value in (max_downloads, max_bytes)):
        raise RSSError('attachment_budgets_must_be_nonnegative_integers_or_none')


def assets(store, vault, *, download=False, max_downloads=None, max_bytes=None,
           retry=False, fetch=None, feed_ids=None):
    validate_attachment_budgets(max_downloads, max_bytes)
    fetch = fetch or feed_media.fetch_asset
    budget = {'maximum': max_downloads if download else 0, 'requests': 0, 'bytes': 0, 'max_bytes': max_bytes}
    summary = {'downloaded': 0, 'reused': 0, 'deferred': 0, 'failed': 0, 'pending': 0, 'unavailable': 0}
    feed_ids = set(store.data['feeds']) if feed_ids is None else feed_ids
    descriptors = {asset_key(item, version['revision_sha256']): item for entry in selected_entries(store, feed_ids)
                   for version in entry['versions'] for item in version['attachments']}
    for identity, item in descriptors.items():
        receipt = store.data['assets'].setdefault(identity, {**item, 'status': 'deferred'})
        try:
            if receipt['status'] == 'downloaded':
                if read_owned(vault, receipt['path'], receipt['sha256']) is None:
                    if not retry:
                        raise RSSError('rss_asset_missing')
                    receipt['status'] = 'failed'
                else:
                    clean_cache(store, vault, receipt)
                    receipt.pop('error', None)
                    summary['reused'] += 1
                    continue
            if receipt['status'] == 'prepared':
                published = receipt.get('publication_receipt', {}).get('published_sha256') == receipt['sha256']
                if published and read_owned(vault, receipt['path'], receipt['sha256']) is not None:
                    receipt.update(status='downloaded')
                    receipt.pop('error', None)
                    store.save()
                    clean_cache(store, vault, receipt)
                    summary['reused'] += 1
                    continue
                cache_relative = STATE_REL + '/assets/' + receipt['cache_name']
                try:
                    cache = read_owned(vault, cache_relative, receipt['sha256'])
                    if cache is None:
                        raise RSSError('rss_asset_cache_missing')
                except (RSSError, common.FeedError, OSError):
                    if not retry:
                        raise
                    # Do not overwrite or delete interrupted/changed bytes.
                    # Explicit retry allocates a fresh cache destination.
                    receipt.setdefault('recovery_paths', []).append(str(Path(vault) / cache_relative))
                    receipt['status'] = 'failed'
            if receipt['status'] != 'prepared':
                if receipt['status'] in {'pending', 'failed'} and not retry:
                    summary[receipt['status']] += 1
                    summary['unavailable'] += 1
                    continue
                if (budget['maximum'] is not None and budget['requests'] >= budget['maximum']
                        or max_bytes is not None and budget['bytes'] >= max_bytes):
                    summary[receipt['status'] if receipt['status'] in {'pending', 'failed'} else 'deferred'] += 1
                    summary['unavailable'] += 1
                    continue
                receipt.update(status='pending')
                store.save()
                captured = fetch(item['url'], item['kind'], budget)
                cache = captured['data']
                suffix = feed_media.extension(cache, item['kind'], captured.get('content_type', ''))
                receipt.update(status='prepared', sha256=common.digest(cache), retrieved_at=now(),
                    path='Sources/' + ('Images' if item['kind'] == 'image' else 'PDFs') + '/rss-' + identity[:32] + '.' + suffix,
                    cache_name=common.digest((identity + uuid.uuid4().hex).encode('utf-8')) + '.bin',
                    publication_receipt={})
                store.save()
                fd = common.safe_dir(Path(vault) / STATE_REL / 'assets', create=True)
                try:
                    handle = os.open(receipt['cache_name'], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                     0o600, dir_fd=fd)
                    with os.fdopen(handle, 'wb') as output:
                        output.write(cache)
                        output.flush()
                        os.fsync(output.fileno())
                    os.fsync(fd)
                finally:
                    os.close(fd)
            guarded_publish(store, vault, receipt['path'], cache, receipt['publication_receipt'], immutable=True)
            receipt.update(status='downloaded')
            receipt.pop('error', None)
            store.save()
            clean_cache(store, vault, receipt)
            summary['downloaded'] += 1
        except (RSSError, common.FeedError, feed_media.MediaError, OSError, ValueError) as exc:
            receipt['error'] = str(exc) if isinstance(exc, (RSSError, common.FeedError, feed_media.MediaError)) else type(exc).__name__
            if receipt['status'] not in {'prepared', 'downloaded'}:
                receipt['status'] = 'failed'
            summary['unavailable'] += 1
            summary['failed'] += 1
            store.save()
    store.save()
    return {**summary, 'requests': budget['requests'], 'bytes': budget['bytes']}


def yaml_value(value):
    return json.dumps(value, ensure_ascii=False)


def current_body(version, receipts, note_relative):
    """Replace only renderer-owned attachment spans, never matching source text."""
    rendered = rss_source.render_current(version)
    body = rendered['markdown']
    if (not isinstance(body, str) or rendered.get('markdown_sha256') != common.digest(body.encode('utf-8'))
            or type(rendered.get('rendering_version')) is not int or rendered['rendering_version'] not in {1, 2}):
        raise RSSError('invalid_rss_current_rendering')
    previous = 0
    replacements = []
    descriptors = {(item['kind'], item['url']) for item in rendered['attachments']}
    for occurrence in rendered['occurrences']:
        start, end = occurrence.get('start'), occurrence.get('end')
        if (type(start) is not int or type(end) is not int or not previous <= start < end <= len(body)
                or occurrence.get('markdown') != body[start:end]
                or occurrence.get('kind') not in {'image', 'pdf'}
                or not isinstance(occurrence.get('label'), str)
                or (occurrence['kind'], occurrence.get('url')) not in descriptors):
            raise RSSError('invalid_rss_attachment_occurrence')
        previous = end
        receipt = receipts.get(asset_key(occurrence, version['revision_sha256']), {})
        if receipt.get('status') != 'downloaded' or receipt.get('error'):
            continue
        path = receipt['path']
        safe_relative(path, 'Sources/Images' if occurrence['kind'] == 'image' else 'Sources/PDFs')
        if occurrence['kind'] == 'image':
            replacement = '![[%s]]' % path
        else:
            # A normal Markdown link preserves arbitrary formatted source labels
            # without introducing wiki alias delimiters from untrusted text.
            relative = posixpath.relpath(path, str(Path(note_relative).parent))
            fragment = urlsplit(occurrence['url']).fragment
            target = quote(relative, safe='/.-_~') + ('#' + fragment if fragment else '')
            replacement = rss_source._markdown_link(occurrence['label'], target)
        replacements.append((start, end, replacement))
    for start, end, replacement in reversed(replacements):
        body = body[:start] + replacement + body[end:]
    return body, rendered


def render_article(feed, entry, version, receipts, *, local_assets=True):
    """Archive format v1 uses saved Markdown forever; current views may improve."""
    metadata = {'sources': [entry['canonical_url']], 'authors': version['authors'],
                'created': entry['first_retrieved_at'][:10],
                'updated': entry.get('note_updated', version['observed_at'][:10]) if local_assets else version['observed_at'][:10],
                'title': version['title'], 'publication': version['publication'],
                'published': version.get('published_at'), 'content_scope': version['content_scope']}
    body = version['markdown']
    if local_assets:
        body, rendered = current_body(version, receipts, entry['note_relative'])
        if 'legacy_render_base_unavailable' in rendered['diagnostics']:
            metadata['rendering_limitation'] = 'legacy_render_base_unavailable'
    lines = ['---', *[key + ': ' + yaml_value(value) for key, value in metadata.items()], '---', '', body.rstrip(), '']
    return '\n'.join(lines).encode('utf-8')


def latest_version(entry, cutoff=None):
    return next((version for version in reversed(entry['versions'])
                 if cutoff is None or common.instant(version['observed_at']) <= common.instant(cutoff)), None)


def publish(store, vault, feed_ids):
    count = 0
    for entry in selected_entries(store, feed_ids):
        feed = store.data['feeds'][entry['feed_id']]
        for version in entry['versions']:
            raw = render_article(feed, entry, version, {}, local_assets=False)
            count += guarded_publish(store, vault, version['archive_relative'], raw,
                                     version['archive_receipt'], immutable=True)
            if not version.get('archive_published_at'):
                version['archive_published_at'] = now()
                store.save()
        version = current_display_version(entry, latest_version(entry))
        rendering = rss_source.render_current(version)
        if 'legacy_render_base_unavailable' in rendering['diagnostics']:
            # A legacy record may have resolved relative URLs using xml:base
            # which it did not save. Preserve the last verified public view,
            # including its local embeds, rather than guessing or degrading it.
            entry['view_rendering_limitation'] = 'legacy_render_base_unavailable'
            store.save()
            existing = read_owned(vault, entry['note_relative'])
            if existing is not None:
                if common.digest(existing) != entry.get('published_sha256'):
                    raise RSSError('rss_ownership_or_edit_conflict')
                continue
            if entry.get('published_sha256'):
                raise RSSError('rss_legacy_current_view_requires_recovery')
        elif entry.pop('view_rendering_limitation', None) is not None:
            store.save()
        raw = render_article(feed, entry, version, store.data['assets'])
        if entry.get('published_sha256') != common.digest(raw):
            entry['note_updated'] = now()[:10]
            raw = render_article(feed, entry, version, store.data['assets'])
        count += guarded_publish(store, vault, entry['note_relative'], raw, entry)
    for identity, feed in store.data['feeds'].items():
        if identity not in feed_ids:
            continue
        rows = selected_entries(store, {identity})
        index_updated = feed.get('index_updated', feed['created'])
        lines = ['---', 'sources: ' + yaml_value([feed['url']]), 'authors: ' + yaml_value(feed['authors']),
                 'created: ' + yaml_value(feed['created']), 'updated: ' + yaml_value(index_updated),
                 'title: ' + yaml_value(feed['title']), '---', '',
                 'Collected feed entries only. This index does not establish complete publication history.', '']
        for entry in sorted(rows, key=lambda value: (latest_version(value).get('published_at') or '', value['canonical_url']), reverse=True):
            version = latest_version(entry)
            lines.append('- [[' + entry['note_relative'] + '|' + common.source_markdown(version['title']).replace('|', '\\|') + ']]')
        raw = ('\n'.join(lines) + '\n').encode('utf-8')
        if feed.get('published_sha256') != common.digest(raw):
            feed['index_updated'] = now()[:10]
            lines[4] = 'updated: ' + yaml_value(feed['index_updated'])
            raw = ('\n'.join(lines) + '\n').encode('utf-8')
        count += guarded_publish(store, vault, feed['index_relative'], raw, feed)
    return count


def preflight(store, vault, feed_ids):
    owners = [(feed['index_relative'], feed) for identity, feed in store.data['feeds'].items() if identity in feed_ids]
    owners += [(entry['note_relative'], entry) for entry in selected_entries(store, feed_ids)]
    owners += [(version['archive_relative'], version['archive_receipt'])
               for entry in selected_entries(store, feed_ids) for version in entry['versions']]
    for path, owner in owners:
        raw = read_owned(vault, path)
        if raw is not None and common.digest(raw) not in {owner.get('published_sha256'), owner.get('prepared_sha256')}:
            raise RSSError('rss_ownership_or_edit_conflict')


def rendering_limitations(store, feed_ids):
    return [{'note': entry['note_relative'], 'reason': entry['view_rendering_limitation']}
            for entry in selected_entries(store, feed_ids) if entry.get('view_rendering_limitation')]


def collect(vault, *, fetch=None, asset_fetch=None, max_downloads=None, max_bytes=None,
            retry_attachments=False):
    validate_attachment_budgets(max_downloads, max_bytes)
    urls = roster(vault)
    if not urls:
        return {'status': 'not_configured', 'configured_feeds': 0, 'requests': 0, 'published_notes': 0}
    fetch = fetch or rss_source.fetch_feed
    result = {'configured_feeds': len(urls), 'requests': 0, 'feed_attempts': 0,
              'request_count_complete': True, 'new_articles': 0, 'new_revisions': 0, 'errors': []}
    with Store(vault, create=True) as store:
        store.active_feed_ids = {feed_identity(url) for url in urls}
        apply_pending(store)
        feed_ids = {ensure_feed(store, url) for url in urls}
        preflight(store, vault, feed_ids)
        for url in urls:
            identity = ensure_feed(store, url)
            feed = store.data['feeds'][identity]
            try:
                result['feed_attempts'] += 1
                response = fetch(feed.get('final_url') or url, etag=feed.get('etag'), last_modified=feed.get('last_modified'))
                result['requests'] += response['requests']
                observed = now()
                if response['status'] == 'not_modified':
                    if not feed.get('observations'):
                        raise rss_source.RSSSourceError('rss_304_without_saved_representation')
                    feed['last_checked_at'] = observed
                    feed['last_error'] = None
                    feed.update(etag=response.get('etag'), last_modified=response.get('last_modified'))
                    feed['observations'].append({'observed_at': observed, 'status': 'not_modified'})
                    store.save()
                    continue
                if response['status'] != 'modified':
                    raise rss_source.RSSSourceError('invalid_rss_fetch_status')
                parsed = rss_source.parse_feed(response['body'], response['final_url'])
                store.data['pending'] = {'feed_id': identity, 'parsed': parsed, 'observed_at': observed,
                    'etag': response.get('etag'), 'last_modified': response.get('last_modified'),
                    'final_url': response['final_url']}
                store.save()  # Parsed response survives failure before validator advancement.
                added = apply_pending(store)
                for key in ('new_articles', 'new_revisions'):
                    result[key] += added[key]
                result['errors'].extend({'feed_url': url, **issue} for issue in added['issues'])
                result['errors'].extend({'feed_url': url, 'reason': reason} for reason in parsed.get('diagnostics', []))
            except rss_source.RSSSourceError as exc:
                attempts = getattr(exc, 'requests', None)
                if type(attempts) is int and attempts >= 0:
                    result['requests'] += attempts
                else:
                    result['request_count_complete'] = False
                feed['last_error'] = str(exc)
                feed['last_attempt_at'] = now()
                feed['observations'].append({'observed_at': now(), 'status': 'failed', 'error': str(exc)})
                store.save()
                result['errors'].append({'feed_url': url, 'error': str(exc)})
        result['assets'] = assets(store, vault, download=True, max_downloads=max_downloads,
            max_bytes=max_bytes, retry=retry_attachments, fetch=asset_fetch, feed_ids=feed_ids)
        result['published_notes'] = publish(store, vault, feed_ids)
        result['rendering_limitations'] = rendering_limitations(store, feed_ids)
        result['status'] = ('incomplete' if result['errors'] or result['assets']['unavailable']
                            or result['rendering_limitations'] else 'ready')
        result['history_limit'] = 'finite_feed_only; older_or_between_polls_posts_may_be_missing'
    return result


def collect_attachments(vault, *, asset_fetch=None, max_downloads=None, max_bytes=None,
                        retry_attachments=False):
    """Download finite saved attachments; never fetch/apply a feed response."""
    validate_attachment_budgets(max_downloads, max_bytes)
    urls = roster(vault)
    if not urls:
        return {'status': 'not_configured', 'feed_requests': 0, 'requests': 0, 'published_notes': 0}
    if read_state(vault) is None:
        return {'status': 'not_collected', 'feed_requests': 0, 'requests': 0, 'published_notes': 0}
    with Store(vault) as store:
        feed_ids = {feed_identity(url) for url in urls}
        preflight(store, vault, feed_ids)
        result = assets(store, vault, download=True, max_downloads=max_downloads, max_bytes=max_bytes,
                        retry=retry_attachments, fetch=asset_fetch, feed_ids=feed_ids)
        count = publish(store, vault, feed_ids)
        limitations = rendering_limitations(store, feed_ids)
        pending = bool(store.data['pending'] and store.data['pending']['feed_id'] in feed_ids)
        uncollected = sorted(set(urls) - {feed['url'] for feed in store.data['feeds'].values()})
        return {'status': 'incomplete' if result['unavailable'] or limitations or pending or uncollected else 'ready',
                'feed_requests': 0, 'requests': result['requests'], 'published_notes': count, 'assets': result,
                'rendering_limitations': limitations, 'pending_feed_response_unchanged': pending,
                'uncollected_feeds': uncollected}

def _context(vault, cutoff, since=None, retained_ids=None, *, compact=False):
    cutoff = common.timestamp(cutoff)
    if since is not None:
        since = common.timestamp(since)
    urls = roster(vault)
    retained = set(retained_ids or [])
    if any(not isinstance(identity, str) or not EVIDENCE.fullmatch(identity) for identity in retained):
        raise RSSError('invalid_retained_rss_evidence_id')
    data = read_state(vault)
    result = {'status': 'ready', 'configured_feeds': len(urls), 'items': [], 'feeds': [], 'diagnostics': [],
              'pending': bool(data and data['pending'])}
    if data is None:
        if urls or retained:
            result['status'] = 'incomplete'
            result['diagnostics'].append({'reason': 'rss_sources_not_collected'})
        return operational_summary(result, None) if compact else result

    if data['pending']:
        result['diagnostics'].append({'reason': 'rss_pending_response_requires_offline_publication'})
    for url in urls:
        if feed_identity(url) not in data['feeds']:
            result['diagnostics'].append({'feed_url': url, 'reason': 'rss_feed_not_collected_at_cutoff'})
    seen = set()
    for identity, feed in data['feeds'].items():
        if feed['url'] in urls:
            observations = [row for row in feed['observations']
                            if common.instant(row['observed_at']) <= common.instant(cutoff)]
            latest_poll = observations[-1] if observations else {}
            latest_modified = next((row for row in reversed(observations) if row['status'] == 'modified'), {})
            result['feeds'].append({'feed_id': identity, 'feed_url': feed['url'], 'publication': feed['title'],
                'last_checked_at': latest_poll.get('observed_at'), 'last_error': latest_poll.get('error'),
                'history_limit': 'finite_feed_only; older_or_between_polls_posts_may_be_missing',
                'diagnostics': latest_modified.get('diagnostics', []), 'observations': observations})
            if latest_poll.get('error'):
                result['diagnostics'].append({'feed_url': feed['url'], 'reason': latest_poll['error']})
            if not observations:
                result['diagnostics'].append({'feed_url': feed['url'], 'reason': 'rss_feed_not_collected_at_cutoff'})
            elif common.instant(cutoff) - common.instant(observations[-1]['observed_at']) > common.timedelta(hours=26):
                result['diagnostics'].append({'feed_url': feed['url'], 'reason': 'rss_feed_check_older_than_26_hours'})
            if latest_modified.get('overlap_with_previous') is False:
                result['diagnostics'].append({'feed_url': feed['url'], 'reason': 'rss_feed_history_gap_possible'})
            for reason in latest_modified.get('diagnostics', []):
                result['diagnostics'].append({'feed_url': feed['url'], 'reason': reason})
    for identity, entry in data['articles'].items():
        feed = data['feeds'][entry['feed_id']]
        selected = latest_version(entry, cutoff)
        for version in entry['versions']:
            evidence_id = identity + '@' + version['revision_sha256']
            if common.instant(version['observed_at']) > common.instant(cutoff):
                continue
            active = any(data['feeds'][source]['url'] in urls for source in entry.get('feed_ids', [entry['feed_id']]))
            if evidence_id not in retained and (not active or version is not selected
                    or since is not None and common.instant(version['observed_at']) < common.instant(since)):
                continue
            available, error = True, None
            try:
                expected = version['archive_receipt'].get('published_sha256')
                expected_content = render_article(feed, entry, version, {}, local_assets=False)
                available = bool(expected and expected == common.digest(expected_content)
                    and version.get('archive_published_at') is not None
                    and common.instant(version['archive_published_at']) <= common.instant(cutoff)
                    and read_owned(vault, version['archive_relative'], expected) == expected_content)
            except (RSSError, OSError) as exc:
                available, error = False, str(exc)
            asset_rows = []
            for item in version['attachments']:
                key = asset_key(item, version['revision_sha256'])
                receipt = data['assets'].get(key, {})
                eligible = receipt.get('status') == 'downloaded' and not receipt.get('error')
                eligible = bool(eligible and common.instant(receipt['retrieved_at']) <= common.instant(cutoff))
                if eligible:
                    try:
                        eligible = read_owned(vault, receipt['path'], receipt['sha256']) is not None
                    except (RSSError, OSError):
                        eligible = False
                asset_rows.append({'asset_key': key, 'kind': item['kind'],
                    'status': receipt.get('status', 'unavailable') if eligible else 'unavailable_at_cutoff',
                    'eligible': eligible, **({key: receipt[key] for key in ('path', 'sha256', 'retrieved_at')
                                             if key in receipt} if eligible else {})})
            item = {'article_id': identity, 'evidence_id': evidence_id, 'canonical_url': entry['canonical_url'],
                'publication': version['publication'], 'observed_at': version['observed_at'], 'first_retrieved_at': entry['first_retrieved_at'],
                'revision_sha256': version['revision_sha256'], 'title': version['title'], 'authors': version['authors'],
                'semantic_sha256': version['semantic_sha256'], 'previous_revision_sha256': version['previous_revision_sha256'],
                'published_at': version.get('published_at'), 'updated_at': version.get('updated_at'),
                'content': version['markdown'], 'raw_content': version['content'], 'content_scope': version['content_scope'],
                'content_basis': 'immutable_revision_archive',
                'evidence_rendering_version': version.get('rendering_version', 1),
                'current_note_is_historical_evidence': False,
                'current_note_rendering_limitation': entry.get('view_rendering_limitation'),
                'linked_media': version.get('linked_media', []),
                'assets': asset_rows, 'note_relative': entry['note_relative'], 'evidence_relative': version['archive_relative'],
                'note_available': available, 'note_sha256': version['archive_receipt'].get('published_sha256'),
                'feed_id': version['source_feed_id'], 'feed_url': version['source_feed_url'],
                'source_group': version['source_feed_id'],
                'diagnostics': version.get('diagnostics', [])}
            result['items'].append(item)
            seen.add(evidence_id)
            missing = [row for row in asset_rows if not row['eligible']]
            if missing:
                result['diagnostics'].append({'evidence_id': evidence_id,
                    'reason': 'rss_attachments_unavailable_at_cutoff', 'unavailable': len(missing),
                    'images': sum(row['kind'] == 'image' for row in missing),
                    'pdfs': sum(row['kind'] == 'pdf' for row in missing)})
            if not available:
                result['diagnostics'].append({'evidence_id': evidence_id, 'reason': error or 'rss_revision_not_published'})
    for missing in sorted(retained - seen):
        result['diagnostics'].append({'evidence_id': missing, 'reason': 'retained_rss_revision_unavailable_at_cutoff'})
    if result['diagnostics']:
        result['status'] = 'incomplete'
    if read_state(vault) != data:
        raise RSSError('rss_state_changed_during_context_read')
    return operational_summary(result, data) if compact else result


def context(vault, cutoff, since=None, retained_ids=None, *, compact=False):
    """Read verified archived source versions without changing collection state."""
    try:
        return _context(vault, cutoff, since, retained_ids, compact=compact)
    except (common.FeedError, rss_source.RSSSourceError, OSError, KeyError, TypeError) as exc:
        raise RSSError(str(exc) if not isinstance(exc, (KeyError, TypeError)) else 'invalid_rss_state') from None


def operational_summary(captured, data):
    """Compact CLI preflight; full verified evidence remains in context()."""
    articles = data['articles'].values() if data else []
    attachment_totals = {}
    for receipt in data['assets'].values() if data else []:
        status = 'failed' if receipt.get('error') else receipt['status']
        attachment_totals[status] = attachment_totals.get(status, 0) + 1
    scopes, limitations = {}, []
    for item in captured['items']:
        scope = item['content_scope']
        scopes[scope] = scopes.get(scope, 0) + 1
        reasons = set(item['diagnostics'])
        if scope == 'summary_only':
            reasons.add('summary_only')
        if item.get('current_note_rendering_limitation'):
            reasons.add(item['current_note_rendering_limitation'])
        if reasons:
            limitations.append({'evidence_id': item['evidence_id'], 'note_relative': item['note_relative'],
                                'reasons': sorted(reasons)})
    return {'status': captured['status'], 'configured_feeds': captured['configured_feeds'],
            'pending': captured['pending'], 'requests': 0,
            'current_articles': len(captured['items']), 'retained_articles': len(articles),
            'retained_revisions': sum(len(entry['versions']) for entry in articles),
            'attachments': attachment_totals, 'content_scopes': scopes, 'article_limitations': limitations,
            'feeds': [{key: feed.get(key) for key in ('feed_id', 'feed_url', 'publication',
                      'last_checked_at', 'last_error', 'history_limit', 'diagnostics')}
                      for feed in captured['feeds']],
            'diagnostics': captured['diagnostics']}


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('command', nargs='?', choices=('plan', 'status', 'collect', 'attachments', 'publish'))
    result.add_argument('--vault')
    result.add_argument('--max-downloads', type=int, default=None,
                        help='Optional media HTTP request limit; default processes the finite saved backlog.')
    result.add_argument('--max-attachment-bytes', type=int, default=None,
                        help='Optional aggregate byte limit; per-file safety limits always apply.')
    result.add_argument('--retry-attachments', action='store_true')
    result.add_argument('--details', action='store_true',
                        help='Plan/status only: output complete verified research context, including source bodies.')
    result.add_argument('--test', action='store_true')
    return result


def execute(args):
    if args.command in {'plan', 'status'}:
        return {**context(args.vault, now(), compact=not args.details), 'requests': 0}
    if args.details:
        raise RSSError('details_requires_plan_or_status')
    if args.command == 'collect':
        return collect(args.vault, max_downloads=args.max_downloads, max_bytes=args.max_attachment_bytes,
                       retry_attachments=args.retry_attachments)
    if args.command == 'attachments':
        return collect_attachments(args.vault, max_downloads=args.max_downloads,
                                   max_bytes=args.max_attachment_bytes, retry_attachments=args.retry_attachments)
    if read_state(args.vault) is None:
        return {'requests': 0, 'published_notes': 0, 'status': 'not_collected'}
    with Store(args.vault) as store:
        feed_ids = {feed_identity(url) for url in roster(args.vault)}
        store.active_feed_ids = feed_ids
        apply_pending(store)
        preflight(store, args.vault, feed_ids)
        result = assets(store, args.vault, download=False, feed_ids=feed_ids)
        count = publish(store, args.vault, feed_ids)
        return {'requests': 0, 'published_notes': count, 'assets': result,
                'rendering_limitations': rendering_limitations(store, feed_ids)}


def run_self_test():
    import unittest
    from unittest.mock import patch
    class Tests(unittest.TestCase):
        def test_absent_roster_is_read_only(self):
            with tempfile.TemporaryDirectory() as directory:
                vault = Path(directory).resolve()
                self.assertEqual(roster(vault), [])
                self.assertEqual(context(vault, '2026-09-08T12:00:00Z')['configured_feeds'], 0)
                self.assertEqual(list(vault.iterdir()), [])
        def test_canonical_identity_is_stable_and_does_not_use_title(self):
            self.assertEqual(article_id('https://example.com/post#one'), article_id('https://example.com/post#two'))
            with self.assertRaises(rss_source.RSSSourceError):
                article_id('http://127.0.0.1/private')
        def test_saved_article_has_verified_revision_and_unchanged_poll_reuses_it(self):
            raw = (b'<rss version="2.0"><channel><title>Research</title><link>https://example.com/</link>'
                   b'<item><title>Source thesis</title><link>https://example.com/post</link>'
                   b'<description>Exact supplied source text.</description></item></channel></rss>')
            with tempfile.TemporaryDirectory() as directory:
                vault = Path(directory).resolve()
                (vault / 'Investments').mkdir()
                (vault / ROSTER_REL).write_text('- [x] https://example.com/feed\n', encoding='utf-8')
                def fetch(url, **kwargs):
                    return {'status': 'modified', 'final_url': url, 'body': raw, 'requests': 1,
                            'etag': '"fixed"', 'last_modified': None}
                record = {'skill': 'investments:feed-collect', 'plugin_version': '1.14.0',
                          'source_commit': None, 'source_url': None, 'source_status': 'uncommitted',
                          'runtime_sha256': '0' * 64}
                with patch.object(common, 'provenance', return_value=record):
                    self.assertEqual(collect(vault, fetch=fetch, max_downloads=0)['new_articles'], 1)
                    self.assertEqual(collect(vault, fetch=fetch, max_downloads=0)['new_revisions'], 0)
                captured = context(vault, now())['items']
                self.assertEqual(len(captured), 1)
                self.assertTrue(captured[0]['note_available'])
                with patch.object(rss_source, 'fetch_feed', side_effect=AssertionError('No feed request')):
                    attached = collect_attachments(vault)
                self.assertEqual(attached['feed_requests'], 0)
                self.assertEqual(attached['requests'], 0)
        def test_renderer_upgrade_does_not_change_supplied_source_identity(self):
            old = {'canonical_url': 'https://example.com/post', 'content': '<p>Unchanged source.</p>',
                   'attachments': [], 'markdown': 'Old display', 'diagnostics': []}
            new = dict(old, markdown='Improved display', rendering_version=2,
                       render_base='https://example.com/feed', linked_media=[])
            self.assertTrue(same_source(old, new))
            self.assertNotEqual(semantic_hash(old), semantic_hash(new))
            self.assertFalse(same_source(old, dict(new, content='<p>New source.</p>')))
        def test_local_pdf_occurrence_does_not_replace_literal_source_code(self):
            version = {'content': '<p><a href="https://example.com/report.pdf">Read report</a></p>'
                        '<pre>[PDF](https://example.com/report.pdf)</pre>', 'content_type': 'html',
                        'render_base': 'https://example.com/feed', 'attachments': [],
                        'revision_sha256': '0' * 64}
            item = {'kind': 'pdf', 'url': 'https://example.com/report.pdf'}
            receipts = {asset_key(item, version['revision_sha256']): {
                'status': 'downloaded', 'path': 'Sources/PDFs/example.pdf'}}
            body, _ = current_body(version, receipts, 'Investments/Sources/RSS/example/post.md')
            self.assertIn('[Read report](../../../../Sources/PDFs/example.pdf)', body)
            self.assertIn('    [PDF](https://example.com/report.pdf)', body)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
    result = unittest.TextTestRunner().run(suite)
    print(str(result.testsRun - len(result.errors) - len(result.failures)) + '/' + str(result.testsRun) + ' tests passed')
    return 0 if result.wasSuccessful() else 1


def main(argv=None):
    args = parser().parse_args(argv)
    if args.test:
        return run_self_test()
    if not args.command or not args.vault:
        parser().error('command and --vault are required')
    if ((args.max_downloads is not None and args.max_downloads < 0)
            or (args.max_attachment_bytes is not None and args.max_attachment_bytes < 0)):
        parser().error('attachment budgets must be nonnegative')
    try:
        print(json.dumps(execute(args), ensure_ascii=False, indent=2))
        return 0
    except (RSSError, common.FeedError, rss_source.RSSSourceError, OSError, ValueError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
