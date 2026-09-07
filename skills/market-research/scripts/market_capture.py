#!/usr/bin/env python3
"""Capture prioritized estimate snapshots before a manual research cutoff.

Read-only provider access; no trades, scheduling or credential changes. Reuses
recent immutable estimates and persists a conservative provider cooldown after
the first quota response. All vault writes use existing immutable writers.
"""
from __future__ import annotations

import argparse
from datetime import timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from types import SimpleNamespace
import uuid

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

from market_credentials import credential_environment, load_credentials
from market_http import CREDENTIAL_NAMES, DataError, HttpClient, parse_date, parse_time, redact, utc_now
import market_estimates
import market_estimate_history as history
import market_evidence as evidence

STATUS_FOLDER = ('Investments', 'Snapshots', 'ProviderStatus')
STATUS_NAME = re.compile(r'[0-9a-f]{64}\.json\Z')
STATUS_BYTES = 4096
MAX_STATUS_RECORDS = 10000
STATUS_KEYS = {'market_provider_status', 'provider', 'status', 'observed_at', 'retry_not_before',
               'provider_reset_at', 'policy', 'scope'}
STOP_SOURCE_CODES = {'missing_credentials', 'invalid_credentials', 'access_denied',
                     'network_error', 'request_budget', 'http_error', 'redirect'}
WARNINGS = [
    'The 24-hour cooldown is a conservative local retry policy, not a provider reset guarantee.',
    'Cooldown scope is this selected vault and provider; it is not a shared account-wide quota ledger.',
    'Current estimates have no historical provider vintage. Eligibility starts at actual observation and first save.',
    'Freshness does not establish comparable accounting basis, currency or analyst coverage.',
]


def _iso(value):
    return value.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def _json(raw):
    try:
        value = json.loads(raw, object_pairs_hook=history._unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
        pending = [(value, 0)]
        while pending:
            item, depth = pending.pop()
            if depth > 30:
                raise ValueError('excessive nesting')
            if isinstance(item, dict):
                pending.extend((child, depth + 1) for child in item.values())
            elif isinstance(item, list):
                pending.extend((child, depth + 1) for child in item)
        return value
    except (ValueError, TypeError, RecursionError):
        raise DataError('invalid_input', 'Use bounded JSON without duplicate keys, nonfinite values or excessive nesting.') from None


def read_plan(path):
    raw, token = history.read_stable(path)
    if len(raw) > 32768:
        raise DataError('invalid_input', 'The capture plan exceeds 32 KiB.')
    value = _json(raw)
    if not isinstance(value, list) or not 1 <= len(value) <= 30:
        raise DataError('invalid_input', 'Use an ordered capture plan with one to thirty explicit periods.')
    result, seen, periods = [], set(), {}
    for item in value:
        if not isinstance(item, dict) or set(item) != {'symbol', 'period', 'horizon', 'reason'}:
            raise DataError('invalid_input', 'Each capture item needs exactly symbol, period, horizon and reason.')
        symbol = history._symbol(item['symbol'])
        period = parse_date(item['period']).isoformat()
        if (item['horizon'] not in market_estimates.HORIZONS or not isinstance(item['reason'], str)
                or not 1 <= len(item['reason'].strip()) <= 400
                or any(ord(char) < 32 or ord(char) == 127 for char in item['reason'])):
            raise DataError('invalid_input', 'Capture items require a supported horizon and brief plain-text priority reason.')
        try:
            item['reason'].encode('utf-8')
        except UnicodeError:
            raise DataError('invalid_input', 'Capture reasons must be valid UTF-8 text.') from None
        identity = symbol, period, item['horizon']
        if identity in seen:
            raise DataError('invalid_input', 'Duplicate symbol, period and horizon in capture plan.')
        seen.add(identity)
        periods.setdefault(symbol, set()).add(period)
        if len(periods[symbol]) > 8:
            raise DataError('invalid_input', 'Request at most eight fiscal period ends per symbol.')
        result.append(dict(item, symbol=symbol, period=period))
    return result, token


def _status(value, name, current):
    if (not isinstance(value, dict) or set(value) != STATUS_KEYS
            or type(value['market_provider_status']) is not int or value['market_provider_status'] != 1
            or value['provider'] != 'alpha_vantage' or value['status'] != 'rate_limited'
            or value['provider_reset_at'] is not None or value['policy'] != 'local-conservative-24h-v1'
            or value['scope'] != 'selected_vault_provider'):
        raise DataError('invalid_status', 'Unrecognized provider cooldown record; preserve it for inspection.')
    observed, retry = parse_time(value['observed_at']), parse_time(value['retry_not_before'])
    if (observed > current or retry != observed + timedelta(hours=24)
            or value['observed_at'] != _iso(observed) or value['retry_not_before'] != _iso(retry)
            or hashlib.sha256(evidence.canonical(value)).hexdigest() + '.json' != name):
        raise DataError('invalid_status', 'Provider cooldown time or content-addressed identity is invalid.')
    return value


def provider_status(vault, current):
    records, opened = [], False
    try:
        with evidence.pinned_directory(vault, STATUS_FOLDER) as (_, descriptor, check):
            opened = True
            names = sorted(os.listdir(descriptor))
            if len(names) > MAX_STATUS_RECORDS:
                raise DataError('invalid_status', 'Provider status history exceeds its bounded record count.')
            for name in names:
                if not STATUS_NAME.fullmatch(name):
                    raise DataError('invalid_status', 'Unexpected provider-status occupant; preserve it for inspection.')
                raw = evidence.read_bytes(descriptor, name, STATUS_BYTES)
                value = _status(_json(raw), name, current)
                if raw != evidence.canonical(value):
                    raise DataError('invalid_status', 'Provider-status bytes are not canonical.')
                records.append(value)
            if sorted(os.listdir(descriptor)) != names:
                raise DataError('changed_status', 'Provider status history changed during inspection; retry later.')
            check()
    except FileNotFoundError:
        if opened:
            raise DataError('changed_status', 'Provider status disappeared during inspection; retry later.') from None
        return {'active': False, 'retry_not_before': None, 'provider_reset_at': None}
    active = [value for value in records if parse_time(value['retry_not_before']) > current]
    latest = max(active, key=lambda value: parse_time(value['retry_not_before'])) if active else None
    return {'active': latest is not None, 'retry_not_before': latest['retry_not_before'] if latest else None,
            'provider_reset_at': None}


def record_quota(vault, current):
    value = {'market_provider_status': 1, 'provider': 'alpha_vantage', 'status': 'rate_limited',
             'observed_at': _iso(current), 'retry_not_before': _iso(current + timedelta(hours=24)),
             'provider_reset_at': None, 'policy': 'local-conservative-24h-v1', 'scope': 'selected_vault_provider'}
    return evidence.write(value, vault, STATUS_FOLDER, STATUS_BYTES)


def _work_folder(path, vault):
    requested = Path(path).expanduser().absolute()
    if requested.is_symlink() or '..' in requested.parts:
        raise DataError('unsafe_work_dir', 'Use the run-owned real scratch directory outside the vault.')
    work, root = requested.resolve(strict=True), Path(vault).expanduser().resolve(strict=True)
    if (not work.is_dir() or not work.name.startswith('.obsidian-skills-tmp-')
            or work == root or root in work.parents):
        raise DataError('unsafe_work_dir', 'Use the run-owned hidden scratch directory outside the vault.')
    return work


def capture(vault, plan_path, work_dir, *, max_calls=3, reuse_hours=24, as_of=None,
            client=None, clock=utc_now, sleep=time.sleep):
    if (type(max_calls) is not int or not 0 <= max_calls <= 10
            or type(reuse_hours) is not int or not 1 <= reuse_hours <= 24):
        raise DataError('invalid_input', 'Use zero to ten unique-symbol calls and one to 24 reuse hours.')
    current = clock()
    cutoff = parse_time(as_of) if as_of is not None else None
    if cutoff is not None and cutoff > current:
        raise DataError('invalid_input', 'A frozen evidence cutoff cannot be in the future.')
    work = _work_folder(work_dir, vault)
    plan, plan_token = read_plan(plan_path)
    cooldown = provider_status(vault, current)
    result, missing, cached = [], {}, {}
    for item in plan:
        symbol = item['symbol']
        if symbol not in cached:
            cached[symbol] = history.estimate_history(vault, _iso(cutoff or current), symbol, now=current)['snapshots']
        matching = [record for record in cached[symbol]
                    if record['snapshot']['record']['fiscal_period_end'] == item['period']
                    and record['snapshot']['record']['horizon'] == item['horizon']
                    and parse_time(record['snapshot']['observed_at']) >= current - timedelta(hours=reuse_hours)]
        row = dict(item, status='pending', snapshot=None, available_at=None, eligible_at_cutoff=None)
        if matching:
            selected = matching[-1]
            row.update(status='reused', snapshot=selected['path'], available_at=selected['snapshot']['available_at'],
                       eligible_at_cutoff=True if cutoff is not None else None)
        else:
            missing.setdefault(symbol, []).append(len(result))
        result.append(row)
    calls, status_receipt, stopped = 0, None, None
    for symbol, indexes in missing.items():
        if cooldown['active']:
            for index in indexes:
                result[index]['status'] = 'cooldown'
            continue
        if stopped is not None:
            for index in indexes:
                result[index].update(status='source_unavailable', error_code=stopped)
            continue
        if calls >= max_calls:
            for index in indexes:
                result[index]['status'] = 'budget_deferred'
            continue
        if client is None:
            raise DataError('missing_client', 'Capture requires the bounded credential-redacting market transport.')
        calls += 1
        request_start = len(client.requests)
        args = SimpleNamespace(symbol=symbol, period=sorted({result[index]['period'] for index in indexes}), as_of=as_of)
        try:
            payload = market_estimates.alpha_estimates(client, args)
            payload = dict(payload, market_data=1, operation='estimates', requests=client.requests[request_start:])
            # Use exactly the same redaction boundary as market_data before
            # saving a provider envelope or exposing it to any caller.
            payload = redact(payload, client.env, extra_values=getattr(client, 'redaction_values', ()))
            if payload.get('coverage_complete') is not True:
                for index in indexes:
                    result[index]['status'] = 'coverage_unavailable'
                continue
            saved_payload = work / ('estimates-' + symbol + '-' + uuid.uuid4().hex + '.json')
            with saved_payload.open('xb') as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(evidence.canonical(payload))
                handle.flush(); os.fsync(handle.fileno())
            for index in indexes:
                row = result[index]
                if not any(item['fiscal_period_end'] == row['period'] and item['horizon'] == row['horizon']
                           for item in payload['data']):
                    row['status'] = 'coverage_unavailable'
                    continue
                saved = history.save_snapshot(saved_payload, vault, row['period'], row['horizon'], now=clock())
                available = saved['snapshot']['available_at']
                eligible = parse_time(available) <= cutoff if cutoff is not None else None
                row.update(status='captured' if eligible is not False else 'captured_future_only',
                           snapshot=saved['path'], available_at=available, eligible_at_cutoff=eligible)
        except DataError as exc:
            for index in indexes:
                if result[index]['status'] == 'pending':
                    result[index]['status'] = 'unavailable'
                    result[index]['error_code'] = exc.code
            if exc.code == 'rate_limited':
                status_receipt = record_quota(vault, clock())
                cooldown = provider_status(vault, clock())
                for index in indexes:
                    result[index]['status'] = 'rate_limited'
            elif exc.code in STOP_SOURCE_CODES:
                stopped = exc.code
    if history.read_stable(plan_path)[1] != plan_token:
        raise DataError('changed_plan', 'Capture plan changed during execution; retain saved observations and rerun planning.')
    # Manual preparation freezes whole seconds. Cross only the remaining
    # fractional second after the last actual save, never invent a future cutoff.
    if cutoff is None and any(row['status'] == 'captured' for row in result):
        boundary = max(parse_time(row['available_at']) for row in result if row['available_at']).replace(microsecond=0) + timedelta(seconds=1)
        remaining = (boundary - clock()).total_seconds()
        if 0 < remaining <= 1:
            sleep(remaining)
        if clock() < boundary:
            raise DataError('clock_boundary', 'Manual capture completed but the next whole second has not elapsed; prepare only after it does.')
    return {'market_capture': 1, 'complete': all(row['status'] in ('reused', 'captured') for row in result),
            'manual_preflight': cutoff is None, 'as_of': _iso(cutoff) if cutoff else None,
            'finished_at': _iso(clock()), 'unique_symbol_calls': calls, 'max_calls': max_calls,
            'reuse_hours': reuse_hours, 'cooldown': cooldown, 'status_receipt': status_receipt,
            'source_stop_code': stopped,
            'items': result, 'requests': client.requests if client is not None else [], 'warnings': list(WARNINGS)}


def parser():
    class SafeParser(argparse.ArgumentParser):
        def error(self, message):
            raise DataError('invalid_input', 'Invalid capture arguments; use --help.')
    class SingleCredentialsFile(argparse.Action):
        def __call__(self, parser, namespace, value, option_string=None):
            if getattr(namespace, self.dest, None) is not None:
                raise DataError('invalid_input', 'Specify --credentials-file only once.')
            setattr(namespace, self.dest, value)
    root = SafeParser(description=__doc__)
    root.add_argument('--test', action='store_true')
    sub = root.add_subparsers(dest='command', parser_class=SafeParser)
    command = sub.add_parser('capture')
    command.add_argument('--vault', required=True)
    command.add_argument('--plan', required=True)
    command.add_argument('--work-dir', required=True)
    command.add_argument('--max-calls', type=int, default=3)
    command.add_argument('--reuse-hours', type=int, default=24)
    command.add_argument('--as-of', help='already frozen cutoff; later captures remain future-only')
    command.add_argument('--credentials-file', action=SingleCredentialsFile)
    command.add_argument('--max-seconds', type=int, default=120)
    return root


def main(argv=None, client=None):
    env = dict(os.environ if client is None else client.env)
    secrets = tuple(source.get(key, '') for source in (os.environ, env) for key in CREDENTIAL_NAMES)
    secrets += tuple(getattr(client, 'redaction_values', ()))
    try:
        args = parser().parse_args(argv)
        if args.test:
            return run_self_test()
        if args.command != 'capture':
            raise DataError('invalid_input', 'Choose capture; use --help.')
        if args.credentials_file is not None:
            loaded = load_credentials(args.credentials_file)
            secrets += tuple(loaded.values())
            env = credential_environment(env, loaded)
            if client is not None:
                from copy import copy
                client = copy(client)
                client.env = env
        if client is None:
            client = HttpClient(env, max_requests=max(1, args.max_calls), max_seconds=args.max_seconds,
                                redaction_values=secrets)
        else:
            client.redaction_values = tuple(getattr(client, 'redaction_values', ())) + secrets
        result = capture(args.vault, args.plan, args.work_dir, max_calls=args.max_calls,
                         reuse_hours=args.reuse_hours, as_of=args.as_of, client=client)
        code = 0 if result['complete'] else 2
    except DataError as exc:
        result = {'market_capture': 1, 'complete': False, 'error': {'code': exc.code, 'message': str(exc)}}
        code = 2
    except RuntimeError as exc:
        result = {'market_capture': 1, 'complete': False, 'error': {
            'code': 'publication_failed', 'message': str(exc)}, 'recovery': 'preserve the named recovery stage'}
        code = 3
    except (ValueError, OSError, TypeError, KeyError, RecursionError):
        result = {'market_capture': 1, 'complete': False, 'error': {
            'code': 'invalid_input_or_storage', 'message': 'Capture input or immutable storage could not be verified; preserve existing files.'}}
        code = 2
    print(json.dumps(redact(result, env, extra_values=secrets), ensure_ascii=False, allow_nan=False))
    return code


def run_self_test():
    """Temporary vaults and synthetic transport only; never access real keys."""
    import contextlib
    from datetime import datetime
    import io
    import tempfile
    import unittest
    from unittest.mock import patch

    class CaptureTests(unittest.TestCase):
        def setUp(self):
            self.temp = tempfile.TemporaryDirectory(prefix='.capture-test-')
            self.addCleanup(self.temp.cleanup)
            self.root = Path(self.temp.name).resolve()
            self.vault = self.root / 'vault'; self.vault.mkdir()
            self.work = self.root / '.obsidian-skills-tmp-fixture'; self.work.mkdir()
            self.plan = self.work / 'plan.json'
            self.instant = datetime(2026, 9, 7, 15, 30, 0, 250000, timezone.utc)
            self.secret = 'synthetic-capture-private-key'
            self.calls, self.replies, self.sleeps = [], {}, []
            self.client = SimpleNamespace(env={'ALPHA_VANTAGE_API_KEY': self.secret}, requests=[], redaction_values=())
            self.client.get_json = self.get_json
            self.time_patch = patch.object(market_estimates, 'utc_now', side_effect=lambda: self.instant)
            self.time_patch.start(); self.addCleanup(self.time_patch.stop)

        def item(self, symbol, period='2026-11-30', horizon='fiscal quarter'):
            return {'symbol': symbol, 'period': period, 'horizon': horizon, 'reason': 'Known upcoming event'}

        def get_json(self, url, params=None):
            symbol = params['symbol']; self.calls.append(symbol)
            reply = self.replies.get(symbol, {'symbol': symbol, 'estimates': [
                {'date': '2026-11-30', 'horizon': 'fiscal quarter', 'eps_estimate_average': '2.50', 'currency': 'USD'},
                {'date': '2027-05-31', 'horizon': 'fiscal year', 'eps_estimate_average': '10.00', 'currency': 'USD'}]})
            if isinstance(reply, DataError):
                raise reply
            raw = json.dumps(reply).encode('utf-8')
            self.client.requests.append({'url': url + '?function=EARNINGS_ESTIMATES&symbol=' + symbol + '&apikey=[redacted]',
                'retrieved_at': _iso(self.instant), 'status': 200, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
            return reply

        def sleep(self, seconds):
            self.sleeps.append(seconds); self.instant += timedelta(seconds=seconds)

        def run_capture(self, items=None, **kwargs):
            self.plan.write_text(json.dumps(items or [self.item('AAA')]), encoding='utf-8')
            return capture(self.vault, self.plan, self.work, client=self.client,
                           clock=lambda: self.instant, sleep=self.sleep, **kwargs)

        def test_capture_preserves_actual_save_and_crosses_only_next_whole_second(self):
            result = self.run_capture()
            self.assertTrue(result['complete'])
            self.assertEqual(self.calls, ['AAA'])
            self.assertEqual(result['items'][0]['status'], 'captured')
            self.assertIsNone(result['items'][0]['eligible_at_cutoff'])
            self.assertEqual(self.sleeps, [0.75])
            self.assertGreater(parse_time(result['finished_at']), parse_time(result['items'][0]['available_at']))
            value = json.loads(Path(result['items'][0]['snapshot']).read_bytes())
            self.assertIsNone(value['provider_as_of'])
            self.assertEqual(value['available_at'], value['saved_at'])

        def test_reuse_is_fresh_matching_period_and_does_not_spend_calls(self):
            first = self.run_capture()
            path = Path(first['items'][0]['snapshot']); before = path.read_bytes()
            self.instant += timedelta(hours=2)
            result = self.run_capture([self.item('AAA'), self.item('BBB'), self.item('CCC')], max_calls=1)
            self.assertEqual([row['status'] for row in result['items']], ['reused', 'captured', 'budget_deferred'])
            self.assertEqual(self.calls, ['AAA', 'BBB'])
            self.assertEqual(path.read_bytes(), before)

        def test_ordered_priority_and_multiple_periods_share_one_symbol_request(self):
            result = self.run_capture([self.item('BBB'), self.item('AAA'),
                self.item('BBB', '2027-05-31', 'fiscal year'), self.item('CCC')], max_calls=2)
            self.assertEqual(self.calls, ['BBB', 'AAA'])
            self.assertEqual([row['status'] for row in result['items']], ['captured', 'captured', 'captured', 'budget_deferred'])
            self.assertNotEqual(result['items'][0]['snapshot'], result['items'][2]['snapshot'])

        def test_quota_persists_and_cache_remains_available_during_cooldown(self):
            self.run_capture()
            self.replies['BBB'] = {'Note': 'API call volume quota reached for ' + self.secret}
            result = self.run_capture([self.item('BBB'), self.item('AAA'), self.item('CCC')])
            self.assertEqual(self.calls, ['AAA', 'BBB'])
            self.assertEqual([row['status'] for row in result['items']], ['rate_limited', 'reused', 'cooldown'])
            self.assertTrue(result['cooldown']['active'])
            self.assertIsNone(result['cooldown']['provider_reset_at'])
            next_run = self.run_capture([self.item('AAA'), self.item('DDD')])
            self.assertEqual(next_run['unique_symbol_calls'], 0)
            self.assertEqual([row['status'] for row in next_run['items']], ['reused', 'cooldown'])
            for path in self.vault.rglob('*.json'):
                self.assertNotIn(self.secret, path.read_text(encoding='utf-8'))
                self.assertNotIn('quota reached for', path.read_text(encoding='utf-8'))

        def test_expired_cooldown_is_not_a_guaranteed_reset_and_stale_cache_is_not_reused(self):
            record_quota(self.vault, self.instant - timedelta(hours=25))
            self.assertFalse(provider_status(self.vault, self.instant)['active'])
            self.run_capture()
            self.instant += timedelta(hours=25)
            result = self.run_capture()
            self.assertEqual(self.calls, ['AAA', 'AAA'])
            self.assertEqual(result['items'][0]['status'], 'captured')
            self.assertTrue(any('not a provider reset guarantee' in warning for warning in result['warnings']))

        def test_access_transport_or_budget_failure_stops_source_without_invented_quota(self):
            for code in ('access_denied', 'network_error', 'request_budget'):
                self.calls.clear()
                self.replies['AAA'] = DataError(code, 'Synthetic safe failure')
                result = self.run_capture([self.item('AAA'), self.item('BBB')])
                self.assertEqual(self.calls, ['AAA'])
                self.assertEqual([row['status'] for row in result['items']], ['unavailable', 'source_unavailable'])
                self.assertEqual(result['source_stop_code'], code)
                self.assertFalse(result['cooldown']['active'])
                self.assertIsNone(result['status_receipt'])
                self.assertFalse(self.vault.joinpath(*STATUS_FOLDER).exists())

        def test_frozen_cutoff_is_never_shifted_and_late_capture_is_future_only(self):
            cutoff = self.instant - timedelta(seconds=1)
            result = self.run_capture(as_of=_iso(cutoff))
            self.assertEqual(result['as_of'], _iso(cutoff))
            self.assertEqual(result['items'][0]['status'], 'captured_future_only')
            self.assertFalse(result['items'][0]['eligible_at_cutoff'])
            self.assertFalse(result['complete'])
            self.assertEqual(self.sleeps, [])
            self.instant += timedelta(seconds=2)
            later = self.run_capture(as_of=_iso(self.instant))
            self.assertEqual(later['items'][0]['status'], 'reused')
            self.assertTrue(later['items'][0]['eligible_at_cutoff'])
            self.assertEqual(len(self.calls), 1)

        def test_unknown_matching_horizon_stays_unavailable(self):
            result = self.run_capture([self.item('AAA', horizon='fiscal year')])
            self.assertEqual(result['items'][0]['status'], 'coverage_unavailable')
            self.assertFalse(result['complete'])

        def test_zero_budget_allows_cache_only_without_transport(self):
            self.run_capture()
            result = self.run_capture([self.item('AAA'), self.item('BBB')], max_calls=0)
            self.assertEqual([row['status'] for row in result['items']], ['reused', 'budget_deferred'])
            self.assertEqual(result['unique_symbol_calls'], 0)

        def test_bad_status_or_symlink_stops_before_any_request(self):
            saved = record_quota(self.vault, self.instant - timedelta(hours=25))
            path = Path(saved['path']); original = path.read_bytes()
            path.write_bytes(original + b' ')
            with self.assertRaises(DataError):
                self.run_capture()
            self.assertEqual(self.calls, [])
            path.unlink(); target = self.root / 'outside.json'; target.write_bytes(original); path.symlink_to(target)
            with self.assertRaises(ValueError):
                self.run_capture()
            self.assertEqual(self.calls, [])

        def test_unexpected_status_name_and_folder_owner_fail_closed(self):
            record_quota(self.vault, self.instant - timedelta(hours=25))
            folder = self.vault.joinpath(*STATUS_FOLDER)
            (folder / 'unowned.json').write_text('{}', encoding='utf-8')
            with self.assertRaises(DataError):
                self.run_capture()
            (folder / 'unowned.json').unlink()
            moved = self.root / 'status'; folder.rename(moved); folder.symlink_to(moved, target_is_directory=True)
            with self.assertRaises(ValueError):
                self.run_capture()
            self.assertEqual(self.calls, [])

        def test_portable_equivalent_status_folder_owner_is_not_adopted(self):
            record_quota(self.vault, self.instant - timedelta(hours=25))
            folder = self.vault.joinpath(*STATUS_FOLDER)
            folder.rename(folder.with_name('providerstatus'))
            with self.assertRaisesRegex(ValueError, 'portable-equivalent'):
                self.run_capture()
            self.assertEqual(self.calls, [])

        def test_missing_status_during_read_is_not_treated_as_no_cooldown(self):
            record_quota(self.vault, self.instant - timedelta(hours=25))
            with patch.object(evidence, 'read_bytes', side_effect=FileNotFoundError):
                with self.assertRaisesRegex(DataError, 'disappeared'):
                    self.run_capture()
            self.assertEqual(self.calls, [])

        def test_plan_duplicates_wrong_types_and_unsafe_work_dir_are_rejected(self):
            for items in ([self.item('AAA'), self.item('AAA')], [dict(self.item('AAA'), symbol='../AAA')],
                          [dict(self.item('AAA'), extra='unexpected')], [dict(self.item('AAA'), reason='\ud800')]):
                with self.subTest(items=items), self.assertRaises(ValueError):
                    self.run_capture(items)
            with self.assertRaises(DataError):
                capture(self.vault, self.plan, self.vault, client=self.client)
            self.assertEqual(self.calls, [])

        def test_cli_redacts_failures_and_constructs_one_bounded_transport(self):
            self.plan.write_text(json.dumps([self.item('AAA')]), encoding='utf-8')
            output = io.StringIO()
            with patch.object(sys.modules[__name__], 'HttpClient', return_value=self.client) as constructor:
                with patch.object(sys.modules[__name__], 'capture', return_value={'market_capture': 1, 'complete': True}):
                    with contextlib.redirect_stdout(output):
                        self.assertEqual(main(['capture', '--vault', str(self.vault), '--plan', str(self.plan),
                                              '--work-dir', str(self.work), '--max-calls', '2']), 0)
            self.assertEqual(constructor.call_count, 1)
            self.assertEqual(constructor.call_args.kwargs['max_requests'], 2)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(['capture', '--unknown', self.secret], client=self.client), 2)
            self.assertNotIn(self.secret, output.getvalue())

        def test_cli_preserves_recovery_instruction_without_echoing_secrets(self):
            output = io.StringIO()
            failure = RuntimeError('preserve recovery stage /private/tmp/synthetic-stage: ' + self.secret)
            with patch.object(sys.modules[__name__], 'capture', side_effect=failure):
                with contextlib.redirect_stdout(output):
                    code = main(['capture', '--vault', str(self.vault), '--plan', str(self.plan),
                                 '--work-dir', str(self.work)], client=self.client)
            self.assertEqual(code, 3)
            self.assertNotIn(self.secret, output.getvalue())
            self.assertIn('/private/tmp/synthetic-stage', output.getvalue())
            self.assertIn('preserve', json.loads(output.getvalue())['recovery'])

    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(CaptureTests))
    print('%d/%d self-tests passed' % (result.testsRun - len(result.failures) - len(result.errors), result.testsRun))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
