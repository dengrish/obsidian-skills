#!/usr/bin/env python3
"""Capture bounded raw prices before a fresh manual research cutoff; replay offline.

Explicit known nominees only. No discovery, social calls, orders or scheduling.
Uses the existing redacting transport and pinned create-only evidence writer.
An observation is published before its first-save receipt is timestamped.
"""
from __future__ import annotations

import argparse
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
import market_capitalization as capitalization
from market_credentials import credential_environment, load_credentials
import market_estimate_history as history
import market_evidence as evidence
from market_http import CREDENTIAL_NAMES, DataError, HttpClient, parse_date, parse_time, redact, utc_now
import market_prices as prices

FOLDER = ('Investments', 'Snapshots', 'Prices')
MAX_BYTES = 128 * 1024
MAX_FILES = 10000
NAME = re.compile(r'[0-9a-f]{64}\.json\Z')
PLAN_KEYS = {'symbol', 'class_id', 'identity_source_url', 'identity_available_at', 'reason'}
WARNINGS = [
    'Local availability starts after provider observation and successful first immutable publication, never at the bar timestamp.',
    'Raw minute closes are interval observations, not exact trade times or official closing-auction prices.',
    'Class identity is the explicitly reviewed plan declaration; the provider ticker alone does not verify issuer capitalization.',
    'Price capture does not complete the outstanding-share, corporate-action or entire-issuer size review.',
    'A frozen cutoff never moves; observations first saved later can only support subsequent editions.',
]


def _fail(message):
    raise DataError('invalid_price_evidence', message)


def _ny():
    """Load timezone data only during an operation, never during module import."""
    try:
        return ZoneInfo('America/New_York')
    except ZoneInfoNotFoundError:
        raise DataError('timezone_unavailable', 'Restore IANA timezone data for America/New_York before price capture or replay.') from None


def _iso(value):
    return history._iso(value)


def _item(value, current):
    if not isinstance(value, dict) or set(value) != PLAN_KEYS:
        _fail('Each price-plan item needs exactly symbol, class_id, identity_source_url, identity_available_at and reason.')
    history._symbol(value['symbol'])
    if not isinstance(value['class_id'], str) or not capitalization.CLASS.fullmatch(value['class_id']):
        _fail('Declare the verified quoted common class or ADS; no implicit class is assigned.')
    capitalization._url(value['identity_source_url'])
    if history._time(value['identity_available_at']) > current:
        _fail('Quoted-class identity evidence cannot be in the future.')
    reason = value['reason']
    if (not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 400
            or any(ord(char) < 32 or ord(char) == 127 for char in reason)):
        _fail('Use a brief plain-text reason identifying an already known nominee or tracked stock.')
    try:
        reason.encode('utf-8')
        value['identity_source_url'].encode('utf-8')
    except UnicodeError:
        _fail('Plan evidence and reasons must be valid UTF-8 text.')
    return dict(value)


def read_plan(path, current):
    raw, token = history.read_stable(path)
    if len(raw) > 32768:
        _fail('Price plan exceeds 32 KiB.')
    value = capture_utils._json(raw)
    if not isinstance(value, list) or not 1 <= len(value) <= 30:
        _fail('Use one to thirty explicitly justified known nominees, never a market-wide roster.')
    result = [_item(row, current) for row in value]
    if len({row['symbol'] for row in result}) != len(result):
        _fail('Each provider symbol must appear once with one reviewed quoted class.')
    return result, token


def _requests(rows, endpoint, observed):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 20:
        _fail('Bounded provider request provenance is required.')
    selected = []
    for row in rows:
        if not isinstance(row, dict) or row.get('status') != 200:
            continue
        url = row.get('url')
        if not isinstance(url, str) or url.split('?', 1)[0] != endpoint:
            _fail('Request provenance must use the fixed provider endpoint.')
        selected.append(history._request(row, observed))
    if len(selected) != 1:
        _fail('Exactly one complete successful page is required for each bounded capture endpoint.')
    return selected[0]


def _calendar(value, observed):
    if isinstance(value, dict) and isinstance(value.get('error'), dict):
        code = value['error'].get('code')
        if isinstance(code, str) and re.fullmatch(r'[a-z_]{1,64}', code):
            raise DataError(code, 'Calendar acquisition was unavailable; no complete coverage was assumed.')
    if (not isinstance(value, dict) or value.get('provider') != 'alpaca'
            or value.get('resource') != 'calendar' or value.get('complete') is not True
            or value.get('source', {}).get('url') != prices.CALENDAR_URL):
        _fail('A complete official-provider session calendar is required.')
    query = value.get('query', {})
    start, end = parse_date(query.get('start')), parse_date(query.get('end'))
    if not 1 <= (end - start).days <= 31:
        _fail('Use a bounded calendar covering the capture and upcoming replay dates.')
    rows = value.get('data', {}).get('sessions')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 32:
        _fail('Missing or excessive calendar coverage remains unresolved.')
    sessions, seen = [], set()
    for row in rows:
        day = parse_date(row['date'])
        opened, closed = history._time(row['open_at']), history._time(row['close_at'])
        if (day in seen or not start <= day <= end or opened >= closed
                or opened.astimezone(_ny()).date() != day or closed.astimezone(_ny()).date() != day
                or any(stamp.second or stamp.microsecond for stamp in (opened, closed))):
            _fail('Calendar sessions must be unique complete minute-aligned intervals on their dates.')
        seen.add(day)
        sessions.append({'date': day.isoformat(), 'open_at': _iso(opened), 'close_at': _iso(closed)})
    return {'start': start.isoformat(), 'end': end.isoformat(), 'sessions': sorted(sessions, key=lambda x: x['date']),
            'request': _requests(value.get('requests'), prices.CALENDAR_URL, observed)}


def _endpoint(calendar, cutoff):
    day = cutoff.astimezone(_ny()).date()
    if not parse_date(calendar['start']) <= day <= parse_date(calendar['end']):
        _fail('Archived calendar does not cover this cutoff date; capture new evidence without backdating it.')
    delayed = (cutoff - timedelta(minutes=15)).replace(second=0, microsecond=0)
    completed = [row for row in calendar['sessions'] if history._time(row['close_at']) <= cutoff]
    usable = [row for row in calendar['sessions'] if history._time(row['open_at']) < delayed]
    if not completed or not usable:
        _fail('Calendar does not establish the latest completed reference session and a delayed regular minute.')
    session = usable[-1]
    end = min(delayed, history._time(session['close_at']))
    return session, end, completed[-1]['date']


def _bounds(query, calendar, observed):
    start, end = history._time(query.get('start')), history._time(query.get('end'))
    session, expected_end, _ = _endpoint(calendar, observed)
    if (not timedelta(0) < end - start <= timedelta(minutes=5)
            or end > observed - timedelta(minutes=15)
            or not expected_end - timedelta(minutes=5) <= end <= expected_end
            or start < history._time(session['open_at'])
            or parse_date(query.get('asof')) != observed.astimezone(_ny()).date()):
        _fail('Capture intervals must be bounded, completed and SIP-delay-safe with explicit current symbol mapping.')
    return start, end, session


def _observation(payload, item, calendar, observed):
    if isinstance(payload.get('error'), dict):
        code = payload['error'].get('code')
        scoped_rejection = code == 'invalid_response' and payload.get('data', {}).get('rejected_symbols')
        if not scoped_rejection and isinstance(code, str) and re.fullmatch(r'[a-z_]{1,64}', code):
            raise DataError(code, 'Price acquisition was unavailable or rejected; no complete coverage was assumed.')
    if (payload.get('provider') != 'alpaca' or payload.get('resource') != 'bars'
            or type(payload.get('complete')) is not bool or payload.get('pagination', {}).get('exhausted') is not True
            or payload.get('pagination', {}).get('pages') != 1
            or payload.get('source', {}).get('url') != prices.BARS_URL
            or payload.get('source', {}).get('feed') != 'sip'):
        _fail('Only a complete single-page SIP capture can become archived price evidence.')
    query = payload.get('query', {})
    if any(query.get(k) != v for k, v in {'timeframe': '1Min', 'adjustment': 'raw', 'currency': 'USD', 'feed': 'sip'}.items()):
        _fail('Capitalization capture requires explicit raw USD SIP minute bars.')
    start, end, session = _bounds(query, calendar, observed)
    if query.get('requested_end') != query.get('end'):
        _fail('The requested and completed query intervals must agree.')
    requested = prices._symbols(query.get('symbols'))
    data = payload.get('data', {})
    bars = data.get('bars', {})
    missing, duplicates, rejected = data.get('missing_symbols'), data.get('duplicate_symbols'), data.get('rejected_symbols')
    if (not isinstance(missing, list) or not isinstance(duplicates, list) or not isinstance(rejected, list)
            or any(not isinstance(row, dict) or not isinstance(row.get('symbol'), str) for row in rejected)):
        _fail('Typed per-symbol missing, duplicate and rejection diagnostics are required.')
    bad = missing + duplicates + [row['symbol'] for row in rejected]
    if (any(not isinstance(symbol, str) or symbol not in requested for symbol in bad)
            or (payload['complete'] and bad) or (not payload['complete'] and not bad)):
        _fail('Source completeness is not explained by validated per-symbol diagnostics.')
    if (item['symbol'] not in requested or data.get('requested_symbols') != requested
            or not isinstance(bars, dict) or set(bars) - set(requested) or item['symbol'] in bad
            or not isinstance(bars.get(item['symbol']), list)):
        _fail('Missing, rejected or duplicate target coverage cannot be archived; unrelated valid targets remain usable.')
    selected, seen = [], set()
    opened, closed = history._time(session['open_at']), history._time(session['close_at'])
    for row in bars[item['symbol']]:
        checked = prices._bar(row, '1Min', start, end)
        if checked is None or checked != row or checked['interval_start'] in seen:
            _fail('Duplicate, incomplete or inconsistent minute intervals are not eligible price evidence.')
        seen.add(checked['interval_start'])
        if opened <= history._time(checked['interval_start']) < closed and history._time(checked['interval_end']) <= closed:
            selected.append(checked)
    if not selected:
        _fail('No completed regular-session bar was observed for the requested security.')
    bar = max(selected, key=lambda row: row['interval_end'])
    return {'price_observation': 1, 'identity': {k: item[k] for k in PLAN_KEYS if k != 'reason'},
            'observed_at': _iso(observed), 'source_url': prices.BARS_URL, 'feed': 'sip',
            'currency': 'USD', 'adjustment': 'raw', 'bar': bar, 'calendar': calendar,
            'query': {key: query[key] for key in ('start', 'end', 'asof')},
            'request': _requests(payload.get('requests'), prices.BARS_URL, observed)}


def archive(vault, observation, *, clock=utc_now):
    """Timestamp only after immutable observation publication and verified readback."""
    saved = evidence.write(observation, vault, FOLDER, MAX_BYTES)
    completed = clock()
    if completed < history._time(observation['observed_at']):
        _fail('Clock moved behind observation; retain the unreceipted observation, without eligibility.')
    receipt = {'price_receipt': 1, 'observation_sha256': saved['sha256'], 'available_at': _iso(completed)}
    return evidence.write(receipt, vault, FOLDER, MAX_BYTES)


def _records(vault, current):
    values, opened = {}, False
    try:
        with evidence.pinned_directory(vault, FOLDER) as (root, descriptor, check):
            opened = True
            names = sorted(os.listdir(descriptor))
            if len(names) > MAX_FILES:
                _fail('Price archive exceeds its bounded record inventory.')
            for name in names:
                if not NAME.fullmatch(name):
                    _fail('Unexpected price archive occupant; preserve it for inspection.')
                raw = evidence.read_bytes(descriptor, name, MAX_BYTES)
                value = capture_utils._json(raw)
                if evidence.canonical(value) != raw or hashlib.sha256(raw).hexdigest() + '.json' != name:
                    _fail('Price archive content-addressed identity or canonical bytes disagree.')
                values[name[:-5]] = (value, str(root.joinpath(*FOLDER, name)))
            if sorted(os.listdir(descriptor)) != names:
                _fail('Price archive changed during inspection; retry without replacing existing evidence.')
            check()
    except FileNotFoundError:
        if opened:
            _fail('Price archive disappeared during inspection.')
        return []
    observations, receipts = {}, []
    for digest, (value, path) in values.items():
        if not isinstance(value, dict):
            _fail('Unrecognized price archive record.')
        if set(value) == {'price_receipt', 'observation_sha256', 'available_at'} and type(value['price_receipt']) is int and value['price_receipt'] == 1:
            if not isinstance(value['observation_sha256'], str) or not history.DIGEST.fullmatch(value['observation_sha256']):
                _fail('Receipt has no valid observation identity.')
            if history._time(value['available_at']) > current:
                _fail('Receipt availability cannot be in the future relative to the actual clock.')
            receipts.append((value, path))
        elif (set(value) == {'price_observation', 'identity', 'observed_at', 'source_url', 'feed', 'currency', 'adjustment', 'bar', 'calendar', 'query', 'request'}
              and type(value['price_observation']) is int and value['price_observation'] == 1):
            if not isinstance(value['identity'], dict) or set(value['identity']) != PLAN_KEYS - {'reason'}:
                _fail('Archived quoted-class identity has unsupported fields.')
            _item(dict(value['identity'], reason='Archived reviewed identity'), current)
            observed = history._time(value['observed_at'])
            if observed > current or history._time(value['identity']['identity_available_at']) > observed:
                _fail('Observation or its identity evidence has an impossible time.')
            if (value['source_url'] != prices.BARS_URL or value['feed'] != 'sip'
                    or value['currency'] != 'USD' or value['adjustment'] != 'raw'):
                _fail('Archived source, feed, adjustment or currency is unsupported.')
            calendar = value['calendar']
            if (not isinstance(calendar, dict) or set(calendar) != {'start', 'end', 'sessions', 'request'}
                    or any(set(row) != {'date', 'open_at', 'close_at'} for row in calendar['sessions'])
                    or set(value['query']) != {'start', 'end', 'asof'}):
                _fail('Archived calendar or query fields are invalid.')
            checked_calendar = _calendar({'provider': 'alpaca', 'resource': 'calendar', 'complete': True,
                'source': {'url': prices.CALENDAR_URL}, 'query': calendar,
                'data': {'sessions': calendar['sessions']},
                'requests': [dict(calendar['request'], url=prices.CALENDAR_URL)]}, observed)
            if checked_calendar != calendar:
                _fail('Archived calendar is not canonical validated evidence.')
            start, end, _ = _bounds(value['query'], calendar, observed)
            bar = prices._bar(value['bar'], '1Min', start, end)
            if bar is None or bar != value['bar']:
                _fail('Archived bar must be a complete validated regular minute.')
            if history._request(value['request'], observed) != value['request']:
                _fail('Archived request provenance has unsupported fields or noncanonical times.')
            observations[digest] = (value, path)
        else:
            _fail('Unrecognized price archive schema; preserve existing records.')
    result = []
    for receipt, path in receipts:
        if receipt['observation_sha256'] not in observations:
            _fail('Price receipt refers to a missing observation; preserve the archive.')
        observation, observation_path = observations[receipt['observation_sha256']]
        if history._time(receipt['available_at']) < history._time(observation['observed_at']):
            _fail('Price availability precedes observation.')
        result.append({'observation': observation, 'observation_path': observation_path,
                       'receipt': path, 'available_at': receipt['available_at']})
    # Orphan observations left by a failed receipt publication are never selected.
    return result


def select(vault, plan, as_of, *, current=None, freshness_minutes=30):
    current = current or utc_now()
    cutoff = history._time(as_of)
    if cutoff > current or type(freshness_minutes) is not int or not 1 <= freshness_minutes <= 60:
        _fail('Use a nonfuture cutoff and one to sixty minutes of regular-session freshness.')
    records, items = _records(vault, current), []
    for item in plan:
        _item(item, current)
        identity = {k: item[k] for k in PLAN_KEYS if k != 'reason'}
        matching = [record for record in records if record['observation']['identity'] == identity]
        eligible, future, stale = [], [], []
        for record in matching:
            if history._time(record['available_at']) > cutoff:
                future.append(record); continue
            observation = record['observation']
            try:
                _, target, reference = _endpoint(observation['calendar'], cutoff)
                measured = history._time(observation['bar']['interval_end'])
                fresh = (target - timedelta(minutes=freshness_minutes) <= measured <= target
                         and observation['bar']['new_york_date'] >= reference)
            except DataError:
                fresh = False
            (eligible if fresh else stale).append(record)
        row = dict(item, status='missing', price=None, evidence=None)
        if eligible:
            chosen = max(eligible, key=lambda r: (r['observation']['bar']['interval_end'],
                         -history._time(r['available_at']).timestamp()))
            observed = chosen['observation']
            row.update(status='selected', price={'symbol': item['symbol'], 'class_id': item['class_id'],
                'usd': observed['bar']['c'], 'currency': 'USD', 'adjustment': 'raw',
                'as_of': observed['bar']['interval_end'], 'available_at': chosen['available_at'],
                'source_url': prices.BARS_URL}, evidence={k: chosen[k] for k in ('observation_path', 'receipt', 'available_at')})
        elif future:
            row.update(status='future_only', evidence={'available_at': min(r['available_at'] for r in future)})
        elif stale:
            row['status'] = 'stale'
        items.append(row)
    return {'market_price_capture': 1, 'complete': all(row['price'] is not None for row in items),
            'as_of': _iso(cutoff), 'freshness_minutes': freshness_minutes, 'items': items, 'warnings': list(WARNINGS)}


def capture(vault, plan_path, *, max_symbols=10, as_of=None, client=None, clock=utc_now, sleep=time.sleep):
    current = clock()
    if type(max_symbols) is not int or not 0 <= max_symbols <= 30:
        _fail('Capture at most zero to thirty already justified symbols.')
    plan, token = read_plan(plan_path, current)
    frozen = history._time(as_of) if as_of is not None else None
    initial = select(vault, plan, _iso(frozen or current), current=current)
    missing = [item for item, row in zip(plan, initial['items']) if row['status'] not in ('selected', 'future_only')]
    selected = missing[:max_symbols]
    errors, calls, published = {}, 0, set()
    if selected:
        if client is None:
            _fail('Capture requires the bounded credential-redacting market client.')
        run = Acquisition(client)
        day = current.astimezone(_ny()).date()
        calendar_payload = run.fetch(['sessions', '--start', (day - timedelta(days=14)).isoformat(),
                                      '--end', (day + timedelta(days=7)).isoformat()])
        try:
            calendar = _calendar(calendar_payload, clock())
            session, end, _ = _endpoint(calendar, current)
            start = max(history._time(session['open_at']), end - timedelta(minutes=5))
            payload = run.fetch(['prices', '--symbols', ','.join(row['symbol'] for row in selected),
                '--start', _iso(start), '--end', _iso(end), '--timeframe', '1Min', '--adjustment', 'raw',
                '--feed', 'sip', '--asof', day.isoformat(), '--max-pages', '1'])
            calls = 1
            observed = clock()
            for item in selected:
                try:
                    observation = _observation(payload, item, calendar, observed)
                    archive(vault, observation, clock=clock)
                    published.add(item['symbol'])
                except DataError as exc:
                    errors[item['symbol']] = exc.code
        except DataError as exc:
            errors.update((item['symbol'], exc.code) for item in selected)
    if history.read_stable(plan_path)[1] != token:
        _fail('Capture plan changed; retain archived observations and rerun planning.')
    if frozen is None:
        # Publication may span a second. Wait from actual completion, not from
        # the earlier observation or receipt timestamp, before manual prepare.
        finished = clock()
        boundary = finished.replace(microsecond=0) + timedelta(seconds=1)
        reused_after_floor = any(row['price'] is not None and
            history._time(row['price']['available_at']) > finished.replace(microsecond=0)
            for row in initial['items'])
        if published or reused_after_floor:
            remaining = (boundary - finished).total_seconds()
            sleep(remaining)
            if clock() < boundary:
                _fail('Publication completed but the real next whole second has not elapsed; do not prepare yet.')
    result = select(vault, plan, _iso(frozen or clock()), current=clock())
    for row in result['items']:
        row['capture_status'] = 'captured' if row['symbol'] in published else 'not_captured'
        if row['symbol'] in errors:
            row['capture_error'] = errors[row['symbol']]
        elif row['status'] == 'missing' and row['symbol'] in {item['symbol'] for item in missing[max_symbols:]}:
            row['status'] = 'budget_deferred'
    result.update(manual_preflight=frozen is None, finished_at=_iso(clock()), price_batch_calls=calls,
                  max_symbols=max_symbols, requests=client.requests if client is not None else [])
    return result


def parser():
    class SafeParser(argparse.ArgumentParser):
        def error(self, message):
            raise DataError('invalid_input', 'Invalid price-capture arguments; use --help.')
    class SingleCredentialsFile(argparse.Action):
        def __call__(self, parser, namespace, value, option_string=None):
            if getattr(namespace, self.dest, None) is not None:
                raise DataError('invalid_input', 'Specify --credentials-file only once.')
            setattr(namespace, self.dest, value)
    root = SafeParser(description=__doc__)
    root.add_argument('--test', action='store_true')
    sub = root.add_subparsers(dest='command', parser_class=SafeParser)
    for name in ('capture', 'select'):
        command = sub.add_parser(name)
        command.add_argument('--vault', required=True)
        command.add_argument('--plan', required=True)
        command.add_argument('--as-of', required=name == 'select')
        if name == 'capture':
            command.add_argument('--max-symbols', type=int, default=10)
            command.add_argument('--credentials-file', action=SingleCredentialsFile)
            command.add_argument('--max-seconds', type=int, default=60)
    return root


def main(argv=None, client=None):
    env = dict(os.environ if client is None else client.env)
    secrets = tuple(source.get(key, '') for source in (os.environ, env) for key in CREDENTIAL_NAMES)
    secrets += tuple(getattr(client, 'redaction_values', ()))
    try:
        args = parser().parse_args(argv)
        if args.test:
            return run_self_test()
        if args.command == 'select':
            plan, _ = read_plan(args.plan, utc_now())
            result = select(args.vault, plan, args.as_of)
        elif args.command == 'capture':
            if args.credentials_file:
                loaded = load_credentials(args.credentials_file)
                secrets += tuple(loaded.values())
                env = credential_environment(env, loaded)
                if client is not None:
                    from copy import copy
                    client = copy(client)
                    client.env = env
            if client is not None:
                client.redaction_values = tuple(getattr(client, 'redaction_values', ())) + secrets
            client = client or HttpClient(env, max_requests=3, max_seconds=args.max_seconds, redaction_values=secrets)
            result = capture(args.vault, args.plan, max_symbols=args.max_symbols, as_of=args.as_of, client=client)
        else:
            _fail('Choose capture or select; use --help.')
        code = 0 if result['complete'] else 2
    except DataError as exc:
        result = {'market_price_capture': 1, 'complete': False, 'error': {'code': exc.code, 'message': str(exc)}}
        code = 2
    except RuntimeError as exc:
        result = {'market_price_capture': 1, 'complete': False, 'error': {'code': 'publication_failed', 'message': str(exc)}}
        code = 3
    except (ValueError, OSError, TypeError, KeyError, RecursionError):
        result = {'market_price_capture': 1, 'complete': False, 'error': {
            'code': 'invalid_input_or_storage', 'message': 'Price input or archive could not be verified; preserve existing files.'}}
        code = 2
    print(json.dumps(redact(result, env, extra_values=secrets, price_bars=True), ensure_ascii=False, allow_nan=False))
    return code


def run_self_test():
    """Run the embedded real-shaped provider fixtures without network or real vaults."""
    import copy
    from datetime import datetime
    import tempfile
    from types import SimpleNamespace
    import unittest
    from unittest.mock import patch
    from urllib.parse import urlencode

    class PriceCaptureTests(unittest.TestCase):
        def setUp(self):
            self.temp = tempfile.TemporaryDirectory(prefix='.price-capture-test-')
            self.addCleanup(self.temp.cleanup)
            self.vault = Path(self.temp.name).resolve()
            self.plan = self.vault / 'fixture-plan.json'
            self.now = datetime(2024, 5, 1, 15, 30, 0, 250000, tzinfo=_ny())
            self.item = {'symbol': 'AAA', 'class_id': 'common', 'identity_source_url': 'https://example.com/issuer',
                         'identity_available_at': '2024-04-01T12:00:00Z', 'reason': 'Previously collected feed nominee'}
            self.plan.write_text(json.dumps([self.item]), encoding='utf-8')
            self.client = SimpleNamespace(env={'ALPACA_API_KEY': 'fixture-key', 'ALPACA_SECRET_KEY': 'fixture-secret'},
                                          requests=[], redaction_values=(), get_json=self.get_json)
            self.clock_patch = patch.object(prices, 'utc_now', side_effect=lambda: self.now)
            self.clock_patch.start(); self.addCleanup(self.clock_patch.stop)

        def get_json(self, url, params=None, headers=None):
            if url == prices.CALENDAR_URL:
                day, end = parse_date(params['start']), parse_date(params['end'])
                payload = []
                while day <= end:
                    if day.weekday() < 5:
                        payload.append({'date': day.isoformat(), 'open': '09:30', 'close': '16:00'})
                    day += timedelta(days=1)
            else:
                stamp = history._time(params['end']) - timedelta(minutes=1)
                bar = {'t': _iso(stamp), 'o': 30, 'h': 31, 'l': 29, 'c': 30, 'v': 1000, 'n': 100, 'vw': 30}
                payload = {'bars': {symbol: [copy.deepcopy(bar)] for symbol in params['symbols'].split(',')}, 'next_page_token': None}
            raw = evidence.canonical(payload)
            self.client.requests.append({'url': url + '?' + urlencode(params), 'retrieved_at': _iso(self.now),
                'status': 200, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
            return payload

        def sleep(self, seconds):
            self.now += timedelta(seconds=seconds)

        def run_capture(self, **kwargs):
            return capture(self.vault, self.plan, client=self.client, clock=lambda: self.now, sleep=self.sleep, **kwargs)

        def test_manual_capture_emits_exact_price_shape_and_reuses(self):
            result = self.run_capture()
            self.assertTrue(result['complete'])
            self.assertEqual(set(result['items'][0]['price']), {'symbol', 'class_id', 'usd', 'currency', 'adjustment', 'as_of', 'available_at', 'source_url'})
            self.assertLess(history._time(result['items'][0]['price']['available_at']), self.now)
            self.assertEqual(len(self.client.requests), 2)
            self.assertTrue(self.run_capture()['complete'])
            self.assertEqual(len(self.client.requests), 2)

        def test_fixed_cutoff_keeps_late_capture_future_only(self):
            cutoff = _iso(self.now - timedelta(minutes=1))
            result = self.run_capture(as_of=cutoff)
            self.assertEqual(result['as_of'], cutoff)
            self.assertEqual(result['items'][0]['status'], 'future_only')
            self.assertIsNone(result['items'][0]['price'])
            self.assertEqual(self.run_capture(as_of=cutoff)['price_batch_calls'], 0)

        def test_first_save_receipt_follows_publication_not_request(self):
            original = evidence.write
            def delayed(value, *args, **kwargs):
                result = original(value, *args, **kwargs)
                self.now += timedelta(seconds=2)
                return result
            beginning = self.now
            with patch.object(evidence, 'write', side_effect=delayed):
                result = self.run_capture()
            available = history._time(result['items'][0]['price']['available_at'])
            self.assertEqual(available, beginning + timedelta(seconds=2))
            self.assertGreater(self.now, available)

        def test_stale_missing_and_class_mismatch_are_not_prices(self):
            self.run_capture()
            self.now += timedelta(hours=2)
            result = select(self.vault, [self.item], _iso(self.now), current=self.now)
            self.assertEqual(result['items'][0]['status'], 'stale')
            other = dict(self.item, class_id='A')
            self.assertEqual(select(self.vault, [other], _iso(self.now), current=self.now)['items'][0]['status'], 'missing')

        def test_unowned_or_changed_archive_is_preserved(self):
            result = self.run_capture()
            path = Path(result['items'][0]['evidence']['observation_path'])
            path.write_text('changed', encoding='utf-8')
            with self.assertRaises(DataError):
                select(self.vault, [self.item], _iso(self.now), current=self.now)
            self.assertEqual(path.read_text(encoding='utf-8'), 'changed')

    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(PriceCaptureTests))
    print('%d/%d self-tests passed' % (result.testsRun - len(result.failures) - len(result.errors), result.testsRun))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
