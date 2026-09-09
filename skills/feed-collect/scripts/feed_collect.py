#!/usr/bin/env python3
"""Bounded X source collection. Standard library; no interpretation or trading.

Successful responses are committed before publication. An unresolved request is
never replayed automatically. All network access is explicit, GET-only and to
api.x.com, with redirects disabled. --test is offline.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[3]
_OBSIDIAN_SHARED_MODULES = ('atomic_move', 'note_provenance', 'portable_names')

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
import note_provenance
from portable_names import portable_identity
sys.path.insert(2, str(ROOT / 'skills/stock-research/scripts'))
from market_credentials import load_credentials
import feed_media

HANDLE = re.compile(r'[A-Za-z0-9_]{1,15}\Z')
ID = re.compile(r'[0-9]{1,25}\Z')
LIMIT = 64 * 1024 * 1024
API_RESPONSE_LIMIT = 8 * 1024 * 1024
EXCLUDE = None  # No transport parameter: filter replies to other users locally.
# Finish already-purchased pagination with its original filter and fields.
TIMELINE_FILTERS = (EXCLUDE, 'replies', 'retweets,replies')
REPLY_EXCLUSIONS = ('other_account', 'target_unavailable', 'ambiguous_metadata', 'legacy_filter')
# Keep historical excluded-repost counts readable after enabling reposts.
ROW_CATEGORIES = ('excluded_replies', 'excluded_reposts', 'duplicate_rows',
                  'merged_versions', 'updated_existing_posts', 'newly_stored_posts')
SAFE_QUERY_KEYS = {'max_results', 'tweet.fields', 'post.fields', 'media.fields', 'expansions',
                   'start_time', 'end_time', 'since_id', 'until_id', 'exclude', 'pagination_token', 'ids'}
LEGACY_FIELDS = ('id,text,author_id,created_at,note_tweet,attachments,entities,media_metadata,'
                 'referenced_tweets,conversation_id,edit_history_tweet_ids,withheld')
FIELDS = LEGACY_FIELDS + ',in_reply_to_user_id'
LEGACY_MEDIA_FIELDS = 'media_key,type,url,alt_text,width,height'
MEDIA_FIELDS = LEGACY_MEDIA_FIELDS + ',variants'


class FeedError(Exception):
    pass


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(
            r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})', value):
        raise FeedError('invalid_timestamp')
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise FeedError('invalid_timestamp') from None
    if date.tzinfo is None:
        raise FeedError('timestamp_requires_timezone')
    return date.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def instant(value):
    """Compare timestamps chronologically, including subsecond boundaries."""
    return datetime.fromisoformat(timestamp(value).replace('Z', '+00:00'))


def decode(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise FeedError('duplicate_json_key')
            out[key] = value
        return out
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(FeedError('invalid_json_constant')))
    except (ValueError, UnicodeError, RecursionError):
        raise FeedError('invalid_json') from None


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def check_spelling(fd, name):
    aliases = [entry for entry in os.listdir(fd)
               if portable_identity(entry) == portable_identity(name)]
    if aliases and aliases != [name]:
        raise FeedError('portable_path_spelling_conflict')


def safe_dir(path, create=False):
    """Open an exact directory chain without following links or aliases."""
    if '..' in Path(path).parts:
        raise FeedError('unsafe_path')
    path = Path(os.path.abspath(os.fspath(path)))
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            check_spelling(fd, part)
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                check_spelling(fd, part)
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except Exception:
        os.close(fd)
        raise


def read_at(fd, name, optional=False):
    check_spelling(fd, name)
    try:
        leaf = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except FileNotFoundError:
        if optional:
            return None
        raise
    try:
        info = os.fstat(leaf)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > LIMIT:
            raise FeedError('unsafe_or_oversized_file')
        chunks, count = [], 0
        while True:
            chunk = os.read(leaf, min(65536, LIMIT + 1 - count))
            if not chunk:
                break
            count += len(chunk)
            if count > LIMIT:
                raise FeedError('oversized_file')
            chunks.append(chunk)
        after = os.fstat(leaf)
        named = os.stat(name, dir_fd=fd, follow_symlinks=False)
        def key(item):
            return item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns
        if key(info) != key(after) or key(after) != key(named):
            raise FeedError('file_changed_during_read')
        check_spelling(fd, name)
        return b''.join(chunks)
    finally:
        os.close(leaf)


def roster(path, include_disabled=False):
    fd = safe_dir(Path(path).parent)
    try:
        text = read_at(fd, Path(path).name).decode('utf-8')
    finally:
        os.close(fd)
    result, seen, fence, comment = [], set(), None, False
    for line in text.splitlines():
        if comment:
            if '-->' in line:
                comment = False
            continue
        if fence is None and line.lstrip().startswith('<!--'):
            comment = '-->' not in line
            continue
        opening = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if opening:
            marker = opening[1]
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            continue
        if fence or not re.match(r'^ {0,3}- \[[ xX]\]', line):
            continue
        match = re.fullmatch(r' {0,3}- \[([ xX])\] @([A-Za-z0-9_]{1,15})(?:\s+<!-- x-user-id: ([0-9]{1,25}) -->)?(?:\s+[—–-]\s+[^<>]*)?\s*', line)
        if not match:
            raise FeedError('malformed_account_entry')
        handle = match[2].lower()
        if handle in seen:
            raise FeedError('duplicate_account_entry')
        seen.add(handle)
        if match[1].lower() == 'x' or include_disabled:
            result.append({'handle': handle, 'id': match[3]})
    if not result and not include_disabled:
        raise FeedError('no_active_accounts')
    if len(result) > 100:
        raise FeedError('too_many_active_accounts')
    known_ids = [item['id'] for item in result if item['id']]
    if len(set(known_ids)) != len(known_ids):
        raise FeedError('duplicate_account_identity')
    return result


def validated_references(value):
    if (not isinstance(value, list) or any(not isinstance(item, dict)
            or not isinstance(item.get('id'), str) or not ID.fullmatch(item['id'])
            or not isinstance(item.get('type'), str) for item in value)):
        raise FeedError('invalid_post_references')
    return value


def is_self_reply(post, account_id):
    """Recognize only reply metadata bound to this verified account identity."""
    if not isinstance(post, dict) or post.get('in_reply_to_user_id') != account_id:
        return False
    references = post.get('references', [])
    if not isinstance(references, list) or any(not isinstance(ref, dict) for ref in references):
        return False
    parents = [ref for ref in references if ref.get('type') == 'replied_to']
    conversation = post.get('conversation_id')
    return (isinstance(account_id, str) and bool(ID.fullmatch(account_id)) and len(parents) == 1
            and isinstance(parents[0].get('id'), str) and bool(ID.fullmatch(parents[0]['id']))
            and not any(ref.get('type') == 'retweeted' for ref in references)
            and (conversation is None or isinstance(conversation, str) and bool(ID.fullmatch(conversation))))


def validate_profile(profile):
    if (not isinstance(profile, dict) or not isinstance(profile.get('description'), str)
            or not profile['description'].strip() or len(profile['description']) > 2000
            or not isinstance(profile.get('sources'), list) or not profile['sources']):
        raise FeedError('description_requires_background_and_sources')
    for url in profile['sources']:
        if not isinstance(url, str) or any(char.isspace() for char in url):
            raise FeedError('invalid_description_source')
        try:
            parsed = urllib.parse.urlsplit(url)
            if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError()
        except ValueError:
            raise FeedError('invalid_description_source') from None
    timestamp(profile.get('checked_at'))


def validate_note_metadata(note):
    if not isinstance(note, dict):
        raise FeedError('invalid_note_metadata')
    for field in ('created', 'updated'):
        value = note.get(field)
        if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise FeedError('invalid_note_date')
        timestamp(value + 'T00:00:00Z')
    payload = note.get('provenance')
    if not isinstance(payload, dict) or payload.get('schema') != 1 or 'generated_by' not in payload:
        raise FeedError('invalid_note_provenance')
    for field in ('generated_by', 'updated_by'):
        if payload.get(field) is not None:
            note_provenance.validate_record(payload[field])
    if payload['generated_by'] is None and payload.get('updated_by') is None:
        raise FeedError('invalid_note_provenance')


def validate_state(data):
    """Reject corrupted identity/path/cursor state before any paid operation."""
    if (not isinstance(data, dict) or data.get('schema') != 1 or not isinstance(data.get('accounts'), dict)
            or not isinstance(data.get('requests'), list) or type(data.get('round_robin')) is not int
            or data['round_robin'] < 0 or 'pending' not in data):
        raise FeedError('invalid_collection_state')
    receipts = data.get('assets', {})
    if (not isinstance(receipts, dict) or any(not isinstance(key, str) or not feed_media.KEY.fullmatch(key)
            or not isinstance(value, dict) for key, value in receipts.items())):
        raise FeedError('invalid_asset_receipts')
    identities = set()
    for name, account in data['accounts'].items():
        if not isinstance(name, str) or not HANDLE.fullmatch(name) or name != name.lower() or not isinstance(account, dict):
            raise FeedError('invalid_stored_account')
        required = {'id', 'handle', 'filename', 'posts', 'window', 'completed_at', 'since_id', 'gaps', 'published_sha256'}
        if not required <= account.keys():
            raise FeedError('incomplete_stored_account')
        if (not isinstance(account['id'], str) or not ID.fullmatch(account['id']) or account['id'] in identities
                or not isinstance(account['handle'], str) or not HANDLE.fullmatch(account['handle'])
                or account['filename'] != name + '.md' or not isinstance(account['posts'], dict)
                or not isinstance(account['gaps'], list)):
            raise FeedError('invalid_stored_account_identity')
        identities.add(account['id'])
        if 'profile' in account:
            validate_profile(account['profile'])
        for field in ('note', 'prepared_note'):
            if field in account:
                validate_note_metadata(account[field])
        for key in ('published_sha256', 'prepared_sha256'):
            if account.get(key) is not None and not re.fullmatch(r'[0-9a-f]{64}', str(account[key])):
                raise FeedError('invalid_publication_receipt')
        if account['since_id'] is not None and not ID.fullmatch(str(account['since_id'])):
            raise FeedError('invalid_saved_since_id')
        if account['completed_at'] is not None:
            timestamp(account['completed_at'])
        if account.get('requested_through') is not None:
            timestamp(account['requested_through'])
        if account.get('requested_since') is not None:
            timestamp(account['requested_since'])
        window = account['window']
        if window is not None:
            if not isinstance(window, dict) or not {'start', 'end', 'next_token', 'seen_tokens', 'max_id'} <= window.keys():
                raise FeedError('invalid_saved_window')
            if 'exclude' not in window or window['exclude'] not in TIMELINE_FILTERS:
                raise FeedError('incompatible_saved_timeline_filter')
            if ((window['start'] is not None and instant(window['start']) >= instant(window['end']))
                    or not isinstance(window['seen_tokens'], list)):
                raise FeedError('invalid_saved_window')
            timestamp(window['end'])
            for key in ('since_id', 'until_id', 'oldest_id'):
                if window.get(key) is not None and (not isinstance(window[key], str) or not ID.fullmatch(window[key])):
                    raise FeedError('invalid_saved_window_boundary')
            if ('oldest_id' in window) != ('oldest_at' in window):
                raise FeedError('invalid_saved_window_boundary')
            if window.get('oldest_id') is not None and instant(window['oldest_at']) > instant(window['end']):
                raise FeedError('invalid_saved_window_boundary')
            if 'oldest_is_edit' in window and type(window['oldest_is_edit']) is not bool:
                raise FeedError('invalid_saved_window_boundary')
            if window.get('completed_through') is not None:
                timestamp(window['completed_through'])
            allowed_fields = (FIELDS,) if window['exclude'] is None else (LEGACY_FIELDS, FIELDS)
            allowed_selections = [{'tweet.fields': fields} for fields in allowed_fields] + [
                {'tweet.fields': fields, 'expansions': 'attachments.media_keys', 'media.fields': media_fields}
                for fields in allowed_fields for media_fields in (LEGACY_MEDIA_FIELDS, MEDIA_FIELDS)]
            if ((window['exclude'] is None and 'fields' not in window)
                    or 'fields' in window and window['fields'] not in allowed_selections):
                raise FeedError('invalid_saved_field_selection')
            if window['next_token'] is not None and not re.fullmatch(r'[A-Za-z0-9_-]{1,2048}', str(window['next_token'])):
                raise FeedError('invalid_saved_pagination')
        sample = account.get('sample')
        if sample is not None:
            if (not isinstance(sample, dict) or type(sample.get('target')) is not int
                    or not 1 <= sample['target'] <= 800
                    or sample.get('status') not in {'in_progress', 'target_reached', 'available_history_exhausted', 'abandoned',
                                                  'superseded_by_recent_window'}):
                raise FeedError('invalid_saved_sample')
            timestamp(sample.get('cutoff'))
            if sample.get('history_before') is not None:
                timestamp(sample['history_before'])
        for post_id, post in account['posts'].items():
            if (not isinstance(post_id, str) or not ID.fullmatch(post_id) or not isinstance(post, dict)
                    or post.get('id') != post_id or not {'created_at', 'first_retrieved_at', 'status'} <= post.keys()):
                raise FeedError('invalid_stored_post')
            timestamp(post['created_at'])
            timestamp(post['first_retrieved_at'])
            if post.get('last_checked_at') is not None:
                timestamp(post['last_checked_at'])
            if post['status'] == 'available' and not isinstance(post.get('text'), str):
                raise FeedError('invalid_stored_post_text')
            validated_references(post.get('references', []))
            if 'in_reply_to_user_id' in post and not is_self_reply(post, account['id']):
                raise FeedError('invalid_stored_self_reply')
    for request in data['requests']:
        if not isinstance(request, dict):
            raise FeedError('invalid_request_history')
        if 'returned_posts' in request and (type(request['returned_posts']) is not int or request['returned_posts'] < 0):
            raise FeedError('invalid_request_row_count')
        if 'row_counts' in request:
            counts = request['row_counts']
            if (not isinstance(counts, dict) or set(counts) != set(ROW_CATEGORIES)
                    or any(type(value) is not int or value < 0 for value in counts.values())
                    or sum(counts.values()) != request.get('returned_posts')):
                raise FeedError('invalid_request_row_accounting')
        if 'reply_exclusions' in request:
            reasons = request['reply_exclusions']
            if (not isinstance(reasons, dict) or set(reasons) != set(REPLY_EXCLUSIONS)
                    or any(type(value) is not int or value < 0 for value in reasons.values())
                    or sum(reasons.values()) != request.get('row_counts', {}).get('excluded_replies')):
                raise FeedError('invalid_reply_exclusion_accounting')
    pending = data['pending']
    if pending is not None:
        if (not isinstance(pending, dict) or not {'kind', 'handle', 'path', 'query', 'started_at', 'request_id'} <= pending.keys()
                or pending['kind'] not in {'user', 'timeline', 'reconcile'} or not isinstance(pending['handle'], str)
                or not HANDLE.fullmatch(pending['handle']) or not isinstance(pending['query'], dict)):
            raise FeedError('invalid_pending_request')
        if pending['kind'] != 'user' and pending['handle'] not in data['accounts']:
            raise FeedError('pending_identity_missing')
        if pending['kind'] == 'timeline':
            window = data['accounts'][pending['handle']]['window']
            if (window is None or (window['exclude'] is None and 'exclude' in pending['query'])
                    or (window['exclude'] is not None and pending['query'].get('exclude') != window['exclude'])):
                raise FeedError('incompatible_saved_timeline_filter')
            if 'fields' in window and {key: pending['query'][key] for key in
                    ('tweet.fields', 'post.fields', 'expansions', 'media.fields') if key in pending['query']} != window['fields']:
                raise FeedError('incompatible_saved_timeline_fields')
    return data


class Store:
    """One private locked state file; atomic rename+fsync commits each request."""
    def __init__(self, vault, create=False):
        self.path = Path(vault) / 'Investments/Sources/.feed-collect'
        self.fd = safe_dir(self.path, create)
        self.lock = None
        self.expected = None
        try:
            info = os.fstat(self.fd)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise FeedError('collection_state_directory_must_be_private')
            check_spelling(self.fd, 'collector.lock')
            try:
                self.lock = os.open('collector.lock', os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
                new_lock = True
            except FileExistsError:
                new_lock = False
                self.lock = os.open('collector.lock', os.O_RDWR | os.O_NOFOLLOW, dir_fd=self.fd)
            check_spelling(self.fd, 'collector.lock')
            info = os.fstat(self.lock)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600):
                raise FeedError('unsafe_lock')
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with anchored_cwd(self.fd):
                try:
                    self.expected = atomic_move.regular_file_snapshot('state.json')
                except FileNotFoundError:
                    pass
            raw = read_at(self.fd, 'state.json', optional=True)
            if self.expected is not None and self.expected.mode != 0o600:
                raise FeedError('collection_state_file_must_be_private')
            if raw is None and not new_lock:
                raise FeedError('missing_existing_state_requires_recovery')
            if (raw is None) != (self.expected is None) or (raw is not None and digest(raw) != self.expected.digest):
                raise FeedError('state_changed_during_open')
            self.data = decode(raw) if raw is not None else {'schema': 1, 'accounts': {}, 'pending': None,
                                               'requests': [], 'round_robin': 0}
            validate_state(self.data)
            if raw is None:
                self.save()
        except Exception:
            self.close()
            raise

    def save(self):
        raw = encoded(self.data)
        with anchored_cwd(self.fd):
            check_spelling(self.fd, 'state.json')
            stage = tempfile.mkdtemp(prefix='.state-stage-', dir='.')
            keep = False
            try:
                staged = Path(stage) / 'state.json'
                with staged.open('xb') as handle:
                    atomic_move.set_private_mode(handle.fileno(), 0o600)
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
                if len(raw) > LIMIT:
                    # A received paid response may expand when pretty-printed.
                    # Preserve its complete attempted state before refusing the
                    # bounded public state file; never leave only a request marker.
                    stage_fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    try:
                        os.fsync(stage_fd)
                    finally:
                        os.close(stage_fd)
                    os.fsync(self.fd)
                    raise FeedError('state_capacity_reached')
                if self.expected is None:
                    published = atomic_move.publish_new(staged, 'state.json', atomic_move.regular_file_snapshot, '.')
                else:
                    published = atomic_move.replace_expected(staged, 'state.json', self.expected,
                                                             atomic_move.regular_file_snapshot, stage, '.')
                os.fsync(self.fd)
                check_spelling(self.fd, 'state.json')
                if atomic_move.regular_file_snapshot('state.json') != published or published.digest != digest(raw):
                    raise FeedError('state_changed_after_publication')
                self.expected = published
            except Exception as exc:
                keep = True
                reason = ('state_capacity_reached' if isinstance(exc, FeedError)
                          and str(exc) == 'state_capacity_reached' else
                          'state_publication_link_unavailable' if isinstance(exc, atomic_move.LinkUnavailable)
                          else 'state_publication_conflict')
                recovery = str(Path(getattr(exc, 'recovery_path', None) or stage).absolute())
                raise FeedError(reason + '; preserved_recovery=' + recovery) from None
            finally:
                if not keep:
                    shutil.rmtree(stage)

    def close(self):
        if self.lock is not None:
            os.close(self.lock)
            self.lock = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def token(args):
    value = (load_credentials(args.credentials_file, allowed_names={'X_BEARER_TOKEN'}).get('X_BEARER_TOKEN')
             if args.credentials_file else os.environ.get('X_BEARER_TOKEN'))
    if not value or not re.fullmatch(r'[A-Za-z0-9%._~+/=-]{10,4096}', value):
        raise FeedError('missing_or_invalid_x_bearer_token')
    return value


def request_json(path, query, bearer):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    if not re.fullmatch(r'/2/(?:users/(?:[0-9]{1,25}/tweets|by/username/[A-Za-z0-9_]{1,15})|tweets)', path):
        raise FeedError('invalid_api_path')
    url = 'https://api.x.com' + path + '?' + urllib.parse.urlencode(query)
    request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + bearer,
                                                  'Accept': 'application/json'}, method='GET')
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
            raw = response.read(API_RESPONSE_LIMIT + 1)
            if len(raw) > API_RESPONSE_LIMIT:
                raise FeedError('oversized_api_response')
            value = decode(raw)
            if not isinstance(value, dict):
                raise FeedError('invalid_api_response')
            return value
    except urllib.error.HTTPError as exc:
        # Even known HTTP errors remain durable pending evidence; no schema or
        # rate-limit retry is performed behind the user's back.
        raise FeedError('api_http_' + str(exc.code)) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise FeedError('network_outcome_uncertain') from None


def paid_request(store, kind, handle, path, query, bearer, fetch):
    if store.data['pending']:
        raise FeedError('unresolved_request_blocks_network')
    pending = {'kind': kind, 'handle': handle, 'path': path, 'query': query,
               'started_at': now(), 'request_id': uuid.uuid4().hex}
    # Reserve twice the raw response cap plus bookkeeping before spending.
    # This is conservative headroom, not an absolute serialized-size guarantee:
    # deeply nested JSON can expand much more under indentation. Store.save's
    # durable oversized stage remains the safety net for that case.
    planned = dict(store.data, pending=pending)
    if len(encoded(planned)) + 2 * API_RESPONSE_LIMIT + 4096 > LIMIT:
        raise FeedError('state_capacity_headroom_required; no_api_request_made')
    store.data['pending'] = pending
    store.save()
    try:
        response = fetch(path, query, bearer)
    except Exception as exc:
        pending['error'] = str(exc) if isinstance(exc, FeedError) else 'request_failed_or_interrupted'
        store.save()
        raise FeedError(pending['error']) from None
    # Persist response before validation/publication. A malformed successful
    # response is not purchased again merely because its parser failed.
    pending['response'] = response
    pending['received_at'] = now()
    store.save()
    return pending


def finish_request(store, pending, count=0, row_counts=None, reply_exclusions=None):
    store.data['requests'].append({key: pending[key] for key in
                                  ('kind', 'handle', 'started_at', 'request_id', 'received_at') if key in pending})
    store.data['requests'][-1]['returned_posts'] = count
    store.data['requests'][-1]['query'] = {key: value for key, value in pending['query'].items()
                                         if key in SAFE_QUERY_KEYS}
    if row_counts is not None:
        if sum(row_counts.values()) != count:
            raise FeedError('row_accounting_mismatch')
        store.data['requests'][-1]['row_counts'] = row_counts
    if reply_exclusions is not None:
        store.data['requests'][-1]['reply_exclusions'] = reply_exclusions
    store.data['pending'] = None
    store.save()


def stored_binding(accounts, item):
    """Resolve a verified identity without changing state during offline plans."""
    current = accounts.get(item['handle'])
    if current:
        if item['id'] and item['id'] != current['id']:
            raise FeedError('identity_conflict')
        return item['handle'], current
    if item['id']:
        found = [(name, account) for name, account in accounts.items() if account['id'] == item['id']]
        if found:
            return found[0]
    return item['handle'], None


def binding(store, item):
    name, account = stored_binding(store.data['accounts'], item)
    if account and name != item['handle']:
        account['handle'] = item['handle']
    return name, account


def validate_bindings(store, items):
    """Reject roster aliases selecting the same known account twice."""
    seen = set()
    for item in items:
        _, account = binding(store, item)
        if account:
            if account['id'] in seen:
                raise FeedError('duplicate_account_identity')
            seen.add(account['id'])


def normalize_post(post, expected_id, retrieved, media=None, *, exclude_reposts=False, exclude_replies=False):
    if not isinstance(post, dict) or not isinstance(post.get('id'), str) or not ID.fullmatch(post['id']):
        raise FeedError('invalid_post_id')
    if post.get('author_id') != expected_id:
        raise FeedError('post_author_identity_mismatch')
    for original, alias in (('note_tweet', 'note_post'), ('referenced_tweets', 'referenced_posts'),
                            ('edit_history_tweet_ids', 'edit_history_post_ids')):
        if original in post and alias in post and post[original] != post[alias]:
            raise FeedError('conflicting_post_field_aliases')
    edits = post.get('edit_history_tweet_ids', post.get('edit_history_post_ids', []))
    references = validated_references(post.get('referenced_tweets', post.get('referenced_posts', [])))
    if (not isinstance(edits, list) or any(not isinstance(value, str) or not ID.fullmatch(value) for value in edits)
            or len(edits) != len(set(edits)) or edits and post['id'] not in edits):
        raise FeedError('invalid_edit_history')
    if not isinstance(post.get('attachments', {}), dict) or not isinstance(post.get('entities', {}), dict):
        raise FeedError('invalid_post_metadata')
    created = timestamp(post.get('created_at'))
    parents = [reference for reference in references if reference['type'] == 'replied_to']
    target = post.get('in_reply_to_user_id')
    reply = bool(parents) or target is not None
    reply_reason = None
    if reply:
        if exclude_replies:
            reply_reason = 'legacy_filter'
        elif len(parents) != 1 or any(ref['type'] == 'retweeted' for ref in references):
            reply_reason = 'ambiguous_metadata'
        elif not isinstance(target, str) or not ID.fullmatch(target):
            reply_reason = 'target_unavailable'
        elif target != expected_id:
            reply_reason = 'other_account'
        elif post.get('conversation_id') is not None and (
                not isinstance(post['conversation_id'], str) or not ID.fullmatch(post['conversation_id'])):
            reply_reason = 'ambiguous_metadata'
    if reply_reason or exclude_reposts and any(reference['type'] == 'retweeted' for reference in references):
        # Keep the saved window's filter if a provider still returns an excluded row;
        # retain only enough metadata to advance the cursor, never its body.
        return {'id': post['id'], 'created_at': created, 'source_created_at': post['created_at'],
                'first_retrieved_at': retrieved, 'last_checked_at': retrieved,
                'status': 'excluded', 'edit_history_ids': edits,
                'excluded_reason': 'reply' if reply_reason else 'repost',
                **({'reply_exclusion': reply_reason} if reply_reason else {})}
    reply_metadata = {'in_reply_to_user_id': target, 'conversation_id': post.get('conversation_id')} if reply else {}
    if post.get('withheld'):
        return {'id': post['id'], 'created_at': created, 'source_created_at': post['created_at'], 'first_retrieved_at': retrieved,
                'last_checked_at': retrieved, 'status': 'withheld', 'withheld': post['withheld'],
                'edit_history_ids': edits, 'references': references, **reply_metadata}
    text = post.get('text')
    long = post.get('note_tweet', post.get('note_post'))
    if isinstance(long, dict) and isinstance(long.get('text'), str):
        text = long['text']
    if not isinstance(text, str):
        raise FeedError('missing_post_text')
    text.encode('utf-8')
    result = {'id': post['id'], 'created_at': created, 'source_created_at': post['created_at'],
            'first_retrieved_at': retrieved, 'last_checked_at': retrieved,
            'status': 'available', 'text': text,
            'references': references,
            'attachments': post.get('attachments', {}),
            'entities': post.get('entities', {}),
            'long_post_entities': long.get('entities', {}) if isinstance(long, dict) else {},
            'media_metadata': post.get('media_metadata', {}),
            'edit_history_ids': edits,
            'conversation_id': post.get('conversation_id'), 'withheld': post.get('withheld')}
    result.update(reply_metadata)
    if media is not None:
        keys = post.get('attachments', {}).get('media_keys', [])
        if not isinstance(keys, list) or any(not isinstance(key, str) for key in keys):
            raise FeedError('invalid_attachment_media_keys')
        result['media'] = [value for value in media if value['media_key'] in keys]
    return result


def response_media(response):
    includes = response.get('includes', {})
    if not isinstance(includes, dict):
        raise FeedError('invalid_response_includes')
    if 'media' not in includes:
        return None
    media = includes['media']
    if not isinstance(media, list):
        raise FeedError('invalid_media_expansion')
    result, seen = [], {}
    for item in media:
        if not isinstance(item, dict) or not isinstance(item.get('media_key'), str):
            raise FeedError('invalid_media_expansion')
        key = item['media_key']
        if key in seen and seen[key] != item:
            raise FeedError('conflicting_media_expansion')
        if key in seen:
            continue
        seen[key] = item
        if item.get('type') in {'photo', 'video', 'animated_gif'}:
            result.append({key: value for key, value in item.items() if key in MEDIA_FIELDS.split(',')})
    return result


def apply_response(store):
    """Consume a saved response offline; raises without clearing on ambiguity."""
    pending = store.data['pending']
    if not pending or 'response' not in pending:
        return 0
    response = pending['response']
    handle = pending['handle']
    if pending['kind'] == 'user':
        data = response.get('data')
        if (response.get('errors') or not isinstance(data, dict) or not isinstance(data.get('id'), str) or not ID.fullmatch(data['id'])
                or not isinstance(data.get('username'), str) or not HANDLE.fullmatch(data['username'])
                or data['username'].lower() != handle):
            raise FeedError('user_lookup_not_confirmed')
        if any(account['id'] == data['id'] for account in store.data['accounts'].values()):
            raise FeedError('user_identity_already_bound_use_explicit_id')
        store.data['accounts'][handle] = {'id': data['id'], 'handle': handle, 'filename': handle + '.md',
                                          'posts': {}, 'window': None, 'completed_at': None,
                                          'since_id': None, 'gaps': [], 'published_sha256': None}
        finish_request(store, pending)
        return 0
    account = store.data['accounts'][handle]
    rows = response.get('data', [])
    if not isinstance(rows, list):
        raise FeedError('invalid_posts_response')
    media = response_media(response)
    saved_filter = pending['query'].get('exclude') if pending['kind'] == 'timeline' else None
    exclude_reposts = saved_filter == 'retweets,replies'
    normalized = [normalize_post(post, account['id'], pending['received_at'], media,
                                 exclude_reposts=exclude_reposts, exclude_replies=saved_filter is not None) for post in rows]
    unique = {}
    row_counts = dict.fromkeys(ROW_CATEGORIES, 0)
    reply_exclusions = dict.fromkeys(REPLY_EXCLUSIONS, 0)
    for post in normalized:
        if post['id'] in unique and unique[post['id']] != post:
            raise FeedError('conflicting_duplicate_post_rows')
        if post['status'] == 'excluded':
            row_counts['excluded_replies' if post['excluded_reason'] == 'reply' else 'excluded_reposts'] += 1
            if post['excluded_reason'] == 'reply':
                reply_exclusions[post['reply_exclusion']] += 1
        elif post['id'] in unique:
            row_counts['duplicate_rows'] += 1
        unique[post['id']] = post
    normalized = list(unique.values())

    def identities(post):
        return {post['id']} | set(post.get('edit_history_ids', []))

    def merge_version(post):
        """Keep the newest actually observed version, never superseded text."""
        chain = identities(post)
        related, known = {}, set(chain)
        while True:
            connected = {post_id: old for post_id, old in account['posts'].items()
                         if post_id not in related and known & identities(old)}
            if not connected:
                break
            related.update(connected)
            known.update(identity for old in connected.values() for identity in identities(old))
        if post['status'] == 'excluded':
            for post_id in related:
                account['posts'].pop(post_id)
            return
        if post['id'] in related and post['status'] == 'available':
            for key in ('media', 'assets'):
                if key not in post and key in related[post['id']]:
                    post[key] = related[post['id']][key]
        def source_content(value):
            return {key: item for key, item in value.items()
                    if key not in {'first_retrieved_at', 'last_checked_at', 'assets'}}
        if post['id'] in related and source_content(related[post['id']]) == source_content(post):
            category = 'duplicate_rows'
        elif any(identity != post['id'] for identity in related):
            category = 'merged_versions'
        elif related:
            category = 'updated_existing_posts'
        else:
            category = 'newly_stored_posts'
        row_counts[category] += 1
        candidates = {**related, post['id']: post}
        newest = max(candidates, key=int)
        chosen = dict(candidates[newest])
        # Retrieval time belongs to this exact version ID. A newly fetched edit
        # must not inherit a predecessor's earlier capture time.
        if newest == post['id'] and newest in related:
            chosen['first_retrieved_at'] = related[newest]['first_retrieved_at']
        latest_known = max(known, key=int)
        if int(latest_known) > int(newest):
            chosen = {key: value for key, value in chosen.items() if key in
                      {'id', 'created_at', 'source_created_at', 'first_retrieved_at', 'last_checked_at'}}
            chosen.update(status='superseded', latest_post_id=latest_known,
                          last_checked_at=pending['received_at'])
        if len(known) > 1:
            chosen['edit_history_ids'] = sorted(known, key=int)
        for post_id in related:
            account['posts'].pop(post_id)
        account['posts'][newest] = chosen
    if len(rows) > int(pending['query'].get('max_results', 100)):
        raise FeedError('provider_exceeded_requested_page_limit')
    if pending['kind'] == 'timeline':
        if response.get('errors'):
            raise FeedError('partial_api_error_requires_review')
        window = account['window']
        for post in normalized:
            if instant(post['created_at']) >= instant(window['end']):
                raise FeedError('post_outside_requested_window')
            if 'until_id' in pending['query'] and int(post['id']) >= int(pending['query']['until_id']):
                raise FeedError('post_outside_requested_id_boundary')
            if 'since_id' in pending['query']:
                if int(post['id']) <= int(pending['query']['since_id']):
                    raise FeedError('post_outside_requested_id_boundary')
            elif 'start_time' in pending['query'] and instant(post['created_at']) < instant(pending['query']['start_time']):
                raise FeedError('post_outside_requested_window')
        meta = response.get('meta')
        if not isinstance(meta, dict) or type(meta.get('result_count')) is not int or meta['result_count'] != len(rows):
            raise FeedError('invalid_page_metadata')
        next_token = meta.get('next_token')
        if next_token is not None and (not isinstance(next_token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,2048}', next_token)):
            raise FeedError('invalid_next_token')
        if next_token and next_token in window['seen_tokens']:
            raise FeedError('repeated_pagination_token')
        for post in normalized:
            merge_version(post)
            if window['max_id'] is None or int(post['id']) > int(window['max_id']):
                window['max_id'] = post['id']
            if window.get('oldest_id') is None or int(post['id']) <= int(window['oldest_id']):
                window['oldest_id'], window['oldest_at'] = post['id'], post['created_at']
                # An edited ID may retain an older original creation time;
                # that timestamp cannot prove all earlier IDs have aged out.
                window['oldest_is_edit'] = len(post.get('edit_history_ids', [])) > 1
        window['next_token'] = next_token
        if next_token:
            window['seen_tokens'].append(next_token)
        else:
            account['since_id'] = higher_id(window['max_id'], account['since_id'])
            sample = account.get('sample')
            if sample and sample['status'] == 'in_progress' and sample.pop('pending_forward_window', False):
                # Adopting a sample must finish an already-started forward
                # interval before older saved posts can satisfy its target.
                account['completed_at'] = window['end']
            elif sample and sample['status'] == 'in_progress':
                sample['history_before'] = window['start']
                sample['available_history_exhausted'] = window['start'] is None
                account['completed_at'] = sample['cutoff']
            else:
                account['completed_at'] = max(filter(None, (window['end'], window.get('completed_through'))), key=instant)
                account['history_before'] = account.get('history_before', window['start'])
            account['window'] = None
    elif pending['kind'] == 'reconcile':
        requested = set(pending['query']['ids'].split(','))
        mapping = {}
        for post in normalized:
            matches = {identity for identity in requested & identities(post)
                       if int(identity) <= int(post['id'])}
            if not matches:
                raise FeedError('unrequested_reconciliation_post')
            for identity in matches:
                mapping[identity] = post
        returned = set(mapping)
        removals = set()
        for error in response.get('errors', []):
            # Only explicit resource-level missing/withheld evidence removes
            # text. Generic endpoint/auth/rate-limit failures never do.
            resource = str(error.get('resource_id', error.get('value', '')))
            kind = str(error.get('type', ''))
            if resource in requested and kind in {'https://api.x.com/2/problems/resource-not-found',
                                                   'https://api.twitter.com/2/problems/resource-not-found'}:
                removals.add(resource)
            else:
                raise FeedError('unconfirmed_reconciliation_error')
        if returned | removals != requested:
            raise FeedError('incomplete_reconciliation_response')
        actual_returned = requested & {post['id'] for post in normalized}
        if actual_returned & removals:
            raise FeedError('contradictory_reconciliation_response')
        for post in normalized:
            merge_version(post)
        for post_id in removals:
            affected = [identity for identity, old in account['posts'].items() if post_id in identities(old)]
            for identity in affected:
                old = account['posts'][identity]
                if int(identity) > int(post_id):
                    continue  # A missing predecessor does not delete its newer edit.
                account['posts'][identity] = {key: old[key] for key in
                                             ('id', 'created_at', 'source_created_at', 'first_retrieved_at',
                                              'edit_history_ids', 'latest_post_id') if key in old}
                account['posts'][identity].update(status='unavailable', last_checked_at=pending['received_at'])
    else:
        raise FeedError('unknown_saved_request_kind')
    finish_request(store, pending, len(rows), row_counts, reply_exclusions)
    return len(rows)


def provenance():
    record = note_provenance.verified_record(ROOT, 'feed-collect')
    if Path(__file__).resolve() != ROOT / 'skills/feed-collect/scripts/feed_collect.py':
        raise FeedError('executing_script_outside_verified_plugin')
    return record


def account_status(account):
    """Keep initial sampling, forward completion and unresolved gaps distinct."""
    if account is None:
        return {'status': 'not_started', 'forward_status': 'not_started', 'sample_status': None,
                'completed_through': None, 'requested_through': None,
                'deferred_reasons': ['account_not_started']}
    sample = account.get('sample')
    sample_status = sample['status'] if sample else None
    requested, completed = account.get('requested_through'), account['completed_at']
    forward_pending = requested is not None and (completed is None or instant(completed) < instant(requested))
    reasons = []
    if account.get('recent_deferred_reason'):
        reasons.append(account['recent_deferred_reason'])
    if sample_status == 'in_progress':
        reasons.append('initial_sample_incomplete')
    elif account['window']:
        reasons.append('unfinished_window')
    if forward_pending:
        reasons.append('requested_cutoff_not_reached')
    if account['gaps']:
        reasons.append('known_collection_gaps')
    if sample_status == 'in_progress':
        status = 'initial_sample_in_progress'
    elif account['window'] or forward_pending or account['gaps'] or account.get('recent_deferred_reason'):
        status = 'partial'
    elif sample and not account.get('requested_since'):
        status = 'initial_sample_' + sample_status
    else:
        status = 'bounded_window_complete' if completed else 'not_started'
    if status == 'not_started':
        reasons.append('account_not_started')
    forward_status = ('pending' if forward_pending or account['window'] and sample_status != 'in_progress'
                      else 'complete' if completed else 'not_started')
    return {'status': status, 'forward_status': forward_status, 'sample_status': sample_status,
            'requested_since': account.get('requested_since'),
            'completed_through': completed, 'requested_through': requested, 'deferred_reasons': reasons}


def source_markdown(text, entities=()):
    """Display literal paragraphs with explicit web links, never remote embeds."""
    known = set()
    for container in entities:
        rows = container.get('urls', []) if isinstance(container, dict) else []
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and isinstance(row.get('url'), str):
                known.add(row['url'])
    # Protect destinations from prose escaping. The prefix cannot collide with
    # source text; replacements remain deterministic across offline rerenders.
    prefix = 'FEEDURLTOKEN'
    while prefix in text:
        prefix += 'X'
    links = {}

    def protect(match):
        candidate = match[0]
        exact = [url for url in known if url and candidate.startswith(url)
                 and (candidate == url or re.fullmatch(r'[.,!?;:\u2019\u201d\')\]}]+', candidate[len(url):]))]
        url = max(exact, key=len) if exact else candidate.rstrip('.,!?;:\u2019\u201d\'')
        if not exact:
            while url and url[-1] in ')]}' and url.count(url[-1]) > url.count({')': '(', ']': '[', '}': '{'}[url[-1]]):
                url = url[:-1]
        try:
            parts = urllib.parse.urlsplit(url)
            if parts.scheme.lower() not in {'http', 'https'} or not parts.hostname:
                return candidate
        except ValueError:
            return candidate
        token = prefix + str(len(links)) + 'END'
        # Markdown autolinks preserve literal ampersands; HTML-escaping them
        # here would change both the visible URL and its query parameters.
        links[token] = '<' + url + '>'
        return token + candidate[len(url):]

    text = re.sub(r'https?://[^\s<>"`\\]+', protect, text, flags=re.IGNORECASE)
    text = html.escape(text, quote=False)
    text = re.sub(r'([\\`*_\[\]~$^|#])', r'\\\1', text)
    text = text.replace('%%', r'\%\%').replace('==', r'\=\=')
    lines = []
    for line in text.split('\n'):
        # Source headings, lists and fences must not alter the generated note.
        line = re.sub(r'^(\s*)([#+=-])', r'\1\\\2', line)
        line = re.sub(r'^(\s*\d{1,9})([.)])(?=\s|$)', r'\1\\\2', line)
        # Keep original indentation without turning the paragraph into code.
        line = re.sub(r'^[ \t]+', lambda match: ''.join(
            '&#32;' if char == ' ' else '&#9;' for char in match[0]), line)
        lines.append(line)
    result = '  \n'.join(lines)
    for token, link in links.items():
        result = result.replace(token, link)
    return result


def x_source_markdown(text, entities=()):
    """Decode one X text-entity layer without changing stored text or URL intent.

    Bare URL query strings stay literal unless supplied URL metadata confirms a
    decoded destination. The generic renderer also serves already-decoded RSS
    text and must not perform this provider-specific normalization itself.
    """
    known = {row['url'] for container in entities if isinstance(container, dict)
             for row in (container.get('urls', []) if isinstance(container.get('urls', []), list) else [])
             if isinstance(row, dict) and isinstance(row.get('url'), str)}
    prefix = 'XTEXTURLTOKEN'
    while prefix in text or prefix in html.unescape(text):
        prefix += 'X'
    urls = {}

    def protect(match):
        candidate = match[0]
        decoded = html.unescape(candidate)
        matches = [url for url in known if decoded.startswith(url) and (decoded == url
                   or re.fullmatch(r'[.,!?;:\u2019\u201d\')\]}]+', decoded[len(url):]))]
        # Only authoritative saved URL metadata can resolve an encoded URL.
        if candidate not in known and matches:
            candidate = decoded
        token = prefix + str(len(urls)) + 'END'
        urls[token] = candidate
        return token

    protected = re.sub(r'https?://[^\s<>"`\\]+', protect, text, flags=re.IGNORECASE)
    def decode(match):
        entity = match[0]
        # html.unescape also recognizes legacy name prefixes without a
        # semicolon; require the entire named entity to avoid changing prose.
        return (html.unescape(entity) if entity.startswith('&#')
                else html.entities.html5.get(entity[1:], entity))
    decoded = re.sub(r'&(?:[A-Za-z][A-Za-z0-9]{1,31}|#[0-9]{1,8}|#[xX][0-9A-Fa-f]{1,8});',
                     decode, protected)
    for token, url in urls.items():
        decoded = decoded.replace(token, url)
    return source_markdown(decoded, entities)


def render(account, assets=None):
    note = account.get('note', {})
    lines = ['---', 'sources:', '  - X', 'authors:',
             '  - "[@' + account['handle'] + '](https://x.com/' + account['handle'] + ')"',
             'created: ' + note.get('created', now()[:10]),
             'updated: ' + note.get('updated', now()[:10]),
             'description: ' + json.dumps(account.get('profile', {}).get('description', '')),
             '---', '']
    for post in sorted(account['posts'].values(), key=lambda item: (instant(item['created_at']), int(item['id']))):
        reposts = [reference for reference in post.get('references', []) if reference['type'] == 'retweeted']
        parents = [reference for reference in post.get('references', []) if reference['type'] == 'replied_to']
        self_reply = is_self_reply(post, account['id'])
        label = 'Self-reply' if self_reply else 'Repost' if reposts else 'Original post'
        lines.extend(['## ' + timestamp(post['created_at']).replace('T', ' ').replace('Z', ' UTC'), '',
                      '[' + label + '](https://x.com/i/web/status/' + post['id'] + ')', ''])
        if self_reply:
            links = '[Parent post](https://x.com/i/web/status/' + parents[0]['id'] + ')'
            if post.get('conversation_id'):
                links += ' · [Conversation](https://x.com/i/web/status/' + post['conversation_id'] + ')'
            lines.extend([links, '', 'Thread context may be incomplete; parent and earlier posts are not fetched separately.', ''])
        if reposts:
            lines.extend('Reposted by @' + account['handle'] + ': [Source post](https://x.com/i/web/status/'
                         + reference['id'] + ').' for reference in reposts)
            lines.extend(['', 'Returned repost text may be truncated; the source post is not fetched separately.', ''])
        if post.get('status', 'available') == 'available':
            lines.extend([x_source_markdown(post.get('text', ''),
                                          (post.get('entities', {}), post.get('long_post_entities', {}))), ''])
        else:
            lines.extend(['Source content is unavailable, withheld or superseded.', ''])
        lines.extend(feed_media.render_assets(post, assets or {}))
    return '\n'.join(lines) + '\n'


def anchored_cwd(fd):
    @contextmanager
    def enter():
        before = os.open('.', os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fchdir(fd)
            yield
        finally:
            os.fchdir(before)
            os.close(before)
    return enter()


def publish_account(store, account, vault, record):
    note_provenance.validate_record(record)
    fd = safe_dir(Path(vault) / 'Investments/Sources/X', create=True)
    try:
        filename = account['filename']
        if not re.fullmatch(r'[a-z0-9_]{1,15}\.md', filename):
            raise FeedError('unsafe_account_filename')
        with anchored_cwd(fd):
            # Retain the first snapshot through rendering and publication. The
            # guarded byte read must still refer to that same observed occupant;
            # never take a fresh expected snapshot after deriving the draft.
            expected = atomic_move.regular_file_snapshot(filename) if os.path.lexists(filename) else None
            old = read_at(fd, filename, optional=True)
            if ((expected is None) != (old is None)
                    or (expected is not None
                        and (expected.digest != digest(old)
                             or atomic_move.regular_file_snapshot(filename) != expected))):
                raise FeedError('note_changed_during_initial_read')
            allowed = {account.get('published_sha256'), account.get('prepared_sha256')}
            if old is not None and digest(old) not in allowed:
                raise FeedError('note_ownership_or_edit_conflict')
            metadata = account.get('note')
            if old is not None and digest(old) == account.get('prepared_sha256'):
                metadata = account.get('prepared_note', metadata)
            if metadata is None:
                previous = note_provenance.split_provenance(old.decode('utf-8'))[1] if old else None
                # Migrate the file's known creation date, not its oldest post.
                # On systems without birthtime, record when note tracking began.
                birth = getattr(os.stat(filename, follow_symlinks=False), 'st_birthtime', None) if old else None
                created = datetime.fromtimestamp(birth, timezone.utc).date().isoformat() if birth else now()[:10]
                metadata = {'created': created, 'updated': created,
                            'provenance': previous or {'schema': 1, 'generated_by': record if old is None else None}}
                if metadata['provenance']['generated_by'] is None and 'updated_by' not in metadata['provenance']:
                    metadata['provenance']['updated_by'] = record
            metadata = dict(metadata)
            raw = render(dict(account, note=metadata), store.data.get('assets')).encode('utf-8')
            if old == raw:
                if atomic_move.regular_file_snapshot(filename) != expected:
                    raise FeedError('note_changed_before_unchanged_closeout')
                account['published_sha256'] = digest(raw)
                account['note'] = metadata
                account.pop('prepared_sha256', None)
                account.pop('prepared_note', None)
                store.save()
                return False
            restoring = old is None and digest(raw) == account.get('published_sha256')
            if not restoring:
                metadata['updated'] = now()[:10]
                metadata['provenance'] = dict(metadata['provenance'])
                if old is not None or account.get('note'):
                    metadata['provenance']['updated_by'] = record
            validate_note_metadata(metadata)
            raw = render(dict(account, note=metadata), store.data.get('assets')).encode('utf-8')
            account['prepared_sha256'] = digest(raw)
            account['prepared_note'] = metadata
            store.save()
            check_spelling(fd, filename)
            # The held X-directory descriptor anchors public filenames. Stage
            # beside that directory, outside the source-note scan, on its actual
            # filesystem even if the logical directory is renamed meanwhile.
            stage = tempfile.mkdtemp(prefix='.feed-stage-', dir='..')
            recovery = str(Path(stage).resolve())
            try:
                staged = Path(stage) / 'note.md'
                with staged.open('xb') as handle:
                    handle.write(raw)
                    handle.flush()
                    atomic_move.set_private_mode(handle.fileno(), expected.mode if expected else 0o600)
                    os.fsync(handle.fileno())
                if old is None:
                    published = atomic_move.publish_new(staged, filename, atomic_move.regular_file_snapshot, '..')
                else:
                    published = atomic_move.replace_expected(
                        staged, filename, expected, atomic_move.regular_file_snapshot, stage,
                        stage_parent='..')
                if (published.digest != digest(raw)
                        or atomic_move.regular_file_snapshot(filename) != published):
                    raise FeedError('published_note_changed_during_verification')
                check_spelling(fd, filename)
                os.fsync(fd)
            except Exception as exc:
                extra = getattr(exc, 'recovery_path', None)
                if extra:
                    extra = str(Path(extra).resolve())
                    if extra != recovery:
                        recovery += '; ' + extra
                kind = 'publication_link_unavailable' if isinstance(exc, atomic_move.LinkUnavailable) else 'publication_failed'
                raise FeedError(kind + '; retained_recovery: ' + recovery) from None
            shutil.rmtree(stage)
        account['published_sha256'] = digest(raw)
        account['note'] = metadata
        account.pop('prepared_sha256', None)
        account.pop('prepared_note', None)
        store.save()
        return True
    finally:
        os.close(fd)


def selected(args):
    path = Path(args.accounts_note) if args.accounts_note else Path(args.vault) / 'Investments/x-accounts.md'
    if not path.is_absolute():
        path = Path(args.vault) / path
    try:
        path.absolute().relative_to(Path(args.vault).absolute())
    except ValueError:
        raise FeedError('accounts_note_must_be_inside_vault') from None
    items = roster(path, include_disabled=args.command in {'reconcile', 'resolve-pending', 'status', 'describe'}
                   or args.command == 'publish' and bool(args.account))
    if args.account:
        requested = args.account.lstrip('@').lower()
        items = [item for item in items if item['handle'] == requested]
        if not items:
            raise FeedError('account_not_active_in_roster')
    return items


def preflight_notes(store, items, vault):
    """Refuse lost ownership before buying any source records."""
    try:
        fd = safe_dir(Path(vault) / 'Investments/Sources/X')
    except FileNotFoundError:
        return
    try:
        for item in items:
            _, account = binding(store, item)
            name = account['filename'] if account else item['handle'] + '.md'
            existing = read_at(fd, name, optional=True)
            if existing is not None:
                if not account or digest(existing) not in {account.get('published_sha256'), account.get('prepared_sha256')}:
                    raise FeedError('note_ownership_or_edit_conflict')
    finally:
        os.close(fd)


def higher_id(first, second):
    values = [value for value in (first, second) if value is not None]
    return max(values, key=int) if values else None


def available_count(account):
    return sum(post.get('status') == 'available' for post in account['posts'].values())


def new_window(start, end, since_id=None):
    return {'start': start, 'end': end, 'since_id': since_id, 'next_token': None,
            'seen_tokens': [], 'max_id': since_id, 'exclude': EXCLUDE,
            'fields': {'tweet.fields': FIELDS, 'expansions': 'attachments.media_keys', 'media.fields': MEDIA_FIELDS}}


def prepare_recent(account, floor, cutoff):
    """Keep only the unread, recent part of a window without replaying a page."""
    account['requested_since'] = floor
    account.pop('recent_deferred_reason', None)
    sample = account.get('sample')
    if sample and sample['status'] == 'in_progress':
        sample['status'] = 'superseded_by_recent_window'
    if account['completed_at'] and instant(cutoff) < instant(account['completed_at']):
        # A later completion does not prove the earlier lookback was acquired.
        # Reopening it could overlap paid history, while silently skipping it
        # would falsely claim coverage. Preserve progress and report the limit.
        account['recent_deferred_reason'] = 'requested_cutoff_precedes_saved_completion'
        return
    if (sample and sample['status'] == 'target_reached' and account['window'] is None
            and sample.get('deferred_window')):
        # A finished sample may have omitted more recent posts than its target.
        # Consume that tail before resuming the already completed forward range.
        account['window'] = sample.pop('deferred_window')
    window = account['window']
    if window is None:
        return
    if account['completed_at']:
        window['completed_through'] = max(filter(None, (
            window.get('completed_through'), account['completed_at'])), key=instant)
    if instant(window['end']) > instant(cutoff):
        account['recent_deferred_reason'] = 'saved_window_beyond_requested_cutoff'
        return
    if (instant(window['end']) <= instant(floor)
            or (window.get('oldest_is_edit') is False and window.get('oldest_at')
                and instant(window['oldest_at']) < instant(floor))):
        account.setdefault('retired_windows', []).append({'reason': 'outside_recent_window', 'window': window})
        account['completed_at'] = max(filter(None, (account['completed_at'], window['end'])), key=instant)
        account['since_id'] = higher_id(account['since_id'], window['max_id'])
        account['window'] = None
        return
    if (window['start'] is not None and instant(window['start']) >= instant(floor)
            and window.get('since_id', account['since_id']) is None):
        return  # The exact saved query is still within scope.
    if window['next_token'] and not window.get('oldest_id'):
        # Old releases did not retain the smallest excluded row ID. Guessing
        # from saved eligible posts could buy an already consumed row again.
        account['recent_deferred_reason'] = 'legacy_cursor_needs_recent_boundary'
        return
    replacement = new_window(max(filter(None, (window['start'], floor)), key=instant), window['end'])
    for key in ('exclude', 'fields', 'max_id', 'oldest_id', 'oldest_at', 'oldest_is_edit', 'until_id', 'completed_through'):
        if key in window:
            replacement[key] = window[key]
    if 'fields' not in window:
        replacement.pop('fields')  # Preserve the legacy default selection, too.
    if window.get('oldest_id'):
        replacement['until_id'] = window['oldest_id']
    # until_id is exclusive and replaces the old end_time. It resumes below
    # every consumed row (including excluded replies), while start_time caps age.
    account.setdefault('retired_windows', []).append({'reason': 'recent_window_rebased', 'window': window})
    account['window'] = replacement


def prepare_sample(account, target, cutoff, history_before=None):
    """Adopt an initial target without resetting paid progress or old cursors."""
    existing = account.get('sample')
    if existing:
        if target is not None and target != existing['target']:
            raise FeedError('initial_sample_target_already_fixed')
        return
    if target is None:
        return
    window = account['window']
    bound = account.get('history_before')
    if account['completed_at'] and available_count(account) < target and bound is None:
        # Legacy completed state did not retain its lower time boundary. Its
        # retained IDs cannot recover excluded paid rows, especially for an
        # empty feed. Require a caller-supplied known old boundary; never guess.
        if history_before is None:
            raise FeedError('legacy_completed_sample_requires_history_before')
        bound = timestamp(history_before)
        if instant(bound) >= instant(account['completed_at']):
            raise FeedError('history_before_must_precede_completed_window')
    sample_cutoff = window['end'] if window else account['completed_at'] or cutoff
    account['sample'] = {'target': target, 'cutoff': sample_cutoff, 'status': 'in_progress',
                         'history_before': bound, 'available_history_exhausted': False}
    if window is not None and account['completed_at'] is not None:
        account['sample']['pending_forward_window'] = True
    if window is None and not account['completed_at']:
        account['window'] = new_window(None, sample_cutoff)


def advance_sample(account):
    """Stop a satisfied sample; preserve any older page cursor as omitted history."""
    sample = account.get('sample')
    if not sample or sample['status'] != 'in_progress':
        return
    if sample.get('pending_forward_window') and account['window'] is not None:
        return
    if available_count(account) >= sample['target']:
        if account['window']:
            sample['deferred_window'] = account['window']
            account['since_id'] = higher_id(account['since_id'], account['window']['max_id'])
        account['completed_at'] = sample['cutoff']
        account['window'] = None
        sample['status'] = 'target_reached'
    elif sample['available_history_exhausted']:
        sample['status'] = 'available_history_exhausted'
    elif account['window'] is None:
        bound = sample['history_before']
        if bound is None:
            raise FeedError('sample_history_boundary_unavailable')
        # end_time is exclusive in the X API. The older window abuts, but does
        # not overlap, the already consumed start_time-inclusive window.
        account['window'] = new_window(None, bound)


def request_accounting(requests):
    totals = dict.fromkeys(ROW_CATEGORIES, 0)
    reply_exclusions = dict.fromkeys(REPLY_EXCLUSIONS, 0)
    legacy = 0
    unexpected = 0
    legacy_filters, self_reply_queries, unknown_filters = [], [], []
    for request in requests:
        if 'row_counts' in request:
            for key in ROW_CATEGORIES:
                totals[key] += request['row_counts'].get(key, 0)
        else:
            legacy += request.get('returned_posts', 0)
        for key in REPLY_EXCLUSIONS:
            reply_exclusions[key] += request.get('reply_exclusions', {}).get(key, 0)
        if request.get('query', {}).get('exclude') is not None:
            unexpected += sum(request.get('row_counts', {}).get(key, 0) for key in ('excluded_replies', 'excluded_reposts'))
        if request.get('kind') == 'timeline':
            query = request.get('query', {})
            if query.get('exclude') in ('replies', 'retweets,replies'):
                legacy_filters.append(query)
            elif 'exclude' not in query and 'in_reply_to_user_id' in query.get('tweet.fields', '').split(','):
                self_reply_queries.append(query)
            else:
                unknown_filters.append(query)
    return {'row_counts': totals, 'legacy_unclassified_rows': legacy,
            'reply_exclusions': reply_exclusions,
            'reply_collection': {'legacy_filtered_requests': len(legacy_filters),
                                 'self_reply_enabled_requests': len(self_reply_queries),
                                 'unknown_filter_requests': len(unknown_filters),
                                 'first_self_reply_window_start': self_reply_queries[0].get('start_time') if self_reply_queries else None,
                                 'prior_filtered_history_not_backfilled': bool(legacy_filters)},
            'accounted_returned_rows': sum(totals.values()) + legacy,
            'unexpected_filter_rows': unexpected}


def process_attachments(store, items, args, *, download):
    posts = [post for item in items for account in [binding(store, item)[1]]
             if account for post in account['posts'].values()]
    return feed_media.collect_assets(
        args.vault, posts, store.data.setdefault('assets', {}), store.save,
        max_downloads=args.max_downloads if download else 0,
        max_bytes=args.max_attachment_bytes, retry=args.retry_attachments if download else False)


def retire_attachments(store, vault):
    # Scan every note after publication. Do not ignore a generated filename:
    # an old or manually edited note can still refer to an otherwise orphaned file.
    posts = [post for account in store.data['accounts'].values() for post in account['posts'].values()]
    return feed_media.retire_assets(vault, posts, store.data.get('assets', {}), store.save)


def collect(args, fetch=request_json, record=None):
    items = selected(args)
    bearer = token(args)
    record = record or provenance()
    counts = {'requests': 0, 'returned_posts': 0, 'published_notes': 0, 'resumed_pages': 0,
              'resumed_returned_posts': 0}
    with Store(args.vault, create=True) as store:
        validate_bindings(store, items)
        preflight_notes(store, items, args.vault)
        first_request = len(store.data['requests'])
        before_ids = {post_id for account in store.data['accounts'].values() for post_id in account['posts']}
        if store.data['pending']:
            if 'response' in store.data['pending']:
                counts['resumed_pages'] += store.data['pending']['kind'] == 'timeline'
                counts['resumed_returned_posts'] += apply_response(store)
            else:
                raise FeedError('unresolved_request_blocks_network')
        started = instant(args.until) if args.until else datetime.now(timezone.utc).replace(microsecond=0)
        cutoff = timestamp((started if args.until else started - timedelta(seconds=30)).isoformat())
        initial = timestamp((started - timedelta(days=3)).isoformat())
        recent = args.latest is None
        counts['requested_since'] = initial if recent else None
        counts['requested_through'] = cutoff
        for item in items:
            _, account = binding(store, item)
            if account:
                account['requested_through'] = cutoff
                if recent:
                    prepare_recent(account, initial, cutoff)
                else:
                    account.pop('requested_since', None)
                    account.pop('recent_deferred_reason', None)
                    prepare_sample(account, args.latest, cutoff, args.history_before)
                    advance_sample(account)
        validate_state(store.data)
        store.save()
        start = store.data['round_robin'] % len(items)
        queue = items[start:] + items[:start]
        # One page per account per round; unfinished noisy accounts cannot
        # consume every invocation before quieter accounts receive a turn.
        remaining = list(queue)
        while (remaining and (args.max_requests is None or counts['requests'] < args.max_requests)
               and (args.max_posts is None or counts['returned_posts'] + 5 <= args.max_posts)):
            item = remaining.pop(0)
            name, account = binding(store, item)
            if account is None:
                if item['id']:
                    raise FeedError('explicit_id_requires_existing_verified_binding')
                paid_request(store, 'user', name, '/2/users/by/username/' + name, {}, bearer, fetch)
                counts['requests'] += 1
                apply_response(store)
                name, account = binding(store, item)
                account['requested_through'] = cutoff
                if recent:
                    prepare_recent(account, initial, cutoff)
                else:
                    prepare_sample(account, args.latest, cutoff, args.history_before)
                    advance_sample(account)
                store.save()
                if args.max_requests is not None and counts['requests'] >= args.max_requests:
                    remaining.append(item)
                    break
            if account.get('recent_deferred_reason'):
                continue
            if account['window'] is None:
                begin = account['completed_at'] or initial
                if recent:
                    begin = max(begin, initial, key=instant)
                if instant(begin) >= instant(cutoff):
                    continue
                account['window'] = new_window(begin, cutoff, None if recent else account['since_id'])
                store.save()
            window = account['window']
            resumed = bool(window['next_token'])
            page_size = 100 if args.max_posts is None else min(100, args.max_posts - counts['returned_posts'])
            sample = account.get('sample')
            if sample and sample['status'] == 'in_progress' and not sample.get('pending_forward_window'):
                page_size = min(page_size, max(5, sample['target'] - available_count(account)))
            query = {'max_results': page_size, **window.get('fields', {'tweet.fields': LEGACY_FIELDS}),
                     'end_time': window['end']}
            if window['exclude'] is not None:
                query['exclude'] = window['exclude']
            boundary_id = window.get('since_id', account['since_id'])
            if boundary_id:
                query['since_id'] = boundary_id
            elif window['start'] is not None:
                query['start_time'] = window['start']
            if window.get('until_id'):
                query['until_id'] = window['until_id']
            if window['next_token']:
                query['pagination_token'] = window['next_token']
            paid_request(store, 'timeline', name, '/2/users/' + account['id'] + '/tweets', query, bearer, fetch)
            counts['requests'] += 1
            counts['returned_posts'] += apply_response(store)
            counts['resumed_pages'] += resumed
            if recent:
                prepare_recent(account, initial, cutoff)
            else:
                advance_sample(account)
            store.data['round_robin'] = (items.index(item) + 1) % len(items)
            store.save()
            if account['window'] or (account['completed_at'] is not None and instant(account['completed_at']) < instant(cutoff)):
                remaining.append(item)
        counts['attachments'] = process_attachments(store, items, args, download=True)
        for item in items:
            _, account = binding(store, item)
            if account:
                counts['published_notes'] += publish_account(store, account, args.vault, record)
        counts['attachment_cleanup'] = retire_attachments(store, args.vault)
        counts['stored_posts'] = sum(len(account['posts']) for account in store.data['accounts'].values())
        after_ids = {post_id for account in store.data['accounts'].values() for post_id in account['posts']}
        counts['newly_stored_posts'] = len(after_ids - before_ids)
        counts.update(request_accounting(store.data['requests'][first_request:]))
        counts['processed_rows'] = counts['returned_posts'] + counts['resumed_returned_posts']
        budget_stops = []
        if args.max_requests is not None and counts['requests'] >= args.max_requests:
            budget_stops.append('request_budget_exhausted')
        if args.max_posts is not None and counts['returned_posts'] + 5 > args.max_posts:
            budget_stops.append('post_budget_below_minimum_page')
        counts['accounts'] = []
        for item in items:
            _, account = binding(store, item)
            progress = account_status(account)
            if any(reason != 'known_collection_gaps' for reason in progress['deferred_reasons']):
                progress['deferred_reasons'].extend(budget_stops)
            counts['accounts'].append({'handle': item['handle'],
                                       **progress,
                                       'description_missing': not bool(account and account.get('profile')),
                                       'sample': account.get('sample') if account else None,
                                       'stored_posts': len(account['posts']) if account else 0,
                                       **request_accounting([request for request in store.data['requests']
                                                              if account and request.get('handle') == account['filename'][:-3]]),
                                       'output': str(Path(args.vault) / 'Investments/Sources/X' / account['filename']) if account else None})
        counts['partial_accounts'] = sum(row['status'] in {'partial', 'initial_sample_in_progress'} for row in counts['accounts'])
        counts['deferred_accounts'] = [row['handle'] for row in counts['accounts'] if row['deferred_reasons']]
    return counts


def execute(args):
    # An unresolved paid request must remain recoverable even if its roster
    # entry was removed or the source-list note is temporarily unavailable.
    items = [] if args.command == 'resolve-pending' else selected(args)
    if args.command in {'plan', 'status'}:
        state_path = Path(args.vault) / 'Investments/Sources/.feed-collect'
        data = None
        try:
            fd = safe_dir(state_path)
        except FileNotFoundError:
            pass
        else:
            try:
                raw = read_at(fd, 'state.json', optional=True)
                if raw is None and read_at(fd, 'collector.lock', optional=True) is not None:
                    raise FeedError('missing_existing_state_requires_recovery')
                data = validate_state(decode(raw)) if raw is not None else None
            finally:
                os.close(fd)
        bound_accounts = {item['handle']: stored_binding(data['accounts'], item)[1] if data else None
                          for item in items}
        return {'active_accounts': items, 'requests': 0,
                'missing_descriptions': [item['handle'] for item in items
                                         if not (bound_accounts[item['handle']] or {}).get('profile')],
                'collection_mode': 'recent_72_hours' if args.latest is None else 'initial_sample',
                'max_requests': args.max_requests, 'max_posts': args.max_posts,
                'credential_available': bool(token(args)) if args.credentials_file else bool(os.environ.get('X_BEARER_TOKEN')),
                'stored_accounts': len(data['accounts']) if data else 0,
                'stored_posts': sum(len(account['posts']) for account in data['accounts'].values()) if data else 0,
                'accounts': [{'handle': account['handle'], 'stored_posts': len(account['posts']),
                              **account_status(account),
                              'sample': account.get('sample'),
                              **request_accounting([request for request in data['requests'] if request.get('handle') == name])}
                             for name, account in data['accounts'].items()] if data else [],
                'pending_request': ({key: value for key, value in data['pending'].items() if key != 'response'}
                                    if data and data['pending'] else None)}
    if args.command == 'collect':
        return collect(args)
    with Store(args.vault) as store:
        if args.command == 'resolve-pending':
            pending = store.data['pending']
            if not pending:
                raise FeedError('no_pending_request')
            if args.outcome == 'retry' and not args.allow_possible_repeat_charge:
                raise FeedError('retry_requires_possible_repeat_charge_acknowledgment')
            if args.outcome == 'retry' and 'response' in pending:
                raise FeedError('saved_response_must_be_consumed_offline_not_retried')
            if args.outcome == 'abandon':
                if pending['handle'] in store.data['accounts']:
                    account = store.data['accounts'][pending['handle']]
                    account['gaps'].append({'request_id': pending['request_id'], 'kind': pending['kind'], 'at': now()})
                    if pending['kind'] == 'timeline':
                        sample = account.get('sample')
                        if sample and sample['status'] == 'in_progress':
                            sample['status'] = 'abandoned'
                            sample['deferred_window'] = account['window']
                            account['completed_at'] = sample['cutoff']
                        else:
                            account['completed_at'] = account['window']['end']
                        # An abandoned window is an explicit gap. Using the old
                        # since_id would override start_time and silently replay
                        # that paid/uncertain interval on the next collection.
                        account['since_id'] = None
                        account['window'] = None
                else:
                    store.data.setdefault('unbound_gaps', []).append({'handle': pending['handle'], 'at': now()})
            store.data['requests'].append({'kind': pending['kind'], 'request_id': pending['request_id'],
                                          'resolution': args.outcome, 'possible_charge': True})
            store.data['pending'] = None
            store.save()
            return {'requests': 0, 'resolved': args.outcome, 'possible_charge': True}
        validate_bindings(store, items)
        record = provenance()
        if args.command == 'describe':
            if not args.account or len(items) != 1:
                raise FeedError('describe_requires_one_account')
            profile = {'description': args.description, 'sources': args.description_source or [], 'checked_at': now()}
            validate_profile(profile)
            _, account = binding(store, items[0])
            if account is None:
                raise FeedError('description_requires_stored_account')
            preflight_notes(store, items, args.vault)
            previous = account.get('profile', {})
            if any(profile[key] != previous.get(key) for key in ('description', 'sources')):
                account['profile'] = profile
                store.save()
            return {'requests': 0, 'published_notes': int(publish_account(store, account, args.vault, record))}
        if args.command in {'publish', 'attachments'}:
            preflight_notes(store, items, args.vault)
            apply_response(store)
            attachments = process_attachments(store, items, args, download=args.command == 'attachments')
            changed = 0
            for item in items:
                _, account = binding(store, item)
                if account:
                    advance_sample(account)
                    changed += publish_account(store, account, args.vault, record)
            return {'requests': 0, 'published_notes': changed, 'attachments': attachments,
                    'attachment_cleanup': retire_attachments(store, args.vault)}
        if args.command == 'reconcile':
            if not args.allow_paid_reread or not args.ids or len(items) != 1:
                raise FeedError('reconcile_requires_account_ids_and_paid_reread_acknowledgment')
            ids = args.ids.split(',')
            if len(ids) > (100 if args.max_posts is None else min(100, args.max_posts)) or len(ids) != len(set(ids)) or any(not ID.fullmatch(item) for item in ids):
                raise FeedError('invalid_reconciliation_ids')
            name, account = binding(store, items[0])
            known_ids = ({identity for post in account['posts'].values()
                          for identity in [post['id'], *post.get('edit_history_ids', [])]} if account else set())
            if not account or not set(ids) <= known_ids:
                raise FeedError('reconciliation_requires_stored_ids')
            preflight_notes(store, items, args.vault)
            paid_request(store, 'reconcile', name, '/2/tweets', {'ids': ','.join(ids), 'tweet.fields': FIELDS,
                         'expansions': 'attachments.media_keys', 'media.fields': MEDIA_FIELDS}, token(args), request_json)
            count = apply_response(store)
            attachments = process_attachments(store, items, args, download=True)
            changed = publish_account(store, account, args.vault, record)
            return {'requests': 1, 'returned_posts': count, 'published_notes': int(changed),
                    'attachments': attachments, 'attachment_cleanup': retire_attachments(store, args.vault),
                    **request_accounting(store.data['requests'][-1:])}
    raise FeedError('unsupported_command')


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('--test', action='store_true', help='Run offline reliability and security tests.')
    result.add_argument('command', nargs='?', choices=('plan', 'status', 'collect', 'publish', 'attachments', 'reconcile', 'resolve-pending', 'describe'))
    result.add_argument('--vault')
    result.add_argument('--accounts-note')
    result.add_argument('--account')
    result.add_argument('--credentials-file')
    result.add_argument('--description', help='Verified short account-owner background for offline describe.')
    result.add_argument('--description-source', action='append', help='Supporting public URL; repeat for multiple sources.')
    result.add_argument('--max-requests', type=int, help='Optional total paid API request cap; default completes the requested window.')
    result.add_argument('--max-posts', type=int, help='Optional total returned-post cap; default completes the requested window.')
    result.add_argument('--max-downloads', type=int, help='Optional attachment HTTP request cap, including redirects; default completes saved eligible attachments, zero defers downloads.')
    result.add_argument('--max-attachment-bytes', type=int, help='Optional total attachment response-byte cap; default has no aggregate cap, zero defers downloads. Per-file limits always apply.')
    result.add_argument('--retry-attachments', action='store_true', help='Retry failed/interrupted file downloads; never rereads X posts.')
    result.add_argument('--latest', type=int, help='Explicit historical sample target per account (1–800); overrides the normal 72-hour scope.')
    result.add_argument('--history-before', help='Known exclusive older-history boundary for legacy completed windows without saved lower bounds.')
    result.add_argument('--until', help='UTC collection cutoff; defaults to 30 seconds before now.')
    result.add_argument('--ids', help='Comma-separated stored IDs for explicit reconciliation.')
    result.add_argument('--allow-paid-reread', action='store_true')
    result.add_argument('--outcome', choices=('retry', 'abandon'))
    result.add_argument('--allow-possible-repeat-charge', action='store_true')
    return result


def run_self_test():
    import unittest
    class Tests(unittest.TestCase):
        def test_literal_source(self):
            post = {'id': '123', 'created_at': '2026-09-07T00:00:00Z',
                    'text': '<!-- skill-provenance: evil --> ``` [[bad]] <script>bad</script>'}
            account = {'id': '12', 'handle': 'example', 'window': None, 'gaps': [],
                       'completed_at': None, 'posts': {'123': post}}
            result = render(account)
            self.assertNotIn('<!-- skill-provenance', result)
            self.assertNotIn('<script>', result)
            self.assertNotIn('<pre', result)
            self.assertIn(r'\[\[bad\]\]', result)
            self.assertIn('&lt;script&gt;bad&lt;/script&gt;', result)
        def test_subsecond_timestamp_is_preserved_and_compared_as_time(self):
            source = {'id': '123', 'author_id': '12', 'created_at': '2026-09-07T01:00:00.123-07:00', 'text': 'raw'}
            post = normalize_post(source, '12', '2026-09-07T10:00:00Z')
            self.assertEqual(post['source_created_at'], source['created_at'])
            self.assertEqual(post['created_at'], '2026-09-07T08:00:00.123000Z')
            self.assertGreater(instant(post['created_at']), instant('2026-09-07T08:00:00Z'))
            with self.assertRaises(FeedError):
                timestamp('2026-09-07')
        def test_x_entities_decode_once_without_changing_literal_url_queries(self):
            text = 'S&amp;P; literal &amp;amp; https://example.com/?literal=&amp;value'
            result = x_source_markdown(text)
            self.assertIn('S&amp;P; literal &amp;amp;', result)
            self.assertIn('<https://example.com/?literal=&amp;value>', result)
            self.assertEqual(source_markdown('S&amp;P'), 'S&amp;amp;P')
        def test_self_reply_requires_verified_target_and_keeps_parent(self):
            source = {'id': '123', 'author_id': '12', 'created_at': '2026-09-07T01:00:00Z', 'text': 'continuation',
                      'in_reply_to_user_id': '12', 'referenced_tweets': [{'id': '122', 'type': 'replied_to'}]}
            post = normalize_post(source, '12', '2026-09-07T10:00:00Z')
            self.assertTrue(is_self_reply(post, '12'))
            self.assertEqual(post['references'][0]['id'], '122')
            source['in_reply_to_user_id'] = '13'
            self.assertEqual(normalize_post(source, '12', '2026-09-07T10:00:00Z')['reply_exclusion'], 'other_account')
            source.pop('in_reply_to_user_id')
            self.assertEqual(normalize_post(source, '12', '2026-09-07T10:00:00Z')['reply_exclusion'], 'target_unavailable')
        def test_roster_ignores_examples(self):
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder).resolve() / 'accounts.md'
                path.write_text('```\n- [x] @example\n```\n<!--\n- [x] @comment\n-->\n    - [x] @indented\n- [x] @actual\n- [ ] @paused\n', encoding='utf-8')
                self.assertEqual(roster(path), [{'handle': 'actual', 'id': None}])
        def test_ambiguous_request_persists(self):
            with tempfile.TemporaryDirectory() as folder:
                vault = Path(folder).resolve()
                with Store(vault, True) as store:
                    def fail(*args):
                        raise TimeoutError('secret transport text')
                    with self.assertRaises(FeedError):
                        paid_request(store, 'user', 'actual', '/2/users/by/username/actual', {}, 'secret', fail)
                    self.assertNotIn('secret', encoded(store.data).decode())
                with Store(vault) as store:
                    self.assertIsNotNone(store.data['pending'])
                    with self.assertRaisesRegex(FeedError, 'blocks_network'):
                        paid_request(store, 'user', 'actual', '/2/users/by/username/actual', {}, 'secret', fail)
        def test_saved_user_response_offline(self):
            with tempfile.TemporaryDirectory() as folder:
                with Store(Path(folder).resolve(), True) as store:
                    paid_request(store, 'user', 'actual', '/2/users/by/username/actual', {}, 'secret',
                                 lambda *args: {'data': {'id': '12', 'username': 'actual'}})
                with Store(Path(folder).resolve()) as store:
                    apply_response(store)
                    self.assertEqual(store.data['accounts']['actual']['id'], '12')
                    self.assertIsNone(store.data['pending'])
        def test_state_does_not_adopt_external_edit(self):
            with tempfile.TemporaryDirectory() as folder:
                with Store(Path(folder).resolve(), True) as store:
                    replacement = encoded({'unrelated': 'manual occupant'})
                    (store.path / 'state.json').write_bytes(replacement)
                    with self.assertRaisesRegex(FeedError, 'state_publication_conflict'):
                        store.save()
                    self.assertEqual((store.path / 'state.json').read_bytes(), replacement)
        def test_missing_state_is_not_reinitialized(self):
            with tempfile.TemporaryDirectory() as folder:
                vault = Path(folder).resolve()
                with Store(vault, True) as store:
                    state_path = store.path / 'state.json'
                state_path.unlink()
                with self.assertRaisesRegex(FeedError, 'requires_recovery'):
                    Store(vault, True)
        def test_empty_existing_state_is_not_reinitialized(self):
            with tempfile.TemporaryDirectory() as folder:
                vault = Path(folder).resolve()
                with Store(vault, True) as store:
                    state_path = store.path / 'state.json'
                state_path.write_bytes(b'')
                with self.assertRaisesRegex(FeedError, 'invalid_json'):
                    Store(vault, True)
                self.assertEqual(state_path.read_bytes(), b'')
        def test_user_lookup_rejects_nonstring_identity(self):
            for row in ({'id': 12, 'username': 'actual'}, {'id': '12', 'username': 12}):
                with tempfile.TemporaryDirectory() as folder:
                    with Store(Path(folder).resolve(), True) as store:
                        paid_request(store, 'user', 'actual', '/2/users/by/username/actual', {}, 'secret',
                                     lambda *args: {'data': row})
                        with self.assertRaisesRegex(FeedError, 'user_lookup_not_confirmed'):
                            apply_response(store)
                        self.assertEqual(store.data['accounts'], {})
                        self.assertIn('response', store.data['pending'])
        def test_concurrent_lock_blocks(self):
            with tempfile.TemporaryDirectory() as folder:
                vault = Path(folder).resolve()
                with Store(vault, True):
                    with self.assertRaises(BlockingIOError):
                        Store(vault, True)
        def test_saved_page_deduplicates_and_commits_cursor(self):
            with tempfile.TemporaryDirectory() as folder:
                with Store(Path(folder).resolve(), True) as store:
                    paid_request(store, 'user', 'actual', '/2/users/by/username/actual', {}, 'secret',
                                 lambda *args: {'data': {'id': '12', 'username': 'actual'}})
                    apply_response(store)
                    account = store.data['accounts']['actual']
                    account['window'] = new_window('2026-09-01T00:00:00Z', '2026-09-07T00:00:00Z')
                    row = {'id': '123', 'author_id': '12', 'created_at': '2026-09-06T00:00:00Z',
                           'text': 'preview', 'note_post': {'text': 'complete source'}}
                    response = {'data': [row, row], 'meta': {'result_count': 2}}
                    paid_request(store, 'timeline', 'actual', '/2/users/12/tweets',
                                 {'max_results': 5, **account['window']['fields']}, 'secret', lambda *args: response)
                with Store(Path(folder).resolve()) as store:
                    self.assertEqual(apply_response(store), 2)
                    account = store.data['accounts']['actual']
                    self.assertEqual(len(account['posts']), 1)
                    self.assertEqual(account['posts']['123']['text'], 'complete source')
                    self.assertEqual(account['since_id'], '123')
                    self.assertIsNone(account['window'])
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
    if ((args.max_requests is not None and args.max_requests < 1)
            or (args.max_posts is not None and args.max_posts < 5)):
        parser().error('optional budgets: requests at least 1, posts at least 5')
    if args.latest is not None and not 1 <= args.latest <= 800:
        parser().error('--latest must be 1–800')
    if ((args.max_downloads is not None and args.max_downloads < 0)
            or (args.max_attachment_bytes is not None and args.max_attachment_bytes < 0)):
        parser().error('optional attachment budgets must be nonnegative integers')
    if args.history_before and args.latest is None:
        parser().error('--history-before requires --latest')
    if args.command == 'resolve-pending' and not args.outcome:
        parser().error('resolve-pending requires --outcome')
    try:
        print(json.dumps({'ok': True, **execute(args)}, sort_keys=True))
        return 0
    except Exception as exc:
        # Never echo upstream bodies, credentials, arbitrary filesystem errors
        # or untrusted exceptions into an agent-visible diagnostic.
        error = str(exc) if isinstance(exc, FeedError) else 'local_setup_or_storage_error'
        print(json.dumps({'ok': False, 'error': error, 'inspect_status_before_any_retry': True}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
