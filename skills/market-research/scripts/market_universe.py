#!/usr/bin/env python3
"""Offline directory classification, broad price filtering and liquidity checks.

Consumes original market_data envelopes. No network, credentials or vault writes.
Missing evidence stays unavailable; passing discovery is never a buy instruction.
"""
from __future__ import annotations

import argparse
from datetime import datetime, time, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from market_http import DataError, parse_date, parse_time
from market_screen import MAX_INPUT_BYTES, _digest, _envelope, _iso, _number, _prices, _symbol, _unique_object, screen

def ny():
    return ZoneInfo('America/New_York')
EXCHANGES = {'N': 'NYSE', 'A': 'NYSE AMERICAN', 'P': 'NYSE ARCA', 'Z': 'CBOE BZX'}
EXCLUDED = re.compile(r'\b(?:preferred|preference|warrants?|rights?|units?|bonds?|notes?|debentures?|when[ -]issued|beneficial interest|fund|ETF|ETN)\b', re.I)
COMMON = re.compile(r'\b(?:common (?:stock|shares)|ordinary shares)\b', re.I)
ADR = re.compile(r'\bAmerican deposit[ao]ry (?:shares|receipts)\b', re.I)


def fail(message):
    raise DataError('invalid_input', message)


def _batches(instruments, as_of, size=100):
    if type(size) is not int or not 1 <= size <= 200:
        fail('Batch size must be 1–200.')
    day = parse_time(as_of).astimezone(ny()).date().isoformat()
    def key(row):
        identity = row['exchange'] + ':' + row['symbol']
        return hashlib.sha256(('directory-traversal-v1|' + day + '|' + identity).encode()).hexdigest(), identity
    symbols = [row['symbol'] for row in sorted(instruments, key=key)]
    return [symbols[start:start + size] for start in range(0, len(symbols), size)]


def _directory(envelope):
    if (not isinstance(envelope, dict) or envelope.get('market_data') != 1
            or envelope.get('operation') != 'symbols' or envelope.get('provider') != 'nasdaq'
            or envelope.get('resource') != 'symbols' or type(envelope.get('complete')) is not bool
            or not isinstance(envelope.get('query'), dict) or not isinstance(envelope.get('data'), dict)):
        fail('Use the original Nasdaq symbols helper envelope.')
    if envelope['query'].get('symbols') or envelope['query'].get('scope') != 'current_directory':
        fail('Broad discovery requires unfiltered current directories, not a selected ticker list.')
    if not isinstance(envelope['data'].get('securities'), list):
        fail('Directory securities are missing.')
    files = envelope['data'].get('files')
    if not isinstance(files, list) or {r.get('file') for r in files if isinstance(r, dict)} != {'nasdaqlisted.txt', 'otherlisted.txt'}:
        fail('Both Nasdaq and other-exchange directory snapshots are required.')
    return envelope


def universe(envelope, as_of, batch_size=100):
    """Classify the full current directory; hash traversal rotates by cutoff date."""
    cutoff = parse_time(as_of)
    envelope = _directory(envelope)
    observations = [parse_time(row.get('retrieved_at', row.get('observed_at')))
                    for row in envelope.get('requests', []) if isinstance(row, dict)
                    and row.get('retrieved_at', row.get('observed_at'))]
    footer_dates = [datetime.fromisoformat(row['creation_time_local']).date()
                    for row in envelope['data']['files'] if row.get('creation_time_local')]
    observed_date = max(stamp.astimezone(ny()).date() for stamp in observations) if observations else None
    membership_date = observed_date or (max(footer_dates) if footer_dates else None)
    if membership_date is None:
        fail('Directory observation or creation date is missing; do not invent a membership date.')
    date_available = bool(observed_date and observed_date <= cutoff.astimezone(ny()).date()
                          and all(day <= cutoff.astimezone(ny()).date() for day in footer_dates))
    instruments, exclusions, seen = [], [], set()
    for row in envelope['data']['securities']:
        if not isinstance(row, dict) or not isinstance(row.get('source_fields'), dict):
            fail('Invalid directory row.')
        symbol, name = row.get('symbol'), row.get('security_name')
        if not isinstance(symbol, str) or not isinstance(name, str) or not name:
            fail('Directory identity is missing.')
        if symbol in seen:
            fail('Conflicting or duplicate directory symbol; resolve identity before screening.')
        seen.add(symbol)
        fields, directory = row['source_fields'], row.get('directory')
        if directory not in ('nasdaqlisted.txt', 'otherlisted.txt'):
            fail('Unknown security directory.')
        symbol_field = 'Symbol' if directory == 'nasdaqlisted.txt' else 'ACT Symbol'
        if (fields.get(symbol_field) != symbol or fields.get('Security Name') != name
                or type(row.get('etf')) is not bool or type(row.get('test_issue')) is not bool
                or fields.get('ETF') != ('Y' if row['etf'] else 'N')
                or fields.get('Test Issue') != ('Y' if row['test_issue'] else 'N')):
            fail('Directory normalized values disagree with their original source fields.')
        exchange = 'NASDAQ' if directory == 'nasdaqlisted.txt' else EXCHANGES.get(fields.get('Exchange'))
        reason = None
        if row['etf'] or row['test_issue']:
            reason = 'etf_or_test_issue'
        elif not exchange:
            reason = 'unresolved_exchange'
        elif not re.fullmatch(r'[A-Z][A-Z0-9./-]{0,19}', symbol):
            reason = 'provider_symbol_mapping_unresolved'
        elif EXCLUDED.search(name):
            reason = 'excluded_or_unresolved_instrument_type'
        kind = 'adr' if ADR.search(name) else 'common_stock' if COMMON.search(name) else None
        if not reason and not kind:
            reason = 'common_or_adr_classification_unresolved'
        if reason:
            exclusions.append({'symbol': symbol, 'security_name': name, 'reason': reason, 'directory': directory})
        else:
            instruments.append({'symbol': symbol, 'exchange': exchange, 'security_type': kind, 'currency': 'USD',
                                'security_name': name, 'classification_basis': 'explicit directory security-name wording and ETF/test flags',
                                'directory': directory})
    instruments.sort(key=lambda row: (row['exchange'], row['symbol']))
    result = {'market_universe': 1, 'operation': 'universe', 'complete': envelope['complete'] and date_available,
              'as_of': _iso(cutoff), 'batch_size': batch_size,
              'universe': {'name': 'current-us-directory-v1', 'membership_date': membership_date.isoformat(),
                           'source': 'Current Nasdaq nasdaqlisted.txt and otherlisted.txt; conservative name classification; not historical membership or liquidity proof.',
                           'instruments': instruments},
              'coverage': {'directory_records': len(seen), 'classified': len(instruments), 'excluded_or_unresolved': len(exclusions)},
              'exclusions': exclusions, 'source_envelope': envelope, 'input_sha256': _digest(envelope),
              'directory_observed_at': [_iso(stamp) for stamp in observations], 'directory_date_available': date_available,
              'order': 'SHA256(directory-traversal-v1|New-York-cutoff-date|exchange:symbol), ascending; not market-cap or alphabetic ranking',
              'warnings': list(envelope.get('warnings', [])) + ['Name classification is conservative; resolve ambiguities separately.',
                  'A budget-limited hash prefix is an incomplete daily sample, not a representative market-wide screen.',
                  'Directory creation timestamps lack a timezone; current snapshots do not establish historical availability.']}
    if not date_available:
        result['warnings'].append('Directory observation is missing or is from a later New York date than the cutoff; historical membership is unavailable.')
    elif any(stamp > cutoff for stamp in observations):
        result['warnings'].append('Directory was observed after the cutoff on the same New York date; this is a current discovery universe, not timestamp-level historical membership.')
    result['batches'] = _batches(instruments, result['as_of'], batch_size)
    return result


def _plan(plan, as_of):
    if (not isinstance(plan, dict) or type(plan.get('market_universe')) is not int or plan['market_universe'] != 1
            or not isinstance(plan.get('universe'), dict) or type(plan.get('complete')) is not bool):
        fail('Use a market_universe result with its complete declared roster.')
    if parse_time(plan.get('as_of')) != parse_time(as_of):
        fail('Universe and calculation cutoffs disagree.')
    instruments = plan['universe'].get('instruments')
    if not isinstance(instruments, list):
        fail('Declared instruments are missing.')
    seen = set()
    for row in instruments:
        if not isinstance(row, dict):
            fail('Invalid declared instrument.')
        symbol = _symbol(row.get('symbol'))
        if symbol in seen:
            fail('Duplicate declared symbol.')
        seen.add(symbol)
    return instruments


def _sessions(envelope, cutoff, count):
    envelope = _envelope(envelope, 'sessions', 'calendar')
    if not envelope['complete']:
        raise DataError('incomplete_data', 'A complete calendar is required.')
    start, end = parse_date(envelope['query'].get('start')), parse_date(envelope['query'].get('end'))
    if start > end or end < cutoff.astimezone(ny()).date():
        fail('Calendar must cover its declared interval through the cutoff date.')
    rows = envelope['data'].get('sessions')
    if not isinstance(rows, list):
        fail('Calendar sessions are missing.')
    completed, all_dates = [], set()
    for row in rows:
        if not isinstance(row, dict):
            fail('Invalid calendar session.')
        day = parse_date(row.get('date'))
        opened, closed = parse_time(row.get('open_at')), parse_time(row.get('close_at'))
        if (day in all_dates or not start <= day <= end or opened >= closed
                or opened.astimezone(ny()).date() != day or closed.astimezone(ny()).date() != day
                or opened.second or opened.microsecond or closed.second or closed.microsecond):
            fail('Duplicate, invalid or inconsistent calendar session.')
        all_dates.add(day)
        midnight = datetime.combine(day + timedelta(days=1), time.min, ny())
        if closed <= cutoff and midnight <= cutoff:
            completed.append((day, opened, closed))
    completed.sort()
    if len(completed) < count:
        raise DataError('incomplete_data', 'Not enough completed calendar sessions; do not shorten the lookback.')
    return completed[-count:], all_dates


def _daily(prices, calendar, as_of):
    cutoff = parse_time(as_of)
    sessions, dates = _sessions(calendar, cutoff, 20)
    if not prices:
        return sessions, {}, set(), False, [], []
    bars, requested, complete, warnings, provenance, _, mapping = _prices(prices, cutoff, dates)
    if mapping != cutoff.astimezone(ny()).date():
        fail('Daily price symbol mapping must equal the declared universe cutoff date.')
    for envelope in prices:
        if parse_time(envelope['query']['requested_end']) > cutoff:
            fail('Daily price requested end is later than the frozen cutoff.')
    return sessions, bars, requested, complete, warnings, provenance


def prefilter(plan, prices, calendar, as_of, min_price=10, min_average_daily_notional=25000000):
    """Retain every 20-session daily-proxy pass, without a top-N gate."""
    instruments = _plan(plan, as_of)
    _number(min_price)
    _number(min_average_daily_notional)
    sessions, bars, requested, complete, warnings, provenance = _daily(prices, calendar, as_of)
    days = [row[0] for row in sessions]
    passed, exclusions, missing_rows, measurements = [], [], [], []
    for item in instruments:
        symbol, rows = item['symbol'], bars.get(item['symbol'], {})
        missing = [day.isoformat() for day in days if day not in rows]
        if symbol not in requested or missing:
            missing_rows.append({'symbol': symbol, 'missing_sessions': missing, 'reason': 'symbol_not_requested' if symbol not in requested else 'missing_required_sessions'})
            continue
        price = rows[days[-1]]['c']
        notional = math.fsum(rows[day]['vw'] * rows[day]['v'] for day in days) / len(days)
        _number(notional)
        measurement = {'symbol': symbol, 'price': price, 'average_daily_notional': notional}
        measurements.append(measurement)
        reasons = []
        if price < min_price:
            reasons.append('below_min_price')
        if notional < min_average_daily_notional:
            reasons.append('below_min_average_daily_notional')
        if reasons:
            exclusions.append(measurement | {'reasons': reasons})
        else:
            passed.append(item)
    definition = {'min_price': min_price, 'min_average_daily_notional': min_average_daily_notional,
                  'sessions': 20, 'basis': 'daily VWAP times volume including extended hours', 'top_n_limit': None}
    result = {'market_universe': 1, 'operation': 'prefilter', 'as_of': _iso(parse_time(as_of)),
              'complete': bool(plan['complete'] and complete and not missing_rows), 'batch_size': plan.get('batch_size', 100),
              'universe': {'name': plan['universe']['name'] + '-daily-proxy-v1', 'membership_date': plan['universe']['membership_date'],
                  'source': plan['universe']['source'] + ' Then all available price/daily-notional proxy passes; missing evidence remains excluded from measurement, not presumed failing.',
                  'instruments': passed},
              'coverage': {'declared': len(instruments), 'requested': sum(item['symbol'] in requested for item in instruments),
                           'measured': len(measurements), 'passing': len(passed), 'excluded': len(exclusions), 'unavailable': len(missing_rows)},
              'reference_session': days[-1].isoformat(), 'required_sessions': [day.isoformat() for day in days],
              'definition': definition, 'measurements': measurements, 'exclusions': exclusions, 'unavailable': missing_rows,
              'parent_universe': plan, 'sources': {'prices': provenance, 'sessions': calendar},
              'input_sha256': _digest({'plan': plan, 'prices': prices, 'sessions': calendar, 'as_of': as_of, 'rules': definition}),
              'warnings': list(dict.fromkeys(plan.get('warnings', []) + warnings + ['Daily notional is a broad discovery proxy, not verified regular-session turnover or market capitalization.']))}
    result['batches'] = _batches(passed, result['as_of'], result['batch_size'])
    return result


def prepare(plan, prices, calendar, as_of, benchmark='SPY', rules=None, *, validate=True):
    """Prepare a validated full-history screen without ad hoc envelope rewriting."""
    instruments = _plan(plan, as_of)
    if not instruments:
        raise DataError('incomplete_data', 'No measured discovery passes; report prefilter coverage instead of constructing an empty screen.')
    _symbol(benchmark)
    if type(validate) is not bool or not isinstance(prices, list) or not prices:
        fail('Provide original price batches and an explicit boolean validation choice.')
    cutoff = parse_time(as_of)
    for envelope in prices:
        envelope = _envelope(envelope, 'prices', 'bars')
        if (parse_date(envelope['query'].get('asof')) != cutoff.astimezone(ny()).date()
                or parse_time(envelope['query'].get('requested_end')) > cutoff):
            fail('Price identity mapping or requested end disagrees with the universe cutoff.')
    declared = dict(plan['universe'])
    declared['discovery_coverage'] = plan.get('coverage', {})
    declared['discovery_complete'] = plan['complete']
    declared['discovery_input_sha256'] = plan.get('input_sha256')
    definition = {'min_price': 10, 'min_average_daily_notional': 25000000,
                  'require_above_ma50': False, 'require_above_ma200': False,
                  'require_positive_relative_return_6m': False, 'sort_by': 'relative_return_3m',
                  'limit': len(instruments)}
    if rules is not None:
        if not isinstance(rules, dict):
            fail('Screen rules must be a JSON object.')
        definition.update(rules)
    bundle = {'market_screen_input': 1, 'as_of': _iso(parse_time(as_of)), 'universe': declared,
              'benchmark': benchmark, 'prices': prices, 'sessions': calendar, 'rules': definition}
    if validate:
        screen(bundle)
    return bundle


def liquidity(prices, calendar, as_of, symbols, session_count=20, minimum=25000000, market_caps=None, min_market_cap=2000000000):
    """Measure exact regular-minute coverage and retain unresolved cap eligibility."""
    cutoff = parse_time(as_of)
    if type(session_count) is not int or not 1 <= session_count <= 60:
        fail('Liquidity session count must be 1–60.')
    if not isinstance(symbols, list) or not symbols or len(set(symbols)) != len(symbols):
        fail('Provide distinct shortlist symbols.')
    for symbol in symbols:
        _symbol(symbol)
    _number(minimum)
    _number(min_market_cap)
    sessions, _ = _sessions(calendar, cutoff, session_count)
    expected = {day: {opened + timedelta(minutes=i) for i in range(int((closed-opened).total_seconds()/60))}
                for day, opened, closed in sessions}
    observed = {symbol: {} for symbol in symbols}
    source_complete, sources, warnings = True, [], []
    if not isinstance(prices, list) or len(prices) > 200:
        fail('Provide a list of original minute-price envelopes.')
    for envelope in prices:
        envelope = _envelope(envelope, 'prices', 'bars')
        query = envelope['query']
        if (query.get('feed') != 'sip' or envelope['source'].get('feed') != 'sip'
                or query.get('timeframe') != '1Min' or query.get('adjustment') != 'split'
                or query.get('currency') != 'USD' or parse_date(query.get('asof')) != cutoff.astimezone(ny()).date()):
            fail('Liquidity needs same-date mapped SIP USD split-adjusted minute evidence.')
        start, end = parse_time(query.get('start')), parse_time(query.get('end'))
        requested_end = parse_time(query.get('requested_end'))
        if start > end or end > requested_end or requested_end > cutoff:
            fail('Minute query interval crosses the evidence cutoff.')
        requested, values = envelope['data'].get('requested_symbols'), envelope['data'].get('bars')
        if (not isinstance(requested, list) or not requested or len(set(requested)) != len(requested)
                or query.get('symbols') != ','.join(requested) or not isinstance(values, dict) or set(values) - set(requested)):
            fail('Minute query and response identities disagree.')
        for symbol, rows in values.items():
            _symbol(symbol)
            if not isinstance(rows, list):
                fail('Invalid minute rows.')
            for row in rows:
                if not isinstance(row, dict):
                    fail('Invalid minute row.')
                stamp, left, right = parse_time(row.get('t')), parse_time(row.get('interval_start')), parse_time(row.get('interval_end'))
                day = parse_date(row.get('new_york_date'))
                if (stamp != left or right != left + timedelta(minutes=1) or left.second or left.microsecond
                        or not start <= left <= end or right > requested_end or day != left.astimezone(ny()).date()):
                    fail('Minute bar boundaries disagree with query or source date.')
                for key in ('o', 'h', 'l', 'c', 'vw'):
                    _number(row.get(key), positive=True)
                _number(row.get('v'))
                if row['l'] > min(row['o'], row['c']) or row['h'] < max(row['o'], row['c']):
                    fail('Invalid minute OHLC range.')
                if symbol not in observed or left not in expected.get(day, set()):
                    continue
                normalized = {key: row[key] for key in ('o', 'h', 'l', 'c', 'vw', 'v')}
                prior = observed[symbol].get(left)
                if prior is not None and prior != normalized:
                    fail('Conflicting duplicate minute bars.')
                observed[symbol][left] = normalized
        source_complete = source_complete and envelope['complete']
        warnings.extend(envelope.get('warnings', []))
        sources.append({'query': query, 'source': envelope['source'], 'requests': envelope.get('requests', []),
                        'complete': envelope['complete'], 'sha256': _digest(envelope)})
    caps = {}
    if market_caps is not None:
        if not isinstance(market_caps, list):
            fail('Market-cap evidence must be dated source rows.')
        for row in market_caps:
            if not isinstance(row, dict):
                fail('Invalid market-cap evidence.')
            symbol = _symbol(row.get('symbol'))
            if symbol in caps or symbol not in symbols:
                fail('Ambiguous or unrequested market-cap identity.')
            _number(row.get('market_cap_usd'), positive=True)
            measured, available = parse_time(row.get('as_of')), parse_time(row.get('available_at'))
            if (measured > available or available > cutoff or measured.astimezone(ny()).date() < sessions[-1][0]
                    or row.get('currency') != 'USD'
                    or not isinstance(row.get('source_url'), str) or not re.match(r'https://[^/\s]+/', row['source_url'])
                    or not isinstance(row.get('basis'), str) or not row['basis'].strip()):
                fail('Market cap needs a sourced USD basis, a measurement at least as recent as the reference session, and measurement <= availability <= cutoff.')
            caps[symbol] = row
    candidates = []
    for symbol in symbols:
        by_session, missing_total = [], 0
        for day, opened, closed in sessions:
            missing = sorted(expected[day] - set(observed[symbol]))
            values = [observed[symbol][stamp] for stamp in expected[day] if stamp in observed[symbol]]
            subtotal = math.fsum(row['vw'] * row['v'] for row in values)
            _number(subtotal)
            missing_total += len(missing)
            by_session.append({'date': day.isoformat(), 'expected_minutes': len(expected[day]), 'observed_minutes': len(values),
                               'missing_minutes': [_iso(stamp) for stamp in missing], 'observed_notional_usd': subtotal,
                               'regular_notional_usd': subtotal if not missing else None})
        full = bool(prices) and source_complete and missing_total == 0
        mean = math.fsum(row['regular_notional_usd'] for row in by_session) / session_count if full else None
        cap = caps.get(symbol)
        candidates.append({'symbol': symbol, 'regular_liquidity_complete': full, 'average_regular_notional_usd': mean,
                           'liquidity_eligible': mean >= minimum if mean is not None else None,
                           'market_cap_evidence': cap, 'market_cap_eligible': cap['market_cap_usd'] >= min_market_cap if cap else None,
                           'eligibility_verified': bool(full and mean >= minimum and cap and cap['market_cap_usd'] >= min_market_cap),
                           'sessions': by_session})
    return {'market_universe': 1, 'operation': 'liquidity', 'as_of': _iso(cutoff),
            'complete': all(row['regular_liquidity_complete'] and row['market_cap_evidence'] is not None for row in candidates),
            'reference_session': sessions[-1][0].isoformat(), 'candidates': candidates,
            'definition': {'session_count': session_count, 'minimum_average_regular_notional_usd': minimum,
                           'minimum_market_cap_usd': min_market_cap, 'missing_intervals': 'unresolved; never zero-filled'},
            'sources': {'prices': sources, 'sessions': calendar},
            'warnings': list(dict.fromkeys(warnings + ['Missing minute bars can represent no eligible trades or absent data; absence never proves zero turnover.',
                'Source completeness and regular-session coverage are separate checks; market cap and liquidity do not establish a buying opportunity.',
                'Market-cap dates and share-class/ADR basis require verification; the calculator does not derive capitalization from guessed shares.']))}


def _read(path):
    with Path(path).open('rb') as handle:
        raw = handle.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        fail('Input exceeds 128 MiB.')
    return json.loads(raw.decode(), object_pairs_hook=_unique_object, parse_constant=lambda value: fail('Non-finite JSON is invalid.'))


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('--test', action='store_true')
    commands = result.add_subparsers(dest='command')
    command = commands.add_parser('universe')
    command.add_argument('--directory', required=True)
    command.add_argument('--as-of', required=True)
    command.add_argument('--batch-size', type=int, default=100)
    for name in ('prefilter', 'prepare', 'liquidity'):
        command = commands.add_parser(name)
        command.add_argument('--prices', action='append', default=[])
        command.add_argument('--sessions', required=True)
        command.add_argument('--as-of', required=True)
        if name != 'liquidity':
            command.add_argument('--universe', required=True)
        if name == 'prepare':
            command.add_argument('--benchmark', default='SPY')
            command.add_argument('--rules')
        if name == 'liquidity':
            command.add_argument('--symbols', required=True)
            command.add_argument('--market-caps')
    return result


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        if args.test:
            return run_self_test()
        if args.command == 'universe':
            out = universe(_read(args.directory), args.as_of, args.batch_size)
        elif args.command in ('prefilter', 'prepare', 'liquidity'):
            prices, calendar = [_read(path) for path in args.prices], _read(args.sessions)
            if args.command == 'prefilter':
                out = prefilter(_read(args.universe), prices, calendar, args.as_of)
            elif args.command == 'prepare':
                out = prepare(_read(args.universe), prices, calendar, args.as_of, args.benchmark, _read(args.rules) if args.rules else None)
            else:
                out = liquidity(prices, calendar, args.as_of, args.symbols.split(','), market_caps=_read(args.market_caps) if args.market_caps else None)
        else:
            fail('Choose universe, prefilter, prepare or liquidity.')
        code = 0 if out.get('complete', True) else 2
    except (DataError, OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        out = {'market_universe': 1, 'complete': False, 'error': {'code': exc.code if isinstance(exc, DataError) else 'invalid_input',
               'message': str(exc) if isinstance(exc, DataError) else 'Invalid or unreadable saved evidence.'}}
        code = 2
    print(json.dumps(out, allow_nan=False))
    return code


def run_self_test():
    import copy
    import unittest
    from market_public import _directory as parse_directory

    cutoff = '2025-04-01T15:30:00Z'

    def fixture_directory():
        names = [('AAA', 'Fixture A Common Stock'), ('ADR', 'Fixture American Depositary Shares'),
                 ('BBB', 'Fixture B Ordinary Shares'), ('PRF', 'Fixture Preferred Stock'),
                 ('UNT', 'Fixture Common Units'), ('WI', 'Fixture Common Stock When-Issued'),
                 ('UNK', 'Unresolved instrument'), ('DEP', 'Depositary Shares Representing Preferred Stock')]
        raw = 'Symbol|Security Name|Market Category|Test Issue|Round Lot Size|ETF\n'
        raw += ''.join('%s|%s|Q|N|100|N\n' % pair for pair in names)
        raw += 'File Creation Time: 0401202510:00|||||\n'
        other = ('ACT Symbol|Security Name|Exchange|ETF|Round Lot Size|Test Issue\n'
                 'CCC|Fixture C Common Stock|N|N|100|N\n'
                 'ETF|Fixture ETF Common Stock|P|Y|100|N\n'
                 'File Creation Time: 0401202510:00|||||\n')
        data, files = [], []
        for filename, text in [('nasdaqlisted.txt', raw), ('otherlisted.txt', other)]:
            rows, info = parse_directory(text, filename)
            data.extend(rows)
            files.append(info)
        return {'market_data': 1, 'operation': 'symbols', 'provider': 'nasdaq', 'resource': 'symbols',
                'complete': True, 'query': {'symbols': [], 'scope': 'current_directory'},
                'data': {'securities': data, 'files': files}, 'warnings': [],
                'requests': [{'retrieved_at': '2025-04-01T15:31:00Z'}]}

    def fixture_evidence(minute=False):
        first, last = parse_date('2024-01-01'), parse_date('2025-03-31')
        days, cursor = [], first
        while cursor <= last:
            if cursor.weekday() < 5:
                days.append(cursor)
            cursor += timedelta(days=1)
        cal = {'market_data': 1, 'operation': 'sessions', 'provider': 'alpaca', 'resource': 'calendar',
               'complete': True, 'query': {'start': first.isoformat(), 'end': '2025-04-01'},
               'source': {}, 'requests': [], 'warnings': [], 'data': {'sessions': [
                   {'date': day.isoformat(), 'open_at': _iso(datetime.combine(day, time(9, 30), ny())),
                    'close_at': _iso(datetime.combine(day, time(9, 32), ny()))} for day in days]}}
        bars = {}
        for symbol in ('AAA', 'ADR', 'BBB', 'CCC', 'SPY'):
            rows = []
            for index, day in enumerate(days):
                price = 100 + index
                lefts = [datetime.combine(day, time(9, minute), ny()) for minute in (30, 31)] if minute else [datetime.combine(day, time.min, ny())]
                for left in lefts:
                    right = left + timedelta(minutes=1) if minute else datetime.combine(day + timedelta(days=1), time.min, ny())
                    rows.append({'t': _iso(left), 'interval_start': _iso(left), 'interval_end': _iso(right),
                                 'new_york_date': day.isoformat(), 'o': price, 'h': price, 'l': price,
                                 'c': price, 'vw': price, 'v': 1000000})
            bars[symbol] = rows
        prices = {'market_data': 1, 'operation': 'prices', 'provider': 'alpaca', 'resource': 'bars',
                  'complete': True, 'query': {'symbols': ','.join(bars), 'start': '2024-01-01T05:00:00Z',
                      'end': '2025-04-01T03:59:59Z', 'requested_end': '2025-04-01T04:00:00Z',
                      'asof': '2025-04-01', 'timeframe': '1Min' if minute else '1Day',
                      'adjustment': 'split', 'currency': 'USD', 'feed': 'sip'},
                  'source': {'feed': 'sip'}, 'requests': [], 'warnings': [],
                  'data': {'requested_symbols': list(bars), 'bars': bars}}
        return prices, cal

    def cap():
        return [{'symbol': 'AAA', 'market_cap_usd': 3000000000, 'currency': 'USD',
                 'as_of': '2025-03-31T20:00:00Z', 'available_at': '2025-03-31T20:01:00Z',
                 'source_url': 'https://example.invalid/issuer', 'basis': 'Synthetic complete common equity capitalization'}]

    class Cases(unittest.TestCase):
        def setUp(self):
            self.directory = fixture_directory()
            self.plan = universe(self.directory, cutoff, 2)
            self.prices, self.calendar = fixture_evidence()

        def test_conservative_classification(self):
            self.assertEqual([r['symbol'] for r in self.plan['universe']['instruments']], ['AAA', 'ADR', 'BBB', 'CCC'])
            self.assertEqual(next(r['security_type'] for r in self.plan['universe']['instruments'] if r['symbol'] == 'ADR'), 'adr')
            self.assertEqual(len(self.plan['exclusions']), 6)

        def test_partial_directory_not_complete(self):
            self.directory['complete'] = False
            self.assertFalse(universe(self.directory, cutoff)['complete'])

        def test_filtered_directory_refused(self):
            self.directory['query']['symbols'] = ['AAA']
            with self.assertRaises(DataError):
                universe(self.directory, cutoff)

        def test_duplicate_symbol_refused(self):
            self.directory['data']['securities'].append(self.directory['data']['securities'][0])
            with self.assertRaises(DataError):
                universe(self.directory, cutoff)

        def test_source_flag_conflict_refused(self):
            self.directory['data']['securities'][0]['etf'] = True
            with self.assertRaises(DataError):
                universe(self.directory, cutoff)

        def test_hash_batches_stable_and_complete(self):
            rows = self.plan['universe']['instruments']
            self.assertEqual(_batches(rows, cutoff, 2), _batches(list(reversed(rows)), cutoff, 2))
            self.assertEqual(sorted(sum(_batches(rows, cutoff, 2), [])), ['AAA', 'ADR', 'BBB', 'CCC'])

        def test_hash_order_rotates_by_declared_date(self):
            rows = [{'symbol': 'X%03d' % n, 'exchange': 'NASDAQ'} for n in range(30)]
            self.assertNotEqual(_batches(rows, cutoff), _batches(rows, '2025-04-02T15:30:00Z'))

        def test_later_directory_keeps_real_date_and_is_incomplete(self):
            self.directory['requests'][0]['retrieved_at'] = '2025-04-02T05:00:00Z'
            out = universe(self.directory, cutoff)
            self.assertFalse(out['complete'])
            self.assertEqual(out['universe']['membership_date'], '2025-04-02')

        def test_missing_directory_observation_is_unavailable(self):
            self.directory['requests'] = []
            self.assertFalse(universe(self.directory, cutoff)['complete'])

        def test_same_day_after_cutoff_current_discovery_explicit(self):
            self.assertTrue(self.plan['complete'])
            self.assertIn('after the cutoff', ' '.join(self.plan['warnings']))

        def test_prefilter_complete_without_top_n(self):
            out = prefilter(self.plan, [self.prices], self.calendar, cutoff)
            self.assertTrue(out['complete'])
            self.assertEqual(out['coverage']['passing'], 4)
            self.assertIsNone(out['definition']['top_n_limit'])

        def test_unrequested_names_remain_unavailable(self):
            self.prices['data']['requested_symbols'].remove('AAA')
            self.prices['data']['bars'].pop('AAA')
            self.prices['query']['symbols'] = ','.join(self.prices['data']['requested_symbols'])
            out = prefilter(self.plan, [self.prices], self.calendar, cutoff)
            self.assertFalse(out['complete'])
            self.assertEqual(out['unavailable'][0]['symbol'], 'AAA')
            self.assertEqual(out['coverage']['declared'], 4)

        def test_missing_daily_session_not_zero_filled(self):
            self.prices['data']['bars']['AAA'].pop()
            out = prefilter(self.plan, [self.prices], self.calendar, cutoff)
            self.assertFalse(out['complete'])
            self.assertEqual(out['unavailable'][0]['missing_sessions'], ['2025-03-31'])

        def test_empty_prices_preserve_unavailable_roster(self):
            out = prefilter(self.plan, [], self.calendar, cutoff)
            self.assertFalse(out['complete'])
            self.assertEqual(out['coverage']['unavailable'], 4)

        def test_cutoff_and_mapping_mismatch_refused(self):
            self.prices['query']['asof'] = '2025-04-02'
            with self.assertRaises(DataError):
                prefilter(self.plan, [self.prices], self.calendar, cutoff)

        def test_completion_is_strict_boolean(self):
            self.plan['complete'] = 'false'
            with self.assertRaises(DataError):
                prefilter(self.plan, [self.prices], self.calendar, cutoff)

        def test_prepare_retains_all_names_and_coverage(self):
            filtered = prefilter(self.plan, [self.prices], self.calendar, cutoff)
            filtered['complete'] = False
            bundle = prepare(filtered, [self.prices], self.calendar, cutoff)
            self.assertEqual(bundle['rules']['limit'], 4)
            self.assertFalse(screen(bundle)['complete'])
            self.assertIs(bundle['prices'][0], self.prices)

        def test_minute_liquidity_exact_early_close(self):
            prices, calendar = fixture_evidence(True)
            out = liquidity([prices], calendar, cutoff, ['AAA'], market_caps=cap())
            self.assertTrue(out['complete'])
            self.assertTrue(out['candidates'][0]['eligibility_verified'])
            self.assertEqual(out['candidates'][0]['sessions'][-1]['expected_minutes'], 2)
            self.assertEqual(out['candidates'][0]['sessions'][-1]['regular_notional_usd'], 850000000)

        def test_minute_gap_is_not_zero_or_shorter_denominator(self):
            prices, calendar = fixture_evidence(True)
            prices['data']['bars']['AAA'].pop()
            row = liquidity([prices], calendar, cutoff, ['AAA'], market_caps=cap())['candidates'][0]
            self.assertFalse(row['regular_liquidity_complete'])
            self.assertIsNone(row['average_regular_notional_usd'])
            self.assertEqual(len(row['sessions'][-1]['missing_minutes']), 1)

        def test_minute_partial_envelope_not_complete(self):
            prices, calendar = fixture_evidence(True)
            prices['complete'] = False
            self.assertFalse(liquidity([prices], calendar, cutoff, ['AAA'], market_caps=cap())['complete'])

        def test_no_cap_does_not_invent_cap_eligibility(self):
            prices, calendar = fixture_evidence(True)
            row = liquidity([prices], calendar, cutoff, ['AAA'])['candidates'][0]
            self.assertTrue(row['regular_liquidity_complete'])
            self.assertIsNone(row['market_cap_eligible'])
            self.assertFalse(row['eligibility_verified'])

        def test_postcutoff_market_cap_refused(self):
            prices, calendar = fixture_evidence(True)
            caps = cap()
            caps[0]['available_at'] = '2025-04-02T20:00:00Z'
            with self.assertRaises(DataError):
                liquidity([prices], calendar, cutoff, ['AAA'], market_caps=caps)

        def test_stale_market_cap_refused(self):
            prices, calendar = fixture_evidence(True)
            caps = cap()
            caps[0]['as_of'] = '2025-03-28T20:00:00Z'
            with self.assertRaises(DataError):
                liquidity([prices], calendar, cutoff, ['AAA'], market_caps=caps)

        def test_conflicting_minutes_refused(self):
            prices, calendar = fixture_evidence(True)
            duplicate = copy.deepcopy(prices)
            duplicate['data']['bars']['AAA'][-1]['v'] += 1
            with self.assertRaises(DataError):
                liquidity([prices, duplicate], calendar, cutoff, ['AAA'])

        def test_duplicate_calendar_dates_refused(self):
            self.calendar['data']['sessions'].append(self.calendar['data']['sessions'][-1])
            with self.assertRaises(DataError):
                prefilter(self.plan, [self.prices], self.calendar, cutoff)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Cases)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print('%d/%d self-tests passed' % (passed, result.testsRun))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
