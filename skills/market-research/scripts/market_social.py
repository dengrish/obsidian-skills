#!/usr/bin/env python3
"""Validate a curated social roster and normalize saved ShadowAlpha MCP results.

Offline only: no network, credentials, trading, recommendations or file writes.
Use check --config PATH or normalize --config PATH --input PATH; --test runs
self-contained fixtures. External text is retained as data, never instructions.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys


class SocialError(ValueError):
    """Malformed local configuration or capture; fail without a fallback."""


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SocialError('JSON contains a duplicate object key.')
        result[key] = value
    return result


def _float(value):
    number = float(value)
    return number if math.isfinite(number) else None


def decode(raw):
    """Provider nonfinite numbers represent missing values, never zero."""
    try:
        return json.loads(raw, object_pairs_hook=_object,
                          parse_constant=lambda _value: None, parse_float=_float)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise SocialError('Input is not valid, unambiguous JSON.') from exc


def read_json(path, maximum):
    """Read a bounded regular file; directory aliases are allowed, leaf symlinks are not."""
    path = Path(os.path.abspath(os.path.expanduser(path)))
    descriptor = None
    try:
        # macOS returns /var/... scratch paths even though /var aliases /private/var.
        # Resolve only the parent, preserving the final component for O_NOFOLLOW.
        path = path.parent.resolve(strict=True) / path.name
        descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
        for component in path.parts[1:-1]:
            following = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
        following = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                            dir_fd=descriptor)
        os.close(descriptor)
        descriptor = following
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise SocialError('Input must be a bounded regular file.')
        with os.fdopen(descriptor, 'rb') as stream:
            descriptor = None
            raw = stream.read(maximum + 1)
        if len(raw) > maximum:
            raise SocialError('Input exceeds the file size limit.')
        return decode(raw), hashlib.sha256(raw).hexdigest()
    except (OSError, ValueError, RuntimeError) as exc:
        if isinstance(exc, SocialError):
            raise
        raise SocialError('Cannot safely read the input file; leaf symlinks are not allowed.') from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _keys(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise SocialError('An object has missing or unsupported fields.')


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise SocialError('A numeric setting is outside its allowed integer range.')


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise SocialError('Dates must use YYYY-MM-DD.')
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SocialError('Invalid calendar date.') from exc


def _time(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)', value):
        raise SocialError('Timestamps must include seconds and UTC (Z or +00:00).')
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise SocialError('Invalid UTC timestamp.') from exc


def _original_time(value):
    """Accept known provider timestamp forms, but never invent a timezone."""
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:[0-5]\d)', value):
        raise SocialError('Original timestamps must be timezone-aware provider timestamps.')
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise SocialError('Invalid original timestamp.') from exc


def _iso(value):
    return value.isoformat().replace('+00:00', 'Z')


def _handle(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,15}', value):
        raise SocialError('Roster handles must be bare X handles of 1–15 letters, digits or underscores.')
    return value.casefold()


def validate_config(config):
    _keys(config, ('market_research_sources', 'discovery_mode', 'shadowalpha'), ('reviewed_on',))
    if type(config['market_research_sources']) is not int or config['market_research_sources'] != 1 or config['discovery_mode'] != 'curated_social':
        raise SocialError('Unsupported source configuration version or discovery mode.')
    if 'reviewed_on' in config:
        _day(config['reviewed_on'])
    settings = config['shadowalpha']
    _keys(settings, ('roster', 'lookback_days', 'max_requests_per_run',
                     'max_prediction_pages_per_author', 'max_new_candidates'))
    for name, low, high in (('lookback_days', 1, 90), ('max_requests_per_run', 1, 100),
                            ('max_prediction_pages_per_author', 1, 10), ('max_new_candidates', 1, 50)):
        _integer(settings[name], low, high)
    roster = settings['roster']
    if not isinstance(roster, list) or not 1 <= len(roster) <= 50:
        raise SocialError('The roster must contain 1–50 accounts.')
    seen = set()
    for account in roster:
        _keys(account, ('handle', 'source_type', 'status', 'role', 'reason'))
        handle = _handle(account['handle'])
        if handle in seen:
            raise SocialError('Roster contains a duplicate handle (case-insensitive).')
        seen.add(handle)
        if account['source_type'] != 'x' or account['status'] not in ('pilot', 'context_only', 'paused', 'excluded'):
            raise SocialError('Unsupported roster source or status.')
        for field in ('role', 'reason'):
            if not isinstance(account[field], str) or not account[field].strip() or len(account[field]) > 1000:
                raise SocialError('Roster role and reason must be nonempty text, at most 1000 characters.')
    return config


def check(config, digest):
    validate_config(config)
    return {'market_social_check': 1, 'valid': True, 'config_sha256': digest,
            'discovery_mode': config['discovery_mode'],
            'discovery_roster': [item for item in config['shadowalpha']['roster'] if item['status'] == 'pilot'],
            'context_roster': [item for item in config['shadowalpha']['roster'] if item['status'] == 'context_only'],
            'max_new_candidates': config['shadowalpha']['max_new_candidates']}


TOOL_ARGS = {
    'search_posts': ('author', {'symbol', 'filter', 'limit'}),
    'search_predictions': ('analyst', {'symbol', 'direction', 'resolved', 'outcome',
                                      'date_from', 'date_to', 'sort_by', 'limit', 'offset'}),
    'get_analyst': ('handle', set()),
}


def _arguments(tool, arguments, roster):
    if tool not in TOOL_ARGS:
        raise SocialError('Unsupported capture tool.')
    author_key, optional = TOOL_ARGS[tool]
    _keys(arguments, (author_key,), optional)
    handle = _handle(arguments[author_key])
    if handle not in roster:
        raise SocialError('A captured query names an account outside the configured roster.')
    if 'limit' in arguments:
        _integer(arguments['limit'], 1, 50)
    if 'offset' in arguments:
        _integer(arguments['offset'], 0, 100000)
    for name in ('date_from', 'date_to'):
        if name in arguments:
            _day(arguments[name])
    choices = {'filter': ('all', 'predictions', 'trades', 'chatter'),
               'direction': ('bullish', 'bearish'), 'outcome': ('win', 'loss', 'neutral'),
               'sort_by': ('date_desc', 'date_asc', 'pl_desc', 'pl_asc')}
    for name, values in choices.items():
        if name in arguments and arguments[name] not in values:
            raise SocialError('Unsupported captured query argument value.')
    if 'resolved' in arguments and type(arguments['resolved']) is not bool:
        raise SocialError('The resolved argument must be boolean.')
    if 'symbol' in arguments and (not isinstance(arguments['symbol'], str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9.-]{0,14}', arguments['symbol'])):
        raise SocialError('Invalid captured symbol argument.')
    if arguments.get('date_from', '') > arguments.get('date_to', '9999-12-31'):
        raise SocialError('Captured date range is reversed.')
    return handle


def _identifier(value):
    return str(value) if type(value) in (str, int) and str(value).strip() else None


def _row_author(row, tool):
    value = row.get('author') if tool == 'search_posts' else row.get('channel_handle')
    return value.get('handle') if isinstance(value, dict) else value


def _claim(row, tool):
    """Compare the claim itself; live scores, prices and author profiles can change."""
    raw_time = row.get('created_at' if tool == 'search_posts' else 'post_timestamp')
    try:
        original = _iso(_original_time(raw_time))
    except SocialError:
        original = raw_time
    author = _row_author(row, tool)
    result = {'source_type': row.get('source_type'), 'source_id': _identifier(row.get('source_id')),
              'author': author.casefold() if isinstance(author, str) else author,
              'original_timestamp': original,
              'text': row.get('body' if tool == 'search_posts' else 'raw_quote')}
    if tool == 'search_predictions':
        result.update({key: row.get(key) for key in ('symbol', 'direction', 'target_price', 'target_date', 'entry_price')})
    return result


def normalize(config, capture, digest):
    validate_config(config)
    _keys(capture, ('market_social_capture', 'as_of', 'captures'))
    if type(capture['market_social_capture']) is not int or capture['market_social_capture'] != 1:
        raise SocialError('Unsupported capture version.')
    cutoff = _time(capture['as_of'])
    settings = config['shadowalpha']
    try:
        start = cutoff - timedelta(days=settings['lookback_days'])
    except OverflowError as exc:
        raise SocialError('The lookback window precedes the supported calendar.') from exc
    roster = {item['handle'].casefold(): item for item in settings['roster']}
    captures = capture['captures']
    if not isinstance(captures, list) or len(captures) > settings['max_requests_per_run']:
        raise SocialError('Capture requests exceed the configured per-run budget.')
    counts, pages = Counter(), Counter()
    records, profiles, capture_coverage = {}, [], []
    for index, item in enumerate(captures):
        _keys(item, ('tool', 'arguments', 'retrieved_at', 'data'))
        tool, arguments = item['tool'], item['arguments']
        if not isinstance(tool, str):
            raise SocialError('Invalid tool name.')
        author = _arguments(tool, arguments, roster)
        retrieved = _time(item['retrieved_at'])
        data = item['data']
        if not isinstance(data, dict):
            raise SocialError('Capture data must be a decoded tool response object.')
        provenance = {'capture_index': index, 'tool': tool, 'arguments': arguments,
                      'retrieved_at': item['retrieved_at'],
                      'availability': 'retrieved_after_cutoff' if retrieved > cutoff else 'captured_by_cutoff',
                      'provider_fields_are_unverified': True}
        limitations = []
        if retrieved > cutoff:
            limitations.append('later_snapshot_not_contemporaneous_evidence')
        if tool == 'get_analyst':
            row = data.get('analyst')
            if not isinstance(row, dict):
                raise SocialError('Analyst capture is missing its analyst object.')
            actual = row.get('channel_handle')
            mismatch = not isinstance(actual, str) or actual.casefold() != author or row.get('source_type') != 'x'
            if mismatch:
                limitations.append('author_or_source_mismatch')
            if not row.get('active') or not row.get('total_predictions'):
                limitations.append('coverage_not_demonstrated')
            profiles.append({'configured_handle': roster[author]['handle'], 'raw': row,
                             'provenance': provenance, 'limitations': limitations[:]})
            rows = []
        else:
            key = 'posts' if tool == 'search_posts' else 'predictions'
            rows = data.get(key)
            if not isinstance(rows, list) or len(rows) > 50:
                raise SocialError('Captured feed must contain a list of at most 50 rows.')
            limit = arguments.get('limit', 50)
            if len(rows) > limit:
                raise SocialError('Feed contains more rows than its requested limit.')
            if len(rows) == limit:
                limitations.append('full_page_may_have_more_results')
            if data.get('next_cursor'):
                limitations.append('next_cursor_not_consumable_by_search_posts' if tool == 'search_posts' else 'next_cursor_present')
            if tool == 'search_predictions':
                pages[author] += 1
                if pages[author] > settings['max_prediction_pages_per_author']:
                    raise SocialError('Prediction pages exceed the configured per-author budget.')
                limitations.append('offset_pages_can_overlap_or_omit_tied_rows')
        capture_coverage.append({'capture_index': index, 'tool': tool, 'configured_handle': roster[author]['handle'],
                                 'raw_rows': len(rows), 'coverage': 'sampled', 'limitations': limitations[:]})
        counts[tool] += len(rows)
        for row_index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise SocialError('Captured feed contains a non-object row.')
            actual = _row_author(row, tool)
            source = row.get('source_type')
            raw_id = row.get('id')
            source_id = _identifier(row.get('source_id'))
            own_id = _identifier(raw_id)
            kind = 'post' if tool == 'search_posts' else 'prediction'
            identity = (source_id or own_id) if kind == 'post' else own_id
            key = ((kind, str(source), identity) if kind == 'post' else (kind, identity)) if identity else ('unidentified', index, row_index)
            excluded = []
            row_limits = []
            if not isinstance(actual, str) or actual.casefold() != author or source != 'x':
                excluded.append('author_or_source_mismatch')
            status = roster[author]['status']
            if status != 'pilot':
                excluded.append('roster_' + status)
            if not identity:
                excluded.append('missing_identity')
            raw_time = row.get('created_at' if kind == 'post' else 'post_timestamp')
            try:
                original = _original_time(raw_time)
            except SocialError:
                original = None
                excluded.append('missing_or_invalid_original_timestamp')
            if original is not None:
                if original > cutoff:
                    excluded.append('original_timestamp_after_cutoff')
                elif original < start:
                    excluded.append('outside_lookback')
                if original > retrieved:
                    excluded.append('original_timestamp_after_retrieval')
            text = row.get('body' if kind == 'post' else 'raw_quote')
            if not isinstance(text, str) or not text.strip():
                excluded.append('missing_original_text')
            elif len(text) >= 4000 or text.rstrip().endswith(('...', '…')):
                row_limits.append('possibly_truncated_original_text')
            if retrieved > cutoff:
                row_limits.append('original_text_requires_cutoff_verification')
            record = {'kind': kind, 'id': raw_id, 'source_type': source, 'source_id': row.get('source_id'),
                      'author': actual, 'configured_handle': roster[author]['handle'], 'roster_status': status,
                      'original_timestamp': raw_time, 'symbol': row.get('symbol') if kind == 'prediction' else None,
                      'original_timestamp_utc': _iso(original) if original is not None else None,
                      'direction': row.get('direction') if kind == 'prediction' else None,
                      'text': text, 'raw': row, 'provenance': [provenance], 'limitations': row_limits,
                      'exclusion_reasons': excluded, 'eligible_for_discovery': not excluded}
            if key not in records:
                records[key] = record
            else:
                counts['duplicate_rows'] += 1
                previous = records[key]
                previous['provenance'].append(provenance)
                previous['limitations'] = sorted(set(previous['limitations'] + row_limits))
                previous['exclusion_reasons'] = sorted(set(previous['exclusion_reasons'] + excluded))
                if previous['raw'] != row:
                    if _claim(previous['raw'], tool) != _claim(row, tool):
                        counts['conflicting_duplicate_rows'] += 1
                        previous.setdefault('conflicting_variants', []).append({'raw': row, 'provenance': provenance})
                        previous['exclusion_reasons'] = sorted(set(previous['exclusion_reasons'] + ['conflicting_duplicate_rows']))
                    else:
                        counts['changed_snapshot_rows'] += 1
                        previous.setdefault('snapshot_variants', []).append({'raw': row, 'provenance': provenance})
                        previous['limitations'] = sorted(set(previous['limitations'] + ['provider_snapshot_fields_changed']))
                previous['eligible_for_discovery'] = not previous['exclusion_reasons']
    all_records = list(records.values())
    source_posts = {(str(item['source_type']), _identifier(item['source_id'])) for item in all_records
                    if _identifier(item['source_id']) is not None}
    source_posts.update((str(item['source_type']), 'fallback:' + str(item['id'])) for item in all_records
                        if item['kind'] == 'post' and _identifier(item['source_id']) is None and _identifier(item['id']) is not None)
    exclusion_counts = Counter(reason for item in all_records for reason in item['exclusion_reasons'])
    by_author = []
    for account in settings['roster']:
        author_captures = [item for item in capture_coverage if item['configured_handle'] == account['handle']]
        author_records = [item for item in all_records if item['configured_handle'] == account['handle']]
        feed_captures = [item for item in author_captures if item['tool'] != 'get_analyst']
        by_author.append({'handle': account['handle'], 'status': account['status'],
                          'coverage': 'sampled' if feed_captures else ('profile_only' if author_captures else 'not_queried'),
                          'tools': dict(Counter(item['tool'] for item in author_captures)),
                          'captures': len(author_captures), 'unique_rows': len(author_records),
                          'eligible_rows': sum(item['eligible_for_discovery'] for item in author_records)})
    return {'market_social_review': 1, 'config_sha256': digest, 'as_of': _iso(cutoff),
            'window_start': _iso(start), 'coverage': 'sampled', 'complete_history': False,
            'max_new_candidates': settings['max_new_candidates'],
            'warnings': ['This is an unranked nomination queue, not buying recommendations.',
                         'Original text and company identity require verification; provider classifications and scores are not facts.',
                         'Later retrieval does not make current metrics or classifications available at the cutoff.',
                         'Rows, posts, predictions and distinct symbols are different counts; no symbol is inferred from a query or nested prediction.'],
            'counts': {'captures': len(captures), 'raw_posts': counts['search_posts'],
                       'raw_predictions': counts['search_predictions'], 'duplicate_rows': counts['duplicate_rows'],
                       'conflicting_duplicate_rows': counts['conflicting_duplicate_rows'],
                       'changed_snapshot_rows': counts['changed_snapshot_rows'],
                       'unique_posts': len(source_posts),
                       'unique_post_records': sum(item['kind'] == 'post' for item in all_records),
                       'unique_predictions': sum(item['kind'] == 'prediction' for item in all_records),
                       'eligible_rows': sum(item['eligible_for_discovery'] for item in all_records),
                       'exclusions': dict(sorted(exclusion_counts.items()))},
            'authors': by_author, 'captures': capture_coverage, 'profiles': profiles,
            'review_queue': [item for item in all_records if item['eligible_for_discovery']],
            'context_and_excluded': [item for item in all_records if not item['eligible_for_discovery']]}


def run_self_test():
    import copy
    import tempfile
    import unittest

    class Tests(unittest.TestCase):
        def config(self):
            return {'market_research_sources': 1, 'discovery_mode': 'curated_social',
                    'shadowalpha': {'roster': [{'handle': 'Example', 'source_type': 'x', 'status': 'pilot',
                                              'role': 'Industry', 'reason': 'Provisional source'}],
                                    'lookback_days': 14, 'max_requests_per_run': 24,
                                    'max_prediction_pages_per_author': 2, 'max_new_candidates': 12}}

        def prediction(self, **changes):
            row = {'id': 1, 'source_type': 'x', 'source_id': 'post1', 'channel_handle': 'Example',
                   'post_timestamp': '2026-09-06T12:00:00Z', 'symbol': 'ABC', 'direction': 'bullish',
                   'raw_quote': 'ABC capacity is growing.', 'target_price': None}
            return dict(row, **changes)

        def capture(self, rows=None, **changes):
            value = {'market_social_capture': 1, 'as_of': '2026-09-07T12:00:00Z',
                     'captures': [{'tool': 'search_predictions', 'arguments': {'analyst': 'Example', 'limit': 50},
                                   'retrieved_at': '2026-09-07T12:01:00Z',
                                   'data': {'predictions': rows if rows is not None else [self.prediction()]}}]}
            return dict(value, **changes)

        def test_config_rejects_unknown_duplicates_bounds_and_missing_fields(self):
            variants = []
            cfg = self.config(); cfg['old_setting'] = True; variants.append(cfg)
            cfg = self.config(); cfg['shadowalpha']['roster'].append(dict(cfg['shadowalpha']['roster'][0], handle='example')); variants.append(cfg)
            cfg = self.config(); cfg['shadowalpha']['lookback_days'] = True; variants.append(cfg)
            cfg = self.config(); cfg['shadowalpha']['max_requests_per_run'] = 101; variants.append(cfg)
            cfg = self.config(); cfg['shadowalpha']['roster'][0]['handle'] = '@Example'; variants.append(cfg)
            cfg = self.config(); del cfg['shadowalpha']['max_new_candidates']; variants.append(cfg)
            for cfg in variants:
                with self.subTest(cfg=cfg), self.assertRaises(SocialError):
                    validate_config(cfg)
            self.assertTrue(check(self.config(), 'digest')['valid'])

        def test_multistock_predictions_survive_shared_post_and_pages_deduplicate(self):
            first, second = self.prediction(), self.prediction(id=2, symbol='XYZ', raw_quote='XYZ is growing.')
            cap = self.capture([first, second])
            cap['captures'].append(copy.deepcopy(cap['captures'][0]))
            cap['captures'][1]['arguments']['offset'] = 50
            result = normalize(self.config(), cap, 'digest')
            self.assertEqual(result['counts']['raw_predictions'], 4)
            self.assertEqual(result['counts']['unique_predictions'], 2)
            self.assertEqual(result['counts']['unique_posts'], 1)
            self.assertEqual(result['counts']['unique_post_records'], 0)
            self.assertEqual(result['counts']['duplicate_rows'], 2)
            self.assertEqual(len(result['review_queue']), 2)

        def test_invalid_original_times_never_become_now(self):
            rows = [self.prediction(id=i, post_timestamp=value) for i, value in enumerate((None, '', 'bad', '2026-09-08T00:00:00Z', '2026-08-01T00:00:00Z'))]
            result = normalize(self.config(), self.capture(rows), 'digest')
            self.assertEqual(result['review_queue'], [])
            self.assertEqual(result['counts']['exclusions']['missing_or_invalid_original_timestamp'], 3)
            self.assertEqual(result['counts']['exclusions']['original_timestamp_after_cutoff'], 1)
            self.assertEqual(result['counts']['exclusions']['outside_lookback'], 1)

        def test_later_retrieval_can_nominate_dated_text_without_backdating_metrics(self):
            result = normalize(self.config(), self.capture(), 'digest')
            row = result['review_queue'][0]
            self.assertEqual(row['provenance'][0]['availability'], 'retrieved_after_cutoff')
            self.assertIn('original_text_requires_cutoff_verification', row['limitations'])
            self.assertTrue(row['provenance'][0]['provider_fields_are_unverified'])

        def test_provider_timestamp_forms_and_offsets_preserve_raw_values(self):
            originals = ('2026-09-06 12:00:00+00:00', '2026-09-06T08:00:00-04:00',
                         '2026-09-06T17:30:00+05:30')
            rows = [self.prediction(id=i, post_timestamp=value) for i, value in enumerate(originals)]
            rows.append(self.prediction(id=4, post_timestamp='2026-09-06 12:00:00'))
            result = normalize(self.config(), self.capture(rows), 'digest')
            self.assertEqual(len(result['review_queue']), 3)
            self.assertEqual([row['original_timestamp'] for row in result['review_queue']], list(originals))
            self.assertTrue(all(row['original_timestamp_utc'] == '2026-09-06T12:00:00Z' for row in result['review_queue']))
            self.assertEqual(result['counts']['exclusions']['missing_or_invalid_original_timestamp'], 1)
            for invalid in ('2026-09-07 12:00:00+00:00', '2026-09-07T08:00:00-04:00'):
                with self.subTest(invalid=invalid), self.assertRaises(SocialError):
                    normalize(self.config(), self.capture(as_of=invalid), 'digest')

        def test_nonfinite_and_duplicate_json_keys(self):
            result = decode('{"a":NaN,"b":Infinity,"c":-Infinity,"d":1e999,"e":null}')
            self.assertEqual(set(result.values()), {None})
            cap = self.capture(); cap['captures'][0]['data']['predictions'][0]['target_price'] = float('nan')
            decoded = decode(json.dumps(cap))
            result = normalize(self.config(), decoded, 'digest')
            self.assertIsNone(result['review_queue'][0]['raw']['target_price'])
            with self.assertRaises(SocialError):
                decode('{"a":1,"a":2}')

        def test_conflicts_remove_record_from_discovery(self):
            cap = self.capture([self.prediction(), self.prediction(direction='bearish')])
            result = normalize(self.config(), cap, 'digest')
            self.assertEqual(result['review_queue'], [])
            self.assertEqual(result['counts']['conflicting_duplicate_rows'], 1)
            self.assertEqual(len(result['context_and_excluded'][0]['conflicting_variants']), 1)

        def test_live_metric_changes_preserve_unchanged_claim_and_both_snapshots(self):
            first = self.prediction(current_price=30, pnl_pct=5)
            second = self.prediction(current_price=31, pnl_pct=6)
            result = normalize(self.config(), self.capture([first, second]), 'digest')
            self.assertEqual(len(result['review_queue']), 1)
            self.assertEqual(result['counts']['conflicting_duplicate_rows'], 0)
            self.assertEqual(result['counts']['changed_snapshot_rows'], 1)
            self.assertEqual(result['review_queue'][0]['raw']['current_price'], 30)
            self.assertEqual(result['review_queue'][0]['snapshot_variants'][0]['raw']['current_price'], 31)

        def test_author_and_source_mismatches_cannot_nominate(self):
            cap = self.capture([self.prediction(channel_handle='Other'), self.prediction(id=2, source_type='youtube')])
            result = normalize(self.config(), cap, 'digest')
            self.assertEqual(result['counts']['eligible_rows'], 0)
            self.assertEqual(result['counts']['exclusions']['author_or_source_mismatch'], 2)
            cap['captures'][0]['arguments']['analyst'] = 'Other'
            with self.assertRaises(SocialError):
                normalize(self.config(), cap, 'digest')

        def test_context_and_paused_accounts_are_not_discovery(self):
            for status in ('context_only', 'paused', 'excluded'):
                cfg = self.config(); cfg['shadowalpha']['roster'][0]['status'] = status
                result = normalize(cfg, self.capture(), 'digest')
                self.assertEqual(result['review_queue'], [])
                self.assertEqual(result['context_and_excluded'][0]['roster_status'], status)

        def test_posts_include_chatter_without_inferring_nested_symbol(self):
            cap = self.capture()
            post = {'id': 9, 'author': {'handle': 'Example'}, 'source_type': 'x', 'source_id': 'post1',
                    'created_at': '2026-09-06T12:00:00Z', 'body': 'Several companies are expanding.',
                    'post_type': 'chatter', 'referenced_symbols': ['ABC', 'XYZ'], 'prediction': {'symbol': 'ABC'}}
            cap['captures'] = [{'tool': 'search_posts', 'arguments': {'author': 'Example', 'symbol': 'XYZ', 'filter': 'all', 'limit': 2},
                                'retrieved_at': '2026-09-07T12:01:00Z', 'data': {'posts': [post, dict(post)], 'next_cursor': 'cursor'}}]
            result = normalize(self.config(), cap, 'digest')
            self.assertEqual(result['counts']['unique_posts'], 1)
            self.assertIsNone(result['review_queue'][0]['symbol'])
            self.assertIn('full_page_may_have_more_results', result['captures'][0]['limitations'])
            self.assertIn('next_cursor_not_consumable_by_search_posts', result['captures'][0]['limitations'])

        def test_truncated_text_and_missing_identity(self):
            rows = [self.prediction(raw_quote='x' * 4001), self.prediction(id=2, raw_quote='Excerpt…'), self.prediction(id=None)]
            result = normalize(self.config(), self.capture(rows), 'digest')
            self.assertEqual(len(result['review_queue']), 2)
            self.assertTrue(all('possibly_truncated_original_text' in row['limitations'] for row in result['review_queue']))
            self.assertEqual(result['counts']['exclusions']['missing_identity'], 1)

        def test_request_and_page_budgets_fail_closed(self):
            cap = self.capture(); cap['captures'] *= 3
            with self.assertRaises(SocialError):
                normalize(self.config(), cap, 'digest')
            cfg = self.config(); cfg['shadowalpha']['max_requests_per_run'] = 1
            cap['captures'] = cap['captures'][:2]
            with self.assertRaises(SocialError):
                normalize(cfg, cap, 'digest')
            cap = self.capture(); cap['captures'][0]['arguments']['cursor'] = 'unsupported'
            with self.assertRaises(SocialError):
                normalize(self.config(), cap, 'digest')

        def test_analyst_coverage_is_metadata_and_never_a_recommendation(self):
            cap = self.capture(captures=[{'tool': 'get_analyst', 'arguments': {'handle': 'Example'},
                                         'retrieved_at': '2026-09-07T12:01:00Z',
                                         'data': {'analyst': {'channel_handle': 'Example', 'source_type': None,
                                                              'active': None, 'total_predictions': 0}}}])
            result = normalize(self.config(), cap, 'digest')
            self.assertEqual(result['review_queue'], [])
            self.assertIn('coverage_not_demonstrated', result['profiles'][0]['limitations'])
            self.assertEqual(result['authors'][0]['coverage'], 'profile_only')
            self.assertFalse(result['complete_history'])

        def test_bounded_regular_files_and_symlink_paths(self):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                path = root / 'input.json'; path.write_text('{"a":1}', encoding='utf-8')
                value, digest = read_json(str(path), 100)
                self.assertEqual(value, {'a': 1})
                self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())
                with self.assertRaises(SocialError): read_json(str(path), 3)
                link = root / 'link.json'; link.symlink_to(path)
                with self.assertRaises(SocialError): read_json(str(link), 100)
                directory_link = root / 'alias'; directory_link.symlink_to(root, target_is_directory=True)
                self.assertEqual(read_json(str(directory_link / 'input.json'), 100)[0], value)
                self.assertEqual(read_json(str(Path(temporary) / 'input.json'), 100)[0], value)
                with self.assertRaises(SocialError): read_json(str(root), 100)

    result = unittest.TextTestRunner(stream=sys.stderr).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    print('%d/%d self-test cases pass' % (result.testsRun - len(result.errors) - len(result.failures), result.testsRun))
    return result.wasSuccessful()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', action='store_true', help='Run offline self-tests.')
    commands = parser.add_subparsers(dest='command')
    for name in ('check', 'normalize'):
        sub = commands.add_parser(name)
        sub.add_argument('--config', required=True, help='Vault-local market-research-sources.json.')
        if name == 'normalize':
            sub.add_argument('--input', required=True, help='Saved market_social_capture JSON envelope.')
    args = parser.parse_args(argv)
    if args.test:
        return 0 if run_self_test() else 1
    if args.command is None:
        parser.print_help()
        return 0
    try:
        config, digest = read_json(args.config, 65536)
        if args.command == 'check':
            result = check(config, digest)
        else:
            capture, capture_digest = read_json(args.input, 8 * 1024 * 1024)
            result = normalize(config, capture, digest)
            result['capture_sha256'] = capture_digest
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except SocialError as exc:
        print(json.dumps({'error': 'invalid_social_input', 'message': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
