#!/usr/bin/env python3
"""Read-only SEC and Nasdaq adapters; invoke commands through market_data.py.

SEC args: cik OR symbol, as_of; optional since (ISO date/aware timestamp),
forms (CSV), max_pages (10), limit (1000). Facts also accepts taxonomy (us-gaap)
and concepts (CSV). Nasdaq args: symbols (optional CSV), limit (20000);
halts also accepts date (ISO halt date) and as_of (halt-occurrence cutoff).
No credentials, state, data files or vault notes are written by this module.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, time, timezone
from email.utils import parsedate_to_datetime
import io
import math
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

# Sibling adapters ship together and also support direct file-based imports.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from market_http import DataError, parse_date, parse_time, required_env, utc_now

TICKERS = 'https://www.sec.gov/files/company_tickers_exchange.json'
SUBMISSIONS = 'https://data.sec.gov/submissions/'
FACTS = 'https://data.sec.gov/api/xbrl/companyfacts/'
SYMDIR = 'https://www.nasdaqtrader.com/dynamic/symdir/'
HALTS = 'https://www.nasdaqtrader.com/rss.aspx'
DEFAULT_CONCEPTS = ('RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues',
                    'NetIncomeLoss', 'Assets', 'Liabilities',
                    'CashAndCashEquivalentsAtCarryingValue')
ACC = re.compile(r'\d{10}-\d{2}-\d{6}\Z')
SYMBOL = re.compile(r'[A-Z0-9][A-Z0-9.\-/$^=+]{0,29}\Z')
MAX_RECORDS = 100000
HALT_SOURCE_FIELDS = ('HaltDate', 'HaltTime', 'IssueSymbol', 'IssueName', 'Market', 'Mkt',
                      'ReasonCode', 'PauseThresholdPrice', 'ResumptionDate',
                      'ResumptionQuoteTime', 'ResumptionTradeTime')


def _ny():
    return ZoneInfo('America/New_York')


def _bad(message):
    raise DataError('schema_error', message)


def _str(value, *, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()):
        _bad('Provider returned a missing or invalid text field.')
    return value.strip()


def _int_arg(args, key, default, maximum):
    value = getattr(args, key, None)
    value = default if value is None else value
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise DataError('invalid_input', f'{key} must be between 1 and {maximum}.')
    return value


def _csv(value, pattern, maximum=100):
    if value is None or value == '':
        return []
    if not isinstance(value, str):
        raise DataError('invalid_input', 'A comma-separated string is required.')
    result = [s.strip() for s in value.split(',')]
    if len(result) > maximum or any(not pattern.fullmatch(s) for s in result):
        raise DataError('invalid_input', 'A requested symbol, form or concept is invalid.')
    return list(dict.fromkeys(result))


def _cik(value):
    if isinstance(value, bool) or not re.fullmatch(r'\d{1,10}', str(value)) or int(value) == 0:
        raise DataError('invalid_input', 'CIK must be a nonzero number of at most ten digits.')
    return str(int(value)).zfill(10)


def validate_sec_credentials(env):
    """Validate locally and return the SEC application/contact header value."""
    ua = required_env(env, 'SEC_USER_AGENT')
    if not re.search(r'\S+@\S+\.\S+', ua) or not re.search(r'\s', ua):
        raise DataError('invalid_input', 'SEC_USER_AGENT must identify your application and a contact email.')
    return ua


def _sec_headers(client):
    return {'User-Agent': validate_sec_credentials(client.env), 'Accept': 'application/json'}


def _identity(client, args, headers):
    cik, symbol = getattr(args, 'cik', None), getattr(args, 'symbol', None)
    if bool(cik) == bool(symbol):
        raise DataError('invalid_input', 'Supply exactly one of cik or symbol.')
    if cik:
        return _cik(cik)
    symbols = _csv(symbol.upper(), SYMBOL, 1)
    if len(symbols) != 1:
        raise DataError('invalid_input', 'Supply exactly one SEC symbol.')
    payload = client.get_json(TICKERS, headers=headers)
    if not isinstance(payload, dict) or not isinstance(payload.get('fields'), list) or not isinstance(payload.get('data'), list):
        _bad('SEC ticker directory schema is invalid.')
    fields = payload['fields']
    if (any(not isinstance(field, str) for field in fields) or len(set(fields)) != len(fields)
            or not {'cik', 'ticker', 'name', 'exchange'} <= set(fields)):
        _bad('SEC ticker directory columns are missing or repeated.')
    matches = set()
    for row in payload['data']:
        if not isinstance(row, list) or len(row) != len(fields):
            _bad('SEC ticker directory row has the wrong column count.')
        item = dict(zip(fields, row))
        if _str(item['ticker']).upper() == symbols[0]:
            matches.add(_cik(item['cik']))
    if len(matches) != 1:
        raise DataError('identity_unresolved', 'Symbol did not identify exactly one SEC company; use its verified CIK.')
    return matches.pop()


def _window(args):
    now = utc_now()
    cutoff = parse_time(getattr(args, 'as_of', None) or now.isoformat())
    if cutoff > now:
        raise DataError('invalid_input', 'SEC as_of cannot be in the future.')
    since = getattr(args, 'since', None)
    if since and re.fullmatch(r'\d{4}-\d{2}-\d{2}', since):
        since = datetime.combine(parse_date(since), time.min, _ny()).astimezone(timezone.utc)
    elif since:
        since = parse_time(since)
    if since and since > cutoff:
        raise DataError('invalid_input', 'since cannot be after as_of.')
    return since, cutoff


def _filing_rows(payload):
    required = ('accessionNumber', 'filingDate', 'form')
    optional = ('acceptanceDateTime', 'reportDate', 'primaryDocument', 'primaryDocDescription', 'items')
    if not isinstance(payload, dict) or any(not isinstance(payload.get(k), list) for k in required):
        _bad('SEC submissions columns are missing.')
    count = len(payload['accessionNumber'])
    if count > MAX_RECORDS:
        _bad('SEC submissions exceed the record bound.')
    for key in required + optional:
        if key in payload and (not isinstance(payload[key], list) or len(payload[key]) != count):
            _bad('SEC submissions columns have inconsistent lengths.')
    rows = []
    for i in range(count):
        row = {key: payload[key][i] for key in required + optional if key in payload}
        if not ACC.fullmatch(_str(row['accessionNumber'])):
            _bad('SEC accession number is invalid.')
        _str(row['form'])
        parse_date(row['filingDate'])
        if row.get('acceptanceDateTime'):
            parse_time(row['acceptanceDateTime'])
        for key in optional:
            if key in row and row[key] is not None:
                _str(row[key], empty=True)
        rows.append(row)
    return rows


def _submissions(client, args, headers):
    # Validate local bounds before even a symbol-directory request consumes access.
    since, cutoff = _window(args)
    pages = _int_arg(args, 'max_pages', 10, 50)
    cik = _identity(client, args, headers)
    payload = client.get_json(SUBMISSIONS + f'CIK{cik}.json', headers=headers)
    if not isinstance(payload, dict) or _cik(payload.get('cik')) != cik:
        _bad('SEC submissions company identity does not match the request.')
    for key in ('tickers', 'exchanges'):
        if not isinstance(payload.get(key), list) or any(not isinstance(v, str) for v in payload[key]):
            _bad('SEC company identity arrays are invalid.')
    identity = {'cik': cik, 'name': _str(payload.get('name')),
                'tickers': payload['tickers'], 'exchanges': payload['exchanges']}
    filings = payload.get('filings')
    if not isinstance(filings, dict) or not isinstance(filings.get('files'), list):
        _bad('SEC submissions history descriptor is missing.')
    rows = _filing_rows(filings.get('recent'))
    eligible = []
    for item in filings['files']:
        if not isinstance(item, dict):
            _bad('SEC historical submissions descriptor is invalid.')
        name = _str(item.get('name'))
        if not re.fullmatch(r'CIK' + cik + r'-submissions-\d+\.json', name):
            _bad('SEC historical submissions filename is invalid.')
        start, end = parse_date(item.get('filingFrom')), parse_date(item.get('filingTo'))
        if start > end:
            _bad('SEC historical submissions date range is invalid.')
        if since and end >= since.astimezone(_ny()).date() and start <= cutoff.astimezone(_ny()).date():
            eligible.append((end, name))
    eligible.sort(reverse=True)
    for _, name in eligible[:pages]:
        rows.extend(_filing_rows(client.get_json(SUBMISSIONS + name, headers=headers)))
        if len(rows) > MAX_RECORDS:
            _bad('SEC submissions exceed the combined record bound.')
    unique = {}
    for row in rows:
        key = row['accessionNumber']
        if key in unique and row != unique[key]:
            _bad('SEC submissions returned conflicting duplicate accessions.')
        unique[key] = row
    warnings = ['Company identity metadata is current, not a historical ticker/universe reconstruction.',
                'Acceptance timestamps approximate availability; SEC dissemination can follow acceptance.',
                'Acceptance before the assigned filing date does not prove publication: those filings use conservative date-only availability.']
    complete = len(eligible) <= pages
    if not complete:
        warnings.append('Historical submissions page limit reached; requested filing interval is incomplete.')
    if not since and filings['files']:
        warnings.append('Only the recent submissions block was requested; use since to include older filing pages.')
    return identity, list(unique.values()), complete, warnings, since, cutoff


def _availability(filed, accepted, since, cutoff):
    """Return (eligible, time basis); do not guess a same-day publication time."""
    filed_date = parse_date(filed)
    if accepted:
        stamp = parse_time(accepted)
        # EDGAR can accept an evening submission while assigning the next
        # business day's filing date and withholding dissemination until then.
        # A prior-day acceptance is not an intraday publication timestamp for
        # that later filing date; apply the date-only rules below instead.
        if stamp.astimezone(_ny()).date() >= filed_date:
            return (stamp <= cutoff and (not since or stamp >= since), 'acceptance_timestamp')
    if filed_date >= cutoff.astimezone(_ny()).date():
        return False, 'date_only_unproven' if filed_date == cutoff.astimezone(_ny()).date() else 'after_cutoff'
    if since and filed_date < since.astimezone(_ny()).date():
        return False, 'before_since'
    if since and filed_date == since.astimezone(_ny()).date() and since.astimezone(_ny()).time() != time.min:
        return False, 'date_only_unproven'
    return True, 'prior_filing_date_only'


def _filing_url(cik, accession):
    return f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace("-", "")}/{accession}-index.html'


def sec_company(client, args):
    """Resolve a company and return filings within the declared recent/dated scope."""
    forms = set(_csv(getattr(args, 'forms', None), re.compile(r'[A-Za-z0-9 /\-]{1,30}\Z')))
    limit = _int_arg(args, 'limit', 1000, MAX_RECORDS)
    headers = _sec_headers(client)
    identity, rows, complete, warnings, since, cutoff = _submissions(client, args, headers)
    selected, unproven = [], 0
    for row in rows:
        if forms and row['form'] not in forms:
            continue
        keep, basis = _availability(row['filingDate'], row.get('acceptanceDateTime'), since, cutoff)
        unproven += basis == 'date_only_unproven'
        if keep:
            out = dict(row, availability_basis=basis,
                       source_url=_filing_url(identity['cik'], row['accessionNumber']))
            selected.append(out)
    selected.sort(key=lambda row: (row['filingDate'], row.get('acceptanceDateTime') or '', row['accessionNumber']), reverse=True)
    if len(selected) > limit:
        complete = False
        warnings.append('Filing record limit reached; refine since/forms or raise limit.')
    if unproven:
        complete = False
        warnings.append(f'{unproven} date-only filings omitted because their availability within the timestamp window is unproven.')
    return {'provider': 'sec', 'resource': 'company', 'complete': complete, 'warnings': warnings,
            'query': {'cik': identity['cik'], 'since': since.isoformat() if since else None,
                      'as_of': cutoff.isoformat(), 'forms': sorted(forms),
                      'scope': 'filing_interval' if since else 'recent_submissions'},
            'data': {'company': identity, 'filings': selected[:limit]}}


def sec_facts(client, args):
    """Return chosen reported facts, preserving units, periods and filing versions."""
    taxonomy = getattr(args, 'taxonomy', None) or 'us-gaap'
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,39}', taxonomy):
        raise DataError('invalid_input', 'Invalid taxonomy.')
    concepts = _csv(getattr(args, 'concepts', None), re.compile(r'[A-Za-z][A-Za-z0-9_]{0,149}\Z'), 50) or list(DEFAULT_CONCEPTS)
    forms = set(_csv(getattr(args, 'forms', None), re.compile(r'[A-Za-z0-9 /\-]{1,30}\Z')))
    limit = _int_arg(args, 'limit', 1000, MAX_RECORDS)
    headers = _sec_headers(client)
    identity, filings, complete, warnings, since, cutoff = _submissions(client, args, headers)
    acceptance = {row['accessionNumber']: row.get('acceptanceDateTime') for row in filings}
    payload = client.get_json(FACTS + f'CIK{identity["cik"]}.json', headers=headers)
    if not isinstance(payload, dict) or _cik(payload.get('cik')) != identity['cik'] or not isinstance(payload.get('facts'), dict):
        _bad('SEC company facts identity or schema is invalid.')
    taxonomy_data = payload['facts'].get(taxonomy, {})
    if not isinstance(taxonomy_data, dict):
        _bad('SEC taxonomy schema is invalid.')
    selected, absent, unproven, scanned = [], [], 0, 0
    for concept in concepts:
        info = taxonomy_data.get(concept)
        if info is None:
            absent.append(concept)
            continue
        if not isinstance(info, dict) or not isinstance(info.get('units'), dict):
            _bad('SEC concept units schema is invalid.')
        for unit, facts in info['units'].items():
            _str(unit)
            if not isinstance(facts, list):
                _bad('SEC concept observations schema is invalid.')
            for fact in facts:
                scanned += 1
                if scanned > MAX_RECORDS:
                    _bad('Selected SEC concepts exceed the record bound; request fewer concepts.')
                if not isinstance(fact, dict) or not ACC.fullmatch(_str(fact.get('accn'))):
                    _bad('SEC fact accession is invalid.')
                val = fact.get('val')
                if (isinstance(val, bool) or not isinstance(val, (int, float))
                        or isinstance(val, float) and not math.isfinite(val)):
                    _bad('SEC fact value is not a finite number.')
                _str(fact.get('form'))
                parse_date(fact.get('end'))
                if fact.get('start'):
                    if parse_date(fact['start']) > parse_date(fact['end']):
                        _bad('SEC fact period is reversed.')
                if forms and fact['form'] not in forms:
                    continue
                accepted = acceptance.get(fact['accn'])
                keep, basis = _availability(fact.get('filed'), accepted, since, cutoff)
                unproven += basis == 'date_only_unproven'
                if keep:
                    out = {key: fact[key] for key in ('val', 'accn', 'form', 'filed', 'start', 'end', 'fp', 'fy', 'frame') if key in fact}
                    out.update(taxonomy=taxonomy, concept=concept, unit=unit, availability_basis=basis,
                               acceptance_at=accepted, source_url=_filing_url(identity['cik'], fact['accn']))
                    selected.append(out)
    selected.sort(key=lambda row: (row['filed'], row['end'], row['concept'], row['unit']), reverse=True)
    if len(selected) > limit:
        complete = False
        warnings.append('Fact record limit reached; refine since/concepts or raise limit.')
    if absent:
        warnings.append('Requested concepts absent: ' + ', '.join(absent) + '. Absence is not a zero value.')
    if unproven:
        complete = False
        warnings.append(f'{unproven} date-only facts omitted because filing availability within the timestamp window is unproven.')
    warnings.append('Facts retain reported periods and filing versions; do not sum overlapping periods or treat restatements as independently available earlier.')
    warnings.append('Selected standard taxonomy concepts may omit issuer-specific disclosures; inspect the original filing.')
    return {'provider': 'sec', 'resource': 'facts', 'complete': complete, 'warnings': warnings,
            'query': {'cik': identity['cik'], 'taxonomy': taxonomy, 'concepts': concepts,
                      'since': since.isoformat() if since else None, 'as_of': cutoff.isoformat(), 'forms': sorted(forms)},
            'data': {'company': identity, 'missing_concepts': absent, 'facts': selected[:limit]}}


def _directory(text, filename):
    if not isinstance(text, str):
        _bad('Nasdaq directory response is not text.')
    lines = text.lstrip('\ufeff').splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if len(lines) < 2:
        _bad('Nasdaq directory is missing its header or creation footer.')
    footer = re.fullmatch(r'File Creation Time: (\d{10}:\d{2})(?:\|)*', lines[-1].strip())
    if not footer:
        _bad('Nasdaq directory creation footer is missing or invalid; response may be truncated.')
    try:
        created = datetime.strptime(footer[1], '%m%d%Y%H:%M').isoformat()
    except ValueError:
        _bad('Nasdaq directory creation timestamp is invalid.')
    reader = csv.reader(io.StringIO('\n'.join(lines[:-1])), delimiter='|')
    fields = next(reader)
    symbol_field = 'Symbol' if filename == 'nasdaqlisted.txt' else 'ACT Symbol'
    required = {symbol_field, 'Security Name', 'ETF', 'Test Issue', 'Round Lot Size'}
    required.add('Market Category' if filename == 'nasdaqlisted.txt' else 'Exchange')
    if not required <= set(fields) or len(set(fields)) != len(fields):
        _bad('Nasdaq directory required columns are missing or repeated.')
    records, seen = [], set()
    for values in reader:
        if len(values) != len(fields):
            _bad('Nasdaq directory row has the wrong column count.')
        row = dict(zip(fields, values))
        symbol = row[symbol_field].strip()
        if not symbol or symbol in seen:
            _bad('Nasdaq directory has an empty or repeated symbol.')
        seen.add(symbol)
        if row['ETF'] not in ('Y', 'N') or row['Test Issue'] not in ('Y', 'N'):
            _bad('Nasdaq directory ETF/test flags are invalid.')
        name = _str(row['Security Name'])
        records.append({'symbol': symbol, 'security_name': name, 'etf': row['ETF'] == 'Y',
                        'test_issue': row['Test Issue'] == 'Y', 'security_type': 'unverified',
                        'directory': filename, 'source_fields': row})
        if len(records) > MAX_RECORDS:
            _bad('Nasdaq directory exceeds the record bound.')
    if not records:
        _bad('Nasdaq directory has no security rows.')
    return records, {'file': filename, 'creation_time_local': created,
                     'creation_time_raw': footer[1], 'timezone': 'not specified in file'}


def nasdaq_symbols(client, args):
    """Read current directories without pretending ETF/test flags identify common stock."""
    symbols = set(_csv((getattr(args, 'symbols', None) or '').upper(), SYMBOL))
    limit = _int_arg(args, 'limit', 20000, MAX_RECORDS)
    records, files = [], []
    for filename in ('nasdaqlisted.txt', 'otherlisted.txt'):
        rows, info = _directory(client.get_text(SYMDIR + filename), filename)
        records.extend(rows)
        files.append(info)
    found = {r['symbol'] for r in records}
    selected = [r for r in records if not symbols or r['symbol'] in symbols]
    warnings = ['Current directory snapshot only; not a point-in-time universe or proof of liquidity.',
                'ETF and test flags are explicit; common shares, ADRs, preferreds, units and warrants require separate classification.']
    complete = len(selected) <= limit
    if not complete:
        warnings.append('Directory record limit reached; output is incomplete.')
    if symbols - found:
        complete = False
        warnings.append('Requested symbols absent from the current directories: ' + ', '.join(sorted(symbols - found)) + '.')
    return {'provider': 'nasdaq', 'resource': 'symbols', 'complete': complete, 'warnings': warnings,
            'query': {'symbols': sorted(symbols), 'scope': 'current_directory'},
            'data': {'files': files, 'securities': selected[:limit]}}


def _local_name(tag):
    return tag.rsplit('}', 1)[-1]


def _halt_stamp(day, clock):
    if not day or not clock:
        return None
    # Nasdaq's RSS can pad the seconds field before its fractional suffix.
    # Normalize only that observed format, preserving subsecond precision and
    # leaving the original field untouched in source_fields.
    match = re.fullmatch(r'(\d{2}:\d{2}:\d{2})(?:[ \t]*(\.\d{1,6}))?', clock)
    if match is None:
        _bad('Nasdaq halt timestamp is invalid.')
    clock = match[1] + (match[2] or '')
    try:
        parsed = datetime.strptime(day + ' ' + clock, '%m/%d/%Y %H:%M:%S.%f' if '.' in clock else '%m/%d/%Y %H:%M:%S')
        zoned = parsed.replace(tzinfo=_ny())
        if zoned.utcoffset() != parsed.replace(tzinfo=_ny(), fold=1).utcoffset() or zoned.astimezone(timezone.utc).astimezone(_ny()).replace(tzinfo=None) != parsed:
            _bad('Nasdaq halt timestamp is ambiguous or nonexistent in New York time.')
        return zoned.isoformat()
    except ValueError:
        _bad('Nasdaq halt timestamp is invalid.')


def _rss_item(node, row_number):
    """Normalize one row without losing source spellings or masking bad aliases."""
    def invalid(key, problem):
        # XML names and values are untrusted; diagnostics use only known labels.
        label = key if key in HALT_SOURCE_FIELDS + ('title', 'pubDate', 'link', 'description') else 'unrecognized field'
        _bad(f'Nasdaq RSS item {row_number}: {label} {problem}.')

    original = {}
    for child in node:
        key = _local_name(child.tag)
        if key in original:
            invalid(key, 'is duplicated')
        # RSS extensions can contain nested elements. Ignore that structure
        # only for namespaced fields we do not consume; halt fields and ordinary
        # RSS text fields must still be unambiguous scalar values.
        if len(child) and (key in HALT_SOURCE_FIELDS + ('title', 'pubDate', 'link', 'description')
                           or not child.tag.startswith('{')):
            invalid(key, 'must contain text only')
        original[key] = child.text or ''
    fields = {key: value.strip() for key, value in original.items()}
    for key in ('HaltDate', 'HaltTime', 'IssueSymbol', 'IssueName'):
        if key not in fields:
            invalid(key, 'is missing')
        if not fields[key]:
            invalid(key, 'is blank')
    # The live RSS uses Market. Accept the alternate Mkt spelling only after
    # validating every supplied alias; a blank or conflicting alias is an error.
    markets = [key for key in ('Market', 'Mkt') if key in fields]
    if not markets:
        invalid('Market', 'is missing (alternate Mkt is also absent)')
    for key in markets:
        if not fields[key]:
            invalid(key, 'is blank')
    if len(markets) == 2 and fields['Market'] != fields['Mkt']:
        invalid('Market', 'conflicts with Mkt')

    def stamp(day_key, clock_key):
        day, clock = fields.get(day_key), fields.get(clock_key)
        if clock and not day:
            invalid(clock_key, 'requires a nonblank ' + day_key)
        try:
            return _halt_stamp(day, clock)
        except DataError:
            invalid(clock_key, 'or ' + day_key + ' is invalid or ambiguous in New York time')

    halt_at = stamp('HaltDate', 'HaltTime')
    quote_at = stamp('ResumptionDate', 'ResumptionQuoteTime')
    trade_at = stamp('ResumptionDate', 'ResumptionTradeTime')
    url = fields.get('link') or None
    if url:
        try:
            parts = urlsplit(url)
        except ValueError:
            invalid('link', 'is not an ordinary web URL')
        if parts.scheme not in ('http', 'https') or not parts.netloc or parts.username or parts.password:
            invalid('link', 'is not an ordinary web URL')
    return {'symbol': fields['IssueSymbol'], 'security_name': fields['IssueName'],
            'market_code': fields[markets[0]],
            'halt_at': halt_at, 'scheduled_quote_resumption_at': quote_at,
            'scheduled_trade_resumption_at': trade_at,
            'reason_code': fields.get('ReasonCode') or None, 'source_url': url,
            'source_fields': {key: original[key] for key in HALT_SOURCE_FIELDS if key in original}}


def _rss(text):
    if not isinstance(text, str) or re.search(r'<!\s*(DOCTYPE|ENTITY)\b', text, re.I):
        _bad('Nasdaq RSS contains an unsupported declaration.')
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        _bad('Nasdaq RSS is malformed XML.')
    if _local_name(root.tag) != 'rss':
        _bad('Nasdaq RSS root is missing.')
    channels = [node for node in root if _local_name(node.tag) == 'channel']
    if len(channels) != 1:
        _bad('Nasdaq RSS channel is missing or duplicated.')
    channel = channels[0]
    records, declared, published = [], None, None
    for node in channel:
        tag = _local_name(node.tag)
        if tag == 'numItems':
            if declared is not None:
                _bad('Nasdaq RSS numItems is duplicated.')
            try:
                declared = int(node.text)
            except (TypeError, ValueError):
                _bad('Nasdaq RSS item count is invalid.')
        elif tag == 'pubDate':
            if published is not None:
                _bad('Nasdaq RSS pubDate is duplicated.')
            try:
                parsed = parsedate_to_datetime(node.text)
                if parsed.tzinfo is None:
                    _bad('Nasdaq RSS publication time lacks a timezone.')
                published = parsed.astimezone(timezone.utc).isoformat()
            except (TypeError, ValueError):
                _bad('Nasdaq RSS publication time is invalid.')
        elif tag == 'item':
            records.append(_rss_item(node, len(records) + 1))
            if len(records) > MAX_RECORDS:
                _bad('Nasdaq RSS exceeds the record bound.')
    if published is None:
        _bad('Nasdaq RSS feed publication timestamp is missing.')
    if declared is None or declared != len(records):
        _bad('Nasdaq RSS declared item count is missing or disagrees with parsed rows.')
    return records, published


def nasdaq_halts(client, args):
    """Fetch one official halt feed snapshot; no polling or linked-page requests."""
    now = utc_now()
    day = getattr(args, 'date', None)
    params = {'feed': 'tradehalts'}
    if day:
        parsed_day = parse_date(day)
        if parsed_day > now.astimezone(_ny()).date():
            raise DataError('invalid_input', 'Nasdaq halt date cannot be in the future in New York.')
        params['haltdate'] = parsed_day.strftime('%m%d%Y')
    cutoff = parse_time(args.as_of) if getattr(args, 'as_of', None) else None
    if cutoff and cutoff > now:
        raise DataError('invalid_input', 'Nasdaq as_of cannot be in the future.')
    symbols = set(_csv((getattr(args, 'symbols', None) or '').upper(), SYMBOL))
    limit = _int_arg(args, 'limit', 20000, MAX_RECORDS)
    rows, published = _rss(client.get_text(HALTS, params=params))
    if day and any(parse_time(row['halt_at']).astimezone(_ny()).date() != parsed_day for row in rows):
        _bad('Nasdaq returned a halt outside the explicitly requested halt date.')
    selected = [r for r in rows if (not symbols or r['symbol'] in symbols)
                and (not cutoff or parse_time(r['halt_at']) <= cutoff)]
    warnings = ['Feed is a current snapshot, not a historical record of what was known at an earlier cutoff.',
                'Without date, the current feed may include older halts; absence does not establish historical clearance or a complete inventory of unresolved halts.',
                'complete describes untruncated rows in the returned snapshot, not complete trading-status history.',
                'as_of filters halt occurrence only; reason codes and scheduled resumption times may reflect later updates.',
                'Scheduled resumption times do not prove that trading actually resumed. Do not poll this feed more than once per minute.']
    complete = len(selected) <= limit
    if not complete:
        warnings.append('Halt record limit reached; output is incomplete.')
    return {'provider': 'nasdaq', 'resource': 'halts', 'complete': complete, 'warnings': warnings,
            'query': {'halt_date': day, 'as_of': cutoff.isoformat() if cutoff else None,
                      'symbols': sorted(symbols), 'point_in_time': False},
            'data': {'feed_published_at': published, 'halts': selected[:limit]}}


def self_test():
    """Offline fixtures exercise adapters and failure boundaries, never public APIs."""
    import copy
    from unittest.mock import patch
    checks = 0

    def check(condition, label):
        nonlocal checks
        if not condition:
            raise AssertionError(label)
        checks += 1

    def fails(fn, label):
        nonlocal checks
        try:
            fn()
        except DataError:
            checks += 1
            return
        raise AssertionError(label)

    class Fake:
        def __init__(self, mapping, env=None):
            self.mapping = mapping
            self.env = {'SEC_USER_AGENT': 'Market research test test@example.invalid'} if env is None else env
            self.calls = []
        def get_json(self, url, params=None, headers=None):
            self.calls.append((url, params, headers))
            return copy.deepcopy(self.mapping[url])
        get_text = get_json

    args = SimpleNamespace(cik='1', symbol=None, as_of='2026-09-04T13:00:00Z', since=None, limit=1000,
                           forms=None, max_pages=10, taxonomy='us-gaap', concepts='Assets')
    recent = {'accessionNumber': ['0000000001-26-000001', '0000000001-26-000002', '0000000001-26-000003'],
              'filingDate': ['2026-09-03', '2026-09-04', '2026-09-04'], 'form': ['10-Q', '8-K', '8-K'],
              'acceptanceDateTime': ['2026-09-03T20:00:00Z', '2026-09-04T12:00:00Z', '2026-09-04T14:00:00Z']}
    submission = {'cik': '1', 'name': 'Fixture Co', 'tickers': ['FIX'], 'exchanges': ['Nasdaq'],
                  'filings': {'recent': recent, 'files': []}}
    base = SUBMISSIONS + 'CIK0000000001.json'
    result = sec_company(Fake({base: submission}), args)
    check(len(result['data']['filings']) == 2 and result['complete'], 'filings cutoff')
    check('/000000000126000002/' in result['data']['filings'][0]['source_url'], 'verified filing link')
    missing_time = copy.deepcopy(submission)
    del missing_time['filings']['recent']['acceptanceDateTime']
    result = sec_company(Fake({base: missing_time}), args)
    check(len(result['data']['filings']) == 1 and not result['complete'], 'same-day date-only withheld')
    bad = copy.deepcopy(submission)
    bad['filings']['recent']['form'].pop()
    fails(lambda: sec_company(Fake({base: bad}), args), 'misaligned columns')
    fails(lambda: sec_company(Fake({base: submission}, {}), args), 'SEC contact required')
    fails(lambda: sec_company(Fake({base: submission}, {'SEC_USER_AGENT': 'test'}), args), 'SEC descriptive contact required')
    symbol_args = copy.copy(args)
    symbol_args.cik, symbol_args.symbol = None, 'FIX'
    mapping = {'fields': ['cik', 'name', 'ticker', 'exchange'], 'data': [[1, 'Fixture', 'FIX', 'Nasdaq']]}
    result = sec_company(Fake({base: submission, TICKERS: mapping}), symbol_args)
    check(result['data']['company']['cik'] == '0000000001', 'symbol to CIK')
    mapping['data'].append([2, 'Other', 'FIX', 'NYSE'])
    fails(lambda: sec_company(Fake({base: submission, TICKERS: mapping}), symbol_args), 'ambiguous ticker')
    old = {'accessionNumber': ['0000000001-25-000001'], 'filingDate': ['2025-08-01'], 'form': ['10-K']}
    historic = copy.deepcopy(submission)
    historic['filings']['files'] = [{'name': 'CIK0000000001-submissions-001.json', 'filingFrom': '2025-01-01', 'filingTo': '2025-12-31'}]
    client = Fake({base: historic, SUBMISSIONS + 'CIK0000000001-submissions-001.json': old})
    sec_company(client, args)
    check(len(client.calls) == 1, 'recent mode avoids unnecessary history requests')
    history_args = copy.copy(args)
    history_args.since = '2025-01-01'
    check(len(sec_company(client, history_args)['data']['filings']) == 3, 'explicit history fetched')
    historic['filings']['files'][0]['name'] = '../external.json'
    fails(lambda: sec_company(Fake({base: historic}), history_args), 'history path rejection')
    facts = {'cik': 1, 'facts': {'us-gaap': {'Assets': {'units': {'USD': [
        {'val': 10, 'accn': recent['accessionNumber'][0], 'filed': '2026-09-03', 'end': '2026-06-30', 'form': '10-Q', 'fy': 2026, 'fp': 'Q2'},
        {'val': 11, 'accn': recent['accessionNumber'][1], 'filed': '2026-09-04', 'end': '2026-06-30', 'form': '8-K'},
        {'val': 12, 'accn': recent['accessionNumber'][2], 'filed': '2026-09-04', 'end': '2026-06-30', 'form': '8-K'}]}}}}}
    fact_url = FACTS + 'CIK0000000001.json'
    result = sec_facts(Fake({base: submission, fact_url: facts}), args)
    check([r['val'] for r in result['data']['facts']] == [11, 10], 'facts cutoff and versions retained')
    check(result['data']['facts'][1]['unit'] == 'USD' and result['data']['facts'][1]['fp'] == 'Q2', 'original fact units and period retained')
    result = sec_facts(Fake({base: missing_time, fact_url: facts}), args)
    check(len(result['data']['facts']) == 1 and not result['complete'], 'facts same-day date-only withheld')
    # December 31 evening acceptance can be assigned January 2's filing date:
    # the earlier acceptance does not establish dissemination before the holiday.
    delayed_accession = '0000000001-25-000010'
    delayed = copy.deepcopy(submission)
    delayed['filings']['recent'] = {
        'accessionNumber': [delayed_accession], 'filingDate': ['2026-01-02'],
        'form': ['10-K'], 'acceptanceDateTime': ['2025-12-31T23:00:00Z']}
    delayed_facts = {'cik': 1, 'facts': {'us-gaap': {'Assets': {'units': {'USD': [
        {'val': 20, 'accn': delayed_accession, 'filed': '2026-01-02',
         'end': '2025-09-30', 'form': '10-K'}]}}}}}
    for handler, field in ((sec_company, 'filings'), (sec_facts, 'facts')):
        for cutoff, since, count, complete in (
                ('2025-12-31T23:30:00Z', None, 0, True),
                ('2026-01-02T17:00:00Z', None, 0, False),
                ('2026-01-03T17:00:00Z', None, 1, True),
                ('2026-01-03T17:00:00Z', '2026-01-02', 1, True),
                ('2026-01-03T17:00:00Z', '2026-01-02T17:00:00Z', 0, False)):
            delayed_args = copy.copy(args)
            delayed_args.as_of, delayed_args.since = cutoff, since
            result = handler(Fake({base: delayed, fact_url: delayed_facts}), delayed_args)
            check(len(result['data'][field]) == count and result['complete'] == complete,
                  'delayed SEC filing uses assigned date rather than earlier acceptance')
            if count:
                check(result['data'][field][0]['availability_basis'] == 'prior_filing_date_only',
                      'delayed SEC filing availability basis is explicit')
    for handler in (sec_company, sec_facts):
        for identity_args in (args, symbol_args):
            for key, value in (('limit', 0), ('limit', MAX_RECORDS + 1),
                               ('max_pages', 0), ('max_pages', 51), ('forms', '8-K,?')):
                invalid_args = copy.copy(identity_args)
                setattr(invalid_args, key, value)
                client = Fake({base: submission, fact_url: facts, TICKERS: {
                    'fields': ['cik', 'name', 'ticker', 'exchange'],
                    'data': [[1, 'Fixture', 'FIX', 'Nasdaq']]}})
                fails(lambda: handler(client, invalid_args), 'invalid SEC selection rejected')
                check(not client.calls, 'invalid SEC selection makes no requests')
    facts['facts']['us-gaap']['Assets']['units']['USD'][0]['val'] = float('nan')
    fails(lambda: sec_facts(Fake({base: submission, fact_url: facts}), args), 'nonfinite fact rejected')
    nasdaq = 'Symbol|Security Name|Market Category|Test Issue|Round Lot Size|ETF\nFIX|Fixture Common Stock|Q|N|100|N\nFIXW|Fixture Warrant|Q|N|100|N\nFile Creation Time: 0904202621:31|||||\n'
    other = 'ACT Symbol|Security Name|Exchange|ETF|Round Lot Size|Test Issue\nETF|Fixture Fund|N|Y|100|N\nFile Creation Time: 0904202621:31|||||\n'
    directory_args = SimpleNamespace(symbols=None, limit=20000)
    directory_client = Fake({SYMDIR+'nasdaqlisted.txt': nasdaq, SYMDIR+'otherlisted.txt': other})
    result = nasdaq_symbols(directory_client, directory_args)
    check(len(result['data']['securities']) == 3 and result['complete'], 'both symbol directories')
    check(all(row['security_type'] == 'unverified' for row in result['data']['securities']), 'no fabricated common-only universe')
    check(result['data']['securities'][2]['etf'], 'ETF flag')
    fails(lambda: _directory(nasdaq.rsplit('File Creation', 1)[0], 'nasdaqlisted.txt'), 'missing footer')
    fails(lambda: _directory(nasdaq.replace('|N|100|N', '|Z|100|N'), 'nasdaqlisted.txt'), 'invalid flag')
    directory_args.limit = 1
    check(not nasdaq_symbols(directory_client, directory_args)['complete'], 'directory bound')
    # Synthetic identities with the namespace and Market spelling used by the
    # official public RSS; do not base this fixture on the HTML table's Mkt label.
    rss = '<rss version="2.0" xmlns:n="http://www.nasdaqtrader.com/"><channel><pubDate>Fri, 04 Sep 2026 13:00:00 GMT</pubDate><n:numItems>1</n:numItems><item><n:HaltDate>09/04/2026</n:HaltDate><n:HaltTime>08:00:00</n:HaltTime><n:IssueSymbol>FIX</n:IssueSymbol><n:IssueName>Fixture</n:IssueName><n:Market>NASDAQ</n:Market><n:ReasonCode>T1</n:ReasonCode><n:ResumptionDate>09/04/2026</n:ResumptionDate><n:ResumptionTradeTime>09:30:00</n:ResumptionTradeTime></item></channel></rss>'
    halt_args = SimpleNamespace(symbols=None, date='2026-09-04', as_of='2026-09-04T13:00:00Z', limit=20000)
    client = Fake({HALTS: rss})
    result = nasdaq_halts(client, halt_args)
    check(result['data']['halts'][0]['halt_at'] == '2026-09-04T08:00:00-04:00', 'ET halt timestamp')
    check(client.calls[0][1]['haltdate'] == '09042026', 'official historical halt parameter')
    check('scheduled_trade_resumption_at' in result['data']['halts'][0] and not result['query']['point_in_time'], 'scheduled not actual resumption')
    check(result['data']['halts'][0]['market_code'] == 'NASDAQ'
          and result['data']['halts'][0]['source_fields']['Market'] == 'NASDAQ'
          and 'Mkt' not in result['data']['halts'][0]['source_fields'], 'actual Nasdaq Market field retained')
    market_xml = '<n:Market>NASDAQ</n:Market>'
    legacy = _rss(rss.replace(market_xml, '<n:Mkt>Q</n:Mkt>'))[0][0]
    check(legacy['market_code'] == 'Q' and legacy['source_fields']['Mkt'] == 'Q'
          and 'Market' not in legacy['source_fields'], 'alternate Mkt retains its source spelling and value')
    matching_markets = market_xml + '<n:Mkt> NASDAQ </n:Mkt>'
    matching = _rss(rss.replace(market_xml, matching_markets))[0][0]
    check(matching['market_code'] == 'NASDAQ' and matching['source_fields']['Mkt'] == ' NASDAQ ',
          'matching aliases preserve original text without inventing a market-code mapping')

    def rss_fails(xml, key, problem, row=1):
        try:
            _rss(xml)
        except DataError as exc:
            check(exc.code == 'schema_error' and f'item {row}:' in str(exc)
                  and key in str(exc) and problem in str(exc)
                  and 'secret-provider-payload' not in str(exc), 'actionable safe RSS row and field error')
            return
        raise AssertionError('Malformed RSS row was accepted')

    rss_fails(rss.replace(market_xml, ''), 'Market', 'missing')
    for key, value in (('HaltDate', '09/04/2026'), ('HaltTime', '08:00:00'),
                       ('IssueSymbol', 'FIX'), ('IssueName', 'Fixture'), ('Market', 'NASDAQ')):
        field_xml = f'<n:{key}>{value}</n:{key}>'
        rss_fails(rss.replace(field_xml, ''), key, 'missing')
        rss_fails(rss.replace(field_xml, f'<n:{key}> \t </n:{key}>'), key, 'blank')
        rss_fails(rss.replace(field_xml, field_xml * 2), key, 'duplicated')
    rss_fails(rss.replace(market_xml, '<n:Mkt> </n:Mkt>'), 'Mkt', 'blank')
    rss_fails(rss.replace(market_xml, '<n:Mkt>Q</n:Mkt>' * 2), 'Mkt', 'duplicated')
    for aliases, key, problem in (
            (market_xml + '<n:Mkt>OTHER</n:Mkt>', 'Market', 'conflicts'),
            (market_xml + '<n:Mkt/>', 'Mkt', 'blank'),
            ('<n:Market/> <n:Mkt>NASDAQ</n:Mkt>', 'Market', 'blank'),
            ('<n:Market>NASDAQ<x/></n:Market>', 'Market', 'text only'),
            (market_xml + '<Market>NASDAQ</Market>', 'Market', 'duplicated')):
        rss_fails(rss.replace(market_xml, aliases), key, problem)
    rss_fails(rss.replace('>08:00:00<', '>secret-provider-payload<'), 'HaltTime', 'invalid')
    rss_fails(rss.replace('>09/04/2026</n:ResumptionDate>', '></n:ResumptionDate>'),
              'ResumptionTradeTime', 'requires')
    rss_fails(rss.replace('</item>', '<link>https://[invalid</link></item>'), 'link', 'ordinary web URL')
    unknown_duplicate = '<secret-provider-payload>hidden</secret-provider-payload>' * 2
    rss_fails(rss.replace('</item>', unknown_duplicate + '</item>'), 'unrecognized field', 'duplicated')
    item = rss.split('<item>', 1)[1].split('</item>', 1)[0]
    second_bad_row = rss.replace('>1</n:numItems>', '>2</n:numItems>').replace(
        '</channel>', '<item>' + item.replace(market_xml, '') + '</item></channel>')
    rss_fails(second_bad_row, 'Market', 'missing', row=2)
    empty_rss = rss.replace('<item>' + item + '</item>', '').replace('>1</n:numItems>', '>0</n:numItems>')
    check(_rss(empty_rss)[0] == [], 'declared empty feed is distinct from malformed rows')
    unresolved = rss.replace('09/04/2026</n:ResumptionDate>', '</n:ResumptionDate>').replace(
        '09:30:00</n:ResumptionTradeTime>', '</n:ResumptionTradeTime>')
    check(_rss(unresolved)[0][0]['scheduled_trade_resumption_at'] is None,
          'empty optional resumption fields remain valid without asserting resumption')
    padded_clock = '08:00:00                      .590'
    padded_rss = rss.replace('<n:HaltTime>08:00:00</n:HaltTime>', '<n:HaltTime>' + padded_clock + '</n:HaltTime>')
    padded = nasdaq_halts(Fake({HALTS: padded_rss}), halt_args)['data']['halts'][0]
    check(padded['halt_at'] == '2026-09-04T08:00:00.590000-04:00'
          and padded['source_fields']['HaltTime'] == padded_clock, 'padded fraction parsed without discarding raw clock')
    for bad_clock in ('08: 00:00', '08:00:00 .1234567', '08:00:00 .', '08:00:00 trailing'):
        fails(lambda: _halt_stamp('09/04/2026', bad_clock), 'malformed clock not normalized')
    wrong_day = rss.replace('<n:HaltDate>09/04/2026</n:HaltDate>', '<n:HaltDate>09/03/2026</n:HaltDate>')
    fails(lambda: nasdaq_halts(Fake({HALTS: wrong_day}), halt_args), 'historical halt date mismatch rejected')
    default_halt_args = copy.copy(halt_args)
    default_halt_args.date = None
    default_result = nasdaq_halts(Fake({HALTS: wrong_day}), default_halt_args)
    check(default_result['complete'] and len(default_result['data']['halts']) == 1
          and any('may include older halts' in warning for warning in default_result['warnings'])
          and any('not complete trading-status history' in warning for warning in default_result['warnings']),
          'default current feed retains older halts without claiming historical completeness')
    later_resume = rss.replace('<n:ResumptionDate>09/04/2026</n:ResumptionDate>',
                              '<n:ResumptionDate>09/08/2026</n:ResumptionDate>')
    check(nasdaq_halts(Fake({HALTS: later_resume}), halt_args)['complete'],
          'historical halt date does not restrict a later scheduled resumption')
    fails(lambda: _rss('<!DOCTYPE foo [<!ENTITY a "x">]>' + rss), 'DTD and entity rejected')
    fails(lambda: _rss(rss.replace('>1</n:numItems>', '>2</n:numItems>')), 'RSS count mismatch')
    fails(lambda: _rss(rss.replace('<n:numItems>1</n:numItems>', '<n:numItems>1</n:numItems>' * 2)), 'RSS duplicate count')
    fails(lambda: _rss(rss.replace('<pubDate>Fri, 04 Sep 2026 13:00:00 GMT</pubDate>',
                                  '<pubDate>Fri, 04 Sep 2026 13:00:00 GMT</pubDate>' * 2)), 'RSS duplicate publication time')
    fails(lambda: _rss('<html>blocked</html>'), 'HTML error not empty success')
    fails(lambda: _rss(rss.replace('<pubDate>Fri, 04 Sep 2026 13:00:00 GMT</pubDate>', '')), 'feed timestamp missing')
    fails(lambda: _rss(rss.replace('<pubDate>Fri, 04 Sep 2026 13:00:00 GMT</pubDate>', '<pubDate/>')), 'feed timestamp blank')
    fails(lambda: _halt_stamp('11/01/2026', '01:30:00'), 'DST fold rejected')
    fails(lambda: _halt_stamp('03/08/2026', '02:30:00'), 'DST gap rejected')
    future_client = Fake({})
    for handler in (sec_company, sec_facts):
        for key, value in (('as_of', '9999-12-30T00:00:00Z'),
                           ('since', '9999-12-30T00:00:00Z'), ('since', '9999-12-30')):
            future_args = copy.copy(args)
            future_args.cik, future_args.symbol = None, 'FIX'
            setattr(future_args, key, value)
            fails(lambda: handler(future_client, future_args), 'future SEC window rejected before identity lookup')
    check(not future_client.calls, 'future SEC queries make no requests')
    for key, value in (('as_of', '9999-12-30T00:00:00Z'), ('date', '9999-12-30')):
        future_args = copy.copy(halt_args)
        setattr(future_args, key, value)
        fails(lambda: nasdaq_halts(future_client, future_args), 'future Nasdaq query rejected')
    with patch(__name__ + '.utc_now', return_value=datetime(2026, 9, 5, 1, tzinfo=timezone.utc)):
        future_args = copy.copy(halt_args)
        future_args.date = '2026-09-05'
        fails(lambda: nasdaq_halts(future_client, future_args), 'Nasdaq date uses New York rather than UTC')
    check(not future_client.calls, 'future Nasdaq queries make no requests')
    check(validate_sec_credentials(client.env) == client.env['SEC_USER_AGENT'], 'offline SEC validator matches request header')
    print(f'{checks}/{checks} tests passed')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', action='store_true', help='Run offline adapter tests; no network access.')
    args = parser.parse_args()
    if args.test:
        return self_test()
    parser.print_help()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
