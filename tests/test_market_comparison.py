#!/usr/bin/env python3
"""Hand-checked comparison cohorts in temporary vaults; no accounts or network."""
import copy
from datetime import datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/market-research/scripts'))
import market_comparison as comparison
import market_notes

NY = ZoneInfo('America/New_York')


def iso(value):
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def calendar_fixture(start, end):
    day, last = comparison.parse_date(start), comparison.parse_date(end)
    rows = []
    while day <= last:
        if day.weekday() < 5:
            rows.append({'date': day.isoformat(), 'open_at': iso(datetime.combine(day, time(9, 30), NY)),
                         'close_at': iso(datetime.combine(day, time(16), NY))})
        day += timedelta(days=1)
    return {'market_data': 1, 'provider': 'alpaca', 'resource': 'calendar', 'operation': 'sessions',
            'complete': True, 'query': {'start': start, 'end': end},
            'source': {'url': 'https://paper-api.alpaca.markets/v2/calendar'}, 'data': {'sessions': rows},
            'requests': [], 'warnings': []}


def bar(day, opened, closed=None):
    day = comparison.parse_date(day)
    closed = opened if closed is None else closed
    beginning = iso(datetime.combine(day, time.min, NY))
    return {'t': beginning, 'interval_start': beginning,
            'interval_end': iso(datetime.combine(day + timedelta(days=1), time.min, NY)),
            'new_york_date': day.isoformat(), 'o': opened, 'c': closed,
            'h': max(opened, closed), 'l': min(opened, closed), 'vw': closed, 'v': 1000000}


def prices_fixture(bars, start, end, mapping='2024-05-01'):
    return {'market_data': 1, 'provider': 'alpaca', 'resource': 'bars', 'operation': 'prices', 'complete': True,
            'query': {'symbols': ','.join(bars), 'start': start, 'end': end, 'requested_end': end,
                      'asof': mapping, 'timeframe': '1Day', 'feed': 'sip', 'adjustment': 'split', 'currency': 'USD'},
            'source': {'feed': 'sip', 'url': 'https://data.alpaca.markets/v2/stocks/bars'},
            'data': {'requested_symbols': list(bars), 'bars': bars}, 'warnings': [], 'requests': []}


def formation_fixture():
    sessions = calendar_fixture('2023-01-01', '2024-05-01')
    bars = {}
    for symbol, rate in (('AAA', 0.003), ('BBB', 0.002), ('CCC', 0.001), ('DDD', 0.001), ('SPY', 0.0005)):
        bars[symbol] = [bar(row['date'], 100 * (1 + rate) ** i)
                        for i, row in enumerate(sessions['data']['sessions']) if row['date'] < '2024-05-01']
    return {'market_screen_input': 1, 'as_of': '2024-05-01T11:30:00-04:00', 'benchmark': 'SPY',
            'universe': {'name': 'Four synthetic stocks', 'source': 'https://example.invalid/universe',
                         'membership_date': '2024-05-01', 'instruments': [
                             {'symbol': symbol, 'exchange': 'NASDAQ', 'security_type': 'common_stock', 'currency': 'USD'}
                             for symbol in ('DDD', 'CCC', 'BBB', 'AAA')]},
            'prices': [prices_fixture(bars, '2023-01-01T05:00:00Z', '2024-05-01T03:59:59Z')],
            'sessions': sessions, 'rules': {'limit': 1, 'min_price': 1000000}}


def observation_fixture():
    observations = {'AAA': (100, 130), 'BBB': (200, 220), 'CCC': (50, 45), 'SPY': (100, 105)}
    bars = {symbol: [bar('2024-05-02', first), bar('2024-08-02', last)]
            for symbol, (first, last) in observations.items()}
    return {'market_comparison_input': 1, 'as_of': '2024-08-03T11:30:00-04:00',
            'sessions': calendar_fixture('2024-05-01', '2024-08-03'),
            'prices': [prices_fixture(bars, '2024-05-01T04:00:00Z', '2024-08-03T03:59:59Z')],
            'corporate_actions': {symbol: {'status': 'verified', 'source': 'https://example.invalid/actions',
                                          'note': 'Synthetic unchanged identity and no actions.'} for symbol in bars}}


def note(day, content='', as_of=None):
    cutoff = as_of or day + 'T11:30:00-04:00'
    generated = comparison.parse_time(cutoff) + timedelta(minutes=1)
    return f'''---
market_research: 1
date: {day}
as_of: "{cutoff}"
generated_at: "{generated.isoformat()}"
session: unknown
coverage: limited
---

# Market research — {day}

## Decision brief

### Buying opportunities

Synthetic fixture, no recommendation.

### Next checks

Synthetic check.

## Research record

### Screening and sources

Synthetic evidence only.

### Candidate assessments

No discretionary candidates.

### Thesis updates

No active theses.

### Outcome review

Synthetic mechanical comparison.

{content}
'''


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.bundle = formation_fixture()
        self.card = comparison.form(self.bundle)
        self.temp = tempfile.TemporaryDirectory(prefix='.market-comparison-test-')
        self.addCleanup(self.temp.cleanup)
        self.vault = Path(self.temp.name).resolve()
        self.folder = self.vault / 'Investments'
        self.folder.mkdir()

    def save_formation(self, card=None):
        card = card or self.card
        snippets = comparison.formation_markdown(card, '2024-05-01-market-research')
        path = self.folder / '2024-05-01-market-research.md'
        path.write_text(note('2024-05-01', snippets['journal_markdown'] + '\n' + snippets['detail_markdown']), encoding='utf-8')
        return path

    def draft_observation(self, observation, replaces='-'):
        snippets = comparison.observation_markdown(observation, '2024-08-03-market-research', replaces)
        draft = self.vault / 'draft.md'
        draft.write_text(note('2024-08-03', snippets['journal_markdown'] + '\n' + snippets['detail_markdown']), encoding='utf-8')
        return draft

    def test_fixed_selection_ignores_discretionary_rules_and_breaks_ties(self):
        original = copy.deepcopy(self.bundle)
        self.assertEqual([row['symbol'] for row in self.card['members']], ['AAA', 'BBB', 'CCC'])
        self.assertEqual(len(self.card['rows']), 4)
        self.assertEqual(self.bundle, original)
        self.bundle['universe']['instruments'].reverse()
        self.assertEqual(comparison.form(self.bundle)['members'], self.card['members'])
        changed = copy.deepcopy(self.card)
        changed['rows'][2][-1], changed['rows'][3][-1] = 'not-selected', 'selected'
        with self.assertRaisesRegex(ValueError, 'fixed ranking'):
            comparison.validate_formation(changed)

    def test_actual_selected_count_has_equal_weights_without_cash_slots(self):
        self.bundle['universe']['instruments'] = self.bundle['universe']['instruments'][-1:]
        cohort = comparison.form(self.bundle)
        result = comparison.evaluate(cohort, '2024-05-01T11:31:00-04:00', observation_fixture(), '3m')
        self.assertEqual(result['member_count'], 1)
        self.assertAlmostEqual(result['return_value'], 0.3)

    def test_empty_and_incomplete_formations_never_create_cash_or_partial_winners(self):
        missing = copy.deepcopy(self.bundle)
        missing['prices'][0]['complete'] = False
        result = comparison.form(missing)
        self.assertEqual(result['metadata']['State'], 'unavailable')
        self.assertEqual(result['members'], [])
        for instrument in self.bundle['universe']['instruments']:
            instrument['security_type'] = 'etf'
        empty = comparison.form(self.bundle)
        self.assertEqual(empty['metadata']['State'], 'empty')
        self.assertEqual(empty['members'], [])
        for card in (empty, result):
            with self.assertRaisesRegex(ValueError, 'only formed'):
                comparison.evaluate(card, '2024-05-01T11:31:00-04:00', observation_fixture(), '3m')

    def test_future_membership_and_mapping_are_rejected(self):
        for mutate in ('membership', 'mapping'):
            bundle = copy.deepcopy(self.bundle)
            if mutate == 'membership':
                bundle['universe']['membership_date'] = '2024-05-02'
            else:
                bundle['prices'][0]['query']['asof'] = '2024-05-02'
            with self.subTest(mutate=mutate), self.assertRaisesRegex(ValueError, 'future'):
                comparison.form(bundle)

    def test_visible_markdown_round_trip_preserves_frozen_selection(self):
        self.bundle['universe']['name'] = 'Synthetic A&B | cohort'
        self.card = comparison.form(self.bundle)
        rendered = comparison.formation_markdown(self.card, '2024-05-01-market-research')
        parsed = comparison.read_card(rendered['detail_markdown'], comparison.heading_for(self.card['metadata']['Cohort']))
        self.assertEqual(parsed, self.card)
        path = self.save_formation()
        market_notes.lint_bytes(path.read_bytes())
        result = market_notes.outcomes(self.vault, now=comparison.parse_time('2024-05-01T11:32:00-04:00'))
        self.assertTrue(result['complete'], result['findings'])
        self.assertEqual(result['recommendations'], [])
        self.assertFalse(result['comparison_formation_due'])

    def test_known_returns_use_fixed_first_open_and_matching_session_close(self):
        result = comparison.evaluate(self.card, '2024-05-01T11:31:00-04:00', observation_fixture(), '3m')
        self.assertEqual(result['state'], 'observed')
        self.assertAlmostEqual(result['return_value'], 0.1)
        self.assertAlmostEqual(result['benchmark_return'], 0.05)
        self.assertEqual(comparison.parse_time(result['baseline_at']).astimezone(NY).date().isoformat(), '2024-05-02')
        self.assertEqual(comparison.parse_time(result['observed_at']).astimezone(NY).date().isoformat(), '2024-08-02')
        original = self.save_formation()
        saved = original.read_bytes()
        draft = self.draft_observation(result)
        planned = market_notes.outcomes(self.vault, draft, comparison.parse_time('2024-08-03T11:32:00-04:00'))
        self.assertTrue(planned['complete'], planned['findings'])
        checkpoint = planned['comparison_checkpoints'][0]
        self.assertEqual(checkpoint['state'], 'observed')
        self.assertEqual(checkpoint['member_count'], 3)
        self.assertEqual(original.read_bytes(), saved)

    def test_missing_delisted_member_or_actions_prevents_complete_basket_return(self):
        for missing in ('bar', 'actions', 'benchmark', 'partial'):
            bundle = observation_fixture()
            if missing == 'bar':
                bundle['prices'][0]['data']['bars']['CCC'] = []
            elif missing == 'actions':
                del bundle['corporate_actions']['CCC']
            elif missing == 'benchmark':
                bundle['prices'][0]['data']['bars']['SPY'] = []
            else:
                bundle['prices'][0]['complete'] = False
            with self.subTest(missing=missing):
                result = comparison.evaluate(self.card, '2024-05-01T11:31:00-04:00', bundle, '3m')
                self.assertEqual(result['state'], 'unavailable')
                self.assertIsNone(result['return_value'])
                self.assertIsNone(result['benchmark_return'])
                self.assertEqual([row[0] for row in result['rows']], ['AAA', 'BBB', 'CCC', 'SPY'])

    def test_future_close_late_publication_and_changed_identity_are_rejected(self):
        bundle = observation_fixture()
        bundle['as_of'] = '2024-08-02T11:30:00-04:00'
        result = comparison.evaluate(self.card, '2024-05-01T11:31:00-04:00', bundle, '3m')
        self.assertEqual(result['state'], 'pending')
        with self.assertRaisesRegex(ValueError, 'precedes known publication'):
            comparison.evaluate(self.card, '2024-05-02T10:00:00-04:00', observation_fixture(), '3m')
        bundle = observation_fixture()
        bundle['prices'][0]['query']['asof'] = '2024-08-03'
        with self.assertRaisesRegex(ValueError, 'symbol-mapping'):
            comparison.evaluate(self.card, '2024-05-01T11:31:00-04:00', bundle, '3m')

    def test_holidays_and_month_end_are_calendar_driven(self):
        bundle = observation_fixture()
        bundle['sessions']['data']['sessions'] = [row for row in bundle['sessions']['data']['sessions']
                                                   if row['date'] != '2024-05-02']
        for rows in bundle['prices'][0]['data']['bars'].values():
            rows[0] = bar('2024-05-03', rows[0]['o'])
        result = comparison.evaluate(self.card, '2024-05-01T11:31:00-04:00', bundle, '3m')
        self.assertEqual(result['state'], 'pending')  # August 3 is not a synthetic session.
        self.assertEqual(comparison.month_target(comparison.parse_date('2024-01-31'), 1).isoformat(), '2024-02-29')

    def test_frozen_month_cannot_be_replaced_and_missed_month_cannot_pick_late_winners(self):
        self.save_formation()
        late = self.vault / 'draft.md'
        mutated = copy.deepcopy(self.card)
        mutated['metadata']['As of'] = '2024-05-02T11:30:00-04:00'
        mutated['metadata']['Reference session'] = '2024-05-01'
        sources = json.loads(mutated['metadata']['Sources'])
        sources[-1]['query']['end'] = '2024-05-02'
        sources[0]['query']['end'] = sources[0]['query']['requested_end'] = '2024-05-02T03:59:59Z'
        mutated['metadata']['Sources'] = json.dumps(sources)
        rendered = comparison.formation_markdown(mutated, '2024-05-02-market-research')
        late.write_text(note('2024-05-02', rendered['journal_markdown'] + '\n' + rendered['detail_markdown']), encoding='utf-8')
        result = market_notes.outcomes(self.vault, late, comparison.parse_time('2024-05-02T11:32:00-04:00'))
        self.assertFalse(result['complete'])
        self.assertTrue(any('formation is frozen' in row['error'] for row in result['findings']))
        (self.folder / '2024-06-01-market-research.md').write_text(note('2024-06-01'), encoding='utf-8')
        result = market_notes.outcomes(self.vault, now=comparison.parse_time('2024-06-02T11:32:00-04:00'))
        self.assertTrue(result['comparison_formation_must_be_unavailable'])
        unavailable = comparison.unavailable('2024-06-02T11:30:00-04:00', 'First monthly formation was missed.')
        rendered = comparison.formation_markdown(unavailable, '2024-06-02-market-research')
        late.write_text(note('2024-06-02', rendered['journal_markdown'] + '\n' + rendered['detail_markdown']), encoding='utf-8')
        self.assertTrue(market_notes.outcomes(self.vault, late,
                        comparison.parse_time('2024-06-02T11:32:00-04:00'))['complete'])

    def test_empty_and_unavailable_months_remain_frozen_without_due_return_tasks(self):
        for state in ('empty', 'unavailable'):
            card = comparison.unavailable('2024-05-01T11:30:00-04:00', 'Synthetic unavailable formation.')
            if state == 'empty':
                bundle = copy.deepcopy(self.bundle)
                for instrument in bundle['universe']['instruments']:
                    instrument['security_type'] = 'etf'
                card = comparison.form(bundle)
            self.save_formation(card)
            result = market_notes.outcomes(self.vault, now=comparison.parse_time('2025-06-01T11:32:00-04:00'))
            self.assertTrue(result['complete'])
            self.assertEqual(result['due_comparison_checkpoints'], [])
            self.assertEqual(result['comparison_cohorts'][0]['state'], state)

    def test_arithmetic_tampering_missing_member_and_future_record_fail_validation(self):
        self.save_formation()
        observation = comparison.evaluate(self.card, '2024-05-01T11:31:00-04:00', observation_fixture(), '3m')
        for corruption in ('arithmetic', 'member', 'future'):
            changed = copy.deepcopy(observation)
            if corruption == 'arithmetic':
                changed['rows'][0][3] = 0.9
            elif corruption == 'member':
                changed['rows'].pop(2)
            else:
                changed['metadata']['Observed at'] = '2024-08-05T16:00:00-04:00'
            with self.subTest(corruption=corruption):
                draft = self.draft_observation(changed)
                result = market_notes.outcomes(self.vault, draft, comparison.parse_time('2024-08-03T11:32:00-04:00'))
                self.assertFalse(result['complete'])

    def test_retained_evidence_must_support_sources_actions_and_first_session(self):
        observation = comparison.evaluate(self.card, '2024-05-01T11:31:00-04:00', observation_fixture(), '3m')
        for corruption in ('source', 'actions', 'calendar', 'marker'):
            changed = copy.deepcopy(observation)
            if corruption == 'source':
                changed['metadata']['Sources'] = '[]'
            elif corruption == 'actions':
                changed['metadata']['Corporate actions'] = '{}'
            elif corruption == 'marker':
                changed['metadata']['Observed at'] = '2024-08-02T15:00:00-04:00'
            else:
                calendar = json.loads(changed['metadata']['Calendar'])
                calendar['dates'].remove('2024-05-02')
                changed['metadata']['Calendar'] = json.dumps(calendar)
            with self.subTest(corruption=corruption), self.assertRaises(ValueError):
                comparison.validate_observation(changed, self.card)

    def test_six_and_twelve_month_targets_use_same_fixed_baseline(self):
        for horizon, target, endpoint, cutoff in (
                ('6m', '2024-11-02', '2024-11-04', '2024-11-05'),
                ('12m', '2025-05-02', '2025-05-02', '2025-05-03')):
            bundle = observation_fixture()
            bundle['as_of'] = cutoff + 'T11:30:00-04:00'
            bundle['sessions'] = calendar_fixture('2024-05-01', cutoff)
            prices = bundle['prices'][0]
            prices['query']['end'] = prices['query']['requested_end'] = cutoff + 'T03:59:59Z'
            for rows in prices['data']['bars'].values():
                rows[-1] = bar(endpoint, rows[-1]['o'])
            with self.subTest(horizon=horizon):
                result = comparison.evaluate(self.card, '2024-05-01T11:31:00-04:00', bundle, horizon)
                self.assertEqual(result['state'], 'observed')
                self.assertEqual(comparison.parse_time(result['baseline_at']).astimezone(NY).date().isoformat(), '2024-05-02')
                self.assertEqual(comparison.parse_time(result['observed_at']).astimezone(NY).date().isoformat(), endpoint)
                self.assertEqual(comparison.month_target(comparison.parse_date('2024-05-02'), int(horizon[:-1])).isoformat(), target)

    def test_same_day_retry_links_original_and_corrections_are_explicit(self):
        self.save_formation()
        first = comparison.evaluate(self.card, '2024-05-01T11:31:00-04:00', observation_fixture(), '3m')
        draft = self.draft_observation(first)
        original = self.folder / '2024-08-03-market-research.md'
        original.write_bytes(draft.read_bytes())
        saved = original.read_bytes()
        prior = comparison.record_link('2024-08-03-market-research', comparison.heading_for('simple-momentum-v1@2024-05', '3m'))
        bundle = observation_fixture()
        bundle['as_of'] = '2024-08-03T15:00:00-04:00'
        bundle['prices'][0]['data']['bars']['AAA'][-1]['o'] = 140
        bundle['prices'][0]['data']['bars']['AAA'][-1]['c'] = 140
        bundle['prices'][0]['data']['bars']['AAA'][-1]['h'] = 140
        changed = comparison.evaluate(self.card, '2024-05-01T11:31:00-04:00', bundle, '3m')
        for replaces, complete in (('-', False), (prior, True)):
            snippets = comparison.observation_markdown(changed, '2024-08-03-150000-market-research', replaces)
            draft.write_text(note('2024-08-03', snippets['journal_markdown'] + '\n' + snippets['detail_markdown'],
                                  as_of=bundle['as_of']), encoding='utf-8')
            result = market_notes.outcomes(self.vault, draft, comparison.parse_time('2024-08-03T15:02:00-04:00'),
                                           'manual', bundle['as_of'])
            self.assertEqual(result['complete'], complete, result['findings'])
        self.assertEqual(original.read_bytes(), saved)

    def test_unavailable_observation_can_recover_but_requires_new_card(self):
        self.save_formation()
        incomplete = observation_fixture()
        del incomplete['corporate_actions']['CCC']
        observation = comparison.evaluate(self.card, '2024-05-01T11:31:00-04:00', incomplete, '3m')
        draft = self.draft_observation(observation)
        original = self.folder / '2024-08-03-market-research.md'
        original.write_bytes(draft.read_bytes())
        bundle = observation_fixture()
        bundle['as_of'] = '2024-08-03T15:00:00-04:00'
        result = comparison.evaluate(self.card, '2024-05-01T11:31:00-04:00', bundle, '3m')
        snippets = comparison.observation_markdown(result, '2024-08-03-150000-market-research')
        draft.write_text(note('2024-08-03', snippets['journal_markdown'] + '\n' + snippets['detail_markdown'],
                              as_of=bundle['as_of']), encoding='utf-8')
        indexed = market_notes.outcomes(self.vault, draft, comparison.parse_time('2024-08-03T15:02:00-04:00'),
                                        'manual', bundle['as_of'])
        self.assertTrue(indexed['complete'], indexed['findings'])
        self.assertEqual(indexed['comparison_checkpoints'][0]['state'], 'observed')

    def test_input_rejects_duplicate_fields_nonfinite_and_symlink(self):
        path = self.vault / 'invalid.json'
        for raw in ('{"a": 1, "a": 2}', '{"a": NaN}', '[' * 2000 + '0' + ']' * 2000):
            path.write_text(raw, encoding='utf-8')
            with self.assertRaises((ValueError, comparison.DataError)):
                comparison.load_json(path)
        linked = self.vault / 'linked.json'
        linked.symlink_to(path)
        with self.assertRaises(ValueError):
            comparison.load_json(linked)

    def test_card_bounds_and_malformed_cli_fail_without_traceback(self):
        rendered = comparison.formation_markdown(self.card, '2024-05-01-market-research')
        with self.assertRaisesRegex(ValueError, 'budget'):
            comparison.read_card(rendered['detail_markdown'] + 'x' * comparison.MAX_CARD_BYTES,
                                 comparison.heading_for(self.card['metadata']['Cohort']))
        path = self.vault / 'nested.json'
        path.write_text('[' * 2000 + '0' + ']' * 2000, encoding='utf-8')
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'skills/market-research/scripts/market_comparison.py'),
                                 'form', '--input', str(path), '--note-key', '2024-05-01-market-research'],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('Traceback', result.stderr)
        self.assertIn('nesting', json.loads(result.stdout)['error'])

    def test_retained_source_queries_cannot_change_the_comparison_convention(self):
        self.save_formation()
        good = comparison.evaluate(self.card, '2024-05-01T11:31:00-04:00', observation_fixture(), '3m')
        for corruption in ('feed', 'adjustment', 'currency', 'mapping', 'symbols', 'calendar', 'calendar_range', 'price_range'):
            changed = copy.deepcopy(good)
            sources = json.loads(changed['metadata']['Sources'])
            if corruption == 'calendar':
                sources = [sources[0], sources[0]]
            elif corruption == 'calendar_range':
                sources[-1]['query']['start'] = '2024-05-03'
            elif corruption == 'price_range':
                sources[0]['query']['start'] = '2024-05-03T04:00:00Z'
            else:
                key, value = {'feed': ('feed', 'iex'), 'adjustment': ('adjustment', 'raw'),
                              'currency': ('currency', 'EUR'), 'mapping': ('asof', '2099-01-01'),
                              'symbols': ('symbols', 'AAA')}[corruption]
                sources[0]['query'][key] = value
            changed['metadata']['Sources'] = json.dumps(sources)
            with self.subTest(corruption=corruption):
                draft = self.draft_observation(changed)
                indexed = market_notes.outcomes(self.vault, draft, comparison.parse_time('2024-08-03T11:32:00-04:00'))
                self.assertFalse(indexed['complete'])

    def test_formation_roster_and_classifications_are_bound_to_universe_hash(self):
        for corruption in ('remove', 'classification', 'name'):
            changed = copy.deepcopy(self.card)
            if corruption == 'remove':
                changed['rows'] = [row for row in changed['rows'] if row[1] != 'AAA']
                changed['rows'][-1][-1] = 'selected'
            elif corruption == 'classification':
                changed['rows'][-1][2] = 'etf'
            else:
                changed['metadata']['Universe'] = 'A different declared universe'
            with self.subTest(corruption=corruption), self.assertRaisesRegex(ValueError, 'frozen full universe'):
                comparison.validate_formation(changed)

    def test_visible_daily_bar_evidence_cannot_be_published_before_midnight(self):
        self.save_formation()
        changed = comparison.evaluate(self.card, '2024-05-01T11:31:00-04:00', observation_fixture(), '3m')
        changed['metadata']['As of'] = '2024-08-02T16:30:00-04:00'
        snippets = comparison.observation_markdown(changed, '2024-08-02-163000-market-research')
        draft = self.vault / 'draft.md'
        draft.write_text(note('2024-08-02', snippets['journal_markdown'] + '\n' + snippets['detail_markdown'],
                              as_of=changed['metadata']['As of']), encoding='utf-8')
        indexed = market_notes.outcomes(self.vault, draft, comparison.parse_time('2024-08-02T16:32:00-04:00'),
                                        'manual', changed['metadata']['As of'])
        self.assertFalse(indexed['complete'])
        self.assertTrue(any('not fully elapsed' in row['error'] for row in indexed['findings']))
        changed = copy.deepcopy(self.card)
        changed['metadata']['Reference session'] = '2024-05-01'
        with self.assertRaisesRegex(ValueError, 'not fully elapsed'):
            comparison.validate_formation(changed)

    def test_missing_timezone_is_an_actionable_structured_error(self):
        import contextlib
        import io
        output = io.StringIO()
        with patch.object(comparison, 'ZoneInfo', side_effect=comparison.ZoneInfoNotFoundError('missing')):
            with contextlib.redirect_stdout(output):
                code = comparison.main(['unavailable', '--as-of', '2024-05-01T11:30:00-04:00',
                                        '--reason', 'Synthetic missing calendar', '--note-key', '2024-05-01-market-research'])
        self.assertEqual(code, 2)
        self.assertIn('timezone', json.loads(output.getvalue())['error'])

    def test_formation_queries_and_calendar_preserve_the_complete_screen_lookback(self):
        for corruption in ('price_start', 'calendar_start', 'missing_older_sessions', 'gap_between_price_batches'):
            changed = copy.deepcopy(self.card)
            sources = json.loads(changed['metadata']['Sources'])
            if corruption == 'price_start':
                sources[0]['query']['start'] = '2024-04-30T04:00:00Z'
            elif corruption == 'calendar_start':
                sources[-1]['query']['start'] = '2024-04-30'
            elif corruption == 'missing_older_sessions':
                changed['metadata']['History calendar'] = json.dumps(json.loads(changed['metadata']['History calendar'])[-10:])
            else:
                early = copy.deepcopy(sources[0])
                early['query']['end'] = early['query']['requested_end'] = '2023-07-01T03:59:59Z'
                sources[0]['query']['start'] = '2024-01-01T05:00:00Z'
                sources.insert(0, early)
            changed['metadata']['Sources'] = json.dumps(sources)
            with self.subTest(corruption=corruption), self.assertRaises(ValueError):
                comparison.validate_formation(changed)

    def test_publication_and_identical_retry_preserve_cohort_and_observation(self):
        first = self.save_formation()
        observation = comparison.evaluate(self.card, '2024-05-01T11:31:00-04:00', observation_fixture(), '3m')
        draft = self.draft_observation(observation)
        before = first.read_bytes()
        with patch.object(market_notes, 'require_publication_provenance'):
            result = market_notes.publish(draft, self.vault, comparison.parse_time('2024-08-03T11:32:00-04:00'))
            self.assertEqual(result['status'], 'created')
            self.assertEqual(market_notes.publish(draft, self.vault,
                             comparison.parse_time('2024-08-03T11:32:00-04:00'))['status'], 'unchanged')
        self.assertEqual(first.read_bytes(), before)

    def test_cli_generates_snippets_without_writing_vault(self):
        saved = self.vault / 'input.json'
        saved.write_text(json.dumps(self.bundle), encoding='utf-8')
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'skills/market-research/scripts/market_comparison.py'),
                                 'form', '--input', str(saved), '--note-key', '2024-05-01-market-research'],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        output = json.loads(result.stdout)
        self.assertEqual(output['members'], self.card['members'])
        self.assertIn('#### Comparison cohorts', output['journal_markdown'])
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_linked_formation_keeps_full_evidence_outside_the_readable_note(self):
        rendered = comparison.formation_markdown(self.card, '2024-05-01-market-research', self.vault)
        attachment = rendered['evidence_attachment']
        path = Path(attachment['path'])
        self.assertEqual(path.parent, self.folder / 'Snapshots' / 'Comparisons')
        self.assertEqual(path.name, attachment['sha256'] + '.json')
        raw, before = path.read_bytes(), path.stat().st_mtime_ns
        self.assertEqual(comparison.hashlib.sha256(raw).hexdigest(), attachment['sha256'])
        self.assertNotIn('History calendar', rendered['detail_markdown'])
        self.assertNotIn('| Sources |', rendered['detail_markdown'])
        self.assertNotIn('| NASDAQ | DDD |', rendered['detail_markdown'])
        self.assertLess(len(rendered['detail_markdown']), 5000)
        self.assertGreater(len(raw), len(rendered['detail_markdown']) * 3)
        parsed = comparison.read_card(rendered['detail_markdown'], comparison.heading_for(self.card['metadata']['Cohort']),
                                      vault=self.vault, note_key='2024-05-01-market-research')
        self.assertEqual(parsed, self.card)
        retried = comparison.formation_markdown(self.card, '2024-05-01-market-research', self.vault)
        self.assertEqual(retried['evidence_attachment']['status'], 'unchanged')
        self.assertEqual(path.stat().st_mtime_ns, before)
        self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(list(self.vault.glob('.comparison-*')), [])

    def test_partial_upstream_discovery_cannot_form_a_smaller_successful_cohort(self):
        incomplete = copy.deepcopy(self.bundle)
        incomplete['universe'].update(discovery_complete=False,
            discovery_coverage={'declared': 7, 'passing': 4, 'unavailable': 3},
            discovery_input_sha256='a' * 64)
        self.assertFalse(comparison.market_screen.screen(incomplete)['complete'])
        formed = comparison.form(incomplete)
        self.assertEqual(formed['metadata']['State'], 'unavailable')
        self.assertEqual(formed['members'], [])
        self.assertTrue(all(row[-1] == 'unavailable' for row in formed['rows']))
        self.assertNotEqual(formed['metadata']['Screen input SHA-256'], self.card['metadata']['Screen input SHA-256'])
        rendered = comparison.formation_markdown(formed, '2024-05-01-market-research', self.vault)
        restored = comparison.read_card(rendered['detail_markdown'], comparison.heading_for(formed['metadata']['Cohort']),
                                       vault=self.vault, note_key='2024-05-01-market-research')
        self.assertEqual(restored['metadata']['State'], 'unavailable')
        self.assertEqual(restored['members'], [])

    def test_complete_discovery_preserves_canonical_roster_hash_and_strict_boolean(self):
        complete = copy.deepcopy(self.bundle)
        complete['universe'].update(discovery_complete=True,
            discovery_coverage={'declared': 4, 'passing': 4, 'unavailable': 0},
            discovery_input_sha256='a' * 64)
        formed = comparison.form(complete)
        self.assertEqual(formed['metadata']['State'], 'formed')
        self.assertEqual(formed['members'], self.card['members'])
        self.assertEqual(formed['metadata']['Universe SHA-256'], self.card['metadata']['Universe SHA-256'])
        for invalid in ('false', None, 1):
            complete['universe']['discovery_complete'] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                comparison.form(complete)

    def test_linked_records_are_verified_by_the_ordinary_outcomes_index(self):
        rendered = comparison.formation_markdown(self.card, '2024-05-01-market-research', self.vault)
        path = self.folder / '2024-05-01-market-research.md'
        path.write_text(note('2024-05-01', rendered['journal_markdown'] + '\n' + rendered['detail_markdown']), encoding='utf-8')
        observed = comparison.evaluate(self.card, '2024-05-01T11:31:00-04:00', observation_fixture(), '3m')
        compact = comparison.observation_markdown(observed, '2024-08-03-market-research', vault=self.vault)
        draft = self.vault / 'draft.md'
        draft.write_text(note('2024-08-03', compact['journal_markdown'] + '\n' + compact['detail_markdown']), encoding='utf-8')
        result = market_notes.outcomes(self.vault, draft, comparison.parse_time('2024-08-03T11:32:00-04:00'))
        self.assertTrue(result['complete'], result['findings'])
        self.assertAlmostEqual(result['comparison_checkpoints'][0]['return_value'], 0.1)
        self.assertEqual(len(result['comparison_cohorts'][0]['members']), 3)
        Path(rendered['evidence_attachment']['path']).unlink()
        result = market_notes.outcomes(self.vault, draft, comparison.parse_time('2024-08-03T11:32:00-04:00'))
        self.assertFalse(result['complete'])
        self.assertTrue(any('evidence' in row['error'] for row in result['findings']))

    def test_attached_formation_publishes_from_scratch_before_its_note_exists(self):
        rendered = comparison.formation_markdown(self.card, '2024-05-01-market-research', self.vault)
        attachment = Path(rendered['evidence_attachment']['path'])
        original, original_time = attachment.read_bytes(), attachment.stat().st_mtime_ns
        draft = self.vault / 'not-the-daily-filename.md'
        draft.write_text(note('2024-05-01', rendered['journal_markdown'] + '\n' + rendered['detail_markdown']),
                         encoding='utf-8')
        target = self.folder / '2024-05-01-market-research.md'
        self.assertFalse(target.exists())
        with patch.object(market_notes, 'require_publication_provenance'):
            result = market_notes.publish(draft, self.vault, comparison.parse_time('2024-05-01T11:32:00-04:00'))
            self.assertEqual(result['status'], 'created')
            self.assertEqual(market_notes.publish(draft, self.vault,
                             comparison.parse_time('2024-05-01T11:32:00-04:00'))['status'], 'unchanged')
        self.assertEqual(target.read_bytes(), draft.read_bytes())
        self.assertEqual(attachment.read_bytes(), original)
        self.assertEqual(attachment.stat().st_mtime_ns, original_time)

    def test_attachment_changed_after_initial_validation_cannot_publish(self):
        rendered = comparison.formation_markdown(self.card, '2024-05-01-market-research', self.vault)
        attachment = Path(rendered['evidence_attachment']['path'])
        draft = self.vault / 'draft.md'
        draft.write_text(note('2024-05-01', rendered['journal_markdown'] + '\n' + rendered['detail_markdown']),
                         encoding='utf-8')
        def changed_after_initial_checks(_):
            attachment.write_bytes(attachment.read_bytes() + b' ')
        with patch.object(market_notes, 'require_publication_provenance', side_effect=changed_after_initial_checks):
            with self.assertRaisesRegex(RuntimeError, 'outcome evidence changed before publication'):
                market_notes.publish(draft, self.vault, comparison.parse_time('2024-05-01T11:32:00-04:00'))
        self.assertFalse((self.folder / '2024-05-01-market-research.md').exists())
        self.assertEqual(len(list(self.vault.glob('.market-research-stage-*'))), 1)

    def test_linked_evidence_rejects_owner_digest_summary_and_traversal_tampering(self):
        rendered = comparison.formation_markdown(self.card, '2024-05-01-market-research', self.vault)
        attachment = rendered['evidence_attachment']
        heading = comparison.heading_for(self.card['metadata']['Cohort'])
        def read(text=None, owner='2024-05-01-market-research', vault=None):
            return comparison.read_card(text or rendered['detail_markdown'], heading,
                                        vault=vault or self.vault, note_key=owner)
        for text in (
                rendered['detail_markdown'].replace('| Declared instruments | 4 |', '| Declared instruments | 3 |'),
                rendered['detail_markdown'].replace('| NASDAQ | AAA |', '| NASDAQ | ZZZ |'),
                rendered['detail_markdown'].replace(attachment['link'], attachment['link'].replace('Snapshots/', 'Snapshots/../')),
                rendered['detail_markdown'].replace(attachment['link'], '[[/etc/passwd]]')):
            with self.subTest(text=text[:80]), self.assertRaises(ValueError):
                read(text)
        with self.assertRaisesRegex(ValueError, 'owner'):
            read(owner='2024-05-01-120000-market-research')
        with self.assertRaisesRegex(ValueError, 'selected vault'):
            comparison.read_card(rendered['detail_markdown'], heading, note_key='2024-05-01-market-research')
        path = Path(attachment['path'])
        original = path.read_bytes()
        path.write_bytes(original.replace(b'"AAA"', b'"ZZZ"', 1))
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            read()
        with self.assertRaisesRegex(ValueError, 'occupied by different bytes'):
            comparison.save_evidence(self.card, self.vault, '2024-05-01-market-research')
        self.assertNotEqual(path.read_bytes(), original)  # A failed retry never overwrites the occupant.

    def test_compact_metadata_round_trip_preserves_unescaped_evidence_values(self):
        self.bundle['universe']['name'] = 'Synthetic A&B | declared universe'
        self.bundle['universe']['source'] = 'Synthetic source with A&B | classification notes'
        card = comparison.form(self.bundle)
        rendered = comparison.formation_markdown(card, '2024-05-01-market-research', self.vault)
        parsed = comparison.read_card(rendered['detail_markdown'], comparison.heading_for(card['metadata']['Cohort']),
                                      vault=self.vault, note_key='2024-05-01-market-research')
        self.assertEqual(parsed, card)

    def test_evidence_attachment_has_an_independent_bounded_size(self):
        with patch.object(comparison, 'MAX_EVIDENCE_BYTES', 128):
            with self.assertRaisesRegex(ValueError, 'attachment byte budget'):
                comparison.save_evidence(self.card, self.vault, '2024-05-01-market-research')
        self.assertEqual(list(self.folder.iterdir()), [])
        rendered = comparison.formation_markdown(self.card, '2024-05-01-market-research', self.vault)
        evidence = rendered['evidence_attachment']
        with patch.object(comparison, 'MAX_EVIDENCE_BYTES', 128):
            with self.assertRaisesRegex(ValueError, 'bounded regular'):
                comparison.load_evidence(self.vault, evidence['link'], evidence['sha256'], '2024-05-01-market-research')

    def test_attached_calendar_and_source_validation_is_not_replaced_by_a_digest(self):
        rendered = comparison.formation_markdown(self.card, '2024-05-01-market-research', self.vault)
        original = rendered['evidence_attachment']
        value = json.loads(Path(original['path']).read_bytes())
        value['metadata']['History calendar'] = '[]'
        raw = comparison._canonical_evidence(value)
        sha256 = comparison.hashlib.sha256(raw).hexdigest()
        changed = Path(original['path']).with_name(sha256 + '.json')
        changed.write_bytes(raw)
        text = rendered['detail_markdown'].replace(original['sha256'], sha256)
        with self.assertRaises((ValueError, comparison.DataError)):
            comparison.read_card(text, comparison.heading_for(self.card['metadata']['Cohort']),
                                 vault=self.vault, note_key='2024-05-01-market-research')

    def test_linked_evidence_refuses_symlink_folders_files_and_portable_collisions(self):
        rendered = comparison.formation_markdown(self.card, '2024-05-01-market-research', self.vault)
        attachment = rendered['evidence_attachment']
        path, outside = Path(attachment['path']), self.vault / 'outside.json'
        original = path.read_bytes()
        outside.write_bytes(original)
        path.unlink(); path.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'non-symlink'):
            comparison.load_evidence(self.vault, attachment['link'], attachment['sha256'], '2024-05-01-market-research')
        with self.assertRaisesRegex(ValueError, 'non-symlink'):
            comparison.save_evidence(self.card, self.vault, '2024-05-01-market-research')
        path.unlink(); path.write_bytes(original)
        folder, moved = path.parent, self.vault / 'moved'
        folder.rename(moved); folder.symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'never symlinks'):
            comparison.load_evidence(self.vault, attachment['link'], attachment['sha256'], '2024-05-01-market-research')
        folder.unlink(); moved.rename(folder)
        collision = folder.parent / 'comparisons'
        if not collision.exists():  # Also exercise portable aliases on case-sensitive hosts.
            collision.mkdir()
            with self.assertRaisesRegex(ValueError, 'portable-equivalent'):
                comparison.load_evidence(self.vault, attachment['link'], attachment['sha256'], '2024-05-01-market-research')
        self.assertEqual(outside.read_bytes(), original)

    def test_evidence_directory_swap_during_read_is_detected(self):
        rendered = comparison.formation_markdown(self.card, '2024-05-01-market-research', self.vault)
        attachment = rendered['evidence_attachment']
        folder = Path(attachment['path']).parent
        actual_reader = comparison._read_evidence_bytes
        def swapped(descriptor, name):
            data = actual_reader(descriptor, name)
            folder.rename(self.vault / 'displaced')
            folder.mkdir()
            return data
        with patch.object(comparison, '_read_evidence_bytes', side_effect=swapped):
            with self.assertRaisesRegex(ValueError, 'directory changed'):
                comparison.load_evidence(self.vault, attachment['link'], attachment['sha256'], '2024-05-01-market-research')

    def test_large_frozen_roster_uses_attachment_budget_without_trimming(self):
        # Copy the already verified evidence schema; every new identity has an
        # ineligible security class, so the fixed winners remain unchanged.
        large = copy.deepcopy(self.card)
        for index in range(2000):
            large['rows'].append(['NASDAQ', 'X%04d' % index, 'etf', 'USD', None, None, None, None, 'excluded:type'])
        large['metadata']['Universe SHA-256'] = comparison.digest(comparison.universe_definition(
            large['metadata']['Universe'], large['metadata']['Membership date'], large['metadata']['Universe source'],
            [dict(exchange=row[0], symbol=row[1], security_type=row[2], currency=row[3]) for row in large['rows']]))
        with self.assertRaisesRegex(ValueError, 'note budget'):
            comparison.formation_markdown(large, '2024-05-01-market-research')
        rendered = comparison.formation_markdown(large, '2024-05-01-market-research', self.vault)
        self.assertLess(len(rendered['detail_markdown']), 5000)
        parsed = comparison.read_card(rendered['detail_markdown'], comparison.heading_for(large['metadata']['Cohort']),
                                      vault=self.vault, note_key='2024-05-01-market-research')
        self.assertEqual(len(parsed['rows']), 2004)
        self.assertEqual(parsed['members'], self.card['members'])

    def test_extracted_self_contained_plugin_creates_and_reads_linked_evidence(self):
        install = self.vault / 'isolated installed plugin'
        package = json.loads((ROOT / 'tools/package-files.json').read_text(encoding='utf-8'))['investments']
        for destination, source in package.items():
            target = install / destination
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / source, target)
        source = self.vault / 'fixture.json'
        source.write_text(json.dumps(self.bundle), encoding='utf-8')
        script = install / 'skills/market-research/scripts/market_comparison.py'
        env = {key: value for key, value in os.environ.items() if key not in ('OBSIDIAN_VAULT_SHARED', 'PYTHONPATH')}
        result = subprocess.run([sys.executable, '-I', '-S', '-B', str(script), 'form', '--input', str(source),
                                 '--vault', str(self.vault), '--note-key', '2024-05-01-market-research'],
                                cwd=self.vault, env=env, capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output['members'], self.card['members'])
        self.assertTrue(Path(output['evidence_attachment']['path']).is_file())
        first = self.folder / '2024-05-01-market-research.md'
        first.write_text(note('2024-05-01', output['journal_markdown'] + '\n' + output['detail_markdown']), encoding='utf-8')
        source.write_text(json.dumps(observation_fixture()), encoding='utf-8')
        result = subprocess.run([sys.executable, '-I', '-S', '-B', str(script), 'evaluate', '--input', str(source),
                                 '--vault', str(self.vault), '--cohort-note', str(first), '--cohort', 'simple-momentum-v1@2024-05',
                                 '--horizon', '3m', '--note-key', '2024-08-03-market-research'],
                                cwd=self.vault, env=env, capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        output = json.loads(result.stdout)
        self.assertAlmostEqual(output['return_value'], 0.1)
        self.assertTrue(Path(output['evidence_attachment']['path']).is_file())


if __name__ == '__main__':
    unittest.main()
