#!/usr/bin/env python3
"""Replay visible daily coverage journals; no network, collection or vault writes.

The journal accounts for work, not the truth of an investment judgment. Historical
reports without journals require an explicit hash-bound bootstrap review.
"""
from __future__ import annotations
import argparse
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest

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

TABLES = {
    'Coverage history': ('Report', 'SHA256'),
    'Feed dispositions': ('Post', 'Fingerprint', 'Published', 'Disposition', 'Securities', 'Due', 'Reason'),
    'Research queue': ('Security', 'First seen', 'State', 'Priority', 'Due', 'Sources', 'Assessment', 'Reason'),
}
SECURITY = re.compile(r'[A-Z][A-Z0-9]{1,15}:[A-Z][A-Z0-9.-]{0,14}\Z')
POST = re.compile(r'https://x\.com/i/web/status/([1-9][0-9]{0,24})\Z')
HASH = re.compile(r'[a-f0-9]{64}\Z')
REPORT = re.compile(r'\[\[(Investments/\d{4}-\d{2}-\d{2}(?:-\d{6})?-(?:stock|market)-research)(?:\.md)?\]\]\Z')
ASSESSMENT = re.compile(r'\[\[(Investments/(?:\d{4}-\d{2}-\d{2}(?:-\d{6})?-(?:stock|market)-research|'
                        r'\.stock-research/dossiers/evidence/[a-f0-9]{64}))(?:\.md)?#([^\]\n|]+)\]\]\Z')
POST_STATES = {'nominated', 'repeated', 'no-idea', 'excluded', 'pending', 'blocked'}
WORK_STATES = {'queued', 'blocked', 'assessed', 'reused', 'monitored', 'closed'}
UNFINISHED = {'queued', 'blocked'}
UNRESOLVED = {'pending', 'blocked'}
PRIORITIES = ('active', 'capacity', 'due', 'new')


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _time(value):
    import market_notes
    return market_notes.iso_time(value)


def _list(value):
    if value == '-':
        return []
    items = [item.strip() for item in value.split(',')]
    if any(not item for item in items) or len(set(items)) != len(items):
        raise ValueError('coverage list has empty or duplicate entries')
    return items


def parse(data):
    """Pure journal parser. Does not call lint_bytes or read any files."""
    import market_notes
    text, _ = market_notes.note_provenance.split_provenance(data.decode('utf-8'))
    lines = text.splitlines()
    if not lines or lines[0] != '---':
        raise ValueError('coverage note needs frontmatter')
    end = lines.index('---', 1)
    meta = dict(line.split(': ', 1) for line in lines[1:end])
    cutoff = _time(meta['as_of'].strip('"\''))
    sections = market_notes.note_sections('\n'.join(lines[end + 1:]).strip().splitlines())
    found = {}
    for section, body in sections.items():
        rows = body.splitlines()
        headings = [(i, len(match[1]), (match[2] or '').strip()) for i, line in enumerate(rows)
                    if (match := market_notes.ATX.fullmatch(line))]
        for i, depth, title in headings:
            if title.casefold() not in {name.casefold() for name in TABLES}:
                continue
            if section != 'Screening and sources' or depth != 4 or title not in TABLES or title in found:
                raise ValueError('coverage journals require unique exact H4 headings in Screening and sources')
            stop = next((at for at, level, _ in headings if at > i and level <= depth), len(rows))
            table = '\n'.join(rows[i + 1:stop]).strip().splitlines()
            fields = TABLES[title]
            if (len(table) < 2 or market_notes.table_cells(table[0], len(fields)) != list(fields)
                    or any(not re.fullmatch(r':?-{3,}:?', cell)
                           for cell in market_notes.table_cells(table[1], len(fields)))):
                raise ValueError(title + ' requires its exact table; an empty header/separator is allowed')
            found[title] = []
            for line in table[2:]:
                values = market_notes.table_cells(line, len(fields))
                if not all(values):
                    raise ValueError('empty coverage cell; use - when not applicable')
                found[title].append(dict(zip(fields, values)))
    if not found:
        if meta.get('stock_research') == '2':
            raise ValueError('stock_research: 2 requires all three coverage journals')
        return None
    if set(found) != set(TABLES):
        raise ValueError('include all three coverage journals together')
    seen = set()
    for row in found['Coverage history']:
        match = REPORT.fullmatch(row['Report'])
        if not match or not HASH.fullmatch(row['SHA256']) or match[1] in seen:
            raise ValueError('invalid or duplicate coverage history anchor')
        seen.add(match[1])
    seen = set()
    for row in found['Feed dispositions']:
        match = POST.fullmatch(row['Post'])
        if (not match or match[1] in seen or not HASH.fullmatch(row['Fingerprint'])
                or row['Disposition'] not in POST_STATES or _time(row['Published']) > cutoff):
            raise ValueError('invalid or duplicate feed disposition')
        seen.add(match[1])
        names = _list(row['Securities'])
        if any(not SECURITY.fullmatch(name) for name in names):
            raise ValueError('feed securities need verified EXCHANGE:TICKER identities')
        if (row['Disposition'] in {'nominated', 'repeated'} and not names
                or row['Disposition'] in {'no-idea', 'excluded'} and names):
            raise ValueError('feed nomination/disposition and securities disagree')
        if row['Due'] != '-':
            _time(row['Due'])
        elif row['Disposition'] in UNRESOLVED:
            raise ValueError('unresolved feed work requires a retry timestamp')
    seen = set()
    for row in found['Research queue']:
        if (not SECURITY.fullmatch(row['Security']) or row['Security'] in seen
                or row['State'] not in WORK_STATES or row['Priority'] not in PRIORITIES
                or _time(row['First seen']) > cutoff):
            raise ValueError('invalid or duplicate research queue row')
        seen.add(row['Security'])
        if row['Due'] != '-':
            if _time(row['Due']) < _time(row['First seen']):
                raise ValueError('queue due timestamp precedes first seen')
        elif row['State'] in UNFINISHED or row['State'] == 'monitored':
            raise ValueError('unfinished/monitored work requires a next-review timestamp')
        origins = _list(row['Sources'])
        if not origins or any(not (re.fullmatch(r'[1-9][0-9]{0,24}', origin) or origin == 'user'
                or re.fullmatch(r'legacy:\d{4}-\d{2}-\d{2}(?:-\d{6})?-(?:stock|market)-research\.md', origin))
                for origin in origins):
            raise ValueError('queue sources must name post IDs, user, or an explicit legacy report')
        if row['Assessment'] != '-' and not ASSESSMENT.fullmatch(row['Assessment']):
            raise ValueError('assessment must link an exact dated Candidate assessments H4')
        if row['State'] in {'assessed', 'reused', 'monitored'} and row['Assessment'] == '-':
            raise ValueError('completed/reused work requires an assessment link')
    return found


def fingerprint(post):
    """Changed text or attachment evidence is new; unrelated account edits are not."""
    assets = [{key: item.get(key) for key in ('asset_key', 'status', 'eligible', 'sha256')}
              for item in post.get('attachments', [])]
    value = {'post_id': post['post_id'], 'excerpt_sha256': post['excerpt_sha256'],
             'attachments': assets, 'references': post.get('references', []),
             'repost_text_may_be_truncated': post.get('repost_text_may_be_truncated', False)}
    return _hash(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


def _anchors(reports):
    last = next((i for i in range(len(reports) - 1, -1, -1) if reports[i]['journals'] is not None), None)
    selected = reports[last:] if last is not None else reports
    return [{'Report': '[[' + report['relative'][:-3] + ']]', 'SHA256': report['sha256']}
            for report in selected]


def _bootstrap_required(reports):
    return bool(reports and reports[-1]['journals'] is None)


def _history(vault, cutoff):
    import market_notes
    import stock_dossiers
    day = market_notes.ny_now(cutoff).date().isoformat()
    inventory, baseline = market_notes.inventory(vault, day, '__coverage_context__', cutoff, continuation=True)
    # Inventory's publication-order guard does not make a historical read unsafe.
    failures = [item for item in inventory['findings'] if not item['error'].startswith('a later edition already exists;')]
    if failures:
        raise ValueError('coverage history is incomplete: ' + json.dumps(failures))
    reports, posts, jobs = [], {}, {}
    for name in inventory['prior_notes']:
        data, token = market_notes.read_stable(Path(name))
        if baseline[2].get(name) != token:
            raise ValueError('daily history changed during coverage replay')
        linted = market_notes.lint_bytes(data)
        meta = linted['metadata']
        if _time(meta['as_of']) >= cutoff or _time(meta['generated_at']) > cutoff:
            continue
        journals = parse(data)
        report = {'relative': 'Investments/' + Path(name).name, 'sha256': _hash(data),
                  'as_of': meta['as_of'], 'generated_at': meta['generated_at'], 'journals': journals,
                  'theses': linted['theses'],
                  'candidates': stock_dossiers.candidates(data), 'token': token,
                  'legacy_text': data.decode('utf-8') if journals is None else None}
        if journals is not None:
            if journals['Coverage history'] != _anchors(reports):
                raise ValueError('coverage history anchor is missing, changed or out of order: ' + report['relative'])
            _continuity(posts, jobs, journals, cutoff=_time(meta['as_of']))
            for row in journals['Feed dispositions']:
                posts[POST.fullmatch(row['Post'])[1]] = dict(row, report=report['relative'])
            new_arguments = {security for post in journals['Feed dispositions']
                             if post['Disposition'] == 'nominated' for security in _list(post['Securities'])}
            for row in journals['Research queue']:
                old = jobs.get(row['Security'], {})
                checked_at = meta['as_of'] if row['State'] in {'assessed', 'monitored'} else old.get('checked_at')
                requires_assessment = (row['State'] not in {'assessed', 'closed'} and
                                       (row['State'] == 'queued' or row['Security'] in new_arguments
                                        or old.get('requires_assessment', False)))
                jobs[row['Security']] = dict(row, report=report['relative'], checked_at=checked_at,
                                             requires_assessment=requires_assessment)
        reports.append(report)
    for report in reports:
        if market_notes.read_stable(Path(vault) / report['relative'])[1] != report['token']:
            raise ValueError('daily history changed during coverage replay')
    return inventory, reports, posts, jobs


def _continuity(posts, jobs, journals, *, cutoff):
    current_posts = {POST.fullmatch(row['Post'])[1]: row for row in journals['Feed dispositions']}
    current_jobs = {row['Security']: row for row in journals['Research queue']}
    for identity, previous in posts.items():
        if previous['Disposition'] in UNRESOLVED and identity not in current_posts:
            raise ValueError('carry or explicitly resolve unfinished feed work: ' + identity)
    for security, previous in jobs.items():
        due = previous['Due'] != '-' and _time(previous['Due']) <= cutoff
        if (previous['State'] in UNFINISHED or due) and security not in current_jobs:
            raise ValueError('carry or explicitly resolve unfinished/due research: ' + security)
        if security in current_jobs and current_jobs[security]['First seen'] != previous['First seen']:
            raise ValueError('preserve first-seen time across research updates: ' + security)
        if (previous['State'] in UNFINISHED and security in current_jobs
                and not set(_list(previous['Sources'])).issubset(_list(current_jobs[security]['Sources']))):
            raise ValueError('preserve every source association of unfinished research: ' + security)


def _assessment_continuity(jobs, current_jobs):
    # Older runtimes could accidentally clear material work through reuse.
    # Keep those immutable editions readable and recover their still-unfinished
    # obligation; only a new publication must satisfy this stricter check.
    for security, previous in jobs.items():
        if not previous.get('requires_assessment'):
            continue
        current = current_jobs.get(security)
        if current is None:
            raise ValueError('carry or explicitly resolve unfinished substantive research: ' + security)
        if current['State'] in {'reused', 'monitored'}:
            raise ValueError('unfinished substantive research cannot be completed by reuse or monitoring: ' + security)
        if not set(_list(previous['Sources'])).issubset(_list(current['Sources'])):
            raise ValueError('preserve every source association of unfinished research: ' + security)


def _snapshot(vault, cutoff, since, supplied, retained_ids=()):
    import stock_feed
    try:
        snapshot = stock_feed.context(vault, cutoff.isoformat(), since.isoformat(),
                                      retained_post_ids=list(retained_ids) or None)
    except (stock_feed.IntakeError, stock_feed.feed.FeedError,
            stock_feed.feed.feed_media.MediaError, ValueError, OSError) as exc:
        snapshot = {'since': since.isoformat(), 'cutoff': cutoff.isoformat(), 'posts': [], 'accounts': [],
                    'status': 'unavailable', 'snapshot_sha256': None,
                    'intake_error': str(exc)[:1000]}
    if supplied is not None and supplied != snapshot:
        raise ValueError('supplied feed snapshot no longer matches the verified local sources')
    return snapshot


def _state(vault, as_of, since=None, feed_snapshot=None):
    cutoff = _time(as_of)
    inventory, reports, posts, jobs = _history(vault, cutoff)
    floor = cutoff - timedelta(days=3)
    if since is not None:
        floor = min(floor, _time(since))
    retained = set()
    for identity, row in posts.items():
        if row['Disposition'] in UNRESOLVED:
            floor = min(floor, _time(row['Published']))
            retained.add(identity)
    for job in jobs.values():
        if (job['State'] in UNFINISHED or job.get('requires_assessment')
                or job['Due'] != '-' and _time(job['Due']) <= cutoff):
            for origin in _list(job['Sources']):
                if origin in posts:
                    floor = min(floor, _time(posts[origin]['Published']))
                    retained.add(origin)
    snapshot = _snapshot(vault, cutoff, floor, feed_snapshot, sorted(retained, key=int))
    eligible = {post['post_id']: post for post in snapshot['posts']}
    active = {row['id'].split('@', 1)[0] for row in inventory['active_theses']}
    return cutoff, reports, posts, jobs, snapshot, eligible, active


def _summary(state):
    cutoff, reports, posts, jobs, snapshot, eligible, active = state
    unseen = [{'post_id': identity, 'source_url': post['source_url'], 'published': post['created_at'],
               'fingerprint': fingerprint(post)} for identity, post in eligible.items()
              if identity not in posts or posts[identity]['Fingerprint'] != fingerprint(post)]
    pending = [dict(row, post_id=identity, source_available=identity in eligible)
               for identity, row in posts.items() if row['Disposition'] in UNRESOLVED]
    work = []
    for security in sorted(set(jobs) | active):
        row = jobs.get(security)
        due = row is not None and row['Due'] != '-' and _time(row['Due']) <= cutoff
        if security not in active and (row is None or row['State'] not in UNFINISHED
                                       and not row.get('requires_assessment') and not due):
            continue
        priority = ('active' if security in active else
                    'capacity' if row and (row['State'] == 'queued' or
                        row.get('requires_assessment') and row['State'] not in UNFINISHED)
                    else 'due')
        work.append({'security': security, 'priority': priority, 'due': row['Due'] if row else None,
                     'first_seen': row['First seen'] if row else None,
                     'age_days': max(0, (cutoff - _time(row['First seen'])).days) if row else None,
                     'previous_state': row['State'] if row else None,
                     'requires_assessment': row.get('requires_assessment', False) if row else False,
                     'reason': row['Reason'] if row else 'Existing active thesis requires monitoring.'})
    work.sort(key=lambda row: (PRIORITIES.index(row['priority']),
                              _time(row['first_seen']) if row['first_seen'] else cutoff - timedelta(days=100000),
                              row['security']))
    return {'schema': 1, 'as_of': cutoff.isoformat(), 'since': snapshot['since'],
            'complete': True, 'feed_status': snapshot['status'], 'snapshot_sha256': snapshot['snapshot_sha256'],
            'intake_error': snapshot.get('intake_error'),
            'retained_sources': snapshot.get('retained_sources', []),
            'feed_diagnostics': [{key: row.get(key) for key in ('handle', 'gaps', 'omitted_posts')}
                                 for row in snapshot['accounts']],
            'bootstrap_required': _bootstrap_required(reports),
            'required_history': _anchors(reports), 'new_or_changed_posts': unseen,
            'unresolved_posts': pending, 'work': work, 'active_securities': sorted(active),
            'research_complete': snapshot['status'] == 'ready' and not unseen and not pending and not work,
            'counts': {'eligible_posts': len(eligible), 'new_or_changed_posts': len(unseen),
                       'unresolved_posts': len(pending), 'required_securities': len(work)},
            'limitations': ['Coverage journals verify accounting, not nomination completeness or financial judgments.',
                           'Bootstrap hashes attest review of actual legacy bytes; they never repair conflicted dossier evidence.']}


def context(vault, as_of, *, since=None, feed_snapshot=None):
    return _summary(_state(vault, as_of, since, feed_snapshot))


def _verified_assessment(vault, link, security, reports, cutoff, *, _lock_descriptor=None):
    import stock_dossiers
    import stock_feed
    match = ASSESSMENT.fullmatch(link)
    if match is None:
        raise ValueError('missing exact assessment link: ' + security)
    relative, heading = match[1] + '.md', match[2]
    audit = stock_dossiers.context(vault, security.split(':', 1)[1], cutoff.isoformat(),
                                   _lock_descriptor=_lock_descriptor)
    if relative.startswith('Investments/.stock-research/dossiers/evidence/'):
        verified = next((row for row in audit['history'] if row['evidence_note'] == relative
                         and row['daily_sha256'] == Path(relative).stem), None)
        if verified is None:
            raise ValueError('archive assessment lacks a verified security-bound receipt: ' + relative)
        if _time(verified['as_of']) >= cutoff or _time(verified['generated_at']) > cutoff:
            raise ValueError('archive assessment is later than the reuse cutoff')
        raw = stock_feed.read(Path(vault), relative)
        if _hash(raw) != verified['daily_sha256']:
            raise ValueError('preserved assessment evidence changed')
        rows = stock_dossiers.candidates(raw)
    else:
        report = next((row for row in reports if row['relative'] == relative), None)
        if report is None:
            raise ValueError('reuse assessment is absent, later than cutoff, or not a daily report: ' + relative)
        if any(row.get('path', row['daily_note']) == relative for row in audit['history_diagnostics']):
            verified = next((row for row in audit['history'] if row['daily_note'] == relative), None)
            if verified is None:
                raise ValueError('reuse source is quarantined without verified original: ' + relative)
            raise ValueError('public assessment link is quarantined; link the verified archive original instead: ' + relative)
        rows = report['candidates']
    if not any(row['exchange'] + ':' + row['ticker'] == security and row['heading'] == heading for row in rows):
        raise ValueError('reuse link does not identify that security\'s actual assessment')


def check(vault, draft, as_of, *, since=None, feed_snapshot=None, edition=None, _lock_descriptor=None):
    """Validate accounting before publication; legitimate blocked work can publish."""
    import market_notes
    import stock_dossiers
    data, token = market_notes.read_stable(Path(draft))
    linted = market_notes.lint_bytes(data)
    meta = linted['metadata']
    if _time(meta['as_of']) != _time(as_of):
        raise ValueError('coverage cutoff must equal the draft cutoff')
    journals = parse(data)
    if journals is None:
        raise ValueError('new publications require coverage journals')
    state = _state(vault, as_of, since, feed_snapshot)
    cutoff, reports, posts, jobs, snapshot, eligible, active = state
    if journals['Coverage history'] != _anchors(reports):
        raise ValueError('coverage history must match required prior report hashes exactly')
    _continuity(posts, jobs, journals, cutoff=cutoff)
    current_posts = {POST.fullmatch(row['Post'])[1]: row for row in journals['Feed dispositions']}
    current_jobs = {row['Security']: row for row in journals['Research queue']}
    _assessment_continuity(jobs, current_jobs)
    changes = {identity for identity, post in eligible.items()
               if identity not in posts or posts[identity]['Fingerprint'] != fingerprint(post)}
    if changes - set(current_posts):
        raise ValueError('every new or changed eligible post needs a disposition: ' + ', '.join(sorted(changes - set(current_posts))))
    for identity, row in current_posts.items():
        source = eligible.get(identity)
        if source is None:
            old = posts.get(identity)
            if (old is None or old['Disposition'] not in UNRESOLVED or row['Disposition'] not in {'pending', 'blocked'}
                    or row['Fingerprint'] != old['Fingerprint'] or row['Published'] != old['Published']):
                raise ValueError('feed disposition lacks eligible current or retained unresolved evidence: ' + identity)
        elif row['Fingerprint'] != fingerprint(source) or _time(row['Published']) != _time(source['created_at']):
            raise ValueError('post fingerprint/publication timestamp disagrees with verified feed: ' + identity)
        if row['Disposition'] in {'nominated', 'repeated'}:
            for security in _list(row['Securities']):
                if security not in current_jobs:
                    raise ValueError('nominated security needs a research disposition: ' + security)
                if identity not in _list(current_jobs[security]['Sources']):
                    raise ValueError('research disposition must retain every nominating post ID: ' + security)
                if row['Disposition'] == 'nominated' and current_jobs[security]['State'] not in {'assessed', 'queued', 'blocked'}:
                    raise ValueError('a declared new/material nomination requires assessment, queued work or an explicit blocker')
                if row['Disposition'] == 'repeated' and current_jobs[security]['State'] == 'closed':
                    raise ValueError('a repeated argument needs verified coverage, not an unsupported closed job')
    candidates = {row['exchange'] + ':' + row['ticker']: row for row in stock_dossiers.candidates(data)}
    if set(candidates) - set(current_jobs):
        raise ValueError('every actual stock assessment needs a research queue disposition')
    if candidates:
        stock_dossiers.validate_identities(vault, candidates.values(), _lock_descriptor=_lock_descriptor)
    source_rows = {**posts, **current_posts}
    report_names = {Path(row['relative']).name: row for row in reports}
    current_name = edition or market_notes.run_identity(vault, market_notes.ny_now(cutoff), 'manual', as_of)[1]
    valid_names = {market_notes.run_identity(vault, market_notes.ny_now(cutoff), 'manual', as_of)[1],
                   meta['date'] + '-stock-research.md'}
    if current_name not in valid_names:
        raise ValueError('coverage edition does not match the cutoff')
    current_active = {row['id'].split('@', 1)[0] for row in linted['theses'] if row['state'] in market_notes.ACTIVE}
    required_active = active | current_active
    current_ready = {row['id'].split('@', 1)[0] for row in linted['theses'] if row['state'] == 'ready'}
    for security, candidate in candidates.items():
        if (candidate['status'] == 'ready') != (security in current_ready):
            raise ValueError('candidate readiness must agree with its current thesis ledger: ' + security)
        if candidate['status'] in {'rejected', 'invalidated', 'expired'} and security in current_active:
            raise ValueError('terminal/rejected candidate cannot retain an active thesis: ' + security)
    for security, row in current_jobs.items():
        old = jobs.get(security)
        for origin in _list(row['Sources']):
            if origin.startswith('legacy:'):
                legacy = report_names.get(origin[7:])
                if legacy is None or legacy['journals'] is not None:
                    raise ValueError('legacy source is not a verified earlier daily report')
                if not re.search(r'(?<![A-Za-z0-9])' + re.escape(security.split(':', 1)[1]) + r'(?![A-Za-z0-9])', legacy['legacy_text']):
                    raise ValueError('legacy source does not contain the adopted security')
            elif origin != 'user':
                nominated = source_rows.get(origin)
                original = posts.get(origin)
                if ((nominated is None or security not in _list(nominated['Securities']))
                        and (old is None or original is None or security not in _list(original['Securities']))):
                    raise ValueError('queue source does not nominate its security: ' + security)
        if old is None and security not in active and not any(
                origin == 'user' or origin.startswith('legacy:') or origin in current_posts
                for origin in _list(row['Sources'])):
            raise ValueError('new autonomous job needs an eligible current nomination')
        if security in candidates or row['State'] == 'assessed':
            candidate = candidates.get(security)
            link = ASSESSMENT.fullmatch(row['Assessment'])
            if (candidate is None or link is None or row['State'] not in {'assessed', 'queued', 'blocked'}
                    or link[1] + '.md' != 'Investments/' + current_name or link[2] != candidate['heading']):
                raise ValueError('assessed requires this edition\'s exact substantive Candidate assessment')
        elif row['State'] in {'reused', 'monitored'}:
            _verified_assessment(vault, row['Assessment'], security, reports, cutoff,
                                 _lock_descriptor=_lock_descriptor)
            stale = old is not None and old['Due'] != '-' and _time(old['Due']) <= cutoff
            # A new post may repeat an unchanged argument. Its semantic relevance is
            # the author's documented judgment, not something a fingerprint proves.
            if row['State'] == 'reused' and (stale or security in required_active and (
                    old is None or old['Due'] == '-' or not old.get('checked_at')
                    or market_notes.ny_now(_time(old['checked_at'])).date() != market_notes.ny_now(cutoff).date())):
                raise ValueError('reuse cannot substitute for a due or unestablished freshness check')
        if security in required_active and row['State'] == 'queued':
            raise ValueError('active thesis needs monitoring, substantive assessment or an explicit blocker')
        if security in required_active and row['State'] != 'closed' and row['Due'] == '-':
            raise ValueError('active thesis requires its next review timestamp')
        if security in current_active and row['State'] == 'closed':
            raise ValueError('active thesis cannot have a closed coverage job')
        if security in current_ready and row['State'] in UNFINISHED:
            raise ValueError('blocked or unfinished current confirmation cannot retain ready status')
    if required_active - set(current_jobs):
        raise ValueError('every active security needs a monitoring/research disposition')
    prior_theses = {row['id']: row['state'] for report in reports for row in report['theses']}
    changed_theses = {row['id'].split('@', 1)[0] for row in linted['theses']
                      if prior_theses.get(row['id']) != row['state']}
    if changed_theses - set(candidates):
        raise ValueError('new or state-changing theses need a current substantive Candidate assessment: '
                         + ', '.join(sorted(changed_theses - set(candidates))))
    unfinished_posts = sum(row['Disposition'] in UNRESOLVED for row in current_posts.values())
    unfinished_jobs = sum(row['State'] in UNFINISHED for row in current_jobs.values())
    research_complete = snapshot['status'] == 'ready' and not unfinished_posts and not unfinished_jobs
    if meta['coverage'] == 'normal' and (not research_complete or snapshot['status'] != 'ready'):
        raise ValueError('normal coverage cannot conceal unfinished research or incomplete feeds')
    if market_notes.read_stable(Path(draft))[1] != token:
        raise ValueError('draft changed during coverage validation')
    return {'complete': True, 'research_complete': research_complete,
            'feed_status': snapshot['status'], 'snapshot_sha256': snapshot['snapshot_sha256'],
            'intake_error': snapshot.get('intake_error'),
            'retained_sources': snapshot.get('retained_sources', []),
            'bootstrap_reviewed': _bootstrap_required(reports),
            'counts': {'eligible_posts': len(eligible), 'new_or_changed_posts': len(changes),
                       'post_dispositions': len(current_posts), 'unresolved_posts': unfinished_posts,
                       'reviewed_posts': sum(row['Disposition'] not in UNRESOLVED for row in current_posts.values()),
                       'excluded_posts': sum(row['Disposition'] == 'excluded' for row in current_posts.values()),
                       'nominated_securities': len({security for row in current_posts.values()
                                                   if row['Disposition'] == 'nominated'
                                                   for security in _list(row['Securities'])}),
                       'repeated_securities': len({security for row in current_posts.values()
                                                  if row['Disposition'] == 'repeated'
                                                  for security in _list(row['Securities'])}),
                       'security_dispositions': len(current_jobs), 'substantive_assessments': len(candidates),
                       'completed_assessments': sum(row['State'] == 'assessed' for row in current_jobs.values()),
                       'queued': sum(row['State'] == 'queued' for row in current_jobs.values()),
                       'blocked': sum(row['State'] == 'blocked' for row in current_jobs.values()),
                       'monitored': sum(row['State'] == 'monitored' for row in current_jobs.values()),
                       'reused': sum(row['State'] == 'reused' for row in current_jobs.values())}}


def run_self_test():
    class Tests(unittest.TestCase):
        def test_changed_text_is_new(self):
            source = {'post_id': '1', 'excerpt_sha256': 'a' * 64}
            self.assertNotEqual(fingerprint(source), fingerprint(dict(source, excerpt_sha256='b' * 64)))

        def test_unrelated_note_change_is_not_new(self):
            source = {'post_id': '1', 'excerpt_sha256': 'a' * 64}
            self.assertEqual(fingerprint(source), fingerprint(dict(source, note_sha256='b' * 64)))

        def test_attachment_availability_is_material(self):
            source = {'post_id': '1', 'excerpt_sha256': 'a' * 64}
            self.assertNotEqual(fingerprint(source), fingerprint(dict(source, attachments=[{'eligible': True}])))

        def test_pending_post_cannot_disappear(self):
            with self.assertRaisesRegex(ValueError, 'unfinished feed'):
                _continuity({'1': {'Disposition': 'blocked'}}, {},
                            {'Feed dispositions': [], 'Research queue': []}, cutoff=_time('2026-09-08T12:00:00Z'))

        def test_capacity_queue_cannot_disappear(self):
            with self.assertRaisesRegex(ValueError, 'unfinished/due'):
                _continuity({}, {'NASDAQ:A': {'State': 'queued', 'Due': '2026-09-09T12:00:00Z'}},
                            {'Feed dispositions': [], 'Research queue': []}, cutoff=_time('2026-09-08T12:00:00Z'))

        def test_assessed_with_no_due_is_not_automatic_work(self):
            _continuity({}, {'NASDAQ:A': {'State': 'assessed', 'Due': '-'}},
                        {'Feed dispositions': [], 'Research queue': []}, cutoff=_time('2026-09-08T12:00:00Z'))

    result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    print('%d/%d self-test cases pass' % (result.testsRun - len(result.errors) - len(result.failures), result.testsRun))
    return int(not result.wasSuccessful())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', '--self-test', action='store_true')
    commands = parser.add_subparsers(dest='command')
    for action in ('context', 'check'):
        command = commands.add_parser(action)
        command.add_argument('--vault', required=True)
        command.add_argument('--as-of', required=True)
        command.add_argument('--since')
        command.add_argument('--draft', required=action == 'check',
                             help='validate a completed draft against the live local evidence')
        command.add_argument('--mode', choices=('manual', 'scheduled'), default='manual')
    args = parser.parse_args()
    try:
        if args.test:
            return run_self_test()
        if args.command not in {'context', 'check'}:
            parser.error('choose context, check or --test')
        import market_notes
        edition = market_notes.run_identity(args.vault, market_notes.ny_now(_time(args.as_of)), args.mode, args.as_of)[1]
        result = (check(args.vault, args.draft, args.as_of, since=args.since, edition=edition) if args.draft else
                  context(args.vault, args.as_of, since=args.since))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, RuntimeError) as exc:
        print(json.dumps({'complete': False, 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
