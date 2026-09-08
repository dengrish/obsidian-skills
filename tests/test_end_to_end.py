#!/usr/bin/env python3
"""Exercise cross-skill handoffs through the public CLIs in isolated vaults.

Run with the interpreter holding requirements-dev.txt. No live vault, network,
host configuration or installed plugin cache is used.
"""

import ast
from datetime import datetime, time, timedelta
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zoneinfo import ZoneInfo
import yaml

import pymupdf
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summary_note(stem):
    return f'''---
title: A synthetic study of one rectangle
format: Report
sources:
  - "[[{stem}.pdf]]"
author:
  - Jane Doe
published: 2025-01-01
created: 2026-08-30
description: A blue rectangle illustrates the drawing workflow.
tags:
  - "#engineering"
read: true
---
> [!Summary]
> - One blue rectangle appeared on a single page.
> - The drawing provided a controlled example.
> - The example establishes no empirical result.

___

## How the drawing represented a rectangle

The example documented a simple rectangular shape.

## One rectangle was drawn on a single page

The drawing was constructed as a synthetic example.

## The rectangle retained its four straight sides

The rectangle had four sides.<sup>[[{stem}.pdf#page=1|1]]</sup>

![[{stem}_fig_1.png]]
*The rectangle has four straight sides. The drawing shows the synthetic example.*

## The example illustrates a simple drawing workflow

The example demonstrates the drawing operation.

## The drawing represents only one artificial example

- **Scope.** Only one rectangle was drawn.
- **Evidence.** The example collected no empirical observations.

## The drawing is stored in the local PDF

- **Data.** The drawing is in the source PDF.
- **Code.** No analysis code is stated.
'''


def notice_note(stem):
    return f'''---
title: A correction to two dosage values
format: Paper
sources:
  - "[[{stem}.pdf]]"
author:
  - Jane Doe
published: 2025-01-01
created: 2026-09-04
description: A correction notice replaces two dosage values in the published table.
tags:
  - "#medicine"
read: false
---
> [!Summary]
> - The notice corrects two dosage values.
> - The replacement table supersedes the original table.
> - The remaining findings are not reassessed.

___

## The notice corrects two values in a dosage table

The notice identifies two incorrect entries in the published table.

## Editors compared the table with the underlying records

The publisher states that editors checked the source records.

## Two dosage values change in the published record

The corrected values replace the original entries.<sup>[[{stem}.pdf#page=1|1]]</sup>

## Readers should use the replacement table from now on

The correction makes the replacement table authoritative for those values.

## Other findings remain outside the scope of this correction

- **Scope.** The notice does not reassess the article's other findings.

## The corrected article remains the record of reference

- **Record.** The notice identifies the corrected article and replacement table.
- **Evidence.** No supporting material beyond the source records is supplied.
'''


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="obsidian-e2e-")
        self.addCleanup(self.scratch.cleanup)
        self.vault = Path(self.scratch.name) / "vault with spaces"
        for folder in ("Inbox", "Articles", "Wiki", "Sources/PDFs", "Sources/Images"):
            (self.vault / folder).mkdir(parents=True)
        self.pdfs = self.vault / "Sources/PDFs"
        self.images = self.vault / "Sources/Images"
        self.notes = self.vault / "Articles"
        self.env = dict(os.environ, OBSIDIAN_VAULT_SHARED=str(ROOT / "shared/scripts"),
                        PYTHONDONTWRITEBYTECODE="1")

    def run_script(self, relative, *args, expected=0):
        env = self.env
        if relative in {"skills/stock-research/scripts/market_notes.py",
                        "skills/stock-research/scripts/stock_dossiers.py",
                        "skills/stock-research/scripts/stock_feed.py"}:
            # Publication verifies the complete generated bundle. Exercising the
            # source checkout here would bypass the installed-runtime contract.
            relative = "plugins/investments/" + relative
        if relative.startswith("plugins/investments/"):
            env = dict(env, OBSIDIAN_VAULT_SHARED=str(ROOT / "plugins/investments/shared/scripts"))
        result = subprocess.run(
            [sys.executable, str(ROOT / relative), *map(str, args)],
            cwd=self.vault, env=env, capture_output=True, text=True,
            encoding="utf-8", timeout=60)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def stamp_market_draft(self, path):
        plugin = ROOT / "plugins/investments"
        script = "plugins/investments/shared/scripts/note_provenance.py"
        args = ("--plugin", plugin, "--skill", "stock-research")
        record = json.loads(self.run_script(script, "inspect", *args).stdout)
        stamped = path.with_name(path.stem + "-stamped" + path.suffix)
        self.run_script(script, "stamp", *args, "--draft", path, "--output", stamped)
        return record, stamped

    def test_collected_feed_to_daily_and_all_stock_notes(self):
        """Exercise the installed-tree CLIs without real collection or market calls."""
        self.vault = self.vault.resolve()
        from test_stock_feed import account, post, feed
        daily_helper = "skills/stock-research/scripts/market_notes.py"
        dossier_helper = "skills/stock-research/scripts/stock_dossiers.py"
        prepared = json.loads(self.run_script(daily_helper, "prepare", "--vault", self.vault,
                                             "--mode", "manual", "--work-dir", self.scratch.name).stdout)
        cutoff = datetime.fromisoformat(prepared["as_of"])
        observed = (cutoff - timedelta(minutes=5)).isoformat()
        since = (cutoff - timedelta(days=3)).isoformat()
        item = account(1, "Example", post(101, text="Synthetic ideas: $EXAMPLE and $OTHER.",
                       created_at=(cutoff - timedelta(hours=1)).isoformat(),
                       first_retrieved_at=observed, last_checked_at=observed))
        item.update(completed_at=observed, requested_since=since,
                    requested_through=observed, history_before=since)
        folder = self.vault / "Investments"
        (folder / "Sources/X").mkdir(parents=True)
        (folder / "Sources/.feed-collect").mkdir()
        (folder / "x-accounts.md").write_text("- [x] @Example\n", encoding="utf-8")
        source = folder / "Sources/X/example.md"
        source.write_text(feed.render(item, {}), encoding="utf-8")
        item["published_sha256"] = digest(source)
        state = folder / "Sources/.feed-collect/state.json"
        state.write_bytes(feed.encoded({"schema": 1, "accounts": {"example": item},
                         "requests": [], "pending": None, "round_robin": 0, "assets": {}}))
        before = {path: path.read_bytes() for path in (source, state, folder / "x-accounts.md")}
        intake = json.loads(self.run_script("skills/stock-research/scripts/stock_feed.py", "context",
                            "--vault", self.vault, "--cutoff", prepared["as_of"]).stdout)
        self.assertEqual(intake["status"], "ready")
        self.assertEqual([row["post_id"] for row in intake["posts"]], ["101"])
        draft = Path(prepared["draft"])
        body = re.sub(r"DRAFT —[^\n]*", "Synthetic fixture; no verified financial conclusion.",
                      draft.read_text(encoding="utf-8"))
        assessments = "\n\n".join(
            f"#### NASDAQ:{ticker} — {company}\n\nStatus: {status}\n\n"
            f"[[Investments/Stocks/{ticker}]]\n\n"
            "Feed nomination: [Post 101](https://x.com/i/web/status/101). "
            "This is a synthetic test. Evidence is insufficient for a buying recommendation."
            for ticker, company, status in (("EXAMPLE", "Example Inc.", "watch"),
                                             ("OTHER", "Other Inc.", "rejected")))
        body = re.sub(r"(?<=### Candidate assessments\n)\n.*?(?=\n### Thesis updates)",
                      "\n" + assessments + "\n", body, flags=re.S)
        body = body.replace("No active theses.", "| Thesis | State | Update / next check |\n"
                            "| --- | --- | --- |\n"
                            f"| NASDAQ:EXAMPLE@{prepared['date']} | watch | Verify synthetic evidence. |")
        draft.write_text(body, encoding="utf-8")
        producer, stamped = self.stamp_market_draft(draft)
        self.run_script(daily_helper, "review-complete", "--vault", self.vault,
                        "--run-receipt", prepared["run_receipt"], "--draft", stamped, "--check", "final-review")
        publication = json.loads(self.run_script(daily_helper, "publish", stamped,
                                 "--vault", self.vault, "--run-receipt", prepared["run_receipt"]).stdout)
        daily = Path(publication["path"])
        daily_bytes = daily.read_bytes()
        arguments = ("sync", "--vault", self.vault, "--daily-note", daily, "--work-dir", self.scratch.name)
        synced = json.loads(self.run_script(dossier_helper, *arguments).stdout)
        self.assertTrue(synced["complete"], synced)
        self.assertEqual(synced["analyzed"], 2)
        notes = [folder / "Stocks" / (ticker + ".md") for ticker in ("EXAMPLE", "OTHER")]
        saved = {path: path.read_bytes() for path in notes}
        for path in notes:
            content = path.read_text(encoding="utf-8")
            self.assertIn("[[Investments/" + daily.stem + "#NASDAQ:", content)
            self.assertIn(producer["runtime_sha256"], content)
        self.assertIn('status: "rejected"', notes[1].read_text(encoding="utf-8"))
        retry = json.loads(self.run_script(dossier_helper, *arguments).stdout)
        self.assertTrue(retry["complete"], retry)
        self.assertTrue(all(row["status"] == "unchanged" for row in retry["results"]))
        self.assertEqual(daily.read_bytes(), daily_bytes)
        self.assertEqual({path: path.read_bytes() for path in notes}, saved)
        self.assertEqual({path: path.read_bytes() for path in before}, before)

    def make_pdf(self, path):
        with pymupdf.open() as doc:
            page = doc.new_page(width=612, height=792)
            page.insert_text((72, 50), "A synthetic study of one rectangle. Jane Doe, 2025.")
            page.insert_text((72, 75), "Methods: We drew one rectangle. Results: It had four sides.")
            page.draw_rect((100, 150, 500, 350), color=(0, 0, 1), fill=(0.3, 0.5, 0.8))
            page.insert_text((100, 400), "Figure 1. A blue rectangle.")
            doc.save(path)

    def scan_papers(self):
        return json.loads(self.run_script(
            "skills/paper-summarize/scripts/paper_scan.py", "--src", self.pdfs,
            "--notes", self.notes, "--images", self.images, "--json").stdout)

    def test_market_setup_without_keys_from_unrelated_directory(self):
        for key in ('SEC_USER_AGENT', 'ALPACA_API_KEY', 'ALPACA_SECRET_KEY', 'ALPHA_VANTAGE_API_KEY', 'FRED_API_KEY'):
            self.env.pop(key, None)
        before = sorted(str(path.relative_to(self.vault)) for path in self.vault.rglob('*'))
        result = json.loads(self.run_script('skills/stock-research/scripts/market_data.py',
                                            'check', expected=2).stdout)
        self.assertEqual(result['requests'], [])
        self.assertFalse(result['complete'])
        sources = {row['source']: row for row in result['data']}
        self.assertTrue(sources['nasdaq']['configured'])
        self.assertFalse(sources['alpaca']['configured'])
        self.assertFalse(sources['fred']['configured'])
        self.assertTrue(all(row['access'] == 'not_tested' for row in sources.values()))
        self.assertEqual(before, sorted(str(path.relative_to(self.vault)) for path in self.vault.rglob('*')))

    def market_response(self, args, pages, expected=0):
        # Use the real CLI, transport and adapters from another directory. Only
        # the HTTPS opener is replaced; no production fixture/network overrides.
        driver = Path(self.scratch.name) / 'market fixture driver.py'
        driver.write_text('''import io, json, sys
from unittest.mock import Mock
sys.path.insert(0, sys.argv[1])
from market_data import main
from market_http import HttpClient
fixture = json.load(sys.stdin)
class Reply(io.BytesIO):
    status = 200
    headers = {}
opener = Mock()
opener.open.side_effect = [Reply(row.encode() if isinstance(row, str) else json.dumps(row).encode())
                          for row in fixture['pages']]
client = HttpClient(fixture['env'], opener=opener, sleeper=lambda _: None)
raise SystemExit(main(fixture['args'], client))
''', encoding='utf-8')

        key = 'DUMMY_SECRET_FOR_OFFLINE_TEST'
        fixture = {'args': args, 'pages': pages, 'env': {
            'ALPHA_VANTAGE_API_KEY': key, 'ALPACA_API_KEY': key, 'ALPACA_SECRET_KEY': key,
            'FRED_API_KEY': key, 'SEC_USER_AGENT': 'Fixture Research fixture@example.invalid'}}
        response = subprocess.run(
            [sys.executable, str(driver), str(ROOT / 'skills/stock-research/scripts')],
            input=json.dumps(fixture), cwd=self.vault, env=self.env,
            capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(response.returncode, expected, response.stdout + response.stderr)
        self.assertNotIn(key, response.stdout + response.stderr)
        result = json.loads(response.stdout)
        self.assertEqual(result['market_data'], 1)
        return result

    def test_estimate_retrieval_archives_only_a_selected_observation_for_later_cutoffs(self):
        args = ['estimates', '--symbol', 'IBM', '--period', '2027-03-31',
                '--as-of', '2025-09-05T13:00:00Z']
        result = self.market_response(args, [{'symbol': 'IBM', 'estimates': [{
            'date': '2027-03-31', 'horizon': 'fiscal quarter', 'eps_estimate_average': '2.5000',
            'eps_estimate_analyst_count': '12.0000', 'unrelated_text': 'DUMMY_SECRET_FOR_OFFLINE_TEST'}]}], 2)
        self.assertTrue(result['coverage_complete'])
        self.assertFalse(result['within_cutoff'])
        capture = Path(self.scratch.name) / 'estimate response.json'
        capture.write_text(json.dumps(result), encoding='utf-8')
        helper = 'skills/stock-research/scripts/market_estimate_history.py'
        saved = json.loads(self.run_script(helper, 'save', '--input', capture, '--vault', self.vault,
                                           '--period', '2027-03-31', '--horizon', 'fiscal quarter').stdout)
        path = Path(saved['path'])
        self.assertEqual(path.parent, self.vault.resolve() / 'Investments/Snapshots/Estimates')
        original = path.read_bytes()
        self.assertNotIn(b'DUMMY_SECRET', original)
        self.assertNotIn(b'apikey', original)
        retry = json.loads(self.run_script(helper, 'save', '--input', capture, '--vault', self.vault,
                                           '--period', '2027-03-31', '--horizon', 'fiscal quarter').stdout)
        self.assertEqual(retry['status'], 'unchanged')
        self.assertEqual(path.read_bytes(), original)
        early = json.loads(self.run_script(helper, 'history', '--vault', self.vault,
                                          '--symbol', 'IBM', '--as-of', '2025-09-05T13:00:00Z').stdout)
        self.assertEqual(early['snapshots'], [])
        available = json.loads(self.run_script(helper, 'history', '--vault', self.vault,
                                              '--symbol', 'IBM', '--as-of', datetime.now().astimezone().isoformat()).stdout)
        self.assertEqual(len(available['snapshots']), 1)
        context = json.loads(self.run_script('skills/stock-research/scripts/market_notes.py',
                                             'context', '--vault', self.vault).stdout)
        self.assertTrue(context['complete'])
        self.assertEqual(context['other_notes'], [])

    def test_exact_ownership_metadata_flows_through_cli_without_optional_parser(self):
        accession = '0000000002-25-000001'
        metadata = {'cik': 1, 'name': 'Synthetic Issuer', 'tickers': ['FIX'], 'exchanges': ['NYSE'],
                    'filings': {'files': [], 'recent': {
                        'accessionNumber': [accession], 'filingDate': ['2025-02-03'],
                        'acceptanceDateTime': ['2025-02-03T15:00:00Z'], 'reportDate': ['2025-02-01'],
                        'form': ['4'], 'primaryDocument': ['xslF345X05/fixture.xml']}}}
        xml = '''<ownershipDocument><documentType>4</documentType><periodOfReport>2025-02-01</periodOfReport>
<issuer><issuerCik>1</issuerCik><issuerName>Synthetic Issuer</issuerName><issuerTradingSymbol>FIX</issuerTradingSymbol></issuer>
<reportingOwner><reportingOwnerId><rptOwnerCik>2</rptOwnerCik><rptOwnerName>Fixture Owner</rptOwnerName></reportingOwnerId>
<reportingOwnerRelationship><isDirector>1</isDirector><isOfficer>0</isOfficer><isTenPercentOwner>0</isTenPercentOwner><isOther>0</isOther></reportingOwnerRelationship></reportingOwner>
<nonDerivativeTable><nonDerivativeTransaction><securityTitle><value>Common stock</value></securityTitle>
<transactionDate><value>2025-02-01</value></transactionDate><transactionCoding><transactionFormType>4</transactionFormType><transactionCode>P</transactionCode><equitySwapInvolved>0</equitySwapInvolved></transactionCoding>
<transactionAmounts><transactionShares><value>10.5</value></transactionShares><transactionPricePerShare><value>20.00</value></transactionPricePerShare><transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts>
<postTransactionAmounts><sharesOwnedFollowingTransaction><value>110.5</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
<ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature></nonDerivativeTransaction></nonDerivativeTable></ownershipDocument>'''
        result = self.market_response(['sec-ownership', '--cik', '1', '--accession', accession,
                                      '--as-of', '2025-03-01T15:00:00Z'], [metadata, xml])
        self.assertEqual(len(result['requests']), 2)
        self.assertTrue(result['requests'][1]['url'].endswith('/1/000000000225000001/fixture.xml'))
        row = result['data']['transactions'][0]
        self.assertEqual(row['fields']['transaction_shares']['value'], '10.5')
        self.assertIn('privately', row['transaction_code_label'])
        self.assertEqual(result['data']['issuer']['cik'], '0000000001')

    def test_market_retrieval_envelopes_feed_offline_screen(self):
        # An explicitly synthetic calendar isolates the provider-to-calculator
        # contract; these weekdays are not asserted to be real exchange dates.
        day = datetime(2024, 6, 3).date()
        final = datetime(2025, 9, 5).date()
        dates = []
        while day <= final:
            if day.weekday() < 5:
                dates.append(day)
            day += timedelta(days=1)
        sessions = self.market_response(
            ['sessions', '--start', dates[0].isoformat(), '--end', '2025-09-06'],
            [[{'date': day.isoformat(), 'open': '09:30', 'close': '16:00'} for day in dates]])
        ny = ZoneInfo('America/New_York')
        raw = {'STRONG': [], 'SPY': []}
        for i, day in enumerate(dates):
            for symbol in raw:
                price = 100 + i if symbol == 'STRONG' else 100
                raw[symbol].append({
                    't': datetime.combine(day, time.min, ny).isoformat(),
                    'o': price, 'h': price + 1, 'l': price - 1, 'c': price,
                    'v': 1000000, 'n': 10000, 'vw': price})
        prices = self.market_response(
            ['prices', '--symbols', 'STRONG,SPY', '--start', '2024-06-03T00:00:00-04:00',
             '--end', '2025-09-06T08:00:00-04:00', '--feed', 'sip', '--timeframe', '1Day',
             '--adjustment', 'split', '--asof', '2025-09-05'],
            [{'bars': raw, 'next_page_token': None}])
        bundle = {
            'market_screen_input': 1, 'as_of': '2025-09-06T12:00:00-04:00',
            'universe': {'name': 'Synthetic contract fixture', 'membership_date': '2025-09-05',
                         'source': 'https://example.invalid/fixture', 'instruments': [
                             {'symbol': 'STRONG', 'exchange': 'NASDAQ',
                              'security_type': 'common_stock', 'currency': 'USD'}]},
            'benchmark': 'SPY', 'prices': [prices], 'sessions': sessions,
        }
        path = Path(self.scratch.name) / 'screen input.json'
        path.write_text(json.dumps(bundle), encoding='utf-8')
        result = json.loads(self.run_script('skills/stock-research/scripts/market_screen.py',
                                             '--input', path).stdout)
        self.assertTrue(result['complete'])
        self.assertEqual([row['symbol'] for row in result['candidates']], ['STRONG'])
        self.assertEqual(result['reference_session'], final.isoformat())
        metrics = result['candidates'][0]['metrics']
        last_price = 100 + len(dates) - 1
        self.assertEqual(metrics['price'], last_price)
        self.assertEqual(metrics['ma50'], last_price - 24.5)
        self.assertEqual(metrics['ma200'], last_price - 99.5)
        self.assertEqual(metrics['average_daily_notional'], (last_price - 9.5) * 1000000)
        june_price = 100 + dates.index(datetime(2025, 6, 5).date())
        self.assertAlmostEqual(metrics['return_3m'], last_price / june_price - 1)
        self.assertAlmostEqual(metrics['relative_return_3m'], metrics['return_3m'])
        repeated = json.loads(self.run_script('skills/stock-research/scripts/market_screen.py',
                                               '--input', path).stdout)
        self.assertEqual(result, repeated)
        prices['complete'] = False
        path.write_text(json.dumps(bundle), encoding='utf-8')
        partial = json.loads(self.run_script('skills/stock-research/scripts/market_screen.py',
                                              '--input', path, expected=2).stdout)
        self.assertFalse(partial['complete'])
        self.assertEqual(partial['candidates'], result['candidates'])

    def test_market_transport_providers_and_cli_preserve_scope_and_secrets(self):
        run = self.market_response

        invalid_cutoff = run(['prices', '--symbols', 'AAPL',
                              '--start', '2025-09-01T00:00:00-04:00',
                              '--end', '2025-09-06T08:45:00-04:99'], [], 2)
        self.assertEqual(invalid_cutoff['error']['code'], 'invalid_input')
        self.assertEqual(invalid_cutoff['requests'], [])

        bars = run(['prices', '--symbols', 'AAPL,MSFT', '--start', '2025-09-01T00:00:00-04:00',
                    '--end', '2025-09-06T08:45:00-04:00', '--max-pages', '1'], [{
                        'bars': {'AAPL': [{'t': '2025-09-05T04:00:00Z', 'o': 100, 'h': 105,
                                          'l': 99, 'c': 104, 'v': 10000, 'n': 100, 'vw': 102}]},
                        'next_page_token': 'another-page'}], 2)
        self.assertFalse(bars['complete'])
        self.assertEqual(bars['data']['missing_symbols'], ['MSFT'])
        self.assertEqual(len(bars['data']['bars']['AAPL']), 1)
        self.assertEqual(bars['source']['feed'], 'sip')
        self.assertEqual(len(bars['requests']), 1)

        filing_args = ['sec-filing', '--cik', '320193', '--accession',
                       '0000320193-25-000001', '--as-of', '2025-09-05T13:00:00Z']
        filing_rows = {'accessionNumber': ['0000320193-25-000001'],
                       'filingDate': ['2025-09-04'], 'form': ['10-K'],
                       'acceptanceDateTime': ['2025-09-04T12:00:00Z'],
                       'reportDate': ['2025-06-30'], 'primaryDocument': ['fixture.htm']}
        submissions = {'cik': 320193, 'name': 'Synthetic Filing Company',
                       'tickers': ['FIX'], 'exchanges': ['Nasdaq'],
                       'filings': {'recent': filing_rows, 'files': []}}
        filing_html = '''<html><body><h1>Item 7. Management Discussion</h1>
<p>Revenue is in millions of USD. DUMMY_SECRET_FOR_OFFLINE_TEST</p>
<table><tr><th>Period</th><th>Revenue</th></tr>
<tr><td>2025</td><td>120</td></tr><tr><td>2024</td><td>100</td></tr></table>
</body></html>'''
        filing = run(filing_args, [submissions, filing_html], 0)
        self.assertEqual(len(filing['requests']), 2)
        self.assertEqual(filing['data']['filing']['accessionNumber'], '0000320193-25-000001')
        self.assertIn('120', filing['data']['text'])
        self.assertIn('REDACTED', filing['data']['text'])
        self.assertNotIn('DUMMY_SECRET_FOR_OFFLINE_TEST', filing['data']['text'].replace('\\', ''))
        self.assertTrue(filing['data']['sections'])
        self.assertTrue(all(row['section_id'] and row['section_id'] != '[redacted]'
                            for row in filing['data']['sections']))
        self.assertEqual(len(filing['source']['html_sha256']), 64)
        self.assertIsNone(filing['data']['next_offset'])
        encoded_echo = run(filing_args, [submissions, filing_html.replace('_', '&#95;')], 2)
        self.assertEqual(encoded_echo['error']['code'], 'credential_echo')
        split_echo = run(filing_args, [submissions, filing_html.replace(
            'DUMMY_SECRET_FOR_OFFLINE_TEST', 'DUMMY_<!--split-->SECRET_FOR_OFFLINE_TEST')], 2)
        self.assertEqual(split_echo['error']['code'], 'credential_echo')
        self.assertNotIn('data', split_echo)
        # A newly filed accession after the edition cutoff cannot be fetched,
        # even if the caller explicitly asks for it.
        filing_rows['acceptanceDateTime'] = ['2025-09-05T14:00:00Z']
        after_cutoff = run(filing_args, [submissions], 2)
        self.assertEqual(len(after_cutoff['requests']), 1)
        self.assertFalse(after_cutoff['complete'])
        # Earlier acceptance does not permit downloading a filing assigned a
        # later filing date: dissemination may be deferred until that day.
        filing_rows['acceptanceDateTime'] = ['2025-09-04T23:00:00Z']
        filing_rows['filingDate'] = ['2025-09-08']
        deferred = run(filing_args, [submissions], 2)
        self.assertEqual(len(deferred['requests']), 1)
        self.assertFalse(deferred['complete'])

        article = {'title': 'Synthetic issuer update', 'url': 'https://example.test/update',
                   'time_published': '20250905T123000', 'summary': 'DUMMY_SECRET_FOR_OFFLINE_TEST',
                   'ticker_sentiment': [{'ticker': 'AAPL'}]}
        news_args = ['news', '--symbol', 'AAPL', '--since', '2025-09-04T16:00:00-04:00',
                     '--as-of', '2025-09-05T09:00:00-04:00']
        news = run(news_args, [{'items': '1', 'feed': [article]}], 0)
        self.assertTrue(news['complete'])
        self.assertEqual(len(news['data']), 1)
        self.assertIn('[redacted]', news['requests'][0]['url'])
        self.assertEqual(len(news['requests'][0]['sha256']), 64)
        unavailable = run(news_args, [{'Information': 'Invalid api key DUMMY_SECRET_FOR_OFFLINE_TEST'}], 2)
        self.assertFalse(unavailable['complete'])
        self.assertEqual(unavailable['error']['code'], 'access_denied')

        capped = run(news_args + ['--limit', '1'], [{'items': '2', 'feed': [
            article, {**article, 'time_published': '20250905T123100'}]}], 2)
        self.assertEqual(capped['provider_record_count'], 2)
        self.assertEqual(capped['returned_record_count'], 1)
        self.assertEqual(capped['limited_record_count'], 1)

        alpaca_news = run(['news', '--provider', 'alpaca', '--symbol', 'AAPL',
                          '--since', '2025-09-04T16:00:00-04:00',
                          '--as-of', '2025-09-05T09:00:00-04:00', '--include-content'], [{
            'news': [{'id': 1, 'headline': 'Synthetic update',
                      'created_at': '2025-09-05T12:30:00Z', 'updated_at': '2025-09-05T12:35:00Z',
                      'symbols': ['AAPL'], 'url': 'https://example.test/update',
                      'content': 'DUMMY_SECRET_FOR_OFFLINE_TEST'}], 'next_page_token': None}], 0)
        self.assertTrue(alpaca_news['complete'])
        self.assertEqual(alpaca_news['data'][0]['content'], '[redacted]')

        # Match the real RSS field names and padded fractional clock, with
        # synthetic values. A JSON-only fixture misses this provider's parser.
        rss = '''<rss xmlns:ndaq="http://www.nasdaqtrader.com/"><channel>
<pubDate>Fri, 05 Sep 2025 13:00:00 GMT</pubDate><ndaq:numItems>1</ndaq:numItems>
<item><ndaq:HaltDate>09/05/2025</ndaq:HaltDate>
<ndaq:HaltTime>08:00:00                      .590</ndaq:HaltTime>
<ndaq:IssueSymbol>FIX</ndaq:IssueSymbol><ndaq:IssueName>Fixture company</ndaq:IssueName>
<ndaq:Market>NASDAQ</ndaq:Market><ndaq:ReasonCode>T1</ndaq:ReasonCode></item></channel></rss>'''
        halt_args = ['halts', '--date', '2025-09-05', '--as-of', '2025-09-05T09:00:00-04:00']
        halt = run(halt_args, [rss], 0)
        self.assertEqual(halt['data']['halts'][0]['market_code'], 'NASDAQ')
        self.assertEqual(halt['data']['halts'][0]['halt_at'], '2025-09-05T08:00:00.590000-04:00')
        self.assertIn('haltdate=09052025', halt['requests'][0]['url'])
        mismatched = run(halt_args, [rss.replace('09/05/2025', '09/04/2025')], 2)
        self.assertEqual(mismatched['error']['code'], 'schema_error')

        vintage = '2025-09-03'
        metadata = {'realtime_start': vintage, 'realtime_end': vintage, 'seriess': [{
            'id': 'TEST', 'title': 'Synthetic macro series',
            'realtime_start': vintage, 'realtime_end': vintage,
            'observation_start': '2025-09-01', 'observation_end': '2025-09-03',
            'frequency': 'Daily', 'frequency_short': 'D', 'units': 'Percent', 'units_short': '%',
            'seasonal_adjustment': 'Not Seasonally Adjusted', 'seasonal_adjustment_short': 'NSA',
            'last_updated': '2025-09-03 15:16:00-05', 'notes': 'DUMMY_SECRET_FOR_OFFLINE_TEST'}]}
        observations = {'realtime_start': vintage, 'realtime_end': vintage,
                        'observation_start': '2025-09-01', 'observation_end': '2025-09-03',
                        'units': 'lin', 'output_type': 1, 'file_type': 'json',
                        'order_by': 'observation_date', 'sort_order': 'asc',
                        'count': 2, 'offset': 0, 'limit': 1000, 'observations': [
                            {'realtime_start': vintage, 'realtime_end': vintage,
                             'date': '2025-09-01', 'value': '1.25'},
                            {'realtime_start': vintage, 'realtime_end': vintage,
                             'date': '2025-09-02', 'value': '.'}]}
        macro = run(['fred-series', '--series', 'TEST', '--start', '2025-09-01',
                     '--end', '2025-09-03', '--vintage-date', vintage], [metadata, observations], 0)
        self.assertEqual(len(macro['requests']), 2)
        self.assertTrue(all('api_key=[redacted]' in row['url'] for row in macro['requests']))
        self.assertFalse(macro['point_in_time_verified'])
        self.assertEqual(macro['data']['observations'][0]['value'], '1.25')
        self.assertIsNone(macro['data']['observations'][1]['value'])

        releases = run(['fred-releases', '--start', '2025-09-04', '--end', '2025-09-10'], [{
            'realtime_start': '2025-09-04', 'realtime_end': '2025-09-10',
            'order_by': 'release_date', 'sort_order': 'asc', 'count': 1, 'offset': 0, 'limit': 1000,
            'release_dates': [{'release_id': 10, 'release_name': 'Synthetic release', 'date': '2025-09-05'}]}], 0)
        self.assertEqual(releases['data']['release_dates'][0]['release_date'], '2025-09-05')
        self.assertFalse(releases['point_in_time_verified'])

    def test_market_documented_template_is_accepted_by_publisher_linter(self):
        guide = (ROOT / "skills/stock-research/references/note-format.md").read_text(encoding="utf-8")
        template = guide.split("```markdown\n", 1)[1].split("\n```", 1)[0]
        draft = Path(self.scratch.name) / "documented market template.md"
        draft.write_text(template + "\n", encoding="utf-8")
        result = json.loads(self.run_script(
            "skills/stock-research/scripts/market_notes.py", "lint", draft).stdout)
        self.assertEqual(result["theses"], [])
        self.assertFalse((self.vault / "Investments").exists())

    def test_market_checkpoint_catchup_and_lessons_survive_invalidation(self):
        script = "skills/stock-research/scripts/market_notes.py"
        clock = json.loads(self.run_script(script, "context", "--vault", self.vault).stdout)
        today = datetime.fromisoformat(clock["now"]).date()
        first_day = today - timedelta(days=2000)
        baseline_day = first_day + timedelta(days=1)
        update_day = baseline_day + timedelta(days=1)
        thesis = "NASDAQ:EXAMPLE@" + first_day.isoformat()
        zone = ZoneInfo("America/New_York")
        folder = self.vault / "Investments"
        folder.mkdir()

        def stamp(day, hour, minute=0):
            return datetime.combine(day, time(hour, minute), zone).isoformat()

        def link(day, heading):
            return f"[[Investments/{day}-stock-research#{heading}]]"

        def daily(day, state, review):
            as_of = clock["as_of"] if day == today else stamp(day, 9)
            generated = clock["now"] if day == today else stamp(day, 9, 5)
            ledger = ("| Thesis | State | Update / next check |\n|---|---|---|\n"
                      f"| {thesis} | {state} | Synthetic historical state only. |"
                      if state else "No active theses.")
            return (f'---\nstock_research: 1\ndate: {day}\nas_of: "{as_of}"\n'
                    f'generated_at: "{generated}"\nsession: unknown\ncoverage: limited\n---\n'
                    f'# Stock research — {day}\n\n## Decision brief\n\nSynthetic fixture only.\n\n'
                    '### Buying opportunities\n\nNo real investment recommendation.\n\n'
                    '### Next checks\n\nCheck due synthetic observations.\n\n'
                    '## Research record\n\n### Screening and sources\n\nSynthetic calendar and values.\n\n'
                    '### Candidate assessments\n\nNo claim about a real security or holdings.\n\n'
                    f'### Thesis updates\n\n{ledger}\n\n### Outcome review\n\n{review}\n')

        recommendation_header = ("#### Recommendation records\n\n"
            "| Recommendation | First ready | Baseline at | Record | Replaces |\n"
            "|---|---|---|---|---|\n")
        first = folder / f"{first_day}-stock-research.md"
        first.write_text(daily(first_day, "ready", recommendation_header
            + f"| {thesis} | {first_day} | pending | {link(first_day, 'Original recommendation')} | - |\n\n"
            + "#### Original recommendation\n\nSynthetic reference quote120; prospective baseline pending."),
            encoding="utf-8")
        initial = json.loads(self.run_script(script, "outcomes", "--vault", self.vault).stdout)
        self.assertEqual([item["id"] for item in initial["due_baselines"]], [thesis])
        update = folder / f"{update_day}-stock-research.md"
        update.write_text(daily(update_day, "invalidated", recommendation_header
            + f"| {thesis} | {first_day} | {stamp(baseline_day, 9, 30)} | {link(update_day, 'Baseline evidence')} | - |\n\n"
            + "#### Baseline evidence\n\nSynthetic opening100; original quote120 is not an execution. "
            + f"Original: {link(first_day, 'Original recommendation')}. The buying thesis later failed."),
            encoding="utf-8")
        originals = {path: path.read_bytes() for path in (first, update)}
        planned = json.loads(self.run_script(script, "outcomes", "--vault", self.vault).stdout)
        self.assertTrue(planned["complete"])
        self.assertEqual(planned["recommendations"][0]["first_ready"], first_day.isoformat())
        self.assertEqual({item["horizon"] for item in planned["due_checkpoints"]},
                         {"2w", "1m", "3m", "6m", "12m", "24m", "60m"})
        # Previously published month-only records remain readable without rewriting.
        one_month = next(item for item in planned["checkpoints"] if item["horizon"] == "1m")
        month_target_day = datetime.fromisoformat(one_month["target_date"]).date()
        month_note_day = month_target_day + timedelta(days=1)
        previous_month = folder / f"{month_note_day}-stock-research.md"
        previous_month.write_text(daily(month_note_day, None,
            "#### Checkpoint records\n\n"
            "| Recommendation | Months | State | Observed at | Record | Replaces |\n"
            "|---|---|---|---|---|---|\n"
            f"| {thesis} | 1 | observed | {stamp(month_target_day, 16)} | "
            f"{link(month_note_day, 'Historical monthly result')} | - |\n\n"
            "#### Historical monthly result\n\nSynthetic prior monthly observation; "
            f"baseline: {link(update_day, 'Baseline evidence')}."), encoding="utf-8")
        originals[previous_month] = previous_month.read_bytes()
        two_week = next(item for item in planned["checkpoints"] if item["horizon"] == "2w")
        target_day = datetime.fromisoformat(two_week["target_date"]).date()
        self.assertEqual(target_day, baseline_day + timedelta(days=14))
        lesson = f"lesson-{today}-01"
        review = ("#### Checkpoint records\n\n"
            "| Recommendation | Horizon | State | Observed at | Record | Replaces |\n"
            "|---|---|---|---|---|---|\n"
            f"| {thesis} | 2w | observed | {stamp(target_day, 16)} | {link(today, 'Observed result')} | - |\n\n"
            "#### Observed result\n\nSynthetic100-to90 return is -10%; benchmark100-to105 is +5%; "
            "excess is -15 percentage points, gross of costs. Baseline: "
            f"{link(update_day, 'Baseline evidence')}. Invalidation did not erase this observation.\n\n"
            "#### Lesson records\n\n| Lesson | Status | Record |\n|---|---|---|\n"
            f"| {lesson} | provisional | {link(today, 'Provisional lesson')} |\n\n"
            "#### Provisional lesson\n\nOne synthetic case does not establish predictive skill; "
            "test the prior catalyst assumption prospectively and seek contrary cases.\n\n"
            "#### Monthly summaries\n\n| Month | Record |\n|---|---|\n"
            f"| {today:%Y-%m} | {link(today, 'Learning summary')} |\n\n"
            "#### Learning summary\n\nOne first-ready idea, including its failure; two observed "
            "and five overdue checkpoints; one provisional lesson. Other data remain unavailable.")
        draft = Path(self.scratch.name) / "outcome draft.md"
        draft.write_text(daily(today, None, review).replace(stamp(target_day, 16), stamp(today, 16)),
                         encoding="utf-8")
        self.run_script(script, "outcomes", "--vault", self.vault, "--draft", draft, expected=2)
        self.run_script(script, "publish", draft, "--vault", self.vault, expected=2)
        self.assertFalse((folder / f"{today}-stock-research.md").exists())
        # A timestamp correction needs a newly written evidence card; neither an
        # alias nor a different older card can document the current correction.
        old_record = link(update_day, 'Baseline evidence')
        alias_record = old_record.replace('-stock-research#', '-stock-research.md#')
        for stale_card in (alias_record, link(month_note_day, 'Historical monthly result')):
            ambiguous_correction = (recommendation_header
                + f"| {thesis} | {first_day} | {stamp(baseline_day, 9, 31)} | "
                + f"{stale_card} | {old_record} |\n\n" + review)
            draft.write_text(daily(today, None, ambiguous_correction), encoding="utf-8")
            rejected = self.run_script(script, "outcomes", "--vault", self.vault, "--draft", draft, expected=2)
            self.assertIn("new detail card in the current draft", rejected.stdout)
            self.run_script(script, "publish", draft, "--vault", self.vault, expected=2)
            self.assertFalse((folder / f"{today}-stock-research.md").exists())
        # A real section link is insufficient when that immutable evidence card
        # predates the observation it is supposed to support.
        stale_evidence = review.replace(link(today, 'Observed result'), old_record)
        draft.write_text(daily(today, None, stale_evidence), encoding="utf-8")
        self.run_script(script, "outcomes", "--vault", self.vault, "--draft", draft, expected=2)
        self.run_script(script, "publish", draft, "--vault", self.vault, expected=2)
        self.assertFalse((folder / f"{today}-stock-research.md").exists())
        draft.write_text(daily(today, None, review), encoding="utf-8")
        checked = json.loads(self.run_script(script, "outcomes", "--vault", self.vault, "--draft", draft).stdout)
        self.assertEqual(checked["active_lessons"][0]["id"], lesson)
        self.assertFalse(checked["monthly_review_due"])
        self.assertEqual({item["horizon"] for item in checked["due_checkpoints"]},
                         {"3m", "6m", "12m", "24m", "60m"})
        self.assertEqual({item["horizon"] for item in checked["checkpoints"]
                          if item["state"] == "observed"}, {"2w", "1m"})
        _, draft = self.stamp_market_draft(draft)
        self.run_script(script, "publish", draft, "--vault", self.vault)
        rebuilt = json.loads(self.run_script(script, "outcomes", "--vault", self.vault).stdout)
        self.assertEqual(rebuilt["checkpoints"], checked["checkpoints"])
        self.assertEqual(rebuilt["active_lessons"], checked["active_lessons"])
        self.assertTrue(Path(rebuilt["active_lessons"][0]["record_note"]).is_file())
        for path, original in originals.items():
            self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(self.vault.glob(".stock-research-stage-*")), [])

    def test_market_daily_history_publication_and_retry(self):
        script = "skills/stock-research/scripts/market_notes.py"
        initial = json.loads(self.run_script(script, "context", "--vault", self.vault).stdout)
        folder = self.vault / "Investments"
        self.assertTrue(initial["complete"])
        self.assertFalse(folder.exists(), "context must not create output folders")
        today = datetime.fromisoformat(initial["now"]).date()
        yesterday = today - timedelta(days=1)
        thesis = "NASDAQ:EXAMPLE@" + yesterday.isoformat()

        evidence = '\n\n'.join(
            f'Observation {index}: synthetic café revenue was $12.34; the dated source '
            'and counterargument remain separate. No real market claim or investment '
            'recommendation is made. [Fixture source](https://example.invalid/filing).'
            for index in range(100))

        def daily(day, as_of, generated_at, carry, record=evidence):
            ledger = ("| Thesis | State | Update / next check |\n"
                      "| --- | --- | --- |\n"
                      f"| {thesis} | watch | Synthetic fixture; no investment recommendation. |"
                      if carry else "No active theses.")
            buying = (f'{thesis}: watch only; no confirmed buying opportunity.'
                      if carry else 'No confirmed buying opportunity.')
            return (f'---\nstock_research: 1\ndate: {day}\nas_of: "{as_of}"\n'
                    f'generated_at: "{generated_at}"\nsession: unknown\ncoverage: unavailable\n---\n\n'
                    f'# Stock research — {day}\n\n## Decision brief\n\nNo verified market data.\n\n'
                    f'### Buying opportunities\n\n{buying}\n\n'
                    '### Next checks\n\nVerify data before assessing the fixture.\n\n'
                    '## Research record\n\n### Screening and sources\n\nSynthetic test only.\n\n'
                    f'### Candidate assessments\n\n#### NASDAQ:EXAMPLE — Example Inc.\n\nStatus: watch\n\n[[Investments/Stocks/EXAMPLE]]\n\n{record}\n\n'
                    f'### Thesis updates\n\n{ledger}\n\n'
                    '### Outcome review\n\nNo confirmed ideas are due for measurement.\n')

        folder.mkdir()
        prior_time = datetime.combine(yesterday, time(9), ZoneInfo("America/New_York")).isoformat()
        prior = folder / f"{yesterday}-stock-research.md"
        prior.write_text(daily(yesterday, prior_time, prior_time, True), encoding="utf-8")
        original_prior = prior.read_bytes()
        user_note = folder / "My own research.md"
        user_note.write_text("Personal notes must remain unchanged.\n", encoding="utf-8")
        original_user = user_note.read_bytes()
        draft = Path(self.scratch.name) / "market draft.md"
        target = folder / f"{today}-stock-research.md"

        draft.write_text(daily(today, initial["as_of"], initial["now"], False), encoding="utf-8")
        refused = self.run_script(script, "publish", draft, "--vault", self.vault, expected=2)
        self.assertIn("carry active theses", refused.stdout)
        self.assertFalse(target.exists())
        current = daily(today, initial["as_of"], initial["now"], True)
        new_thesis = "NASDAQ:NEW@" + today.isoformat()
        new_lesson = "lesson-" + today.isoformat() + "-01"
        current = current.replace('\n\n### Outcome review',
                                  f'\n| {new_thesis} | watch | Newly recorded synthetic idea. |\n\n### Outcome review')
        current += ('\n#### Lesson records\n\n| Lesson | Status | Record |\n|---|---|---|\n'
                    f'| {new_lesson} | provisional | [[Investments/{today}-stock-research#Initial lesson]] |\n\n'
                    '#### Initial lesson\n\nSynthetic provisional question; no investment claim.\n')
        for identifier in (new_thesis, new_lesson):
            backdated = identifier.replace(today.isoformat(), yesterday.isoformat())
            draft.write_text(current.replace(identifier, backdated), encoding="utf-8")
            rejected = self.run_script(script, "outcomes", "--vault", self.vault, "--draft", draft, expected=2)
            self.assertIn("first-recorded note date", rejected.stdout)
            rejected = self.run_script(script, "publish", draft, "--vault", self.vault, expected=2)
            self.assertIn("first-recorded note date", rejected.stdout)
            self.assertFalse(target.exists())
            self.assertEqual(prior.read_bytes(), original_prior)
        draft.write_text(current, encoding="utf-8")
        linted = json.loads(self.run_script(script, "lint", draft).stdout)
        self.assertEqual(linted["theses"][0]["id"], thesis)
        self.assertEqual(linted["theses"][0]["state"], "watch")
        missing = self.run_script(script, "publish", draft, "--vault", self.vault, expected=2)
        self.assertIn("skill-provenance footer", missing.stdout)
        self.assertFalse(target.exists())
        generator, draft = self.stamp_market_draft(draft)
        stamped = json.loads(self.run_script(script, "lint", draft).stdout)
        self.assertEqual(stamped["provenance"], {"schema": 1, "generated_by": generator})
        self.assertEqual(generator["skill"], "investments:stock-research")
        self.assertEqual(len(generator["runtime_sha256"]), 64)
        created = json.loads(self.run_script(script, "publish", draft, "--vault", self.vault).stdout)
        self.assertEqual(created, {"status": "created", "path": str(target.resolve())})
        self.assertEqual(target.read_bytes(), draft.read_bytes())
        brief, record = target.read_text(encoding="utf-8").split('## Research record\n', 1)
        self.assertIn(f'{thesis}: watch only;', brief)
        self.assertNotIn('### Thesis updates', brief)
        self.assertGreater(len(record), 10 * len(brief), "retain detailed evidence beyond the brief")
        self.assertIn(evidence, record, "long evidence must remain verbatim after publication")
        retry = json.loads(self.run_script(script, "publish", draft, "--vault", self.vault).stdout)
        self.assertEqual(retry["status"], "unchanged")
        published_bytes = target.read_bytes()
        draft.write_text(draft.read_text(encoding="utf-8").replace("Synthetic test only.", "Changed assessment."),
                         encoding="utf-8")
        self.run_script(script, "publish", draft, "--vault", self.vault, expected=2)
        self.assertEqual(target.read_bytes(), published_bytes)
        self.assertEqual(prior.read_bytes(), original_prior)
        self.assertEqual(user_note.read_bytes(), original_user)
        current = json.loads(self.run_script(script, "context", "--vault", self.vault).stdout)
        self.assertEqual(current["current_note"]["state"], "valid")
        self.assertEqual(current["prior_notes"], [str(prior.resolve())])
        self.assertEqual(current["other_notes"], [str(user_note.resolve())])
        self.assertEqual(current["active_theses"][0]["id"], thesis)
        historical_record = Path(current["active_theses"][0]["note"]).read_text(encoding="utf-8")
        self.assertIn(evidence, historical_record, "ledger retrieval must reach the complete earlier record")
        self.assertEqual(list(self.vault.glob(".stock-research-stage-*")), [])

    def test_paper_note_lint_applies_the_selected_nonempirical_mode(self):
        note = self.notes / "Doe_Correction_2025.md"
        note.write_text(notice_note("Doe_Correction_2025"),
                        encoding="utf-8", newline="\n")
        missing_mode = self.run_script(
            "skills/paper-summarize/scripts/note_lint.py", note, expected=2)
        self.assertIn("--mode is required", missing_mode.stderr)
        self.run_script("skills/paper-summarize/scripts/note_lint.py", note,
                        "--mode", "notice")

    def test_pdf_repair_and_rename_preserve_notes_images_and_ledgers(self):
        organizer = "skills/pdf-organize/scripts/organize.py"
        batch = "skills/figure-extract/scripts/batch_extract.py"
        source = self.vault / "Inbox/download.pdf"
        self.make_pdf(source)
        self.run_script(organizer, "rename", "--vault", self.vault, source,
                        "--to", "Doe_Study_2025.pdf", "--dest", self.pdfs, "--apply")
        pdf = self.pdfs / "Doe_Study_2025.pdf"
        self.assertFalse(source.exists())
        self.assertTrue(pdf.is_file())
        self.run_script(batch, "--src", pdf, "--out", self.images, "--dpi", 72)
        figure = self.images / "Doe_Study_2025_fig_1.png"
        automatic = digest(figure)
        self.run_script("skills/figure-extract/scripts/extract_figures.py", pdf,
                        "--out", self.images, "--stem", pdf.stem,
                        "--crop", "1:1:120,170,400,300", "--dpi", 72, "--overwrite")
        repaired = digest(figure)
        self.assertNotEqual(repaired, automatic)
        self.run_script(batch, "--src", pdf, "--out", self.images, "--dpi", 72)
        self.assertEqual(digest(figure), repaired)
        self.run_script(batch, "--src", pdf, "--out", self.images,
                        "--mark-reviewed", "Doe_Study_2025:1")

        note = self.notes / "Doe_Study_2025.md"
        note.write_text(summary_note(pdf.stem), encoding="utf-8", newline="\n")
        self.run_script("skills/paper-summarize/scripts/note_lint.py", note,
                        "--mode", "empirical", "--images", self.images)
        self.assertEqual(self.scan_papers()["counts"]["done"], 1)
        references = self.vault / "Wiki/reference.md"
        references.write_text("[[Doe_Study_2025.md]]\n[[Doe_Study_2025.pdf#page=1]]\n",
                              encoding="utf-8")
        reviews = self.vault / "Reviews"
        reviews.mkdir()
        suggestions = reviews / "figure-extract-suggestions.md"
        examples = (
            "Example: `[[Doe_Study_2025.pdf#page=1]]`.\n\n"
            "```markdown\n![[Doe_Study_2025_fig_1.png]]\n```\n\n"
            "<!-- [[Doe_Study_2025.md]] -->\n")
        suggestions.write_text(
            examples + "Actual evidence: [[Doe_Study_2025.pdf#page=1]].\n",
            encoding="utf-8")

        # Sharing a vault must not let a knowledge rename alter immutable
        # investment history or partly move its otherwise writable family.
        history = self.vault / "Investments/2025-09-05-stock-research.md"
        history.parent.mkdir(exist_ok=True)
        history.write_text("Original evidence: [[Doe_Study_2025.pdf#page=1]].\n",
                           encoding="utf-8")
        before = {str(path.relative_to(self.vault)): digest(path)
                  for path in self.vault.rglob("*") if path.is_file()}
        blocked = self.run_script(organizer, "rename", "--vault", self.vault, pdf,
                                  "--to", "Doe_Renamed_2025.pdf", "--apply", expected=1)
        self.assertIn("protected Investments/ record", blocked.stdout)
        self.assertEqual(before, {str(path.relative_to(self.vault)): digest(path)
                                  for path in self.vault.rglob("*") if path.is_file()})
        # Remove only this synthetic blocker to exercise the ordinary rename
        # and downstream figure/summary consumers in the remainder of the test.
        history.unlink()

        self.run_script(organizer, "rename", "--vault", self.vault, pdf,
                        "--to", "Doe_Renamed_2025.pdf", "--apply")
        renamed = self.pdfs / "Doe_Renamed_2025.pdf"
        renamed_figure = self.images / "Doe_Renamed_2025_fig_1.png"
        renamed_note = self.notes / "Doe_Renamed_2025.md"
        self.assertEqual(digest(renamed_figure), repaired)
        self.assertFalse(pdf.exists())
        self.assertFalse(note.exists())
        self.assertFalse(figure.exists())
        self.assertEqual(renamed_note.read_text(encoding="utf-8"),
                         summary_note("Doe_Renamed_2025"))
        self.assertNotIn("Doe_Study_2025", references.read_text(encoding="utf-8"))
        self.assertEqual(
            suggestions.read_text(encoding="utf-8"),
            examples + "Actual evidence: [[Doe_Renamed_2025.pdf#page=1]].\n")
        for filename in (".figure-manifest.tsv", ".figure-review.txt"):
            record = (self.images / filename).read_text(encoding="utf-8")
            self.assertIn("Doe_Renamed_2025", record)
            self.assertNotIn("Doe_Study_2025", record)
        self.run_script(batch, "--src", renamed, "--out", self.images, "--dpi", 72)
        self.assertEqual(digest(renamed_figure), repaired)
        self.run_script("skills/paper-summarize/scripts/note_lint.py", renamed_note,
                        "--mode", "empirical", "--images", self.images)
        self.assertEqual(self.scan_papers()["counts"]["done"], 1)

    def test_pdf_year_rename_keeps_owned_summary_metadata_aligned(self):
        organizer = "skills/pdf-organize/scripts/organize.py"
        source = self.pdfs / "Doe_Correction_2025.pdf"
        self.make_pdf(source)
        note = self.notes / "Doe_Correction_2025.md"
        note.write_text(
            notice_note(source.stem).replace(
                "published: 2025-01-01",
                "published: 2025-03-14 # date printed by the document"),
            encoding="utf-8", newline="\n")
        citing_note = self.vault / "Wiki/context.md"
        citing_note.write_text(
            "---\npublished: 1999-12-31\n---\n"
            "[[Doe_Correction_2025.pdf]]\n",
            encoding="utf-8")

        planned = self.run_script(
            organizer, "rename", "--vault", self.vault, source,
            "--to", "Doe_Correction_2026.pdf")
        self.assertIn("Publication-date updates (1):", planned.stdout)
        self.assertIn("2025-03-14 -> 2026-03-14", planned.stdout)
        self.assertTrue(source.is_file())
        self.assertIn("published: 2025-03-14", note.read_text(encoding="utf-8"))

        self.run_script(
            organizer, "rename", "--vault", self.vault, source,
            "--to", "Doe_Correction_2026.pdf", "--apply")
        source = self.pdfs / "Doe_Correction_2026.pdf"
        note = self.notes / "Doe_Correction_2026.md"
        body = note.read_text(encoding="utf-8")
        self.assertIn(
            "published: 2026-03-14 # date printed by the document", body)
        self.assertIn("[[Doe_Correction_2026.pdf]]", body)
        context = citing_note.read_text(encoding="utf-8")
        self.assertIn("published: 1999-12-31", context)
        self.assertIn("[[Doe_Correction_2026.pdf]]", context)
        self.run_script("skills/paper-summarize/scripts/note_lint.py", note,
                        "--mode", "notice")

        self.run_script(
            organizer, "rename", "--vault", self.vault, source,
            "--to", "Doe_Correction_nd.pdf", "--apply")
        source = self.pdfs / "Doe_Correction_nd.pdf"
        note = self.notes / "Doe_Correction_nd.md"
        self.assertIn("published: null", note.read_text(encoding="utf-8"))
        self.run_script("skills/paper-summarize/scripts/note_lint.py", note,
                        "--mode", "notice")

        self.run_script(
            organizer, "rename", "--vault", self.vault, source,
            "--to", "Doe_Correction_2027.pdf", "--apply")
        note = self.notes / "Doe_Correction_2027.md"
        self.assertIn("published: 2027-01-01",
                      note.read_text(encoding="utf-8"))
        self.assertIn("published: 1999-12-31",
                      citing_note.read_text(encoding="utf-8"))
        self.run_script("skills/paper-summarize/scripts/note_lint.py", note,
                        "--mode", "notice")

    def test_canonical_inbox_pdf_can_be_filed_without_changing_identity(self):
        source = self.vault / "Inbox/Doe_Study_2025.pdf"
        self.make_pdf(source)
        original = digest(source)
        self.run_script("skills/pdf-organize/scripts/organize.py", "rename",
                        "--vault", self.vault, source, "--to", source.name,
                        "--dest", self.pdfs, "--apply")
        self.assertFalse(source.exists())
        self.assertEqual(digest(self.pdfs / source.name), original)

    def test_book_split_feeds_paper_scan_and_figure_extraction(self):
        book = self.pdfs / "Doe_SynthBook_2025.pdf"
        with pymupdf.open() as doc:
            for number, heading in ((1, "Chapter 1 First topic"),
                                    (2, "Chapter 2 Second topic")):
                page = doc.new_page(width=612, height=792)
                page.insert_text((72, 50), heading)
                page.insert_text((72, 75), "A synthetic chapter for integration testing.")
                page.draw_rect((100, 150, 500, 350), color=(0, 0, 1),
                               fill=(0.3, 0.5, 0.8))
                page.insert_text((100, 400),
                                 f"Figure {number}. A blue rectangle.")
            doc.save(book)
        chapters = [
            {"heading_text": "Chapter 1 First topic",
             "filename": "Doe_SynthBook_2025_01_FirstTopic.pdf",
             "start_idx": 0, "end_idx": 1},
            {"heading_text": "Chapter 2 Second topic",
             "filename": "Doe_SynthBook_2025_02_SecondTopic.pdf",
             "start_idx": 1, "end_idx": 2},
        ]
        chapter_plan = Path(self.scratch.name) / "chapters.json"
        chapter_plan.write_text(json.dumps(chapters), encoding="utf-8")
        chapter_dir = self.pdfs / book.stem
        self.run_script("skills/pdf-organize/scripts/organize.py", "split", book,
                        "--chapters", chapter_plan, "--out", chapter_dir,
                        "--vault", self.vault)
        chapter_paths = [chapter_dir / item["filename"] for item in chapters]
        self.assertTrue(all(path.is_file() for path in chapter_paths))

        sweep = self.scan_papers()
        self.assertEqual(sweep["counts"]["book"], 1)
        self.assertEqual(sweep["counts"]["chapter"], 2)
        selected = json.loads(self.run_script(
            "skills/paper-summarize/scripts/paper_scan.py",
            "--src", chapter_paths[0], "--notes", self.notes,
            "--images", self.images, "--json").stdout)
        self.assertEqual(selected["counts"]["new"], 1)
        self.run_script("skills/figure-extract/scripts/batch_extract.py",
                        "--src", chapter_paths[0], "--out", self.images,
                        "--dpi", 72)
        self.assertTrue((self.images /
                         "Doe_SynthBook_2025_01_FirstTopic_fig_1.png").is_file())

    def test_dotted_pdf_names_require_organization_before_downstream_work(self):
        sources = [self.pdfs / name for name in
                   ("Doe_Study_2025.revised.pdf", "Doe_Study_2025.pdf.pdf")]
        for source in sources:
            self.make_pdf(source)
        original = {path: digest(path) for path in sources}
        scan = self.scan_papers()
        self.assertEqual(scan["counts"]["unorganized"], 2)
        self.assertEqual(scan["counts"]["new"], 0)
        batch = "skills/figure-extract/scripts/batch_extract.py"
        self.run_script(batch, "--src", self.pdfs, "--out", self.images,
                        "--dpi", 72, expected=1)
        self.assertEqual(list(self.images.iterdir()), [])
        self.assertEqual({path: digest(path) for path in sources}, original)

        self.run_script("skills/pdf-organize/scripts/organize.py", "rename",
                        "--vault", self.vault, sources[0],
                        "--to", "Doe_Study_2025.pdf", "--apply")
        organized = self.pdfs / "Doe_Study_2025.pdf"
        self.assertEqual(digest(organized), original[sources[0]])
        self.assertEqual(digest(sources[1]), original[sources[1]])
        scan = self.scan_papers()
        self.assertEqual(scan["counts"]["unorganized"], 1)
        self.assertEqual(scan["counts"]["new"], 1)
        self.run_script(batch, "--src", organized, "--out", self.images, "--dpi", 72)
        self.assertTrue((self.images / "Doe_Study_2025_fig_1.png").is_file())
        self.assertFalse(any("revised" in path.name or ".pdf_fig" in path.name
                             for path in self.images.iterdir()))

    def test_escaped_source_identity_survives_scan_and_pdf_rename(self):
        source = self.pdfs / "Doe_Study_2025.pdf"
        self.make_pdf(source)
        self.run_script("skills/figure-extract/scripts/batch_extract.py",
                        "--src", source, "--out", self.images, "--dpi", 72)
        figure = self.images / "Doe_Study_2025_fig_1.png"
        note = self.notes / "Doe_Study_2025.md"
        body = summary_note(source.stem).replace(
            'sources:\n  - "[[Doe_Study_2025.pdf]]"',
            'sources: # recorded origin\n- "[[\\x44oe_Study_2025.pdf]]" # verified')
        note.write_text(body, encoding="utf-8", newline="\n")
        self.assertEqual(self.scan_papers()["counts"]["done"], 1)
        self.run_script("skills/paper-summarize/scripts/note_lint.py", note,
                        "--mode", "empirical", "--images", self.images)
        original = digest(figure)
        self.run_script("skills/pdf-organize/scripts/organize.py", "rename",
                        "--vault", self.vault, source,
                        "--to", "Doe_Renamed_2025.pdf", "--apply")
        renamed_note = self.notes / "Doe_Renamed_2025.md"
        metadata = yaml.safe_load(
            renamed_note.read_text(encoding="utf-8").split("---", 2)[1])
        self.assertEqual(metadata["sources"], ["[[Doe_Renamed_2025.pdf]]"])
        self.assertTrue(metadata["read"])
        self.assertEqual(str(metadata["created"]), "2026-08-30")
        self.assertEqual(digest(self.images / "Doe_Renamed_2025_fig_1.png"), original)
        self.assertEqual(self.scan_papers()["counts"]["done"], 1)
        self.run_script("skills/paper-summarize/scripts/note_lint.py", renamed_note,
                        "--mode", "empirical", "--images", self.images)

    def test_pdf_rename_preserves_publisher_urls_and_foreign_clipping(self):
        source = self.vault / "Inbox/download.pdf"
        self.make_pdf(source)
        clipping = self.notes / "download.md"
        clipping.write_text(
            "---\n\"sources\": # capture\n- 'https://example.org/O''Reilly/download.pdf'\n"
            'source: "[[download.pdf]]"\n'
            "read: true\n---\n![[download_fig_1.png]]\n*Clipping image.*\n",
            encoding="utf-8")
        figure = self.images / "download_fig_1.png"
        Image.new("RGB", (32, 24), (180, 40, 80)).save(figure)
        reference = self.vault / "Wiki/reference.md"
        publisher = "https://publisher.example/papers/download.pdf"
        reference.write_text(
            f'[[Inbox/download.pdf#page=1]]\n[Publisher]({publisher})\n',
            encoding="utf-8")
        before = {path: digest(path) for path in (source, clipping, figure, reference)}
        self.run_script("skills/pdf-organize/scripts/organize.py", "rename",
                        "--vault", self.vault, source,
                        "--to", "Doe_Study_2025.pdf", "--dest", self.pdfs, "--apply",
                        expected=1)
        self.assertEqual({path: digest(path) for path in before}, before)
        # Resolve the fixture's ambiguous image ownership before retrying.
        # The image keeps its basename and bytes, so the clipping still embeds it.
        held = self.vault / "Held clipping images"
        held.mkdir()
        relocated = held / figure.name
        figure.rename(relocated)
        self.run_script("skills/pdf-organize/scripts/organize.py", "rename",
                        "--vault", self.vault, source,
                        "--to", "Doe_Study_2025.pdf", "--dest", self.pdfs, "--apply")
        self.assertTrue((self.pdfs / "Doe_Study_2025.pdf").is_file())
        # The URL still owns this clipping; only its separate legacy PDF
        # reference follows the authorized rename, never the clipping path.
        self.assertEqual(
            clipping.read_text(encoding="utf-8"),
            "---\n\"sources\": # capture\n- 'https://example.org/O''Reilly/download.pdf'\n"
            'source: "[[Doe_Study_2025.pdf]]"\n'
            "read: true\n---\n![[download_fig_1.png]]\n*Clipping image.*\n")
        self.assertEqual(digest(relocated), before[figure])
        self.assertEqual(reference.read_text(encoding="utf-8"),
                         f'[[Doe_Study_2025.pdf#page=1]]\n[Publisher]({publisher})\n')

    def test_clipping_slug_requires_a_date_decision_and_supports_undated(self):
        script = "skills/clipping-clean/scripts/slug.py"
        missing = self.run_script(
            script, "--no-author", "--topic", "Evergreen Reference",
            expected=2)
        self.assertIn("--year YYYY or --undated", missing.stderr)
        invalid = self.run_script(
            script, "--no-author", "--topic", "Evergreen Reference",
            "--year", "unknown", expected=2)
        self.assertIn("four digits from 0001 to 9999", invalid.stderr)
        undated = json.loads(self.run_script(
            script, "--no-author", "--topic", "Evergreen Reference",
            "--undated").stdout)
        self.assertEqual(undated["filename"], "Evergreen_Reference_nd.md")

    def test_clipping_image_reprocess_keeps_duplicate_detection_and_stems_aligned(self):
        fetch = "skills/clipping-clean/scripts/fetch_images.py"
        dedup = "skills/clipping-clean/scripts/dedup_index.py"

        def clipping_slug(topic):
            result = json.loads(self.run_script(
                "skills/clipping-clean/scripts/slug.py",
                "--author", "Alice Smith", "--topic", topic,
                "--year", "2026").stdout)
            self.assertEqual(result["image_prefix"], result["slug"] + "_fig_")
            return result["slug"]

        old = clipping_slug("Cell Signals")
        new = clipping_slug("Cell Receptors")
        raw = self.vault / "Inbox/capture.md"
        raw.write_text('---\nsources:\n  - "https://example.org/study?utm_source=clip"\n---\nBody.\n',
                       encoding="utf-8")

        def verdict(exclude=None):
            args = [self.notes, "--raw", raw]
            if exclude:
                args.extend(["--exclude", exclude])
            return json.loads(self.run_script(dedup, *args).stdout)["checked"][0]

        self.assertEqual(verdict()["status"], "new")
        note = self.notes / (old + ".md")
        # Publish the complete owner before placing its image.  The guarded
        # placement path requires the exact rendered filename-only embed so a
        # failed run cannot leave an ownerless file in Sources/Images.
        metadata = {"title": "Cell signals", "format": "Article",
                    "sources": ["https://example.org/study"], "read": True}
        body = ('---\n' + yaml.safe_dump(metadata, sort_keys=False) + '---\n'
                + f'![[{old}_fig_1.png]]\n*The cells exchange signals.*\n')
        note.write_text(body, encoding="utf-8")
        rendered = Path(self.scratch.name) / "browser render.png"
        Image.new("RGB", (64, 48), (20, 100, 180)).save(rendered)
        self.run_script(fetch, "place", "--attachments", self.images,
                        "--slug", old, "--index", 1, "--from-file", rendered,
                        "--owner-note", note)
        image = self.images / (old + "_fig_1.png")
        original = digest(image)
        # First-time PDF manifest migration must not claim this clipping.
        pdf = self.pdfs / "Doe_Study_2025.pdf"
        self.make_pdf(pdf)
        self.run_script("skills/figure-extract/scripts/batch_extract.py",
                        "--src", pdf, "--out", self.images, "--dpi", 72)
        manifest = (self.images / ".figure-manifest.tsv").read_text(encoding="utf-8")
        self.assertIn("Doe_Study_2025_fig_1.png", manifest)
        self.assertNotIn(image.name, manifest)
        # Default YAML serialization uses valid, indentless block lists.
        # Duplicate detection must survive that representation too.
        self.assertEqual(verdict()["status"], "duplicate")
        self.assertEqual(verdict(note)["status"], "new")
        external = self.vault / "Wiki/clipping-reference.md"
        external.write_text(
            'The HTML opener is `<!--`.\n\n'
            f'[[{old}|the clipping]]\n![[Sources/Images/{old}_fig_1.png]]\n'
            '\nThe closer is `-->`.\n',
            encoding="utf-8")
        moc_dependency = self.vault / "MOCs/biology.md"
        moc_dependency.parent.mkdir()
        moc_dependency.write_text(
            f'# Supporting sources\n[[{old}|the clipping]]\n'
            f'![[Sources/Images/{old}_fig_1.png]]\n', encoding="utf-8")
        new_note = self.notes / (new + ".md")
        new_note.write_text(body.replace(old, new), encoding="utf-8")
        rename = ["rename", "--attachments", self.images, "--sources", self.pdfs,
                  "--owner-note", note, "--new-owner-note", new_note,
                  "--old-slug", old, "--new-slug", new]

        planned = json.loads(self.run_script(
            fetch, *rename, "--phase", "prepare", "--dry-run").stdout)
        expected_mapping = [{"from": image.name,
                             "to": new + "_fig_1.png"}]
        expected_blockers = [{
            "path": str(moc_dependency.resolve()),
            "references": [old + ".md", old + "_fig_1.png"],
        }, {
            "path": str(external.resolve()),
            "references": [old + ".md", old + "_fig_1.png"],
        }]
        self.assertEqual(planned["phase"], "prepare")
        self.assertEqual(planned["mapping"], expected_mapping)
        self.assertEqual(planned["dependency"]["blockers"], expected_blockers)
        self.assertEqual(planned["results"][0]["action"], "would-copy")
        self.assertTrue(image.is_file())
        self.assertFalse((self.images / (new + "_fig_1.png")).exists())

        prepared = json.loads(self.run_script(
            fetch, *rename, "--phase", "prepare").stdout)
        self.assertEqual(prepared["mapping"], expected_mapping)
        self.assertEqual(prepared["dependency"]["blockers"], expected_blockers)
        self.assertEqual(prepared["results"][0]["action"], "copied")
        new_image = self.images / (new + "_fig_1.png")
        self.assertEqual(digest(image), original)
        self.assertEqual(digest(new_image), original)

        # Dependencies may be rewritten only while both exact artifacts resolve;
        # premature finalization is refused without retiring either copy.
        self.run_script(fetch, *rename, "--phase", "finalize", expected=1)
        self.assertEqual(digest(image), original)
        self.assertEqual(digest(new_image), original)
        dependency = json.loads(self.run_script(
            fetch, "dependencies", "--attachments", self.images,
            "--owner-note", note, "--old-slug", old, expected=1).stdout)
        self.assertFalse(dependency["ok"])
        self.assertEqual(dependency["blockers"], expected_blockers)
        # An external dependency rewrite is a separate authorized operation;
        # once the fixture supplies it, the old copies may be retired.
        external.write_text(
            external.read_text(encoding="utf-8").replace(old, new),
            encoding="utf-8")
        moc_dependency.write_text(
            f'# Supporting sources\n[[{new}|the clipping]]\n'
            f'![[Sources/Images/{new}_fig_1.png]]\n', encoding="utf-8")
        dependency = json.loads(self.run_script(
            fetch, "dependencies", "--attachments", self.images,
            "--owner-note", note, "--old-slug", old).stdout)
        self.assertTrue(dependency["ok"])

        finalized = json.loads(self.run_script(
            fetch, *rename, "--phase", "finalize", "--dry-run").stdout)
        self.assertEqual(finalized["phase"], "finalize")
        self.assertEqual(finalized["mapping"], expected_mapping)
        self.assertEqual(finalized["results"][0]["action"], "would-retire")
        self.assertEqual(digest(image), original)
        self.assertEqual(digest(new_image), original)
        finalized = json.loads(self.run_script(
            fetch, *rename, "--phase", "finalize").stdout)
        self.assertEqual(finalized["results"][0]["action"], "retired")
        note.unlink()
        self.assertFalse(image.exists())
        self.assertEqual(digest(new_image), original)
        current = verdict()
        self.assertEqual(current["status"], "duplicate")
        self.assertEqual(current["matches"], [str(self.notes / (new + ".md"))])

    def test_fresh_vault_bootstrap_supports_both_article_producers(self):
        fresh = Path(self.scratch.name) / "fresh vault"
        inbox = fresh / "Inbox"
        pdfs = fresh / "Sources/PDFs"
        inbox.mkdir(parents=True)
        pdfs.mkdir(parents=True)
        raw = inbox / "capture.md"
        raw.write_text(
            '---\nsources:\n  - "https://example.org/fresh"\n---\nBody.\n',
            encoding="utf-8")
        pdf = pdfs / "Doe_Fresh_2025.pdf"
        self.make_pdf(pdf)
        articles = fresh / "Articles"
        images = fresh / "Sources/Images"
        self.assertFalse(articles.exists())
        self.assertFalse(images.exists())

        # This mirrors both skills' documented fresh-vault bootstrap: input
        # roots already exist, and only the canonical output roots are added.
        articles.mkdir()
        images.mkdir()
        dedup = json.loads(self.run_script(
            "skills/clipping-clean/scripts/dedup_index.py", articles,
            "--raw", raw, "--slug", "Doe_Fresh_Article_2025").stdout)
        self.assertEqual(dedup["checked"][0]["status"], "new")
        self.assertEqual(dedup["slug_checks"][0]["status"], "free")
        papers = json.loads(self.run_script(
            "skills/paper-summarize/scripts/paper_scan.py", "--src", pdfs,
            "--notes", articles, "--images", images, "--json").stdout)
        self.assertEqual(papers["counts"]["new"], 1)
        self.assertFalse((fresh / "Wiki").exists())

    def test_unreadable_alias_owner_cannot_trigger_link_removal(self):
        wiki = self.vault / "Wiki"
        owner = wiki / "hidden-topic.md"
        owner_bytes = (
            '---\ntitle: "Hidden topic"\naliases: ["concealed-alias"]\n'
            '---\nA **hidden topic** illustrates alias resolution.\n').encode("utf-8")
        owner.write_bytes(owner_bytes)
        reader = wiki / "reader.md"
        reader.write_text(
            '---\ntitle: "Reader"\naliases: []\n---\n'
            'A **reader** uses [[concealed-alias]] and [[reader]].\n',
            encoding="utf-8")
        scan_script = "skills/wiki-lint/scripts/scan_vault.py"

        def report():
            return json.loads(self.run_script(
                scan_script, wiki, "--images", self.images).stdout)

        self.assertTrue(any(row["item"] == "item10/alias"
                            for row in report()["problems"]))
        # Even readable frontmatter cannot establish aliases if the complete
        # file cannot be decoded. Do not let that missing owner become a dangler.
        owner.write_bytes(owner_bytes + b"\xff")
        blocked = report()
        self.assertTrue(any(row["item"] == "item0"
                            and "Alias inventory is incomplete" in row["message"]
                            for row in blocked["problems"]))
        self.assertFalse(any(row["item"] in {"item10/dangling", "item10/alias"}
                             for row in blocked["problems"]))
        self.assertTrue(any(row["item"] == "item10/self"
                            for row in blocked["problems"]))
        owner.write_bytes(owner_bytes)
        self.assertTrue(any(row["item"] == "item10/alias"
                            for row in report()["problems"]))

    def test_source_to_wiki_entry_index_collision_checks_and_vault_scan(self):
        source = self.pdfs / "Doe_Study_2025.pdf"
        source_text = (
            "The study compared a treated specimen with a control sample. "
            "The control sample received no treatment, but underwent the same "
            "preparation and measurement procedure. It supplied the baseline "
            "for interpreting differences between the groups; the design supports "
            "this comparison and does not establish a universal treatment effect.")
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_textbox((72, 72, 500, 500), source_text)
            doc.save(source)
        located = json.loads(self.run_script(
            "skills/paper-summarize/scripts/paper_text.py", source,
            "--find", "control sample", "--json").stdout)
        self.assertEqual(located["find"][0]["pages"], [1])
        wiki = self.vault / "Wiki"
        entry = wiki / "control-sample.md"
        entry.write_text('''---
title: "Control sample"
type: Concept
sources:
  - "[[Doe_Study_2025.pdf#page=1]]"
created: 2026-08-30
updated: 2026-08-30
description: "A control sample provides a baseline for comparing the effect of an experimental treatment."
tags:
  - "#biology"
parents:
  - "[[MOCs/biology]]"
read: false
---
A **control sample** provides a baseline for comparing an experimental treatment with an otherwise matched condition. The treatment is withheld while the preparation and measurement procedure remain the same. A difference between the treated and untreated groups can then be interpreted within the limits of that comparison.

**Related:**

---

## Flashcards

An untreated experimental specimen prepared and measured like the treated group to provide a baseline.
??
Control sample
''', encoding="utf-8")
        # A complete generated MOC is an ordinary nested bullet list.
        (self.vault / "MOCs").mkdir()
        (self.vault / "MOCs/biology.md").write_text(
            "- [[Wiki/control-sample|Control sample]]\n", encoding="utf-8")
        index = self.vault / "index.json"
        self.run_script("skills/wiki-build/scripts/vault_index.py", wiki, "-o", index)
        self.assertEqual(
            json.loads(index.read_text(encoding="utf-8"))["entry_count"], 1)
        candidates = self.vault / "candidates.json"
        candidates.write_text(
            json.dumps(["Control sample", "Unrelated device"]), encoding="utf-8")
        collisions = json.loads(self.run_script(
            "skills/wiki-build/scripts/find_collisions.py", "--index", index,
            "--titles", candidates).stdout)
        self.assertEqual([r["verdict"] for r in collisions["results"]], ["merge", "create"])
        lint = self.vault / "lint.json"
        self.run_script("skills/wiki-build/scripts/lint_entry.py", wiki, "-o", lint)
        self.assertTrue(
            json.loads(lint.read_text(encoding="utf-8"))["summary"]["clean"])
        scan = self.vault / "scan.json"
        self.run_script("skills/wiki-lint/scripts/scan_vault.py", wiki,
                        "--images", self.images, "--out", scan)
        report = json.loads(scan.read_text(encoding="utf-8"))
        self.assertEqual(report["problems"], [])
        self.assertEqual(report["backfill_candidates"], [])
        for key in ("self_parented", "parent_cycles"):
            self.assertEqual(report["hierarchy_diagnostic"][key], [])
        file_states = {row["discipline"]: row["state"] for row in
                       report["hierarchy_diagnostic"]["moc_file_states"]}
        self.assertEqual(file_states["biology"], "readable")
        self.assertEqual(report["hierarchy_diagnostic"]["moc_consistency_findings"], [])

        # Content outside the outline is also generated content, not an
        # unchecked region that silently passes the hierarchy audit.
        (self.vault / "MOCs/biology.md").write_text(
            "Introductory prose left by an older generation.\n"
            "- [[Wiki/control-sample|Control sample]]\n", encoding="utf-8")
        self.run_script("skills/wiki-lint/scripts/scan_vault.py", wiki,
                        "--images", self.images, "--out", scan)
        revised_report = json.loads(scan.read_text(encoding="utf-8"))
        self.assertTrue(any(
            finding["kind"] == "malformed-line" and finding["line"] == 1
            for finding in revised_report["hierarchy_diagnostic"]["moc_consistency_findings"]))

    def test_misc_requires_explicit_fallback_tag_and_retagging_updates_both_mocs(self):
        wiki = self.vault / "Wiki"
        entry = wiki / "reference-label.md"
        self.notes.joinpath("Example_Labels_nd.md").write_text(
            "A reference label identifies a record independently of its position.\n",
            encoding="utf-8")
        original = '''---
title: "Reference label"
type: Concept
sources:
  - "[[Example_Labels_nd.md]]"
created: 2026-08-30
updated: 2026-08-30
description: "A reference label identifies a record independently of its position."
tags:
parents: []
read: false
---
A **reference label** identifies a record independently of its position. The label remains attached to the record when the surrounding collection is reordered. This lets a reference continue to identify the same record after its position changes.

**Related:**

---

## Flashcards

An identifier attached to a record that remains stable when its position in a collection changes.
??
Reference label
'''
        entry.write_text(original, encoding="utf-8")

        def scan():
            return json.loads(self.run_script(
                "skills/wiki-lint/scripts/scan_vault.py", wiki,
                "--images", self.images).stdout)

        initial = scan()
        self.assertEqual(initial["untagged_entries"], ["reference-label"])
        self.assertEqual(initial["inventory"], {"entries": 1, "slugs": ["reference-label"]})
        self.assertTrue(any(row["item"] == "item8" for row in initial["problems"]))
        self.assertEqual(initial["hierarchy_diagnostic"]["moc_file_states"], [])
        lint_path = self.vault / "misc-entry-lint.json"
        self.run_script("skills/wiki-build/scripts/lint_entry.py", wiki, "-o", lint_path)
        self.assertFalse(json.loads(lint_path.read_text(encoding="utf-8"))["summary"]["clean"])

        # Blank tags are a repair worklist, not implicit Misc membership.
        # A producer must explicitly assign the fallback before placement.
        fallback = original.replace("tags:\n", 'tags:\n  - "#misc"\n')
        entry.write_text(fallback, encoding="utf-8")
        assigned = scan()
        self.assertEqual(assigned["untagged_entries"], [])
        self.assertEqual(assigned["discipline_tags"], {"misc": 1})
        self.assertEqual(assigned["hierarchy_diagnostic"]["placement_gaps"][0]["missing_disciplines"], ["misc"])
        mocs = self.vault / "MOCs"
        mocs.mkdir()
        misc = mocs / "misc.md"
        tree = "- [[Wiki/reference-label|Reference label]]\n"
        misc.write_text(tree, encoding="utf-8")
        entry.write_text(fallback.replace("parents: []", 'parents:\n  - "[[MOCs/misc]]"'), encoding="utf-8")
        placed = scan()
        self.assertEqual(placed["hierarchy_diagnostic"]["placement_gaps"], [])
        self.assertEqual(placed["hierarchy_diagnostic"]["moc_consistency_findings"], [])
        self.run_script("skills/wiki-build/scripts/lint_entry.py", wiki, "-o", lint_path)
        self.assertTrue(json.loads(lint_path.read_text(encoding="utf-8"))["summary"]["clean"])

        # Misc is exclusive: a specific discipline replaces the fallback.
        entry.write_text(fallback.replace('  - "#misc"', '  - "#misc"\n  - "#computer-science"'),
                         encoding="utf-8")
        mixed = scan()
        self.assertTrue(any(row["item"] == "item8" for row in mixed["problems"]))
        self.run_script("skills/wiki-build/scripts/lint_entry.py", wiki, "-o", lint_path)
        self.assertFalse(json.loads(lint_path.read_text(encoding="utf-8"))["summary"]["clean"])

        # A specific tag places the note in its discipline MOC. Leaving its old
        # Misc listing behind must remain visible even if parents are correct.
        entry.write_text(original.replace("tags:\n", 'tags:\n  - "#computer-science"\n')
                         .replace("parents: []", 'parents:\n  - "[[MOCs/computer-science]]"'), encoding="utf-8")
        discipline = mocs / "computer-science.md"
        discipline.write_text(tree, encoding="utf-8")
        stale = scan()
        self.assertTrue(any(
            row.get("discipline") == "misc" and row.get("slug") == "reference-label"
            for row in stale["hierarchy_diagnostic"]["moc_consistency_findings"]))
        misc.write_text("", encoding="utf-8")
        tagged = scan()
        self.assertEqual(tagged["untagged_entries"], [])
        self.assertEqual(tagged["hierarchy_diagnostic"]["moc_consistency_findings"], [])
        self.assertFalse(any(row.get("discipline") == "misc" for row in
                             tagged["hierarchy_diagnostic"]["moc_inventory_findings"]))

        # Replacing a specific tag with #misc requires a Misc placement again, even when the old
        # discipline MOC and its matching parent still exist.
        entry.write_text(fallback.replace("parents: []", 'parents:\n  - "[[MOCs/computer-science]]"'), encoding="utf-8")
        returning = scan()
        self.assertEqual(returning["hierarchy_diagnostic"]["placement_gaps"][0]["missing_disciplines"], ["misc"])
        entry.write_text(fallback.replace("parents: []", 'parents:\n  - "[[MOCs/misc]]"'), encoding="utf-8")
        misc.write_text(tree, encoding="utf-8")
        returned = scan()
        self.assertEqual(returned["hierarchy_diagnostic"]["placement_gaps"], [])
        self.assertFalse(any(row.get("discipline") == "misc" for row in
                             returned["hierarchy_diagnostic"]["moc_consistency_findings"]))

    def test_topic_queue_reuses_sources_and_checks_off_only_public_entries(self):
        wiki = self.vault / "Wiki"
        backlog = self.vault / "add-to-wiki.md"
        backlog.write_bytes(
            b"# Topics\r\n\r\n- [ ] Geometric average\r\n"
            b"- Arithmetic mean\r\n- [ ] Unresolved topic")
        source = self.notes / "Example_Averages_nd.md"
        source.write_text('''---
title: Averages
format: Article
sources:
  - "https://example.org/averages"
author: []
published: null
created: 2026-09-05
description: Two mathematical averages provide a synthetic workflow fixture.
tags:
  - "#mathematics"
read: false
---
<!-- obsidian:wiki-add-research-source -->
Research extract

This synthetic fixture is an agent-written extract, not captured article text.
Origin: [Averages](https://example.org/averages), accessed 2026-09-05.
Section: Definitions. The arithmetic mean divides the sum by the count;
for positive inputs, the geometric mean is the root of their product.
''', encoding="utf-8")
        existing = wiki / "geometric-mean.md"
        existing.write_text('''---
title: "Geometric mean"
type: Concept
aliases:
  - "geometric-average"
sources:
  - "[[Example_Averages_nd.md]]"
created: 2025-01-01
updated: 2025-01-01
description: "The geometric mean is the root of the product of positive inputs."
tags:
  - "#mathematics"
parents: []
read: true
---
The **geometric mean** of positive inputs is the root of their product.

**Related:**

---

## Flashcards

For positive inputs, the root of their product with degree equal to their count.
!!
Geometric mean <!--SR:!2026-09-05,7,250--> ^saved-card
''', encoding="utf-8")
        original_entry = existing.read_bytes()
        original_source = source.read_bytes()
        scratch = Path(self.scratch.name)
        index = scratch / "topic-index.json"
        self.run_script("skills/wiki-build/scripts/vault_index.py", wiki,
                        "--source", source.name, "-o", index)
        inventory = json.loads(index.read_text(encoding="utf-8"))
        self.assertTrue(inventory["source_matches"])
        candidates = scratch / "topic-candidates.json"
        candidates.write_text(json.dumps(["Geometric average", "Arithmetic mean"]),
                              encoding="utf-8")
        collisions = json.loads(self.run_script(
            "skills/wiki-build/scripts/find_collisions.py", "--index", index,
            "--titles", candidates).stdout)
        self.assertEqual([row["verdict"] for row in collisions["results"]],
                         ["merge", "create"])
        # The queue workflow interprets the same-owner match as a no-edit
        # completion, never as permission to take the builder's merge path.
        helper = "skills/wiki-add/scripts/backlog.py"
        first = scratch / "topic-snapshot-1.json"
        self.run_script(helper, "scan", backlog, "--out", first)
        first_state = json.loads(first.read_text(encoding="utf-8"))
        self.assertEqual(first_state["counts"]["pending"], 3)
        self.run_script(helper, "complete", "--snapshot", first,
                        "--item", first_state["items"][0]["id"],
                        "--wiki", wiki, "--entry", existing)
        self.assertEqual(existing.read_bytes(), original_entry)
        second = scratch / "topic-snapshot-2.json"
        self.run_script(helper, "scan", backlog, "--out", second)
        second_state = json.loads(second.read_text(encoding="utf-8"))
        item = second_state["items"][0]
        self.assertEqual(item["text"], "Arithmetic mean")
        created = wiki / "arithmetic-mean.md"
        before_failed_completion = backlog.read_bytes()
        self.run_script(helper, "complete", "--snapshot", second,
                        "--item", item["id"], "--wiki", wiki,
                        "--entry", created, expected=2)
        self.assertEqual(backlog.read_bytes(), before_failed_completion)
        # Establish the reviewed public-entry fixture. The helper does not
        # write Wiki notes; its evidence gate must see this real file first.
        created.write_text(r'''---
title: "Arithmetic mean"
type: Concept
sources:
  - "[[Example_Averages_nd.md]]"
created: 2026-09-05
updated: 2026-09-05
description: "The arithmetic mean is the sum of a nonempty collection of numbers divided by its size."
tags:
  - "#mathematics"
parents: []
read: false
---
The **arithmetic mean** of a nonempty collection is its sum divided by its size.
For $n\ge1$ observations $x_i$:

$$
\bar{x}=\frac{1}{n}\sum_{i=1}^{n}x_i
$$

**Related:**

---

## Flashcards

The sum divided by the count, $n^{-1}\sum_{i=1}^{n}x_i$, for $n\ge1$ observations $x_i$.
??
Arithmetic mean
''', encoding="utf-8")
        lint = scratch / "topic-entry-lint.json"
        self.run_script("skills/wiki-build/scripts/lint_entry.py", created, "-o", lint)
        self.assertTrue(json.loads(lint.read_text(encoding="utf-8"))["summary"]["clean"])
        self.run_script(helper, "complete", "--snapshot", second,
                        "--item", item["id"], "--wiki", wiki, "--entry", created)
        self.assertEqual(backlog.read_bytes(),
                         b"# Topics\r\n\r\n- [x] Geometric average\r\n"
                         b"- [x] Arithmetic mean\r\n- [ ] Unresolved topic")
        third = scratch / "topic-snapshot-3.json"
        self.run_script(helper, "scan", backlog, "--out", third)
        pending = json.loads(third.read_text(encoding="utf-8"))["items"]
        self.assertEqual([row["text"] for row in pending], ["Unresolved topic"])
        self.assertEqual(existing.read_bytes(), original_entry)
        self.assertEqual(source.read_bytes(), original_source)
        ownership = json.loads(self.run_script(
            "skills/clipping-clean/scripts/dedup_index.py", self.notes,
            "--url", "https://example.org/averages").stdout)
        self.assertEqual(ownership["checked"][0]["status"], "duplicate")

    def test_builder_and_linter_share_the_same_entry_contract_floor(self):
        wiki = self.vault / "Wiki"

        def write_entry(slug, title, body, *, type_="Concept", aliases=(),
                        source="[[Clean.pdf#page=1]]", description=None,
                        tags_block='tags:\n  - "#statistics"', card=None,
                        related=None):
            alias_yaml = ""
            if aliases:
                alias_yaml = "aliases:\n" + "".join(
                    f'  - "{alias}"\n' for alias in aliases)
            footer = "\n\n**Related:**" + (f" {related}" if related else "")
            term = card if card is not None else title
            text = f'''---
title: "{title}"
type: {type_}
{alias_yaml}sources:
  - "{source}"
created: 2026-08-31
updated: 2026-08-31
description: "{description or title + ' is a synthetic alignment fixture.'}"
{tags_block}
parents: []
read: false
---
{body}{footer}

---

## Flashcards

A compact definition used only to exercise the shared contract.
??
{term}
'''
            path = wiki / f"{slug}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

        write_entry(
            "arxiv", "arxiv", "**arxiv** is a repository for scholarly preprints.",
            description="arxiv stores scholarly preprints.")
        write_entry(
            "feature-machine-learning", "Feature (machine learning)",
            "**Feature** is an input variable supplied to a model.", card="Feature",
            description="A feature is an input variable supplied to a model.")
        write_entry(
            "principal-component-analysis", "Principal component analysis",
            "**Principal component analysis** (PCA) is an orthogonal linear transformation.",
            aliases=("pca",), card="Principal component analysis (PCA)",
            description="Principal component analysis transforms variables into orthogonal components.")
        write_entry(
            "k-nearest-neighbors", "$k$-nearest neighbors",
            "**$\\boldsymbol{k}$-nearest neighbors** algorithm (KNN) predicts "
            "from nearby observations.",
            aliases=("knn",), card="k-nearest neighbors (KNN)",
            description="k-nearest neighbors predicts from nearby observations.")
        write_entry(
            "ell-1-norm", "$\\\\ell_1$ norm",
            "**$\\ell_1$ norm** measures vector magnitude using absolute values.",
            card="ell-one norm",
            description=(
                "ell-one norm measures vector magnitude using absolute values."))
        write_entry(
            "l-1-regularization", "$L^{-1}$ regularization",
            "**$L^{-1}$ regularization** is a worked mathematical example.",
            card="L-inverse regularization",
            description=(
                "L-inverse regularization is a worked mathematical example."))
        write_entry(
            "x-1-2-transform", "$x^{1/2}$ transform",
            "**$x^{1/2}$ transform** is a worked mathematical example.",
            card="x-to-the-one-half transform",
            description=(
                "x-to-the-one-half transform is a worked mathematical example."))
        write_entry(
            "r-plus", "$R^{+}$",
            "**$R^{+}$** is a worked mathematical example.",
            card="R-plus",
            description="R-plus is a worked mathematical example.")
        write_entry(
            "archaea", "Archaea",
            "**Archaea** (singular, *archaeon*) is a domain of organisms.",
            card="Archaea")
        write_entry(
            "hard-wrap-acronym", "Hard wrap acronym",
            "**Hard wrap acronym**\n(HWA) binds its counterpart across a hard wrap.",
            aliases=("hwa",), card="Hard wrap acronym (HWA)")
        write_entry(
            "adaboost", "AdaBoost",
            "**AdaBoost** (short for *adaptive boosting*) reweights mistakes.",
            aliases=("adaptive-boosting",),
            card="AdaBoost (adaptive boosting)")
        write_entry(
            "saccharomyces-cerevisiae", "Saccharomyces cerevisiae",
            "***Saccharomyces cerevisiae*** (*S. cerevisiae*) is a model budding yeast.",
            aliases=("s-cerevisiae",),
            card="Saccharomyces cerevisiae (S. cerevisiae)", type_="Organism")
        write_entry(
            "historical-synonym", "Historical synonym",
            "**Historical synonym** (originally called *former name*) is a "
            "worked example.", aliases=("former-name",),
            card="Historical synonym")
        write_entry(
            "introduced-alias", "Introduced alias",
            "**Introduced alias** — which many people call *alternate name* — "
            "is a worked example.")
        write_entry(
            "two-sentence-description", "Two sentence description",
            "**Two sentence description** is a deliberately malformed fixture.",
            description="Two sentence description states one claim. It adds another.")
        write_entry(
            "malformed-flow-list", "Malformed flow list",
            "**Malformed flow list** is a deliberately malformed fixture.")
        malformed_flow = wiki / "malformed-flow-list.md"
        malformed_flow.write_text(
            malformed_flow.read_text(encoding="utf-8").replace(
                "sources:\n", 'aliases: ["one",, "two"]\nsources:\n', 1),
            encoding="utf-8")
        write_entry(
            "malformed-person-date", "Malformed person date",
            "**Malformed person date** (1947 to 2020) was a researcher.",
            type_="Person")
        write_entry(
            "bare-code-shapes", "Bare code shapes",
            "**Bare code shapes** uses [CLS] and writes a .csv file.")
        write_entry(
            "canonical-code-shapes", "Canonical code shapes",
            "**Canonical code shapes** uses `[CLS]` and writes a `.csv` file.")
        write_entry(
            "alignment-sample", "Alignment sample",
            "**Alignment sample** is a deliberately malformed fixture.",
            type_="Widget", aliases=("Wrong Alias",),
            source="[[LeadingZero.pdf#page=02]]",
            description="bad description", tags_block='tags: ["#statistics"]',
            card="Different term", related="[[arxiv]]")
        write_entry(
            "scalar-alias", "Scalar alias",
            "**Scalar alias** is a deliberately malformed alias fixture.")
        scalar_alias = wiki / "scalar-alias.md"
        scalar_alias.write_text(
            scalar_alias.read_text(encoding="utf-8").replace(
                "sources:\n", 'aliases: "scalar-alias-name"\nsources:\n', 1),
            encoding="utf-8")
        write_entry(
            "blank-alias", "Blank alias",
            "**Blank alias** is a deliberately malformed alias fixture.")
        blank_alias = wiki / "blank-alias.md"
        blank_alias.write_text(
            blank_alias.read_text(encoding="utf-8").replace(
                "sources:\n", "aliases:\nsources:\n", 1),
            encoding="utf-8")
        write_entry(
            "missing-counterpart-acronym", "Missing counterpart acronym",
            "**Missing counterpart acronym** (MCA) binds its acronym in the opener.",
            aliases=("mca",), card="Missing counterpart acronym")
        write_entry(
            "synonym-parenthetical", "Synonym parenthetical",
            "**Synonym parenthetical** has a synonym alias without an opener binding.",
            aliases=("alternate-name",),
            card="Synonym parenthetical (alternate-name)")
        write_entry(
            "wrong-title-case", "Wrong title case",
            "**Wrong title case** is a case-sensitive answer fixture.",
            card="wrong title case")
        write_entry(
            "singular-parenthetical", "Bacteria",
            "**Bacteria** (singular, *bacterium*) is a domain of organisms.",
            aliases=("bacterium",), card="Bacteria (bacterium)")
        write_entry(
            "related-anchored", "Related anchored",
            "**Related anchored** has a path-qualified anchored footer link.",
            related="[[Wiki/arxiv.md#History]]")
        write_entry(
            "related-wrong-label", "Related wrong label",
            "**Related wrong label** has a noncanonical footer label.",
            related="[[arxiv#History|preprint archive]]")
        write_entry(
            "duplicate-link-forms", "Duplicate link forms",
            "**Duplicate link forms** compares "
            "[[Wiki/principal-component-analysis.md|Principal component analysis]] "
            "with [[pca|PCA]] as two spellings of one destination.")
        for qualified in ("shared-target", "sub/shared-target",
                          "other/shared-target"):
            write_entry(
                qualified, "Shared target",
                "**Shared target** is one of several same-basename fixtures.")
        write_entry(
            "ambiguous-path-links", "Ambiguous path links",
            "**Ambiguous path links** compares [[sub/shared-target|one target]] "
            "with [[other/shared-target|another target]], while bare "
            "[[shared-target]] and [[SHARED-TARGET.md|Shared target]] remain "
            "ambiguous because a root file has the same basename.")

        lint = json.loads(self.run_script(
            "skills/wiki-build/scripts/lint_entry.py", wiki, "--compact").stdout)
        lint_items = {
            Path(entry["file"]).stem: {finding["item"] for finding in entry["findings"]}
            for entry in lint["entries"]
        }
        self.assertTrue({"2-type-enum", "4-sources", "7-description",
                         "8-tags", "18-alias-form", "19-flashcards"}
                        .issubset(lint_items["alignment-sample"]),
                        lint_items["alignment-sample"])
        for slug in ("arxiv", "feature-machine-learning",
                     "principal-component-analysis", "k-nearest-neighbors",
                     "ell-1-norm", "l-1-regularization",
                     "x-1-2-transform", "r-plus",
                     "archaea", "hard-wrap-acronym", "adaboost",
                     "saccharomyces-cerevisiae", "historical-synonym",
                     "canonical-code-shapes"):
            self.assertEqual(lint_items[slug], set(), slug)
        for slug in ("scalar-alias", "blank-alias", "missing-counterpart-acronym",
                     "synonym-parenthetical", "wrong-title-case",
                     "singular-parenthetical"):
            expected = ("18-alias-form" if slug in ("scalar-alias", "blank-alias")
                        else "19-flashcards")
            self.assertIn(expected, lint_items[slug], slug)
        self.assertIn("17-alias-completeness", lint_items["introduced-alias"])
        self.assertIn("7-description", lint_items["two-sentence-description"])
        self.assertIn("1-valid-yaml", lint_items["malformed-flow-list"])
        self.assertIn("9-person-event-date",
                      lint_items["malformed-person-date"])
        self.assertIn("16-code-typography", lint_items["bare-code-shapes"])

        scan = json.loads(self.run_script(
            "skills/wiki-lint/scripts/scan_vault.py", wiki, "--indent", "0").stdout)
        scan_items = {}
        for problem in scan["problems"]:
            scan_items.setdefault(problem["slug"], set()).add(problem["item"])
        self.assertTrue({"item2/type-enum", "item4", "item7", "item8",
                         "item11", "item18", "item19"}
                        .issubset(scan_items["alignment-sample"]),
                        scan_items["alignment-sample"])
        for slug in ("arxiv", "feature-machine-learning",
                     "principal-component-analysis", "k-nearest-neighbors",
                     "ell-1-norm", "l-1-regularization",
                     "x-1-2-transform", "r-plus",
                     "archaea", "hard-wrap-acronym", "adaboost",
                     "saccharomyces-cerevisiae", "historical-synonym",
                     "canonical-code-shapes"):
            self.assertEqual(scan_items.get(slug, set()), set())
        for slug in ("scalar-alias", "blank-alias", "missing-counterpart-acronym",
                     "synonym-parenthetical", "wrong-title-case",
                     "singular-parenthetical"):
            expected = ("item18" if slug in ("scalar-alias", "blank-alias")
                        else "item19")
            self.assertIn(expected, scan_items.get(slug, set()), scan_items.get(slug))
        self.assertNotIn("item17/alias-candidate",
                         scan_items.get("introduced-alias", set()))
        self.assertIn("item7", scan_items.get("two-sentence-description", set()))
        self.assertIn("item1", scan_items.get("malformed-flow-list", set()))
        self.assertIn("item9", scan_items.get("malformed-person-date", set()))
        self.assertIn("item16", scan_items.get("bare-code-shapes", set()))
        for slug in ("related-anchored", "related-wrong-label"):
            self.assertIn("item11", scan_items.get(slug, set()), scan_items.get(slug))
        self.assertNotIn("item10/dup",
                         scan_items.get("duplicate-link-forms", set()))
        # Local QC remains available with malformed alias metadata, but
        # cross-entry alias ownership is provisional. Repair those fixture
        # prerequisites before checking alias additions and canonicalization.
        for path, before, after in (
                (scalar_alias, 'aliases: "scalar-alias-name"',
                 'aliases: ["scalar-alias-name"]'),
                (blank_alias, "aliases:\n", "aliases: []\n"),
                (malformed_flow, 'aliases: ["one",, "two"]',
                 'aliases: ["one", "two"]')):
            path.write_text(path.read_text(encoding="utf-8").replace(before, after),
                            encoding="utf-8")
        repaired_scan = json.loads(self.run_script(
            "skills/wiki-lint/scripts/scan_vault.py", wiki, "--indent", "0").stdout)
        self.assertFalse(any("Alias inventory is incomplete" in row["message"]
                             for row in repaired_scan["problems"]))
        scan_items = {}
        for problem in repaired_scan["problems"]:
            scan_items.setdefault(problem["slug"], set()).add(problem["item"])
        self.assertIn("item17/alias-candidate",
                      scan_items.get("introduced-alias", set()))
        self.assertIn("10-duplicate-wikilink",
                      lint_items["duplicate-link-forms"])
        self.assertIn("item10/dup",
                      scan_items.get("duplicate-link-forms", set()))
        self.assertNotIn("10-duplicate-wikilink",
                         lint_items["ambiguous-path-links"])
        self.assertNotIn("item10/dup",
                         scan_items.get("ambiguous-path-links", set()))
        self.assertIn("item10/ambiguous",
                      scan_items.get("ambiguous-path-links", set()))

        index = json.loads(self.run_script(
            "skills/wiki-build/scripts/vault_index.py", wiki,
            "--source", "LeadingZero.pdf").stdout)
        self.assertNotIn("alignment-sample",
                         {match["slug"] for match in index["source_matches"]})
        self.assertTrue(any("alignment-sample.md: sources:" in problem
                            for problem in index["problems"]))

    def test_builder_and_linter_literal_contract_constants_stay_aligned(self):
        def literal(relative, name):
            tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"),
                             filename=relative)
            for node in tree.body:
                if not isinstance(node, ast.Assign):
                    continue
                if any(isinstance(target, ast.Name) and target.id == name
                       for target in node.targets):
                    return ast.literal_eval(node.value)
            self.fail(f"{relative} has no literal assignment for {name}")

        builder = "skills/wiki-build/scripts/lint_entry.py"
        linter = "skills/wiki-lint/scripts/scan_vault.py"
        self.assertEqual(literal(builder, "OBSIDIAN_KEYS"),
                         literal(linter, "OBSIDIAN_KEYS"))
        self.assertEqual(literal(builder, "TYPE_ENUM"),
                         literal(linter, "VALID_TYPES"))
        self.assertEqual(set(literal(builder, "TAG_ENUM")),
                         literal(linter, "VALID_TAGS"))
        self.assertEqual(
            literal(builder, "MANDATORY_KEYS"),
            [key for key in literal(linter, "CANON")
             if key not in ("aliases", "importance")])

    def test_builder_and_linter_share_equation_coverage_candidate(self):
        entry = self.vault / "Wiki/synthetic-deviation.md"
        equationless = '''---
title: "Synthetic deviation"
type: Concept
sources:
  - "[[Clean.pdf#page=1]]"
created: 2026-08-31
updated: 2026-08-31
description: "Synthetic deviation is a spread measure used by this alignment fixture."
tags:
  - "#statistics"
parents: []
read: false
---
**Synthetic deviation** measures the spread of a quantity $X$. Its value $\\sigma$ is the square root of the variance $\\operatorname{Var}(X)$.

**Related:**

---

## Flashcards

A spread measure derived from variance.
??
Synthetic deviation
'''
        entry.write_text(equationless, encoding="utf-8")

        builder = json.loads(self.run_script(
            "skills/wiki-build/scripts/lint_entry.py", entry,
            "--compact").stdout)
        builder_items = {finding["item"]
                         for finding in builder["entries"][0]["findings"]}
        self.assertIn("12-equation-coverage-candidate", builder_items)

        scanner = json.loads(self.run_script(
            "skills/wiki-lint/scripts/scan_vault.py", self.vault / "Wiki",
            "--indent", "0").stdout)
        scanner_items = {problem["item"] for problem in scanner["problems"]
                         if problem["slug"] == "synthetic-deviation"}
        self.assertIn("item12/equation-coverage-candidate", scanner_items)

        entry.write_text(equationless.replace(
            "$\\operatorname{Var}(X)$.\n",
            "$\\operatorname{Var}(X)$:\n\n$$\n"
            "\\sigma = \\sqrt{\\operatorname{Var}(X)}\n$$\n"),
            encoding="utf-8")
        builder = json.loads(self.run_script(
            "skills/wiki-build/scripts/lint_entry.py", entry,
            "--compact").stdout)
        self.assertNotIn(
            "12-equation-coverage-candidate",
            {finding["item"] for finding in builder["entries"][0]["findings"]})
        scanner = json.loads(self.run_script(
            "skills/wiki-lint/scripts/scan_vault.py", self.vault / "Wiki",
            "--indent", "0").stdout)
        self.assertNotIn(
            "item12/equation-coverage-candidate",
            {problem["item"] for problem in scanner["problems"]
             if problem["slug"] == "synthetic-deviation"})

        entry.write_text(equationless.replace(
            "$\\operatorname{Var}(X)$.\n",
            "$\\operatorname{Var}(X)$:\n\n$$\n"
            "f(x) = \\sqrt{x} + \\operatorname{Var}(Y)\n$$\n"),
            encoding="utf-8")
        builder = json.loads(self.run_script(
            "skills/wiki-build/scripts/lint_entry.py", entry,
            "--compact").stdout)
        self.assertIn(
            "12-equation-coverage-candidate",
            {finding["item"] for finding in builder["entries"][0]["findings"]})
        scanner = json.loads(self.run_script(
            "skills/wiki-lint/scripts/scan_vault.py", self.vault / "Wiki",
            "--indent", "0").stdout)
        self.assertIn(
            "item12/equation-coverage-candidate",
            {problem["item"] for problem in scanner["problems"]
             if problem["slug"] == "synthetic-deviation"})

        entry.write_text(equationless.replace(
            "$\\operatorname{Var}(X)$.\n",
            "$\\operatorname{Var}(X)$:\n\n$$\n"
            "\\sigma = \\sqrt{\\frac{1}{N}"
            "\\sum_i (x_i - \\mu)^2}\n$$\n"),
            encoding="utf-8")
        builder = json.loads(self.run_script(
            "skills/wiki-build/scripts/lint_entry.py", entry,
            "--compact").stdout)
        self.assertNotIn(
            "12-equation-coverage-candidate",
            {finding["item"] for finding in builder["entries"][0]["findings"]})
        scanner = json.loads(self.run_script(
            "skills/wiki-lint/scripts/scan_vault.py", self.vault / "Wiki",
            "--indent", "0").stdout)
        self.assertNotIn(
            "item12/equation-coverage-candidate",
            {problem["item"] for problem in scanner["problems"]
             if problem["slug"] == "synthetic-deviation"})


if __name__ == "__main__":
    unittest.main()
