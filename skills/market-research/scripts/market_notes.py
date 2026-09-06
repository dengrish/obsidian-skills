#!/usr/bin/env python3
"""Inventory, validate and exclusively publish daily market research notes.

Stdlib only; this helper does not fetch prices, infer market holidays or trade.
The caller verifies the evidence, session calendar and investment reasoning.
All commands print JSON. Exit 2 means invalid/incomplete input; exit 3 means
publication failed and any named recovery directory must be preserved.
Publication briefly pins the process working directory and restores it even
on failure; invoke this single-threaded CLI, not publish() from parallel threads.
"""

from __future__ import annotations

import argparse
import calendar
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_OBSIDIAN_SHARED_MODULES = ('atomic_move', 'vault_artifacts')

# --- obsidian shared-layer bootstrap (canonical; see shared/CONVENTIONS.md) ---
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
from vault_artifacts import portable_identity

MAX_BYTES = 256 * 1024
FIELDS = ('market_research', 'date', 'as_of', 'generated_at', 'session', 'coverage')
HEADINGS = ('Decision brief', 'Research record')
SUBHEADINGS = {
    'Decision brief': ('Buying opportunities', 'Next checks'),
    'Research record': ('Screening and sources', 'Candidate assessments', 'Thesis updates', 'Outcome review'),
}
ATX = re.compile(r' {0,3}(#{1,6})(?:[ \t]+(.*)|[ \t]*)$')
DAILY = re.compile(r'(\d{4}-\d{2}-\d{2})-market-research\.md\Z')
THESIS = re.compile(r'([A-Z][A-Z0-9]{1,15}:[A-Z][A-Z0-9.-]{0,14})@(\d{4}-\d{2}-\d{2})\Z')
STATES = {'watch', 'ready', 'invalidated', 'expired'}
ACTIVE = {'watch', 'ready'}
HORIZONS = ('2w', '1m', '3m', '6m', '12m', '24m', '60m')
JOURNALS = {
    'Recommendation records': ('Recommendation', 'First ready', 'Baseline at', 'Record', 'Replaces'),
    'Checkpoint records': ('Recommendation', 'Horizon', 'State', 'Observed at', 'Record', 'Replaces'),
    'Lesson records': ('Lesson', 'Status', 'Record'),
    'Monthly summaries': ('Month', 'Record'),
}


def ny_now(now=None):
    """Use actual New York civil time, including daylight-saving transitions."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError('current time must include an offset')
    try:
        zone = ZoneInfo('America/New_York')
    except ZoneInfoNotFoundError as exc:
        raise ValueError('system IANA timezone data for America/New_York is required; '
                         'install or restore the operating system timezone database '
                         'before running market research') from exc
    return current.astimezone(zone)


def scheduled_cutoff(current):
    """The daily 08:30 Pacific run uses an 11:30 New York evidence cutoff."""
    return datetime.combine(current.date(), time(11, 30), current.tzinfo)


def iso_date(value):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('date must be YYYY-MM-DD')
    return date.fromisoformat(value)


def iso_time(value):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})', value):
        raise ValueError('timestamps must include ISO8601 seconds and an explicit offset')
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def read_stable(path):
    """Bind bounded UTF-8 bytes to the shared identity/content snapshot."""
    before = os.lstat(path)
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
        raise ValueError('note must be a regular non-symlink file of at most %d bytes: %s' % (MAX_BYTES, path))
    expected = atomic_move.regular_file_snapshot(path)
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    with os.fdopen(os.open(path, flags), 'rb') as handle:
        opened = os.fstat(handle.fileno())
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError('note became a non-regular file: %s' % path)
        data = handle.read(MAX_BYTES + 1)
        identity = (opened.st_dev, opened.st_ino, stat.S_IFMT(opened.st_mode))
    if (len(data) > MAX_BYTES or identity != expected.identity
            or len(data) != expected.size
            or hashlib.sha256(data).hexdigest() != expected.digest
            or atomic_move.regular_file_snapshot(path) != expected):
        raise ValueError('note changed or exceeded the size limit while reading: %s' % path)
    data.decode('utf-8')
    return data, expected


def table_cells(line, count=3):
    """Parse a fixed-width ledger, respecting escaped GFM pipes."""
    if line != line.lstrip():
        raise ValueError('thesis table rows must not be indented or rendered as code')
    line = line.strip()
    if not (line.startswith('|') and line.endswith('|')):
        raise ValueError('thesis table rows must have outer pipes')
    cells, start, backslashes = [], 1, 0
    for index, character in enumerate(line[1:], 1):
        if character == '|' and backslashes % 2 == 0:
            cells.append(line[start:index].strip())
            start = index + 1
        backslashes = backslashes + 1 if character == '\\' else 0
    if start != len(line) or len(cells) != count:
        raise ValueError('table must have exactly %d cells per row; escape literal pipes' % count)
    return cells


def note_sections(body_lines):
    """Validate the two-part outline and isolate the sole authoritative ledger."""
    headings = []
    reserved = set(HEADINGS).union(*(set(titles) for titles in SUBHEADINGS.values()))
    for index, line in enumerate(body_lines):
        if (index and body_lines[index - 1].strip()
                and re.fullmatch(r' {0,3}(?:=+|-+)[ \t]*', line)):
            raise ValueError('use ATX headings; separate a thematic break from preceding prose with a blank line')
        match = ATX.fullmatch(line)
        if match is None:
            continue
        level, title = len(match[1]), (match[2] or '').strip()
        if line != '#' * level + ' ' + title or re.search(r'[ \t]+#+$', title):
            raise ValueError('use canonical ATX headings without indentation or closing hashes')
        if level > 3 and title in reserved:
            raise ValueError('reserved section heading at the wrong level: ' + title)
        if title.casefold() in {name.casefold() for name in JOURNALS} and (level != 4 or title not in JOURNALS):
            raise ValueError('outcome journal headings must use the exact prescribed H4: ' + title)
        headings.append((index, level, title))
    if len([item for item in headings if item[1] == 1]) != 1:
        raise ValueError('expected exactly one dated Market research H1')
    parts = [(index, title) for index, level, title in headings if level == 2]
    if tuple(title for _, title in parts) != HEADINGS:
        raise ValueError('expected exactly two parts, in order: ' + ', '.join(HEADINGS))
    if any(line.strip() for line in body_lines[1:parts[0][0]]):
        raise ValueError('place opening prose in Decision brief')
    sections = {}
    for position, (start, part) in enumerate(parts):
        stop = parts[position + 1][0] if position + 1 < len(parts) else len(body_lines)
        children = [(index, title) for index, level, title in headings
                    if start < index < stop and level == 3]
        if tuple(title for _, title in children) != SUBHEADINGS[part]:
            raise ValueError(part + ' must contain these exact H3 subsections, in order: '
                             + ', '.join(SUBHEADINGS[part]))
        opening = body_lines[start + 1:children[0][0]]
        if ((part == 'Research record' and any(line.strip() for line in opening))
                or any(ATX.fullmatch(line) for line in opening)):
            raise ValueError('place research detail inside its named H3 subsection')
        for child_position, (index, title) in enumerate(children):
            end = children[child_position + 1][0] if child_position + 1 < len(children) else stop
            content = body_lines[index + 1:end]
            if not any(line.strip() and not ATX.fullmatch(line) for line in content):
                raise ValueError('empty subsection: ' + title)
            first = next(index for index, line in enumerate(content) if line.strip())
            last = len(content) - next(index for index, line in enumerate(reversed(content)) if line.strip())
            sections[title] = '\n'.join(content[first:last])
            if title != 'Outcome review' and any(
                    ATX.fullmatch(line) and (ATX.fullmatch(line)[2] or '').strip() in JOURNALS
                    for line in content):
                raise ValueError('outcome journals belong only in Research record / Outcome review')
            if title != 'Thesis updates' and any(
                    re.fullmatch(r'\|\s*Thesis\s*\|\s*State\s*\|\s*Update / next check\s*\|', line.strip())
                    for line in content):
                raise ValueError('the thesis ledger belongs only in Research record / Thesis updates')
    return sections


def journal_tables(section):
    """Optional journals are strict tables; detailed cards use other H4 titles."""
    lines, result = section.splitlines(), {}
    headings = [(index, len(match[1]), (match[2] or '').strip())
                for index, line in enumerate(lines) if (match := ATX.fullmatch(line))]
    for index, level, title in headings:
        if title not in JOURNALS:
            continue
        if title in result:
            raise ValueError('duplicate outcome journal: ' + title)
        stop = next((at for at, depth, _ in headings if at > index and depth <= level), len(lines))
        body_lines = lines[index + 1:stop]
        while body_lines and not body_lines[0].strip():
            body_lines = body_lines[1:]
        while body_lines and not body_lines[-1].strip():
            body_lines = body_lines[:-1]
        body = '\n'.join(body_lines)
        result[title] = []
        if body == 'No changes.':
            continue
        table, columns = body.splitlines(), JOURNALS[title]
        header = table_cells(table[0], len(columns)) if table else []
        old_months = title == 'Checkpoint records' and header == [
            'Recommendation', 'Months', 'State', 'Observed at', 'Record', 'Replaces']
        if (len(table) < 3 or (header != list(columns) and not old_months)
                or any(not re.fullmatch(r':?-{3,}:?', cell)
                       for cell in table_cells(table[1], len(columns)))):
            raise ValueError(title + ' must contain its exact table or No changes.')
        for line in table[2:]:
            cells = table_cells(line, len(columns))
            if not all(cells):
                raise ValueError('empty outcome journal cell: ' + title)
            if old_months:
                cells[1] += 'm'  # Normalize immutable month-only records in memory.
            result[title].append(dict(zip(columns, cells)))
    return result


def lint_bytes(data, expected_date=None):
    """Validate structure only, never the truth of financial claims or dates."""
    if len(data) > MAX_BYTES:
        raise ValueError('note exceeds %d bytes' % MAX_BYTES)
    lines = data.decode('utf-8').splitlines()
    if not lines or lines[0] != '---':
        raise ValueError('note must start with frontmatter')
    try:
        end = lines.index('---', 1)
    except ValueError as exc:
        raise ValueError('frontmatter is not closed') from exc
    pairs = [line.split(': ', 1) for line in lines[1:end]]
    if (any(len(pair) != 2 for pair in pairs)
            or tuple(pair[0] for pair in pairs) != FIELDS):
        raise ValueError('frontmatter must use these exact ordered fields: ' + ', '.join(FIELDS))
    meta = dict(pairs)
    if meta['market_research'] != '1':
        raise ValueError('unsupported market_research schema version')
    day = iso_date(meta['date'])
    if expected_date is not None and day.isoformat() != expected_date:
        raise ValueError('frontmatter date does not match the daily filename')
    for field in ('as_of', 'generated_at'):
        raw = meta[field]
        if len(raw) < 2 or raw[0] not in ('"', "'") or raw[-1] != raw[0]:
            raise ValueError(field + ' must be a quoted timestamp')
        meta[field] = raw[1:-1]
    as_of, generated = (iso_time(meta[field]) for field in ('as_of', 'generated_at'))
    if ny_now(as_of).date() != day or as_of > generated:
        raise ValueError('as_of must fall on the note date in New York and not exceed generated_at')
    if meta['session'] not in {'premarket', 'closed', 'intraday', 'after-hours', 'unknown'}:
        raise ValueError('invalid session')
    if meta['coverage'] not in {'normal', 'limited', 'unavailable'}:
        raise ValueError('invalid coverage')
    body = '\n'.join(lines[end + 1:]).strip()
    if '<!--' in body or re.search(r'^ {0,3}(?:`{3,}|~{3,})', body, re.M):
        raise ValueError('daily research notes must not hide state in comments or code fences')
    body_lines = body.splitlines()
    if not body_lines or body_lines[0] != '# Market research — ' + day.isoformat():
        raise ValueError('expected dated Market research H1')
    sections = note_sections(body_lines)
    ledger = sections['Thesis updates']
    rows = []
    if ledger != 'No active theses.':
        table = ledger.splitlines()
        if (len(table) < 3 or table_cells(table[0]) != ['Thesis', 'State', 'Update / next check']
                or any(not re.fullmatch(r':?-{3,}:?', cell) for cell in table_cells(table[1]))):
            raise ValueError('Thesis updates must contain the prescribed table or No active theses.')
        seen = set()
        for line in table[2:]:
            thesis_id, state, update = table_cells(line)
            match = THESIS.fullmatch(thesis_id)
            if not match or iso_date(match[2]) > day:
                raise ValueError('invalid or future thesis ID: ' + thesis_id)
            if thesis_id in seen or state not in STATES or not update:
                raise ValueError('duplicate thesis, invalid state or empty update: ' + thesis_id)
            seen.add(thesis_id)
            rows.append({'id': thesis_id, 'state': state, 'update': update})
    return {'metadata': meta, 'theses': rows, 'journals': journal_tables(sections['Outcome review'])}


def output_folder(vault, create=False):
    """Refuse symlink and portable-name folder owners without altering them."""
    vault = Path(vault).expanduser().resolve(strict=True)
    if not vault.is_dir():
        raise ValueError('vault is not a directory')
    owners = [item for item in vault.iterdir() if portable_identity(item.name) == 'investments']
    folder = vault / 'Investments'
    if owners and (len(owners) != 1 or owners[0].name != 'Investments'):
        raise ValueError('portable-equivalent Investments folder collision: ' + ', '.join(map(str, owners)))
    if not owners and create:
        folder.mkdir()  # Exclusive creation; a concurrent occupant is not adopted.
    if os.path.lexists(folder):
        item = folder.lstat()
        if not stat.S_ISDIR(item.st_mode):
            raise ValueError('Investments must be a real directory, not a symlink or other occupant')
        return vault, folder, (item.st_dev, item.st_ino)
    return vault, folder, None


def inventory(vault, day):
    """Keep omitted open theses open; expose every malformed daily-note owner."""
    vault, folder, folder_identity = output_folder(vault)
    result = {'complete': True, 'findings': [], 'prior_notes': [], 'other_notes': [],
              'current_note': {'path': str(folder / (day + '-market-research.md')), 'state': 'missing'},
              'thesis_history': [], 'active_theses': []}
    tokens, latest, terminal = {}, {}, set()
    paths = sorted(folder.iterdir(), key=lambda path: path.name) if folder_identity else []
    names = {}
    for path in paths:
        names.setdefault(portable_identity(path.name), []).append(path)
    for identity, owners in sorted(names.items()):
        match = DAILY.fullmatch(identity)
        if not match:
            result['other_notes'].extend(str(path) for path in owners if path.suffix.lower() == '.md')
            continue
        today = match[1] == day
        try:
            if len(owners) != 1 or owners[0].name != identity:
                raise ValueError('portable-equivalent or noncanonical daily-note owner')
            path = owners[0]
            data, token = read_stable(path)
            note = lint_bytes(data, match[1])
            tokens[str(path)] = token
            if today:
                result['current_note']['state'] = 'valid'
            if match[1] > day:
                continue
            revived = [row['id'] for row in note['theses']
                       if row['state'] in ACTIVE and row['id'] in terminal]
            if revived:
                raise ValueError('terminal theses require a new linked thesis ID, not revival: '
                                 + ', '.join(revived))
            terminal.update(row['id'] for row in note['theses'] if row['state'] not in ACTIVE)
            if today:
                continue
            result['prior_notes'].append(str(path))
            for row in note['theses']:
                record = dict(row, note=str(path))
                result['thesis_history'].append(record)
                latest[row['id']] = record
        except (ValueError, OSError, UnicodeError) as exc:
            result['complete'] = False
            result['findings'].append({'paths': list(map(str, owners)), 'error': str(exc)})
            if today:
                result['current_note']['state'] = 'blocked'
    result['active_theses'] = [row for _, row in sorted(latest.items()) if row['state'] in ACTIVE]
    if output_folder(vault)[2] != folder_identity:
        raise ValueError('Investments directory changed during inventory')
    return result, (folder_identity, tuple((str(path),) for path in paths), tokens)


def context(vault, now=None):
    current = ny_now(now)
    day = current.date().isoformat()
    scheduled = scheduled_cutoff(current)
    result, _ = inventory(vault, day)
    return dict(result, date=day, now=current.isoformat(),
                scheduled_cutoff=scheduled.isoformat(),
                as_of=min(current, scheduled).isoformat(),
                timing='early/manual' if current < scheduled else 'scheduled-cutoff',
                calendar='unverified; verify the exchange session and holiday calendar')


def month_target(day, months):
    """Calendar anniversaries clamp month ends; exchange sessions stay unverified."""
    year, month = divmod(day.year * 12 + day.month - 1 + months, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def horizon_target(day, horizon):
    """Two weeks means 14 civil dates, not 14 trading days or a fractional month."""
    if horizon not in HORIZONS:
        raise ValueError('checkpoint horizon must be one of ' + ', '.join(HORIZONS))
    return day + timedelta(days=14) if horizon == '2w' else month_target(day, int(horizon[:-1]))


def outcomes(vault, draft=None, now=None):
    """Rebuild the prospective journal without a mutable index or any writes."""
    current = ny_now(now)
    day = current.date().isoformat()
    history, snapshot = inventory(vault, day)
    findings, notes, draft_token = list(history['findings']), {}, None
    def finding(path, error):
        findings.append({'paths': [str(path)], 'error': str(error)})
    for path, token in snapshot[2].items():
        if Path(path).name[:10] > day:
            continue
        data, checked = read_stable(path)
        if checked != token:
            raise ValueError('daily-note history changed while reading outcomes')
        note = lint_bytes(data)
        if iso_time(note['metadata']['generated_at']) > current:
            finding(path, 'generated_at is in the future')
        notes[note['metadata']['date']] = (path, note, data)
    unpublished_draft = draft is not None and day not in notes
    if draft is not None:
        data, draft_token = read_stable(draft)
        note = lint_bytes(data, day)
        if iso_time(note['metadata']['generated_at']) > current:
            raise ValueError('draft generated_at is in the future')
        if day in notes and notes[day][2] != data:
            raise ValueError('today already has a different published note; draft overlay is only for unpublished content')
        notes[day] = (history['current_note']['path'], note, data)
    first, recommendations, checkpoints, lessons = {}, {}, {}, {}
    monthly = None
    for note_day, (path, note, _) in sorted(notes.items()):
        for row in note['theses']:
            if row['state'] == 'ready':
                first.setdefault(row['id'], {'id': row['id'], 'first_ready': note_day,
                                             'first_ready_note': path})

    def reference(raw, note_day):
        match = re.fullmatch(r'\[\[(?:Investments/)?(\d{4}-\d{2}-\d{2})-market-research'
                             r'(?:\.md)?(?:#([^\[\]|\\#\r\n]+))?\]\]', raw)
        if not match or match[1] not in notes or match[1] > note_day:
            raise ValueError('Record must link to a known, nonfuture dated market note or section: ' + raw)
        # Preserve all published note-wide links, including today's immutable
        # record and identical retries. Only a new draft can adopt this rule.
        if unpublished_draft and note_day == day and not match[2]:
            raise ValueError('new draft Record must include a specific section anchor: ' + raw)
        target, target_note, data = notes[match[1]]
        if match[2] and sum((heading[2] or '').strip() == match[2]
                           for line in data.decode('utf-8').splitlines()
                           if (heading := ATX.fullmatch(line))) != 1:
            raise ValueError('Record section must resolve to exactly one heading: ' + raw)
        return target, match[2], iso_time(target_note['metadata']['as_of'])

    def record_identity(item):
        return item['record_note'], item['record_section']

    def event_identity(value):
        return value if value in ('pending', 'unavailable', '-') else iso_time(value)

    def baseline_version(item):
        return record_identity(item), event_identity(item['baseline_at']), item['version_note']

    def correction(row, item, previous, changed, finalized, note_day):
        replaces = row['Replaces']
        if previous is None:
            if replaces != '-':
                raise ValueError('first journal record must use Replaces -')
        elif changed and finalized:
            if replaces != previous['record']:
                raise ValueError('changed finalized record must explicitly replace its previous Record link')
            # Earlier releases accepted same-card corrections. Keep their immutable
            # history readable; new rows must supply a distinct correction card.
            if note_day == day and record_identity(item) == record_identity(previous):
                raise ValueError('changed finalized record must link to a distinct new detail card')
        elif replaces not in ('-', previous['record']):
            raise ValueError('Replaces does not identify the previous Record link')

    for note_day, (path, note, _) in sorted(notes.items()):
        as_of = iso_time(note['metadata']['as_of'])
        for title, columns in JOURNALS.items():
            seen = set()
            for row in note['journals'].get(title, []):
                try:
                    key = (row[columns[0]], row.get('Horizon'))
                    if key in seen:
                        raise ValueError('duplicate journal key in ' + title + ': ' + str(key))
                    seen.add(key)
                    target, section, record_as_of = reference(row['Record'], note_day)
                    common = {'record': row['Record'], 'record_note': target,
                              'record_section': section, 'journal_note': path}
                    if title in ('Recommendation records', 'Checkpoint records'):
                        identifier = row['Recommendation']
                        if identifier not in first or first[identifier]['first_ready'] > note_day:
                            raise ValueError('recommendation has no actual ready state by this date: ' + identifier)
                    if title == 'Recommendation records':
                        if row['First ready'] != first[identifier]['first_ready']:
                            raise ValueError('First ready must match the earliest actual ready state: ' + identifier)
                        baseline = row['Baseline at']
                        if baseline not in ('pending', 'unavailable'):
                            stamp = iso_time(baseline)
                            if (ny_now(stamp).date() <= iso_date(row['First ready']) or stamp > as_of):
                                raise ValueError('baseline must follow First ready in New York and not exceed as_of')
                            first_note = notes[first[identifier]['first_ready']][1]
                            if stamp < iso_time(first_note['metadata']['generated_at']):
                                raise ValueError('baseline must not precede the first-ready note\'s generated_at')
                            if stamp > record_as_of:
                                raise ValueError('baseline must not exceed its Record note\'s as_of')
                        previous = recommendations.get(identifier)
                        item = dict(first[identifier], baseline_at=baseline, **common)
                        changed = previous is not None and (
                            event_identity(item['baseline_at']) != event_identity(previous['baseline_at'])
                            or record_identity(item) != record_identity(previous))
                        correction(row, item, previous, changed, previous is not None
                                   and previous['baseline_at'] not in ('pending', 'unavailable'), note_day)
                        item['version_note'] = path if previous is None or changed else previous['version_note']
                        recommendations[identifier] = item
                    elif title == 'Checkpoint records':
                        horizon = row['Horizon']
                        if horizon not in HORIZONS:
                            raise ValueError('checkpoint horizon must be one of ' + ', '.join(HORIZONS))
                        baseline = recommendations.get(identifier)
                        if baseline is None:
                            raise ValueError('checkpoint requires a recommendation record: ' + identifier)
                        baseline_time = baseline['baseline_at']
                        known = baseline_time not in ('pending', 'unavailable')
                        observed = row['Observed at']
                        if row['State'] == 'observed':
                            if not known:
                                raise ValueError('observed checkpoint requires a known baseline')
                            stamp = iso_time(observed)
                            target_day = horizon_target(ny_now(iso_time(baseline_time)).date(), horizon)
                            if stamp > as_of or ny_now(stamp).date() < target_day:
                                raise ValueError('checkpoint observation must be on/after its calendar target and not exceed as_of')
                            if stamp > record_as_of:
                                raise ValueError('checkpoint observation must not exceed its Record note\'s as_of')
                        elif row['State'] != 'unavailable' or observed != '-':
                            raise ValueError('checkpoint state must be observed with a timestamp or unavailable with -')
                        key = (identifier, horizon)
                        previous = checkpoints.get(key)
                        item = dict(recommendation=identifier, horizon=horizon, state=row['State'],
                                    observed_at=observed, baseline_record=baseline['record'],
                                    _baseline_version=baseline_version(baseline), **common)
                        changed = previous is not None and (
                            any(item[key] != previous[key] for key in ('state', '_baseline_version'))
                            or event_identity(item['observed_at']) != event_identity(previous['observed_at']))
                        changed = changed or (previous is not None
                                              and record_identity(item) != record_identity(previous))
                        finalized = previous is not None and (
                            previous['state'] == 'observed' or previous['_needs_card_recheck']
                            or previous['_baseline_version'] != item['_baseline_version'])
                        correction(row, item, previous, changed, finalized, note_day)
                        # Legacy same-card changes cannot make unchanged evidence current.
                        # Repeats retain this flag until an explicit distinct-card correction.
                        item['_needs_card_recheck'] = previous is not None and (
                            record_identity(item) == record_identity(previous)
                            and (previous['_needs_card_recheck'] or (changed and finalized)))
                        checkpoints[key] = item
                    elif title == 'Lesson records':
                        identifier = row['Lesson']
                        match = re.fullmatch(r'lesson-(\d{4}-\d{2}-\d{2})-(0[1-9]|[1-9]\d+)', identifier)
                        if (not match or iso_date(match[1]) > iso_date(note_day) or int(match[2]) < 1
                                or row['Status'] not in ('provisional', 'supported', 'retired')):
                            raise ValueError('invalid lesson ID or status: ' + identifier)
                        previous = lessons.get(identifier)
                        item = dict(id=identifier, status=row['Status'], **common)
                        if (previous is not None and item['status'] != previous['status']
                                and record_identity(item) == record_identity(previous)):
                            raise ValueError('changed lesson status must link to a distinct new detail card')
                        lessons[identifier] = item
                    else:
                        if row['Month'] != note_day[:7]:
                            raise ValueError('monthly summary Month must match the containing note month')
                        if Path(target).name[:7] != row['Month']:
                            raise ValueError('monthly summary Record must link to a note in its registered Month')
                        monthly = dict(month=row['Month'], **common)
                except (ValueError, OverflowError) as exc:
                    finding(path, str(exc))
    for identifier, ready in first.items():
        if identifier not in recommendations:
            finding(ready['first_ready_note'], 'ready recommendation is missing a Recommendation record: ' + identifier)
            recommendations[identifier] = dict(ready, baseline_at='pending', record=None,
                                               record_note=None, record_section=None,
                                               journal_note=None, version_note=None)
    planned, due = [], []
    for identifier, baseline in sorted(recommendations.items()):
        known = baseline['baseline_at'] not in ('pending', 'unavailable')
        for horizon in HORIZONS:
            prior = checkpoints.get((identifier, horizon))
            target = horizon_target(ny_now(iso_time(baseline['baseline_at'])).date(), horizon) if known else None
            stale = prior is not None and (prior['_baseline_version'] != baseline_version(baseline)
                                          or prior['_needs_card_recheck'])
            state = ('needs-recheck' if stale else prior['state'] if prior else
                     'needs-baseline' if target is None else 'due' if target <= current.date() else 'pending')
            item = dict({key: value for key, value in (prior or {}).items() if not key.startswith('_')},
                        recommendation=identifier, horizon=horizon, state=state,
                        target_date=target.isoformat() if target else None,
                        baseline_at=baseline['baseline_at'], current_baseline_record=baseline['record'])
            planned.append(item)
            if stale or (target is not None and target <= current.date() and state != 'observed'):
                due.append(item)
    if inventory(vault, day)[1] != snapshot:
        finding(history['current_note']['path'], 'daily-note history changed during outcome planning; rerun')
    if draft_token is not None and atomic_move.regular_file_snapshot(draft) != draft_token:
        finding(draft, 'draft changed during outcome planning; rerun')
    cutoff = notes[day][1]['metadata']['as_of'] if day in notes else min(
        current, scheduled_cutoff(current)).isoformat()
    return {'complete': not findings, 'findings': findings, 'date': day,
            'as_of': cutoff,
            'calendar': 'unverified; due targets require exchange-calendar and completed-session verification',
            'recommendations': [recommendations[key] for key in sorted(recommendations)],
            'due_baselines': [value for key, value in sorted(recommendations.items())
                              if value['baseline_at'] in ('pending', 'unavailable') and value['first_ready'] < day],
            'checkpoints': planned, 'due_checkpoints': due,
            'active_lessons': [value for key, value in sorted(lessons.items()) if value['status'] != 'retired'],
            'retired_lessons': [value for key, value in sorted(lessons.items()) if value['status'] == 'retired'],
            'latest_monthly_summary': monthly, 'monthly_review_due': monthly is None or monthly['month'] < day[:7]}


def publish_pinned(staged, target, stage_parent, folder_identity):
    """Pin the real output directory while the single-threaded CLI publishes.

    A renamed/replaced folder cannot redirect a basename resolved from this
    open working-directory descriptor. All stage paths remain absolute.
    """
    flags = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    folder_fd = os.open(target.parent, flags)
    previous_fd = None
    try:
        opened = os.fstat(folder_fd)
        if (not stat.S_ISDIR(opened.st_mode)
                or (opened.st_dev, opened.st_ino) != folder_identity):
            raise ValueError('Investments directory changed before publication')
        previous_fd = os.open('.', flags)
        os.fchdir(folder_fd)
        atomic_move.publish_new(staged, Path(target.name), atomic_move.regular_file_snapshot, stage_parent)
        return str(Path.cwd() / target.name)
    finally:
        if previous_fd is not None:
            os.fchdir(previous_fd)
            os.close(previous_fd)
        os.close(folder_fd)


def publish(draft, vault, now=None):
    data, expected = read_stable(draft)
    note = lint_bytes(data)
    current = ny_now(now)
    day = current.date().isoformat()
    if note['metadata']['date'] != day:
        raise ValueError('publication creates only today\'s New York note; no historical backfill')
    if iso_time(note['metadata']['generated_at']) > current:
        raise ValueError('generated_at is in the future')
    history, baseline = inventory(vault, day)
    target = Path(history['current_note']['path'])
    if not history['complete']:
        raise ValueError('daily-note history is incomplete: ' + json.dumps(history['findings'], ensure_ascii=False))
    if history['current_note']['state'] == 'valid':
        existing, _ = read_stable(target)
        if existing == data:
            planned = outcomes(vault, draft, current)
            if not planned['complete']:
                raise ValueError('outcome journal is incomplete: ' + json.dumps(planned['findings'], ensure_ascii=False))
            return {'status': 'unchanged', 'path': str(target)}
        raise ValueError('daily note already exists with different bytes; preserve and reuse it')
    present = {row['id'] for row in note['theses']}
    omitted = [row['id'] for row in history['active_theses'] if row['id'] not in present]
    if omitted:
        raise ValueError('carry active theses or explicitly invalidate/expire them: ' + ', '.join(omitted))
    latest = {row['id']: row['state'] for row in history['thesis_history']}
    revived = [row['id'] for row in note['theses'] if row['state'] in ACTIVE
               and latest.get(row['id']) in {'invalidated', 'expired'}]
    if revived:
        raise ValueError('terminal theses require a new linked thesis ID, not revival: ' + ', '.join(revived))
    planned = outcomes(vault, draft, current)
    if not planned['complete']:
        raise ValueError('outcome journal is incomplete: ' + json.dumps(planned['findings'], ensure_ascii=False))
    vault, folder, folder_identity = output_folder(vault, create=True)
    # Folder creation changes an absent-folder baseline, but does not adopt files.
    if baseline[0] is None:
        checked, baseline = inventory(vault, day)
        if not checked['complete'] or baseline[1]:
            raise ValueError('Investments was populated concurrently; rerun context')
    stage_dir = Path(tempfile.mkdtemp(prefix='.market-research-stage-', dir=vault))
    staged = stage_dir / target.name
    try:
        with staged.open('xb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if atomic_move.regular_file_snapshot(draft) != expected:
            raise ValueError('draft changed after validation')
        _, checked = inventory(vault, day)
        if checked != baseline or output_folder(vault)[2] != folder_identity:
            raise ValueError('daily-note history changed after planning; rerun context')
        actual = publish_pinned(staged, target, vault, folder_identity)
        try:
            stable_folder = output_folder(vault)[2] == folder_identity
        except (OSError, ValueError):
            stable_folder = False
        if not stable_folder:
            raise ValueError('Investments changed during publication; inspect the published note at ' + actual)
    except Exception as exc:
        raise RuntimeError('publication failed; preserve recovery stage %s: %s' % (stage_dir, exc)) from exc
    shutil.rmtree(stage_dir)
    return {'status': 'created', 'path': str(target)}


def run_self_test():
    """Adversarial temporary-vault tests; never accesses an account or network."""
    import unittest
    from unittest.mock import patch

    class Tests(unittest.TestCase):
        def setUp(self):
            self.temp = tempfile.TemporaryDirectory(prefix='.market-notes-test-')
            self.addCleanup(self.temp.cleanup)
            self.vault = Path(self.temp.name).resolve()
            self.now = datetime.fromisoformat('2026-09-05T09:03:00-04:00')
            self.draft = self.vault / 'draft.txt'

        def note(self, day='2026-09-05', rows=(), as_of=None, generated=None):
            ledger = ('| Thesis | State | Update / next check |\n| --- | --- | --- |\n'
                      + '\n'.join('| %s | %s | %s |' % row for row in rows)) if rows else 'No active theses.'
            return ('---\nmarket_research: 1\ndate: %s\nas_of: "%s"\ngenerated_at: "%s"\n'
                    'session: premarket\ncoverage: limited\n---\n\n# Market research — %s\n\n'
                    '## Decision brief\n\nWait for confirmation.\n\n'
                    '### Buying opportunities\n\nNo qualifying opportunity.\n\n'
                    '### Next checks\n\nVerify the next session.\n\n'
                    '## Research record\n\n### Screening and sources\n\nSynthetic fixture only.\n\n'
                    '### Candidate assessments\n\nNo candidate passed the fixture screen.\n\n'
                    '### Thesis updates\n\n%s\n\n### Outcome review\n\nNo observations are due.\n' %
                    (day, as_of or day + 'T09:00:00-04:00', generated or day + 'T09:02:00-04:00', day, ledger)).encode()

        def prior(self, day, rows):
            folder = self.vault / 'Investments'
            folder.mkdir(exist_ok=True)
            path = folder / (day + '-market-research.md')
            path.write_bytes(self.note(day, rows))
            return path

        def record_link(self, day):
            return '[[Investments/' + day + '-market-research#Outcome review]]'

        def journal(self, title, rows):
            columns = JOURNALS[title]
            return ('#### ' + title + '\n\n| ' + ' | '.join(columns) + ' |\n| '
                    + ' | '.join('---' for _ in columns) + ' |\n'
                    + '\n'.join('| ' + ' | '.join(row) + ' |' for row in rows) + '\n')

        def outcome_note(self, day, rows=(), journals=(), draft=False):
            data = self.note(day, rows) + ('\n' + '\n'.join(journals)).encode('utf-8')
            path = self.draft if draft else self.prior(day, rows)
            path.write_bytes(data)
            return path

        def baseline_fixture(self, first_day='2024-01-30', baseline_day='2024-01-31', record_day=None):
            record_day = record_day or baseline_day
            identifier = 'NYSE:ABC@' + first_day
            first_link, baseline_link = self.record_link(first_day), self.record_link(record_day)
            self.outcome_note(first_day, [(identifier, 'ready', 'Synthetic confirmed setup')], [
                self.journal('Recommendation records', [(identifier, first_day, 'pending', first_link, '-')])])
            self.outcome_note(record_day, [(identifier, 'watch', 'Synthetic follow-up')], [
                self.journal('Recommendation records', [(identifier, first_day, baseline_day + 'T09:30:00-05:00',
                                                         baseline_link, '-')])])
            # The fixture baseline session is observed in a later intraday review.
            path = self.vault / 'Investments' / (record_day + '-market-research.md')
            path.write_bytes(path.read_bytes().replace((record_day + 'T09:00:00-04:00').encode(),
                                                       (record_day + 'T16:00:00-05:00').encode())
                             .replace((record_day + 'T09:02:00-04:00').encode(),
                                      (record_day + 'T16:02:00-05:00').encode()))
            return identifier, first_link, baseline_link

        def test_clock_and_dst(self):
            for pacific, eastern, utc in (
                    ('2026-09-05T08:30:00-07:00', '2026-09-05T11:30:00-04:00', '2026-09-05T15:30:00+00:00'),
                    ('2026-12-01T08:30:00-08:00', '2026-12-01T11:30:00-05:00', '2026-12-01T16:30:00+00:00')):
                with self.subTest(pacific=pacific):
                    result = context(self.vault, datetime.fromisoformat(pacific))
                    self.assertEqual(result['scheduled_cutoff'], eastern)
                    self.assertEqual(result['now'], eastern)
                    self.assertEqual(result['as_of'], eastern)
                    self.assertEqual(iso_time(result['as_of']).astimezone(timezone.utc).isoformat(), utc)
            with self.assertRaises(ValueError):
                ny_now(datetime(2026, 9, 5))

        def test_early_exact_and_late_runs_agree_on_unsaved_note_cutoff(self):
            for pacific, eastern_now, cutoff, timing in (
                    ('2026-09-05T08:29:30-07:00', '11:29:30', '11:29:30', 'early/manual'),
                    ('2026-09-05T08:30:00-07:00', '11:30:00', '11:30:00', 'scheduled-cutoff'),
                    ('2026-09-05T10:15:22-07:00', '13:15:22', '11:30:00', 'scheduled-cutoff')):
                with self.subTest(pacific=pacific):
                    now = datetime.fromisoformat(pacific)
                    result = context(self.vault, now)
                    planned = outcomes(self.vault, now=now)
                    self.assertEqual(result['current_note']['state'], 'missing')
                    self.assertEqual(result['as_of'], '2026-09-05T' + cutoff + '-04:00')
                    self.assertEqual(result['now'], '2026-09-05T' + eastern_now + '-04:00')
                    self.assertEqual(result['timing'], timing)
                    self.assertTrue(planned['complete'])
                    self.assertEqual(planned['as_of'], result['as_of'])
            self.assertFalse((self.vault / 'Investments').exists())

        def test_note_date_uses_new_york_before_pacific_midnight(self):
            now = datetime.fromisoformat('2026-09-05T23:50:00-07:00')
            result = context(self.vault, now)
            self.assertEqual(result['date'], '2026-09-06')
            self.assertEqual(result['now'], '2026-09-06T02:50:00-04:00')
            self.assertEqual(result['scheduled_cutoff'], '2026-09-06T11:30:00-04:00')
            self.assertEqual(result['as_of'], result['now'])
            planned = outcomes(self.vault, now=now)
            self.assertEqual(planned['date'], result['date'])
            self.assertEqual(planned['as_of'], result['as_of'])

        def test_saved_nine_oclock_note_keeps_its_original_cutoff_and_bytes(self):
            path = self.prior('2026-09-05', [])
            original = path.read_bytes()
            late = datetime.fromisoformat('2026-09-05T10:15:22-07:00')
            self.assertEqual(context(self.vault, late)['current_note']['state'], 'valid')
            for draft in (None, path):
                with self.subTest(draft=draft):
                    planned = outcomes(self.vault, draft=draft, now=late)
                    self.assertTrue(planned['complete'])
                    self.assertEqual(planned['as_of'], '2026-09-05T09:00:00-04:00')
            self.assertEqual(publish(path, self.vault, late)['status'], 'unchanged')
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(lint_bytes(original)['metadata']['generated_at'], '2026-09-05T09:02:00-04:00')

        def test_missing_timezone_reports_json_error(self):
            import io
            from contextlib import redirect_stdout
            from unittest.mock import Mock
            output = io.StringIO()
            missing = Mock(side_effect=ZoneInfoNotFoundError('America/New_York'))
            with patch.dict(globals(), {'ZoneInfo': missing}), redirect_stdout(output):
                status = main(['context', '--vault', str(self.vault)])
            self.assertEqual(status, 2)
            self.assertIn('system IANA timezone data', json.loads(output.getvalue())['error'])
            self.assertFalse((self.vault / 'Investments').exists())

        def test_timestamp_failures(self):
            for timestamp in ('2026-09-05T09:00:00', '2026-09-06T09:00:00-04:00',
                              '2026-09-05T09:03:00-04:00', '2026-09-05T00:30:00+04:00'):
                with self.subTest(timestamp=timestamp), self.assertRaises(ValueError):
                    lint_bytes(self.note(as_of=timestamp))
            lint_bytes(self.note(as_of='2026-09-05T12:00:00-04:00', generated='2026-09-05T12:02:00-04:00'))

        def test_schema_and_sections(self):
            source = self.note()
            for data in (source.replace(b'coverage:', b'unknown:'),
                         source.replace(b'## Research record', b'## Something else'),
                         source.replace(b'No qualifying opportunity.', b''),
                         source.replace(b'No active theses.', b'<!-- No active theses. -->'),
                         source.replace(b'### Next checks', b'  ### Next checks'),
                         source.replace(b'### Next checks', b'### Next checks ###'),
                         source.replace(b'Wait for confirmation.', b'Another part\n---'),
                         source.replace(b'### Outcome review', b'# Second title')):
                with self.subTest(data=data), self.assertRaises(ValueError):
                    lint_bytes(data)

        def test_required_subsections_cannot_be_missing(self):
            for titles in SUBHEADINGS.values():
                for title in titles:
                    with self.subTest(title=title), self.assertRaisesRegex(ValueError, 'exact H3 subsections'):
                        lint_bytes(self.note().replace(('### ' + title).encode('utf-8'), title.encode('utf-8')))

        def test_required_subsections_cannot_be_reordered(self):
            source = self.note()
            for first, second in (('Buying opportunities', 'Next checks'),
                                  ('Screening and sources', 'Candidate assessments'),
                                  ('Thesis updates', 'Outcome review')):
                data = source.replace(('### ' + first).encode('utf-8'), b'### TEMP')
                data = data.replace(('### ' + second).encode('utf-8'), ('### ' + first).encode('utf-8'))
                data = data.replace(b'### TEMP', ('### ' + second).encode('utf-8'))
                with self.subTest(first=first), self.assertRaisesRegex(ValueError, 'exact H3 subsections'):
                    lint_bytes(data)

        def test_duplicate_and_misplaced_subsections(self):
            source = self.note()
            for data in (source + b'\n### Thesis updates\n\nNo active theses.\n',
                         source.replace(b'## Research record', b'### Thesis updates\n\nNo active theses.\n\n## Research record'),
                         source.replace(b'### Candidate assessments', b'#### Thesis updates\n\nNo active theses.\n\n### Candidate assessments'),
                         source.replace(b'## Research record\n\n', b'## Research record\n\nUnfiled evidence.\n\n'),
                         source.replace(b'No active theses.', b'#### State\n\nNo active theses.'),
                         source.replace(b'No active theses.', b'No active theses.\n\nExtra ledger prose.')):
                with self.subTest(data=data), self.assertRaises(ValueError):
                    lint_bytes(data)

        def test_optional_brief_opening_and_candidate_subheadings(self):
            source = self.note().replace(b'Wait for confirmation.\n\n', b'')
            source = source.replace(b'No candidate passed the fixture screen.',
                                    '#### Synthetic candidate\n\nSource evidence retains café and $x = 1$.\n\n'
                                    '##### Contrary evidence\n\nThis is a test, not a recommendation.'.encode('utf-8'))
            self.assertEqual(lint_bytes(source)['theses'], [])
            with self.assertRaisesRegex(ValueError, 'empty subsection'):
                lint_bytes(self.note().replace(b'No qualifying opportunity.', b'#### Only a heading'))

        def test_ledger_cannot_be_code_or_duplicated_elsewhere(self):
            source = self.note(rows=[('NYSE:ABC@2026-09-04', 'watch', 'Synthetic fixture')])
            duplicate = (b'| Thesis | State | Update / next check |\n| --- | --- | --- |\n'
                         b'| NYSE:ABC@2026-09-04 | ready | Conflicting fixture |')
            for data in (self.note().replace(b'No active theses.', b'    No active theses.'),
                         source.replace(b'| Thesis |', b'    | Thesis |'),
                         source.replace(b'| NYSE:ABC@2026-09-04', b'    | NYSE:ABC@2026-09-04'),
                         source.replace(b'No qualifying opportunity.', duplicate),
                         source.replace(b'No candidate passed the fixture screen.', duplicate)):
                with self.subTest(data=data), self.assertRaises(ValueError):
                    lint_bytes(data)

        def test_table(self):
            good = [('NASDAQ:ABC@2026-09-04', 'watch', r'Keep [[Investments/earlier\|prior]]; verify $x\|y$.')]
            self.assertEqual(lint_bytes(self.note(rows=good))['theses'][0]['state'], 'watch')
            for rows in (good + good, [('NASDAQ:ABC@2026-09-06', 'watch', 'Future')],
                         [('ABC', 'watch', 'No exchange')], [('NYSE:A@2026-09-04', 'done', 'Bad state')],
                         [('NYSE:A@2026-09-04', 'ready', 'Unescaped | pipe')]):
                with self.subTest(rows=rows), self.assertRaises(ValueError):
                    lint_bytes(self.note(rows=rows))

        def test_creation_idempotence_and_refusal(self):
            self.draft.write_bytes(self.note())
            result = publish(self.draft, self.vault, self.now)
            self.assertEqual(result['status'], 'created')
            self.assertEqual(Path(result['path']).read_bytes(), self.note())
            self.assertEqual(publish(self.draft, self.vault, self.now)['status'], 'unchanged')
            self.draft.write_bytes(self.note().replace(b'Wait for confirmation.', b'Still wait.'))
            with self.assertRaises(ValueError):
                publish(self.draft, self.vault, self.now)
            self.assertFalse(list(self.vault.glob('.market-research-stage-*')))

        def test_identical_retry_still_validates_history_and_outcomes(self):
            identifier = 'NYSE:ABC@2026-09-05'
            for broken in ('current recommendation', 'prior recommendation', 'prior structure'):
                with self.subTest(broken=broken):
                    folder = self.vault / 'Investments'
                    if folder.exists():
                        shutil.rmtree(folder)
                    current = self.prior('2026-09-05', [(identifier, 'ready', 'Missing record')]
                                         if broken == 'current recommendation' else [])
                    if broken != 'current recommendation':
                        prior = self.prior('2026-09-04', [('NYSE:ABC@2026-09-04', 'ready', 'Missing record')])
                        if broken == 'prior structure':
                            prior.write_text('Preserve this malformed history.', encoding='utf-8')
                    before = {path.name: path.read_bytes() for path in folder.iterdir()}
                    self.draft.write_bytes(current.read_bytes())
                    with self.assertRaisesRegex(ValueError, 'history is incomplete|outcome journal is incomplete'):
                        publish(self.draft, self.vault, self.now)
                    self.assertEqual({path.name: path.read_bytes() for path in folder.iterdir()}, before)
                    self.assertFalse(list(self.vault.glob('.market-research-stage-*')))

        def test_no_backfill_or_future_generation(self):
            for data in (self.note('2026-09-04'), self.note(generated='2026-09-05T09:04:00-04:00')):
                self.draft.write_bytes(data)
                with self.subTest(data=data), self.assertRaises(ValueError):
                    publish(self.draft, self.vault, self.now)

        def test_continuity_and_terminal_rows(self):
            thesis = 'NYSE:ABC@2026-09-02'
            self.prior('2026-09-02', [(thesis, 'watch', 'Original thesis')])
            self.prior('2026-09-03', [])  # An omission cannot silently close it.
            state = context(self.vault, self.now)
            self.assertEqual([row['id'] for row in state['active_theses']], [thesis])
            self.draft.write_bytes(self.note())
            with self.assertRaisesRegex(ValueError, 'carry active'):
                publish(self.draft, self.vault, self.now)
            self.draft.write_bytes(self.note(rows=[(thesis, 'invalidated', 'Catalyst failed')]))
            publish(self.draft, self.vault, self.now)
            later = context(self.vault, datetime.fromisoformat('2026-09-06T09:00:00-04:00'))
            self.assertEqual(later['active_theses'], [])
            self.assertEqual(len(later['thesis_history']), 2)

        def test_terminal_id_cannot_be_revived(self):
            thesis = 'NYSE:ABC@2026-09-02'
            self.prior('2026-09-02', [(thesis, 'watch', 'Original thesis')])
            self.prior('2026-09-03', [(thesis, 'expired', 'Window closed')])
            self.draft.write_bytes(self.note(rows=[(thesis, 'ready', 'Do not erase expiry')]))
            with self.assertRaisesRegex(ValueError, 'not revival'):
                publish(self.draft, self.vault, self.now)

        def test_historical_terminal_revival_blocks_publication_and_identical_retry(self):
            identifier = 'NYSE:ABC@2026-09-01'
            for revival_day in ('2026-09-03', '2026-09-05'):
                with self.subTest(revival_day=revival_day):
                    folder = self.vault / 'Investments'
                    if folder.exists():
                        shutil.rmtree(folder)
                    self.prior('2026-09-01', [(identifier, 'watch', 'Original thesis')])
                    self.prior('2026-09-02', [(identifier, 'expired', 'Terminal thesis')])
                    revived = self.prior(revival_day, [(identifier, 'watch', 'Invalid revival')])
                    before = {path.name: path.read_bytes() for path in folder.iterdir()}
                    self.draft.write_bytes(revived.read_bytes() if revival_day == '2026-09-05'
                                           else self.note(rows=[(identifier, 'watch', 'Carry revival')]))
                    history = context(self.vault, self.now)
                    self.assertFalse(history['complete'])
                    self.assertTrue(any('not revival' in row['error'] for row in history['findings']))
                    self.assertEqual(history['active_theses'], [])
                    self.assertFalse(outcomes(self.vault, now=self.now)['complete'])
                    with self.assertRaisesRegex(ValueError, 'history is incomplete'):
                        publish(self.draft, self.vault, self.now)
                    self.assertEqual({path.name: path.read_bytes() for path in folder.iterdir()}, before)
                    self.assertFalse(list(self.vault.glob('.market-research-stage-*')))

        def test_history_rechecked_before_publication(self):
            self.prior('2026-09-03', [])
            self.draft.write_bytes(self.note())
            original, calls = inventory, 0
            def changed(vault, day):
                nonlocal calls
                calls += 1
                if calls == 2:
                    self.prior('2026-09-04', [('NYSE:ABC@2026-09-04', 'watch', 'Concurrent thesis')])
                return original(vault, day)
            with patch.dict(globals(), {'inventory': changed}):
                with self.assertRaisesRegex(RuntimeError, 'history changed'):
                    publish(self.draft, self.vault, self.now)
            self.assertFalse((self.vault / 'Investments/2026-09-05-market-research.md').exists())
            self.assertEqual(len(list(self.vault.glob('.market-research-stage-*'))), 1)

        def test_malformed_history_and_foreign_notes(self):
            bad = self.prior('2026-09-04', [])
            bad.write_text('ordinary foreign content', encoding='utf-8')
            other = bad.parent / 'My watchlist.md'
            other.write_text('User note', encoding='utf-8')
            state = context(self.vault, self.now)
            self.assertFalse(state['complete'])
            self.assertEqual(state['other_notes'], [str(other)])
            self.draft.write_bytes(self.note())
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                publish(self.draft, self.vault, self.now)
            self.assertEqual(other.read_text(encoding='utf-8'), 'User note')

        def test_noncanonical_filename_collision(self):
            folder = self.vault / 'Investments'
            folder.mkdir()
            occupant = folder / '2026-09-05-MARKET-RESEARCH.md'
            occupant.write_bytes(self.note())
            state = context(self.vault, self.now)
            self.assertFalse(state['complete'])
            self.assertEqual(state['current_note']['state'], 'blocked')
            self.draft.write_bytes(self.note())
            with self.assertRaises(ValueError):
                publish(self.draft, self.vault, self.now)

        def test_folder_owners(self):
            folder = self.vault / 'Investments'
            folder.symlink_to(self.vault, target_is_directory=True)
            with self.assertRaises(ValueError):
                context(self.vault, self.now)
            folder.unlink()
            folder.write_text('keep', encoding='utf-8')
            with self.assertRaises(ValueError):
                context(self.vault, self.now)
            folder.unlink()
            (self.vault / 'investments').mkdir()
            with self.assertRaises(ValueError):
                context(self.vault, self.now)

        def test_symlink_directory_and_oversize_note_owners(self):
            self.draft.write_bytes(self.note())
            folder = self.vault / 'Investments'
            folder.mkdir()
            target = folder / '2026-09-05-market-research.md'
            target.symlink_to(self.vault / 'absent')
            self.assertFalse(context(self.vault, self.now)['complete'])
            target.unlink()
            target.mkdir()
            self.assertFalse(context(self.vault, self.now)['complete'])
            target.rmdir()
            target.write_bytes(b'x' * (MAX_BYTES + 1))
            self.assertFalse(context(self.vault, self.now)['complete'])
            self.draft.unlink()
            self.draft.symlink_to(target)
            with self.assertRaises(ValueError):
                publish(self.draft, self.vault, self.now)

        def test_publication_failure_retains_stage_and_competitor(self):
            self.draft.write_bytes(self.note())
            def conflict(staged, target, snapshot, stage_parent):
                target.write_text('competing writer', encoding='utf-8')
                raise FileExistsError(str(target))
            with patch.object(atomic_move, 'publish_new', side_effect=conflict):
                with self.assertRaisesRegex(RuntimeError, 'preserve recovery stage'):
                    publish(self.draft, self.vault, self.now)
            stages = list(self.vault.glob('.market-research-stage-*'))
            self.assertEqual(len(stages), 1)
            self.assertEqual((stages[0] / '2026-09-05-market-research.md').read_bytes(), self.note())
            self.assertEqual((self.vault / 'Investments/2026-09-05-market-research.md').read_text(encoding='utf-8'), 'competing writer')

        def test_folder_swap_cannot_redirect_publication(self):
            self.draft.write_bytes(self.note())
            folder = self.vault / 'Investments'
            moved, unrelated = self.vault / 'moved', self.vault / 'unrelated'
            unrelated.mkdir()
            original, cwd = atomic_move.publish_new, Path.cwd()
            def swap(staged, target, snapshot, stage_parent):
                folder.rename(moved)
                folder.symlink_to(unrelated, target_is_directory=True)
                return original(staged, target, snapshot, stage_parent)
            with patch.object(atomic_move, 'publish_new', side_effect=swap):
                with self.assertRaisesRegex(RuntimeError, 'Investments changed'):
                    publish(self.draft, self.vault, self.now)
            self.assertEqual(Path.cwd(), cwd)
            self.assertEqual(list(unrelated.iterdir()), [])
            self.assertEqual((moved / '2026-09-05-market-research.md').read_bytes(), self.note())
            self.assertEqual(len(list(self.vault.glob('.market-research-stage-*'))), 1)

        def test_outcome_calendar_targets_and_leap_years(self):
            for start, months, expected in (('2024-01-31', 1, '2024-02-29'),
                                           ('2025-01-31', 1, '2025-02-28'),
                                           ('2024-02-29', 12, '2025-02-28'),
                                           ('2024-02-29', 24, '2026-02-28'),
                                           ('2024-02-29', 60, '2029-02-28'),
                                           ('2024-11-30', 3, '2025-02-28')):
                with self.subTest(start=start, months=months):
                    self.assertEqual(month_target(iso_date(start), months).isoformat(), expected)

        def test_two_week_calendar_targets_across_month_leap_and_dst_boundaries(self):
            for start, expected in (('2024-01-31', '2024-02-14'),
                                    ('2024-02-20', '2024-03-05'),
                                    ('2025-02-20', '2025-03-06'),
                                    ('2024-02-29', '2024-03-14'),
                                    ('2024-03-01', '2024-03-15'),
                                    ('2024-10-25', '2024-11-08')):
                with self.subTest(start=start):
                    self.assertEqual(horizon_target(iso_date(start), '2w').isoformat(), expected)
            # Derive the civil date in New York even when the UTC date differs.
            local_day = ny_now(iso_time('2024-03-02T00:30:00+00:00')).date()
            self.assertEqual(horizon_target(local_day, '2w').isoformat(), '2024-03-15')
            for token in ('14d', '0.5m', '2', '02w', '1', '01m'):
                with self.subTest(token=token), self.assertRaises(ValueError):
                    horizon_target(iso_date('2024-01-31'), token)

        def test_two_week_pending_due_observed_and_future_close_rejection(self):
            identifier, _, _ = self.baseline_fixture('2024-02-29', '2024-03-01')
            before = outcomes(self.vault, now=datetime.fromisoformat('2024-03-14T09:03:00-04:00'))
            self.assertTrue(before['complete'], before['findings'])
            self.assertEqual(before['checkpoints'][0]['horizon'], '2w')
            self.assertEqual(before['checkpoints'][0]['target_date'], '2024-03-15')
            self.assertEqual(before['checkpoints'][0]['state'], 'pending')
            self.assertEqual(before['due_checkpoints'], [])
            now_due = datetime.fromisoformat('2024-03-15T09:03:00-04:00')
            due = outcomes(self.vault, now=now_due)
            self.assertEqual([row['horizon'] for row in due['due_checkpoints']], ['2w'])
            self.assertEqual(due['due_checkpoints'][0]['state'], 'due')
            self.assertIn('unverified', due['calendar'])
            for stamp in ('2024-03-14T16:00:00-04:00', '2024-03-15T16:00:00-04:00'):
                self.outcome_note('2024-03-15', journals=[self.journal('Checkpoint records', [
                    (identifier, '2w', 'observed', stamp, self.record_link('2024-03-15'), '-')])], draft=True)
                rejected = outcomes(self.vault, self.draft, now_due)
                self.assertFalse(rejected['complete'])
                self.assertIn('calendar target and not exceed as_of', rejected['findings'][0]['error'])
            self.outcome_note('2024-03-18', journals=[self.journal('Checkpoint records', [
                (identifier, '2w', 'observed', '2024-03-15T16:00:00-04:00',
                 self.record_link('2024-03-18'), '-')])], draft=True)
            recorded = outcomes(self.vault, self.draft, datetime.fromisoformat('2024-03-18T09:03:00-04:00'))
            self.assertTrue(recorded['complete'], recorded['findings'])
            self.assertEqual(recorded['checkpoints'][0]['state'], 'observed')
            self.assertEqual(recorded['due_checkpoints'], [])

        def test_two_week_unavailable_catchup_and_explicit_correction(self):
            identifier, _, _ = self.baseline_fixture()
            self.outcome_note('2024-02-15', journals=[self.journal('Checkpoint records', [
                (identifier, '2w', 'unavailable', '-', self.record_link('2024-02-15'), '-')])])
            unavailable = outcomes(self.vault, now=self.now)
            self.assertTrue(unavailable['complete'], unavailable['findings'])
            self.assertEqual(unavailable['due_checkpoints'][0]['horizon'], '2w')
            self.assertEqual(unavailable['due_checkpoints'][0]['state'], 'unavailable')
            observed_link = self.record_link('2024-02-16')
            self.outcome_note('2024-02-16', journals=[self.journal('Checkpoint records', [
                (identifier, '2w', 'observed', '2024-02-14T16:00:00-05:00', observed_link, '-')])])
            caught_up = outcomes(self.vault, now=self.now)
            self.assertTrue(caught_up['complete'], caught_up['findings'])
            self.assertEqual(caught_up['checkpoints'][0]['state'], 'observed')
            self.assertNotIn('2w', [row['horizon'] for row in caught_up['due_checkpoints']])
            for replaces, complete in (('-', False), (observed_link, True)):
                self.outcome_note('2026-09-05', journals=[self.journal('Checkpoint records', [
                    (identifier, '2w', 'observed', '2024-02-15T16:00:00-05:00',
                     self.record_link('2026-09-05'), replaces)])], draft=True)
                revised = outcomes(self.vault, self.draft, self.now)
                self.assertEqual(revised['complete'], complete, revised['findings'])

        def test_historical_month_tables_normalize_without_rewriting(self):
            identifier, _, _ = self.baseline_fixture()
            path = self.outcome_note('2024-03-01', journals=[self.journal('Checkpoint records', [
                (identifier, '1m', 'observed', '2024-02-29T16:00:00-05:00',
                 self.record_link('2024-03-01'), '-')])])
            canonical = outcomes(self.vault, now=self.now)
            self.assertTrue(canonical['complete'], canonical['findings'])
            old_bytes = path.read_bytes().replace(b'| Horizon |', b'| Months |').replace(b'| 1m |', b'| 1 |')
            path.write_bytes(old_bytes)
            old = outcomes(self.vault, now=self.now)
            self.assertEqual(old, canonical)
            self.assertEqual(path.read_bytes(), old_bytes)
            normalized = lint_bytes(old_bytes)['journals']['Checkpoint records'][0]
            self.assertEqual(normalized['Horizon'], '1m')
            self.assertNotIn('Months', normalized)
            # New canonical rows reassert the same observation; they do not create a second checkpoint.
            self.outcome_note('2026-09-05', journals=[self.journal('Checkpoint records', [
                (identifier, '1m', 'observed', '2024-02-29T16:00:00-05:00',
                 self.record_link('2024-03-01'), '-')])], draft=True)
            combined = outcomes(self.vault, self.draft, self.now)
            self.assertTrue(combined['complete'], combined['findings'])
            self.assertEqual(len([row for row in combined['checkpoints'] if row['horizon'] == '1m']), 1)

        def test_empty_outcomes_are_read_only_and_monthly_due(self):
            before = list(self.vault.iterdir())
            result = outcomes(self.vault, now=self.now)
            self.assertTrue(result['complete'])
            self.assertTrue(result['monthly_review_due'])
            self.assertEqual(result['recommendations'], [])
            self.assertEqual(result['due_baselines'], [])
            self.assertEqual(result['due_checkpoints'], [])
            self.assertEqual(list(self.vault.iterdir()), before)

        def test_first_ready_survives_watch_and_terminal_states(self):
            identifier, _, _ = self.baseline_fixture()
            self.prior('2024-02-01', [(identifier, 'ready', 'A later ready state cannot reset the clock')])
            self.prior('2024-02-02', [(identifier, 'invalidated', 'Synthetic failure retained')])
            self.prior('2024-02-03', [('NYSE:OLD@2024-02-03', 'watch', 'Never confirmed')])
            result = outcomes(self.vault, now=self.now)
            self.assertTrue(result['complete'], result['findings'])
            self.assertEqual(len(result['recommendations']), 1)
            self.assertEqual(result['recommendations'][0]['first_ready'], '2024-01-30')
            self.assertEqual([row['horizon'] for row in result['due_checkpoints']], ['2w', '1m', '3m', '6m', '12m', '24m'])
            by_horizon = {row['horizon']: row for row in result['checkpoints']}
            self.assertEqual(by_horizon['24m']['target_date'], '2026-01-31')
            self.assertEqual(by_horizon['60m']['target_date'], '2029-01-31')
            self.assertEqual(by_horizon['60m']['state'], 'pending')

        def test_five_year_checkpoint_matures_and_accepts_observation(self):
            identifier, _, _ = self.baseline_fixture()
            before = outcomes(self.vault, now=datetime.fromisoformat('2029-01-30T09:03:00-05:00'))
            five_year = next(row for row in before['checkpoints'] if row['horizon'] == '60m')
            self.assertTrue(before['complete'], before['findings'])
            self.assertEqual(five_year['target_date'], '2029-01-31')
            self.assertEqual(five_year['state'], 'pending')
            self.assertNotIn('60m', [row['horizon'] for row in before['due_checkpoints']])
            mature = outcomes(self.vault, now=datetime.fromisoformat('2029-01-31T09:03:00-05:00'))
            self.assertEqual([row['horizon'] for row in mature['due_checkpoints']], list(HORIZONS))
            self.assertEqual(mature['due_checkpoints'][-1]['state'], 'due')
            # Calendar maturity alone does not imply a completed market close.
            self.assertIn('unverified', mature['calendar'])
            self.outcome_note('2029-02-01', journals=[self.journal('Checkpoint records', [
                (identifier, '60m', 'observed', '2029-01-31T16:00:00-05:00',
                 self.record_link('2029-02-01'), '-')])])
            recorded = outcomes(self.vault, now=datetime.fromisoformat('2029-02-01T09:03:00-05:00'))
            self.assertTrue(recorded['complete'], recorded['findings'])
            five_year = next(row for row in recorded['checkpoints'] if row['horizon'] == '60m')
            self.assertEqual(five_year['state'], 'observed')
            self.assertEqual(five_year['observed_at'], '2029-01-31T16:00:00-05:00')
            self.assertNotIn('60m', [row['horizon'] for row in recorded['due_checkpoints']])

        def test_missing_first_ready_record_blocks_publication(self):
            identifier = 'NYSE:ABC@2026-09-05'
            self.draft.write_bytes(self.note(rows=[(identifier, 'ready', 'Missing initial record')]))
            result = outcomes(self.vault, self.draft, self.now)
            self.assertFalse(result['complete'])
            self.assertIn('missing a Recommendation record', result['findings'][0]['error'])
            self.assertEqual(result['checkpoints'][0]['state'], 'needs-baseline')
            with self.assertRaisesRegex(ValueError, 'outcome journal is incomplete'):
                publish(self.draft, self.vault, self.now)
            self.assertFalse((self.vault / 'Investments').exists())

        def test_first_ready_cannot_be_reanchored(self):
            identifier, _, baseline_link = self.baseline_fixture()
            self.outcome_note('2024-02-01', [(identifier, 'ready', 'Still confirmed')], [
                self.journal('Recommendation records', [(identifier, '2024-02-01', 'pending',
                                                         self.record_link('2024-02-01'), baseline_link)])])
            result = outcomes(self.vault, now=self.now)
            self.assertFalse(result['complete'])
            self.assertIn('earliest actual ready', result['findings'][0]['error'])

        def test_checkpoint_timestamps_and_unknown_baselines(self):
            identifier, _, _ = self.baseline_fixture()
            for stamp in ('2024-02-28T16:00:00-05:00', '2026-09-06T16:00:00-04:00',
                          '2024-02-29T16:00:00'):
                with self.subTest(stamp=stamp):
                    self.outcome_note('2026-09-05', journals=[self.journal('Checkpoint records', [
                        (identifier, '1m', 'observed', stamp, self.record_link('2026-09-05'), '-')])], draft=True)
                    result = outcomes(self.vault, self.draft, self.now)
                    self.assertFalse(result['complete'])
            self.outcome_note('2026-09-05', journals=[self.journal('Checkpoint records', [
                (identifier, '1m', 'observed', '2024-02-29T16:00:00-05:00',
                 self.record_link('2026-09-05'), '-')])], draft=True)
            self.assertTrue(outcomes(self.vault, self.draft, self.now)['complete'])

        def test_unknown_baseline_cannot_support_an_observation(self):
            identifier, day = 'NYSE:ABC@2024-01-30', '2024-01-30'
            self.outcome_note(day, [(identifier, 'ready', 'Synthetic confirmed setup')], [
                self.journal('Recommendation records', [(identifier, day, 'unavailable', self.record_link(day), '-')])])
            for state, stamp, complete in (('observed', '2024-02-29T16:00:00-05:00', False),
                                            ('unavailable', '-', True)):
                self.outcome_note('2026-09-05', journals=[self.journal('Checkpoint records', [
                    (identifier, '1m', state, stamp, self.record_link('2026-09-05'), '-')])], draft=True)
                result = outcomes(self.vault, self.draft, self.now)
                self.assertEqual(result['complete'], complete, result['findings'])
                self.assertIsNone(result['checkpoints'][0]['target_date'])

        def test_baseline_cannot_be_changed_without_replacement(self):
            identifier, _, baseline_link = self.baseline_fixture()
            for baseline, record, replaces, complete in (
                    ('2024-01-31T09:30:00-05:00', baseline_link, '-', True),
                    ('2024-02-01T09:30:00-05:00', self.record_link('2026-09-05'), '-', False),
                    ('2024-01-30T09:30:00-05:00', self.record_link('2026-09-05'), baseline_link, False),
                    ('2026-09-06T09:30:00-04:00', self.record_link('2026-09-05'), baseline_link, False)):
                self.outcome_note('2026-09-05', journals=[self.journal('Recommendation records', [
                    (identifier, '2024-01-30', baseline, record, replaces)])], draft=True)
                result = outcomes(self.vault, self.draft, self.now)
                self.assertEqual(result['complete'], complete, result['findings'])

        def test_finalized_corrections_need_distinct_canonical_cards_today(self):
            identifier, _, baseline_link = self.baseline_fixture()
            observation_link = self.record_link('2024-03-01')
            self.outcome_note('2024-03-01', journals=[self.journal('Checkpoint records', [
                (identifier, '1m', 'observed', '2024-02-29T16:00:00-05:00', observation_link, '-')])])
            for title, previous, fields in (
                    ('Recommendation records', baseline_link,
                     (identifier, '2024-01-30', '2024-01-31T09:31:00-05:00')),
                    ('Checkpoint records', observation_link,
                     (identifier, '1m', 'observed', '2024-02-29T15:59:00-05:00'))):
                for new_link in (previous, previous.replace('Investments/', ''),
                                 previous.replace('-research#', '-research.md#')):
                    with self.subTest(title=title, new_link=new_link):
                        self.outcome_note('2026-09-05', journals=[self.journal(title, [
                            fields + (new_link, previous)])], draft=True)
                        result = outcomes(self.vault, self.draft, self.now)
                        self.assertFalse(result['complete'])
                        self.assertIn('distinct new detail card', result['findings'][0]['error'])

        def test_legacy_same_card_baseline_changes_are_recheckable_without_rewriting(self):
            identifier, _, baseline_link = self.baseline_fixture(record_day='2024-02-02')
            observation_link = self.record_link('2024-03-01')
            self.outcome_note('2024-03-01', journals=[self.journal('Checkpoint records', [
                (identifier, '1m', 'observed', '2024-02-29T16:00:00-05:00', observation_link, '-')])])
            correction = self.outcome_note('2024-03-02', journals=[self.journal('Recommendation records', [
                (identifier, '2024-01-30', '2024-02-01T09:30:00-05:00', baseline_link, baseline_link)])])
            original = correction.read_bytes()
            result = outcomes(self.vault, now=self.now)
            self.assertTrue(result['complete'], result['findings'])
            checkpoint = next(row for row in result['checkpoints'] if row['horizon'] == '1m')
            self.assertEqual(checkpoint['state'], 'needs-recheck')
            self.assertEqual(checkpoint['target_date'], '2024-03-01')
            self.outcome_note('2026-09-05', journals=[self.journal('Checkpoint records', [
                (identifier, '1m', 'observed', '2024-03-01T16:00:00-05:00',
                 self.record_link('2026-09-05'), observation_link)])], draft=True)
            repaired = outcomes(self.vault, self.draft, self.now)
            self.assertTrue(repaired['complete'], repaired['findings'])
            self.assertEqual(next(row for row in repaired['checkpoints'] if row['horizon'] == '1m')['state'], 'observed')
            self.assertEqual(correction.read_bytes(), original)

        def test_reverted_legacy_baseline_still_requires_checkpoint_recheck(self):
            identifier, _, baseline_link = self.baseline_fixture(record_day='2024-02-02')
            self.outcome_note('2024-03-01', journals=[self.journal('Checkpoint records', [
                (identifier, '1m', 'observed', '2024-02-29T16:00:00-05:00',
                 self.record_link('2024-03-01'), '-')])])
            for note_day, baseline_day in (('2024-03-02', '2024-02-01'), ('2024-03-03', '2024-01-31')):
                self.outcome_note(note_day, journals=[self.journal('Recommendation records', [
                    (identifier, '2024-01-30', baseline_day + 'T09:30:00-05:00', baseline_link, baseline_link)])])
            result = outcomes(self.vault, now=self.now)
            self.assertTrue(result['complete'], result['findings'])
            self.assertEqual(next(row for row in result['checkpoints'] if row['horizon'] == '1m')['state'], 'needs-recheck')

        def test_legacy_same_card_checkpoint_changes_remain_due_until_new_card(self):
            identifier, _, _ = self.baseline_fixture()
            observation_link = self.record_link('2024-03-01')
            alias = observation_link.replace('Investments/', '').replace('-research#', '-research.md#')
            self.outcome_note('2024-03-01', journals=[self.journal('Checkpoint records', [
                (identifier, '1m', 'observed', '2024-02-29T16:00:00-05:00', observation_link, '-')])])
            for state, observed in (('observed', '2024-02-29T15:59:00-05:00'), ('unavailable', '-')):
                with self.subTest(state=state):
                    correction_path = self.outcome_note('2024-03-02', journals=[self.journal('Checkpoint records', [
                        (identifier, '1m', state, observed, observation_link, observation_link)])])
                    correction_bytes = correction_path.read_bytes()
                    self.outcome_note('2024-03-03', journals=[self.journal('Checkpoint records', [
                        (identifier, '1m', state, observed, alias, '-')])])
                    result = outcomes(self.vault, now=self.now)
                    self.assertTrue(result['complete'], result['findings'])
                    checkpoint = next(row for row in result['due_checkpoints'] if row['horizon'] == '1m')
                    self.assertEqual(checkpoint['state'], 'needs-recheck')
                    self.assertFalse(any(key.startswith('_') for key in checkpoint))
                    # A same-card repeat cannot clear the unresolved correction today.
                    self.outcome_note('2026-09-05', journals=[self.journal('Checkpoint records', [
                        (identifier, '1m', state, observed, observation_link, '-')])], draft=True)
                    repeated = outcomes(self.vault, self.draft, self.now)
                    self.assertTrue(repeated['complete'], repeated['findings'])
                    self.assertEqual(next(row for row in repeated['checkpoints']
                                          if row['horizon'] == '1m')['state'], 'needs-recheck')
                    for record, replaces, complete in ((alias, alias, False),
                                                       (self.record_link('2026-09-05'), '-', False),
                                                       (self.record_link('2026-09-05'), alias, True)):
                        self.outcome_note('2026-09-05', journals=[self.journal('Checkpoint records', [
                            (identifier, '1m', 'observed', '2024-03-02T16:00:00-05:00', record, replaces)])], draft=True)
                        repaired = outcomes(self.vault, self.draft, self.now)
                        self.assertEqual(repaired['complete'], complete, repaired['findings'])
                        if complete:
                            self.assertEqual(next(row for row in repaired['checkpoints']
                                                  if row['horizon'] == '1m')['state'], 'observed')
                    self.assertEqual(correction_path.read_bytes(), correction_bytes)

        def test_equivalent_record_spellings_do_not_change_baseline_version(self):
            identifier, _, baseline_link = self.baseline_fixture()
            self.outcome_note('2024-03-01', journals=[self.journal('Checkpoint records', [
                (identifier, '1m', 'observed', '2024-02-29T16:00:00-05:00',
                 self.record_link('2024-03-01'), '-')])])
            alias = baseline_link.replace('Investments/', '').replace('-research#', '-research.md#')
            self.outcome_note('2026-09-05', journals=[self.journal('Recommendation records', [
                (identifier, '2024-01-30', '2024-01-31T09:30:00-05:00', alias, '-')])], draft=True)
            result = outcomes(self.vault, self.draft, self.now)
            self.assertTrue(result['complete'], result['findings'])
            self.assertEqual(next(row for row in result['checkpoints'] if row['horizon'] == '1m')['state'], 'observed')

        def test_equivalent_event_timestamps_do_not_create_corrections(self):
            identifier, _, baseline_link = self.baseline_fixture()
            observation_link = self.record_link('2024-03-01')
            self.outcome_note('2024-03-01', journals=[self.journal('Checkpoint records', [
                (identifier, '1m', 'observed', '2024-02-29T16:00:00-05:00', observation_link, '-')])])
            original = outcomes(self.vault, now=self.now)
            for baseline, observed in (('2024-01-31T09:30:00.000-05:00', '2024-02-29T16:00:00.000-05:00'),
                                       ('2024-01-31T14:30:00Z', '2024-02-29T21:00:00+00:00')):
                with self.subTest(baseline=baseline, observed=observed):
                    self.outcome_note('2026-09-05', journals=[
                        self.journal('Recommendation records', [
                            (identifier, '2024-01-30', baseline, baseline_link, '-')]),
                        self.journal('Checkpoint records', [
                            (identifier, '1m', 'observed', observed, observation_link, '-')])], draft=True)
                    result = outcomes(self.vault, self.draft, self.now)
                    self.assertTrue(result['complete'], result['findings'])
                    self.assertEqual(result['recommendations'][0]['version_note'],
                                     original['recommendations'][0]['version_note'])
                    self.assertEqual(next(row for row in result['checkpoints']
                                          if row['horizon'] == '1m')['state'], 'observed')
                    self.assertNotIn('1m', [row['horizon'] for row in result['due_checkpoints']])

        def test_timestamped_records_cannot_predate_their_events(self):
            identifier, first_link, baseline_link = self.baseline_fixture()
            for title, fields, old_link, replaces in (
                    ('Recommendation records', (identifier, '2024-01-30', '2024-02-01T09:30:00-05:00'),
                     first_link, baseline_link),
                    ('Checkpoint records', (identifier, '1m', 'observed', '2024-02-29T16:00:00-05:00'),
                     baseline_link, '-')):
                with self.subTest(title=title):
                    self.outcome_note('2026-09-05', journals=[self.journal(title, [
                        fields + (old_link, replaces)])], draft=True)
                    rejected = outcomes(self.vault, self.draft, self.now)
                    self.assertFalse(rejected['complete'])
                    self.assertTrue(any("Record note's as_of" in row['error'] for row in rejected['findings']))
                    self.outcome_note('2026-09-05', journals=[self.journal(title, [
                        fields + (self.record_link('2026-09-05'), replaces)])], draft=True)
                    accepted = outcomes(self.vault, self.draft, self.now)
                    self.assertTrue(accepted['complete'], accepted['findings'])

        def test_pending_baseline_requires_evidence_record_after_the_opening(self):
            identifier, first_day = 'NYSE:ABC@2026-09-03', '2026-09-03'
            first_link = self.record_link(first_day)
            self.outcome_note(first_day, [(identifier, 'ready', 'Original setup')], [
                self.journal('Recommendation records', [(identifier, first_day, 'pending', first_link, '-')])])
            for record, complete in ((first_link, False), (self.record_link('2026-09-05'), True)):
                with self.subTest(record=record):
                    self.outcome_note('2026-09-05', journals=[self.journal('Recommendation records', [
                        (identifier, first_day, '2026-09-04T09:30:00-04:00', record, '-')])], draft=True)
                    result = outcomes(self.vault, self.draft, self.now)
                    self.assertEqual(result['complete'], complete, result['findings'])

        def test_baseline_cannot_predate_known_first_ready_generation(self):
            identifier, _, _ = self.baseline_fixture()
            first = self.vault / 'Investments/2024-01-30-market-research.md'
            first.write_bytes(first.read_bytes().replace(b'2024-01-30T09:02:00-04:00',
                                                        b'2024-02-01T12:00:00-05:00'))
            result = outcomes(self.vault, now=self.now)
            self.assertFalse(result['complete'])
            self.assertTrue(any('first-ready note\'s generated_at' in row['error'] for row in result['findings']))

        def test_journal_headers_cannot_be_indented_code(self):
            identifier = 'NYSE:ABC@2026-09-05'
            self.outcome_note('2026-09-05', [(identifier, 'ready', 'Synthetic setup')], [
                self.journal('Recommendation records', [(identifier, '2026-09-05', 'pending',
                                                         self.record_link('2026-09-05'), '-')])], draft=True)
            data = self.draft.read_bytes().replace(b'| Recommendation | First ready |',
                                                  b'    | Recommendation | First ready |')
            with self.assertRaisesRegex(ValueError, 'must not be indented'):
                lint_bytes(data)

        def test_observation_corrections_require_explicit_replacement(self):
            identifier, _, _ = self.baseline_fixture()
            old_link = self.record_link('2024-03-01')
            self.outcome_note('2024-03-01', journals=[self.journal('Checkpoint records', [
                (identifier, '1m', 'observed', '2024-02-29T16:00:00-05:00', old_link, '-')])])
            for replaces, complete in (('-', False), (old_link, True)):
                self.outcome_note('2026-09-05', journals=[self.journal('Checkpoint records', [
                    (identifier, '1m', 'observed', '2024-03-01T16:00:00-05:00',
                     self.record_link('2026-09-05'), replaces)])], draft=True)
                self.assertEqual(outcomes(self.vault, self.draft, self.now)['complete'], complete)

        def test_baseline_correction_requires_checkpoint_recheck(self):
            identifier, _, baseline_link = self.baseline_fixture()
            observation_link = self.record_link('2024-03-01')
            self.outcome_note('2024-03-01', journals=[self.journal('Checkpoint records', [
                (identifier, '1m', 'observed', '2024-02-29T16:00:00-05:00', observation_link, '-')])])
            correction_link = self.record_link('2024-03-02')
            self.outcome_note('2024-03-02', journals=[self.journal('Recommendation records', [
                (identifier, '2024-01-30', '2024-02-01T09:30:00-05:00', correction_link, baseline_link)])])
            result = outcomes(self.vault, now=self.now)
            self.assertTrue(result['complete'], result['findings'])
            self.assertEqual(next(row for row in result['checkpoints'] if row['horizon'] == '1m')['state'], 'needs-recheck')
            self.assertIn('1m', [row['horizon'] for row in result['due_checkpoints']])
            self.outcome_note('2026-09-05', journals=[self.journal('Checkpoint records', [
                (identifier, '1m', 'observed', '2024-03-01T16:00:00-05:00',
                 self.record_link('2026-09-05'), observation_link)])], draft=True)
            updated = outcomes(self.vault, self.draft, self.now)
            self.assertTrue(updated['complete'], updated['findings'])
            self.assertEqual(next(row for row in updated['checkpoints'] if row['horizon'] == '1m')['state'], 'observed')
            self.assertEqual([row['horizon'] for row in updated['due_checkpoints']], ['2w', '3m', '6m', '12m', '24m'])

        def test_unavailable_observations_remain_due(self):
            identifier, _, _ = self.baseline_fixture()
            self.outcome_note('2024-03-01', journals=[self.journal('Checkpoint records', [
                (identifier, '1m', 'unavailable', '-', self.record_link('2024-03-01'), '-')])])
            result = outcomes(self.vault, now=self.now)
            self.assertTrue(result['complete'], result['findings'])
            self.assertEqual(next(row for row in result['due_checkpoints'] if row['horizon'] == '1m')['state'], 'unavailable')
            self.assertEqual([row['horizon'] for row in result['due_checkpoints']], ['2w', '1m', '3m', '6m', '12m', '24m'])

        def test_stale_unavailable_checkpoint_requires_explicit_distinct_correction(self):
            identifier, _, baseline_link = self.baseline_fixture()
            checkpoint_link = self.record_link('2024-03-01')
            self.outcome_note('2024-03-01', journals=[self.journal('Checkpoint records', [
                (identifier, '1m', 'unavailable', '-', checkpoint_link, '-')])])
            self.outcome_note('2024-03-02', journals=[self.journal('Recommendation records', [
                (identifier, '2024-01-30', '2024-02-01T09:30:00-05:00',
                 self.record_link('2024-03-02'), baseline_link)])])
            before = outcomes(self.vault, now=self.now)
            self.assertEqual(next(row for row in before['checkpoints']
                                  if row['horizon'] == '1m')['state'], 'needs-recheck')
            for state, observed, record, replaces, complete in (
                    ('observed', '2024-03-01T16:00:00-05:00', self.record_link('2026-09-05'), '-', False),
                    ('unavailable', '-', checkpoint_link, checkpoint_link, False),
                    ('unavailable', '-', self.record_link('2026-09-05'), '-', False),
                    ('observed', '2024-03-01T16:00:00-05:00', self.record_link('2026-09-05'), checkpoint_link, True)):
                with self.subTest(state=state, record=record, replaces=replaces):
                    self.outcome_note('2026-09-05', journals=[self.journal('Checkpoint records', [
                        (identifier, '1m', state, observed, record, replaces)])], draft=True)
                    result = outcomes(self.vault, self.draft, self.now)
                    self.assertEqual(result['complete'], complete, result['findings'])
                    self.assertEqual(next(row for row in result['checkpoints'] if row['horizon'] == '1m')['state'],
                                     'observed' if complete else 'needs-recheck')

        def test_lesson_status_and_monthly_retrieval(self):
            lesson = 'lesson-2026-08-01-01'
            self.outcome_note('2026-08-01', journals=[self.journal('Lesson records', [
                (lesson, 'provisional', self.record_link('2026-08-01'))]),
                self.journal('Monthly summaries', [('2026-08', self.record_link('2026-08-01'))])])
            self.outcome_note('2026-09-05', journals=[self.journal('Lesson records', [
                (lesson, 'retired', self.record_link('2026-09-05'))]),
                self.journal('Monthly summaries', [('2026-09', self.record_link('2026-09-05'))])], draft=True)
            before = outcomes(self.vault, now=self.now)
            self.assertEqual(before['active_lessons'][0]['id'], lesson)
            self.assertTrue(before['monthly_review_due'])
            after = outcomes(self.vault, self.draft, self.now)
            self.assertTrue(after['complete'], after['findings'])
            self.assertEqual(after['active_lessons'], [])
            self.assertEqual(after['retired_lessons'][0]['status'], 'retired')
            self.assertFalse(after['monthly_review_due'])

        def test_lesson_status_changes_require_a_distinct_canonical_card(self):
            identifier = 'lesson-2026-08-01-01'
            old_link, current_link = self.record_link('2026-08-01'), self.record_link('2026-09-05')
            self.outcome_note('2026-08-01', journals=[self.journal('Lesson records', [
                (identifier, 'provisional', old_link)])])
            alias = old_link.replace('Investments/', '').replace('-research#', '-research.md#')
            for status, record, complete in (('provisional', alias, True), ('supported', old_link, False),
                                             ('retired', alias, False), ('supported', current_link, True),
                                             ('retired', current_link, True)):
                with self.subTest(status=status, record=record):
                    self.outcome_note('2026-09-05', journals=[self.journal('Lesson records', [
                        (identifier, status, record)])], draft=True)
                    result = outcomes(self.vault, self.draft, self.now)
                    self.assertEqual(result['complete'], complete, result['findings'])
                    if not complete:
                        self.assertIn('distinct new detail card', result['findings'][0]['error'])
                        self.assertEqual(result['active_lessons'][0]['status'], 'provisional')

        def test_invalid_lessons_and_misdated_monthly_summaries(self):
            for identifier, status in (('lesson-2026-09-05-00', 'provisional'),
                                       ('lesson-2026-09-05-001', 'provisional'),
                                       ('lesson-2026-09-05-0100', 'provisional'),
                                       ('lesson-2026-09-06-01', 'provisional'),
                                       ('lesson-2026-02-30-01', 'supported'),
                                       ('lesson-2026-09-05-01', 'certain')):
                self.outcome_note('2026-09-05', journals=[self.journal('Lesson records', [
                    (identifier, status, self.record_link('2026-09-05'))])], draft=True)
                self.assertFalse(outcomes(self.vault, self.draft, self.now)['complete'])
            self.outcome_note('2026-09-05', journals=[self.journal('Monthly summaries', [
                ('2026-08', self.record_link('2026-09-05'))])], draft=True)
            self.assertFalse(outcomes(self.vault, self.draft, self.now)['complete'])
            self.outcome_note('2026-09-05', journals=[self.journal('Lesson records', [
                ('lesson-2026-09-05-100', 'provisional', self.record_link('2026-09-05'))])], draft=True)
            self.assertTrue(outcomes(self.vault, self.draft, self.now)['complete'])

        def test_monthly_summary_cannot_point_to_an_older_month(self):
            self.prior('2026-08-31', [])
            self.outcome_note('2026-09-05', journals=[self.journal('Monthly summaries', [
                ('2026-09', self.record_link('2026-08-31'))])], draft=True)
            result = outcomes(self.vault, self.draft, self.now)
            self.assertFalse(result['complete'])
            self.assertTrue(result['monthly_review_due'])
            self.assertIn('registered Month', result['findings'][0]['error'])

        def test_record_section_anchor_must_be_unambiguous(self):
            path = self.prior('2026-09-04', [])
            path.write_bytes(path.read_bytes() + b'\n#### Finding\n\nFirst detail.\n\n#### Finding\n\nSecond detail.\n')
            self.outcome_note('2026-09-05', journals=[self.journal('Lesson records', [
                ('lesson-2026-09-05-01', 'provisional',
                 '[[Investments/2026-09-04-market-research#Finding]]')])], draft=True)
            result = outcomes(self.vault, self.draft, self.now)
            self.assertFalse(result['complete'])
            self.assertIn('exactly one heading', result['findings'][0]['error'])

        def test_new_records_need_anchors_without_invalidating_older_note_links(self):
            identifier = 'lesson-2026-09-04-01'
            old_link = '[[Investments/2026-09-04-market-research]]'
            old = self.outcome_note('2026-09-04', journals=[self.journal('Lesson records', [
                (identifier, 'provisional', old_link)])])
            original = old.read_bytes()
            legacy = outcomes(self.vault, now=self.now)
            self.assertTrue(legacy['complete'], legacy['findings'])
            self.assertIsNone(legacy['active_lessons'][0]['record_section'])
            for link in (old_link, '[[Investments/2026-09-05-market-research]]'):
                with self.subTest(link=link):
                    self.outcome_note('2026-09-05', journals=[self.journal('Lesson records', [
                        (identifier, 'provisional', link)])], draft=True)
                    result = outcomes(self.vault, self.draft, self.now)
                    self.assertFalse(result['complete'])
                    self.assertIn('specific section anchor', result['findings'][0]['error'])
                    with self.assertRaisesRegex(ValueError, 'specific section anchor'):
                        publish(self.draft, self.vault, self.now)
            updated_link = '[[Investments/2026-09-05-market-research#Updated lesson evidence]]'
            self.outcome_note('2026-09-05', journals=[self.journal('Lesson records', [
                (identifier, 'supported', updated_link)])], draft=True)
            self.draft.write_bytes(self.draft.read_bytes()
                                   + b'\n#### Updated lesson evidence\n\nSynthetic evidence with a prior-record link: '
                                   + old_link.encode() + b'.\n')
            checked = outcomes(self.vault, self.draft, self.now)
            self.assertTrue(checked['complete'], checked['findings'])
            self.assertEqual(checked['active_lessons'][0]['record_section'], 'Updated lesson evidence')
            self.assertEqual(old.read_bytes(), original)

        def test_published_same_day_note_links_allow_read_and_identical_retry(self):
            link = '[[Investments/2026-09-05-market-research]]'
            published = self.outcome_note('2026-09-05', journals=[self.journal('Lesson records', [
                ('lesson-2026-09-05-01', 'provisional', link)])])
            original = published.read_bytes()
            indexed = outcomes(self.vault, now=self.now)
            self.assertTrue(indexed['complete'], indexed['findings'])
            self.assertIsNone(indexed['active_lessons'][0]['record_section'])
            self.draft.write_bytes(original)
            retry = outcomes(self.vault, self.draft, self.now)
            self.assertTrue(retry['complete'], retry['findings'])
            self.assertEqual(retry['active_lessons'], indexed['active_lessons'])
            self.assertEqual(publish(self.draft, self.vault, self.now)['status'], 'unchanged')
            self.assertEqual(published.read_bytes(), original)
            self.assertFalse(list(self.vault.glob('.market-research-stage-*')))

        def test_due_baselines_include_terminal_recommendations_once(self):
            identifier, first_day = 'NYSE:ABC@2026-09-03', '2026-09-03'
            self.outcome_note(first_day, [(identifier, 'ready', 'Synthetic confirmed setup')], [
                self.journal('Recommendation records', [(identifier, first_day, 'pending',
                                                         self.record_link(first_day), '-')])])
            first = outcomes(self.vault, now=datetime.fromisoformat('2026-09-03T09:03:00-04:00'))
            self.assertEqual(first['due_baselines'], [])
            self.outcome_note('2026-09-04', [(identifier, 'invalidated', 'Keep observing the failed setup')], [
                self.journal('Recommendation records', [(identifier, first_day, 'unavailable',
                                                         self.record_link('2026-09-04'), '-')])])
            result = outcomes(self.vault, now=self.now)
            self.assertTrue(result['complete'], result['findings'])
            self.assertEqual([item['id'] for item in result['due_baselines']], [identifier])
            self.assertEqual(result['due_checkpoints'], [])
            self.assertEqual(context(self.vault, self.now)['active_theses'], [])

        def test_malformed_and_mislocated_journals_are_not_omitted(self):
            source = self.note() + b'\n#### Lesson records\n\nNo changes.\n'
            for data in (source + b'\n#### Lesson records\n\nNo changes.\n',
                         source.replace(b'#### Lesson records', b'##### Lesson records'),
                         source.replace(b'#### Lesson records', b'#### lesson records'),
                         source.replace(b'No changes.', b'No changes.\nExtra prose.'),
                         self.note().replace(b'No qualifying opportunity.',
                                             b'#### Lesson records\n\nNo changes.')):
                with self.subTest(data=data), self.assertRaises(ValueError):
                    lint_bytes(data)
            malformed = self.prior('2026-09-04', [])
            malformed.write_bytes(self.note('2026-09-04') + b'\n#### Lesson records\n\nBroken table.\n')
            self.assertFalse(outcomes(self.vault, now=self.now)['complete'])

        def test_unknown_duplicate_and_future_journal_references(self):
            identifier, _, _ = self.baseline_fixture()
            valid = (identifier, '1m', 'unavailable', '-', self.record_link('2026-09-05'), '-')
            for rows in ([valid, valid], [('NYSE:UNKNOWN@2024-01-30', *valid[1:])],
                         [(*valid[:4], '[[Investments/2026-09-06-market-research]]', '-')],
                         [(*valid[:4], '[[Investments/2026-09-05-market-research#Missing]]', '-')],
                         [(*valid[:4], 'https://example.com', '-')]):
                self.outcome_note('2026-09-05', journals=[self.journal('Checkpoint records', rows)], draft=True)
                self.assertFalse(outcomes(self.vault, self.draft, self.now)['complete'])

        def test_draft_overlay_and_current_published_retrieval(self):
            identifier = 'NYSE:ABC@2026-09-05'
            self.outcome_note('2026-09-05', [(identifier, 'ready', 'Synthetic current setup')], [
                self.journal('Recommendation records', [(identifier, '2026-09-05', 'pending',
                                                         self.record_link('2026-09-05'), '-')])], draft=True)
            before = list(self.vault.iterdir())
            preview = outcomes(self.vault, self.draft, self.now)
            self.assertTrue(preview['complete'], preview['findings'])
            self.assertEqual(preview['recommendations'][0]['first_ready'], '2026-09-05')
            self.assertEqual(list(self.vault.iterdir()), before)
            publish(self.draft, self.vault, self.now)
            saved = outcomes(self.vault, now=self.now)
            self.assertEqual(saved['recommendations'], preview['recommendations'])
            self.assertTrue(outcomes(self.vault, self.draft, self.now)['complete'])
            self.draft.write_bytes(self.draft.read_bytes().replace(b'Synthetic current setup', b'Changed setup'))
            with self.assertRaisesRegex(ValueError, 'different published note'):
                outcomes(self.vault, self.draft, self.now)

    result = unittest.TextTestRunner(stream=sys.stderr).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    failed = sum(len(items) for items in (result.failures, result.errors, result.skipped,
                                        result.expectedFailures, result.unexpectedSuccesses))
    print('%d/%d self-test cases pass' % (result.testsRun - failed, result.testsRun))
    return result.wasSuccessful() and failed == 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', action='store_true')
    commands = parser.add_subparsers(dest='command')
    context_parser = commands.add_parser('context')
    context_parser.add_argument('--vault', required=True)
    outcomes_parser = commands.add_parser('outcomes')
    outcomes_parser.add_argument('--vault', required=True)
    outcomes_parser.add_argument('--draft')
    lint_parser = commands.add_parser('lint')
    lint_parser.add_argument('note')
    publish_parser = commands.add_parser('publish')
    publish_parser.add_argument('draft')
    publish_parser.add_argument('--vault', required=True)
    args = parser.parse_args(argv)
    if args.test:
        return 0 if run_self_test() else 1
    try:
        if args.command == 'context':
            result = context(args.vault)
        elif args.command == 'outcomes':
            result = outcomes(args.vault, args.draft)
        elif args.command == 'lint':
            result = lint_bytes(read_stable(args.note)[0])
        elif args.command == 'publish':
            result = publish(args.draft, args.vault)
        else:
            parser.error('choose context, outcomes, lint, publish or --test')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get('complete', True) else 2
    except (ValueError, OSError, UnicodeError, RuntimeError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        return 3 if isinstance(exc, RuntimeError) else 2


if __name__ == '__main__':
    raise SystemExit(main())
