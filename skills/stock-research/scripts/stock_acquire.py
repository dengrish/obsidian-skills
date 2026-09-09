#!/usr/bin/env python3
"""Plan, then explicitly acquire bounded evidence for already verified stock nominees.

Coordinates the existing price/estimate archival helpers with one transport and
one fixed HTTP-attempt budget. Never discovers securities or collects feeds.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

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
import market_capture as estimates
import market_price_capture as prices
import market_estimate_history as history
import market_estimates
from market_acquire import Scratch
from market_credentials import credential_environment, load_credentials
from market_http import CREDENTIAL_NAMES, DataError, HttpClient, parse_date, parse_time, redact, utc_now

MAX_TARGETS = 100
MAX_PLAN_BYTES = 256 * 1024
ORIGIN_KINDS = {'feed', 'prior_stock', 'user'}


def _fail(message):
    raise DataError('invalid_nomination_plan', message)


def _text(value, limit=400):
    if (not isinstance(value, str) or not 1 <= len(value.strip()) <= limit
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        _fail('Use bounded plain text for nomination sources and justifications.')
    try:
        value.encode('utf-8')
    except UnicodeError:
        _fail('Nomination text must be valid UTF-8.')
    return value


def read_plan(path, current, cutoff=None):
    raw, token = history.read_stable(path)
    if len(raw) > MAX_PLAN_BYTES:
        _fail('The nomination plan exceeds 256 KiB; split the explicitly justified scope.')
    plan = estimates._json(raw)
    if not isinstance(plan, list) or not 1 <= len(plan) <= MAX_TARGETS:
        _fail('Use one to 100 explicit nominees per plan; carry further justified nominees in a separate continuation plan.')
    seen = set()
    for row in plan:
        if (not isinstance(row, dict) or set(row) - (prices.PLAN_KEYS | {'origins', 'estimates'})
                or not (prices.PLAN_KEYS | {'origins'}) <= set(row)):
            _fail('Each nominee needs the price-plan identity/reason fields, origins and optional estimates.')
        prices._item({key: row[key] for key in prices.PLAN_KEYS}, current)
        if row['symbol'] in seen:
            _fail('Each symbol must appear once with one explicitly verified quoted class.')
        seen.add(row['symbol'])
        if cutoff and parse_time(row['identity_available_at']) > cutoff:
            _fail('Quoted-class identity evidence must be available by the fixed cutoff.')
        if not isinstance(row['origins'], list) or not 1 <= len(row['origins']) <= 8:
            _fail('Supply one to eight verified nomination origins.')
        for origin in row['origins']:
            if not isinstance(origin, dict) or set(origin) != {'kind', 'source', 'available_at'}:
                _fail('Each origin needs exactly kind, source and available_at.')
            if origin['kind'] not in ORIGIN_KINDS:
                _fail('Origins must be feed, prior_stock or an explicit user nomination.')
            _text(origin['source'], 1000)
            if parse_time(origin['available_at']) > (cutoff or current):
                _fail('Nomination origins must already be available at the applicable cutoff.')
        fiscal = row.get('estimates', [])
        if not isinstance(fiscal, list) or len(fiscal) > 8:
            _fail('Declare at most eight justified fiscal period/horizon pairs per nominee.')
        periods = set()
        for item in fiscal:
            if not isinstance(item, dict) or set(item) != {'period', 'horizon', 'reason'}:
                _fail('Estimate selections need exactly period, horizon and reason.')
            parse_date(item['period'])
            _text(item['reason'])
            if item['horizon'] not in market_estimates.HORIZONS:
                _fail('Use the existing estimate adapter\'s supported fiscal horizon.')
            identity = item['period'], item['horizon']
            if identity in periods:
                _fail('Duplicate fiscal period/horizon within one nominee.')
            periods.add(identity)
    return plan, token, hashlib.sha256(raw).hexdigest()


def _price_plan(plan):
    return [{key: row[key] for key in prices.PLAN_KEYS} for row in plan]


def _plan_bytes(rows):
    return len(json.dumps(rows, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) + 1


def _price_batches(plan):
    batch = []
    for row in plan:
        if batch and (len(batch) >= 30 or _plan_bytes(_price_plan(batch + [row])) > 32768):
            yield batch
            batch = []
        batch.append(row)
    if batch:
        yield batch


def _estimate_batches(plan):
    """Keep every period for a symbol together, within both existing helper bounds."""
    batch, symbols = [], 0
    for row in plan:
        fiscal = [dict(item, symbol=row['symbol']) for item in row.get('estimates', [])]
        if fiscal and (len(batch) + len(fiscal) > 30 or symbols >= 10
                       or _plan_bytes(batch + fiscal) > 32768):
            yield batch
            batch, symbols = [], 0
        if fiscal:
            batch.extend(fiscal)
            symbols += 1
    if batch:
        yield batch


def _estimate_cache(vault, plan, current, cutoff, reuse_hours):
    rows = []
    for nominee in plan:
        if not nominee.get('estimates'):
            continue
        saved = history.estimate_history(vault, history._iso(current), nominee['symbol'], now=current)['snapshots']
        for item in nominee['estimates']:
            matching = [record for record in saved
                if record['snapshot']['record']['fiscal_period_end'] == item['period']
                and record['snapshot']['record']['horizon'] == item['horizon']
                and parse_time(record['snapshot']['observed_at']) >= current - timedelta(hours=reuse_hours)]
            eligible = [record for record in matching if not cutoff or parse_time(record['available_at']) <= cutoff]
            chosen = max(eligible or matching, key=lambda record: (
                parse_time(record['snapshot']['observed_at']), parse_time(record['available_at'])), default=None)
            rows.append(dict(item, symbol=nominee['symbol'],
                status=('reused' if eligible else 'reused_future_only') if chosen else 'planned',
                snapshot=chosen['path'] if chosen else None,
                available_at=chosen['available_at'] if chosen else None))
    return rows


def _recheck_estimates(vault, rows, current, cutoff, reuse_hours):
    """Validate retained successes at completion without another provider call."""
    cached = {}
    for row in rows:
        if row['status'] not in {'captured', 'reused'}:
            continue
        symbol = row['symbol']
        if symbol not in cached:
            cached[symbol] = history.estimate_history(
                vault, history._iso(current), symbol, now=current)['snapshots']
        record = next((item for item in cached[symbol]
            if item['path'] == row['snapshot']
            and item['snapshot']['record']['fiscal_period_end'] == row['period']
            and item['snapshot']['record']['horizon'] == row['horizon']), None)
        original = row['status']
        if record is None:
            row.update(status='unavailable', acquisition_status=original,
                       error_code='estimate_archive_missing')
        elif cutoff and parse_time(record['available_at']) > cutoff:
            row.update(status=original + '_future_only', acquisition_status=original,
                       eligible_at_cutoff=False)
        elif parse_time(record['snapshot']['observed_at']) < current - timedelta(hours=reuse_hours):
            row.update(status='stale', acquisition_status=original,
                       error_code='estimate_stale', freshness_checked_at=history._iso(current))


class RunClient:
    """Memoize bounded requests; the underlying HttpClient alone performs retries.

    Request provenance replayed to an archival adapter is separate from the
    actual transport ledger. Every physical retry still consumes the one budget.
    """
    def __init__(self, client, max_requests, scratch):
        self.client, self.limit, self.scratch = client, max_requests, scratch
        self.env, self.redaction_values = client.env, getattr(client, 'redaction_values', ())
        self.requests, self.memo, self.stopped = [], {}, {}
        self.first = len(client.requests)
        self.reuses, self.invocations = 0, 0
        if hasattr(client, 'max_requests'):
            client.max_requests = min(client.max_requests, getattr(client, 'attempts', 0) + max_requests)

    @property
    def actual(self):
        return self.client.requests[self.first:]

    def get_json(self, url, params=None, headers=None):
        # The key is memory-only: credentials are never published in filenames.
        key = (url, json.dumps(params or {}, sort_keys=True), json.dumps(headers or {}, sort_keys=True))
        if key in self.memo:
            payload, events = self.memo[key]
            self.requests.extend(deepcopy(events))
            self.reuses += 1
            return deepcopy(payload)
        source = 'alpaca' if 'alpaca.markets/' in url else 'alpha_vantage'
        blocked = self.stopped.get('all') or self.stopped.get(source) or self.stopped.get(url)
        if blocked:
            raise DataError(blocked, 'Earlier source failure stopped further requests in this run.')
        if len(self.actual) >= self.limit:
            self.stopped['all'] = 'request_budget'
            raise DataError('request_budget', 'The whole-run request budget is exhausted; retain unresolved targets.')
        self.invocations += 1
        number = self.invocations
        # An intent with no corresponding completion identifies an interrupted
        # request. It is never silently resumed as another paid request.
        self.scratch.save('request-%03d-intent.json' % number,
            {'request_intent': 1, 'source': source, 'endpoint': url,
             'query': redact(params or {}, self.env, extra_values=self.redaction_values),
             'remaining_attempt_budget': self.limit - len(self.actual)})
        first = len(self.client.requests)
        error, completed = None, False
        try:
            payload = self.client.get_json(url, params=params, headers=headers) if headers is not None else self.client.get_json(url, params=params)
            completed = True
        except DataError as exc:
            error, completed = exc.code, True
            if error == 'request_budget':
                self.stopped['all'] = error
            elif error in {'rate_limited', 'invalid_credentials', 'missing_credentials'}:
                self.stopped[source] = error
            elif error in {'access_denied', 'network_error', 'http_error', 'redirect'}:
                self.stopped[url] = error
            raise
        finally:
            events = self.client.requests[first:]
            self.requests.extend(deepcopy(events))
            if completed:
                self.scratch.save('request-%03d-complete.json' % number,
                    redact({'request_completion': 1, 'error_code': error, 'requests': events},
                           self.env, extra_values=self.redaction_values))
        self.memo[key] = deepcopy(payload), deepcopy(events)
        return payload


def acquire(vault, plan_path, work_dir, *, execute=False, as_of=None, max_requests=20,
            max_estimate_calls=3, reuse_hours=24, max_seconds=None,
            client=None, clock=utc_now, sleep=time.sleep):
    if (type(max_requests) is not int or not 0 <= max_requests <= 100
            or type(max_estimate_calls) is not int or not 0 <= max_estimate_calls <= 100
            or type(reuse_hours) is not int or not 1 <= reuse_hours <= 24):
        _fail('Use zero to 100 whole-run requests and estimate calls, and one to 24 reuse hours.')
    # During execution only transport-owned metadata establishes its configured
    # cap. A declared plan option cannot tighten an injected client's deadline.
    if execute:
        max_seconds = getattr(client, 'max_seconds', None)
    if max_seconds is not None and (type(max_seconds) not in (int, float)
            or not math.isfinite(max_seconds) or not 1 <= max_seconds <= 600):
        _fail('A known transport time budget must be one to 600 seconds.')
    current = clock()
    cutoff = parse_time(as_of) if as_of else None
    if cutoff and cutoff > current:
        _fail('A fixed cutoff cannot be in the future.')
    plan, token, digest = read_plan(plan_path, current, cutoff)
    work = estimates._work_folder(work_dir, vault)
    price_initial = prices.select(vault, _price_plan(plan), history._iso(cutoff or current), current=current)
    estimate_initial = _estimate_cache(vault, plan, current, cutoff, reuse_hours)
    cooldown = estimates.provider_status(vault, current)
    price_missing = sum(row['status'] not in {'selected', 'future_only'} for row in price_initial['items'])
    estimate_missing = list(dict.fromkeys(row['symbol'] for row in estimate_initial if row['status'] == 'planned'))
    result = {'stock_acquire': 1, 'executed': execute, 'plan_sha256': digest,
        'as_of': history._iso(cutoff) if cutoff else None, 'preparing': cutoff is None,
        'scope': plan, 'target_count': len(plan),
        'budget': {'max_requests': max_requests, 'max_estimate_calls': max_estimate_calls,
                   'max_seconds': max_seconds, 'reuse_hours': reuse_hours,
                   'http_attempts': 0, 'estimate_symbol_calls': 0, 'memoized_requests': 0},
        'planned': {'price_symbols_missing': price_missing,
                    'estimate_symbols_missing': estimate_missing, 'cooldown': cooldown},
        'prices': price_initial['items'], 'estimates': estimate_initial,
        'requests': [], 'ready_to_freeze_after': None, 'scratch': None,
        'warnings': ['Source origins and quoted class are explicit reviewed declarations, not inferred ticker identities.',
                     'Raw price acquisition does not establish shares outstanding, entire-issuer capitalization or research readiness.',
                     'A fixed cutoff never advances; later saves remain available only to subsequent editions.',
                     'A new execution has a newly declared budget; no unresolved target is retried automatically.']}
    if not execute:
        return _finish(result, plan)
    if client is None:
        raise DataError('missing_client', 'Explicit execution needs one bounded market transport.')
    scratch = Scratch(work, vault)
    result['scratch'] = str(scratch.root)
    scratch.save('plan.json', plan)
    scratch.save('budget.json', dict(result['budget'], plan_sha256=digest, as_of=result['as_of']))
    run = RunClient(client, max_requests, scratch)
    captures = {}
    for index, selected in enumerate(_price_batches(plan)):
        path = scratch.save('prices-%03d-plan.json' % index, _price_plan(selected))
        data = prices.capture(vault, path, max_symbols=30, as_of=as_of, client=run, clock=clock, sleep=sleep)
        scratch.save('prices-%03d-result.json' % index, data)
        captures.update((row['symbol'], row) for row in data['items'])
    estimate_rows, calls, stop = [], 0, None
    for index, batch in enumerate(_estimate_batches(plan)):
        path = scratch.save('estimates-%03d-plan.json' % index, batch)
        allowance = 0 if stop else min(10, max_estimate_calls - calls)
        data = estimates.capture(vault, path, work, max_calls=allowance, reuse_hours=reuse_hours,
                                 as_of=as_of, client=run, clock=clock, sleep=sleep)
        if stop:
            for row in data['items']:
                if row['status'] == 'budget_deferred':
                    row.update(status='source_unavailable', error_code=stop)
        calls += data['unique_symbol_calls']
        stop = stop or data['source_stop_code']
        scratch.save('estimates-%03d-result.json' % index, data)
        estimate_rows.extend(data['items'])
        cooldown = data['cooldown']
    if history.read_stable(plan_path)[1] != token:
        raise DataError('changed_plan', 'Nomination plan changed; preserve all saved evidence and run artifacts.')
    # Re-select after ALL phases: an early price can become stale during later
    # estimate work. The fresh cutoff is real completion, never a predicted save.
    finished = clock()
    if cutoff is None:
        available = [parse_time(row['available_at']) for row in estimate_rows if row.get('available_at')]
        available += [parse_time(row['price']['available_at']) for row in captures.values() if row.get('price')]
        if available and max(available) > finished.replace(microsecond=0):
            boundary = finished.replace(microsecond=0) + timedelta(seconds=1)
            sleep((boundary - finished).total_seconds())
            finished = clock()
            if finished < boundary:
                raise DataError('clock_boundary', 'Wait for actual publication completion before preparing research.')
    final_prices = prices.select(vault, _price_plan(plan), history._iso(cutoff or finished), current=finished)
    _recheck_estimates(vault, estimate_rows, finished, cutoff, reuse_hours)
    for row in final_prices['items']:
        prior = captures[row['symbol']]
        row.update({key: prior[key] for key in ('capture_status', 'capture_error') if key in prior})
    result.update(prices=final_prices['items'], estimates=estimate_rows, cooldown=cooldown,
                  finished_at=history._iso(finished), requests=run.actual,
                  ready_to_freeze_after=history._iso(finished) if cutoff is None else None)
    result['budget'].update(http_attempts=len(run.actual), estimate_symbol_calls=calls, memoized_requests=run.reuses,
                            remaining_requests=max(0, max_requests - len(run.actual)))
    result = _finish(result, plan)
    result['continuation_plan'] = scratch.save('continuation-plan.json', result['continuation'])
    scratch.save('result.json', redact(result, run.env, extra_values=run.redaction_values, price_bars=True))
    return result


def _finish(result, plan):
    estimates_by_symbol = {}
    for row in result['estimates']:
        estimates_by_symbol.setdefault(row['symbol'], []).append(row)
    targets, continuation = [], []
    for nominee, price in zip(plan, result['prices']):
        fiscal = estimates_by_symbol.get(nominee['symbol'], [])
        limitations = []
        if price['status'] != 'selected':
            limitations.append({'resource': 'raw_price', 'status': price['status'],
                                'error_code': price.get('capture_error')})
        for row in fiscal:
            if row['status'] not in {'reused', 'captured'}:
                limitations.append({'resource': 'estimate', 'period': row['period'], 'horizon': row['horizon'],
                                    'status': row['status'], 'error_code': row.get('error_code'),
                                    'coverage': row.get('coverage')})
        targets.append({'symbol': nominee['symbol'], 'class_id': nominee['class_id'], 'limitations': limitations})
        retry_estimates = [item for item in nominee.get('estimates', [])
            if any(row['period'] == item['period'] and row['horizon'] == item['horizon']
                   and row['status'] not in {'reused', 'captured', 'reused_future_only', 'captured_future_only'} for row in fiscal)]
        if price['status'] not in {'selected', 'future_only'} or retry_estimates:
            continuation.append(dict(nominee, estimates=retry_estimates))
    result.update(targets=targets, complete=all(not row['limitations'] for row in targets), continuation=continuation)
    return result


def parser():
    class SafeParser(argparse.ArgumentParser):
        def error(self, message):
            raise DataError('invalid_input', 'Invalid targeted-acquisition arguments; use --help.')
    root = SafeParser(description=__doc__)
    root.add_argument('--test', action='store_true')
    root.add_argument('--vault')
    root.add_argument('--plan')
    root.add_argument('--work-dir')
    root.add_argument('--execute', action='store_true')
    root.add_argument('--as-of')
    root.add_argument('--max-requests', type=int, default=20)
    root.add_argument('--max-estimate-calls', type=int, default=3)
    root.add_argument('--reuse-hours', type=int, default=24)
    root.add_argument('--max-seconds', type=int, default=120)
    root.add_argument('--credentials-file', action='append')
    return root


def main(argv=None, client=None):
    env, secrets = {}, ()
    try:
        args = parser().parse_args(argv)
        if args.test:
            return run_self_test()
        if not all((args.vault, args.plan, args.work_dir)):
            raise DataError('invalid_input', 'Specify vault, nomination plan and private work directory.')
        if args.credentials_file and (len(args.credentials_file) != 1 or not args.execute):
            raise DataError('invalid_input', 'Use one credentials file only with explicit execution.')
        if args.execute:
            env = dict(os.environ if client is None else client.env)
            secrets = tuple(env.get(key, '') for key in CREDENTIAL_NAMES) + tuple(getattr(client, 'redaction_values', ()))
            if args.credentials_file:
                loaded = load_credentials(args.credentials_file[0])
                secrets += tuple(loaded.values())
                env = credential_environment(env, loaded)
            if client is None:
                client = HttpClient(env, max_requests=max(1, args.max_requests), max_seconds=args.max_seconds,
                                    redaction_values=secrets)
                # Record the bound passed to this exact transport constructor.
                # Pre-existing clients keep their own metadata, or unknown.
                client.max_seconds = args.max_seconds
            client.env, client.redaction_values = env, secrets
        result = acquire(args.vault, args.plan, args.work_dir, execute=args.execute, as_of=args.as_of,
            max_requests=args.max_requests, max_estimate_calls=args.max_estimate_calls,
            reuse_hours=args.reuse_hours, max_seconds=args.max_seconds, client=client)
        code = 0 if result['complete'] or not args.execute else 2
    except DataError as exc:
        result = {'stock_acquire': 1, 'complete': False, 'error': {'code': exc.code, 'message': str(exc)}}
        code = 2
    except RuntimeError as exc:
        result = {'stock_acquire': 1, 'complete': False, 'error': {'code': 'publication_failed', 'message': str(exc)},
                  'recovery': 'Preserve the named recovery stage and request-intent records; do not automatically repeat an interrupted request.'}
        code = 3
    except (ValueError, OSError, TypeError, KeyError, RecursionError):
        result = {'stock_acquire': 1, 'complete': False, 'error': {'code': 'invalid_input_or_storage',
                  'message': 'Input or immutable evidence could not be verified; preserve saved run artifacts.'}}
        code = 2
    print(json.dumps(redact(result, env, extra_values=secrets, price_bars=True), ensure_ascii=False, allow_nan=False))
    return code


def run_self_test():
    import tempfile
    import unittest
    from datetime import datetime, timezone

    class PlanTests(unittest.TestCase):
        def test_batches_keep_symbol_periods_together(self):
            rows = [{'symbol': 'S%02d' % n, 'estimates': [
                {'period': '2026-12-31', 'horizon': 'fiscal year', 'reason': 'Explicit event review'}]}
                for n in range(23)]
            batches = list(_estimate_batches(rows))
            self.assertEqual([len(batch) for batch in batches], [10, 10, 3])
            self.assertEqual([row['symbol'] for batch in batches for row in batch], [row['symbol'] for row in rows])

        def test_rejects_unknown_origin_and_duplicate_identity(self):
            row = {'symbol': 'AAA', 'class_id': 'common', 'identity_source_url': 'https://example.com/issuer',
                   'identity_available_at': '2026-01-01T00:00:00Z', 'reason': 'Explicit nominee',
                   'origins': [{'kind': 'discovery', 'source': 'broad market', 'available_at': '2026-01-01T00:00:00Z'}]}
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'plan.json'
                path.write_text(json.dumps([row]), encoding='utf-8')
                with self.assertRaises(DataError):
                    read_plan(path, datetime(2026, 9, 8, tzinfo=timezone.utc))
                row['origins'][0]['kind'] = 'user'
                path.write_text(json.dumps([row, row]), encoding='utf-8')
                with self.assertRaises(DataError):
                    read_plan(path, datetime(2026, 9, 8, tzinfo=timezone.utc))
    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(PlanTests))
    print('%d/%d self-tests passed' % (result.testsRun - len(result.failures) - len(result.errors), result.testsRun))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
