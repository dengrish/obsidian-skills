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

MAX_BYTES = 256 * 1024
FIELDS = ('market_research', 'date', 'as_of', 'generated_at', 'session', 'coverage')
HEADINGS = ('Decision brief', 'Research record')
SUBHEADINGS = {
    'Decision brief': ('Buying opportunities', 'Next checks'),
    'Research record': ('Screening and sources', 'Candidate assessments', 'Thesis updates', 'Outcome review'),
}
ATX = re.compile(r' {0,3}(#{1,6})(?:[ \t]+(.*)|[ \t]*)$')
DAILY = re.compile(r'(\d{4}-\d{2}-\d{2})(?:-(\d{6}))?-market-research\.md\Z')
THESIS = re.compile(r'([A-Z][A-Z0-9]{1,15}:[A-Z][A-Z0-9.-]{0,14})@(\d{4}-\d{2}-\d{2})(?:-(\d{6}))?\Z')
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
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?'
                        r'(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)', value):
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
    text, provenance = note_provenance.split_provenance(data.decode('utf-8'))
    lines = text.splitlines()
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
            if match[3]:
                time(int(match[3][:2]), int(match[3][2:4]), int(match[3][4:]))
            if thesis_id in seen or state not in STATES or not update:
                raise ValueError('duplicate thesis, invalid state or empty update: ' + thesis_id)
            seen.add(thesis_id)
            rows.append({'id': thesis_id, 'state': state, 'update': update})
    return {'metadata': meta, 'provenance': provenance, 'theses': rows,
            'journals': journal_tables(sections['Outcome review'])}


def active_provenance():
    """Verify the actual executing bundle, never an unrelated shared override."""
    plugin_root = Path(__file__).resolve(strict=True).parents[3]
    expected_shared = (plugin_root / 'shared' / 'scripts').resolve(strict=True)
    if Path(_shared).resolve(strict=True) != expected_shared:
        raise ValueError('publication provenance requires shared helpers from the executing plugin bundle')
    return note_provenance.verified_record(plugin_root, 'market-research')


def require_publication_provenance(metadata):
    """New immutable editions identify their current, verified creator."""
    if metadata is None:
        raise ValueError('new market notes require a skill-provenance footer; stamp the draft with '
                         'the installed plugin\'s note_provenance helper before publication')
    if metadata.get('generated_by') != active_provenance() or 'updated_by' in metadata:
        raise ValueError('new market-note provenance must identify the executing installed '
                         'market-research bundle as its creator, without an update record')


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


def edition_identity(current, mode='scheduled', as_of=None):
    """Freeze a manual run's identity; ordinary scheduled retries keep one target."""
    if mode not in ('scheduled', 'manual'):
        raise ValueError('mode must be scheduled or manual')
    if mode == 'scheduled':
        if as_of is not None:
            raise ValueError('--as-of is only supported with --mode manual')
        cutoff = min(current, scheduled_cutoff(current))
        return current.date().isoformat() + '-market-research.md', cutoff
    cutoff = ny_now(iso_time(as_of)) if as_of is not None else current.replace(microsecond=0)
    if (cutoff.date() != current.date() or cutoff.astimezone(timezone.utc) > current.astimezone(timezone.utc)
            or cutoff.microsecond):
        raise ValueError('manual as_of must be a nonfuture timestamp on today\'s New York date, with whole seconds')
    # Fixed offsets compare as instants even during the repeated fall-back hour.
    return cutoff.strftime('%Y-%m-%d-%H%M%S-market-research.md'), iso_time(cutoff.isoformat())


def inventory(vault, day, edition=None, cutoff=None):
    """Read all editions in evidence-time order; preserve omitted open theses."""
    vault, folder, folder_identity = output_folder(vault)
    edition = edition or day + '-market-research.md'
    result = {'complete': True, 'findings': [], 'prior_notes': [], 'later_notes': [], 'other_notes': [],
              'current_note': {'path': str(folder / edition), 'state': 'missing'},
              'thesis_history': [], 'active_theses': []}
    tokens, latest, terminal, records = {}, {}, set(), []
    paths = sorted(folder.iterdir(), key=lambda path: path.name) if folder_identity else []
    names = {}
    for path in paths:
        names.setdefault(portable_identity(path.name), []).append(path)
    for identity, owners in sorted(names.items()):
        match = DAILY.fullmatch(identity)
        if not match:
            result['other_notes'].extend(str(path) for path in owners if path.suffix.lower() == '.md')
            continue
        selected = identity == edition
        try:
            if len(owners) != 1 or owners[0].name != identity:
                raise ValueError('portable-equivalent or noncanonical daily-note owner')
            path = owners[0]
            data, token = read_stable(path)
            note = lint_bytes(data, match[1])
            stamp = iso_time(note['metadata']['as_of'])
            if match[2] and (ny_now(stamp).strftime('%H%M%S') != match[2] or stamp.microsecond):
                raise ValueError('manual filename time must match its as_of in New York, with whole seconds')
            tokens[str(path)] = token
            records.append((stamp, iso_time(note['metadata']['generated_at']), str(path), note))
            if selected:
                result['current_note'].update(state='valid', as_of=note['metadata']['as_of'])
                if match[2] and cutoff is not None and stamp != cutoff:
                    raise ValueError('manual filename is occupied by another timestamp; start a new manual run')
                cutoff = stamp
        except (ValueError, OSError, UnicodeError) as exc:
            result['complete'] = False
            result['findings'].append({'paths': list(map(str, owners)), 'error': str(exc)})
            if selected:
                result['current_note']['state'] = 'blocked'
    for stamp, generated, path, note in sorted(records):
        selected = Path(path).name == edition
        note_day = note['metadata']['date']
        if note_day > day:
            continue
        later = cutoff is not None and not selected and (stamp >= cutoff or generated > cutoff)
        if later:
            result['later_notes'].append(path)
            continue
        revived = [row['id'] for row in note['theses']
                   if row['state'] in ACTIVE and row['id'] in terminal]
        if revived:
            result['complete'] = False
            result['findings'].append({'paths': [path], 'error':
                'terminal theses require a new linked thesis ID, not revival: ' + ', '.join(revived)})
            continue
        terminal.update(row['id'] for row in note['theses'] if row['state'] not in ACTIVE)
        if selected:
            continue
        result['prior_notes'].append(path)
        for row in note['theses']:
            record = dict(row, note=path)
            result['thesis_history'].append(record)
            latest[row['id']] = record
    if result['current_note']['state'] == 'missing' and result['later_notes']:
        result['complete'] = False
        result['findings'].append({'paths': result['later_notes'], 'error':
            'a later edition already exists; do not backfill or publish out of order; start a fresh manual run'})
    result['active_theses'] = [row for _, row in sorted(latest.items()) if row['state'] in ACTIVE]
    if output_folder(vault)[2] != folder_identity:
        raise ValueError('Investments directory changed during inventory')
    return result, (folder_identity, tuple((str(path),) for path in paths), tokens)


def context(vault, now=None, mode='scheduled', as_of=None):
    current = ny_now(now)
    day = current.date().isoformat()
    scheduled = scheduled_cutoff(current)
    edition, cutoff = edition_identity(current, mode, as_of)
    result, _ = inventory(vault, day, edition, cutoff)
    return dict(result, date=day, now=current.isoformat(), mode=mode,
                scheduled_cutoff=scheduled.isoformat(),
                as_of=result['current_note'].get('as_of', cutoff.isoformat()),
                timing='manual' if mode == 'manual' else
                       'early/manual' if current < scheduled else 'scheduled-cutoff',
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


def outcomes(vault, draft=None, now=None, mode='scheduled', as_of=None):
    """Rebuild the prospective journal without a mutable index or any writes."""
    current = ny_now(now)
    day = current.date().isoformat()
    draft_data, draft_token = None, None
    if draft is not None:
        draft_data, draft_token = read_stable(draft)
        draft_note = lint_bytes(draft_data, day)
        if mode == 'manual':
            if as_of is not None and iso_time(as_of) != iso_time(draft_note['metadata']['as_of']):
                raise ValueError('manual --as-of must match the draft as_of')
            as_of = draft_note['metadata']['as_of']
    edition, cutoff = edition_identity(current, mode, as_of)
    if draft is not None:
        cutoff = iso_time(draft_note['metadata']['as_of'])
    history, snapshot = inventory(vault, day, edition, cutoff)
    findings, notes = list(history['findings']), {}
    edition_key = Path(edition).stem
    def finding(path, error):
        findings.append({'paths': [str(path)], 'error': str(error)})
    included = set(history['prior_notes']) | {history['current_note']['path']}
    for path, token in snapshot[2].items():
        if path not in included:
            continue
        data, checked = read_stable(path)
        if checked != token:
            raise ValueError('daily-note history changed while reading outcomes')
        note = lint_bytes(data)
        if iso_time(note['metadata']['generated_at']) > current:
            finding(path, 'generated_at is in the future')
        notes[Path(path).stem] = (path, note, data)
    unpublished_draft = draft is not None and edition_key not in notes
    if draft is not None:
        if iso_time(draft_note['metadata']['generated_at']) > current:
            raise ValueError('draft generated_at is in the future')
        if edition_key in notes and notes[edition_key][2] != draft_data:
            raise ValueError('edition already has a different published note; draft overlay is only for unpublished content')
        notes[edition_key] = (history['current_note']['path'], draft_note, draft_data)
    ordered = sorted(notes.items(), key=lambda item: (
        iso_time(item[1][1]['metadata']['as_of']), iso_time(item[1][1]['metadata']['generated_at']), item[0]))
    positions = {key: index for index, (key, _) in enumerate(ordered)}
    first, recommendations, checkpoints, lessons = {}, {}, {}, {}
    monthly = None
    introduced_theses = set()
    for note_key, (path, note, _) in ordered:
        note_day = note['metadata']['date']
        for row in note['theses']:
            if (unpublished_draft and note_key == edition_key and row['id'] not in introduced_theses
                    and THESIS.fullmatch(row['id'])[2] != note_day):
                finding(path, 'new thesis ID must use its first-recorded note date: ' + row['id'])
            if unpublished_draft and note_key == edition_key and row['id'] not in introduced_theses:
                identity = THESIS.fullmatch(row['id'])
                if identity[3] and (mode != 'manual' or identity[2] + '-' + identity[3]
                        != ny_now(iso_time(note['metadata']['as_of'])).strftime('%Y-%m-%d-%H%M%S')):
                    finding(path, 'new time-suffixed thesis ID must match its manual edition as_of: ' + row['id'])
            introduced_theses.add(row['id'])
            if row['state'] == 'ready':
                first.setdefault(row['id'], {'id': row['id'], 'first_ready': note_day,
                                             'first_ready_note': path})

    def reference(raw, note_key):
        match = re.fullmatch(r'\[\[(?:Investments/)?(\d{4}-\d{2}-\d{2}(?:-\d{6})?-market-research)'
                             r'(?:\.md)?(?:#([^\[\]|\\#\r\n]+))?\]\]', raw)
        if not match or match[1] not in notes or positions[match[1]] > positions[note_key]:
            raise ValueError('Record must link to a known, nonfuture dated market note or section: ' + raw)
        # Preserve published note-wide links and identical retries. New drafts
        # reference a specific card in an exact edition, never an ambiguous date.
        if unpublished_draft and note_key == edition_key and not match[2]:
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

    def correction(row, item, previous, changed, finalized, note_key, first_observation=False):
        replaces = row['Replaces']
        if previous is None:
            if replaces != '-':
                raise ValueError('first journal record must use Replaces -')
        elif changed and finalized:
            if replaces != previous['record']:
                raise ValueError('changed finalized record must explicitly replace its previous Record link')
            # Earlier releases accepted reused correction cards. Keep their immutable
            # history and retries readable; a new correction needs a newly written card.
            if (unpublished_draft and note_key == edition_key
                    and Path(item['record_note']).stem != edition_key):
                raise ValueError('changed finalized record must link to a distinct new detail card in the current draft')
        elif replaces not in ('-', previous['record']):
            raise ValueError('Replaces does not identify the previous Record link')
        if (first_observation and unpublished_draft and note_key == edition_key
                and Path(item['record_note']).stem != edition_key):
            raise ValueError('newly observed data must link to a new detail card in the current draft')

    for note_key, (path, note, _) in ordered:
        note_day = note['metadata']['date']
        as_of = iso_time(note['metadata']['as_of'])
        for title, columns in JOURNALS.items():
            seen = set()
            for row in note['journals'].get(title, []):
                try:
                    key = (row[columns[0]], row.get('Horizon'))
                    if key in seen:
                        raise ValueError('duplicate journal key in ' + title + ': ' + str(key))
                    seen.add(key)
                    target, section, record_as_of = reference(row['Record'], note_key)
                    common = {'record': row['Record'], 'record_note': target,
                              'record_section': section, 'journal_note': path}
                    if title in ('Recommendation records', 'Checkpoint records'):
                        identifier = row['Recommendation']
                        if identifier not in first or positions[Path(first[identifier]['first_ready_note']).stem] > positions[note_key]:
                            raise ValueError('recommendation has no actual ready state by this date: ' + identifier)
                    if title == 'Recommendation records':
                        if row['First ready'] != first[identifier]['first_ready']:
                            raise ValueError('First ready must match the earliest actual ready state: ' + identifier)
                        baseline = row['Baseline at']
                        if baseline not in ('pending', 'unavailable'):
                            stamp = iso_time(baseline)
                            if (ny_now(stamp).date() <= iso_date(row['First ready']) or stamp > as_of):
                                raise ValueError('baseline must follow First ready in New York and not exceed as_of')
                            first_note = notes[Path(first[identifier]['first_ready_note']).stem][1]
                            if stamp < iso_time(first_note['metadata']['generated_at']):
                                raise ValueError('baseline must not precede the first-ready note\'s generated_at')
                            if stamp > record_as_of:
                                raise ValueError('baseline must not exceed its Record note\'s as_of')
                        previous = recommendations.get(identifier)
                        item = dict(first[identifier], baseline_at=baseline, **common)
                        changed = previous is not None and (
                            event_identity(item['baseline_at']) != event_identity(previous['baseline_at'])
                            or record_identity(item) != record_identity(previous))
                        finalized = previous is not None and previous['baseline_at'] not in ('pending', 'unavailable')
                        correction(row, item, previous, changed, finalized, note_key,
                                   first_observation=previous is not None and not finalized
                                   and baseline not in ('pending', 'unavailable'))
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
                        correction(row, item, previous, changed, finalized, note_key,
                                   first_observation=previous is not None and previous['state'] == 'unavailable'
                                   and item['state'] == 'observed')
                        # Legacy same-card changes cannot make unchanged evidence current.
                        # Repeats retain this flag until an explicit distinct-card correction.
                        item['_needs_card_recheck'] = previous is not None and (
                            record_identity(item) == record_identity(previous)
                            and (previous['_needs_card_recheck'] or (changed and finalized)
                                 or (previous['state'] == 'unavailable' and item['state'] == 'observed')))
                        checkpoints[key] = item
                    elif title == 'Lesson records':
                        identifier = row['Lesson']
                        match = re.fullmatch(r'lesson-(\d{4}-\d{2}-\d{2})-(0[1-9]|[1-9]\d+)', identifier)
                        if (not match or iso_date(match[1]) > iso_date(note_day) or int(match[2]) < 1
                                or row['Status'] not in ('provisional', 'supported', 'retired')):
                            raise ValueError('invalid lesson ID or status: ' + identifier)
                        previous = lessons.get(identifier)
                        if (unpublished_draft and note_key == edition_key and previous is None
                                and match[1] != note_day):
                            raise ValueError('new lesson ID must use its first-recorded note date: ' + identifier)
                        item = dict(id=identifier, status=row['Status'], **common)
                        if (previous is not None and item['status'] != previous['status']
                                and record_identity(item) == record_identity(previous)):
                            raise ValueError('changed lesson status must link to a distinct new detail card')
                        if (unpublished_draft and note_key == edition_key and previous is not None
                                and (item['status'] != previous['status']
                                     or record_identity(item) != record_identity(previous))
                                and Path(item['record_note']).stem != edition_key):
                            raise ValueError('revised lesson must link to a new detail card in the current draft')
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
    if inventory(vault, day, edition, cutoff)[1] != snapshot:
        finding(history['current_note']['path'], 'daily-note history changed during outcome planning; rerun')
    if draft_token is not None and atomic_move.regular_file_snapshot(draft) != draft_token:
        finding(draft, 'draft changed during outcome planning; rerun')
    cutoff = notes[edition_key][1]['metadata']['as_of'] if edition_key in notes else cutoff.isoformat()
    return {'complete': not findings, 'findings': findings, 'date': day,
            'as_of': cutoff, 'mode': mode, 'current_note': history['current_note'],
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


def publish(draft, vault, now=None, mode='scheduled', as_of=None):
    # Distinct edition filenames no longer collide atomically. Serialize helper
    # publishers on the existing vault directory, without a persistent lock file.
    # Advisory locks are released by the OS even after an interrupted process.
    import fcntl
    root = Path(vault).expanduser().resolve(strict=True)
    flags = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(root, flags)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('another market-note publication is in progress; rerun context after it finishes') from exc
        return _publish(draft, root, now, mode, as_of)
    finally:
        os.close(descriptor)


def _publish(draft, vault, now=None, mode='scheduled', as_of=None):
    data, expected = read_stable(draft)
    note = lint_bytes(data)
    current = ny_now(now)
    day = current.date().isoformat()
    if note['metadata']['date'] != day:
        raise ValueError('publication creates only today\'s New York note; no historical backfill')
    if iso_time(note['metadata']['generated_at']) > current:
        raise ValueError('generated_at is in the future')
    if mode == 'manual':
        if as_of is not None and iso_time(as_of) != iso_time(note['metadata']['as_of']):
            raise ValueError('manual --as-of must match the draft as_of')
        as_of = note['metadata']['as_of']
    edition, cutoff = edition_identity(current, mode, as_of)
    cutoff = iso_time(note['metadata']['as_of'])
    history, baseline = inventory(vault, day, edition, cutoff)
    target = Path(history['current_note']['path'])
    if not history['complete']:
        raise ValueError('daily-note history is incomplete: ' + json.dumps(history['findings'], ensure_ascii=False))
    if history['current_note']['state'] == 'valid':
        existing, _ = read_stable(target)
        if existing == data:
            planned = outcomes(vault, draft, current, mode, as_of)
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
    planned = outcomes(vault, draft, current, mode, as_of)
    if not planned['complete']:
        raise ValueError('outcome journal is incomplete: ' + json.dumps(planned['findings'], ensure_ascii=False))
    require_publication_provenance(note['provenance'])
    vault, folder, folder_identity = output_folder(vault, create=True)
    # Folder creation changes an absent-folder baseline, but does not adopt files.
    if baseline[0] is None:
        checked, baseline = inventory(vault, day, edition, cutoff)
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
        _, checked = inventory(vault, day, edition, cutoff)
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
            # Financial-history fixtures predate provenance and intentionally
            # exercise that logic alone. Dedicated tests below restore the real
            # publication gate and cover current-bundle and historical behavior.
            self.provenance_gate = patch(__name__ + '.require_publication_provenance')
            self.provenance_gate.start()
            self.addCleanup(self.provenance_gate.stop)
            self.generator = {'skill': 'investments:market-research', 'plugin_version': '1.2.0',
                              'source_commit': None, 'source_url': None,
                              'source_status': 'unavailable', 'runtime_sha256': 'f' * 64}

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

        def test_manual_identity_uses_live_time_and_frozen_retry(self):
            now = iso_time('2026-09-05T14:05:06.999-04:00')
            first = context(self.vault, now, mode='manual')
            self.assertTrue(first['complete'])
            self.assertEqual(first['as_of'], '2026-09-05T14:05:06-04:00')
            self.assertEqual(Path(first['current_note']['path']).name,
                             '2026-09-05-140506-market-research.md')
            later = now + timedelta(minutes=20)
            retry = context(self.vault, later, mode='manual', as_of=first['as_of'])
            self.assertEqual(retry['current_note'], first['current_note'])
            self.assertEqual(retry['as_of'], first['as_of'])
            new = context(self.vault, later, mode='manual')
            self.assertNotEqual(new['current_note']['path'], first['current_note']['path'])
            self.assertEqual(outcomes(self.vault, now=later, mode='manual', as_of=first['as_of'])['as_of'],
                             first['as_of'])
            for invalid in ('2026-09-04T14:05:06-04:00', '2026-09-05T15:05:06-04:00',
                            '2026-09-05T14:05:06.5-04:00'):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    context(self.vault, now, mode='manual', as_of=invalid)
            with self.assertRaisesRegex(ValueError, 'only supported'):
                context(self.vault, now, as_of=first['as_of'])

        def test_manual_scheduled_manual_editions_preserve_history_and_first_ready(self):
            identifier = 'NYSE:ABC@2026-09-05'
            first_cutoff = '2026-09-05T09:00:00-04:00'
            first_context = context(self.vault, self.now, mode='manual', as_of=first_cutoff)
            first_path = Path(first_context['current_note']['path'])
            first_link = '[[Investments/' + first_path.stem + '#Outcome review]]'
            rows = [(identifier, 'ready', 'Confirmed fixture setup')]
            self.draft.write_bytes(self.note(rows=rows) + ('\n' + self.journal('Recommendation records', [
                (identifier, '2026-09-05', 'pending', first_link, '-')]) + '\n' +
                self.journal('Monthly summaries', [('2026-09', first_link)])).encode())
            lint_bytes(self.draft.read_bytes())
            planned = outcomes(self.vault, self.draft, self.now, mode='manual')
            self.assertTrue(planned['complete'], planned['findings'])
            self.assertEqual(publish(self.draft, self.vault, self.now, mode='manual')['path'], str(first_path))
            original = first_path.read_bytes()
            scheduled_now = iso_time('2026-09-05T11:32:00-04:00')
            scheduled = context(self.vault, scheduled_now)
            self.assertEqual(scheduled['prior_notes'], [str(first_path)])
            self.assertEqual([row['id'] for row in scheduled['active_theses']], [identifier])
            self.draft.write_bytes(self.note(rows=rows, as_of=scheduled['as_of'], generated=scheduled_now.isoformat()))
            middle = Path(publish(self.draft, self.vault, scheduled_now)['path'])
            middle_bytes = middle.read_bytes()
            manual_now = iso_time('2026-09-05T13:02:00-04:00')
            manual = context(self.vault, manual_now, mode='manual', as_of='2026-09-05T13:00:00-04:00')
            self.assertEqual(manual['prior_notes'], [str(first_path), str(middle)])
            latest_link = '[[Investments/' + Path(manual['current_note']['path']).stem + '#Outcome review]]'
            self.draft.write_bytes(self.note(rows=rows, as_of=manual['as_of'], generated=manual_now.isoformat())
                                  + ('\n' + self.journal('Monthly summaries', [('2026-09', latest_link)])).encode())
            latest = publish(self.draft, self.vault, manual_now, mode='manual')
            planned = outcomes(self.vault, now=manual_now, mode='manual', as_of=manual['as_of'])
            self.assertTrue(planned['complete'], planned['findings'])
            self.assertEqual(len(planned['recommendations']), 1)
            self.assertEqual(planned['recommendations'][0]['first_ready_note'], str(first_path))
            self.assertEqual(len(planned['checkpoints']), len(HORIZONS))
            self.assertEqual(planned['latest_monthly_summary']['record_note'], latest['path'])
            self.assertEqual(publish(self.draft, self.vault, manual_now, mode='manual')['status'], 'unchanged')
            self.assertEqual(publish(middle, self.vault, manual_now)['status'], 'unchanged')
            self.assertEqual(outcomes(self.vault, now=manual_now)['latest_monthly_summary']['record_note'], str(first_path))
            self.assertEqual(first_path.read_bytes(), original)
            self.assertEqual(middle.read_bytes(), middle_bytes)
            self.assertEqual(len(list(first_path.parent.glob('*.md'))), 3)

        def test_manual_editions_carry_active_theses_and_cannot_revive_terminal_ids(self):
            identifier = 'NYSE:ABC@2026-09-05'
            first = self.prior('2026-09-05', [(identifier, 'watch', 'Original setup')])
            original = first.read_bytes()
            later = iso_time('2026-09-05T13:02:00-04:00')
            fields = dict(as_of='2026-09-05T13:00:00-04:00', generated=later.isoformat())
            self.draft.write_bytes(self.note(**fields))
            with self.assertRaisesRegex(ValueError, 'carry active'):
                publish(self.draft, self.vault, later, mode='manual')
            self.draft.write_bytes(self.note(rows=[(identifier, 'expired', 'Window ended')], **fields))
            terminal = publish(self.draft, self.vault, later, mode='manual')['path']
            later = later + timedelta(hours=1)
            self.draft.write_bytes(self.note(rows=[(identifier, 'watch', 'Attempted revival')],
                as_of='2026-09-05T14:00:00-04:00', generated=later.isoformat()))
            with self.assertRaisesRegex(ValueError, 'not revival'):
                publish(self.draft, self.vault, later, mode='manual')
            self.assertEqual(first.read_bytes(), original)
            self.assertTrue(Path(terminal).exists())

        def test_terminal_thesis_can_renew_with_a_distinct_manual_edition_id(self):
            first = 'NYSE:ABC@2026-09-05'
            self.outcome_note('2026-09-05', [(first, 'ready', 'Original confirmed setup')], [
                self.journal('Recommendation records', [(first, '2026-09-05', 'pending',
                                                         self.record_link('2026-09-05'), '-')])])
            noon = iso_time('2026-09-05T12:02:00-04:00')
            self.draft.write_bytes(self.note(rows=[(first, 'invalidated', 'Original catalyst failed')],
                as_of='2026-09-05T12:00:00-04:00', generated=noon.isoformat()))
            terminal = publish(self.draft, self.vault, noon, mode='manual')['path']
            later = iso_time('2026-09-05T13:02:00-04:00')
            renewal = first + '-130000'
            record = '[[Investments/2026-09-05-130000-market-research#Outcome review]]'
            self.draft.write_bytes(self.note(rows=[(renewal, 'ready', 'Distinct new catalyst; [[Investments/'
                + Path(terminal).stem + '#Thesis updates]] preserves the failed thesis.')],
                as_of='2026-09-05T13:00:00-04:00', generated=later.isoformat())
                + ('\n' + self.journal('Recommendation records', [(renewal, '2026-09-05', 'pending', record, '-')])).encode())
            result = outcomes(self.vault, self.draft, later, mode='manual')
            self.assertTrue(result['complete'], result['findings'])
            self.assertEqual({row['id'] for row in result['recommendations']}, {first, renewal})
            saved = publish(self.draft, self.vault, later, mode='manual')
            self.assertEqual(publish(saved['path'], self.vault, later, mode='manual')['status'], 'unchanged')
            next_context = context(self.vault, later + timedelta(hours=1), mode='manual')
            self.assertEqual([row['id'] for row in next_context['active_theses']], [renewal])

        def test_new_time_suffixed_thesis_requires_its_exact_manual_edition(self):
            later = iso_time('2026-09-05T13:02:00-04:00')
            for mode, identifier in (('scheduled', 'NYSE:ABC@2026-09-05-130000'),
                                     ('manual', 'NYSE:ABC@2026-09-05-125959')):
                with self.subTest(mode=mode, identifier=identifier):
                    self.draft.write_bytes(self.note(rows=[(identifier, 'watch', 'Fixture setup')],
                        as_of='2026-09-05T13:00:00-04:00', generated=later.isoformat()))
                    result = outcomes(self.vault, self.draft, later, mode=mode)
                    self.assertFalse(result['complete'])
                    self.assertTrue(any('time-suffixed thesis' in finding['error'] for finding in result['findings']))
                    with self.assertRaisesRegex(ValueError, 'time-suffixed thesis'):
                        publish(self.draft, self.vault, later, mode=mode)
            with self.assertRaises(ValueError):
                lint_bytes(self.note(rows=[('NYSE:ABC@2026-09-05-250000', 'watch', 'Invalid time')]))

        def test_missing_scheduled_and_backdated_manual_editions_are_blocked(self):
            late = iso_time('2026-09-05T13:02:00-04:00')
            self.draft.write_bytes(self.note(as_of='2026-09-05T13:00:00-04:00', generated=late.isoformat()))
            published = Path(publish(self.draft, self.vault, late, mode='manual')['path'])
            original = published.read_bytes()
            self.assertFalse(context(self.vault, late)['complete'])
            for mode, cutoff in (('scheduled', '2026-09-05T11:30:00-04:00'),
                                 ('manual', '2026-09-05T12:59:59-04:00')):
                with self.subTest(mode=mode):
                    self.draft.write_bytes(self.note(as_of=cutoff, generated=late.isoformat()))
                    self.assertFalse(outcomes(self.vault, self.draft, late, mode=mode)['complete'])
                    with self.assertRaisesRegex(ValueError, 'out of order'):
                        publish(self.draft, self.vault, late, mode=mode)
            self.assertEqual(published.read_bytes(), original)
            self.assertEqual(len(list(published.parent.glob('*.md'))), 1)

        def test_earlier_cutoff_with_later_publication_cannot_leak_into_manual_history(self):
            path = self.prior('2026-09-05', [])
            path.write_bytes(self.note(generated='2026-09-05T13:02:00-04:00'))
            late = iso_time('2026-09-05T13:05:00-04:00')
            context_result = context(self.vault, late, mode='manual', as_of='2026-09-05T13:00:00-04:00')
            self.assertFalse(context_result['complete'])
            self.assertEqual(context_result['prior_notes'], [])
            self.assertEqual(context_result['later_notes'], [str(path)])

        def test_manual_identity_collisions_and_mismatched_filenames_fail_closed(self):
            cutoff = '2026-09-05T09:00:00-04:00'
            self.draft.write_bytes(self.note())
            saved = Path(publish(self.draft, self.vault, self.now, mode='manual')['path'])
            original = saved.read_bytes()
            self.draft.write_bytes(original.replace(b'Wait for confirmation.', b'Changed decision.'))
            with self.assertRaisesRegex(ValueError, 'different bytes'):
                publish(self.draft, self.vault, self.now, mode='manual')
            with self.assertRaisesRegex(ValueError, 'must match'):
                publish(self.draft, self.vault, self.now, mode='manual', as_of='2026-09-05T09:01:00-04:00')
            self.assertEqual(saved.read_bytes(), original)
            saved.rename(saved.with_name('2026-09-05-090001-market-research.md'))
            result = context(self.vault, self.now, mode='manual', as_of=cutoff)
            self.assertFalse(result['complete'])
            self.assertTrue(any('filename time' in finding['error'] for finding in result['findings']))

        def test_manual_daylight_saving_repeated_wall_clock_collision_is_not_overwritten(self):
            early = iso_time('2026-11-01T01:32:00-04:00')
            self.draft.write_bytes(self.note('2026-11-01', as_of='2026-11-01T01:30:00-04:00',
                                            generated=early.isoformat()))
            path = Path(publish(self.draft, self.vault, early, mode='manual')['path'])
            original = path.read_bytes()
            self.assertEqual(publish(path, self.vault, early, mode='manual')['status'], 'unchanged')
            self.assertTrue(context(self.vault, early, mode='manual',
                                    as_of='2026-11-01T01:30:00-04:00')['complete'])
            late = iso_time('2026-11-01T01:32:00-05:00')
            result = context(self.vault, late, mode='manual', as_of='2026-11-01T01:30:00-05:00')
            self.assertFalse(result['complete'])
            self.assertEqual(result['current_note']['state'], 'blocked')
            self.assertEqual(path.read_bytes(), original)

        def test_manual_cutoff_orders_ambiguous_times_by_instant(self):
            before_fallback = iso_time('2026-11-01T01:45:00-04:00')
            after_fallback = iso_time('2026-11-01T01:15:00-05:00')
            with self.assertRaisesRegex(ValueError, 'nonfuture'):
                context(self.vault, before_fallback, mode='manual', as_of=after_fallback.isoformat())
            accepted = context(self.vault, after_fallback, mode='manual', as_of=before_fallback.isoformat())
            self.assertTrue(accepted['complete'])
            self.assertEqual(accepted['as_of'], before_fallback.isoformat())
            self.draft.write_bytes(self.note('2026-11-01', as_of=after_fallback.isoformat(),
                                            generated=after_fallback.isoformat()))
            saved = Path(publish(self.draft, self.vault, after_fallback, mode='manual')['path'])
            self.assertEqual(publish(saved, self.vault, after_fallback, mode='manual')['status'], 'unchanged')

        def test_same_day_correction_cards_must_belong_to_exact_new_edition(self):
            lesson = 'lesson-2026-09-05-01'
            earlier = self.outcome_note('2026-09-05', journals=[self.journal('Lesson records', [
                (lesson, 'provisional', self.record_link('2026-09-05'))])])
            earlier.write_bytes(earlier.read_bytes() + b'\n#### Unused older card\n\nOriginal evidence.\n')
            now = iso_time('2026-09-05T13:02:00-04:00')
            base = self.note(as_of='2026-09-05T13:00:00-04:00', generated=now.isoformat())
            old = '[[Investments/2026-09-05-market-research#Unused older card]]'
            self.draft.write_bytes(base + ('\n' + self.journal('Lesson records', [(lesson, 'supported', old)])).encode())
            rejected = outcomes(self.vault, self.draft, now, mode='manual')
            self.assertFalse(rejected['complete'])
            self.assertTrue(any('current draft' in finding['error'] for finding in rejected['findings']))
            new = '[[Investments/2026-09-05-130000-market-research#Outcome review]]'
            self.draft.write_bytes(base + ('\n' + self.journal('Lesson records', [(lesson, 'supported', new)])).encode())
            self.assertTrue(outcomes(self.vault, self.draft, now, mode='manual')['complete'])
            publish(self.draft, self.vault, now, mode='manual')

        def test_same_day_future_edition_references_are_rejected(self):
            lesson = 'lesson-2026-09-05-01'
            first = self.outcome_note('2026-09-05', journals=[self.journal('Lesson records', [
                (lesson, 'provisional', '[[Investments/2026-09-05-130000-market-research#Outcome review]]')])])
            late = iso_time('2026-09-05T13:02:00-04:00')
            self.draft.write_bytes(self.note(as_of='2026-09-05T13:00:00-04:00', generated=late.isoformat()))
            result = outcomes(self.vault, self.draft, late, mode='manual')
            self.assertFalse(result['complete'])
            self.assertTrue(any('nonfuture' in finding['error'] for finding in result['findings']))
            self.assertTrue(first.exists())

        def test_publication_lock_prevents_concurrent_editions_without_lock_files(self):
            import fcntl
            descriptor = os.open(self.vault, os.O_RDONLY | os.O_DIRECTORY)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.draft.write_bytes(self.note())
                with self.assertRaisesRegex(ValueError, 'publication is in progress'):
                    publish(self.draft, self.vault, self.now, mode='manual')
            finally:
                os.close(descriptor)
            self.assertEqual(publish(self.draft, self.vault, self.now, mode='manual')['status'], 'created')
            self.assertFalse(list(self.vault.glob('*lock*')))

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

        def test_malformed_offset_minutes_cannot_be_normalized_into_valid_metadata(self):
            for offset in ('-04:60', '-04:99', '+00:60'):
                data = self.note(as_of='2026-09-05T09:00:00' + offset,
                                 generated='2026-09-05T09:02:00' + offset)
                with self.subTest(offset=offset):
                    with self.assertRaisesRegex(ValueError, 'timestamp'):
                        lint_bytes(data)
                    self.draft.write_bytes(data)
                    with self.assertRaisesRegex(ValueError, 'timestamp'):
                        publish(self.draft, self.vault,
                                datetime.fromisoformat('2026-09-05T16:00:00-04:00'))
            self.assertFalse((self.vault / 'Investments').exists())

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

        def test_provenance_footer_is_separate_from_financial_state(self):
            original = self.note()
            stamped = note_provenance.stamp_text(original.decode('utf-8'), self.generator).encode('utf-8')
            old, new = lint_bytes(original), lint_bytes(stamped)
            self.assertIsNone(old.pop('provenance'))
            self.assertEqual(new.pop('provenance'), {'schema': 1, 'generated_by': self.generator})
            self.assertEqual(old, new)
            footer = stamped.decode('utf-8').split('<!-- skill-provenance:', 1)[1]
            for malformed in (
                    stamped + b'\nHidden continuation.\n',
                    stamped + ('\n<!-- skill-provenance:' + footer).encode('utf-8'),
                    original.replace(b'No active theses.', b'<!-- No active theses. -->')
                    + stamped[len(original):],
                    stamped.replace(b'"schema":', b'"financial_state":'),
                    stamped.replace(b'<!-- skill-provenance:', b'<!-- unrelated:')):
                with self.subTest(malformed=malformed), self.assertRaises(ValueError):
                    lint_bytes(malformed)

        def test_new_publication_requires_its_verified_creator(self):
            self.provenance_gate.stop()
            self.draft.write_bytes(self.note())
            with patch(__name__ + '.active_provenance', return_value=self.generator):
                with self.assertRaisesRegex(ValueError, 'skill-provenance footer'):
                    publish(self.draft, self.vault, self.now)
                for change in ({'plugin_version': '0.0.1'}, {'runtime_sha256': 'e' * 64},
                               {'skill': 'knowledge:wiki-build'}):
                    with self.subTest(change=change):
                        self.draft.write_text(note_provenance.stamp_text(
                            self.note().decode('utf-8'), dict(self.generator, **change)), encoding='utf-8')
                        with self.assertRaisesRegex(ValueError, 'executing installed'):
                            publish(self.draft, self.vault, self.now)
                update = {'schema': 1, 'generated_by': self.generator, 'updated_by': self.generator}
                self.draft.write_text(self.note().decode('utf-8').rstrip() + '\n\n'
                                      + '<!-- skill-provenance: ' + json.dumps(update) + ' -->\n', encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'without an update record'):
                    publish(self.draft, self.vault, self.now)
                self.assertFalse((self.vault / 'Investments').exists())
                self.draft.write_text(note_provenance.stamp_text(
                    self.note().decode('utf-8'), self.generator), encoding='utf-8')
                saved = publish(self.draft, self.vault, self.now)
                self.assertEqual(saved['status'], 'created')
                self.assertEqual(Path(saved['path']).read_bytes(), self.draft.read_bytes())

        def test_historical_identical_retry_never_relabels_its_creator(self):
            self.provenance_gate.stop()
            current = self.prior('2026-09-05', [])
            original = current.read_bytes()
            with patch(__name__ + '.active_provenance', side_effect=AssertionError('must not verify a retry')):
                self.assertEqual(publish(current, self.vault, self.now)['status'], 'unchanged')
            self.assertEqual(current.read_bytes(), original)
            self.assertIsNone(lint_bytes(original)['provenance'])

        def test_publisher_rejects_shared_helpers_from_another_bundle(self):
            with patch(__name__ + '._shared', str(self.vault)), \
                    patch.object(note_provenance, 'verified_record') as verify:
                with self.assertRaisesRegex(ValueError, 'executing plugin bundle'):
                    active_provenance()
                verify.assert_not_called()

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

        def test_new_draft_thesis_ids_use_the_first_recorded_note_date(self):
            for state in sorted(STATES):
                for introduced, complete in (('2026-09-04', False), ('2026-09-05', True)):
                    with self.subTest(state=state, introduced=introduced):
                        identifier = 'NYSE:ABC@' + introduced
                        journals = ([self.journal('Recommendation records', [
                            (identifier, '2026-09-05', 'pending', self.record_link('2026-09-05'), '-')])]
                                    if state == 'ready' else [])
                        self.outcome_note('2026-09-05', [(identifier, state, 'Synthetic first record')],
                                          journals, draft=True)
                        result = outcomes(self.vault, self.draft, self.now)
                        self.assertEqual(result['complete'], complete, result['findings'])
                        if not complete:
                            self.assertIn('new thesis ID must use its first-recorded note date',
                                          result['findings'][0]['error'])
                            with self.assertRaisesRegex(ValueError, 'first-recorded note date'):
                                publish(self.draft, self.vault, self.now)
                            self.assertFalse((self.vault / 'Investments').exists())

        def test_legacy_first_recorded_ids_remain_readable_and_keep_their_identity(self):
            identifier = 'NYSE:ABC@2026-09-01'
            lesson = 'lesson-2026-09-01-01'
            prior = self.outcome_note('2026-09-04', [(identifier, 'watch', 'Earlier published ID')], [
                self.journal('Lesson records', [(lesson, 'provisional', self.record_link('2026-09-04'))])])
            original = prior.read_bytes()
            self.outcome_note('2026-09-05', [(identifier, 'watch', 'Carry the stable ID')], [
                self.journal('Lesson records', [(lesson, 'supported', self.record_link('2026-09-05'))])],
                draft=True)
            self.assertTrue(outcomes(self.vault, now=self.now)['complete'])
            checked = outcomes(self.vault, self.draft, self.now)
            self.assertTrue(checked['complete'], checked['findings'])
            self.assertEqual(checked['active_lessons'][0]['id'], lesson)
            self.assertEqual(publish(self.draft, self.vault, self.now)['status'], 'created')
            self.assertEqual(publish(self.draft, self.vault, self.now)['status'], 'unchanged')
            self.assertEqual(prior.read_bytes(), original)

        def test_published_same_day_backdated_ids_allow_read_and_identical_retry(self):
            identifier = 'NYSE:ABC@2026-09-01'
            lesson = 'lesson-2026-09-01-01'
            published = self.outcome_note('2026-09-05', [(identifier, 'watch', 'Published legacy identity')], [
                self.journal('Lesson records', [(lesson, 'provisional', self.record_link('2026-09-05'))])])
            original = published.read_bytes()
            self.assertTrue(outcomes(self.vault, now=self.now)['complete'])
            self.draft.write_bytes(original)
            self.assertTrue(outcomes(self.vault, self.draft, self.now)['complete'])
            self.assertEqual(publish(self.draft, self.vault, self.now)['status'], 'unchanged')
            self.assertEqual(published.read_bytes(), original)
            self.assertFalse(list(self.vault.glob('.market-research-stage-*')))

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
            def changed(vault, day, *edition_args):
                nonlocal calls
                calls += 1
                if calls == 2:
                    self.prior('2026-09-04', [('NYSE:ABC@2026-09-04', 'watch', 'Concurrent thesis')])
                return original(vault, day, *edition_args)
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

        def test_restoring_prior_values_requires_new_correction_cards(self):
            identifier, _, original_baseline = self.baseline_fixture()
            original_checkpoint = self.record_link('2024-03-01')
            self.outcome_note('2024-03-01', journals=[self.journal('Checkpoint records', [
                (identifier, '1m', 'observed', '2024-02-29T16:00:00-05:00', original_checkpoint, '-')])])
            changed_baseline, changed_checkpoint = self.record_link('2024-04-01'), self.record_link('2024-04-02')
            self.outcome_note('2024-04-01', journals=[self.journal('Recommendation records', [
                (identifier, '2024-01-30', '2024-01-31T09:31:00-05:00', changed_baseline, original_baseline)])])
            self.outcome_note('2024-04-02', journals=[self.journal('Checkpoint records', [
                (identifier, '1m', 'observed', '2024-02-29T15:59:00-05:00', changed_checkpoint, original_checkpoint)])])
            originals = {path: path.read_bytes() for path in (self.vault / 'Investments').iterdir()}
            for title, fields, old_card, previous in (
                    ('Recommendation records', (identifier, '2024-01-30', '2024-01-31T09:30:00-05:00'),
                     original_baseline, changed_baseline),
                    ('Checkpoint records', (identifier, '1m', 'observed', '2024-02-29T16:00:00-05:00'),
                     original_checkpoint, changed_checkpoint)):
                for card, complete in ((old_card, False), (self.record_link('2026-09-05'), True)):
                    with self.subTest(title=title, card=card):
                        self.outcome_note('2026-09-05', [(identifier, 'watch', 'Carry the original thesis')],
                                          journals=[self.journal(title, [
                            fields + (card, previous)])], draft=True)
                        result = outcomes(self.vault, self.draft, self.now)
                        self.assertEqual(result['complete'], complete, result['findings'])
                        if not complete:
                            self.assertIn('distinct new detail card', result['findings'][0]['error'])
                            with self.assertRaisesRegex(ValueError, 'distinct new detail card'):
                                publish(self.draft, self.vault, self.now)
                            self.assertFalse((self.vault / 'Investments/2026-09-05-market-research.md').exists())
            restored_baseline = self.record_link('2026-09-05').replace('#Outcome review', '#Restored baseline')
            restored_checkpoint = self.record_link('2026-09-05').replace('#Outcome review', '#Restored checkpoint')
            self.outcome_note('2026-09-05', [(identifier, 'watch', 'Carry the original thesis')], journals=[
                self.journal('Recommendation records', [
                    (identifier, '2024-01-30', '2024-01-31T09:30:00-05:00', restored_baseline, changed_baseline)]),
                self.journal('Checkpoint records', [
                    (identifier, '1m', 'observed', '2024-02-29T16:00:00-05:00', restored_checkpoint, changed_checkpoint)])],
                draft=True)
            self.draft.write_bytes(self.draft.read_bytes() + (
                '\n#### Restored baseline\n\nSynthetic evidence corrects the mistaken update: '
                + changed_baseline + '.\n\n#### Restored checkpoint\n\nSynthetic recalculation restores the prior value: '
                + changed_checkpoint + '.\n').encode())
            self.assertEqual(publish(self.draft, self.vault, self.now)['status'], 'created')
            restored = outcomes(self.vault, now=self.now)
            self.assertEqual(restored['recommendations'][0]['baseline_at'], '2024-01-31T09:30:00-05:00')
            checkpoint = next(row for row in restored['checkpoints'] if row['horizon'] == '1m')
            self.assertEqual(checkpoint['state'], 'observed')
            self.assertEqual(checkpoint['observed_at'], '2024-02-29T16:00:00-05:00')
            self.assertEqual(publish(self.draft, self.vault, self.now)['status'], 'unchanged')
            self.assertEqual({path: path.read_bytes() for path in originals}, originals)

        def test_published_same_day_legacy_corrections_allow_read_and_identical_retry(self):
            identifier, _, baseline_link = self.baseline_fixture()
            observation_link = self.record_link('2024-03-01')
            self.outcome_note('2024-03-01', journals=[self.journal('Checkpoint records', [
                (identifier, '1m', 'observed', '2024-02-29T16:00:00-05:00', observation_link, '-')])])
            published = self.outcome_note('2026-09-05', journals=[
                self.journal('Recommendation records', [
                    (identifier, '2024-01-30', '2024-01-31T09:31:00-05:00', baseline_link, baseline_link)]),
                self.journal('Checkpoint records', [
                    (identifier, '1m', 'observed', '2024-02-29T15:59:00-05:00', observation_link, observation_link)])])
            original = published.read_bytes()
            indexed = outcomes(self.vault, now=self.now)
            self.assertTrue(indexed['complete'], indexed['findings'])
            self.assertEqual(next(row for row in indexed['checkpoints'] if row['horizon'] == '1m')['state'],
                             'needs-recheck')
            self.draft.write_bytes(original)
            retry = outcomes(self.vault, self.draft, self.now)
            self.assertTrue(retry['complete'], retry['findings'])
            self.assertEqual(retry['checkpoints'], indexed['checkpoints'])
            self.assertEqual(publish(self.draft, self.vault, self.now)['status'], 'unchanged')
            self.assertEqual(published.read_bytes(), original)
            self.assertFalse(list(self.vault.glob('.market-research-stage-*')))

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

        def test_legacy_observation_on_missing_data_card_remains_due_until_explicit_resolution(self):
            identifier, _, _ = self.baseline_fixture()
            missing_link = self.record_link('2024-03-01')
            alias = missing_link.replace('Investments/', '').replace('-research#', '-research.md#')
            observed_at = '2024-02-29T16:00:00-05:00'
            self.outcome_note('2024-03-01', journals=[self.journal('Checkpoint records', [
                (identifier, '1m', 'unavailable', '-', missing_link, '-')])])
            self.outcome_note('2024-03-02', journals=[self.journal('Checkpoint records', [
                (identifier, '1m', 'observed', observed_at, missing_link, '-')])])
            repeated = self.outcome_note('2026-09-05', [(identifier, 'watch', 'Carry the earlier thesis')], [
                self.journal('Checkpoint records', [(identifier, '1m', 'observed', observed_at, alias, '-')])])
            originals = {path: path.read_bytes() for path in (self.vault / 'Investments').iterdir()}
            result = outcomes(self.vault, now=self.now)
            self.assertTrue(result['complete'], result['findings'])
            checkpoint = next(row for row in result['checkpoints'] if row['horizon'] == '1m')
            self.assertEqual(checkpoint['state'], 'needs-recheck')
            self.assertIn(checkpoint, result['due_checkpoints'])
            self.assertEqual(publish(repeated, self.vault, self.now)['status'], 'unchanged')

            next_day = '2026-09-06'
            next_now = datetime.fromisoformat(next_day + 'T09:03:00-04:00')
            for replaces, complete in (('-', False), (alias, True)):
                with self.subTest(replaces=replaces):
                    self.outcome_note(next_day, [(identifier, 'watch', 'Carry the earlier thesis')], [
                        self.journal('Checkpoint records', [(identifier, '1m', 'observed', observed_at,
                                                            self.record_link(next_day), replaces)])], draft=True)
                    repaired = outcomes(self.vault, self.draft, next_now)
                    self.assertEqual(repaired['complete'], complete, repaired['findings'])
                    if not complete:
                        with self.assertRaisesRegex(ValueError, 'explicitly replace'):
                            publish(self.draft, self.vault, next_now)
                        self.assertFalse((self.vault / 'Investments/2026-09-06-market-research.md').exists())
            self.assertEqual(publish(self.draft, self.vault, next_now)['status'], 'created')
            self.assertEqual(publish(self.draft, self.vault, next_now)['status'], 'unchanged')
            repaired = outcomes(self.vault, now=next_now)
            self.assertTrue(repaired['complete'], repaired['findings'])
            self.assertEqual(next(row['state'] for row in repaired['checkpoints'] if row['horizon'] == '1m'),
                             'observed')
            self.assertNotIn('1m', [row['horizon'] for row in repaired['due_checkpoints']])
            self.assertEqual({path: path.read_bytes() for path in originals}, originals)

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

        def test_late_baseline_observation_requires_a_current_evidence_card(self):
            identifier, _, old_link = self.baseline_fixture()
            old_path = self.vault / 'Investments/2024-01-31-market-research.md'
            observed = old_path.read_bytes()
            for unavailable in ('pending', 'unavailable'):
                original = observed.replace(b'2024-01-31T09:30:00-05:00', unavailable.encode())
                old_path.write_bytes(original)
                for record, complete in ((old_link, False), (self.record_link('2026-09-05'), True)):
                    with self.subTest(unavailable=unavailable, record=record):
                        self.outcome_note('2026-09-05', [(identifier, 'watch', 'Carry the earlier thesis')], [
                            self.journal('Recommendation records', [(identifier, '2024-01-30',
                                '2024-01-31T09:30:00-05:00', record, '-')])], draft=True)
                        result = outcomes(self.vault, self.draft, self.now)
                        self.assertEqual(result['complete'], complete, result['findings'])
                        if not complete:
                            with self.assertRaisesRegex(ValueError, 'current draft'):
                                publish(self.draft, self.vault, self.now)
                            self.assertFalse((self.vault / 'Investments/2026-09-05-market-research.md').exists())
                self.assertEqual(old_path.read_bytes(), original)
            self.assertEqual(publish(self.draft, self.vault, self.now)['status'], 'created')
            self.assertEqual(publish(self.draft, self.vault, self.now)['status'], 'unchanged')
            self.assertEqual(outcomes(self.vault, now=self.now)['recommendations'][0]['record'],
                             self.record_link('2026-09-05'))

        def test_late_checkpoint_observation_requires_a_current_evidence_card(self):
            identifier, _, _ = self.baseline_fixture()
            old_link = self.record_link('2024-03-01')
            old_path = self.outcome_note('2024-03-01', journals=[self.journal('Checkpoint records', [
                (identifier, '1m', 'unavailable', '-', old_link, '-')])])
            original = old_path.read_bytes()
            for record, complete in ((old_link, False), (self.record_link('2026-09-05'), True)):
                with self.subTest(record=record):
                    self.outcome_note('2026-09-05', [(identifier, 'watch', 'Carry the earlier thesis')], [
                        self.journal('Checkpoint records', [(identifier, '1m', 'observed',
                            '2024-02-29T16:00:00-05:00', record, '-')])], draft=True)
                    result = outcomes(self.vault, self.draft, self.now)
                    self.assertEqual(result['complete'], complete, result['findings'])
                    if not complete:
                        with self.assertRaisesRegex(ValueError, 'current draft'):
                            publish(self.draft, self.vault, self.now)
                        self.assertFalse((self.vault / 'Investments/2026-09-05-market-research.md').exists())
            self.assertEqual(publish(self.draft, self.vault, self.now)['status'], 'created')
            self.assertEqual(publish(self.draft, self.vault, self.now)['status'], 'unchanged')
            checkpoint = next(row for row in outcomes(self.vault, now=self.now)['checkpoints']
                              if row['horizon'] == '1m')
            self.assertEqual(checkpoint['state'], 'observed')
            self.assertEqual(checkpoint['record'], self.record_link('2026-09-05'))
            self.assertEqual(old_path.read_bytes(), original)

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

        def test_lesson_revisions_cannot_reuse_an_older_version_card(self):
            identifier = 'lesson-2026-08-01-01'
            original_link = self.record_link('2026-08-01')
            self.outcome_note('2026-08-01', journals=[self.journal('Lesson records', [
                (identifier, 'provisional', original_link)])])
            self.outcome_note('2026-08-02', journals=[self.journal('Lesson records', [
                (identifier, 'supported', self.record_link('2026-08-02'))])])
            for status in ('provisional', 'supported', 'retired'):
                for card, complete in ((original_link, False), (self.record_link('2026-09-05'), True)):
                    with self.subTest(status=status, card=card):
                        self.outcome_note('2026-09-05', journals=[self.journal('Lesson records', [
                            (identifier, status, card)])], draft=True)
                        result = outcomes(self.vault, self.draft, self.now)
                        self.assertEqual(result['complete'], complete, result['findings'])
                        if not complete:
                            self.assertIn('new detail card in the current draft', result['findings'][0]['error'])
                            with self.assertRaisesRegex(ValueError, 'new detail card in the current draft'):
                                publish(self.draft, self.vault, self.now)

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

        def test_new_draft_lesson_ids_use_the_first_recorded_note_date(self):
            for status in ('provisional', 'supported', 'retired'):
                for introduced, complete in (('2026-09-04', False), ('2026-09-05', True)):
                    with self.subTest(status=status, introduced=introduced):
                        identifier = 'lesson-' + introduced + '-01'
                        self.outcome_note('2026-09-05', journals=[self.journal('Lesson records', [
                            (identifier, status, self.record_link('2026-09-05'))])], draft=True)
                        result = outcomes(self.vault, self.draft, self.now)
                        self.assertEqual(result['complete'], complete, result['findings'])
                        if not complete:
                            self.assertIn('new lesson ID must use its first-recorded note date',
                                          result['findings'][0]['error'])
                            with self.assertRaisesRegex(ValueError, 'first-recorded note date'):
                                publish(self.draft, self.vault, self.now)
                            self.assertFalse((self.vault / 'Investments').exists())

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
    for run_parser in (context_parser, outcomes_parser, publish_parser):
        run_parser.add_argument('--mode', choices=('scheduled', 'manual'), default='scheduled')
        run_parser.add_argument('--as-of', help='fixed manual run timestamp returned by context')
    args = parser.parse_args(argv)
    if args.test:
        return 0 if run_self_test() else 1
    try:
        if args.command == 'context':
            result = context(args.vault, mode=args.mode, as_of=args.as_of)
        elif args.command == 'outcomes':
            result = outcomes(args.vault, args.draft, mode=args.mode, as_of=args.as_of)
        elif args.command == 'lint':
            result = lint_bytes(read_stable(args.note)[0])
        elif args.command == 'publish':
            result = publish(args.draft, args.vault, mode=args.mode, as_of=args.as_of)
        else:
            parser.error('choose context, outcomes, lint, publish or --test')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get('complete', True) else 2
    except (ValueError, OSError, UnicodeError, RuntimeError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        return 3 if isinstance(exc, RuntimeError) else 2


if __name__ == '__main__':
    raise SystemExit(main())
