#!/usr/bin/env python3
"""Bounded, receipted history for explicit nominees; transport belongs to stock_acquire.

Acquisition completeness means pagination and symbol validation succeeded, not
that regular-session liquidity or any investment trigger has been verified.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

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
from market_acquire import Acquisition
import market_capture as capture_utils
import market_estimate_history as dates
import market_evidence as evidence
import market_price_capture as raw_prices
import market_prices as prices
from market_http import DataError, parse_date, parse_time, utc_now

FOLDER = ('Investments', 'Snapshots', 'PriceHistory')
KEYS = {'timeframe', 'start', 'end', 'adjustment', 'asof', 'reason', 'max_pages'}
IDENTITY = raw_prices.PLAN_KEYS - {'reason'}
NAME = re.compile(r'[0-9a-f]{64}\.json\Z')
MAX_FILES = 20000
RECEIPT_BYTES = 8192


def _fail(message):
    raise DataError('invalid_history_evidence', message)


def validate_requests(value, current):
    """Validate the explicit per-nominee windows before any credentials or I/O."""
    if not isinstance(value, list) or len(value) > 4:
        _fail('Use at most four justified history windows per nominee.')
    result, seen = [], set()
    for row in value:
        if not isinstance(row, dict) or set(row) != KEYS:
            _fail('History requires exactly timeframe, start, end, adjustment, asof, reason and max_pages.')
        if row['timeframe'] not in {'1Day', '1Min'} or row['adjustment'] not in {'raw', 'split'}:
            _fail('History supports daily or minute SIP bars with explicit raw or split adjustment.')
        start, end = parse_time(row['start']), parse_time(row['end'])
        maximum = 370 if row['timeframe'] == '1Day' else 45
        if not timedelta(0) < end - start <= timedelta(days=maximum) or end > current - timedelta(minutes=15):
            _fail('History windows must be completed and SIP-delay-safe, at most 370 daily or 45 minute-history days.')
        if row['timeframe'] == '1Day':
            midnight = datetime.combine(start.astimezone(raw_prices._ny()).date(), time.min, raw_prices._ny())
            first_day = midnight if midnight >= start else midnight + timedelta(days=1)
            if first_day > _effective_end(row):
                _fail('A daily history window must contain at least one fully elapsed New York daily interval.')
        mapping = parse_date(row['asof'])
        if mapping > current.astimezone(raw_prices._ny()).date():
            _fail('History symbol mapping cannot use a future date.')
        if (max(end.astimezone(raw_prices._ny()).date(), mapping) - start.astimezone(raw_prices._ny()).date()).days > 372:
            _fail('History calendar through its mapping date must stay within a bounded 372-day window.')
        if type(row['max_pages']) is not int or not 1 <= row['max_pages'] <= 20:
            _fail('History pagination must be bounded to one through twenty pages.')
        reason = row['reason']
        if (not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 400
                or any(ord(char) < 32 or ord(char) == 127 for char in reason)):
            _fail('Give a brief plain-text reason for each needed history window.')
        reason.encode('utf-8')
        checked = dict(row, start=dates._iso(start), end=dates._iso(end), asof=mapping.isoformat())
        key = _key(checked)
        if key in seen:
            _fail('A nominee must not repeat the same history query.')
        seen.add(key); result.append(checked)
    return result


def _key(request):
    return tuple(request[field] for field in sorted(KEYS - {'reason', 'max_pages'}))


def _identity(nominee):
    return {key: nominee[key] for key in IDENTITY}


def _calendar_dates(request):
    ny = raw_prices._ny()
    start, end = (parse_time(request[key]).astimezone(ny).date() for key in ('start', 'end'))
    return start.isoformat(), max(end, parse_date(request['asof'])).isoformat()


def _effective_end(request):
    end = parse_time(request['end'])
    if request['timeframe'] == '1Day':
        end = datetime.combine(end.astimezone(raw_prices._ny()).date(), time.min, raw_prices._ny()) - timedelta(microseconds=1)
    return end


def _requests(rows, endpoint, observed, maximum):
    if not isinstance(rows, list) or len(rows) > 100:
        _fail('History needs bounded provider request provenance.')
    successes = []
    for row in rows:
        if not isinstance(row, dict) or row.get('url', '').split('?', 1)[0] != endpoint:
            _fail('History request provenance uses an unexpected provider endpoint.')
        if row.get('status') == 200:
            successes.append(dates._request(row, observed))
    if not 1 <= len(successes) <= maximum:
        _fail('History needs successful provider response receipts within its page budget.')
    return successes


def _calendar(payload, request, observed):
    start, end = _calendar_dates(request)
    if (not isinstance(payload, dict) or payload.get('provider') != 'alpaca'
            or payload.get('resource') != 'calendar' or payload.get('complete') is not True
            or payload.get('source', {}).get('url') != prices.CALENDAR_URL
            or any(payload.get('query', {}).get(key) != val for key, val in [('start', start), ('end', end)])):
        _fail('History requires a complete provider calendar for its exact window.')
    sessions, seen = [], set()
    rows = payload.get('data', {}).get('sessions')
    if not isinstance(rows, list) or len(rows) > 372:
        _fail('Calendar sessions are missing or exceed the bounded history window.')
    for row in rows:
        day = parse_date(row['date'])
        opened, closed = parse_time(row['open_at']), parse_time(row['close_at'])
        if (day in seen or not parse_date(start) <= day <= parse_date(end) or opened >= closed
                or any(stamp.astimezone(raw_prices._ny()).date() != day or stamp.second or stamp.microsecond
                       for stamp in (opened, closed))):
            _fail('Calendar intervals must be unique complete minute-aligned regular sessions.')
        seen.add(day)
        sessions.append({'date': day.isoformat(), 'open_at': dates._iso(opened), 'close_at': dates._iso(closed)})
    return {'start': start, 'end': end, 'sessions': sorted(sessions, key=lambda item: item['date']),
            'requests': _requests(payload.get('requests'), prices.CALENDAR_URL, observed, 1)}


def _snapshot(payload, nominee, request, calendar, observed):
    if (not isinstance(payload, dict) or payload.get('provider') != 'alpaca'
            or payload.get('resource') != 'bars' or type(payload.get('complete')) is not bool
            or payload.get('source', {}).get('url') != prices.BARS_URL
            or payload.get('source', {}).get('feed') != 'sip'):
        _fail('History requires the typed Alpaca SIP bar adapter response.')
    query, pagination, data = payload.get('query', {}), payload.get('pagination', {}), payload.get('data', {})
    end = _effective_end(request)
    expected = {key: request[key] for key in ('start', 'timeframe', 'adjustment', 'asof')}
    expected.update(end=dates._iso(end), requested_end=request['end'], currency='USD', feed='sip')
    if any((parse_time(query.get(key)) != parse_time(value) if key in {'start', 'end', 'requested_end'}
            else query.get(key) != value) for key, value in expected.items()):
        _fail('History response does not match its explicit query window or price basis.')
    requested = prices._symbols(query.get('symbols'))
    if (nominee['symbol'] not in requested or data.get('requested_symbols') != requested
            or type(pagination.get('pages')) is not int or not 1 <= pagination['pages'] <= request['max_pages']
            or type(pagination.get('exhausted')) is not bool):
        _fail('History scope or pagination diagnostics are invalid.')
    missing, duplicate, rejected = (data.get(key) for key in ('missing_symbols', 'duplicate_symbols', 'rejected_symbols'))
    if (not isinstance(missing, list) or not isinstance(duplicate, list) or not isinstance(rejected, list)
            or any(not isinstance(row, dict) or not isinstance(row.get('symbol'), str) for row in rejected)
            or any(symbol not in requested for symbol in missing + duplicate + [row['symbol'] for row in rejected])):
        _fail('History requires typed missing, duplicate and rejected-symbol diagnostics.')
    symbol = nominee['symbol']
    source_bars = data.get('bars')
    if not isinstance(source_bars, dict) or set(source_bars) - set(requested) or not isinstance(source_bars.get(symbol), list):
        _fail('History has an invalid per-symbol bar inventory.')
    bars, seen = [], set()
    for row in source_bars[symbol]:
        checked = prices._bar(row, request['timeframe'], parse_time(request['start']), end)
        if checked is None or checked != row or checked['interval_start'] in seen:
            _fail('Archived history must contain canonical, unique, completed intervals.')
        seen.add(checked['interval_start']); bars.append(checked)
    if (not bars) != (symbol in missing):
        _fail('History missing-symbol diagnostics do not match the retained bars.')
    error = pagination.get('error', {}).get('code')
    if error is not None and (not isinstance(error, str) or not re.fullmatch('[a-z_]{1,64}', error)):
        _fail('History pagination error needs a typed public diagnostic.')
    coverage = {'pages': pagination['pages'], 'exhausted': pagination['exhausted'],
                'missing': symbol in missing, 'duplicate': symbol in duplicate,
                'rejected': any(row['symbol'] == symbol for row in rejected), 'error_code': error}
    coverage['complete'] = bool(coverage['exhausted'] and not error and not any(coverage[key] for key in ('missing', 'duplicate', 'rejected')))
    if payload['complete'] and (not coverage['complete'] or missing or duplicate or rejected):
        _fail('Complete source coverage conflicts with provider diagnostics.')
    if not payload['complete'] and coverage['exhausted'] and not error and not (missing or duplicate or rejected):
        _fail('Incomplete source coverage requires explicit pagination or symbol diagnostics.')
    if coverage['rejected'] and bars:
        _fail('Rejected symbol histories must not retain usable bars.')
    requests = _requests(payload.get('requests'), prices.BARS_URL, observed, request['max_pages'] + 1)
    if not pagination['pages'] <= len(requests) <= pagination['pages'] + bool(pagination.get('error')):
        _fail('History page counts disagree with successful response provenance.')
    return {'stock_history': 1, 'identity': _identity(nominee), 'request': request,
            'observed_at': dates._iso(observed), 'calendar': calendar,
            'bars': sorted(bars, key=lambda row: row['interval_start']), 'coverage': coverage,
            'requests': requests}


def _validate_snapshot(value, current):
    if (not isinstance(value, dict) or set(value) != {'stock_history', 'identity', 'request', 'observed_at', 'calendar', 'bars', 'coverage', 'requests'}
            or type(value['stock_history']) is not int or value['stock_history'] != 1
            or not isinstance(value['identity'], dict) or set(value['identity']) != IDENTITY):
        _fail('Unrecognized archived history schema.')
    observed = parse_time(value['observed_at'])
    if observed > current:
        _fail('History observation cannot be in the future.')
    raw_prices._item(dict(value['identity'], reason='Archived history identity'), observed)
    request = validate_requests([value['request']], observed)[0]
    if request != value['request']:
        _fail('History request is not canonical.')
    cal = value['calendar']
    if not isinstance(cal, dict) or set(cal) != {'start', 'end', 'sessions', 'requests'}:
        _fail('Unrecognized archived history calendar.')
    checked = _calendar({'provider': 'alpaca', 'resource': 'calendar', 'complete': True,
        'source': {'url': prices.CALENDAR_URL}, 'query': cal, 'data': {'sessions': cal['sessions']},
        'requests': [dict(row, url=prices.CALENDAR_URL) for row in cal['requests']]}, request, observed)
    if checked != cal:
        _fail('History calendar is not canonical.')
    coverage = value['coverage']
    if (not isinstance(coverage, dict) or set(coverage) != {'pages', 'exhausted', 'missing', 'duplicate', 'rejected', 'error_code', 'complete'}
            or any(type(coverage[key]) is not bool for key in ('exhausted', 'missing', 'duplicate', 'rejected', 'complete'))):
        _fail('Unrecognized history coverage diagnostics.')
    envelopes = _adapter_payloads(value)
    rebuilt = _snapshot(envelopes['prices'], value['identity'], request, cal, observed)
    if rebuilt != value:
        _fail('History content or provenance is not canonical validated evidence.')


def _adapter_payloads(value):
    """Reconstruct only validated, per-symbol original-adapter fields."""
    request, coverage, cal = value['request'], value['coverage'], value['calendar']
    symbol = value['identity']['symbol']
    end = _effective_end(request)
    query = {key: request[key] for key in ('start', 'timeframe', 'adjustment', 'asof')}
    query.update(end=dates._iso(end), requested_end=request['end'], currency='USD', feed='sip', symbols=symbol)
    pagination = {key: coverage[key] for key in ('pages', 'exhausted')}
    if coverage['error_code']:
        pagination['error'] = {'code': coverage['error_code']}
    price_payload = {'market_data': 1, 'operation': 'prices', 'provider': 'alpaca', 'resource': 'bars', 'complete': coverage['complete'],
        'source': {'url': prices.BARS_URL, 'feed': 'sip'}, 'query': query, 'pagination': pagination,
        'data': {'requested_symbols': [symbol], 'bars': {symbol: value['bars']},
                 'missing_symbols': [symbol] if coverage['missing'] else [],
                 'duplicate_symbols': [symbol] if coverage['duplicate'] else [],
                 'rejected_symbols': [{'symbol': symbol}] if coverage['rejected'] else []},
        'requests': [dict(row, url=prices.BARS_URL) for row in value['requests']],
        'warnings': ['Per-symbol evidence derived from the original validated acquisition batch.',
                     'Completeness is provider pagination and symbol validation, not complete minute coverage or verified liquidity.',
                     'Daily bars include all eligible sessions; their closes are not official closing-auction prices.',
                     'Adjusted history is available from capture, not proof of what was known on each bar date.']}
    calendar_payload = {'market_data': 1, 'operation': 'sessions', 'provider': 'alpaca', 'resource': 'calendar', 'complete': True,
        'query': {key: cal[key] for key in ('start', 'end')}, 'source': {'url': prices.CALENDAR_URL},
        'data': {'sessions': cal['sessions']}, 'requests': [dict(row, url=prices.CALENDAR_URL) for row in cal['requests']],
        'warnings': ['Calendar boundaries are scheduled regular-session markers, not observed trade timestamps.']}
    return {'prices': price_payload, 'sessions': calendar_payload}


def payloads(vault, snapshot, receipt, as_of, current=None):
    """Return validated per-symbol derivatives in the existing calculator format.

    The derivative label, original bar/query timestamps, response provenance and
    first-save receipt stay explicit. A late receipt is never admitted merely
    because the underlying bar describes an earlier trading session.
    """
    current = current or utc_now()
    cutoff = parse_time(as_of)
    if cutoff > current:
        _fail('History export cutoff cannot be in the future.')
    with evidence.pinned_directory(vault, FOLDER) as (root, descriptor, _):
        paths = [Path(path).expanduser().absolute() for path in (snapshot, receipt)]
        if any(path.parent != root.joinpath(*FOLDER) or not NAME.fullmatch(path.name) for path in paths):
            _fail('History export requires the exact snapshot and receipt paths in the selected vault.')
        value, stamp = (_read(descriptor, path.name) for path in paths)
        _validate_snapshot(value, current)
        _validate_receipt(stamp, current)
        if (stamp['snapshot_sha256'] != paths[0].stem
                or any(stamp[key] != value[key] for key in ('identity', 'request', 'observed_at'))):
            _fail('History receipt does not identify the exact selected snapshot.')
        if parse_time(stamp['available_at']) > cutoff:
            raise DataError('history_future_only', 'History was first saved after the fixed cutoff and cannot supply that edition.')
        result = _adapter_payloads(value)
        for envelope in result.values():
            envelope['evidence'] = {'snapshot': str(paths[0]), 'receipt': str(paths[1]),
                                    'observed_at': value['observed_at'], 'available_at': stamp['available_at']}
        return result


def _archive(vault, value, clock):
    _validate_snapshot(value, clock())
    saved = evidence.write(value, vault, FOLDER)
    available = clock()
    if available < parse_time(value['observed_at']):
        _fail('Clock moved behind the history observation; retain unreceipted evidence without eligibility.')
    receipt = {'history_receipt': 1, 'snapshot_sha256': saved['sha256'], 'identity': value['identity'],
               'request': value['request'], 'observed_at': value['observed_at'], 'available_at': dates._iso(available)}
    stamped = evidence.write(receipt, vault, FOLDER, RECEIPT_BYTES)
    return dict(snapshot=saved['path'], receipt=stamped['path'], available_at=receipt['available_at'])


def _read(descriptor, name, maximum=evidence.MAX_BYTES):
    raw = evidence.read_bytes(descriptor, name, maximum)
    value = capture_utils._json(raw)
    if evidence.canonical(value) != raw or hashlib.sha256(raw).hexdigest() + '.json' != name:
        _fail('History archive content hash or canonical bytes disagree.')
    return value


def _validate_receipt(receipt, current):
    if (not isinstance(receipt, dict) or set(receipt) != {'history_receipt', 'snapshot_sha256', 'identity', 'request', 'observed_at', 'available_at'}
            or type(receipt['history_receipt']) is not int or receipt['history_receipt'] != 1):
        _fail('Unrecognized history availability receipt.')
    observed, available = parse_time(receipt['observed_at']), parse_time(receipt['available_at'])
    if (not observed <= available <= current or not isinstance(receipt['snapshot_sha256'], str)
            or not dates.DIGEST.fullmatch(receipt['snapshot_sha256'])):
        _fail('History receipt has an invalid snapshot identity or chronology.')
    raw_prices._item(dict(receipt['identity'], reason='Archived history identity'), observed)
    if validate_requests([receipt['request']], observed)[0] != receipt['request']:
        _fail('History receipt query is not canonical.')


def _saved(vault, requests, current, reuse_hours, cutoff=None):
    """Read small receipts first; only matching histories need expensive bar validation."""
    wanted = {(tuple(sorted(_identity(row).items())), _key(request)) for row, request in requests}
    found, opened = [], False
    if not wanted:
        return found
    try:
        with evidence.pinned_directory(vault, FOLDER) as (root, descriptor, check):
            opened = True
            names = sorted(os.listdir(descriptor))
            if len(names) > MAX_FILES or any(not NAME.fullmatch(name) for name in names):
                _fail('History archive inventory is excessive or contains an unexpected occupant.')
            for name in names:
                entry = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                if not stat.S_ISREG(entry.st_mode) or entry.st_size > evidence.MAX_BYTES:
                    _fail('History archive occupants must be bounded regular files, never symlinks.')
                if entry.st_size > RECEIPT_BYTES:
                    continue
                receipt = _read(descriptor, name, RECEIPT_BYTES)
                if isinstance(receipt, dict) and 'stock_history' in receipt:
                    continue
                _validate_receipt(receipt, current)
                observed, available = parse_time(receipt['observed_at']), parse_time(receipt['available_at'])
                key = tuple(sorted(receipt['identity'].items())), _key(receipt['request'])
                late = bool(cutoff and available > cutoff)
                if key not in wanted or (observed < current - timedelta(hours=reuse_hours) and not late):
                    continue
                snapshot_name = receipt['snapshot_sha256'] + '.json'
                value = _read(descriptor, snapshot_name)
                _validate_snapshot(value, current)
                if any(receipt[key] != value[key] for key in ('identity', 'request', 'observed_at')):
                    _fail('History receipt does not match its immutable snapshot.')
                found.append(dict(snapshot=str(root.joinpath(*FOLDER, snapshot_name)),
                    receipt=str(root.joinpath(*FOLDER, name)), available_at=receipt['available_at'],
                    observed_at=value['observed_at'], identity=value['identity'], request=value['request'], coverage=value['coverage']))
            if sorted(os.listdir(descriptor)) != names:
                _fail('History archive changed during inspection; retry without overwriting saved evidence.')
            check()
    except FileNotFoundError:
        if opened:
            _fail('History archive disappeared during inspection.')
    return found


def inspect(vault, plan, current, cutoff=None, reuse_hours=24):
    """Offline exact-query cache selection; never creates files or loads credentials."""
    requests = [(row, request) for row in plan for request in validate_requests(row.get('history', []), current)]
    saved = _saved(vault, requests, current, reuse_hours, cutoff)
    result = []
    for nominee, request in requests:
        matches = [row for row in saved if row['identity'] == _identity(nominee) and _key(row['request']) == _key(request)]
        eligible = [row for row in matches if not cutoff or parse_time(row['available_at']) <= cutoff]
        chosen = max(eligible or matches, key=lambda row: (row['coverage']['complete'], parse_time(row['observed_at']),
            -parse_time(row['available_at']).timestamp()), default=None)
        row = dict(request, symbol=nominee['symbol'], class_id=nominee['class_id'], status='planned', complete=False)
        if chosen:
            row.update({key: chosen[key] for key in ('snapshot', 'receipt', 'available_at', 'observed_at', 'coverage')})
            row.update(status='reused' if chosen['coverage']['complete'] else 'reused_partial', complete=chosen['coverage']['complete'],
                       eligible_at_cutoff=bool(not cutoff or eligible), error_code=_coverage_error(chosen['coverage']))
            if cutoff and not eligible:
                row['status'] += '_future_only'
        result.append(row)
    return result


def _coverage_error(coverage):
    return (coverage['error_code'] or next((key + '_symbol' for key in ('rejected', 'duplicate', 'missing') if coverage[key]), None)
            or ('pagination_incomplete' if not coverage['exhausted'] else None))


def capture(vault, plan, client, clock=utc_now, cutoff=None, reuse_hours=24):
    """Fetch each missing query group once through the parent's budgeted transport."""
    rows = inspect(vault, plan, clock(), cutoff, reuse_hours)
    nominees = {row['symbol']: row for row in plan}
    groups = {}
    for row in rows:
        if row['status'] == 'planned':
            groups.setdefault((_key(row), row['max_pages']), []).append(row)
    run, calendars = Acquisition(client), {}
    for group in groups.values():
        request = {key: group[0][key] for key in KEYS}
        window = _calendar_dates(request)
        if window not in calendars:
            calendars[window] = run.fetch(['sessions', '--start', window[0], '--end', window[1]])
        cal_payload = calendars[window]
        if not cal_payload['complete']:
            for row in group:
                row.update(status='unavailable', error_code=cal_payload.get('error', {}).get('code', 'calendar_unavailable'))
            continue
        for offset in range(0, len(group), 200):
            batch = group[offset:offset + 200]
            argv = ['prices', '--symbols', ','.join(row['symbol'] for row in batch), '--feed', 'sip']
            for key in ('start', 'end', 'timeframe', 'adjustment', 'asof', 'max_pages'):
                argv.extend(['--' + key.replace('_', '-'), str(request[key])])
            payload = run.fetch(argv)
            observed = clock()
            if (not isinstance(payload.get('data', {}).get('bars'), dict)
                    or type(payload.get('pagination', {}).get('pages')) is not int
                    or payload['pagination']['pages'] < 1):
                for row in batch:
                    row.update(status='unavailable', error_code=payload.get('error', {}).get('code')
                               or payload.get('pagination', {}).get('error', {}).get('code') or 'history_unavailable')
                continue
            for row in batch:
                own_request = {key: row[key] for key in KEYS}
                value = _snapshot(payload, nominees[row['symbol']], own_request,
                                  _calendar(cal_payload, own_request, observed), observed)
                archived = _archive(vault, value, clock)
                future = bool(cutoff and parse_time(archived['available_at']) > cutoff)
                row.update(archived, observed_at=value['observed_at'], coverage=value['coverage'],
                           complete=value['coverage']['complete'], eligible_at_cutoff=not future,
                           status=('captured' if value['coverage']['complete'] else 'partial') + ('_future_only' if future else ''),
                           error_code=_coverage_error(value['coverage']))
    return rows


def recheck(vault, rows, current, cutoff=None, reuse_hours=24):
    """Revalidate selected immutable bytes after later acquisition phases, without requests."""
    plan = []
    for row in rows:
        if not row.get('snapshot'):
            continue
        # Exact saved identity is verified through its receipt, never invented
        # from a ticker while rechecking a later research cutoff.
        with evidence.pinned_directory(vault, FOLDER) as (_, descriptor, _):
            receipt_name = Path(row['receipt']).name
            if not NAME.fullmatch(receipt_name):
                _fail('Invalid selected history receipt path.')
            receipt = _read(descriptor, receipt_name, RECEIPT_BYTES)
            _validate_receipt(receipt, current)
        nominee = dict(receipt['identity'], history=[{key: row[key] for key in KEYS}])
        plan.append(nominee)
    checked = inspect(vault, plan, current, cutoff, reuse_hours)
    for row in rows:
        if not row.get('snapshot'):
            continue
        replacement = next((item for item in checked if item['symbol'] == row['symbol'] and _key(item) == _key(row)
                            and item.get('snapshot') == row['snapshot']), None)
        original = row['status']
        if replacement is None:
            row.update(status='stale', acquisition_status=original, eligible_at_cutoff=False,
                       error_code='history_stale', freshness_checked_at=dates._iso(current))
        elif cutoff and parse_time(row['available_at']) > cutoff and not original.endswith('_future_only'):
            row.update(status=original + '_future_only', acquisition_status=original, eligible_at_cutoff=False)
    return rows


def run_self_test():
    import tempfile
    import unittest
    from datetime import timezone

    class HistoryTests(unittest.TestCase):
        def test_plan_is_bounded_and_offline(self):
            now = datetime(2026, 9, 9, tzinfo=timezone.utc)
            request = {'timeframe': '1Min', 'start': '2026-09-01T00:00:00Z', 'end': '2026-09-08T20:00:00Z',
                       'adjustment': 'raw', 'asof': '2026-09-08', 'max_pages': 3, 'reason': 'Regular-session liquidity'}
            self.assertEqual(parse_time(validate_requests([request], now)[0]['start']), parse_time(request['start']))
            with self.assertRaises(DataError):
                validate_requests([dict(request, end=dates._iso(now))], now)
            with self.assertRaises(DataError):
                validate_requests([request, request], now)
            with tempfile.TemporaryDirectory() as folder:
                self.assertEqual(inspect(folder, [], now), [])
                self.assertEqual(list(Path(folder).iterdir()), [])
    result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(HistoryTests))
    print('%d/%d self-tests passed' % (result.testsRun - len(result.failures) - len(result.errors), result.testsRun))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', action='store_true')
    args = parser.parse_args()
    if args.test:
        raise SystemExit(run_self_test())
    parser.print_help()
