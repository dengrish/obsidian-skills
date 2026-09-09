#!/usr/bin/env python3
"""Prospectively freeze the actual feed nominee pool and evaluate saved evidence.

No network or daily-note writes. Activation, enrollment and checkpoint artifacts
are immutable. Command-line writes always use the actual clock; ``now`` is an
in-process test seam. Existing independent momentum comparisons are untouched.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re

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

import market_comparison as comparison
import market_evidence as evidence
import market_notes
import market_screen
import stock_coverage as coverage

FOLDER = ('Investments', 'Snapshots', 'Nominees')
STRATEGY = {
    'id': 'feed-nominees-v1', 'unit': 'first_verified_security_nomination_after_activation',
    'groups': ['ready', 'watch', 'rejected', 'unfinished'],
    'horizons': ['2w', '1m', '3m', '6m', '12m'], 'benchmark': 'SPY',
    'baseline': 'first_regular_open_after_actual_formation_ny_date',
    'endpoint': 'first_regular_close_on_or_after_calendar_horizon_target',
    'returns': 'sip_split_adjusted_price_gross_v1',
    'weighting': 'equal_original_member_weights_no_missing_member_renormalization',
    'costs': 'excludes cash dividends, fees, spreads and slippage',
}
HASH = re.compile(r'[a-f0-9]{64}\Z')
MAX_EVENTS = 20000
EVENT_FIELDS = {
    'launch': {'excluded_reports', 'excluded_securities'},
    'report': {'source_report', 'source_sha256', 'source_as_of', 'published_at', 'formation_delay_seconds',
               'cohort', 'members', 'observations', 'excluded_prior_securities', 'coverage'},
    'checkpoint': {'cohort', 'formation_sha256', 'horizon', 'replaces', 'input', 'result'},
}


def _now(value=None):
    result = value if value is not None else datetime.now(timezone.utc)
    if not isinstance(result, datetime) or result.tzinfo is None:
        raise ValueError('an aware actual observation clock is required')
    return result


def _hash(value):
    return hashlib.sha256(evidence.canonical(value)).hexdigest()


def _link(digest):
    return '[[%s/%s.json]]' % ('/'.join(FOLDER), digest)


def _reports(vault, cutoff):
    """Use the existing hash-bound, continuity-checked published coverage replay."""
    _, reports, _, _ = coverage._history(vault, cutoff)
    for report in reports:
        data, token = market_notes.read_stable(Path(vault) / report['relative'])
        if token != report['token']:
            raise ValueError('published nominee source changed during replay')
        report['schema2'] = market_notes.lint_bytes(data)['metadata'].get('stock_research') == '2'
    return reports


def _events(vault):
    """Read a single immutable predecessor chain; reject forks and unknown occupants."""
    records, entered = {}, False
    try:
        with evidence.pinned_directory(vault, FOLDER) as (_, descriptor, check):
            entered = True
            names = os.listdir(descriptor)
            if len(names) > MAX_EVENTS:
                raise ValueError('nominee event limit reached; preserve history and report the limit')
            for name in names:
                if not re.fullmatch(r'[a-f0-9]{64}\.json', name):
                    raise ValueError('unexpected nominee evidence occupant: ' + name)
                raw = evidence.read_bytes(descriptor, name)
                if hashlib.sha256(raw).hexdigest() != name[:-5]:
                    raise ValueError('nominee evidence SHA-256 mismatch')
                value = comparison.parse_json(raw)
                if (not isinstance(value, dict) or type(value.get('stock_nominees')) is not int or value.get('stock_nominees') != 1
                        or value.get('strategy') != STRATEGY
                        or value.get('kind') not in {'launch', 'report', 'checkpoint'}
                        or evidence.canonical(value) != raw):
                    raise ValueError('invalid nominee event or changed strategy')
                if set(value) != {'stock_nominees', 'strategy', 'kind', 'recorded_at', 'previous'} | EVENT_FIELDS[value['kind']]:
                    raise ValueError('invalid nominee event fields')
                market_notes.iso_time(value['recorded_at'])
                previous = value.get('previous')
                if previous is not None and not HASH.fullmatch(previous):
                    raise ValueError('invalid nominee predecessor')
                records[name[:-5]] = value
            check()
    except FileNotFoundError:
        if not entered:
            return []
        raise ValueError('nominee evidence disappeared during access')
    children = {}
    for digest, value in records.items():
        parent = value['previous']
        if parent in children:
            raise ValueError('nominee history has competing events; preserve both for review')
        children[parent] = digest
    result, head = [], None
    while head in children:
        digest = children[head]
        value = records[digest]
        if result and market_notes.iso_time(value['recorded_at']) < market_notes.iso_time(result[-1][1]['recorded_at']):
            raise ValueError('nominee event clock went backwards')
        result.append((digest, value)); head = digest
        if len(result) > len(records):
            raise ValueError('nominee history has a cycle')
    if len(result) != len(records) or result and result[0][1]['kind'] != 'launch':
        raise ValueError('nominee history lacks its unique activation or predecessor')
    if any(value['kind'] == 'launch' for _, value in result[1:]):
        raise ValueError('nominee strategy cannot be reactivated or reset')
    return result


def _new(kind, now, events, **payload):
    return dict(stock_nominees=1, strategy=STRATEGY, kind=kind,
                recorded_at=now.isoformat(), previous=events[-1][0] if events else None, **payload)


def _append(vault, value, events, lock_descriptor):
    # The content-addressed writer provides no-clobber publication. Rechecking
    # closes ordinary stale plans; a simultaneous competing append is detected
    # as a fork on readback, never silently selected as the current truth.
    if _events(vault) != events:
        raise ValueError('nominee history changed before publication; retry from context')
    saved = evidence.write(value, vault, FOLDER, _lock_descriptor=lock_descriptor)
    expected = events + [(saved['sha256'], value)]
    if _events(vault) != expected:
        raise ValueError('nominee history changed at publication; preserve the competing events')
    return saved


def _identities(reports):
    identities = set()
    for report in reports:
        identities.update(row['id'].split('@', 1)[0] for row in report['theses'])
        identities.update(row['exchange'] + ':' + row['ticker'] for row in report['candidates'])
        if report['journals']:
            identities.update(row['Security'] for row in report['journals']['Research queue'])
            for row in report['journals']['Feed dispositions']:
                identities.update(coverage._list(row['Securities']))
    return sorted(identities)


def _serialized(function, vault, *args, **kwargs):
    """Acquire the publication lock only when a public write command executes."""
    import fcntl
    requested = Path(vault).expanduser().absolute()
    if requested.is_symlink() or '..' in requested.parts:
        raise ValueError('nominee vault must be an explicit real directory')
    root = requested.resolve(strict=True)
    descriptor = os.open(root, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0))
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('another market publication is in progress; retry nominee work after it finishes') from exc
        return function(root, *args, _lock_descriptor=descriptor, **kwargs)
    finally:
        os.close(descriptor)


def start(vault, now=None):
    """Activate once, before publishing new work. Never enroll historical ideas."""
    return _serialized(_start, vault, now)


def _start(vault, now=None, *, _lock_descriptor=None):
    stamp = _now(now)
    events = _events(vault)
    if events:
        return {'status': 'unchanged', 'launch_at': events[0][1]['recorded_at'],
                'evidence_attachment': {'sha256': events[0][0], 'link': _link(events[0][0])}}
    reports = _reports(vault, stamp)
    value = _new('launch', stamp, events,
                 excluded_reports=[{'report': row['relative'], 'sha256': row['sha256']} for row in reports],
                 excluded_securities=_identities(reports))
    attachment = _append(vault, value, events, _lock_descriptor)
    return {'status': attachment['status'], 'launch_at': value['recorded_at'], 'evidence_attachment': attachment}


def _disposition(report, job):
    security = job['Security']
    candidates = {row['exchange'] + ':' + row['ticker']: row for row in report['candidates']}
    candidate = candidates.get(security)
    if job['State'] in {'queued', 'blocked'}:
        group = 'unfinished'
    elif candidate is not None:
        group = candidate['status'] if candidate['status'] in {'ready', 'watch', 'rejected'} else 'rejected'
    else:
        # Reuse/monitoring may link an earlier assessment. It is an observation,
        # not a new decision at this publication, so never infer eventual readiness.
        group = 'unfinished'
    return {'group': group, 'work_state': job['State'],
            'assessment_status': candidate['status'] if candidate else None,
            'assessment': job['Assessment'], 'first_seen': job['First seen'],
            'due': job['Due'], 'reason': job['Reason'], 'source_ids': coverage._list(job['Sources']),
            'decision_as_of': report['as_of'], 'published_at': report['generated_at']}


def _derive(report, enrolled, excluded, latest):
    journals = report['journals']
    if not report['schema2'] or journals is None:
        return {'members': [], 'observations': [], 'excluded_prior_securities': [],
                'coverage': {'posts': None, 'nominated_posts': None, 'unresolved_posts': None,
                             'queued': None, 'blocked': None,
                             'gap': 'Published legacy schema has no eligible schema-2 nominee journal; history retained without prospective enrollment.'}}
    jobs = {row['Security']: row for row in journals['Research queue']}
    origins = {}
    for post in journals['Feed dispositions']:
        if post['Disposition'] != 'nominated':
            continue
        for security in coverage._list(post['Securities']):
            job = jobs.get(security)
            post_id = coverage.POST.fullmatch(post['Post'])[1]
            if (job is None or job['State'] not in {'assessed', 'queued', 'blocked'}
                    or post_id not in coverage._list(job['Sources'])):
                raise ValueError('every substantive nomination needs its matching research disposition')
            if job['State'] == 'assessed':
                candidate = next((row for row in report['candidates'] if row['exchange'] + ':' + row['ticker'] == security), None)
                expected = '[[' + report['relative'][:-3] + '#' + candidate['heading'] + ']]' if candidate else None
                if candidate is None or job['Assessment'] != expected:
                    raise ValueError('new assessed nomination needs this published report\'s exact candidate assessment')
                ready = any(row['id'].split('@', 1)[0] == security and row['state'] == 'ready' for row in report['theses'])
                if ready != (candidate['status'] == 'ready'):
                    raise ValueError('nominee ready disposition disagrees with the published thesis ledger')
            origins.setdefault(security, []).append({
                'post': post['Post'], 'post_id': post_id, 'fingerprint': post['Fingerprint'],
                'published_at': post['Published'], 'reason': post['Reason']})
    members, observations = [], []
    for security in sorted(set(origins) | (set(jobs) & set(enrolled))):
        decision = _disposition(report, jobs[security])
        row = dict(security=security, disposition=decision, origins=origins.get(security, []))
        if security in origins and security not in enrolled and security not in excluded:
            members.append(row)
        elif security in enrolled and (row['origins'] or latest.get(security) != decision):
            observations.append(row)
    return {'members': members, 'observations': observations,
            'excluded_prior_securities': sorted(set(origins) & set(excluded)),
            'coverage': {'posts': len(journals['Feed dispositions']),
                'nominated_posts': sum(row['Disposition'] == 'nominated' for row in journals['Feed dispositions']),
                'unresolved_posts': sum(row['Disposition'] in coverage.UNRESOLVED for row in journals['Feed dispositions']),
                'queued': sum(row['State'] == 'queued' for row in jobs.values()),
                'blocked': sum(row['State'] == 'blocked' for row in jobs.values())}}


def _replay(vault, events, reports):
    if not events:
        return {}, {}, {}, {}
    by_report = {row['relative']: row for row in reports}
    launch = events[0][1]
    if (not isinstance(launch['excluded_reports'], list) or not isinstance(launch['excluded_securities'], list)
            or any(not isinstance(row, dict) or set(row) != {'report', 'sha256'}
                   or not isinstance(row['report'], str) or not coverage.REPORT.fullmatch('[[' + row['report'][:-3] + ']]')
                   or not row['report'].endswith('.md') or not isinstance(row['sha256'], str)
                   or not HASH.fullmatch(row['sha256']) for row in launch['excluded_reports'])):
        raise ValueError('invalid activation source census')
    excluded = launch['excluded_securities']
    if excluded != sorted(set(excluded)) or any(not coverage.SECURITY.fullmatch(row) for row in excluded):
        raise ValueError('invalid activation exclusion roster')
    prior = []
    for row in launch['excluded_reports']:
        actual = by_report.get(row['report'])
        if actual is None or actual['sha256'] != row['sha256']:
            raise ValueError('preactivation source history is missing or changed')
        prior.append(actual)
    if _identities(prior) != excluded:
        raise ValueError('activation exclusion roster no longer matches its sources')
    enrolled, latest, cohorts, checkpoints = {}, {}, {}, {}
    processed = {row['report'] for row in launch['excluded_reports']}
    for digest, event in events[1:]:
        if event['kind'] == 'report':
            report = by_report.get(event['source_report'])
            if report is None or report['sha256'] != event['source_sha256']:
                raise ValueError('frozen nominee source report is missing or changed')
            if event['source_report'] in processed:
                raise ValueError('nominee report was enrolled twice')
            next_report = next((row for row in reports if row['relative'] not in processed), None)
            if next_report is None or next_report['relative'] != event['source_report']:
                raise ValueError('nominee enrollment omitted or reordered a published report')
            if (market_notes.iso_time(report['generated_at']) < market_notes.iso_time(launch['recorded_at'])
                    or market_notes.iso_time(report['generated_at']) > market_notes.iso_time(event['recorded_at'])):
                raise ValueError('nominee enrollment predates activation or publication')
            derived = _derive(report, enrolled, excluded, latest)
            if any(event.get(key) != value for key, value in derived.items()):
                raise ValueError('frozen nominee pool or initial decisions do not match the actual source report')
            expected_delay = (market_notes.iso_time(event['recorded_at']) - market_notes.iso_time(report['generated_at'])).total_seconds()
            if (event['source_as_of'] != report['as_of'] or event['published_at'] != report['generated_at']
                    or event['formation_delay_seconds'] != expected_delay):
                raise ValueError('nominee formation changed its source timing or observed delay')
            expected_id = STRATEGY['id'] + '@' + report['sha256'][:24]
            if event['cohort'] != expected_id:
                raise ValueError('nominee cohort identity differs from its original report')
            processed.add(event['source_report'])
            if event['members']:
                cohorts[event['cohort']] = dict(event, sha256=digest, evidence_link=_link(digest))
            for row in event['members']:
                enrolled[row['security']] = event['cohort']
            for row in event['members'] + event['observations']:
                latest[row['security']] = row['disposition']
        elif event['kind'] == 'checkpoint':
            cohort = cohorts.get(event['cohort'])
            if cohort is None or event['formation_sha256'] != cohort['sha256']:
                raise ValueError('nominee checkpoint lacks its frozen formation')
            result = calculate(cohort, event['input'], event['horizon'])
            if event['result'] != result or result['state'] == 'pending':
                raise ValueError('nominee checkpoint does not recompute from its full retained evidence')
            if market_notes.iso_time(event['input']['as_of']) > market_notes.iso_time(event['recorded_at']):
                raise ValueError('nominee checkpoint uses future evidence')
            key = (event['cohort'], event['horizon'])
            old = checkpoints.get(key)
            expected = old['sha256'] if old and old['result']['state'] == 'observed' else None
            if event['replaces'] != expected:
                raise ValueError('changed observed checkpoint needs its exact immutable predecessor')
            checkpoints[key] = dict(event, sha256=digest, evidence_link=_link(digest))
    return enrolled, latest, cohorts, checkpoints


def form(vault, now=None):
    """Enroll all new published reports automatically; caller cannot select members."""
    return _serialized(_form, vault, now)


def _form(vault, now=None, *, _lock_descriptor=None):
    stamp = _now(now)
    events = _events(vault)
    if not events:
        raise ValueError('activate nominee evaluation before publishing new reports: run start')
    reports = _reports(vault, stamp)
    enrolled, latest, _, _ = _replay(vault, events, reports)
    launch = events[0][1]
    processed = {row['report'] for row in launch['excluded_reports']}
    processed.update(value['source_report'] for _, value in events if value['kind'] == 'report')
    result = {'status': 'unchanged', 'launch_at': launch['recorded_at'], 'processed_reports': [],
              'new_cohorts': 0, 'new_members': 0, 'observations': 0, 'evidence_attachments': []}
    for report in reports:
        if report['relative'] in processed:
            continue
        if market_notes.iso_time(report['generated_at']) < market_notes.iso_time(launch['recorded_at']):
            raise ValueError('unregistered preactivation report appeared; do not backfill historical recommendations')
        payload = _derive(report, enrolled, launch['excluded_securities'], latest)
        observed = _now(now)
        value = _new('report', observed, events, source_report=report['relative'], source_sha256=report['sha256'],
                     source_as_of=report['as_of'], published_at=report['generated_at'],
                     formation_delay_seconds=(observed - market_notes.iso_time(report['generated_at'])).total_seconds(),
                     cohort=STRATEGY['id'] + '@' + report['sha256'][:24], **payload)
        saved = _append(vault, value, events, _lock_descriptor)
        events.append((saved['sha256'], value))
        for row in value['members']:
            enrolled[row['security']] = value['cohort']
        for row in value['members'] + value['observations']:
            latest[row['security']] = row['disposition']
        result['processed_reports'].append(report['relative'])
        result['new_cohorts'] += bool(value['members'])
        result['new_members'] += len(value['members'])
        result['observations'] += len(value['observations'])
        result['evidence_attachments'].append(saved)
    if result['processed_reports']:
        result['status'] = 'created'
    result['summary_markdown'] = ('Nominee evaluation froze %s new securities in %s publication cohorts; '
        '%s later decision/source observations. Baselines follow actual formation, including any delay.' %
        (result['new_members'], result['new_cohorts'], result['observations']))
    return result


def _empty_rows(cohort, reason):
    return [dict(security=row['security'], initial_group=row['disposition']['group'],
                 initial_work_state=row['disposition']['work_state'], baseline_price=None,
                 endpoint_price=None, return_value=None, excess_spy=None, state='unavailable', reason=reason)
            for row in cohort['members']]


def _groups(rows, benchmark):
    groups = {}
    for group in ['all'] + STRATEGY['groups']:
        members = [row for row in rows if group == 'all' or row['initial_group'] == group]
        observed = sum(row['state'] == 'observed' for row in members)
        value = math.fsum(row['return_value'] for row in members) / len(members) if members and observed == len(members) else None
        groups[group] = {'enrolled': len(members), 'observed': observed, 'unavailable': len(members) - observed,
                         'return_value': value, 'excess_spy': value - benchmark if value is not None and benchmark is not None else None}
    ready, pool = groups['ready']['return_value'], groups['all']['return_value']
    return groups, ready - pool if ready is not None and pool is not None else None


def calculate(cohort, bundle, horizon):
    """Pure fixed-window calculation; original members never disappear or change group."""
    if horizon not in STRATEGY['horizons'] or not cohort['members']:
        raise ValueError('use a nonempty frozen nominee cohort and a supported horizon')
    if not isinstance(bundle, dict) or type(bundle.get('stock_nominee_input')) is not int or bundle['stock_nominee_input'] != 1:
        raise ValueError('use stock_nominee_input version 1 with saved price/calendar envelopes')
    cutoff = market_notes.iso_time(bundle['as_of'])
    formed = market_notes.iso_time(cohort['recorded_at'])
    if cutoff < formed:
        raise ValueError('observation cutoff precedes actual formation')
    formation_day = formed.astimezone(comparison.ny_zone()).date()
    result = {'cohort': cohort['cohort'], 'horizon': horizon, 'as_of': bundle['as_of'],
              'baseline_at': None, 'observed_at': None, 'target_date': None,
              'formation_at': cohort['recorded_at'], 'formation_delay_seconds': cohort['formation_delay_seconds'],
              'return_convention': STRATEGY['returns'], 'costs': STRATEGY['costs']}
    if bundle.get('unavailable_reason'):
        if not isinstance(bundle['unavailable_reason'], str) or not bundle['unavailable_reason'].strip():
            raise ValueError('unavailable evidence needs a concrete reason')
        rows = _empty_rows(cohort, bundle['unavailable_reason'])
        groups, selection = _groups(rows, None)
        return dict(result, state='unavailable', rows=rows, benchmark_return=None, benchmark_state='unavailable',
                    groups=groups, ready_minus_pool=selection, reason=bundle['unavailable_reason'])
    sessions, dates = comparison.calendar_events(bundle['sessions'], formation_day, cutoff)
    following = [event for event in sessions if event[0] > formation_day]
    if not following or following[0][1] > cutoff:
        return dict(result, state='pending', reason='The fixed postformation opening is not yet available.')
    baseline = following[0]
    if baseline[1] < formed or baseline[1] < market_notes.iso_time(cohort['published_at']):
        raise ValueError('fixed baseline precedes actual formation/publication')
    target = market_notes.horizon_target(baseline[0], horizon)
    result.update(baseline_at=baseline[1].isoformat(), target_date=target.isoformat())
    endpoints = [event for event in sessions if event[0] >= target]
    if not endpoints or endpoints[0][2] > cutoff or not comparison.full_daily_bar_available(endpoints[0][0], cutoff):
        return dict(result, state='pending', reason='The fixed endpoint close or its full daily bar is not yet available.')
    endpoint = endpoints[0]
    result['observed_at'] = endpoint[2].isoformat()
    bars, requested, complete, warnings, _, _, mapping = market_screen._prices(bundle['prices'], cutoff, dates)
    if mapping != formation_day:
        raise ValueError('price symbol mapping must preserve the actual formation date')
    symbols = sorted({row['security'].split(':', 1)[1] for row in cohort['members']} | {'SPY'})
    comparison.source_evidence(json.dumps(comparison.source_records(bundle['prices'] + [bundle['sessions']])),
                               cutoff, formation_day.isoformat(), symbols, first_day=baseline[0], last_day=endpoint[0])
    actions = bundle.get('corporate_actions', {})
    if not isinstance(actions, dict):
        raise ValueError('retain corporate-action and identity verification for each instrument')
    def instrument(symbol):
        first, last = bars.get(symbol, {}).get(baseline[0]), bars.get(symbol, {}).get(endpoint[0])
        reason = ('incomplete price retrieval' if not complete else 'instrument not requested' if symbol not in requested
                  else 'missing fixed baseline or endpoint (including delisted/renamed instruments)' if first is None or last is None
                  else 'unverified corporate actions or instrument identity' if not comparison.verified_action(actions.get(symbol)) else None)
        value = last['c'] / first['o'] - 1 if reason is None else None
        if value is not None:
            comparison.number(value)
        return first, last, value, reason
    _, _, spy, spy_reason = instrument('SPY')
    rows = []
    for member in cohort['members']:
        security = member['security']; symbol = security.split(':', 1)[1]
        first, last, value, reason = instrument(symbol)
        if sum(row['security'].split(':', 1)[1] == symbol for row in cohort['members']) > 1:
            value, reason = None, 'ambiguous exchange identities share one provider symbol'
        rows.append(dict(security=security, initial_group=member['disposition']['group'],
                         initial_work_state=member['disposition']['work_state'],
                         baseline_price=first['o'] if first else None, endpoint_price=last['c'] if last else None,
                         return_value=value, excess_spy=value - spy if value is not None and spy is not None else None,
                         state='observed' if value is not None else 'unavailable', reason=reason))
    groups, selection = _groups(rows, spy)
    state = 'observed' if all(row['state'] == 'observed' for row in rows) and spy is not None else 'unavailable'
    return dict(result, state=state, rows=rows, benchmark_return=spy,
                benchmark_state='observed' if spy is not None else 'unavailable', benchmark_reason=spy_reason,
                groups=groups, ready_minus_pool=selection, warnings=warnings,
                reason='Same-cohort descriptive selection difference; overlapping small samples do not establish alpha.')


def evaluate(vault, cohort, bundle, horizon, replaces=None, now=None):
    return _serialized(_evaluate, vault, cohort, bundle, horizon, replaces, now)


def _evaluate(vault, cohort, bundle, horizon, replaces=None, now=None, *, _lock_descriptor=None):
    stamp = _now(now)
    if market_notes.iso_time(bundle['as_of']) > stamp:
        raise ValueError('checkpoint evidence cutoff is in the future')
    events = _events(vault)
    _, _, cohorts, checkpoints = _replay(vault, events, _reports(vault, stamp))
    if cohort not in cohorts:
        raise ValueError('select an actual frozen nominee cohort from context')
    result = calculate(cohorts[cohort], bundle, horizon)
    if result['state'] == 'pending':
        return result
    old = checkpoints.get((cohort, horizon))
    if old and old['input'] == bundle and old['result'] == result:
        return dict(result, status='unchanged', evidence_attachment={'sha256': old['sha256'], 'link': old['evidence_link']})
    expected = old['sha256'] if old and old['result']['state'] == 'observed' else None
    if replaces != expected:
        raise ValueError('changing an observed nominee checkpoint requires --replaces with its exact evidence SHA-256')
    event = _new('checkpoint', _now(now), events, cohort=cohort, formation_sha256=cohorts[cohort]['sha256'],
                 horizon=horizon, replaces=replaces, input=bundle, result=result)
    return dict(result, status='created', evidence_attachment=_append(vault, event, events, _lock_descriptor))


def context(vault, as_of):
    """Read-only daily/monthly view; later events never rewrite initial decisions."""
    cutoff = market_notes.iso_time(as_of)
    all_events = _events(vault)
    events = [(key, row) for key, row in all_events if market_notes.iso_time(row['recorded_at']) <= cutoff]
    result = {'schema': 1, 'strategy_id': STRATEGY['id'], 'as_of': as_of,
              'launch_at': all_events[0][1]['recorded_at'] if all_events else None,
              'launch_due': not bool(all_events), 'cohorts': [], 'checkpoints': [], 'due_checkpoints': [],
              'formation_due': False, 'unformed_reports': [],
              'counts': {'cohorts': 0, 'enrolled': 0, 'observations': 0, 'unresolved_posts': 0},
              'evidence_links': [_link(key) for key, _ in events]}
    if not events:
        result['summary_markdown'] = 'Prospective nominee evaluation has not yet formed an observable cohort.'
        return result
    reports = _reports(vault, cutoff)
    enrolled, _, cohorts, checkpoints = _replay(vault, events, reports)
    processed = {row['report'] for row in events[0][1]['excluded_reports']}
    processed.update(row['source_report'] for _, row in events if row['kind'] == 'report')
    result['unformed_reports'] = [row['relative'] for row in reports if row['relative'] not in processed]
    result['formation_due'] = bool(result['unformed_reports'])
    for key, value in cohorts.items():
        count = {group: sum(row['disposition']['group'] == group for row in value['members']) for group in STRATEGY['groups']}
        result['cohorts'].append({name: value[name] for name in (
            'cohort', 'recorded_at', 'source_report', 'source_sha256', 'source_as_of', 'published_at',
            'formation_delay_seconds', 'members', 'coverage', 'sha256', 'evidence_link')} | {'initial_counts': count})
        for horizon in STRATEGY['horizons']:
            old = checkpoints.get((key, horizon))
            earliest = market_notes.horizon_target(
                market_notes.ny_now(market_notes.iso_time(value['recorded_at'])).date() + timedelta(days=1), horizon)
            if (old is None or old['result']['state'] != 'observed') and earliest <= market_notes.ny_now(cutoff).date():
                result['due_checkpoints'].append({'cohort': key, 'horizon': horizon,
                    'target_not_before': earliest.isoformat(), 'state': old['result']['state'] if old else 'pending',
                    'reason': 'Verify the fixed baseline and first eligible session; this lower bound is not a trading calendar.'})
    result['checkpoints'] = [dict(row['result'], evidence_link=row['evidence_link'], sha256=row['sha256']) for row in checkpoints.values()]
    report_events = [row for _, row in events if row['kind'] == 'report']
    result['counts'].update(cohorts=len(cohorts), enrolled=len(enrolled),
        observations=sum(len(row['observations']) for row in report_events),
        unresolved_posts=report_events[-1]['coverage']['unresolved_posts'] if report_events else 0,
        checkpoints_observed=sum(row['result']['state'] == 'observed' for row in checkpoints.values()),
        checkpoints_unavailable=sum(row['result']['state'] == 'unavailable' for row in checkpoints.values()),
        checkpoints_pending=len(cohorts) * len(STRATEGY['horizons']) - len(checkpoints))
    result['counts']['legacy_report_gaps'] = sum(bool(row['coverage'].get('gap')) for row in report_events)
    result['summary_markdown'] = ('Prospective nominee pool: %s unique securities across %s cohorts; '
        '%s observed, %s unavailable and %s pending cohort windows. Latest source journal has %s unresolved posts. '
        'Initial ready/watch/rejected/unfinished groups remain frozen; later transitions are separate observations. '
        'Returns begin after actual formation, including any delay; selection differences are descriptive.' %
        tuple(result['counts'][name] for name in ('enrolled', 'cohorts', 'checkpoints_observed',
                                                'checkpoints_unavailable', 'checkpoints_pending', 'unresolved_posts')))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', action='store_true', help='run bounded offline invariant fixtures')
    commands = parser.add_subparsers(dest='command')
    for name in ('start', 'form', 'context', 'evaluate'):
        command = commands.add_parser(name)
        command.add_argument('--vault', required=True)
        if name == 'context':
            command.add_argument('--as-of', required=True)
        if name == 'evaluate':
            command.add_argument('--cohort', required=True)
            command.add_argument('--horizon', choices=STRATEGY['horizons'], required=True)
            command.add_argument('--input', required=True)
            command.add_argument('--replaces')
    args = parser.parse_args(argv)
    if args.test:
        if args.command:
            parser.error('--test cannot be combined with a write or context command')
        return run_self_test()
    if not args.command:
        parser.error('a command is required unless --test is selected')
    try:
        if args.command == 'context':
            result = context(args.vault, args.as_of)
        elif args.command == 'evaluate':
            result = evaluate(args.vault, args.cohort, comparison.load_json(args.input), args.horizon, args.replaces)
        else:
            result = globals()[args.command](args.vault)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError, RuntimeError, KeyError, TypeError, comparison.DataError) as exc:
        print(json.dumps({'complete': False, 'error': str(exc)}, ensure_ascii=False))
        return 1


def run_self_test():
    """Small installed-plugin regressions; repository tests exercise real journals."""
    import tempfile
    import unittest

    class NomineeTests(unittest.TestCase):
        def test_no_survivor_renormalization(self):
            groups, selection = _groups([
                {'initial_group': 'ready', 'state': 'observed', 'return_value': 0.4},
                {'initial_group': 'unfinished', 'state': 'unavailable', 'return_value': None}], 0.1)
            self.assertIsNone(groups['all']['return_value'])
            self.assertAlmostEqual(groups['ready']['excess_spy'], 0.3)
            self.assertIsNone(selection)

        def test_empty_ready_is_not_a_cash_return(self):
            groups, selection = _groups([{'initial_group': 'watch', 'state': 'observed', 'return_value': -0.2}], None)
            self.assertEqual(groups['ready']['enrolled'], 0)
            self.assertIsNone(groups['ready']['return_value'])
            self.assertIsNone(groups['all']['excess_spy'])
            self.assertIsNone(selection)

        def test_same_cohort_selection_difference(self):
            groups, selection = _groups([
                {'initial_group': 'ready', 'state': 'observed', 'return_value': 0.3},
                {'initial_group': 'rejected', 'state': 'observed', 'return_value': -0.1}], 0.05)
            self.assertAlmostEqual(groups['all']['return_value'], 0.1)
            self.assertAlmostEqual(selection, 0.2)

        def test_activation_retry_and_readonly_context(self):
            with tempfile.TemporaryDirectory(prefix='nominee-self-test-') as folder:
                vault = Path(folder).resolve()
                now = datetime(2026, 9, 8, 15, 0, tzinfo=timezone.utc)
                self.assertTrue(context(vault, now.isoformat())['launch_due'])
                self.assertEqual(list(vault.iterdir()), [])
                self.assertEqual(start(vault, now)['status'], 'created')
                self.assertEqual(start(vault, now)['status'], 'unchanged')
                self.assertEqual(form(vault, now)['new_members'], 0)
                self.assertEqual(len(_events(vault)), 1)

        def test_unsupported_write_clock_is_not_exposed(self):
            with self.assertRaises(ValueError):
                _now(datetime(2026, 9, 8))
            with self.assertRaises(ValueError):
                calculate({'members': []}, {'stock_nominee_input': 1}, '2w')

        def test_empty_unavailable_census_never_has_zero_return(self):
            groups, _ = _groups([], None)
            self.assertEqual(groups['all']['enrolled'], 0)
            self.assertIsNone(groups['all']['return_value'])

    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(NomineeTests))
    print('%d/%d self-test cases pass' % (result.testsRun - len(result.failures) - len(result.errors), result.testsRun))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
