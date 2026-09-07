#!/usr/bin/env python3
"""Acquire a bounded, directory-derived stock screen through bundled adapters.

Writes only a new private subdirectory of external run scratch. It neither
publishes research nor marks a security ready. Missing batches remain visible.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from market_credentials import credential_environment, load_credentials
from market_data import handlers, parser as data_parser
from market_http import CREDENTIAL_NAMES, DataError, HttpClient, parse_time, redact, utc_now
from market_screen import MAX_INPUT_BYTES, _calendar


STOP_CODES = {'request_budget', 'rate_limited', 'access_denied', 'missing_credentials',
              'invalid_credentials', 'network_error'}


class ArtifactTooLarge(ValueError):
    """An intact source/result does not fit one bounded scratch artifact."""


def _error_code(result):
    pagination = result.get('pagination')
    error = result.get('error') or (pagination.get('error') if isinstance(pagination, dict) else None)
    return error.get('code') if isinstance(error, dict) else None


class Acquisition:
    """One client shares transport time/request limits across all stages."""
    def __init__(self, client):
        self.client = client
        self.operations = []
        self.stopped = {}

    def fetch(self, argv):
        args = data_parser().parse_args(argv)
        source = 'nasdaq' if args.command == 'symbols' else 'alpaca'
        first = len(self.client.requests)
        blocked = self.stopped.get(source) or self.stopped.get(source + ':' + args.command)
        if blocked:
            result = {'complete': False, 'error': {'code': blocked,
                       'message': 'This source stopped earlier in the acquisition; no additional request was made.'}}
        else:
            try:
                result = handlers()[args.command](self.client, args)
            except DataError as exc:
                result = {'complete': False, 'error': {'code': exc.code, 'message': str(exc)}}
        if not isinstance(result, dict) or not isinstance(result.get('complete'), bool):
            result = {'complete': False, 'error': {'code': 'invalid_response',
                       'message': 'Provider adapter returned an invalid result; no complete coverage was assumed.'}}
        result = redact(dict(result, market_data=1, operation=args.command,
                             requests=self.client.requests[first:]), self.client.env,
                        extra_values=getattr(self.client, 'redaction_values', ()))
        code = _error_code(result)
        if code in STOP_CODES:
            scope = source + ':' + args.command if code in {'access_denied', 'network_error'} else source
            self.stopped[scope] = code
        self.operations.append({'operation': args.command, 'source': source,
                                'complete': result['complete'], 'error_code': code,
                                'requests': len(result['requests'])})
        return result


class Scratch:
    def __init__(self, work_dir, vault):
        parent = Path(work_dir).expanduser().resolve(strict=True)
        vault = Path(vault).expanduser().resolve(strict=True)
        if not parent.is_dir() or parent == vault or vault in parent.parents:
            raise ValueError('Acquisition scratch must be an existing directory outside the selected vault.')
        for ancestor in (parent, *parent.parents):
            if (ancestor / '.obsidian').exists():
                raise ValueError('Acquisition scratch must not be inside an Obsidian vault.')
        self.root = Path(tempfile.mkdtemp(prefix='acquisition-', dir=parent))
        self.identity = (self.root.stat().st_dev, self.root.stat().st_ino)

    def save(self, name, value):
        if Path(name).name != name or not name.endswith('.json'):
            raise ValueError('Invalid private acquisition artifact name.')
        data = (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n').encode()
        if len(data) > MAX_INPUT_BYTES:
            raise ArtifactTooLarge('An acquisition artifact exceeds the screen input byte bound; retain earlier scratch and its complete declared scope.')
        descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino) != self.identity:
                raise ValueError('Acquisition scratch owner changed; preserve the original output.')
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=descriptor)
            with os.fdopen(fd, 'wb') as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
                written = os.fstat(handle.fileno())
            current = self.root.lstat()
            named = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if (not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != self.identity
                    or not stat.S_ISREG(named.st_mode)
                    or (named.st_dev, named.st_ino, named.st_size, named.st_mtime_ns, named.st_ctime_ns)
                    != (written.st_dev, written.st_ino, written.st_size, written.st_mtime_ns, written.st_ctime_ns)):
                raise ValueError('Acquisition scratch changed during publication; preserve the original output.')
        finally:
            os.close(descriptor)
        return str(self.root / name)


def _batches(run, plan, start, end, mapping, scratch, prefix, benchmarks=()):
    results, attempted = [], []
    benchmarks = list(dict.fromkeys(benchmarks))
    capacity = 200 - len(benchmarks)
    if capacity < 1:
        raise ValueError('Benchmark list leaves no stock slots within the provider symbol limit.')
    for planned in plan['batches']:
        for offset in range(0, len(planned), capacity):
            if 'alpaca' in run.stopped or 'alpaca:prices' in run.stopped:
                return results, attempted
            group = planned[offset:offset + capacity]
            symbols = list(dict.fromkeys(list(group) + benchmarks))
            result = run.fetch(['prices', '--symbols', ','.join(symbols), '--start', start,
                                '--end', end, '--adjustment', 'split', '--asof', mapping,
                                '--max-pages', '20'])
            path = scratch.save('%s-%04d.json' % (prefix, len(attempted) + 1), result)
            attempted.append({'symbols': group, 'path': path, 'complete': result['complete']})
            if isinstance(result.get('data', {}).get('bars'), dict):
                results.append(result)
    return results, attempted


def _finish(scratch, result):
    """Retain a discoverable manifest even after a later stage fails safely."""
    result['outputs']['manifest'] = str(scratch.root / 'manifest.json')
    try:
        scratch.save('manifest.json', result)
    except (ValueError, TypeError, OSError, OverflowError):
        result['complete'] = False
        result['manifest_error'] = 'Manifest could not be saved; preserve the named scratch directory and its earlier artifacts.'
    return result


def discover(client, vault, work_dir, as_of, news_since, *, batch_size=100, benchmark='SPY', now=None):
    from market_universe import universe, prefilter, prepare
    from market_screen import screen
    current, cutoff, since = now or utc_now(), parse_time(as_of), parse_time(news_since)
    if cutoff > current or since > cutoff:
        raise ValueError('Discovery requires news-since <= as-of <= now.')
    if benchmark != 'SPY':
        raise ValueError('This discovery workflow uses SPY; alternate benchmarks need a declared offline screen.')
    ny = ZoneInfo('America/New_York')
    day = cutoff.astimezone(ny).date()
    # Respect delayed SIP even during weekend/manual runs and the first minutes
    # after midnight. The bar adapter separately excludes incomplete dates.
    end = min(cutoff, current - timedelta(minutes=15)).isoformat()
    start = datetime.combine(day - timedelta(days=450), datetime.min.time(), ny).isoformat()
    scratch, run = Scratch(work_dir, vault), Acquisition(client)
    outputs, stage = {}, 'directory'
    result = {'complete': False, 'scratch': str(scratch.root), 'as_of': as_of,
              'outputs': outputs, 'operations': run.operations,
              'preliminary_batches': [], 'history_batches': [], 'last_completed_stage': None,
              'stopped_sources': run.stopped,
              'warnings': ['Daily turnover is a preliminary proxy. Verify regular-session liquidity and dated market capitalization for every shortlisted security.',
                           'A broad directory screen is not a verified investment recommendation; partial batches remain unavailable.']}
    try:
        directory = run.fetch(['symbols'])
        outputs['directory'] = scratch.save('directory.json', directory)
        result['last_completed_stage'] = stage
        if not directory['complete']:
            result['reason'] = 'A complete directory was unavailable; no smaller roster was silently substituted.'
            return _finish(scratch, result)
        stage = 'universe'
        roster = universe(directory, as_of, batch_size=batch_size)
        outputs['universe'] = scratch.save('universe.json', roster)
        result['last_completed_stage'] = stage
        stage = 'calendar'
        calendar = run.fetch(['sessions', '--start', start[:10], '--end', day.isoformat()])
        outputs['calendar'] = scratch.save('calendar.json', calendar)
        result['last_completed_stage'] = stage
        stage = 'news'
        news = run.fetch(['news', '--provider', 'alpaca', '--since', news_since, '--as-of', as_of,
                           '--limit', '50', '--max-pages', '10'])
        outputs['news'] = scratch.save('news.json', news)
        result['last_completed_stage'] = stage
        if not calendar['complete']:
            result['reason'] = 'Calendar unavailable; no session-based screen was inferred.'
            return _finish(scratch, result)
        stage = 'calendar-windows'
        _, _, required_days, _ = _calendar(calendar, cutoff)
        history_start = datetime.combine(required_days[0], datetime.min.time(), ny).isoformat()
        recent = datetime.combine(required_days[-20], datetime.min.time(), ny).isoformat()
        result['history_start'] = history_start
        result['liquidity_start'] = recent
        result['last_completed_stage'] = stage
        stage = 'liquidity-proxy'
        daily, result['preliminary_batches'] = _batches(run, roster, recent, end, day.isoformat(), scratch, stage)
        result['last_completed_stage'] = stage
        stage = 'prefilter'
        filtered = prefilter(roster, daily, calendar, as_of)
        outputs['prefilter'] = scratch.save('prefilter.json', filtered)
        result['last_completed_stage'] = stage
        stage = 'history'
        history, result['history_batches'] = _batches(run, filtered, history_start, end, day.isoformat(), scratch, stage, [benchmark])
        result['last_completed_stage'] = stage
        if history:
            stage = 'screen-input'
            bundle = prepare(filtered, history, calendar, as_of, benchmark=benchmark, validate=False)
            stage = 'screen'
            measured = screen(bundle)
            outputs['screen'] = scratch.save('screen.json', measured)
            result['last_completed_stage'] = stage
            result['coverage'] = measured['coverage']
            result['complete'] = bool(filtered['complete'] and measured['complete'] and news['complete'])
            result['price_screen_complete'] = measured['complete']
            stage = 'screen-input'
            try:
                outputs['screen_input'] = scratch.save('screen-input.json', bundle)
                result['comparison_input_available'] = True
                result['last_completed_stage'] = stage
            except ArtifactTooLarge:
                result['complete'] = False
                result['comparison_input_available'] = False
                result['assembly_limitation'] = ('The complete price screen was measured without dropping names, '
                    'but its duplicate assembled input exceeds the 128 MiB file boundary. '
                    'The original history batches, frozen universe, calendar and measured screen remain '
                    'in this manifest. Do not form a smaller comparison cohort to fit; record that comparison input as unavailable.')
        elif filtered['complete'] and not filtered['batches']:
            result['complete'] = news['complete']
            result['eligibility_empty'] = True
            result['coverage'] = filtered.get('coverage', {})
            result['coverage_basis'] = 'complete preliminary eligibility assessment; no full-history screen required'
            result['reason'] = ('No directory equities passed the declared price and daily-turnover proxy; '
                                'there were no full-history batches to request. This does not claim no '
                                'investment opportunities exist outside the checked eligibility rules.')
        else:
            result['reason'] = 'No usable full-history batch: preserve the complete declared roster and unresolved coverage; do not claim no opportunities.'
    except (ValueError, TypeError, KeyError, OSError, OverflowError, RuntimeError):
        result.update(complete=False, failed_stage=stage, error={
            'code': 'stage_failure',
            'message': 'Provider evidence, validation or scratch access failed at this stage; preserve the named scratch and earlier artifacts. No complete result was assumed.'})
    return _finish(scratch, result)


def main(argv=None):
    class SafeParser(argparse.ArgumentParser):
        def error(self, message):
            raise DataError('invalid_input', 'Invalid command arguments. Use --help for the selected command.')

    class SingleCredentialsFile(argparse.Action):
        def __call__(self, parser, namespace, value, option_string=None):
            if getattr(namespace, self.dest, None) is not None:
                raise DataError('invalid_input', 'Specify --credentials-file only once per command.')
            setattr(namespace, self.dest, value)

    parser = SafeParser(description=__doc__)
    parser.add_argument('--test', action='store_true')
    sub = parser.add_subparsers(dest='command', parser_class=SafeParser)
    collect = sub.add_parser('discover')
    collect.add_argument('--vault', required=True)
    collect.add_argument('--work-dir', required=True)
    collect.add_argument('--as-of', required=True)
    collect.add_argument('--news-since', required=True)
    collect.add_argument('--credentials-file', action=SingleCredentialsFile)
    collect.add_argument('--batch-size', type=int, default=100)
    collect.add_argument('--max-requests', type=int, default=250)
    collect.add_argument('--max-seconds', type=int, default=300)
    env = dict(os.environ)
    secrets = tuple(env.get(name, '') for name in CREDENTIAL_NAMES)
    try:
        args = parser.parse_args(argv)
        if args.test:
            return run_self_test()
        if args.command != 'discover':
            raise ValueError('Choose discover or --test.')
        if args.credentials_file:
            loaded = load_credentials(args.credentials_file)
            secrets += tuple(loaded.values())
            env = credential_environment(env, loaded)
        client = HttpClient(env, max_requests=args.max_requests, max_seconds=args.max_seconds,
                            redaction_values=secrets)
        result = discover(client, args.vault, args.work_dir, args.as_of, args.news_since, batch_size=args.batch_size)
        code = 0 if result['complete'] else 2
    except (ValueError, TypeError, KeyError, OSError, OverflowError, RuntimeError):
        result, code = {'complete': False, 'error': 'Acquisition input, provider evidence or scratch access failed; retain the owned scratch artifacts and inspect the last completed stage.'}, 2
    print(json.dumps(redact(result, env, extra_values=secrets), ensure_ascii=False, allow_nan=False))
    return code


def run_self_test():
    import unittest
    from types import SimpleNamespace
    from unittest.mock import Mock, patch

    class Tests(unittest.TestCase):
        def test_source_quota_stops_only_affected_provider(self):
            client = SimpleNamespace(env={}, requests=[])
            run = Acquisition(client)
            limited = Mock(side_effect=DataError('rate_limited', 'Stop.'))
            with patch(__name__ + '.handlers', return_value={'prices': limited, 'symbols': lambda c, a: {'complete': True}}):
                argv = ['prices', '--symbols', 'ABC', '--start', '2026-09-01T00:00:00Z', '--end', '2026-09-02T00:00:00Z']
                self.assertFalse(run.fetch(argv)['complete'])
                self.assertFalse(run.fetch(argv)['complete'])
                self.assertTrue(run.fetch(['symbols'])['complete'])
                self.assertEqual(limited.call_count, 1)

        def test_per_batch_provenance_and_secret_redaction(self):
            client = SimpleNamespace(env={'ALPACA_API_KEY': 'secret-fixture'}, requests=[])
            def retrieve(c, a):
                c.requests.append({'url': 'https://example.org/', 'status': 200})
                return {'complete': True, 'data': 'secret-fixture'}
            run = Acquisition(client)
            with patch(__name__ + '.handlers', return_value={'symbols': retrieve}):
                first, second = run.fetch(['symbols']), run.fetch(['symbols'])
            self.assertEqual(len(first['requests']), 1)
            self.assertEqual(len(second['requests']), 1)
            self.assertNotIn('secret-fixture', json.dumps(second))

        def test_private_scratch_refuses_vault_and_existing_file(self):
            with tempfile.TemporaryDirectory() as temp:
                base = Path(temp); vault = base / 'vault'; vault.mkdir()
                with self.assertRaises(ValueError):
                    Scratch(vault, vault)
                scratch = Scratch(base, vault)
                target = Path(scratch.save('result.json', {'first': True}))
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
                with self.assertRaises(FileExistsError):
                    scratch.save('result.json', {'first': False})
                self.assertTrue(json.loads(target.read_text(encoding='utf-8'))['first'])
                with self.assertRaises(ValueError):
                    scratch.save('../escape.json', {})

        def test_missing_directory_does_not_start_a_handpicked_screen(self):
            with tempfile.TemporaryDirectory() as temp:
                vault = Path(temp) / 'vault'; vault.mkdir()
                client = SimpleNamespace(env={}, requests=[])
                with patch.object(Acquisition, 'fetch', return_value={'complete': False, 'error': {'code': 'network_error'}}) as fetch:
                    result = discover(client, vault, temp, '2026-09-06T23:00:00-04:00', '2026-09-04T16:00:00-04:00')
                self.assertFalse(result['complete'])
                self.assertEqual(fetch.call_count, 1)

    outcome = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    failed = len(outcome.failures) + len(outcome.errors) + len(getattr(outcome, 'unexpectedSuccesses', ()))
    print('%d/%d self-test cases pass' % (outcome.testsRun - failed, outcome.testsRun))
    return 0 if outcome.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
