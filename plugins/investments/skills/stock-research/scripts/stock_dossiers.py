#!/usr/bin/env python3
"""Maintain stock snapshots from immutable daily assessments; no network or reasoning.

Daily reports remain the historical record. Private write-ahead receipts bind every
managed snapshot to its exact predecessor and support safe retry after interruption.
All commands print JSON. Never run this module concurrently in one process: pinned
publication temporarily changes and restores the working directory.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile

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

import market_notes

MAX_BYTES = 2 * 1024 * 1024
SYMBOL = re.compile(r'[A-Z][A-Z0-9.-]{0,14}\Z')
EXCHANGE = re.compile(r'[A-Z][A-Z0-9]{1,15}\Z')
HEADING = re.compile(r'([A-Z][A-Z0-9]{1,15}):([A-Z][A-Z0-9.-]{0,14}) — (\S.*\S|\S)\Z')
STATES = {'ready', 'watch', 'rejected', 'invalidated', 'expired'}
ID = re.compile(r'[A-Z][A-Z0-9_-]{1,15}:[A-Za-z0-9._-]{1,64}\Z')


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique)


def _bytes(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + '\n').encode()


def _read(path):
    before = atomic_move.regular_file_snapshot(path)
    if before.size > MAX_BYTES:
        raise ValueError('dossier input exceeds size limit')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError('dossier input must be a regular file')
        data = stream.read(MAX_BYTES + 1)
        identity = (opened.st_dev, opened.st_ino, stat.S_IFMT(opened.st_mode))
    if (identity != before.identity or len(data) > MAX_BYTES or _hash(data) != before.digest
            or atomic_move.regular_file_snapshot(path) != before):
        raise ValueError('dossier input changed while reading')
    data.decode('utf-8')
    return data, before


def candidates(data):
    """Extract canonical H4 stock assessments, ignoring headings in fenced code."""
    text, _ = note_provenance.split_provenance(data.decode('utf-8'))
    lines, headings, fence = text.splitlines(), [], None
    for index, line in enumerate(lines):
        opened = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if fence:
            if opened and opened[1][0] == fence[0] and len(opened[1]) >= len(fence) and not opened[2].strip():
                fence = None
            continue
        if opened:
            fence = opened[1]
            continue
        heading = re.fullmatch(r' {0,3}(#{1,6})[ \t]+(.*?)[ \t]*', line)
        if heading:
            headings.append((index, len(heading[1]), heading[2]))
    sections = [row for row in headings if row[1:] == (3, 'Candidate assessments')]
    if len(sections) != 1:
        raise ValueError('daily report needs one Candidate assessments section')
    start = sections[0][0]
    end = next((at for at, depth, _ in headings if at > start and depth <= 3), len(lines))
    result, seen = [], set()
    for at, depth, title in headings:
        if not start < at < end or depth != 4:
            continue
        match = HEADING.fullmatch(title)
        if not match:
            if (re.match(r'[A-Za-z][A-Za-z0-9]{1,15}:', title)
                    or re.match(r'[A-Z][A-Z0-9.-]{0,14} [—–-] ', title)):
                raise ValueError('stock assessment heading must be EXCHANGE:TICKER — Company: ' + title)
            continue
        exchange, ticker, company = match.groups()
        if ticker in seen:
            raise ValueError('duplicate or ambiguous stock assessment: ' + ticker)
        seen.add(ticker)
        stop = next((i for i, level, _ in headings if i > at and level <= 4), len(lines))
        body = '\n'.join(lines[at + 1:stop]).strip() + '\n'
        statuses = re.findall(r'^Status: ([a-z]+)[ \t]*$', body, re.M)
        if len(statuses) != 1 or statuses[0] not in STATES:
            raise ValueError('stock assessment needs exactly one valid Status: line: ' + title)
        company_ids = re.findall(r'^Company ID: (.+?)[ \t]*$', body, re.M)
        if len(company_ids) > 1 or (company_ids and not ID.fullmatch(company_ids[0])):
            raise ValueError('invalid or duplicate Company ID: ' + title)
        if not re.search(r'\[\[Investments/Stocks/' + re.escape(ticker)
                         + r'(?:\.md)?(?:#[^\]\n|]+)?(?:\|[^\]\n]+)?\]\]', body):
            raise ValueError('stock assessment must link its dossier: ' + ticker)
        if len(body.splitlines()) < 4:
            raise ValueError('stock assessment has no substantive text: ' + title)
        result.append({'ticker': ticker, 'exchange': exchange, 'company': company,
                       'company_id': company_ids[0] if company_ids else None,
                       'heading': title, 'status': statuses[0], 'assessment': body})
    return result


def _identity(fd):
    item = os.fstat(fd)
    return item.st_dev, item.st_ino


class _pinned:
    def __init__(self, fd):
        self.fd = fd
        self.previous = None

    def __enter__(self):
        self.previous = os.open('.', os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fchdir(self.fd)
        except BaseException:
            os.close(self.previous)
            self.previous = None
            raise
        return self

    def __exit__(self, *args):
        try:
            os.fchdir(self.previous)
        finally:
            os.close(self.previous)


def _directory(parent, name, create=False, private=False):
    with _pinned(parent):
        owners = [n for n in os.listdir('.') if portable_identity(n) == portable_identity(name)]
        if owners and owners != [name]:
            raise ValueError('portable-equivalent folder collision: ' + name)
        if not owners and create:
            os.mkdir(name, 0o700 if private else 0o755)
        if not os.path.lexists(name):
            return None
        return os.open(name, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0))


class Store:
    def __init__(self, vault, create=False, *, _lock_descriptor=None):
        import fcntl
        self.vault = Path(vault).expanduser().resolve(strict=True)
        self.fds = []
        flags = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0)
        try:
            self.root = os.open(self.vault, flags)
            self.fds.append(self.root)
            if _lock_descriptor is not None:
                # The daily publisher already owns this exact directory lock.
                # Reopening/flocking it would conflict with our own publication.
                # Only read-only nested context accepts its live descriptor.
                if create or _identity(_lock_descriptor) != _identity(self.root):
                    raise ValueError('inherited research lock does not match this read-only vault')
            else:
                try:
                    fcntl.flock(self.root, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise ValueError('another research publication is in progress; retry afterwards') from exc
            self.investments = self._child(self.root, 'Investments', create)
            self.stocks = self._child(self.investments, 'Stocks', create)
            self.private = self._child(self.investments, '.stock-research', create, True)
            self.receipts = self._child(self.private, 'dossiers', create, True)
            self.evidence_invalid = False
            try:
                self.evidence = self._child(self.receipts, 'evidence', create, True)
            except (OSError, ValueError):
                if create:
                    raise
                self.evidence = None
                self.evidence_invalid = True
        except BaseException:
            self.close()
            raise

    def _child(self, parent, name, create, private=False):
        if parent is None:
            return None
        fd = _directory(parent, name, create, private)
        if fd is not None:
            self.fds.append(fd)
        return fd

    def close(self):
        for fd in reversed(self.fds):
            os.close(fd)
        self.fds = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def stable(self):
        checks = ((self.vault, self.root), (self.vault / 'Investments', self.investments),
                  (self.vault / 'Investments/Stocks', self.stocks),
                  (self.vault / 'Investments/.stock-research', self.private),
                  (self.vault / 'Investments/.stock-research/dossiers', self.receipts),
                  (self.vault / 'Investments/.stock-research/dossiers/evidence', self.evidence))
        for path, fd in checks:
            if fd is not None:
                item = path.lstat()
                if not stat.S_ISDIR(item.st_mode) or (item.st_dev, item.st_ino) != _identity(fd):
                    raise ValueError('dossier directory changed: ' + str(path))

    def read(self, fd, name):
        if fd is None:
            return None, None
        with _pinned(fd):
            owners = [n for n in os.listdir('.') if portable_identity(n) == portable_identity(name)]
            if owners and owners != [name]:
                raise ValueError('portable-equivalent filename collision: ' + name)
            return _read(name) if owners else (None, None)

    def write(self, fd, name, data, expected, private=False):
        self.stable()
        # Stage within the pinned vault filesystem; only validated basenames are resolved.
        with _pinned(fd):
            stage = Path(tempfile.mkdtemp(prefix='.stock-dossier-stage-', dir='.')).resolve()
            staged = stage / 'new'
            try:
                with staged.open('xb') as handle:
                    if private:
                        os.fchmod(handle.fileno(), 0o600)
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                if expected is None:
                    atomic_move.publish_new(staged, Path(name), atomic_move.regular_file_snapshot, stage)
                else:
                    atomic_move.replace_expected(staged, Path(name), expected,
                                                 atomic_move.regular_file_snapshot, stage, stage.parent)
                actual, snapshot = _read(name)
                if actual != data:
                    raise ValueError('published dossier bytes failed readback')
                os.fsync(fd)
                self.stable()
            except BaseException as exc:
                raise RuntimeError('dossier publication failed; preserve recovery directory %s: %s' % (stage, exc)) from exc
            shutil.rmtree(stage)
            return snapshot

    def load(self, ticker):
        receipt_bytes, receipt_snapshot = self.read(self.receipts, ticker + '.json')
        note_bytes, note_snapshot = self.read(self.stocks, ticker + '.md')
        if receipt_bytes is None:
            if note_bytes is not None:
                raise ValueError('unmanaged stock note already exists; preserve it: ' + ticker)
            return {'schema': 1, 'committed': None, 'pending': None}, None, None
        value = _json(receipt_bytes)
        if not isinstance(value, dict) or set(value) != {'schema', 'committed', 'pending'} or value['schema'] != 1:
            raise ValueError('invalid dossier receipt')
        pending = value['pending']
        if pending is not None and (not isinstance(pending, dict) or set(pending) != {'record', 'document'}
                                    or not isinstance(pending['document'], str)):
            raise ValueError('invalid pending dossier receipt')
        for record in (value['committed'], pending['record'] if pending else None):
            if record is not None:
                _validate_record(record, ticker)
        committed, pending = value['committed'], value['pending']
        acceptable = {committed['published_sha256'] if committed else None}
        if pending:
            if _hash(pending['document'].encode()) != pending['record']['published_sha256']:
                raise ValueError('pending dossier bytes do not match their receipt')
            acceptable.add(pending['record']['published_sha256'])
        if (_hash(note_bytes) if note_bytes is not None else None) not in acceptable:
            raise ValueError('stock note changed outside stock-research; preserve edits and resolve before updating: ' + ticker)
        self.stable()
        return value, receipt_snapshot, note_snapshot


def _validate_record(record, ticker):
    fields = {'ticker', 'exchange', 'company', 'company_id', 'created', 'updated', 'as_of',
              'status', 'history', 'published_sha256', 'provenance'}
    if not isinstance(record, dict) or set(record) != fields:
        raise ValueError('invalid stock record fields')
    if record['ticker'] != ticker or not SYMBOL.fullmatch(ticker) or not EXCHANGE.fullmatch(record['exchange']):
        raise ValueError('stock receipt identity mismatch')
    if not isinstance(record['company'], str) or not record['company'].strip() or '\n' in record['company']:
        raise ValueError('invalid stock company')
    if record['company_id'] is not None and not ID.fullmatch(record['company_id']):
        raise ValueError('invalid stock company ID')
    for key in ('created', 'updated', 'as_of'):
        market_notes.iso_time(record[key])
    if record['status'] not in STATES or not re.fullmatch('[a-f0-9]{64}', record['published_sha256']):
        raise ValueError('invalid stock status or digest')
    if not isinstance(record['history'], list) or not record['history']:
        raise ValueError('stock history is empty')
    last = None
    for row in record['history']:
        fields = {'daily_note', 'daily_sha256', 'as_of', 'generated_at', 'heading', 'status'}
        if (not isinstance(row, dict) or set(row) not in (fields, fields | {'evidence_snapshot'})
                or ('evidence_snapshot' in row and row['evidence_snapshot'] is not True)):
            raise ValueError('invalid stock history row')
        _daily_name(row['daily_note'])
        cutoff = market_notes.iso_time(row['as_of'])
        generated = market_notes.iso_time(row['generated_at'])
        if generated < cutoff:
            raise ValueError('stock history generation precedes its evidence cutoff')
        if last is not None and cutoff <= last:
            raise ValueError('stock history is not strictly increasing')
        last = cutoff
        if (row['status'] not in STATES or not re.fullmatch('[a-f0-9]{64}', row['daily_sha256'])
                or not HEADING.fullmatch(row['heading'])):
            raise ValueError('invalid stock history identity or digest')
    if (record['as_of'] != record['history'][-1]['as_of']
            or record['updated'] != record['history'][-1]['generated_at']
            or record['created'] != record['history'][0]['generated_at']
            or record['status'] != record['history'][-1]['status']):
        raise ValueError('stock latest metadata does not match history')
    provenance = record['provenance']
    if (not isinstance(provenance, dict) or provenance.get('schema') != 1
            or not {'schema', 'generated_by'} <= set(provenance)
            or set(provenance) - {'schema', 'generated_by', 'updated_by'}):
        raise ValueError('invalid dossier provenance')
    note_provenance.validate_record(provenance['generated_by'])
    if 'updated_by' in provenance:
        note_provenance.validate_record(provenance['updated_by'])
    if any(provenance[key]['skill'] != 'investments:stock-research'
           for key in ('generated_by', 'updated_by') if key in provenance):
        raise ValueError('dossier receipt provenance must be investments:stock-research')


def _daily_name(value):
    if not isinstance(value, str) or not re.fullmatch(
            r'Investments/\d{4}-\d{2}-\d{2}(?:-\d{6})?-stock-research\.md', value):
        raise ValueError('dossiers require a canonical published stock-research daily note')
    return Path(value).name


def _daily(store, name):
    basename = _daily_name(name)
    data, _ = store.read(store.investments, basename)
    if data is None:
        raise ValueError('publish the immutable daily report before updating stock notes')
    return _daily_content(data, name)


def _daily_content(data, name):
    basename = _daily_name(name)
    linted = market_notes.lint_bytes(data)
    if (linted['provenance'] is None
            or linted['provenance']['generated_by']['skill'] != 'investments:stock-research'):
        raise ValueError('daily report lacks stock-research provenance')
    meta = linted['metadata']
    if not basename.startswith(meta['date']):
        raise ValueError('daily filename and report date disagree')
    return data, meta, candidates(data)


def _evidence_path(digest):
    return 'Investments/.stock-research/dossiers/evidence/' + digest + '.md'


def _archive_daily(store, data):
    """Create exact original evidence once; never replace an existing occupant."""
    name = _hash(data) + '.md'
    existing, _ = store.read(store.evidence, name)
    if existing is not None:
        if existing != data:
            raise ValueError('dossier evidence snapshot changed; preserve it: ' + name)
    else:
        store.write(store.evidence, name, data, None, True)


def _history_audit(store, record, cutoff=None):
    """Separate usable original evidence from quarantined paths, without repairs."""
    history, diagnostics = [], []
    for row in record['history'] if record else []:
        if cutoff is not None and (market_notes.iso_time(row['as_of']) > cutoff
                                   or market_notes.iso_time(row['generated_at']) > cutoff):
            continue
        sources = [(store.investments, _daily_name(row['daily_note']), row['daily_note'])]
        if row.get('evidence_snapshot'):
            path = _evidence_path(row['daily_sha256'])
            sources.append((store.evidence, Path(path).name, path))
        verified = None
        for fd, name, path in sources:
            reason = None
            try:
                data, _ = store.read(fd, name)
                if data is None:
                    reason = ('unsafe-or-invalid' if path != row['daily_note'] and store.evidence_invalid
                              else 'missing')
                elif _hash(data) != row['daily_sha256']:
                    reason = 'changed'
                else:
                    _, meta, entries = _daily_content(data, row['daily_note'])
                    item = next((item for item in entries if item['ticker'] == record['ticker']), None)
                    if (meta['as_of'] != row['as_of'] or meta['generated_at'] != row['generated_at']
                            or item is None or item['heading'] != row['heading'] or item['status'] != row['status']):
                        reason = 'metadata-conflict'
                    else:
                        verified = path
            except (OSError, ValueError, RuntimeError):
                # Do not expose content or a symlink target in a diagnostic.
                reason = 'unsafe-or-invalid'
            if reason:
                diagnostics.append({'daily_note': row['daily_note'], 'path': path,
                                    'expected_sha256': row['daily_sha256'], 'reason': reason,
                                    'quarantined': True})
        if verified:
            history.append({**row, 'evidence_note': verified})
    store.stable()
    return {'history': history, 'history_complete': not diagnostics,
            'history_diagnostics': diagnostics}


def _same_company(prior, item):
    if prior['exchange'] != item['exchange']:
        raise ValueError('ticker is already assigned to another exchange; verify corporate identity before migration')
    old, new = prior['company_id'], item['company_id']
    if old and new and old != new:
        raise ValueError('ticker company ID changed; do not overwrite an unrelated issuer')
    if not (old and new and old == new) and prior['company'].casefold() != item['company'].casefold():
        raise ValueError('company name changed without a matching stable ID; verify identity before migration')


def validate_identities(vault, entries, *, _lock_descriptor=None):
    """Check prospective daily assessments against owned dossiers before publication.

    Reuse the exact synchronization identity rules without creating folders,
    adopting unmanaged notes, or advancing a pending publication.
    """
    with Store(vault, _lock_descriptor=_lock_descriptor) as store:
        for item in entries:
            receipt, _, _ = store.load(item['ticker'])
            if receipt['pending']:
                raise ValueError('stock publication is incomplete; recover the pending daily update first: '
                                 + item['ticker'])
            if receipt['committed']:
                _same_company(receipt['committed'], item)
        store.stable()


def _daily_relative(vault, daily_note):
    path = Path(daily_note).expanduser()
    if not path.is_absolute():
        path = Path(vault).expanduser().resolve(strict=True) / path
    # Do not resolve the child: a symlink must be rejected when read, not followed here.
    try:
        value = str(path.relative_to(Path(vault).expanduser().resolve(strict=True)))
    except ValueError as exc:
        raise ValueError('daily report must be inside this vault') from exc
    _daily_name(value)
    return value


def prepare(vault, daily_note, ticker, exchange=None, company=None, heading=None,
            company_id=None, draft=None):
    if not SYMBOL.fullmatch(ticker):
        raise ValueError('invalid ticker')
    daily = _daily_relative(vault, daily_note)
    with Store(vault) as store:
        data, meta, entries = _daily(store, daily)
        item = next((entry for entry in entries if entry['ticker'] == ticker), None)
        if item is None:
            raise ValueError('stock has no substantive assessment in this daily report: ' + ticker)
        for name, supplied in (('exchange', exchange), ('company', company), ('heading', heading), ('company_id', company_id)):
            if supplied is not None and supplied != item[name]:
                raise ValueError(name + ' must match the immutable daily assessment')
        receipt, _, _ = store.load(ticker)
        prior = receipt['committed']
        already_synced = prior and any(row['daily_note'] == daily and row['daily_sha256'] == _hash(data)
                                       for row in prior['history'])
        if prior and not already_synced:
            _same_company(prior, item)
        audit = _history_audit(store, prior)
        value = {'schema': 1, 'vault': str(store.vault), 'daily_note': daily,
                 'daily_sha256': _hash(data), 'ticker': ticker,
                 'expected_sha256': prior['published_sha256'] if prior else None}
        if draft:
            supplied = Path(draft).expanduser().absolute()
            target = supplied.parent.resolve(strict=True) / supplied.name
            if target.is_relative_to(store.vault):
                raise ValueError('prepare drafts in private scratch outside the vault')
            data = _bytes(value)
            with target.open('xb') as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(data)
            if _read(target)[0] != data:
                raise ValueError('dossier draft failed readback')
        return {'status': 'prepared', 'draft': str(draft) if draft else None, 'plan': value,
                'path': str(store.vault / 'Investments/Stocks' / (ticker + '.md')), **audit}


def _render(item, meta, daily, daily_digest, prior, previous, provenance):
    row = {'daily_note': daily, 'daily_sha256': daily_digest, 'as_of': meta['as_of'],
           'generated_at': meta['generated_at'], 'heading': item['heading'], 'status': item['status'],
           'evidence_snapshot': True}
    record = {key: item[key] for key in ('ticker', 'exchange', 'company', 'company_id', 'status')}
    if prior and record['company_id'] is None:
        record['company_id'] = prior['company_id']
    record.update({'created': prior['created'] if prior else meta['generated_at'],
                   'updated': meta['generated_at'], 'as_of': meta['as_of'],
                   'history': [*(prior['history'] if prior else []), row]})
    front = '\n'.join(key + ': ' + json.dumps(value, ensure_ascii=False)
                      for key, value in {'stock_research': 1, 'ticker': record['ticker'],
                                        'exchange': record['exchange'], 'company': record['company'],
                                        'company_id': record['company_id'], 'created': record['created'],
                                        'updated': record['updated'], 'as_of': record['as_of'],
                                        'status': record['status']}.items())
    link = daily.removesuffix('.md') + '#' + item['heading']
    history = '\n'.join('- ' + r['as_of'] + ' — ' + r['status'] + ' — [['
                        + r['daily_note'].removesuffix('.md') + '#' + r['heading'] + ']]'
                        for r in reversed(record['history']))
    body = ('---\n' + front + '\n---\n\n# ' + item['ticker'] + ' — ' + item['company']
            + '\n\n## Latest assessment\n\nSource: [[' + link + ']].\n\n'
            + item['assessment'] + '\n## Research history\n\n' + history + '\n')
    text = note_provenance.stamp_text(body, provenance, previous.decode() if previous else None)
    record['provenance'] = note_provenance.split_provenance(text)[1]
    record['published_sha256'] = _hash(text.encode())
    return record, text


def publish(vault, draft, provenance=None):
    data, _ = _read(draft)
    plan = _json(data)
    if (not isinstance(plan, dict) or set(plan) != {'schema', 'vault', 'daily_note', 'daily_sha256', 'ticker', 'expected_sha256'}
            or plan['schema'] != 1 or not isinstance(plan['ticker'], str) or not SYMBOL.fullmatch(plan['ticker'])):
        raise ValueError('invalid dossier publication plan')
    if plan['vault'] != str(Path(vault).expanduser().resolve(strict=True)):
        raise ValueError('dossier plan belongs to another vault')
    _daily_name(plan['daily_note'])
    if (not isinstance(plan['daily_sha256'], str) or not re.fullmatch('[a-f0-9]{64}', plan['daily_sha256'])
            or (plan['expected_sha256'] is not None and
                (not isinstance(plan['expected_sha256'], str) or not re.fullmatch('[a-f0-9]{64}', plan['expected_sha256'])))):
        raise ValueError('invalid dossier plan digest')
    # Provenance overrides exist only for fixture callers; the CLI always verifies its installed bundle.
    producer = provenance if provenance is not None else market_notes.active_provenance()
    note_provenance.validate_record(producer)
    if producer['skill'] != 'investments:stock-research':
        raise ValueError('dossier producer must be investments:stock-research')
    with Store(vault, create=True) as store:
        receipt, receipt_token, note_token = store.load(plan['ticker'])
        prior, pending = receipt['committed'], receipt['pending']
        if prior and not pending:
            previous_publication = next((row for row in prior['history']
                                         if row['daily_note'] == plan['daily_note']
                                         and row['daily_sha256'] == plan['daily_sha256']), None)
            if previous_publication:
                # An already committed plan needs no source copying or new write.
                return {'status': 'unchanged', 'superseded': previous_publication != prior['history'][-1],
                        'path': str(store.vault / 'Investments/Stocks' / (plan['ticker'] + '.md')),
                        **_history_audit(store, prior)}
        if pending:
            tail = pending['record']['history'][-1]
            if tail['daily_note'] != plan['daily_note'] or tail['daily_sha256'] != plan['daily_sha256']:
                raise ValueError('another dossier update is pending; recover it first')
            if plan['expected_sha256'] != (prior['published_sha256'] if prior else None):
                raise ValueError('stock snapshot changed after planning; prepare again')
            if pending['record']['history'][:-1] != (prior['history'] if prior else []):
                raise ValueError('pending dossier history does not extend its exact predecessor')
        try:
            daily, meta, entries = _daily(store, plan['daily_note'])
            if _hash(daily) != plan['daily_sha256']:
                raise ValueError('immutable daily report changed after planning')
        except (OSError, ValueError, RuntimeError):
            # Only a validated, plan-bound write-ahead transaction authorizes this
            # recovery. An orphan archive is never a substitute for a fresh source.
            if not pending or not tail.get('evidence_snapshot'):
                raise
            daily, _ = store.read(store.evidence, plan['daily_sha256'] + '.md')
            if daily is None or _hash(daily) != plan['daily_sha256']:
                raise ValueError('pending dossier original evidence is unavailable; preserve recovery artifacts')
            daily, meta, entries = _daily_content(daily, plan['daily_note'])
        item = next((entry for entry in entries if entry['ticker'] == plan['ticker']), None)
        if item is None:
            raise ValueError('stock assessment disappeared from the daily report')
        if prior:
            _same_company(prior, item)
            if market_notes.iso_time(meta['as_of']) <= market_notes.iso_time(prior['as_of']):
                raise ValueError('stale or equal-cutoff assessment cannot replace a newer stock snapshot')
            if market_notes.iso_time(meta['generated_at']) < market_notes.iso_time(prior['updated']):
                raise ValueError('stock update timestamp would move backwards')
        if plan['expected_sha256'] != (prior['published_sha256'] if prior else None):
            raise ValueError('stock snapshot changed after planning; prepare again')
        previous, _ = store.read(store.stocks, item['ticker'] + '.md')
        if pending:
            record, text = pending['record'], pending['document']
            frozen_provenance = record['provenance'].get('updated_by', record['provenance']['generated_by'])
            rebuilt, rebuilt_text = _render(item, meta, plan['daily_note'], plan['daily_sha256'],
                                            prior, previous, frozen_provenance)
            if not tail.get('evidence_snapshot'):
                rebuilt['history'][-1].pop('evidence_snapshot')
            if rebuilt != record or rebuilt_text != text:
                raise ValueError('pending dossier does not match its original assessment, identity and provenance')
            if tail.get('evidence_snapshot'):
                _archive_daily(store, daily)
        else:
            _archive_daily(store, daily)
            record, text = _render(item, meta, plan['daily_note'], plan['daily_sha256'], prior, previous, producer)
            _validate_record(record, item['ticker'])
            receipt = {'schema': 1, 'committed': prior, 'pending': {'record': record, 'document': text}}
            receipt_token = store.write(store.receipts, item['ticker'] + '.json', _bytes(receipt), receipt_token, True)
        if previous is None or _hash(previous) != record['published_sha256']:
            store.write(store.stocks, item['ticker'] + '.md', text.encode(), note_token)
        store.write(store.receipts, item['ticker'] + '.json',
                    _bytes({'schema': 1, 'committed': record, 'pending': None}), receipt_token, True)
        store.load(item['ticker'])
        return {'status': 'updated' if prior else 'created',
                'path': str(store.vault / 'Investments/Stocks' / (item['ticker'] + '.md')),
                **_history_audit(store, record)}


def context(vault, ticker, as_of, *, _lock_descriptor=None):
    if not SYMBOL.fullmatch(ticker):
        raise ValueError('invalid ticker')
    cutoff = market_notes.iso_time(as_of)
    with Store(vault, _lock_descriptor=_lock_descriptor) as store:
        receipt, _, _ = store.load(ticker)
        if receipt['pending']:
            raise ValueError('stock publication is incomplete; recover the pending daily update first')
        record = receipt['committed']
        if record is None:
            return {'status': 'missing', 'ticker': ticker, 'current': None,
                    'current_source': None, **_history_audit(store, None)}
        audit = _history_audit(store, record, cutoff)
        available = (market_notes.iso_time(record['as_of']) <= cutoff
                     and market_notes.iso_time(record['updated']) <= cutoff)
        latest = next((row for row in audit['history']
                       if row['daily_sha256'] == record['history'][-1]['daily_sha256']
                       and row['daily_note'] == record['history'][-1]['daily_note']), None)
        status = 'current' if available and latest else 'unverified-current' if available else 'newer-than-cutoff'
        warning = None
        if status == 'newer-than-cutoff':
            warning = 'Read only eligible verified evidence; the current stock snapshot contains later information.'
        elif status == 'unverified-current':
            warning = 'The latest daily evidence is unverified; the current assessment is withheld.'
        if audit['history_diagnostics']:
            warning = (warning + ' ' if warning else '') + 'Quarantined paths are not trusted; use only history evidence_note paths. Publication does not resolve these conflicts.'
        note, _ = store.read(store.stocks, ticker + '.md')
        if note is None or _hash(note) != record['published_sha256']:
            raise ValueError('stock note changed while reading context; preserve it: ' + ticker)
        store.stable()
        return {'status': status, 'ticker': ticker, 'current': note.decode() if status == 'current' else None,
                'current_source': latest['evidence_note'] if status == 'current' else None,
                'warning': warning, **audit}


def sync(vault, daily_note, work_dir, provenance=None):
    workspace = Path(work_dir).expanduser().resolve(strict=True)
    root = Path(vault).expanduser().resolve(strict=True)
    if not workspace.is_dir() or workspace.is_relative_to(root):
        raise ValueError('dossier work directory must be private scratch outside the vault')
    daily = _daily_relative(vault, daily_note)
    with Store(vault) as store:
        _, _, entries = _daily(store, daily)
    results, failures = [], []
    for item in entries:
        folder = Path(tempfile.mkdtemp(prefix='dossier-' + item['ticker'] + '-', dir=workspace))
        draft = folder / 'plan.json'
        try:
            prepare(vault, daily, item['ticker'], draft=draft)
            results.append(publish(vault, draft, provenance))
        except (ValueError, RuntimeError, OSError) as exc:
            failures.append({'ticker': item['ticker'], 'error': str(exc), 'recovery_draft': str(draft)})
        else:
            shutil.rmtree(folder)
    return {'complete': not failures, 'analyzed': len(entries), 'results': results, 'failures': failures,
            'history_complete': not failures and all(row['history_complete'] for row in results),
            'history_diagnostics': [item for row in results for item in row['history_diagnostics']]}


def run_self_test():
    import unittest
    class Tests(unittest.TestCase):
        def test_extract(self):
            raw = b'### Candidate assessments\n\n#### NASDAQ:ABC \xe2\x80\x94 Example\n\nStatus: rejected\n\n[[Investments/Stocks/ABC]]\nInsufficient evidence.\n\n### Thesis updates\n'
            self.assertEqual(candidates(raw)[0]['status'], 'rejected')
        def test_missing_status(self):
            with self.assertRaisesRegex(ValueError, 'Status'):
                candidates(b'### Candidate assessments\n#### NASDAQ:ABC \xe2\x80\x94 Example\nDetails.\n')
        def test_path_escape(self):
            with self.assertRaises(ValueError):
                _daily_name('Investments/../secret.md')
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print('%d/%d self-test cases pass' % (passed, result.testsRun))
    return 0 if result.wasSuccessful() else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', '--self-test', dest='self_test', action='store_true')
    commands = parser.add_subparsers(dest='command')
    sub = commands.add_parser('context')
    sub.add_argument('--vault', required=True)
    sub.add_argument('--ticker', required=True)
    sub.add_argument('--as-of', required=True)
    sub = commands.add_parser('prepare')
    sub.add_argument('--vault', required=True)
    sub.add_argument('--daily-note', required=True)
    sub.add_argument('--ticker', required=True)
    for field in ('exchange', 'company', 'heading', 'company-id'):
        sub.add_argument('--' + field)
    sub.add_argument('--draft', required=True)
    sub = commands.add_parser('publish')
    sub.add_argument('--vault', required=True)
    sub.add_argument('--draft', required=True)
    sub = commands.add_parser('sync')
    sub.add_argument('--vault', required=True)
    sub.add_argument('--daily-note', required=True)
    sub.add_argument('--work-dir', required=True)
    args = vars(parser.parse_args(argv))
    if args.pop('self_test'):
        return run_self_test()
    command = args.pop('command')
    if not command:
        parser.error('choose a command')
    try:
        result = globals()[command](**args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get('complete', True) else 2
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
