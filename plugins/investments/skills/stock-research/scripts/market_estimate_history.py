#!/usr/bin/env python3
"""Preserve selected current estimates for later, cutoff-aware comparison.

Snapshots are create-only observations, not historical provider vintages.
No account access, full feed, credentials or arbitrary source URLs are saved.
Publication is single-threaded and uses the shared pinned atomic writer.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
from urllib.parse import parse_qs, urlsplit

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

from market_estimates import ESTIMATE_FIELDS, HORIZONS, SOURCE, has_current_estimate, validate_estimate_row
from market_http import parse_date, parse_time
from market_notes import MAX_BYTES, atomic_move, output_folder, portable_identity, publish_pinned, read_stable
import market_evidence as receipt_store

SYMBOL = re.compile(r'[A-Z][A-Z0-9.-]{0,14}\Z', re.ASCII)
DIGEST = re.compile(r'[0-9a-f]{64}\Z', re.ASCII)
NAME = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{6}\.[0-9]{6}Z-([A-Z][A-Z0-9.-]{0,14})-[0-9a-f]{64}\.json\Z', re.ASCII)
MAX_FILES = 100000
EVIDENCE_KEYS = {'source', 'symbol', 'observed_at', 'provider_as_of', 'record', 'request'}
SNAPSHOT_KEYS = EVIDENCE_KEYS | {'estimate_snapshot', 'saved_at', 'available_at', 'observation_sha256', 'snapshot_sha256'}
SNAPSHOT_KEYS_V2 = SNAPSHOT_KEYS - {'saved_at', 'available_at'}
RECEIPT_FOLDER = ('Investments', 'Snapshots', 'EstimateReceipts')
RECEIPT_BYTES = 4096
WARNINGS = [
    'Verified availability comes from a receipt timestamped after immutable snapshot publication and readback, not the observation or a legacy pre-publication save timestamp.',
    'Unreceipted snapshots retain their original bytes but have unverified local availability and cannot support a historical cutoff; an explicit save retry can receipt them only at the current time.',
    'Provider trailing-window estimates and revision counts are current reported aggregates, not independently archived earlier observations.',
    'Numeric changes alone do not verify economic comparability; check instrument, period, units, accounting basis and provider coverage.',
    'This provider does not supply an EPS accounting basis; an absent currency also remains unknown, not an assumed U.S. dollar denomination.',
]


def _time(value):
    if (not isinstance(value, str) or not re.fullmatch(
            r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})', value)):
        raise ValueError('timestamps require ISO seconds, an offset and at most six fractional digits')
    return parse_time(value)


def _now(now=None):
    value = now if now is not None else datetime.now(timezone.utc)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('current time must be timezone-aware')
    return value.astimezone(timezone.utc)


def _iso(value):
    return value.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def _symbol(value):
    if not isinstance(value, str) or not SYMBOL.fullmatch(value):
        raise ValueError('use one canonical uppercase U.S. ticker, at most 15 characters')
    return value


def _canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON keys are not supported')
        result[key] = value
    return result


def _load(path):
    data, token = read_stable(path)
    try:
        value = json.loads(data, object_pairs_hook=_unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON numbers are not supported')))
    except (json.JSONDecodeError, RecursionError):
        raise ValueError('snapshot input must contain a bounded, valid JSON object') from None
    if not isinstance(value, dict):
        raise ValueError('snapshot input must be a JSON object')
    return value, token


def _request(row, observed):
    if (not isinstance(row, dict) or type(row.get('status')) is not int or row['status'] != 200
            or type(row.get('bytes')) is not int or not 0 < row['bytes'] <= 50 * 1024 * 1024
            or not isinstance(row.get('sha256'), str) or not DIGEST.fullmatch(row['sha256'])):
        raise ValueError('a successful bounded provider request and content hash are required')
    retrieved = _time(row.get('retrieved_at'))
    if retrieved > observed:
        raise ValueError('request retrieval time cannot follow the declared observation')
    return {'retrieved_at': _iso(retrieved), 'status': 200, 'bytes': row['bytes'], 'sha256': row['sha256']}


def _source_request(rows, symbol, observed):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 500:
        raise ValueError('bounded request provenance is required')
    successful = [row for row in rows if isinstance(row, dict) and row.get('status') == 200]
    if len(successful) != 1:
        raise ValueError('exactly one successful estimates request is required; failed retries do not count')
    row = successful[0]
    url = row.get('url')
    try:
        if not isinstance(url, str) or any(ord(char) < 32 or ord(char) == 127 for char in url):
            raise ValueError('invalid URL')
        parsed = urlsplit(url)
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
        if (parsed.scheme != 'https' or parsed.netloc != 'www.alphavantage.co'
                or parsed.path != '/query' or parsed.fragment
                or set(query) - {'function', 'symbol', 'apikey'}
                or query.get('function') != [SOURCE['function']] or query.get('symbol') != [symbol]
                or any(len(values) != 1 for values in query.values())):
            raise ValueError('wrong request')
    except (ValueError, TypeError):
        raise ValueError('request provenance must identify the selected Alpha Vantage estimates endpoint and ticker') from None
    return _request(row, observed)


def _selected(payload, period, horizon, current):
    period = parse_date(period).isoformat()
    if horizon not in HORIZONS:
        raise ValueError('select exactly one fiscal quarter or fiscal year')
    if (type(payload.get('market_data')) is not int or payload['market_data'] != 1
            or payload.get('operation') != 'estimates' or payload.get('source') != SOURCE
            or payload.get('provider_as_of') is not None or 'provider_as_of' not in payload
            or payload.get('coverage_complete') is not True
            or type(payload.get('complete')) is not bool or type(payload.get('within_cutoff')) is not bool
            or payload['complete'] != payload['within_cutoff']):
        raise ValueError('save requires an estimates result with complete coverage; only late-cutoff incompleteness is allowed')
    query = payload.get('query')
    if not isinstance(query, dict):
        raise ValueError('estimate query provenance is missing')
    symbol = _symbol(query.get('symbol'))
    observed = _time(payload.get('observed_at'))
    if observed > current:
        raise ValueError('an estimate observation cannot be in the future')
    cutoff = _time(query['as_of']) if query.get('as_of') is not None else None
    if (cutoff is not None and cutoff > current) or payload['within_cutoff'] != (cutoff is None or observed <= cutoff):
        raise ValueError('estimate cutoff flags disagree with the observation time')
    rows = payload.get('data')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
        raise ValueError('estimate periods must be a bounded nonempty list')
    selected, seen = None, set()
    for row in rows:
        checked = validate_estimate_row(row)
        if not has_current_estimate(checked):
            raise ValueError('a period without current estimates cannot be archived as complete coverage')
        identity = checked['fiscal_period_end'], checked['horizon']
        if identity in seen:
            raise ValueError('duplicate estimate period/horizon cannot be archived as unambiguous evidence')
        seen.add(identity)
        if identity == (period, horizon):
            selected = checked
    if selected is None:
        raise ValueError('the explicitly selected fiscal period/horizon is absent')
    return {'source': dict(SOURCE), 'symbol': symbol, 'observed_at': _iso(observed), 'provider_as_of': None,
            'record': selected, 'request': _source_request(payload.get('requests'), symbol, observed)}


def _filename(evidence):
    digest = hashlib.sha256(_canonical(evidence)).hexdigest()
    return '%s-%s-%s.json' % (_time(evidence['observed_at']).strftime('%Y-%m-%dT%H%M%S.%fZ'), evidence['symbol'], digest)


def _validate_snapshot(value, name=None):
    if (type(value.get('estimate_snapshot')) is not int or value['estimate_snapshot'] not in (1, 2)
            or set(value) != (SNAPSHOT_KEYS if value['estimate_snapshot'] == 1 else SNAPSHOT_KEYS_V2)
            or value.get('source') != SOURCE
            or value.get('provider_as_of') is not None):
        raise ValueError('unsupported or nonminimal estimate snapshot schema')
    symbol = _symbol(value['symbol'])
    observed = _time(value['observed_at'])
    if value['estimate_snapshot'] == 1:
        saved, available = (_time(value[key]) for key in ('saved_at', 'available_at'))
        if (saved < observed or available != max(observed, saved)
                or value['saved_at'] != _iso(saved) or value['available_at'] != _iso(available)):
            raise ValueError('legacy snapshot timestamps are inconsistent')
    evidence = {'source': dict(SOURCE), 'symbol': symbol, 'observed_at': _iso(observed), 'provider_as_of': None,
                'record': validate_estimate_row(value['record']), 'request': _request(value['request'], observed)}
    if not has_current_estimate(evidence['record']):
        raise ValueError('an estimate snapshot must contain current estimates')
    if (set(value['request']) != {'retrieved_at', 'status', 'bytes', 'sha256'}
            or any(value[key] != evidence[key] for key in EVIDENCE_KEYS)
            or value['observation_sha256'] != hashlib.sha256(_canonical(evidence)).hexdigest()
            or value['snapshot_sha256'] != hashlib.sha256(_canonical({key: item for key, item in value.items()
                                                                       if key != 'snapshot_sha256'})).hexdigest()
            or (name is not None and name != _filename(evidence))):
        raise ValueError('estimate snapshot identity, canonical representation or content hash does not match')
    return value


def _receipts(vault, current):
    """Validate immutable receipts; retain the earliest proven persistence time."""
    result, opened = {}, False
    try:
        with receipt_store.pinned_directory(vault, RECEIPT_FOLDER) as (root, descriptor, check):
            opened = True
            names = sorted(os.listdir(descriptor))
            if len(names) > MAX_FILES:
                raise ValueError('estimate receipt inventory exceeds its bounded file count')
            for name in names:
                if not re.fullmatch(r'[0-9a-f]{64}\.json', name):
                    raise ValueError('unexpected estimate receipt occupant; preserve it for inspection')
                raw = receipt_store.read_bytes(descriptor, name, RECEIPT_BYTES)
                value = json.loads(raw, object_pairs_hook=_unique)
                if (not isinstance(value, dict) or set(value) != {'estimate_receipt', 'snapshot_sha256', 'available_at'}
                        or type(value['estimate_receipt']) is not int or value['estimate_receipt'] != 1
                        or not isinstance(value['snapshot_sha256'], str) or not DIGEST.fullmatch(value['snapshot_sha256'])
                        or raw != receipt_store.canonical(value) or hashlib.sha256(raw).hexdigest() + '.json' != name):
                    raise ValueError('estimate receipt schema, hash or canonical bytes disagree')
                available = _time(value['available_at'])
                if available > current or value['available_at'] != _iso(available):
                    raise ValueError('estimate receipt availability is invalid or in the future')
                key = value['snapshot_sha256']
                if key not in result or available < _time(result[key]['available_at']):
                    result[key] = {'available_at': value['available_at'],
                                   'receipt': str(root.joinpath(*RECEIPT_FOLDER, name))}
            if sorted(os.listdir(descriptor)) != names:
                raise ValueError('estimate receipts changed during inventory; retry')
            check()
    except FileNotFoundError:
        if opened:
            raise ValueError('estimate receipt disappeared during inventory; retry') from None
    return result


def _verified_availability(value, receipts):
    receipt = receipts.get(value['snapshot_sha256'])
    if receipt is not None and _time(receipt['available_at']) < _time(value['observed_at']):
        raise ValueError('estimate receipt precedes the actual observation')
    return receipt


def _snapshot_current(value, current):
    if (_time(value['observed_at']) > current
            or value['estimate_snapshot'] == 1 and _time(value['saved_at']) > current):
        raise ValueError('a stored snapshot claims a future observation or legacy save time')


def _subfolder(parent, name, parent_identity, create):
    flags = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(parent, flags)
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != parent_identity:
            raise ValueError('snapshot parent directory changed')
        owners = [item for item in os.listdir(descriptor) if portable_identity(item) == portable_identity(name)]
        if owners and owners != [name]:
            raise ValueError('portable-equivalent snapshot folder collision')
        if not owners:
            if not create:
                return None
            os.mkdir(name, dir_fd=descriptor)  # No concurrent occupant is adopted.
        child = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if not stat.S_ISDIR(child.st_mode):
            raise ValueError('snapshot folders must be real directories, never symlinks')
        return child.st_dev, child.st_ino
    finally:
        os.close(descriptor)


def _folders(vault, create=False):
    vault, investments, identity = output_folder(vault, create=create)
    folder = investments / 'Snapshots' / 'Estimates'
    chain = [identity]
    if identity is not None:
        for parent, name in ((investments, 'Snapshots'), (investments / 'Snapshots', 'Estimates')):
            identity = _subfolder(parent, name, identity, create)
            chain.append(identity)
            if identity is None:
                break
    return vault, folder, tuple(chain)


def _listing(folder):
    paths = []
    for path in folder.iterdir():
        if len(paths) >= MAX_FILES:
            raise ValueError('estimate snapshot inventory exceeds its bounded file count')
        paths.append(path)
    paths.sort(key=lambda path: path.name)
    identities = set()
    for path in paths:
        identity = portable_identity(path.name)
        if identity in identities or not NAME.fullmatch(path.name):
            raise ValueError('unexpected or portable-equivalent snapshot file; preserve it for inspection')
        identities.add(identity)
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError('estimate snapshots must be ordinary non-symlink files')
    return paths


def _locked_vault(vault):
    """Yield a pinned vault while holding its publication lock."""
    import fcntl
    root = Path(vault).expanduser().resolve(strict=True)
    flags = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(root, flags)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('another market publication is in progress; retry after it finishes') from None
        yield root
    finally:
        os.close(descriptor)


def _save_observation(input_path, vault, period, horizon, now=None):
    """Persist the observation before any receipt may establish availability."""
    current = _now(now)
    input_path = Path(input_path).expanduser().absolute()
    payload, input_token = _load(input_path)
    evidence = _selected(payload, period, horizon, current)
    name = _filename(evidence)
    with contextmanager(_locked_vault)(vault) as root:
        root, folder, chain = _folders(root, create=True)
        paths = _listing(folder)
        target = folder / name
        if target in paths:
            existing, target_token = _load(target)
            _validate_snapshot(existing, name)
            _snapshot_current(existing, current)
            if {key: existing[key] for key in EVIDENCE_KEYS} != evidence:
                raise ValueError('snapshot filename is occupied by different evidence; preserve the existing file')
            if (_folders(root)[2] != chain or _listing(folder) != paths
                    or atomic_move.regular_file_snapshot(input_path) != input_token
                    or atomic_move.regular_file_snapshot(target) != target_token):
                raise ValueError('snapshot input or directories changed during retry validation')
            return {'status': 'unchanged', 'path': str(target), 'snapshot': existing, 'warnings': list(WARNINGS)}
        value = dict(evidence, estimate_snapshot=2,
                     observation_sha256=hashlib.sha256(_canonical(evidence)).hexdigest())
        value['snapshot_sha256'] = hashlib.sha256(_canonical(value)).hexdigest()
        data = _canonical(value)
        if len(data) > MAX_BYTES:
            raise ValueError('selected snapshot exceeds the shared bounded-file limit')
        stage_dir = Path(tempfile.mkdtemp(prefix='.estimate-snapshot-stage-', dir=root))
        staged = stage_dir / name
        try:
            with staged.open('xb') as handle:
                atomic_move.set_private_mode(handle, 0o600)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            if (atomic_move.regular_file_snapshot(input_path) != input_token
                    or _folders(root)[2] != chain or _listing(folder) != paths):
                raise ValueError('snapshot input or destination changed after validation; retry')
            actual = publish_pinned(staged, target, root, chain[-1])
            if (_folders(root)[2] != chain or _listing(folder) != sorted(paths + [target], key=lambda path: path.name)):
                raise ValueError('snapshot directories changed during publication; inspect the published file at ' + actual)
        except Exception as exc:
            raise RuntimeError('snapshot publication failed; preserve recovery stage %s: %s' % (stage_dir, exc)) from exc
        shutil.rmtree(stage_dir)
        return {'status': 'created', 'path': str(target), 'snapshot': value, 'warnings': list(WARNINGS)}


def save_snapshot(input_path, vault, period, horizon, now=None, *, clock=None):
    """Receipt only after publication/readback; exact retries keep verified time."""
    clock = clock or (lambda: _now(now))
    result = _save_observation(input_path, vault, period, horizon, now=clock())
    # Verify the final immutable bytes, then sample actual time. A failed receipt
    # leaves an unreceipted observation, which history never treats as eligible.
    value, token = _load(Path(result['path']))
    if value != result['snapshot']:
        raise ValueError('published estimate readback changed; preserve the unreceipted observation')
    completed = _now(clock())
    _snapshot_current(value, completed)
    receipts = _receipts(vault, completed)
    receipt = _verified_availability(value, receipts)
    if receipt is None:
        saved = receipt_store.write({'estimate_receipt': 1, 'snapshot_sha256': value['snapshot_sha256'],
            'available_at': _iso(completed)}, vault, RECEIPT_FOLDER, RECEIPT_BYTES)
        receipt = {'available_at': _iso(completed), 'receipt': saved['path']}
    if atomic_move.regular_file_snapshot(result['path']) != token:
        raise ValueError('estimate observation changed during receipt publication; preserve both files')
    return dict(result, **receipt, availability_basis='post_publication_receipt')


def estimate_history(vault, as_of, symbol, now=None):
    symbol, cutoff, current = _symbol(symbol), _time(as_of), _now(now)
    if cutoff > current:
        raise ValueError('history cutoff cannot be in the future')
    root, folder, chain = _folders(vault)
    if chain[-1] is None:
        if _folders(root)[2] != chain:
            raise ValueError('snapshot history directories changed during inventory; retry')
        return {'complete': True, 'symbol': symbol, 'as_of': _iso(cutoff), 'snapshots': [],
                'unverified_snapshots': [], 'warnings': list(WARNINGS)}
    receipts = _receipts(root, current)
    paths, records, unverified, tokens = _listing(folder), [], [], {}
    for path in paths:
        if NAME.fullmatch(path.name)[1] != symbol:
            continue
        value, token = _load(path)
        _validate_snapshot(value, path.name)
        _snapshot_current(value, current)
        tokens[path] = token
        receipt = _verified_availability(value, receipts)
        if receipt is None:
            unverified.append({'path': str(path), 'observed_at': value['observed_at'],
                               'reason': 'missing_post_publication_receipt'})
        elif _time(receipt['available_at']) <= cutoff:
            records.append({'path': str(path), 'snapshot': value, **receipt,
                            'availability_basis': 'post_publication_receipt'})
    if (_folders(root)[2] != chain or _listing(folder) != paths
            or any(atomic_move.regular_file_snapshot(path) != token for path, token in tokens.items())):
        raise ValueError('snapshot history changed during inventory; retry')
    records.sort(key=lambda row: (_time(row['available_at']),
                                 _time(row['snapshot']['observed_at']), row['path']))
    return {'complete': not unverified, 'symbol': symbol, 'as_of': _iso(cutoff), 'snapshots': records,
            'unverified_snapshots': unverified, 'warnings': list(WARNINGS)}


def compare_snapshots(older_path, newer_path, now=None):
    paths = [Path(path).expanduser().absolute() for path in (older_path, newer_path)]
    current = _now(now)
    values, tokens, availability = [], [], []
    for path in paths:
        value, token = _load(path)
        values.append(_validate_snapshot(value, path.name))
        owners = [entry.name for entry in path.parent.iterdir()
                  if portable_identity(entry.name) == portable_identity(path.name)]
        if owners != [path.name]:
            raise ValueError('portable-equivalent snapshot owner collision')
        _snapshot_current(value, current)
        if tuple(path.parts[-4:-1]) != ('Investments', 'Snapshots', 'Estimates'):
            raise ValueError('comparison requires canonical archived paths with their local persistence receipts')
        receipt = _verified_availability(value, _receipts(path.parents[3], current))
        if receipt is None:
            raise ValueError('snapshot local availability is unverified without a post-publication receipt')
        availability.append(receipt)
        tokens.append(token)
    older, newer = values
    if (older['source'] != newer['source'] or older['symbol'] != newer['symbol']
            or any(older['record'][key] != newer['record'][key]
                   for key in ('fiscal_period_end', 'horizon', 'currency', 'accounting_basis'))):
        raise ValueError('comparison requires the exact same provider, symbol, fiscal period, horizon, currency and accounting basis')
    if (_time(older['observed_at']) >= _time(newer['observed_at'])
            or _time(availability[0]['available_at']) > _time(availability[1]['available_at'])):
        raise ValueError('older and newer observations and their availability must be chronological')
    changes = {}
    for field in ESTIMATE_FIELDS:
        left, right = older['record']['values'][field], newer['record']['values'][field]
        difference = percentage = None
        if left is not None and right is not None:
            with localcontext() as context:
                context.prec = 2200  # Exact difference across the adapter's bounded exponents.
                old, new = Decimal(left), Decimal(right)
                delta = new - old
                difference = str(delta)
                if old > 0:
                    context.prec = 28
                    percentage = str(delta / old * Decimal(100))
        changes[field] = {'older': left, 'newer': right, 'absolute_change': difference, 'percent_change': percentage}
    if any(atomic_move.regular_file_snapshot(path) != token for path, token in zip(paths, tokens)):
        raise ValueError('a snapshot changed during comparison; retry')
    warnings = list(WARNINGS)
    if older['record']['currency'] is None or older['record']['accounting_basis'] is None:
        warnings.append('Currency or accounting basis is unknown in these observations; these are numeric provider changes, not verified economically comparable revisions.')
    return {'complete': True, 'older': str(paths[0]), 'newer': str(paths[1]), 'symbol': older['symbol'],
            'source': dict(SOURCE), 'older_observed_at': older['observed_at'], 'newer_observed_at': newer['observed_at'],
            'fiscal_period_end': older['record']['fiscal_period_end'], 'horizon': older['record']['horizon'],
            'currency': older['record']['currency'], 'accounting_basis': older['record']['accounting_basis'],
            'available_at': availability[1]['available_at'], 'availability_basis': 'post_publication_receipt',
            'receipts': [row['receipt'] for row in availability], 'percent_significant_digits': 28,
            'changes': changes, 'warnings': warnings}


def run_self_test():
    import copy
    from datetime import timedelta
    import io
    import unittest
    from unittest.mock import patch

    class Tests(unittest.TestCase):
        def setUp(self):
            self.temp = tempfile.TemporaryDirectory(prefix='.estimate-history-test-')
            self.addCleanup(self.temp.cleanup)
            self.root = Path(self.temp.name).resolve()
            self.vault = self.root / 'vault'
            self.vault.mkdir()
            self.input = self.root / 'capture.json'
            self.observed = datetime(2025, 3, 3, 15, 0, tzinfo=timezone.utc)
            self.now = self.observed + timedelta(minutes=1)
            self.period, self.horizon = '2025-06-30', 'fiscal quarter'
            self.row = {'fiscal_period_end': self.period, 'horizon': self.horizon,
                        'currency': None, 'accounting_basis': None,
                        'values': {field: None for field in ESTIMATE_FIELDS}}
            self.row['values'].update(eps_estimate_average='2.5000', revenue_estimate_average='1000',
                                      eps_estimate_analyst_count='5', eps_estimate_average_7_days_ago='2.3')
            self.payload = {'market_data': 1, 'operation': 'estimates', 'source': dict(SOURCE),
                            'query': {'symbol': 'IBM', 'periods': [], 'as_of': None},
                            'observed_at': _iso(self.observed), 'provider_as_of': None,
                            'within_cutoff': True, 'complete': True, 'coverage_complete': True,
                            'data': [self.row], 'warnings': ['Untrusted text must not be archived.'],
                            'requests': [{'url': SOURCE['endpoint'] + '?function=EARNINGS_ESTIMATES&symbol=IBM&apikey=synthetic-key-not-for-storage',
                                          'retrieved_at': _iso(self.observed - timedelta(seconds=1)),
                                          'status': 200, 'bytes': 1234, 'sha256': 'a' * 64}]}

        def capture(self):
            self.input.write_text(json.dumps(self.payload), encoding='utf-8')

        def save(self, now=None):
            self.capture()
            return save_snapshot(self.input, self.vault, self.period, self.horizon, now=now or self.now)

        def next_observation(self):
            self.observed += timedelta(days=1)
            self.now = self.observed + timedelta(minutes=1)
            self.payload['observed_at'] = _iso(self.observed)
            self.payload['requests'][0]['retrieved_at'] = _iso(self.observed - timedelta(seconds=1))
            self.payload['requests'][0]['sha256'] = 'b' * 64

        def history(self, cutoff=None):
            return estimate_history(self.vault, _iso(cutoff or self.now), 'IBM', now=self.now)

        def pair(self):
            old = self.save()
            self.next_observation()
            self.row['values']['eps_estimate_average'] = '3.0000'
            return old, self.save()

        def test_selected_minimal_snapshot_and_private_atomic_output(self):
            other = copy.deepcopy(self.row)
            other['horizon'] = 'fiscal year'
            other['values']['eps_estimate_average'] = '9.9'
            self.payload['data'].append(other)
            result = self.save()
            path = Path(result['path'])
            self.assertEqual(result['status'], 'created')
            self.assertEqual(path.parent, self.vault / 'Investments' / 'Snapshots' / 'Estimates')
            self.assertTrue(NAME.fullmatch(path.name))
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            text = path.read_text(encoding='utf-8')
            self.assertNotIn('synthetic-key-not-for-storage', text)
            self.assertNotIn('Untrusted text', text)
            self.assertNotIn('9.9', text)
            self.assertNotIn('apikey', text)
            self.assertEqual(result['snapshot']['record'], self.row)
            self.assertEqual(result['snapshot']['estimate_snapshot'], 2)
            self.assertNotIn('saved_at', result['snapshot'])
            self.assertNotIn('available_at', result['snapshot'])
            self.assertEqual(result['available_at'], _iso(self.now))
            self.assertTrue(Path(result['receipt']).is_file())
            self.assertEqual(set(result['snapshot']['request']), {'status', 'retrieved_at', 'bytes', 'sha256'})
            self.assertFalse(list(self.vault.glob('.estimate-snapshot-stage-*')))

        def test_exact_retry_preserves_first_save_bytes_and_mtime(self):
            first = self.save()
            path = Path(first['path'])
            before = path.read_bytes(), path.stat().st_mtime_ns
            retry = self.save(now=self.now + timedelta(days=3))
            self.assertEqual(retry['status'], 'unchanged')
            self.assertEqual(retry['snapshot'], first['snapshot'])
            self.assertEqual(retry['available_at'], first['available_at'])
            self.assertEqual(retry['receipt'], first['receipt'])
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
            self.assertEqual(len(list(path.parent.iterdir())), 1)

        def test_new_observation_is_saved_even_without_estimate_change(self):
            first = self.save()
            self.next_observation()
            second = self.save()
            self.assertNotEqual(first['path'], second['path'])
            self.assertEqual(first['snapshot']['record'], second['snapshot']['record'])
            self.assertEqual(len(self.history()['snapshots']), 2)

        def test_late_cutoff_is_archived_only_for_later_use(self):
            self.payload['query']['as_of'] = _iso(self.observed - timedelta(seconds=1))
            self.payload.update(within_cutoff=False, complete=False)
            result = self.save()
            self.assertEqual(self.history(self.observed)['snapshots'], [])
            self.assertEqual(self.history(self.now - timedelta(microseconds=1))['snapshots'], [])
            self.assertEqual(self.history()['snapshots'][0]['path'], result['path'])

        def test_old_fiscal_period_and_late_save_do_not_backfill_availability(self):
            self.period = self.row['fiscal_period_end'] = '2020-03-31'
            self.now += timedelta(days=30)
            result = self.save()
            self.assertEqual(self.history(self.observed + timedelta(days=1))['snapshots'], [])
            self.assertEqual(result['available_at'], _iso(self.now))

        def test_partial_schema_failure_or_other_incompleteness_never_saves(self):
            for updates in ({'coverage_complete': False}, {'complete': False}, {'complete': 1},
                            {'provider_as_of': '2025-03-03'}, {'market_data': True}):
                with self.subTest(updates=updates):
                    payload = copy.deepcopy(self.payload)
                    self.payload.update(updates)
                    with self.assertRaises(ValueError):
                        self.save()
                    self.assertFalse((self.vault / 'Investments').exists())
                    self.payload = payload

        def test_explicit_period_and_horizon_are_required(self):
            self.capture()
            for period, horizon in (('2025-09-30', self.horizon), (self.period, 'fiscal year'),
                                    ('2025-02-30', self.horizon), (self.period, 'quarter')):
                with self.assertRaises(ValueError):
                    save_snapshot(self.input, self.vault, period, horizon, now=self.now)

        def test_duplicate_or_invalid_unselected_period_blocks_capture(self):
            empty = dict(self.row, horizon='fiscal year',
                         values={name: None for name in ESTIMATE_FIELDS})
            empty['values']['eps_estimate_analyst_count'] = '2'
            for extra in (copy.deepcopy(self.row), dict(self.row, horizon='unknown'), empty):
                self.payload['data'] = [self.row, extra]
                with self.assertRaises(ValueError):
                    self.save()
                self.assertFalse((self.vault / 'Investments').exists())

        def test_future_observation_and_inconsistent_cutoff_are_rejected(self):
            self.payload['observed_at'] = _iso(self.now + timedelta(seconds=1))
            with self.assertRaises(ValueError):
                self.save()
            self.payload['observed_at'] = _iso(self.observed)
            self.payload['query']['as_of'] = _iso(self.observed - timedelta(seconds=1))
            with self.assertRaises(ValueError):
                self.save()

        def test_failed_retries_are_not_independent_observations(self):
            failed = dict(self.payload['requests'][0], status=429, sha256=None)
            self.payload['requests'].insert(0, failed)
            result = self.save()
            self.assertEqual(result['snapshot']['request']['status'], 200)
            self.assertNotIn('requests', result['snapshot'])

        def test_missing_duplicate_or_wrong_success_provenance_is_rejected(self):
            successful = self.payload['requests'][0]
            for requests in ([], [dict(successful, status=500)], [successful, successful],
                             [dict(successful, sha256='bad')], [dict(successful, bytes=True)],
                             [dict(successful, retrieved_at=_iso(self.now))],
                             [dict(successful, url='https://example.invalid/?apikey=do-not-store')],
                             [dict(successful, url=successful['url'].replace('symbol=IBM', 'symbol=AAPL'))]):
                self.payload['requests'] = requests
                with self.assertRaises(ValueError):
                    self.save()

        def test_numeric_change_and_unknown_comparability_warning(self):
            old, new = self.pair()
            result = compare_snapshots(old['path'], new['path'], now=self.now)
            change = result['changes']['eps_estimate_average']
            self.assertEqual(change['absolute_change'], '0.5000')
            self.assertEqual(Decimal(change['percent_change']), Decimal(20))
            self.assertTrue(any('unknown' in warning and 'economically' in warning for warning in result['warnings']))
            self.assertEqual(result['available_at'], new['available_at'])

        def test_missing_values_never_become_zero_changes(self):
            old = self.save()
            self.next_observation()
            self.row['values']['revenue_estimate_average'] = None
            self.row['values']['eps_estimate_high'] = '3'
            new = self.save()
            result = compare_snapshots(old['path'], new['path'], now=self.now)
            for field in ('revenue_estimate_average', 'eps_estimate_high', 'eps_estimate_low'):
                self.assertIsNone(result['changes'][field]['absolute_change'])
                self.assertIsNone(result['changes'][field]['percent_change'])

        def test_percent_change_requires_positive_older_base(self):
            for base in ('0', '-2.5'):
                with self.subTest(base=base):
                    self.row['values']['eps_estimate_average'] = base
                    old = self.save()
                    self.next_observation()
                    self.row['values']['eps_estimate_average'] = '1.5'
                    new = self.save()
                    result = compare_snapshots(old['path'], new['path'], now=self.now)
                    self.assertIsNone(result['changes']['eps_estimate_average']['percent_change'])
                    self.assertEqual(Decimal(result['changes']['eps_estimate_average']['absolute_change']), Decimal('1.5') - Decimal(base))
                    self.next_observation()

        def test_large_exponent_difference_remains_exact(self):
            self.row['values']['eps_estimate_average'] = '1E-999'
            old = self.save()
            self.next_observation()
            self.row['values']['eps_estimate_average'] = '1'
            new = self.save()
            result = compare_snapshots(old['path'], new['path'], now=self.now)
            self.assertEqual(result['changes']['eps_estimate_average']['absolute_change'], '0.' + '9' * 999)

        def test_trailing_aggregates_are_not_promoted_to_historical_vintages(self):
            old, new = self.pair()
            result = compare_snapshots(old['path'], new['path'], now=self.now)
            self.assertEqual(set(result['changes']), set(ESTIMATE_FIELDS))
            self.assertTrue(any('current reported aggregates' in warning for warning in result['warnings']))
            self.assertNotIn('seven_days_ago_snapshot', result)

        def test_comparison_requires_exact_period_horizon_currency_and_symbol(self):
            old = self.save()
            for key, value in (('fiscal_period_end', '2025-09-30'), ('horizon', 'fiscal year'), ('currency', 'USD')):
                self.next_observation()
                previous = self.row[key]
                self.row[key] = value
                period, horizon = self.period, self.horizon
                self.period, self.horizon = self.row['fiscal_period_end'], self.row['horizon']
                new = self.save()
                with self.assertRaises(ValueError):
                    compare_snapshots(old['path'], new['path'], now=self.now)
                self.row[key], self.period, self.horizon = previous, period, horizon
            self.next_observation()
            self.payload['query']['symbol'] = 'AAPL'
            self.payload['requests'][0]['url'] = self.payload['requests'][0]['url'].replace('symbol=IBM', 'symbol=AAPL')
            new = self.save()
            with self.assertRaises(ValueError):
                compare_snapshots(old['path'], new['path'], now=self.now)

        def test_comparison_rejects_reversed_equal_and_late_saved_older_observations(self):
            old, new = self.pair()
            for left, right in ((new, old), (old, old)):
                with self.assertRaises(ValueError):
                    compare_snapshots(left['path'], right['path'], now=self.now)
            other = self.root / 'another-vault'
            other.mkdir()
            self.payload['observed_at'] = old['snapshot']['observed_at']
            self.payload['requests'][0]['retrieved_at'] = old['snapshot']['request']['retrieved_at']
            self.capture()
            later = save_snapshot(self.input, other, self.period, self.horizon, now=self.now + timedelta(days=1))
            with self.assertRaises(ValueError):
                compare_snapshots(later['path'], new['path'], now=self.now + timedelta(days=1))

        def test_history_reads_only_requested_ticker_and_known_availability(self):
            old, new = self.pair()
            result = self.history(_time(old['available_at']))
            self.assertEqual([item['path'] for item in result['snapshots']], [old['path']])
            empty = estimate_history(self.vault, _iso(self.now), 'AAPL', now=self.now)
            self.assertEqual(empty['snapshots'], [])
            self.assertEqual([item['path'] for item in self.history()['snapshots']], [old['path'], new['path']])

        def test_mixed_input_timestamp_precision_orders_by_instant(self):
            self.payload['observed_at'] = '2025-03-03T15:00:00Z'
            first = self.save()
            self.observed += timedelta(milliseconds=123)
            self.now += timedelta(milliseconds=123)
            self.payload['observed_at'] = '2025-03-03T10:00:00.123-05:00'
            self.payload['requests'][0]['retrieved_at'] = '2025-03-03T15:00:00.100Z'
            second = self.save()
            history = self.history()
            self.assertEqual([row['path'] for row in history['snapshots']], [first['path'], second['path']])
            self.assertEqual(first['snapshot']['observed_at'], '2025-03-03T15:00:00.000000Z')
            self.assertEqual(second['snapshot']['observed_at'], '2025-03-03T15:00:00.123000Z')

        def test_empty_history_does_not_create_directories(self):
            self.assertEqual(self.history()['snapshots'], [])
            self.assertEqual(list(self.vault.iterdir()), [])
            with self.assertRaises(ValueError):
                self.history(self.now + timedelta(seconds=1))

        def test_content_or_first_save_tampering_is_detected_without_overwrite(self):
            result = self.save()
            path = Path(result['path'])
            original = path.read_bytes()
            value = json.loads(original)
            value['saved_at'] = value['available_at'] = value['observed_at']
            path.write_bytes(_canonical(value))
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                self.save()
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaises(ValueError):
                self.history()
            path.write_bytes(original)

        def test_wrong_filename_nonminimal_fields_and_future_save_are_rejected(self):
            result = self.save()
            path = Path(result['path'])
            value = json.loads(path.read_bytes())
            with self.assertRaises(ValueError):
                _validate_snapshot(dict(value, credentials='never-valid'), path.name)
            with self.assertRaises(ValueError):
                _validate_snapshot(value, path.name.replace('IBM', 'AAPL'))
            value['saved_at'] = value['available_at'] = _iso(self.now + timedelta(days=1))
            value['estimate_snapshot'] = 1
            value['snapshot_sha256'] = hashlib.sha256(_canonical({key: item for key, item in value.items() if key != 'snapshot_sha256'})).hexdigest()
            path.write_bytes(_canonical(value))
            with self.assertRaises(ValueError):
                self.history()

        def test_receipt_waits_until_observation_publication_and_readback_finish(self):
            self.capture()
            started, original = self.now, publish_pinned
            def delayed(*args):
                result = original(*args)
                self.now += timedelta(seconds=3)
                return result
            with patch(__name__ + '.publish_pinned', side_effect=delayed):
                saved = save_snapshot(self.input, self.vault, self.period, self.horizon, clock=lambda: self.now)
            self.assertEqual(saved['available_at'], _iso(started + timedelta(seconds=3)))
            self.assertEqual(self.history(started + timedelta(seconds=2))['snapshots'], [])
            self.assertEqual(self.history()['snapshots'][0]['path'], saved['path'])

        def test_failed_receipt_leaves_unavailable_observation_and_retry_never_backdates(self):
            self.capture()
            with patch.object(receipt_store, 'write', side_effect=receipt_store.PublicationError('fixture receipt failure')):
                with self.assertRaises(RuntimeError):
                    self.save()
            path = next((self.vault / 'Investments/Snapshots/Estimates').iterdir())
            original = path.read_bytes()
            result = self.history()
            self.assertFalse(result['complete'])
            self.assertEqual(result['snapshots'], [])
            self.assertEqual(result['unverified_snapshots'][0]['path'], str(path))
            before_retry = self.now
            self.now += timedelta(hours=1)
            retry = self.save()
            self.assertEqual(retry['status'], 'unchanged')
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(retry['available_at'], _iso(self.now))
            self.assertEqual(self.history(before_retry)['snapshots'], [])

        def test_legacy_bytes_remain_readable_but_need_new_verified_receipt(self):
            self.capture()
            saved = _save_observation(self.input, self.vault, self.period, self.horizon, now=self.now)
            path = Path(saved['path'])
            value = dict(saved['snapshot'], estimate_snapshot=1, saved_at=_iso(self.now), available_at=_iso(self.now))
            value['snapshot_sha256'] = hashlib.sha256(_canonical({key: item for key, item in value.items()
                if key != 'snapshot_sha256'})).hexdigest()
            original = _canonical(value)
            path.write_bytes(original)
            self.assertEqual(_validate_snapshot(value, path.name), value)
            self.assertEqual(self.history()['snapshots'], [])
            with self.assertRaisesRegex(ValueError, 'unverified'):
                compare_snapshots(path, path, now=self.now)
            original_cutoff = self.now
            self.now += timedelta(hours=2)
            retry = self.save()
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(retry['available_at'], _iso(self.now))
            self.assertEqual(self.history(original_cutoff)['snapshots'], [])
            self.assertEqual(self.history()['snapshots'][0]['snapshot'], value)

        def test_receipt_tampering_or_missing_receipt_never_grants_availability(self):
            saved = self.save()
            path = Path(saved['receipt'])
            raw = path.read_bytes()
            path.write_bytes(raw + b' ')
            with self.assertRaises(ValueError):
                self.history()
            path.unlink()
            self.assertFalse(self.history()['complete'])
            self.assertEqual(self.history()['snapshots'], [])
            path.symlink_to(self.input)
            with self.assertRaises(ValueError):
                self.history()

        def test_symlink_and_portable_folder_owners_are_rejected(self):
            investments = self.vault / 'Investments'
            investments.mkdir()
            external = self.root / 'external'
            external.mkdir()
            (investments / 'Snapshots').symlink_to(external, target_is_directory=True)
            with self.assertRaises(ValueError):
                self.save()
            self.assertEqual(list(external.iterdir()), [])
            (investments / 'Snapshots').unlink()
            (investments / 'snapshots').mkdir()
            with self.assertRaises(ValueError):
                self.save()

        def test_nonregular_or_noncanonical_snapshot_owners_are_rejected(self):
            result = self.save()
            path = Path(result['path'])
            data = path.read_bytes()
            path.unlink()
            path.symlink_to(self.input)
            with self.assertRaises(ValueError):
                self.history()
            with self.assertRaises(ValueError):
                self.save()
            path.unlink()
            path.with_name(path.name.replace('IBM', 'ibm')).write_bytes(data)
            with self.assertRaises(ValueError):
                self.save()

        def test_bounded_input_duplicate_json_and_symlink_are_rejected(self):
            self.input.write_bytes(b'x' * (MAX_BYTES + 1))
            with self.assertRaises(ValueError):
                save_snapshot(self.input, self.vault, self.period, self.horizon, now=self.now)
            self.input.write_text('{"market_data":1,"market_data":1}', encoding='utf-8')
            with self.assertRaises(ValueError):
                save_snapshot(self.input, self.vault, self.period, self.horizon, now=self.now)
            self.capture()
            link = self.root / 'linked.json'
            link.symlink_to(self.input)
            with self.assertRaises(ValueError):
                save_snapshot(link, self.vault, self.period, self.horizon, now=self.now)

        def test_input_change_after_validation_preserves_recovery(self):
            self.capture()
            original = _selected
            def swap(*args):
                result = original(*args)
                self.input.write_text('{}', encoding='utf-8')
                return result
            with patch(__name__ + '._selected', side_effect=swap), self.assertRaises(RuntimeError):
                save_snapshot(self.input, self.vault, self.period, self.horizon, now=self.now)
            self.assertTrue(list(self.vault.glob('.estimate-snapshot-stage-*')))
            folder = self.vault / 'Investments' / 'Snapshots' / 'Estimates'
            self.assertEqual(list(folder.iterdir()), [])

        def test_folder_replacement_cannot_redirect_publication(self):
            original = publish_pinned
            displaced = self.root / 'displaced'
            def swap(staged, target, stage_parent, identity):
                target.parent.rename(displaced)
                target.parent.mkdir()
                return original(staged, target, stage_parent, identity)
            with patch(__name__ + '.publish_pinned', side_effect=swap), self.assertRaises(RuntimeError):
                self.save()
            self.assertEqual(list(displaced.iterdir()), [])
            self.assertEqual(list((self.vault / 'Investments' / 'Snapshots' / 'Estimates').iterdir()), [])
            self.assertTrue(list(self.vault.glob('.estimate-snapshot-stage-*')))

        def test_publication_failure_retains_named_recovery(self):
            with patch(__name__ + '.publish_pinned', side_effect=OSError('synthetic publication failure')):
                with self.assertRaises(RuntimeError) as failure:
                    self.save()
            stage = next(self.vault.glob('.estimate-snapshot-stage-*'))
            self.assertIn(str(stage), str(failure.exception))
            self.assertEqual(len(list(stage.iterdir())), 1)

        def test_cli_errors_are_json_and_preserve_recovery_exit(self):
            self.capture()
            with patch('sys.stdout', new_callable=io.StringIO) as output:
                code = main(['save', '--input', str(self.input), '--vault', str(self.vault),
                             '--period', 'invalid', '--horizon', self.horizon])
            self.assertEqual(code, 2)
            self.assertIn('error', json.loads(output.getvalue()))
            with patch(__name__ + '.save_snapshot', side_effect=RuntimeError('preserve fixture-stage')):
                with patch('sys.stdout', new_callable=io.StringIO) as output:
                    code = main(['save', '--input', str(self.input), '--vault', str(self.vault),
                                 '--period', self.period, '--horizon', self.horizon])
            self.assertEqual(code, 3)
            self.assertIn('recovery', json.loads(output.getvalue()))

        def test_bad_cli_arguments_do_not_echo_accidental_secret_values(self):
            with patch('sys.stdout', new_callable=io.StringIO) as output:
                code = main(['save', '--unexpected', 'synthetic-argument-secret'])
            self.assertEqual(code, 2)
            self.assertNotIn('synthetic-argument-secret', output.getvalue())
            self.assertIn('error', json.loads(output.getvalue()))

    result = unittest.TextTestRunner(verbosity=0).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print('%d/%d self-tests passed' % (passed, result.testsRun))
    return 0 if result.wasSuccessful() else 1


def main(argv=None):
    class SafeParser(argparse.ArgumentParser):
        def error(self, message):
            raise ValueError('invalid command arguments; use --help for the selected command')

    parser = SafeParser(description=__doc__)
    parser.add_argument('--test', action='store_true', help='run offline snapshot tests')
    commands = parser.add_subparsers(dest='command')
    save = commands.add_parser('save', help='create one immutable selected observation')
    save.add_argument('--input', required=True)
    save.add_argument('--vault', required=True)
    save.add_argument('--period', required=True)
    save.add_argument('--horizon', required=True, choices=HORIZONS)
    history = commands.add_parser('history', help='read only snapshots available by the cutoff')
    history.add_argument('--vault', required=True)
    history.add_argument('--as-of', required=True)
    history.add_argument('--symbol', required=True)
    compare = commands.add_parser('compare', help='compare two exact matching archived periods')
    compare.add_argument('--older', required=True)
    compare.add_argument('--newer', required=True)
    try:
        args = parser.parse_args(argv)
        if args.test:
            return run_self_test()
        if args.command == 'save':
            result = save_snapshot(args.input, args.vault, args.period, args.horizon)
        elif args.command == 'history':
            result = estimate_history(args.vault, args.as_of, args.symbol)
        elif args.command == 'compare':
            result = compare_snapshots(args.older, args.newer)
        else:
            parser.print_help()
            return 0
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except RuntimeError as exc:
        print(json.dumps({'error': str(exc), 'recovery': 'preserve the named recovery stage'}))
        return 3
    except (ValueError, OSError) as exc:
        print(json.dumps({'error': str(exc)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
