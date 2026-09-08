#!/usr/bin/env python3
"""Form and evaluate an immutable monthly momentum diagnostic from saved data.

Offline only. Prints JSON and visible Markdown snippets; --vault preserves
create-only comparison evidence attachments. Never writes daily notes, fetches
data, infers missing returns, rebalances holdings, or places trades.
"""
from __future__ import annotations

import argparse
import calendar
import copy
from datetime import date, datetime, time, timedelta
import hashlib
import json
import math
from pathlib import Path
import re
import os
import stat
import sys
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

import market_screen
import market_evidence as evidence_store
from market_http import DataError, parse_date, parse_time

STRATEGY = {
    'id': 'simple-momentum-v1', 'benchmark': 'SPY', 'maximum_members': 3,
    'weighting': 'equal_weights_over_actual_selected_members',
    'rules': {'min_price': 10, 'min_average_daily_notional': 25000000,
              'require_above_ma50': False, 'require_above_ma200': True,
              'require_positive_relative_return_6m': True,
              'sort_by': 'relative_return_6m', 'limit': 20000},
    'horizons': ['3m', '6m', '12m'],
    'baseline': 'first_regular_session_open_after_formation_note_ny_date_and_publication',
    'endpoint': 'first_regular_session_close_on_or_after_baseline_calendar_month_target',
    'returns': 'sip_split_adjusted_price_gross_v1',
    'costs': 'gross; excludes dividends, fees, spreads and slippage',
}
COHORT = re.compile(r'simple-momentum-v1@(\d{4}-\d{2})\Z')
NOTE = re.compile(r'\d{4}-\d{2}-\d{2}(?:-\d{6})?-(?:stock|market)-research\Z')
DIGEST = re.compile(r'[0-9a-f]{64}\Z')
FORMATION_COLUMNS = ('Exchange', 'Symbol', 'Type', 'Currency', 'Price', 'MA200',
                     'Daily notional', 'Relative 6m', 'Selection')
OBSERVATION_COLUMNS = ('Instrument', 'Baseline price', 'Endpoint price', 'Return', 'Status')
META = ('Cohort', 'State', 'As of', 'Strategy SHA-256', 'Universe', 'Membership date',
        'Universe source', 'Universe SHA-256', 'Screen input SHA-256', 'Calculator SHA-256',
        'Reference session', 'Symbol mapping date', 'Sources', 'History calendar', 'Reason')
OBS_META = ('Cohort', 'Horizon', 'State', 'As of', 'Baseline at', 'Observed at',
            'Return convention', 'Sources', 'Calendar', 'Corporate actions', 'Reason')
MAX_CARD_BYTES = 120 * 1024
MAX_EVIDENCE_BYTES = 32 * 1024 * 1024
EVIDENCE_FOLDER = ('Investments', 'Snapshots', 'Comparisons')
EVIDENCE_LINK = re.compile(r'\[\[Investments/Snapshots/Comparisons/([0-9a-f]{64})\.json\]\]\Z')
COMPACT_META = tuple(key for key in META if key not in ('Sources', 'History calendar')) + (
    'Declared instruments', 'Selected instruments', 'Evidence', 'Evidence SHA-256')
COMPACT_OBS_META = tuple(key for key in OBS_META if key not in ('Sources', 'Calendar', 'Corporate actions')) + (
    'Evidence', 'Evidence SHA-256')


def ny_zone():
    try:
        return ZoneInfo('America/New_York')
    except ZoneInfoNotFoundError:
        fail('system IANA timezone data for America/New_York is required; restore it before comparison research')


def digest(value):
    return market_screen._digest(value)


def fail(message):
    raise ValueError(message)


def parse_json(raw):
    try:
        value = json.loads(raw, object_pairs_hook=market_screen._unique_object,
                           parse_constant=lambda value: fail('JSON non-finite constants are not allowed'))
    except RecursionError:
        fail('comparison JSON nesting exceeds the supported depth')
    # Python versions have different decoder recursion limits. Keep this input
    # boundary deterministic before recursive hashing/serialization happens.
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > 100:
            fail('comparison JSON nesting exceeds the supported depth')
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return value


def number(value, positive=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or (positive and value <= 0)):
        fail('comparison numbers must be finite and prices positive')
    return value


def scalar(value):
    if value is None:
        return '-'
    if isinstance(value, float):
        return repr(value)
    return str(value).replace('&', '&amp;').replace('|', '&#124;').replace('\n', ' ')


def table(columns, rows):
    return '\n'.join(['| ' + ' | '.join(columns) + ' |',
                     '| ' + ' | '.join('---' for _ in columns) + ' |']
                    + ['| ' + ' | '.join(scalar(value) for value in row) + ' |' for row in rows])


def heading_for(identifier, horizon=None):
    return 'Comparison ' + ('checkpoint ' if horizon else 'cohort ') + identifier + ((' ' + horizon) if horizon else '')


def record_link(note_key, heading):
    if not isinstance(note_key, str) or not NOTE.fullmatch(note_key):
        fail('note-key must be the exact canonical daily filename without .md')
    return '[[Investments/' + note_key + '#' + heading + ']]'


def _canonical_evidence(value):
    return evidence_store.canonical(value)


def _evidence_directory(vault, create=False):
    return evidence_store.pinned_directory(vault, EVIDENCE_FOLDER, create)


def _read_evidence_bytes(descriptor, name):
    return evidence_store.read_bytes(descriptor, name, MAX_EVIDENCE_BYTES)


def _evidence_card(raw, sha256, note_key, observation=False):
    if hashlib.sha256(raw).hexdigest() != sha256:
        fail('comparison evidence SHA-256 does not match its immutable attachment')
    value = parse_json(raw.decode('utf-8'))
    kind = 'checkpoint' if observation else 'formation'
    fields = OBS_META if observation else META
    if (not isinstance(value, dict) or set(value) != {
            'market_comparison_evidence', 'note_key', 'kind', 'metadata', 'rows'}
            or type(value['market_comparison_evidence']) is not int or value['market_comparison_evidence'] != 1
            or not isinstance(note_key, str) or not NOTE.fullmatch(note_key)
            or value['note_key'] != note_key or value['kind'] != kind
            or not isinstance(value['metadata'], dict) or set(value['metadata']) != set(fields)
            or not isinstance(value['rows'], list) or raw != _canonical_evidence(value)):
        fail('comparison evidence schema, canonical bytes, kind or exact owner note does not match')
    card = {'metadata': {key: value['metadata'][key] for key in fields}, 'rows': value['rows']}
    if note_key[:10] != parse_time(card['metadata']['As of']).astimezone(ny_zone()).date().isoformat():
        fail('comparison evidence owner date disagrees with its cutoff')
    # An observation needs its original formation for full validation; every
    # indexing/evaluation caller still invokes validate_observation with it.
    return card if observation else validate_formation(card)


def save_evidence(card, vault, note_key, observation=False):
    """Create one content-addressed attachment, or verify an exact identical retry."""
    record_link(note_key, 'comparison evidence')  # Validate the canonical owner.
    if not observation:
        validate_formation(card)
    value = {'market_comparison_evidence': 1, 'note_key': note_key,
             'kind': 'checkpoint' if observation else 'formation',
             'metadata': card['metadata'], 'rows': card['rows']}
    raw = _canonical_evidence(value)
    if len(raw) > MAX_EVIDENCE_BYTES:
        fail('comparison evidence exceeds its attachment byte budget; do not trim the universe after ranking')
    sha256 = hashlib.sha256(raw).hexdigest()
    _evidence_card(raw, sha256, note_key, observation)
    return evidence_store.write(value, vault, EVIDENCE_FOLDER, MAX_EVIDENCE_BYTES)


def load_evidence(vault, link, sha256, note_key, observation=False):
    matched = EVIDENCE_LINK.fullmatch(link) if isinstance(link, str) else None
    if matched is None or not isinstance(sha256, str) or not DIGEST.fullmatch(sha256) or matched[1] != sha256:
        fail('comparison evidence requires its exact safe content-addressed vault link and digest')
    try:
        with _evidence_directory(vault) as (_, descriptor, check):
            raw = _read_evidence_bytes(descriptor, sha256 + '.json')
            card = _evidence_card(raw, sha256, note_key, observation)
            check()
            return card
    except OSError as exc:
        raise ValueError('comparison evidence cannot be safely read: %s' % exc) from exc


def _compact_metadata(card, evidence, observation=False):
    meta = card['metadata']
    fields = COMPACT_OBS_META if observation else COMPACT_META
    retained = {key: meta[key] for key in fields if key in meta}
    if not observation:
        retained.update({'Declared instruments': str(len(card['rows'])),
                         'Selected instruments': ', '.join(row[0] + ':' + row[1] for row in card['rows']
                                                         if row[-1] == 'selected') or '-'})
    retained.update({'Evidence': evidence['link'], 'Evidence SHA-256': evidence['sha256']})
    return retained


def cohort_id(as_of):
    return 'simple-momentum-v1@' + parse_time(as_of).astimezone(ny_zone()).strftime('%Y-%m')


def source_records(envelopes):
    return [{'sha256': digest(value), 'provider': value['provider'], 'operation': value['operation'],
             'resource': value['resource'], 'query': value['query'], 'source': value['source'],
             'requests': value.get('requests', []), 'complete': value['complete']} for value in envelopes]


def source_evidence(value, cutoff, mapping, symbols, require_complete=False, first_day=None, last_day=None,
                    required_days=None):
    """Recheck retained source queries, not merely their claimed return label."""
    records = parse_json(value)
    if not isinstance(records, list):
        fail('comparison source evidence must be a list')
    seen, prices, calendars = set(), [], []
    for row in records:
        if (not isinstance(row, dict) or not DIGEST.fullmatch(row.get('sha256', ''))
                or not isinstance(row.get('query'), dict) or not isinstance(row.get('source'), dict)
                or not isinstance(row.get('requests'), list) or type(row.get('complete')) is not bool
                or row.get('provider') != 'alpaca'):
            fail('comparison source evidence needs digest, query, source and completeness')
        query, source = row['query'], row['source']
        key = (row.get('operation'), digest(query))
        if key in seen:
            fail('comparison source queries must not be duplicated or conflicting')
        seen.add(key)
        if row.get('operation') == 'prices' and row.get('resource') == 'bars':
            if (query.get('feed') != 'sip' or source.get('feed') != 'sip'
                    or query.get('timeframe') != '1Day' or query.get('adjustment') != 'split'
                    or query.get('currency') != 'USD'
                    or source.get('url') != 'https://data.alpaca.markets/v2/stocks/bars'
                    or parse_date(query.get('asof')) != parse_date(mapping)):
                fail('comparison price evidence must preserve SIP/split/USD/1Day and the frozen mapping')
            start, end, requested_end = (parse_time(query.get(key)) for key in ('start', 'end', 'requested_end'))
            names = query.get('symbols', '').split(',')
            if (start > end or end > requested_end or not 1 <= len(names) <= 200
                    or len(set(names)) != len(names) or any(not market_screen.SYMBOL.fullmatch(name) for name in names)):
                fail('comparison price query interval or symbols are invalid')
            prices.append((set(names), start, end, row['complete']))
        elif row.get('operation') == 'sessions' and row.get('resource') == 'calendar':
            start, end = parse_date(query.get('start')), parse_date(query.get('end'))
            if (not row['complete'] or start > end or end < cutoff.astimezone(ny_zone()).date()
                    or (first_day is not None and start > first_day)
                    or source.get('url') != 'https://paper-api.alpaca.markets/v2/calendar'):
                fail('comparison calendar evidence must completely cover formation through cutoff')
            calendars.append((start, end))
        else:
            fail('comparison source must identify saved Alpaca prices or calendar evidence')
    if not prices or len(calendars) != 1:
        fail('comparison needs price evidence and exactly one complete calendar source')
    if require_complete:
        if any(not complete for _, _, _, complete in prices):
            fail('completed comparison needs complete price evidence')
        intervals = {}
        for names, start, end, _ in prices:
            for name in names:
                intervals.setdefault(name, []).append((start, end))
        stamps = [datetime.combine(day, time.min, ny_zone())
                  for day in (required_days if required_days is not None else (first_day, last_day)) if day is not None]
        for symbol in symbols:
            for stamp in stamps:
                if not any(start <= stamp <= end for start, end in intervals.get(symbol, [])):
                    fail('comparison price queries do not cover every fixed instrument and required date')
    return records


def universe_definition(name, membership, source, instruments):
    return {'name': name, 'membership_date': membership, 'source': source,
            'instruments': sorted(({key: item[key] for key in ('exchange', 'symbol', 'security_type', 'currency')}
                                  for item in instruments), key=lambda item: (item['exchange'], item['symbol']))}


def full_daily_bar_available(day, cutoff):
    return datetime.combine(day + timedelta(days=1), time.min, ny_zone()) <= cutoff


def verified_action(action):
    return (isinstance(action, dict) and action.get('status') == 'verified'
            and isinstance(action.get('source'), str) and bool(action['source'].strip())
            and isinstance(action.get('note'), str) and bool(action['note'].strip()))


def unavailable(as_of, reason):
    parse_time(as_of)
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
        fail('an unavailable formation needs a specific reason')
    metadata = dict(zip(META, [cohort_id(as_of), 'unavailable', as_of, digest(STRATEGY),
                             '-', '-', '-', '-', '-', hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                             '-', '-', '[]', '[]', reason]))
    return {'metadata': metadata, 'rows': [], 'members': []}


def form(bundle):
    """Recompute the fixed screen; never accept a manually selected winner list."""
    if not isinstance(bundle, dict):
        fail('comparison formation requires a saved screen input object')
    prepared = copy.deepcopy(bundle)
    universe = prepared['universe']
    identity = universe_definition(universe['name'], universe['membership_date'], universe['source'],
                                   universe['instruments'])
    # Ranking rules may be replaced by the fixed strategy; missing upstream
    # directory/liquidity coverage must never be replaced by a smaller success.
    prepared['universe'] = identity | {key: universe[key] for key in
        ('discovery_complete', 'discovery_coverage', 'discovery_input_sha256') if key in universe}
    prepared['benchmark'], prepared['rules'] = 'SPY', dict(STRATEGY['rules'])
    screen = market_screen.screen(prepared)
    cutoff = parse_time(screen['as_of']).astimezone(ny_zone())
    if (parse_date(screen['universe']['membership_date']) > cutoff.date()
            or parse_date(screen['sources']['symbol_mapping_date']) > cutoff.date()):
        fail('comparison formation cannot use future universe membership or symbol mapping')
    ranked = screen['candidates']
    state = 'unavailable' if not screen['complete'] else 'formed' if ranked else 'empty'
    selected = {(row['exchange'], row['symbol']) for row in ranked[:3]} if state == 'formed' else set()
    rows = []
    for row in ranked + screen['exclusions']:
        metrics = row.get('metrics', {})
        selection = ('selected' if (row['exchange'], row['symbol']) in selected else
                     'not-selected' if row in ranked else 'excluded:' + ','.join(row['reasons']))
        if state == 'unavailable':
            selection = 'unavailable'
        rows.append([row['exchange'], row['symbol'], row['security_type'], row['currency'],
                     metrics.get('price'), metrics.get('ma200'), metrics.get('average_daily_notional'),
                     metrics.get('relative_return_6m'), selection])
    reason = ('Incomplete declared-universe data; no members were selected.' if state == 'unavailable'
              else 'No eligible positive-relative-momentum names.' if state == 'empty'
              else 'Top up to three eligible names; equal weights over the actual selected count.')
    metadata = dict(zip(META, [cohort_id(screen['as_of']), state, screen['as_of'], digest(STRATEGY),
        screen['universe']['name'], screen['universe']['membership_date'], screen['universe']['source'],
        digest(identity), screen['input_sha256'], hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        screen['reference_session'], screen['sources']['symbol_mapping_date'],
        json.dumps(source_records(prepared['prices'] + [prepared['sessions']]), separators=(',', ':')),
        json.dumps([[row['date'], row['open_at'], row['close_at']] for row in prepared['sessions']['data']['sessions']],
                   separators=(',', ':')), reason]))
    result = {'metadata': metadata, 'rows': rows,
              'members': [{'exchange': row[0], 'symbol': row[1]} for row in rows if row[-1] == 'selected']}
    validate_formation(result)
    return result


def validate_formation(card):
    meta, rows = card['metadata'], card['rows']
    if tuple(meta) != META or not COHORT.fullmatch(meta['Cohort']):
        fail('invalid comparison formation metadata')
    if meta['Cohort'] != cohort_id(meta['As of']) or meta['Strategy SHA-256'] != digest(STRATEGY):
        fail('comparison formation month or fixed strategy definition disagrees')
    state = meta['State']
    if state not in ('formed', 'empty', 'unavailable'):
        fail('invalid comparison formation state')
    eligible, selected, seen = [], [], set()
    for row in rows:
        if len(row) != len(FORMATION_COLUMNS):
            fail('invalid comparison formation row')
        exchange, symbol, security, currency, price, ma200, notional, relative, selection = row
        if symbol in seen or not market_screen.SYMBOL.fullmatch(symbol):
            fail('duplicate or invalid comparison instrument')
        seen.add(symbol)
        for value in (price, ma200):
            if value is not None:
                number(value, True)
        if notional is not None and number(notional) < 0:
            fail('comparison daily notional cannot be negative')
        if relative is not None:
            number(relative)
        metrics_known = all(value is not None for value in (price, ma200, notional, relative))
        if metrics_known:
            number(price, True); number(ma200, True); number(notional); number(relative)
        eligible_type = (exchange.upper() in market_screen.US_EXCHANGES
                         and security in ('common_stock', 'adr') and currency == 'USD')
        if state != 'unavailable' and (selection == 'unavailable' or (eligible_type and not metrics_known)):
            fail('missing eligible-instrument measurements require an unavailable formation')
        qualified = (metrics_known and eligible_type
                     and price >= 10 and price > ma200 and notional >= 25000000 and relative > 0)
        if qualified:
            eligible.append((exchange, symbol, relative))
        if selection == 'selected':
            selected.append((exchange, symbol))
        elif selection not in ('not-selected', 'unavailable') and not selection.startswith('excluded:'):
            fail('invalid comparison selection status')
    ranked = sorted(eligible, key=lambda row: (-row[2], row[0], row[1]))
    expected = [(exchange, symbol) for exchange, symbol, _ in ranked[:3]]
    if state == 'formed' and (not expected or selected != expected):
        fail('comparison members do not match the fixed ranking and tie break')
    if state != 'formed' and selected:
        fail('empty or unavailable comparisons must not select members or invent cash')
    if state == 'empty' and eligible:
        fail('empty comparison contains eligible members')
    if state != 'unavailable':
        if not rows or any(not DIGEST.fullmatch(meta[key]) for key in
                           ('Universe SHA-256', 'Screen input SHA-256', 'Calculator SHA-256')):
            fail('completed formation needs its universe, inputs and calculator identity')
        cutoff_day = parse_time(meta['As of']).astimezone(ny_zone()).date()
        if any(parse_date(meta[key]) > cutoff_day for key in
               ('Membership date', 'Reference session', 'Symbol mapping date')):
            fail('comparison membership, reference and mapping must be available by formation')
    if rows:
        retained_universe = universe_definition(meta['Universe'], meta['Membership date'], meta['Universe source'],
            [dict(exchange=row[0], symbol=row[1], security_type=row[2], currency=row[3]) for row in rows])
        if digest(retained_universe) != meta['Universe SHA-256']:
            fail('comparison rows do not reproduce the frozen full universe identity and classifications')
    if meta['Sources'] != '[]' or state != 'unavailable':
        cutoff = parse_time(meta['As of'])
        reference = parse_date(meta['Reference session'])
        if not full_daily_bar_available(reference, cutoff):
            fail('comparison formation reference daily bar is not fully elapsed at cutoff')
        eligible_symbols = [row[1] for row in rows if row[0].upper() in market_screen.US_EXCHANGES
                            and row[2] in ('common_stock', 'adr') and row[3] == 'USD'] + ['SPY']
        records = source_evidence(meta['Sources'], cutoff, meta['Symbol mapping date'], eligible_symbols,
                                  first_day=reference)
        history = parse_json(meta['History calendar'])
        if not isinstance(history, list) or any(not isinstance(row, list) or len(row) != 3 for row in history):
            fail('comparison formation needs its retained calendar session triples')
        calendar_source = next(row for row in records if row['operation'] == 'sessions')
        calendar_envelope = dict(calendar_source, market_data=1, data={'sessions': [
            dict(zip(('date', 'open_at', 'close_at'), row)) for row in history]})
        expected_reference, _, required_days, _ = market_screen._calendar(calendar_envelope, cutoff)
        if expected_reference != reference:
            fail('comparison reference must be the latest fully elapsed calendar session')
        source_evidence(meta['Sources'], cutoff, meta['Symbol mapping date'], eligible_symbols,
                        require_complete=state != 'unavailable', first_day=required_days[0],
                        required_days=required_days)
    card['members'] = [{'exchange': exchange, 'symbol': symbol} for exchange, symbol in selected]
    return card


def formation_markdown(card, note_key, vault=None):
    validate_formation(card)
    meta = card['metadata']
    heading = heading_for(meta['Cohort'])
    evidence = save_evidence(card, vault, note_key) if vault is not None else None
    visible = _compact_metadata(card, evidence) if evidence else meta
    rows = [row for row in card['rows'] if row[-1] == 'selected'] if evidence else card['rows']
    detail = '#### ' + heading + '\n\n' + table(('Field', 'Value'), visible.items())
    if rows:
        detail += '\n\n' + table(FORMATION_COLUMNS, rows)
    detail += ('\n\nFixed monthly strategy diagnostic, not a purchase recommendation. '
               'Coverage is only the declared universe. Daily notional includes extended hours. '
               'Empty/unavailable cohorts have no simulated cash return.\n')
    if evidence:
        retained = []
        if card['rows']:
            retained.append('%d declared instrument rows with their recorded measurements and dispositions' % len(card['rows']))
        if parse_json(meta['Sources']):
            retained.append('source queries')
        if parse_json(meta['History calendar']):
            retained.append('history calendar boundaries')
        detail += '\nThe immutable evidence attachment retains the strategy, cutoff and formation reason. '
        if retained:
            detail += 'It also preserves ' + ', '.join(retained) + '. '
        else:
            detail += 'No instrument rows, source queries or history calendar were available for this formation. '
        detail += 'Its digest and exact owner note are verified whenever this record is indexed.\n'
    if len(detail.encode('utf-8')) > MAX_CARD_BYTES:
        fail('comparison evidence exceeds the note budget; record formation unavailable, do not trim the universe after ranking')
    result = {'detail_markdown': detail, 'journal_markdown': '#### Comparison cohorts\n\n' + table(
        ('Cohort', 'State', 'Record'), [(meta['Cohort'], meta['State'], record_link(note_key, heading))]) + '\n'}
    if evidence:
        result['evidence_attachment'] = evidence
    return result


def _unescape(value):
    return value.replace('&#124;', '|').replace('&amp;', '&')


def read_card(text, section, observation=False, *, vault=None, note_key=None):
    """Read only helper-shaped visible tables in one uniquely named detail card."""
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line == '#### ' + section]
    if len(starts) != 1:
        fail('comparison detail card must have one exact H4 heading')
    start = starts[0] + 1
    stop = next((i for i in range(start, len(lines)) if re.match(r'^#{1,4} ', lines[i])), len(lines))
    if len('\n'.join(lines[start:stop]).encode('utf-8')) > MAX_CARD_BYTES:
        fail('comparison detail card exceeds its note budget')
    tables, current = [], []
    for line in lines[start:stop] + ['']:
        if line.startswith('| ') and line.endswith(' |'):
            current.append([_unescape(cell.strip()) for cell in line[1:-1].split('|')])
        elif current:
            tables.append(current); current = []
    fields, columns = (OBS_META, OBSERVATION_COLUMNS) if observation else (META, FORMATION_COLUMNS)
    compact_fields = COMPACT_OBS_META if observation else COMPACT_META
    if not 1 <= len(tables) <= 2 or tables[0][:2] != [['Field', 'Value'], ['---', '---']]:
        fail('comparison detail requires its exact metadata table')
    actual_fields = tuple(row[0] for row in tables[0][2:])
    attached = actual_fields == compact_fields
    if any(len(row) != 2 for row in tables[0][2:]) or actual_fields not in (fields, compact_fields):
        fail('comparison metadata fields are missing, duplicated or reordered')
    metadata, rows = dict(tables[0][2:]), []
    if len(tables) == 2:
        if tables[1][:2] != [list(columns), ['---'] * len(columns)]:
            fail('comparison detail requires its exact measurement table')
        for row in tables[1][2:]:
            if len(row) != len(columns):
                fail('comparison measurement row has the wrong width')
            numeric_positions = (1, 2, 3) if observation else (4, 5, 6, 7)
            for index in numeric_positions:
                row[index] = None if row[index] == '-' else number(float(row[index]))
            rows.append(row)
    card = {'metadata': metadata, 'rows': rows}
    if attached:
        card = load_evidence(vault, metadata['Evidence'], metadata['Evidence SHA-256'], note_key, observation)
        expected = _compact_metadata(card, {'link': metadata['Evidence'], 'sha256': metadata['Evidence SHA-256']}, observation)
        # Apply the same visible escaping/decoding as the table renderer: a
        # metadata source may contain an ampersand, pipe, or line break.
        expected = {key: _unescape(scalar(value)) for key, value in expected.items()}
        visible_rows = card['rows'] if observation else [row for row in card['rows'] if row[-1] == 'selected']
        if metadata != expected or rows != visible_rows:
            fail('comparison visible summary or measurements disagree with its verified evidence attachment')
        return card
    return card if observation else validate_formation(card)


def month_target(day, months):
    year, month = divmod(day.year * 12 + day.month - 1 + months, 12)
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def calendar_events(envelope, formation_day, cutoff):
    market_screen._envelope(envelope, 'sessions', 'calendar')
    if (not envelope['complete'] or parse_date(envelope['query']['start']) > formation_day
            or parse_date(envelope['query']['end']) < cutoff.astimezone(ny_zone()).date()):
        fail('comparison needs a complete calendar from formation through the current cutoff')
    events, seen = [], set()
    for row in envelope['data'].get('sessions', []):
        day, opened, closed = parse_date(row['date']), parse_time(row['open_at']), parse_time(row['close_at'])
        if (day in seen or opened >= closed or opened.astimezone(ny_zone()).date() != day
                or closed.astimezone(ny_zone()).date() != day
                or not parse_date(envelope['query']['start']) <= day <= parse_date(envelope['query']['end'])):
            fail('comparison calendar contains inconsistent sessions')
        seen.add(day); events.append((day, opened, closed))
    return sorted(events), seen


def evaluate(card, published_at, bundle, horizon):
    validate_formation(card)
    if horizon not in STRATEGY['horizons'] or card['metadata']['State'] != 'formed':
        fail('only formed cohorts have 3m/6m/12m return observations')
    if (not isinstance(bundle, dict) or type(bundle.get('market_comparison_input')) is not int
            or bundle['market_comparison_input'] != 1):
        fail('use market_comparison_input version 1')
    cutoff, published = parse_time(bundle['as_of']), parse_time(published_at)
    formation_day = parse_time(card['metadata']['As of']).astimezone(ny_zone()).date()
    events, dates = calendar_events(bundle['sessions'], formation_day, cutoff)
    following = [event for event in events if event[0] > formation_day]
    if not following or following[0][1] > cutoff:
        return {'state': 'pending', 'reason': 'The first post-publication regular opening has not been observed.'}
    baseline = following[0]
    if baseline[1] < published:
        fail('fixed baseline opening precedes known publication; do not substitute a later opening')
    target = month_target(baseline[0], int(horizon[:-1]))
    endpoints = [event for event in events if event[0] >= target]
    if not endpoints or endpoints[0][2] > cutoff:
        return {'state': 'pending', 'reason': 'The first target-date regular close has not completed.',
                'target_date': target.isoformat()}
    endpoint = endpoints[0]
    bars, requested, complete, warnings, sources, ignored, mapping = market_screen._prices(bundle['prices'], cutoff, dates)
    if mapping.isoformat() != card['metadata']['Symbol mapping date']:
        fail('comparison prices must preserve the formation symbol-mapping date')
    symbols = [row['symbol'] for row in card['members']] + ['SPY']
    actions = bundle.get('corporate_actions', {})
    if not isinstance(actions, dict):
        fail('corporate_actions must retain a verification record for each fixed instrument')
    rows, failed = [], not complete
    for symbol in symbols:
        first, last = bars.get(symbol, {}).get(baseline[0]), bars.get(symbol, {}).get(endpoint[0])
        action = actions.get(symbol)
        verified = verified_action(action)
        usable = complete and symbol in requested and first is not None and last is not None and verified
        value = last['c'] / first['o'] - 1 if usable else None
        rows.append([symbol, first['o'] if first else None, last['c'] if last else None,
                     value, 'observed' if usable else 'unavailable'])
        failed = failed or not usable
    state = 'unavailable' if failed else 'observed'
    metadata = dict(zip(OBS_META, [card['metadata']['Cohort'], horizon, state, bundle['as_of'],
        baseline[1].isoformat(), endpoint[2].isoformat(), STRATEGY['returns'],
        json.dumps(source_records(bundle['prices'] + [bundle['sessions']]), separators=(',', ':')),
        json.dumps({'dates': [event[0].isoformat() for event in events],
                    'baseline': [baseline[0].isoformat(), baseline[1].isoformat(), baseline[2].isoformat()],
                    'endpoint': [endpoint[0].isoformat(), endpoint[1].isoformat(), endpoint[2].isoformat()]},
                   separators=(',', ':')),
        json.dumps(actions, separators=(',', ':')),
        'Missing member, benchmark, calendar-price availability or corporate-action evidence; no partial basket return.'
        if failed else STRATEGY['costs']]))
    result = {'metadata': metadata, 'rows': rows}
    return validate_observation(result, card)


def validate_observation(observation, cohort):
    validate_formation(cohort)
    if cohort['metadata']['State'] != 'formed':
        fail('only formed cohorts have return observations')
    meta, rows = observation['metadata'], observation['rows']
    if tuple(meta) != OBS_META or meta['Cohort'] != cohort['metadata']['Cohort']:
        fail('invalid comparison observation metadata or cohort')
    if meta['Horizon'] not in STRATEGY['horizons'] or meta['Return convention'] != STRATEGY['returns']:
        fail('comparison observation changed the frozen horizon or return convention')
    if meta['State'] not in ('observed', 'unavailable'):
        fail('invalid comparison observation state')
    expected = [row['symbol'] for row in cohort['members']] + ['SPY']
    if [row[0] for row in rows] != expected:
        fail('comparison observation must retain every original member and SPY in order')
    actions = parse_json(meta['Corporate actions'])
    if not isinstance(actions, dict):
        fail('comparison observations need corporate-action evidence')
    for symbol, first, last, value, state in rows:
        for price in (first, last):
            if price is not None:
                number(price, True)
        if state not in ('observed', 'unavailable'):
            fail('invalid comparison member observation state')
        if state == 'observed':
            if not verified_action(actions.get(symbol)):
                fail('observed comparison member needs verified corporate-action and identity evidence')
            number(first, True); number(last, True); number(value)
            if not math.isclose(last / first - 1, value, rel_tol=1e-12, abs_tol=1e-12):
                fail('comparison member return does not recompute from retained prices')
        elif value is not None:
            fail('an unavailable member cannot have a fabricated return')
    complete = all(row[-1] == 'observed' for row in rows)
    if (meta['State'] == 'observed') != complete:
        fail('comparison basket state must reflect every original member and benchmark')
    first, last, cutoff = (parse_time(meta[key]) for key in ('Baseline at', 'Observed at', 'As of'))
    formation_day = parse_time(cohort['metadata']['As of']).astimezone(ny_zone()).date()
    if (first.astimezone(ny_zone()).date() <= formation_day or first > last or last > cutoff
            or last.astimezone(ny_zone()).date() < month_target(first.astimezone(ny_zone()).date(), int(meta['Horizon'][:-1]))):
        fail('comparison event timestamps violate formation, horizon or cutoff')
    if not full_daily_bar_available(last.astimezone(ny_zone()).date(), cutoff):
        fail('comparison endpoint daily bar is not fully elapsed at cutoff')
    records = source_evidence(meta['Sources'], cutoff, cohort['metadata']['Symbol mapping date'], expected,
                              require_complete=complete, first_day=first.astimezone(ny_zone()).date(),
                              last_day=last.astimezone(ny_zone()).date())
    evidence = parse_json(meta['Calendar'])
    dates = [parse_date(value) for value in evidence['dates']]
    if dates != sorted(set(dates)):
        fail('comparison calendar dates must be unique and ordered')
    calendar_query = next(row['query'] for row in records if row['operation'] == 'sessions')
    if (parse_date(calendar_query['start']) > formation_day
            or any(not parse_date(calendar_query['start']) <= day <= parse_date(calendar_query['end']) for day in dates)):
        fail('retained comparison calendar dates exceed the source query or omit formation coverage')
    post_formation = [day for day in dates if day > formation_day]
    target = month_target(first.astimezone(ny_zone()).date(), int(meta['Horizon'][:-1]))
    post_target = [day for day in dates if day >= target]
    if (not post_formation or first.astimezone(ny_zone()).date() != post_formation[0]
            or not post_target or last.astimezone(ny_zone()).date() != post_target[0]):
        fail('comparison must use the first eligible calendar opening and closing dates')
    for key, instant, boundary in (('baseline', first, 1), ('endpoint', last, 2)):
        day, opened, closed = evidence[key]
        opened, closed = parse_time(opened), parse_time(closed)
        if (parse_date(day) != instant.astimezone(ny_zone()).date() or opened >= closed
                or opened.astimezone(ny_zone()).date() != parse_date(day)
                or closed.astimezone(ny_zone()).date() != parse_date(day)
                or instant != (opened if boundary == 1 else closed)):
            fail('comparison event markers disagree with retained calendar evidence')
    observation.update(state=meta['State'], cohort=meta['Cohort'], horizon=meta['Horizon'],
                       baseline_at=meta['Baseline at'], observed_at=meta['Observed at'],
                       return_value=math.fsum(row[3] for row in rows[:-1]) / len(rows[:-1]) if complete else None,
                       benchmark_return=rows[-1][3] if complete else None,
                       member_count=len(rows) - 1)
    return observation


def observation_markdown(observation, note_key, replaces='-', vault=None):
    if observation.get('state') == 'pending':
        return {'detail_markdown': None, 'journal_markdown': None}
    meta = observation['metadata']
    heading = heading_for(meta['Cohort'], meta['Horizon'])
    evidence = save_evidence(observation, vault, note_key, observation=True) if vault is not None else None
    visible = _compact_metadata(observation, evidence, observation=True) if evidence else meta
    detail = ('#### ' + heading + '\n\n' + table(('Field', 'Value'), visible.items())
              + '\n\n' + table(OBSERVATION_COLUMNS, observation['rows'])
              + '\n\nMember return = endpoint split-adjusted daily close / baseline split-adjusted '
                'daily open - 1. Cohort return is the arithmetic mean across the original selected '
                'members, without interim rebalancing. Event timestamps are verified calendar session '
                'markers, not auction fills. No dividend, fee, spread or slippage return is invented.\n')
    if len(detail.encode('utf-8')) > MAX_CARD_BYTES:
        fail('comparison observation exceeds the note budget; retain the task due and explain the limitation')
    journal = '#### Comparison checkpoints\n\n' + table(
        ('Cohort', 'Horizon', 'State', 'Baseline at', 'Observed at', 'Return', 'Benchmark return', 'Record', 'Replaces'),
        [(meta['Cohort'], meta['Horizon'], meta['State'], meta['Baseline at'], meta['Observed at'],
          observation['return_value'], observation['benchmark_return'], record_link(note_key, heading), replaces)]) + '\n'
    result = {'detail_markdown': detail, 'journal_markdown': journal}
    if evidence:
        result['evidence_attachment'] = evidence
    return result


def load_json(path):
    path = Path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > market_screen.MAX_INPUT_BYTES:
        fail('input must be a bounded regular JSON file')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    with os.fdopen(os.open(path, flags), 'rb') as handle:
        opened = os.fstat(handle.fileno())
        if not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            fail('input changed identity while opening')
        raw = handle.read(market_screen.MAX_INPUT_BYTES + 1)
    if len(raw) > market_screen.MAX_INPUT_BYTES:
        fail('input exceeds the 128 MiB limit')
    return parse_json(raw.decode('utf-8'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', action='store_true', help='run bounded offline invariant fixtures')
    sub = parser.add_subparsers(dest='command')
    make = sub.add_parser('form'); make.add_argument('--input', required=True)
    missing = sub.add_parser('unavailable')
    missing.add_argument('--as-of', required=True); missing.add_argument('--reason', required=True)
    observe = sub.add_parser('evaluate')
    observe.add_argument('--cohort-note', required=True); observe.add_argument('--cohort', required=True)
    observe.add_argument('--input', required=True); observe.add_argument('--horizon', choices=STRATEGY['horizons'], required=True)
    observe.add_argument('--replaces', default='-')
    for command in (make, missing, observe):
        command.add_argument('--note-key', required=True)
        command.add_argument('--vault', help='selected vault; preserve immutable evidence and emit compact cards')
    args = parser.parse_args(argv)
    try:
        if args.test:
            return run_self_test()
        if args.command is None:
            fail('provide form, unavailable or evaluate; use --help for the input contract')
        if args.command == 'form':
            result = form(load_json(args.input)); result.update(formation_markdown(result, args.note_key, args.vault))
        elif args.command == 'unavailable':
            result = unavailable(args.as_of, args.reason); result.update(formation_markdown(result, args.note_key, args.vault))
        else:
            import market_notes
            data, _ = market_notes.read_stable(args.cohort_note)
            note = market_notes.lint_bytes(data)
            card = read_card(data.decode('utf-8'), heading_for(args.cohort), vault=args.vault,
                             note_key=Path(args.cohort_note).stem)
            result = evaluate(card, note['metadata']['generated_at'], load_json(args.input), args.horizon)
            result.update(observation_markdown(result, args.note_key, args.replaces, args.vault))
        print(json.dumps({'market_comparison': 1, **result}, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValueError, KeyError, TypeError, OSError, RecursionError, DataError, evidence_store.PublicationError) as exc:
        print(json.dumps({'market_comparison': 1, 'error': str(exc)}))
        return 2


def run_self_test():
    """Small package-portable invariants; full temporary-vault tests live in tests/."""
    import unittest

    class ComparisonSelfTests(unittest.TestCase):
        def setUp(self):
            self.card = unavailable('2024-05-01T11:30:00-04:00', 'Synthetic fixture')
            self.card['metadata'].update({
                'State': 'formed', 'Universe': 'Synthetic declared universe', 'Membership date': '2024-05-01',
                'Universe source': 'https://example.invalid/universe', 'Universe SHA-256': 'a' * 64,
                'Screen input SHA-256': 'b' * 64, 'Reference session': '2024-04-30',
                'Symbol mapping date': '2024-05-01', 'Sources': json.dumps([
                    {'sha256': 'c' * 64, 'provider': 'alpaca', 'operation': 'prices', 'resource': 'bars',
                     'query': {'feed': 'sip', 'timeframe': '1Day', 'adjustment': 'split', 'currency': 'USD',
                               'asof': '2024-05-01', 'symbols': 'AAA,BBB,SPY', 'start': '2023-01-01T05:00:00Z',
                               'end': '2024-05-01T03:59:59Z', 'requested_end': '2024-05-01T03:59:59Z'},
                     'source': {'url': 'https://data.alpaca.markets/v2/stocks/bars', 'feed': 'sip'},
                     'complete': True, 'requests': []},
                    {'sha256': 'd' * 64, 'provider': 'alpaca', 'operation': 'sessions', 'resource': 'calendar',
                     'query': {'start': '2023-01-01', 'end': '2024-05-01'},
                     'source': {'url': 'https://paper-api.alpaca.markets/v2/calendar'}, 'complete': True, 'requests': []}])})
            self.card['rows'] = [['NASDAQ', 'AAA', 'common_stock', 'USD', 100, 80, 30000000, 0.2, 'selected'],
                                 ['NASDAQ', 'BBB', 'common_stock', 'USD', 100, 80, 30000000, 0.1, 'selected']]
            self.card['metadata']['Universe SHA-256'] = digest(universe_definition(
                self.card['metadata']['Universe'], '2024-05-01', self.card['metadata']['Universe source'],
                [dict(exchange=row[0], symbol=row[1], security_type=row[2], currency=row[3]) for row in self.card['rows']]))
            day, history = date(2023, 1, 1), []
            while day <= date(2024, 5, 1):
                if day.weekday() < 5:  # Deliberately synthetic calendar, not an exchange-holiday assertion.
                    history.append([day.isoformat(), datetime.combine(day, time(9, 30), ny_zone()).isoformat(),
                                    datetime.combine(day, time(16), ny_zone()).isoformat()])
                day += timedelta(days=1)
            self.card['metadata']['History calendar'] = json.dumps(history)
            validate_formation(self.card)

        def observation(self):
            first, last = '2024-05-02T09:30:00-04:00', '2024-08-02T16:00:00-04:00'
            evidence = {'dates': ['2024-05-01', '2024-05-02', '2024-08-02'],
                        'baseline': ['2024-05-02', first, '2024-05-02T16:00:00-04:00'],
                        'endpoint': ['2024-08-02', '2024-08-02T09:30:00-04:00', last]}
            actions = {symbol: {'status': 'verified', 'source': 'https://example.invalid/actions',
                                'note': 'Synthetic unchanged identity.'} for symbol in ('AAA', 'BBB', 'SPY')}
            sources = parse_json(self.card['metadata']['Sources'])
            sources[0]['query'].update(end='2024-08-03T03:59:59Z', requested_end='2024-08-03T03:59:59Z')
            sources[1]['query']['end'] = '2024-08-03'
            return {'metadata': dict(zip(OBS_META, [self.card['metadata']['Cohort'], '3m', 'observed',
                '2024-08-03T11:30:00-04:00', first, last, STRATEGY['returns'], json.dumps(sources),
                json.dumps(evidence), json.dumps(actions), STRATEGY['costs']])),
                'rows': [['AAA', 100, 130, 0.3, 'observed'], ['BBB', 100, 90, -0.1, 'observed'],
                         ['SPY', 100, 105, 0.05, 'observed']]}

        def test_visible_card_round_trip(self):
            rendered = formation_markdown(self.card, '2024-05-01-market-research')
            self.assertEqual(read_card(rendered['detail_markdown'], heading_for(self.card['metadata']['Cohort'])), self.card)

        def test_fixed_ranking_rejects_reordered_winners(self):
            self.card['rows'].reverse()
            with self.assertRaisesRegex(ValueError, 'fixed ranking'):
                validate_formation(self.card)

        def test_actual_two_members_have_no_third_cash_slot(self):
            observed = validate_observation(self.observation(), self.card)
            self.assertAlmostEqual(observed['return_value'], 0.1)
            self.assertAlmostEqual(observed['benchmark_return'], 0.05)
            self.assertEqual(observed['member_count'], 2)

        def test_missing_member_never_renormalizes_survivors(self):
            observed = self.observation()
            observed['rows'].pop(1)
            with self.assertRaisesRegex(ValueError, 'every original member'):
                validate_observation(observed, self.card)

        def test_unavailable_never_has_cash_return(self):
            card = unavailable('2024-05-01T11:30:00-04:00', 'Synthetic absent coverage')
            with self.assertRaisesRegex(ValueError, 'only formed'):
                validate_observation(self.observation(), card)

        def test_invalid_nested_json_and_unverified_actions_are_rejected(self):
            with self.assertRaisesRegex(ValueError, 'nesting'):
                parse_json('[' * 2000 + '0' + ']' * 2000)
            observed = self.observation()
            observed['metadata']['Corporate actions'] = '{}'
            with self.assertRaisesRegex(ValueError, 'corporate-action'):
                validate_observation(observed, self.card)

    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(ComparisonSelfTests))
    print('%d/%d self-test cases pass' % (result.testsRun - len(result.failures) - len(result.errors), result.testsRun))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
