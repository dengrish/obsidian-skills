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
import shlex
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


def coverage_journals(reports=(), queue_rows=()):
    """Visible version-2 journals; historical fixture reports remain unchanged."""
    anchors = ''.join(f'| [[Investments/{path.stem}]] | {digest(path)} |\n'
                      for path in reports)
    rows = ''.join('| ' + ' | '.join(row) + ' |\n' for row in queue_rows)
    return ('#### Coverage history\n\n| Report | SHA256 |\n| --- | --- |\n'
            + anchors + '\n#### Feed dispositions\n\n'
            '| Post | Fingerprint | Published | Disposition | Securities | Due | Reason |\n'
            '| --- | --- | --- | --- | --- | --- | --- |\n\n'
            '#### Research queue\n\n'
            '| Security | First seen | State | Priority | Due | Sources | Assessment | Reason |\n'
            '| --- | --- | --- | --- | --- | --- | --- | --- |\n'
            + rows + '\n')


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
                        "skills/stock-research/scripts/stock_coverage.py",
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

    def inspect_market_runtime(self, path):
        plugin = ROOT / "plugins/investments"
        script = "plugins/investments/shared/scripts/note_provenance.py"
        args = ("--plugin", plugin, "--skill", "stock-research")
        record = json.loads(self.run_script(script, "inspect", *args).stdout)
        return record, path

    def test_summary_ownership_honors_the_qualified_pdf_path(self):
        stem = "Doe_Qualified_2025"
        pdf = self.pdfs / (stem + ".pdf")
        doc = pymupdf.open()
        doc.new_page()
        doc.save(pdf)
        doc.close()
        note = self.notes / (stem + ".md")
        for origin, expected in (
                (f"Missing/{stem}.pdf", "collision"),
                (f"Sources/Other/{stem}.pdf", "collision"),
                (f"Sources/PDFs/{stem}.pdf", "done"),
                (f"PDFs/{stem}.pdf", "done"),
                (f"{stem}.pdf", "done")):
            with self.subTest(origin=origin):
                note.write_text(summary_note(stem).replace(
                    f'"[[{stem}.pdf]]"', f'"[[{origin}]]"'), encoding="utf-8")
                before = note.read_bytes()
                result = self.run_script(
                    "skills/paper-summarize/scripts/paper_scan.py",
                    "--src", pdf, "--notes", self.notes,
                    "--images", self.images, "--json")
                self.assertEqual(json.loads(result.stdout)["pdfs"][0]["status"], expected)
                self.assertEqual(note.read_bytes(), before)

    def test_backlog_frontmatter_literal_fence_never_becomes_a_request(self):
        queue = self.vault / "add-to-wiki.md"
        original = ("---\r\ndescription: |\r\n  ---\r\nlabels:\r\n"
                    "- Metadata only\r\n---\r\n- [ ] Real topic\r\n").encode()
        queue.write_bytes(original)
        snapshot = Path(self.scratch.name) / "queue.json"
        result = self.run_script("skills/wiki-add/scripts/backlog.py", "scan",
                                 queue, "--out", snapshot)
        report = json.loads(result.stdout)
        self.assertEqual([item["text"] for item in report["items"]], ["Real topic"])
        entry = self.vault / "Wiki/real-topic.md"
        entry.write_text("Real topic evidence.\n", encoding="utf-8")
        self.run_script("skills/wiki-add/scripts/backlog.py", "complete",
                        "--snapshot", snapshot, "--item", report["items"][0]["id"],
                        "--wiki", self.vault / "Wiki", "--entry", entry)
        self.assertEqual(queue.read_bytes(), original.replace(b"[ ]", b"[x]"))

    def test_backlog_reports_an_unindented_continuation_as_request_text(self):
        queue = self.vault / "add-to-wiki.md"
        queue.write_text("- [ ] Kalman filter\nParticle filter\n- [ ] Next\n",
                         encoding="utf-8")
        snapshot = Path(self.scratch.name) / "queue.json"
        report = json.loads(self.run_script(
            "skills/wiki-add/scripts/backlog.py", "scan", queue,
            "--out", snapshot).stdout)
        self.assertEqual([item["text"] for item in report["items"]],
                         ["Kalman filter", "Next"])
        self.assertEqual(report["items"][0]["context_lines"], ["Particle filter"])
        self.assertEqual(
            [(row["line"], row["reason"]) for row in report["report_only"]],
            [(2, "unindented line continues the request above")])

    def test_backlog_reports_text_that_is_not_a_pending_request(self):
        queue = self.vault / "add-to-wiki.md"
        for number, (text, rows) in enumerate((
                ("- [x] Done\nParticle filter\n",
                 [(2, "unindented line continues an item that is not a pending request")]),
                ("- [ ] A\n\nParticle filter\n",
                 [(3, "text outside a list item is not a request")]))):
            with self.subTest(text=text):
                queue.write_text(text, encoding="utf-8")
                snapshot = Path(self.scratch.name) / ("stray-%d.json" % number)
                report = json.loads(self.run_script(
                    "skills/wiki-add/scripts/backlog.py", "scan", queue,
                    "--out", snapshot).stdout)
                self.assertEqual(
                    [(row["line"], row["reason"]) for row in report["report_only"]], rows)
                self.assertEqual(report["counts"]["report_only"], 1)

    def test_backlog_reports_a_nested_open_task_before_and_after_completion(self):
        queue = self.vault / "add-to-wiki.md"
        queue.write_text("- [ ] Regularization\n  - [ ] Dropout\n", encoding="utf-8")
        helper = "skills/wiki-add/scripts/backlog.py"
        nested = [(2, "nested task is not a top-level request")]
        first = Path(self.scratch.name) / "nested-1.json"
        report = json.loads(self.run_script(helper, "scan", queue, "--out", first).stdout)
        self.assertEqual([(item["text"], item["context_lines"]) for item in report["items"]],
                         [("Regularization", ["  - [ ] Dropout"])])
        self.assertEqual(
            [(row["line"], row["reason"]) for row in report["report_only"]], nested)
        entry = self.vault / "Wiki/regularization.md"
        entry.write_text("Regularization evidence.\n", encoding="utf-8")
        self.run_script(helper, "complete", "--snapshot", first,
                        "--item", report["items"][0]["id"],
                        "--wiki", self.vault / "Wiki", "--entry", entry)
        second = Path(self.scratch.name) / "nested-2.json"
        rescan = json.loads(self.run_script(helper, "scan", queue, "--out", second).stdout)
        self.assertEqual((rescan["items"], rescan["counts"]["completed_skipped"]), ([], 1))
        self.assertEqual(
            [(row["line"], row["reason"]) for row in rescan["report_only"]], nested)

    def test_pdf_rename_does_not_claim_a_wrongly_qualified_article_origin(self):
        for folder in ("Missing", "Sources/Other"):
            with self.subTest(folder=folder):
                stem = "Doe_" + folder.replace("/", "") + "_2025"
                pdf = self.pdfs / (stem + ".pdf")
                self.make_pdf(pdf)
                note = self.notes / (stem + ".md")
                note.write_text(summary_note(stem).replace(
                    f'"[[{stem}.pdf]]"', f'"[[{folder}/{stem}.pdf]]"'), encoding="utf-8")
                new_stem = stem.replace("2025", "2026")
                self.run_script("skills/pdf-organize/scripts/organize.py", "rename",
                                pdf, "--vault", self.vault, "--to", new_stem + ".pdf", "--apply")
                self.assertTrue(note.is_file(), "an unproved owner must retain its pathname")
                self.assertFalse((self.notes / (new_stem + ".md")).exists())
                content = note.read_text(encoding="utf-8")
                self.assertIn(f'"[[{folder}/{stem}.pdf]]"', content)
                self.assertIn("published: 2025-01-01", content)
                # The article's ordinary bare citation does resolve to this
                # PDF, so it receives reference repair without ownership/date repair.
                self.assertIn(f"[[{new_stem}.pdf#page=1|1]]", content)

    def test_relative_and_shortest_pdf_origins_survive_rename_and_rescan(self):
        for prefix in ("Sources/PDFs/", "../Sources/PDFs/", "PDFs/"):
            with self.subTest(prefix=prefix):
                stem = "Doe_Path" + str(len(list(self.pdfs.iterdir()))) + "_2025"
                pdf = self.pdfs / (stem + ".pdf")
                self.make_pdf(pdf)
                note = self.notes / (stem + ".md")
                note.write_text(summary_note(stem).replace(
                    f'"[[{stem}.pdf]]"', f'"[[{prefix}{stem}.pdf]]"')
                    + f'\n[Other relative path](PDFs/{stem}.pdf)\n', encoding="utf-8")
                new_stem = stem.replace("2025", "2026")
                self.run_script("skills/pdf-organize/scripts/organize.py", "rename",
                                pdf, "--vault", self.vault, "--to", new_stem + ".pdf", "--apply")
                renamed = self.notes / (new_stem + ".md")
                self.assertFalse(note.exists())
                self.assertIn(f'"[[{prefix}{new_stem}.pdf]]"', renamed.read_text(encoding="utf-8"))
                self.assertIn(f'](PDFs/{stem}.pdf)', renamed.read_text(encoding="utf-8"))
                result = self.run_script("skills/paper-summarize/scripts/paper_scan.py",
                                         "--src", self.pdfs / (new_stem + ".pdf"),
                                         "--notes", self.notes, "--images", self.images, "--json")
                self.assertEqual(json.loads(result.stdout)["pdfs"][0]["status"], "done")

    def test_clipping_duplicates_keep_published_and_pending_owners_distinct(self):
        url = "https://example.com/existing"
        owner = self.notes / "Existing_2025.md"
        owner.write_text(f'---\nsources:\n  - "{url}"\n---\nCaptured body.\n',
                         encoding="utf-8")
        result = self.run_script("skills/clipping-clean/scripts/dedup_index.py",
                                 self.notes, "--url", url, "--url", url)
        rows = json.loads(result.stdout)["checked"]
        self.assertEqual([row["status"] for row in rows], ["duplicate", "duplicate"])
        self.assertEqual([row["matches"] for row in rows], [[str(owner)], [str(owner)]])
        pending = "https://example.com/pending"
        result = self.run_script("skills/clipping-clean/scripts/dedup_index.py",
                                 self.notes, "--url", pending, "--url", pending)
        self.assertEqual([row["status"] for row in json.loads(result.stdout)["checked"]],
                         ["new", "duplicate-of-earlier-input"])
        # A failed first capture publishes no owner. A fresh probe of the next
        # capture must therefore leave it eligible for processing.
        result = self.run_script("skills/clipping-clean/scripts/dedup_index.py",
                                 self.notes, "--url", pending)
        self.assertEqual(json.loads(result.stdout)["checked"][0]["status"], "new")

    def test_wiki_add_ownership_check_lists_copies_under_url_variants(self):
        # wiki-add cites the canonical address, while a clipping and a raw
        # capture keep the mobile or http address they were saved under.
        note = self.notes / "X_Wiki_2026.md"
        note.write_text('---\nsources:\n  - "https://en.m.wikipedia.org/wiki/X'
                        '?utm_source=y"\n---\nCaptured body.\n', encoding="utf-8")
        raw = self.vault / "Inbox/y-capture.md"
        raw.write_text('---\nsource: "http://en.m.wikipedia.org/wiki/Y"\n---\nRaw.\n',
                       encoding="utf-8")
        result = self.run_script(
            "skills/clipping-clean/scripts/dedup_index.py", self.notes,
            "--raw", self.vault / "Inbox",
            "--url", "https://en.wikipedia.org/wiki/X",
            "--url", "https://en.wikipedia.org/wiki/Y")
        rows = json.loads(result.stdout)["checked"]
        self.assertEqual([(row["id"], row["status"], row["variant_matches"]) for row in rows],
                         [(str(raw), "new", []),
                          ("https://en.wikipedia.org/wiki/X", "new", [str(note)]),
                          ("https://en.wikipedia.org/wiki/Y", "new", [str(raw)])])

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
        # The real publication path refuses a superficially complete report
        # that silently omits a collected source and its two stock ideas.
        draft.write_text(body, encoding="utf-8")
        _, incomplete = self.inspect_market_runtime(draft)
        refused = self.run_script(daily_helper, "publish", incomplete, "--vault", self.vault,
                                 "--run-receipt", prepared["run_receipt"], expected=2)
        self.assertIn('needs a disposition: 101', refused.stdout)
        planner = json.loads(self.run_script("skills/stock-research/scripts/stock_coverage.py",
                            "context", "--vault", self.vault, "--as-of", prepared['as_of']).stdout)
        nomination = planner['new_or_changed_posts'][0]
        body = body.replace('| --- | --- | --- | --- | --- | --- | --- |\n',
            '| --- | --- | --- | --- | --- | --- | --- |\n'
            f"| {nomination['source_url']} | {nomination['fingerprint']} | {nomination['published']} | "
            'nominated | NASDAQ:EXAMPLE, NASDAQ:OTHER | - | Two synthetic user-visible arguments. |\n', 1)
        due = (cutoff + timedelta(days=1)).isoformat()
        edition = prepared['date'] + '-' + cutoff.strftime('%H%M%S') + '-stock-research'
        queue = ''.join(
            f'| NASDAQ:{ticker} | {prepared["as_of"]} | assessed | new | {due if ticker == "EXAMPLE" else "-"} | '
            f'101 | [[Investments/{edition}#NASDAQ:{ticker} — {company}]] | Synthetic assessment completed. |\n'
            for ticker, company in (("EXAMPLE", "Example Inc."), ("OTHER", "Other Inc.")))
        body = body.replace('| --- | --- | --- | --- | --- | --- | --- | --- |\n',
                            '| --- | --- | --- | --- | --- | --- | --- | --- |\n' + queue, 1)
        draft.write_text(body, encoding="utf-8")
        producer, final_draft = self.inspect_market_runtime(draft)
        self.run_script(daily_helper, "review-complete", "--vault", self.vault,
                        "--run-receipt", prepared["run_receipt"], "--draft", final_draft, "--check", "final-review")
        publication = json.loads(self.run_script(daily_helper, "publish", final_draft,
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
            self.assertNotIn("skill-provenance", content)
            receipt = json.loads((folder / ".stock-research/dossiers" / (path.stem + ".json")).read_bytes())
            self.assertEqual(receipt["committed"]["provenance"]["generated_by"], producer)
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
        # A late scheduled run can legitimately follow today's close. Use a
        # genuinely future observation to exercise the cutoff guard at any hour.
        draft.write_text(daily(today, None, review).replace(stamp(target_day, 16), stamp(today + timedelta(days=1), 16)),
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
        draft.write_text(draft.read_text(encoding="utf-8")
                         .replace('stock_research: 1', 'stock_research: 2')
                         .replace('### Candidate assessments',
                                  coverage_journals((first, update, previous_month))
                                  + '### Candidate assessments'), encoding="utf-8")
        _, draft = self.inspect_market_runtime(draft)
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
        current = current.replace('### Thesis updates',
            '#### NASDAQ:NEW — New Inc.\n\nStatus: watch\n\n'
            '[[Investments/Stocks/NEW]]\n\nSynthetic assessment of an explicit user-requested '
            'idea; no real investment recommendation.\n\n### Thesis updates')
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
        self.assertIn("stock_research: 2", missing.stdout)
        self.assertFalse(target.exists())
        due = (datetime.fromisoformat(initial['as_of']) + timedelta(days=1)).isoformat()
        rows = (
            ('NASDAQ:EXAMPLE', prior_time, 'assessed', 'active', due,
             f'legacy:{prior.name}',
             f'[[Investments/{target.stem}#NASDAQ:EXAMPLE — Example Inc.]]',
             'Synthetic continued assessment; relevant facts checked at the cutoff.'),
            ('NASDAQ:NEW', initial['as_of'], 'assessed', 'new', due, 'user',
             f'[[Investments/{target.stem}#NASDAQ:NEW — New Inc.]]',
             'Synthetic initial assessment of a user-requested idea.'))
        draft.write_text(current.replace('stock_research: 1', 'stock_research: 2')
                         .replace('### Candidate assessments',
                                  coverage_journals((prior,), rows)
                                  + '### Candidate assessments'), encoding="utf-8")
        generator, draft = self.inspect_market_runtime(draft)
        linted = json.loads(self.run_script(script, "lint", draft).stdout)
        self.assertIsNone(linted["provenance"])
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

    def test_paper_note_lint_reads_display_math_through_the_shared_floor(self):
        # The installed command resolves equation_coverage.py from the shared
        # layer: two equations on one display line are an advisory, and an
        # absolute value inside a display is math, not a table.
        note = self.notes / "Doe_Correction_2025.md"
        cited = "entries.<sup>[[Doe_Correction_2025.pdf#page=1|1]]</sup>"
        note.write_text(notice_note("Doe_Correction_2025").replace(
            cited, cited + "\n\n$$\nd_1 = 1.5, \\qquad d_2 = 3.7\n$$\n\n"
            "Each value is a corrected dose.\n\n$$\n|d_1 - d_2| = 2.2\n$$\n\n"
            "The bars give the size of the gap."),
            encoding="utf-8", newline="\n")
        result = self.run_script(
            "skills/paper-summarize/scripts/note_lint.py", note,
            "--mode", "notice")
        self.assertIn("advisory: a display line holds more than one equation",
                      result.stdout)
        self.assertIn("1 advisory(s)", result.stdout)
        self.assertNotIn("violation", result.stdout.replace(
            "no violations", ""))

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

    def test_extended_data_switch_moves_links_to_the_crops_it_moves(self):
        # A default run folds Extended Data into _fig_S<N>, and a summary
        # embeds those crops. The printed switch moves each Extended Data
        # figure to _fig_ED<N> and, in the same run, every link with it, so
        # no embed starts showing the Supplementary figure.
        batch = "skills/figure-extract/scripts/batch_extract.py"
        pdf = self.pdfs / "Doe_Nature_2025.pdf"
        with pymupdf.open() as doc:
            for caption, fill in (("Figure 1. Main.", (0.5, 0.5, 0)),
                                  ("Extended Data Figure 1. First.", (1, 0, 0)),
                                  ("Extended Data Figure 2. Second.", (0, 0.6, 0)),
                                  ("Supplementary Figure 1. Third.", (0, 0, 1))):
                page = doc.new_page(width=612, height=792)
                page.draw_rect((100, 200, 500, 400), fill=fill)
                page.insert_text((100, 430), caption, fontsize=9)
            doc.save(pdf)
        default = self.run_script(batch, "--src", pdf, "--out", self.images,
                                  "--dpi", 72, expected=1)
        switch = [line.strip() for line in default.stdout.splitlines()
                  if "--ed-prefix ED" in line
                  and "--overwrite-supplementary" in line]
        self.assertEqual(len(switch), 1, default.stdout)
        s1 = self.images / "Doe_Nature_2025_fig_S1.png"
        extended_data = digest(s1)
        note = self.notes / "Doe_Nature_2025.md"
        body = summary_note(pdf.stem).replace(
            "![[Doe_Nature_2025_fig_1.png]]",
            "![[Doe_Nature_2025_fig_S1.png]]\n\n![[Doe_Nature_2025_fig_S2.png]]")
        note.write_text(body, encoding="utf-8", newline="\n")
        entry = self.vault / "Wiki/Control.md"
        entry.write_text("See ![[Sources/Images/Doe_Nature_2025_fig_S1.png|400]].\n",
                         encoding="utf-8")

        self.run_script(batch, *shlex.split(switch[0])[2:])
        self.assertEqual(digest(self.images / "Doe_Nature_2025_fig_ED1.png"),
                         extended_data)
        self.assertNotEqual(digest(s1), extended_data)
        self.assertEqual(note.read_text(encoding="utf-8"), body.replace(
            "_fig_S1.png", "_fig_ED1.png").replace("_fig_S2.png", "_fig_ED2.png"))
        self.assertEqual(entry.read_text(encoding="utf-8"),
                         "See ![[Sources/Images/Doe_Nature_2025_fig_ED1.png|400]].\n")
        check = self.run_script("skills/pdf-organize/scripts/organize.py", "check",
                                "--vault", self.vault, pdf, expected=1)
        cited = [line for line in check.stdout.splitlines() if "cites:" in line]
        self.assertTrue(cited, check.stdout)
        self.assertFalse(any("_fig_S1.png" in line or "_fig_S2.png" in line
                             for line in cited), check.stdout)

    def test_extended_data_switch_without_a_supplementary_collision(self):
        # With no Supplementary figure the summary prints no rerun, yet the
        # documented switch still moves the crop and its links.
        batch = "skills/figure-extract/scripts/batch_extract.py"
        pdf = self.pdfs / "Doe_Widgets_2025.pdf"
        with pymupdf.open() as doc:
            for caption, fill in (("Figure 1. Main.", (0.5, 0.5, 0)),
                                  ("Extended Data Figure 1. First.", (1, 0, 0))):
                page = doc.new_page(width=612, height=792)
                page.draw_rect((100, 200, 500, 400), fill=fill)
                page.insert_text((100, 430), caption, fontsize=9)
            doc.save(pdf)
        default = self.run_script(batch, "--src", pdf, "--out", self.images,
                                  "--dpi", 72)
        self.assertNotIn("--ed-prefix ED", default.stdout)
        s1 = self.images / "Doe_Widgets_2025_fig_S1.png"
        extended_data = digest(s1)
        note = self.notes / "Doe_Widgets_2025.md"
        body = summary_note(pdf.stem).replace(
            "![[Doe_Widgets_2025_fig_1.png]]", "![[Doe_Widgets_2025_fig_S1.png]]")
        note.write_text(body, encoding="utf-8", newline="\n")

        switch = self.run_script(batch, "--src", pdf, "--out", self.images,
                                 "--dpi", 72, "--ed-prefix", "ED",
                                 "--overwrite-supplementary")
        self.assertEqual(digest(self.images / "Doe_Widgets_2025_fig_ED1.png"),
                         extended_data)
        self.assertEqual(note.read_text(encoding="utf-8"),
                         body.replace("_fig_S1.png", "_fig_ED1.png"))
        leftovers = switch.stdout.partition("Leftover _fig_S<N> crops")[2]
        self.assertIn("Doe_Widgets_2025_fig_S1.png", leftovers, switch.stdout)

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
        self.assertIn("2025-03-14 -> 2026-01-01", planned.stdout)
        self.assertTrue(source.is_file())
        self.assertIn("published: 2025-03-14", note.read_text(encoding="utf-8"))

        self.run_script(
            organizer, "rename", "--vault", self.vault, source,
            "--to", "Doe_Correction_2026.pdf", "--apply")
        source = self.pdfs / "Doe_Correction_2026.pdf"
        note = self.notes / "Doe_Correction_2026.md"
        body = note.read_text(encoding="utf-8")
        self.assertIn(
            "published: 2026-01-01 # date printed by the document", body)
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

    def test_canvas_board_follows_filing_and_rename_of_a_pdf_family(self):
        organizer = "skills/pdf-organize/scripts/organize.py"
        source = self.vault / "Inbox/download.pdf"
        self.make_pdf(source)
        board = self.vault / "Boards/reading.canvas"
        board.parent.mkdir()

        def write_board(nodes):
            board.write_text(json.dumps({"nodes": nodes, "edges": []},
                                        indent="\t"), encoding="utf-8")

        def card(node_id, path):
            return {"id": node_id, "type": "file", "file": path,
                    "x": 0, "y": 0, "width": 400, "height": 400}

        def text_card(text):
            return {"id": "t", "type": "text", "text": text,
                    "x": 0, "y": 0, "width": 400, "height": 100}

        write_board([card("p", "Inbox/download.pdf"),
                     text_card("Read [[download.pdf]] first.")])
        checked = self.run_script(organizer, "check", source,
                                  "--vault", self.vault, expected=1)
        self.assertIn(str(Path("Boards") / "reading.canvas"), checked.stdout)
        filed = self.run_script(organizer, "rename", "--vault", self.vault,
                                source, "--to", "Doe_Board_2025.pdf",
                                "--dest", self.pdfs, "--apply")
        self.assertIn("Verified: no canvas card points at any of the 1 old "
                      "path(s).", filed.stdout)
        nodes = json.loads(board.read_text(encoding="utf-8"))["nodes"]
        self.assertEqual(nodes[0]["file"], "Sources/PDFs/Doe_Board_2025.pdf")
        self.assertEqual(nodes[1]["text"], "Read [[Doe_Board_2025.pdf]] first.")

        # The figure and the reading note made from the filed PDF go on the
        # same board, and a later rename carries all three cards.
        pdf = self.pdfs / "Doe_Board_2025.pdf"
        self.run_script("skills/figure-extract/scripts/batch_extract.py",
                        "--src", pdf, "--out", self.images, "--dpi", 72)
        (self.notes / "Doe_Board_2025.md").write_text(
            summary_note("Doe_Board_2025"), encoding="utf-8", newline="\n")
        write_board([card("p", "Sources/PDFs/Doe_Board_2025.pdf"),
                     card("f", "Sources/Images/Doe_Board_2025_fig_1.png"),
                     card("n", "Articles/Doe_Board_2025.md"),
                     text_card("See ![[Doe_Board_2025_fig_1.png]].")])
        renamed = self.run_script(organizer, "rename", "--vault", self.vault,
                                  pdf, "--to", "Doe_Renamed_2025.pdf", "--apply")
        self.assertIn("Verified: no note or canvas cites any of the",
                      renamed.stdout)
        nodes = json.loads(board.read_text(encoding="utf-8"))["nodes"]
        self.assertEqual([node.get("file") for node in nodes[:3]],
                         ["Sources/PDFs/Doe_Renamed_2025.pdf",
                          "Sources/Images/Doe_Renamed_2025_fig_1.png",
                          "Articles/Doe_Renamed_2025.md"])
        for node in nodes[:3]:
            self.assertTrue((self.vault / node["file"]).is_file(), node)
        self.assertEqual(nodes[3]["text"],
                         "See ![[Doe_Renamed_2025_fig_1.png]].")

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
        split_args = ("skills/pdf-organize/scripts/organize.py", "split", book,
                      "--chapters", chapter_plan, "--out", chapter_dir,
                      "--vault", self.vault)
        plan = self.run_script(*split_args)
        self.assertIn("Plan only", plan.stdout)
        self.assertFalse(chapter_dir.exists())
        self.run_script(*split_args, "--apply")
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

        # A split book's figures are its chapters' figures: the named book
        # lists the chapter crops and extracts over its chapter folder only.
        named = json.loads(self.run_script(
            "skills/paper-summarize/scripts/paper_scan.py",
            "--src", book, "--notes", self.notes,
            "--images", self.images, "--json").stdout)["pdfs"][0]
        self.assertEqual(named["status"], "new")
        self.assertEqual(named["figures"], [])
        self.assertEqual([Path(path).name for path in named["split_book_chapters"]],
                         [path.name for path in chapter_paths])
        self.assertIn("Doe_SynthBook_2025_01_FirstTopic_fig_1.png",
                      [figure["file"] for figure in named["chapter_figures"]])
        # A re-crop of the named book's figure is refused for its chapters.
        refused = self.run_script(
            "skills/figure-extract/scripts/extract_figures.py", book,
            "--out", self.images, "--crop", "2:2:100,150,500,350",
            "--dpi", 72, expected=1)
        self.assertIn("is a split book", refused.stderr)
        self.run_script("skills/figure-extract/scripts/batch_extract.py",
                        "--src", chapter_dir, "--out", self.images,
                        "--dpi", 72)
        names = [path.name.casefold() for path in self.images.iterdir()]
        self.assertTrue(any(name.startswith("doe_synthbook_2025_02_secondtopic_fig")
                            for name in names), names)
        self.assertFalse(any(name.startswith("doe_synthbook_2025_fig")
                             for name in names), names)
        draft = Path(self.scratch.name) / "Doe_SynthBook_2025.md"
        draft.write_text(summary_note(book.stem).replace(
            "![[Doe_SynthBook_2025_fig_1.png]]",
            "![[Doe_SynthBook_2025_01_FirstTopic_fig_1.png]]"),
            encoding="utf-8", newline="\n")
        self.run_script("skills/paper-summarize/scripts/note_lint.py", draft,
                        "--mode", "empirical", "--images", self.images)

    def test_split_book_representations_rename_together(self):
        # Both copies of a split book pair with one chapter set: renaming one
        # copy carries the other, so the scanner and extractor still skip both.
        plain = self.pdfs / "Doe_Book_2020.pdf"
        scan = self.pdfs / "Doe_Book_2020_src.pdf"
        chapter = self.pdfs / "Doe_Book_2020" / "Doe_Book_2020_01_Intro.pdf"
        chapter.parent.mkdir()
        for path in (plain, scan, chapter):
            self.make_pdf(path)
        self.run_script("skills/pdf-organize/scripts/organize.py", "rename",
                        "--vault", self.vault, scan,
                        "--to", "Doe_Scan_2020_src.pdf", "--apply")
        self.assertEqual(sorted(path.name for path in self.pdfs.iterdir()),
                         ["Doe_Scan_2020", "Doe_Scan_2020.pdf",
                          "Doe_Scan_2020_src.pdf"])
        sweep = self.scan_papers()
        self.assertEqual((sweep["counts"]["book"], sweep["counts"]["chapter"]),
                         (2, 1))
        self.run_script("skills/figure-extract/scripts/batch_extract.py",
                        "--src", self.pdfs, "--out", self.images, "--dpi", 72)
        crops = [path.name for path in self.images.iterdir()
                 if path.suffix == ".png"]
        self.assertTrue(crops)
        self.assertTrue(all(name.startswith("Doe_Scan_2020_01_Intro_fig")
                            for name in crops), crops)

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
        refused = self.run_script(batch, "--src", self.pdfs, "--out", self.images,
                                  "--dpi", 72, expected=1)
        self.assertEqual(list(self.images.iterdir()), [])
        self.assertEqual({path: digest(path) for path in sources}, original)
        # Both remedies say a later pdf-organize rename carries the figures.
        human = self.run_script(
            "skills/paper-summarize/scripts/paper_scan.py", "--src", self.pdfs,
            "--notes", self.notes, "--images", self.images)
        for output in (refused.stdout, human.stdout):
            self.assertIn("pdf-organize", output)
            self.assertIn("carries", output)
            self.assertNotIn("orphan", output)

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

    def test_unorganized_extraction_moves_with_a_later_pdf_organize_rename(self):
        organizer = "skills/pdf-organize/scripts/organize.py"
        batch = "skills/figure-extract/scripts/batch_extract.py"
        source = self.pdfs / "download.pdf"
        self.make_pdf(source)
        self.run_script(batch, "--src", source, "--out", self.images,
                        "--dpi", 72, "--allow-unorganized")
        figure = self.images / "download_fig_1.png"
        extracted = digest(figure)
        note = self.notes / "download.md"
        note.write_text(summary_note("download"), encoding="utf-8", newline="\n")
        entry = self.vault / "Wiki/rectangle.md"
        entry.write_text("![[download_fig_1.png]]\n", encoding="utf-8")

        self.run_script(organizer, "rename", "--vault", self.vault, source,
                        "--to", "Doe_Drawing_2025.pdf", "--apply")
        renamed_figure = self.images / "Doe_Drawing_2025_fig_1.png"
        self.assertFalse(figure.exists())
        self.assertEqual(digest(renamed_figure), extracted)
        manifest = (self.images / ".figure-manifest.tsv").read_text(encoding="utf-8")
        self.assertIn("Doe_Drawing_2025_fig_1.png", manifest)
        self.assertNotIn("download_fig", manifest)
        self.assertFalse(note.exists())
        self.assertEqual(
            (self.notes / "Doe_Drawing_2025.md").read_text(encoding="utf-8"),
            summary_note("Doe_Drawing_2025"))
        self.assertEqual(entry.read_text(encoding="utf-8"),
                         "![[Doe_Drawing_2025_fig_1.png]]\n")

    def test_legacy_crop_of_an_unorganized_pdf_is_adopted_before_its_rename(self):
        organizer = "skills/pdf-organize/scripts/organize.py"
        batch = "skills/figure-extract/scripts/batch_extract.py"
        source = self.pdfs / "Smith2020.pdf"
        self.make_pdf(source)
        # A crop from before ownership records existed: real extractor bytes
        # with no manifest line.
        legacy_run = Path(self.scratch.name) / "legacy-run"
        self.run_script(batch, "--src", source, "--out", legacy_run,
                        "--dpi", 72, "--allow-unorganized")
        legacy = self.images / "Smith2020_fig_1.png"
        legacy.write_bytes((legacy_run / legacy.name).read_bytes())
        original = digest(legacy)
        entry = self.vault / "Wiki/rectangle.md"
        entry.write_text("![[Smith2020_fig_1.png]]\n", encoding="utf-8")

        blocked = self.run_script(organizer, "rename", "--vault", self.vault, source,
                                  "--to", "Smith_Study_2020.pdf", "--apply",
                                  expected=1)
        self.assertIn("--adopt-legacy 'Smith2020:<label>'", blocked.stdout)
        self.assertTrue(source.is_file())

        plain = self.run_script(batch, "--src", source, "--out", self.images,
                                "--dpi", 72, expected=1)
        self.assertIn("Run pdf-organize on these first", plain.stdout)
        adopted = self.run_script(batch, "--src", source, "--out", self.images,
                                  "--dpi", 72, "--adopt-legacy", "Smith2020:1")
        self.assertIn("Adoption recorded; nothing was extracted.", adopted.stdout)
        self.assertEqual(sorted(path.name for path in self.images.glob("*.png")),
                         [legacy.name])

        self.run_script(organizer, "rename", "--vault", self.vault, source,
                        "--to", "Smith_Study_2020.pdf", "--apply")
        renamed = self.images / "Smith_Study_2020_fig_1.png"
        self.assertFalse(legacy.exists())
        self.assertEqual(digest(renamed), original)
        self.assertEqual(entry.read_text(encoding="utf-8"),
                         "![[Smith_Study_2020_fig_1.png]]\n")

    def test_legacy_crop_of_a_split_book_is_adopted_before_its_rename(self):
        organizer = "skills/pdf-organize/scripts/organize.py"
        batch = "skills/figure-extract/scripts/batch_extract.py"
        book = self.pdfs / "Doe_Book_2025.pdf"
        chapter = self.pdfs / "Doe_Book_2025" / "Doe_Book_2025_01_Intro.pdf"
        chapter.parent.mkdir()
        for path in (book, chapter):
            self.make_pdf(path)
        # Whole-book and chapter crops from before ownership records existed,
        # with no manifest line. Each is adopted under its own PDF's stem.
        legacy_run = Path(self.scratch.name) / "legacy-run"
        originals = {}
        for path in (book, chapter):
            self.run_script(batch, "--src", path, "--out", legacy_run,
                            "--dpi", 72)
            legacy = self.images / (path.stem + "_fig_1.png")
            legacy.write_bytes((legacy_run / legacy.name).read_bytes())
            originals[path] = digest(legacy)

        blocked = self.run_script(organizer, "rename", "--vault", self.vault, book,
                                  "--to", "Doe_Volume_2025.pdf", "--apply",
                                  expected=1)
        for path in (book, chapter):
            self.assertIn("--src %s --out %s --adopt-legacy '%s:<label>'"
                          % (shlex.quote(str(path)), shlex.quote(str(self.images)),
                             path.stem), blocked.stdout)
            adopted = self.run_script(batch, "--src", path, "--out", self.images,
                                      "--dpi", 72, "--adopt-legacy",
                                      path.stem + ":1")
            if path == book:
                self.assertIn("Adoption recorded; nothing was extracted.",
                              adopted.stdout)
        manifest = (self.images / ".figure-manifest.tsv").read_text(
            encoding="utf-8")
        self.assertIn("Doe_Book_2025_fig_1.png\t", manifest)
        self.assertIn("Doe_Book_2025_01_Intro_fig_1.png\t", manifest)
        self.assertEqual(sorted(path.name for path in self.images.glob("*.png")),
                         ["Doe_Book_2025_01_Intro_fig_1.png",
                          "Doe_Book_2025_fig_1.png"])

        self.run_script(organizer, "rename", "--vault", self.vault, book,
                        "--to", "Doe_Volume_2025.pdf", "--apply")
        self.assertEqual(sorted(path.name for path in self.images.glob("*.png")),
                         ["Doe_Volume_2025_01_Intro_fig_1.png",
                          "Doe_Volume_2025_fig_1.png"])
        self.assertEqual(digest(self.images / "Doe_Volume_2025_fig_1.png"),
                         originals[book])
        self.assertEqual(digest(self.images / "Doe_Volume_2025_01_Intro_fig_1.png"),
                         originals[chapter])
        self.assertTrue((self.pdfs / "Doe_Volume_2025"
                         / "Doe_Volume_2025_01_Intro.pdf").is_file())

    def test_errata_pdf_in_a_chapter_folder_is_renamed_where_it_stands(self):
        # pdf-organize skips only canonical chapters in a book folder, so the
        # sweep's "run pdf-organize" remedy for an errata PDF there works.
        organizer = "skills/pdf-organize/scripts/organize.py"
        batch = "skills/figure-extract/scripts/batch_extract.py"
        folder = self.pdfs / "Doe_Book_2025"
        folder.mkdir()
        book = self.pdfs / "Doe_Book_2025.pdf"
        errata = folder / "errata.pdf"
        for path in (book, folder / "Doe_Book_2025_01_Intro.pdf",
                     folder / "Doe_Book_2025_02_Methods.pdf", errata):
            self.make_pdf(path)
        sweep = ("--src", self.pdfs, "--out", self.images, "--dpi", 72)
        refused = self.run_script(batch, *sweep, expected=1)
        self.assertIn("Run pdf-organize on these first", refused.stdout)
        self.assertIn(str(errata), refused.stdout)

        self.run_script(organizer, "rename", "--vault", self.vault, errata,
                        "--to", "Doe_BookErrata_2025.pdf", "--apply")
        renamed = folder / "Doe_BookErrata_2025.pdf"
        self.assertTrue(renamed.is_file())
        self.run_script(batch, *sweep)
        self.assertEqual(self.scan_papers()["counts"]["unorganized"], 0)
        plan = self.run_script(organizer, "rename", "--vault", self.vault, book,
                               "--to", "Doe_Volume_2025.pdf")
        self.assertIn("Moved with the chapter folder, names unchanged (1):\n"
                      "  %s" % renamed, plan.stdout)

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
        # reference follows the rename, never the clipping path.
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
        moc_dependency = self.vault / "MOCs/biology-moc.md"
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
        # The reprocess request authorizes the repair phase, which rewrites
        # every dependent; the old copies may then be retired.
        self.run_script(fetch, *rename, "--phase", "repair")
        self.assertEqual(
            external.read_text(encoding="utf-8"),
            'The HTML opener is `<!--`.\n\n'
            f'[[{new}|the clipping]]\n![[Sources/Images/{new}_fig_1.png]]\n'
            '\nThe closer is `-->`.\n')
        self.assertEqual(
            moc_dependency.read_text(encoding="utf-8"),
            f'# Supporting sources\n[[{new}|the clipping]]\n'
            f'![[Sources/Images/{new}_fig_1.png]]\n')
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

    def test_clipping_changed_slug_repairs_every_dependent_before_retirement(self):
        fetch = "skills/clipping-clean/scripts/fetch_images.py"
        old, new = "Smith_Cell_Signals_2026", "Smith_Cell_Receptors_2026"
        old_image, new_image = old + "_fig_1.png", new + "_fig_1.png"
        note = self.notes / (old + ".md")
        metadata = {"title": "Cell signals", "format": "Article",
                    "sources": ["https://example.org/study"], "read": True}
        # The user's block ID carries into the redraft, so a block link to
        # the old note still resolves after the rename.
        body = ('---\n' + yaml.safe_dump(metadata, sort_keys=False) + '---\n'
                + f'![[{old_image}]]\n*The cells exchange signals.*\n\n'
                + 'Cells answer a ligand within seconds. ^fast-answer\n')
        note.write_text(body, encoding="utf-8")
        rendered = Path(self.scratch.name) / "browser render.png"
        Image.new("RGB", (64, 48), (20, 100, 180)).save(rendered)
        self.run_script(fetch, "place", "--attachments", self.images,
                        "--slug", old, "--index", 1, "--from-file", rendered,
                        "--owner-note", note)
        original = digest(self.images / old_image)
        os.chmod(note, 0o640)
        snapshots = Path(self.scratch.name) / "clipping-snapshots.json"
        self.run_script("shared/scripts/publish_files.py", "snapshot",
                        "--vault", self.vault, "-o", snapshots,
                        f"Articles/{old}.md", f"Articles/{new}.md")
        snap_bytes = snapshots.read_bytes()
        new_note = self.notes / (new + ".md")

        # Step 4 publishes the reviewed scratch draft with the shipped writer.
        draft = Path(self.scratch.name) / "draft.md"
        draft.write_text(body.replace(old, new), encoding="utf-8")
        publish = ["rename", "--phase", "publish-note", "--vault", self.vault,
                   "--snapshots", snapshots, "--draft", draft,
                   "--owner-note", note, "--new-owner-note", new_note,
                   "--old-slug", old, "--new-slug", new]
        planned = json.loads(self.run_script(fetch, *publish, "--dry-run").stdout)
        self.assertEqual(planned["action"], "would-create")
        self.assertFalse(new_note.exists())
        created = json.loads(self.run_script(fetch, *publish).stdout)
        self.assertEqual(created["action"], "created")
        self.assertEqual(new_note.read_bytes(), draft.read_bytes())
        self.assertEqual(new_note.stat().st_mode & 0o777, 0o640)
        self.assertEqual(snapshots.read_bytes(), snap_bytes)
        self.assertFalse([path.name for folder in (self.vault, self.notes)
                          for path in folder.iterdir()
                          if path.name.startswith(".clipping-note-")])
        # The hidden record names the old note: the pair reads the same both
        # ways.
        handoff = self.notes / f".{new}.handoff.json"
        self.assertEqual(created["handoff_record"], f"Articles/{handoff.name}")
        self.assertEqual(json.loads(handoff.read_text(encoding="utf-8")),
                         {"old_note": f"Articles/{old}.md",
                          "new_note": f"Articles/{new}.md"})
        recorded = json.loads(self.run_script(
            "shared/scripts/publish_files.py", "snapshot", "--vault",
            self.vault, "-o", snapshots, "--replace",
            f"Articles/{new}.md", f"Articles/{handoff.name}").stdout)
        self.assertEqual(recorded["snapshots"][0]["digest"], created["sha256"])

        # Real dependents in every scanned area. Labels, anchors, sizes, a
        # code span and a name that only shares the old prefix must survive.
        wiki = self.vault / "Wiki/cell-signaling.md"
        wiki_text = '''---
title: "Cell signaling"
type: Concept
sources:
  - "[[{slug}.md]]"
created: 2026-08-30
updated: 2026-09-02
description: "Cell signaling transmits information between cells through chemical messages."
tags:
  - "#biology"
parents: []
read: true
issues: ""
---
**Cell signaling** transmits information between cells through chemical messages.

![[{slug}_fig_1.png]]
*Cells exchange signals.*

**Related:**
'''
        wiki.write_text(wiki_text.format(slug=old), encoding="utf-8")
        moc = self.vault / "MOCs/biology-moc.md"
        moc.parent.mkdir()
        moc_text = ('- [[Articles/{slug}|Cell signals]]\n'
                    f'- [[{old}_Supplement]]\n')
        moc.write_text(moc_text.format(slug=old), encoding="utf-8")
        investment = self.vault / "Investments/Research notes.md"
        investment.parent.mkdir()
        investment_text = ('Receptor platforms matter for the thesis.\n\n'
                           '![[{image}|300]]\n')
        investment.write_text(investment_text.format(image=old_image),
                              encoding="utf-8")
        log = self.vault / "Reviews/clipping-clean-suggestions.md"
        log.parent.mkdir()
        log_text = (
            '## Open\n\n### [caption-lost] Caption lost on reprocess\n\n'
            '- **Issue:** The first caption was dropped.\n'
            '- **Evidence:** [Cell signals](../Articles/{slug}.md) lost the '
            f'caption below `![[{old_image}]]`.\n'
            '- **Reported by:** clipping-clean\n\n## Fixed\n\n'
            'No fixed suggestions.\n')
        log.write_text(log_text.format(slug=old), encoding="utf-8")
        other = self.notes / "Other_Clipping_2026.md"
        other_text = ('---\ntitle: "Other"\n---\n'
                      'Related: [[{slug}#^fast-answer|fast answers]]\n')
        other.write_text(other_text.format(slug=old), encoding="utf-8")
        # A vault folder link to notes stored outside the vault.
        linked = Path(self.scratch.name) / "linked notes"
        linked.mkdir()
        (self.vault / "Shared notes").symlink_to(linked, target_is_directory=True)
        shared = self.vault / "Shared notes/reading.md"
        shared_text = 'Shared reading: [[{slug}|the study]].\n'
        shared.write_text(shared_text.format(slug=old), encoding="utf-8")
        # A raw capture's link is respelled too; its URL stays.
        raw = self.vault / "Inbox/follow-up.md"
        raw_text = ('---\nsource: "https://example.org/other"\n---\n'
                    'Responds to [[{slug}]].\n')
        raw.write_text(raw_text.format(slug=old), encoding="utf-8")
        dependents = {wiki: wiki_text.format(slug=new),
                      moc: moc_text.format(slug=new),
                      investment: investment_text.format(image=new_image),
                      log: log_text.format(slug=new),
                      other: other_text.format(slug=new),
                      shared: shared_text.format(slug=new),
                      raw: raw_text.format(slug=new)}
        rename = ["rename", "--attachments", self.images, "--sources", self.pdfs,
                  "--owner-note", note, "--new-owner-note", new_note,
                  "--old-slug", old, "--new-slug", new]

        prepared = json.loads(self.run_script(
            fetch, *rename, "--phase", "prepare").stdout)
        self.assertEqual(prepared["mapping"], [{"from": old_image, "to": new_image}])
        self.assertEqual(
            {Path(row["path"]).resolve(): row["references"]
             for row in prepared["dependency"]["blockers"]},
            {wiki.resolve(): [old + ".md", old_image],
             moc.resolve(): [old + ".md"],
             investment.resolve(): [old_image], log.resolve(): [old + ".md"],
             other.resolve(): [old + ".md"], shared.resolve(): [old + ".md"],
             raw.resolve(): [old + ".md"]})
        self.assertEqual(digest(self.images / new_image), original)
        # The swapped pair is refused while the recorded old note exists.
        swapped = ["rename", "--attachments", self.images, "--sources",
                   self.pdfs, "--owner-note", new_note, "--new-owner-note",
                   note, "--old-slug", new, "--new-slug", old]
        for phase in ("prepare", "repair", "finalize"):
            refused = json.loads(self.run_script(
                fetch, *swapped, "--phase", phase, "--dry-run",
                expected=1).stdout)
            self.assertIn(f"pending handoff from {old}.md", refused["error"])

        def vault_state():
            return {path: (path.read_bytes() if path.is_file() else None)
                    for path in self.vault.rglob("*")}

        state = vault_state()
        planned = json.loads(self.run_script(
            fetch, *rename, "--phase", "repair", "--dry-run").stdout)
        self.assertEqual(vault_state(), state)
        self.assertEqual(
            {Path(row["path"]).resolve(): (row["status"], len(row["references"]))
             for row in planned["results"]},
            {wiki.resolve(): ("would-rewrite", 2), moc.resolve(): ("would-rewrite", 1),
             investment.resolve(): ("would-rewrite", 1),
             log.resolve(): ("would-rewrite", 1),
             other.resolve(): ("would-rewrite", 1),
             shared.resolve(): ("would-rewrite", 1),
             raw.resolve(): ("would-rewrite", 1)})
        for row in planned["results"]:
            for reference in row["references"]:
                self.assertEqual(reference["to"],
                                 reference["from"].replace(old, new))
        # The redraft kept the block ID, so no rewritten anchor is missing.
        self.assertFalse([row["path"] for row in planned["results"]
                          if "missing_anchors" in row])

        repaired = json.loads(self.run_script(
            fetch, *rename, "--phase", "repair").stdout)
        self.assertTrue(repaired["ok"])
        self.assertEqual({Path(row["path"]).resolve(): row["status"]
                          for row in repaired["results"]},
                         {path.resolve(): "rewritten" for path in dependents})
        self.assertEqual({path: path.read_text(encoding="utf-8")
                          for path in dependents}, dependents)
        self.assertFalse(list(self.vault.rglob(".clipping-link-repair*")))
        self.assertEqual(new_note.read_text(encoding="utf-8"),
                         body.replace(old, new))
        self.assertEqual(digest(self.images / old_image), original)
        entry = yaml.safe_load(wiki.read_text(encoding="utf-8").split("---", 2)[1])
        self.assertEqual((str(entry["created"]), str(entry["updated"]), entry["read"]),
                         ("2026-08-30", "2026-09-02", True))
        self.assertEqual(entry["sources"], [f"[[{new}.md]]"])
        after = {path: path.read_bytes() for path in dependents}
        again = json.loads(self.run_script(
            fetch, *rename, "--phase", "repair").stdout)
        self.assertFalse([row for row in again["results"]
                          if row["status"] != "unchanged"])
        self.assertEqual({path: path.read_bytes() for path in dependents}, after)

        dependency = json.loads(self.run_script(
            fetch, "dependencies", "--attachments", self.images,
            "--owner-note", note, "--old-slug", old).stdout)
        self.assertTrue(dependency["ok"])
        finalized = json.loads(self.run_script(
            fetch, *rename, "--phase", "finalize").stdout)
        self.assertEqual(finalized["results"][0]["action"], "retired")
        removed = json.loads(self.run_script(
            "shared/scripts/publish_files.py", "remove", "--vault", self.vault,
            "--snapshots", snapshots, f"Articles/{old}.md",
            f"Articles/{handoff.name}").stdout)
        self.assertEqual([row["action"] for row in removed["results"]],
                         ["removed", "removed"])
        self.assertFalse(note.exists())
        self.assertFalse(handoff.exists())
        self.assertFalse((self.images / old_image).exists())
        self.assertEqual(digest(self.images / new_image), original)
        self.assertTrue(new_note.is_file())

    def test_clipping_case_only_slug_change_keeps_the_note_spelling(self):
        # A slug that differs only by case is not a changed slug: publish-note
        # refuses it, and a same-name rewrite keeps the note's and images'
        # spelling, so no link needs repair.
        fetch = "skills/clipping-clean/scripts/fetch_images.py"
        publish = "shared/scripts/publish_files.py"
        old, respelled = "Smith_Llm_Agents_2026", "Smith_LLM_Agents_2026"
        image = old + "_fig_1.png"
        note = self.notes / (old + ".md")
        body = ('---\ntitle: "LLM agents"\nsources:\n'
                '  - "https://example.org/agents"\n---\n'
                f'![[{image}]]\n*An agent loop.*\n')
        note.write_text(body, encoding="utf-8")
        rendered = Path(self.scratch.name) / "browser render.png"
        Image.new("RGB", (64, 48), (20, 100, 180)).save(rendered)
        self.run_script(fetch, "place", "--attachments", self.images,
                        "--slug", old, "--index", 1, "--from-file", rendered,
                        "--owner-note", note)
        wiki = self.vault / "Wiki/agent-loop.md"
        wiki.write_text(f"See [[{old}]] and ![[{image}]].\n", encoding="utf-8")
        scratch = Path(self.scratch.name)
        snapshots = scratch / "clipping-snapshots.json"
        self.run_script(publish, "snapshot", "--vault", self.vault, "-o",
                        snapshots, f"Articles/{old}.md")
        draft = scratch / "draft.md"
        draft.write_text(body + "Reprocessed.\n", encoding="utf-8")
        before = {path: path.read_bytes()
                  for path in (self.images / image, wiki)}

        refused = json.loads(self.run_script(
            fetch, "rename", "--phase", "publish-note", "--vault", self.vault,
            "--snapshots", snapshots, "--draft", draft, "--owner-note", note,
            "--new-owner-note", self.notes / (respelled + ".md"),
            "--old-slug", old, "--new-slug", respelled, expected=1).stdout)
        self.assertIn("same-name rewrite", refused["error"])
        self.assertEqual(sorted(path.name for path in self.notes.iterdir()),
                         [old + ".md"])
        self.assertEqual(note.read_text(encoding="utf-8"), body)

        manifest = scratch / "manifest.json"
        manifest.write_text(json.dumps(
            [{"path": f"Articles/{old}.md", "draft": str(draft)}]),
            encoding="utf-8")
        published = json.loads(self.run_script(
            publish, "publish", "--vault", self.vault, "--snapshots",
            snapshots, "--manifest", manifest).stdout)
        self.assertEqual([row["action"] for row in published["results"]],
                         ["replaced"])
        self.assertEqual(sorted(path.name for path in self.notes.iterdir()),
                         [old + ".md"])
        self.assertEqual(note.read_bytes(), draft.read_bytes())
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        self.assertEqual(sorted(path.name for path in self.images.iterdir()),
                         [image])

    def test_clipping_changed_slug_migrates_legacy_origin_and_resumes_after_finalize(self):
        fetch = "skills/clipping-clean/scripts/fetch_images.py"
        publish = "shared/scripts/publish_files.py"
        old, new = "Smith_Cell_Signals_2026", "Smith_Cell_Receptors_2026"
        old_image, new_image = old + "_fig_1.png", new + "_fig_1.png"
        note, new_note = self.notes / (old + ".md"), self.notes / (new + ".md")
        legacy = ('---\ntitle: "Cell signals"\nsource: "https://example.org/study"\n'
                  f'---\n![[{old_image}]]\n*The cells exchange signals.*\n')
        current = legacy.replace("source: ", "sources:\n  - ")
        note.write_text(legacy, encoding="utf-8")
        Image.new("RGB", (64, 48), (20, 100, 180)).save(self.images / old_image)
        original = digest(self.images / old_image)
        wiki = self.vault / "Wiki/cell-signaling.md"
        wiki.write_text(f"See [[{old}]] and ![[{old_image}]].\n", encoding="utf-8")
        scratch = Path(self.scratch.name)
        snapshots = scratch / "clipping-snapshots.json"
        self.run_script(publish, "snapshot", "--vault", self.vault, "-o", snapshots,
                        f"Articles/{old}.md", f"Articles/{new}.md")
        draft = scratch / "draft.md"
        draft.write_text(current.replace(old, new), encoding="utf-8")
        publish_note = ["rename", "--phase", "publish-note", "--vault", self.vault,
                        "--snapshots", snapshots, "--draft", draft,
                        "--owner-note", note, "--new-owner-note", new_note,
                        "--old-slug", old, "--new-slug", new]

        # Every image phase refuses a legacy-only owner, so publish-note
        # refuses it before the new note is public.
        refused = json.loads(self.run_script(fetch, *publish_note, expected=1).stdout)
        self.assertIn("legacy scalar source:", refused["error"])
        self.assertFalse(new_note.exists())
        migrated = scratch / "migrated.md"
        migrated.write_text(current, encoding="utf-8")
        manifest = scratch / "migration-manifest.json"
        manifest.write_text(json.dumps(
            [{"path": f"Articles/{old}.md", "draft": str(migrated)}]), encoding="utf-8")
        self.run_script(publish, "publish", "--vault", self.vault,
                        "--snapshots", snapshots, "--manifest", manifest)
        self.run_script(publish, "snapshot", "--vault", self.vault, "-o", snapshots,
                        "--replace", f"Articles/{old}.md")
        created = json.loads(self.run_script(fetch, *publish_note).stdout)
        self.assertEqual(created["action"], "created")
        recorded = json.loads(self.run_script(
            publish, "snapshot", "--vault", self.vault, "-o", snapshots,
            "--replace", f"Articles/{new}.md", created["handoff_record"]).stdout)
        self.assertEqual(recorded["snapshots"][0]["digest"], created["sha256"])

        rename = ["rename", "--attachments", self.images, "--sources", self.pdfs,
                  "--owner-note", note, "--new-owner-note", new_note,
                  "--old-slug", old, "--new-slug", new]
        self.run_script(fetch, *rename, "--phase", "prepare")
        self.run_script(fetch, *rename, "--phase", "repair")
        self.assertEqual(wiki.read_text(encoding="utf-8"),
                         f"See [[{new}]] and ![[{new_image}]].\n")
        self.run_script(fetch, *rename, "--phase", "finalize")

        # The run stops before old-note removal. Finishing the handoff names
        # the retired copy instead of asking for a restore, and goes from the
        # clean re-probe straight to old-note removal. The swapped pair reads
        # the same, so its handoff record refuses it: guessing the direction
        # would remove the reprocessed note.
        handoff = f"Articles/.{new}.handoff.json"
        swapped = json.loads(self.run_script(
            fetch, "rename", "--attachments", self.images, "--sources",
            self.pdfs, "--owner-note", new_note, "--new-owner-note", note,
            "--old-slug", new, "--new-slug", old, "--phase", "prepare",
            "--dry-run", expected=1).stdout)
        self.assertIn(f"pending handoff from {old}.md", swapped["error"])
        self.assertNotIn("already retired", swapped["error"])
        self.run_script(fetch, "dependencies", "--attachments", self.images,
                        "--owner-note", new_note, "--old-slug", new,
                        expected=1)
        resumed = json.loads(self.run_script(
            fetch, *rename, "--phase", "prepare", "--dry-run", expected=1).stdout)
        self.assertIn("already retired", resumed["error"])
        self.assertNotIn("restore it or replace", resumed["error"])
        dependency = json.loads(self.run_script(
            fetch, "dependencies", "--attachments", self.images,
            "--owner-note", note, "--old-slug", old).stdout)
        self.assertTrue(dependency["ok"])
        resume_snapshots = scratch / "resume-snapshots.json"
        self.run_script(publish, "snapshot", "--vault", self.vault,
                        "-o", resume_snapshots, f"Articles/{old}.md", handoff)
        removed = json.loads(self.run_script(
            publish, "remove", "--vault", self.vault,
            "--snapshots", resume_snapshots, f"Articles/{old}.md",
            handoff).stdout)
        self.assertEqual([row["action"] for row in removed["results"]],
                         ["removed", "removed"])
        self.assertFalse(note.exists())
        self.assertFalse((self.vault / handoff).exists())
        self.assertFalse((self.images / old_image).exists())
        self.assertEqual(digest(self.images / new_image), original)
        self.assertEqual(new_note.read_text(encoding="utf-8"), current.replace(old, new))

    def test_clipping_changed_slug_never_edits_a_dated_research_record(self):
        fetch = "skills/clipping-clean/scripts/fetch_images.py"
        old, new = "Smith_Cell_Signals_2026", "Smith_Cell_Receptors_2026"
        old_image, new_image = old + "_fig_1.png", new + "_fig_1.png"
        note = self.notes / (old + ".md")
        metadata = {"title": "Cell signals", "format": "Article",
                    "sources": ["https://example.org/study"], "read": True}
        body = ('---\n' + yaml.safe_dump(metadata, sort_keys=False) + '---\n'
                + f'![[{old_image}]]\n*The cells exchange signals.*\n')
        note.write_text(body, encoding="utf-8")
        rendered = Path(self.scratch.name) / "browser render.png"
        Image.new("RGB", (64, 48), (20, 100, 180)).save(rendered)
        self.run_script(fetch, "place", "--attachments", self.images,
                        "--slug", old, "--index", 1, "--from-file", rendered,
                        "--owner-note", note)
        original = digest(self.images / old_image)
        new_note = self.notes / (new + ".md")
        new_note.write_text(body.replace(old, new), encoding="utf-8")

        # Dated stock-research records are the investments plugin's
        # immutable history; any other Investments/ note is repaired.
        record = self.vault / "Investments/2026-09-01-stock-research.md"
        record.parent.mkdir()
        record_bytes = ('---\nstock_research: 2\n---\nReceptor platforms, as in '
                        f'[[{old}]].\n\n![[{old_image}|300]]\n').encode("utf-8")
        record.write_bytes(record_bytes)
        notes = self.vault / "Investments/Research notes.md"
        notes.write_text(f"See [[{old}]].\n", encoding="utf-8")
        rename = ["rename", "--attachments", self.images, "--sources", self.pdfs,
                  "--owner-note", note, "--new-owner-note", new_note,
                  "--old-slug", old, "--new-slug", new]
        self.run_script(fetch, *rename, "--phase", "prepare")

        repaired = json.loads(self.run_script(
            fetch, *rename, "--phase", "repair", expected=1).stdout)
        rows = {Path(row["path"]).resolve(): row for row in repaired["results"]}
        self.assertFalse(repaired["ok"])
        self.assertEqual(
            {path: row["status"] for path, row in rows.items()},
            {record.resolve(): "blocked", notes.resolve(): "rewritten"})
        self.assertIn("dated Investments/ research record is immutable",
                      rows[record.resolve()]["reason"])
        self.assertEqual(record.read_bytes(), record_bytes)
        self.assertEqual(notes.read_text(encoding="utf-8"), f"See [[{new}]].\n")

        dependency = json.loads(self.run_script(
            fetch, "dependencies", "--attachments", self.images,
            "--owner-note", note, "--old-slug", old, expected=1).stdout)
        self.assertFalse(dependency["ok"])
        self.assertEqual([Path(row["path"]).resolve()
                          for row in dependency["blockers"]], [record.resolve()])
        self.run_script(fetch, *rename, "--phase", "finalize", expected=1)
        self.assertEqual(record.read_bytes(), record_bytes)
        self.assertTrue(note.is_file())
        self.assertEqual(digest(self.images / old_image), original)
        self.assertEqual(digest(self.images / new_image), original)

    def test_same_url_clipping_twin_counts_as_prior_coverage(self):
        # A pending changed-slug handoff keeps two Articles notes of one page.
        # wiki-build finds the twin with dedup_index and passes both notes to
        # vault_index, so an entry citing the old note covers the new one.
        url = "https://example.org/cell-signals"
        old = self.notes / "Smith_Cell_Signals_2026.md"
        new = self.notes / "Smith_Cell_Receptors_2026.md"
        for note in (old, new):
            note.write_text('---\nsources:\n  - "%s"\n---\nBody.\n' % url,
                            encoding="utf-8")
        (self.vault / "Wiki/receptor.md").write_text(
            '---\ntitle: "Receptor"\ntype: Concept\nsources:\n'
            '  - "[[Smith_Cell_Signals_2026.md]]"\n---\nBody.\n',
            encoding="utf-8")
        dedup = json.loads(self.run_script(
            "skills/clipping-clean/scripts/dedup_index.py", self.notes,
            "--url", url).stdout)
        twins = sorted(Path(path).name for path in dedup["checked"][0]["matches"])
        self.assertEqual(twins, [new.name, old.name])

        def covered(*notes):
            index = json.loads(self.run_script(
                "skills/wiki-build/scripts/vault_index.py", self.vault / "Wiki",
                "--vault", self.vault,
                *[arg for note in notes for arg in ("--source", note)]).stdout)
            return [(item["relpath"], item["identity_confirmed"])
                    for item in index["source_matches"]]

        self.assertEqual(covered(new), [])
        self.assertEqual(covered(new, old), [("receptor.md", True)])

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

    def test_fresh_vault_bootstrap_lets_wiki_build_extract_figures(self):
        # wiki-build's media rule: an absent Sources/Images keeps the figure
        # inventory incomplete until an apply run creates the folder with a
        # plain mkdir; a preview creates nothing.
        fresh = Path(self.scratch.name) / "fresh figures vault"
        pdfs = fresh / "Sources/PDFs"
        pdfs.mkdir(parents=True)
        pdf = pdfs / "Doe_Fresh_2025.pdf"
        self.make_pdf(pdf)
        images = fresh / "Sources/Images"
        inventory = ("shared/scripts/vault_artifacts.py", "figures",
                     "--images", images, "--stem", pdf.stem)
        absent = json.loads(self.run_script(*inventory, expected=1).stdout)
        self.assertFalse(absent["complete"])
        self.assertFalse(absent["safe"])
        self.assertIn("unreadable",
                      [finding["kind"] for finding in absent["findings"]])

        self.run_script("skills/figure-extract/scripts/batch_extract.py",
                        "--src", pdf, "--out", images, "--dpi", 72,
                        "--dry-run")
        self.assertFalse(images.exists())

        images.mkdir()
        empty = json.loads(self.run_script(*inventory).stdout)
        self.assertTrue(empty["complete"])
        self.assertTrue(empty["safe"])
        self.assertEqual(empty["candidates"], [])
        self.run_script("skills/figure-extract/scripts/batch_extract.py",
                        "--src", pdf, "--out", images, "--dpi", 72)
        filled = json.loads(self.run_script(*inventory).stdout)
        self.assertTrue(filled["complete"])
        self.assertEqual([Path(path).name for path in filled["candidates"]],
                         ["Doe_Fresh_2025_fig_1.png"])

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

    def write_discipline_root(self, discipline):
        title = discipline.replace("-", " ").capitalize()
        text = f'''---
title: "{title}"
type: Concept
sources:
  - "[[Example_Fields_nd.md]]"
created: 2026-08-30
updated: 2026-08-30
description: "{title} organizes a field of knowledge."
tags:
  - "#{discipline}"
parents: []
read: false
issues: ""
---
**{title}** organizes a field of knowledge.

**Related:**

---

## Flashcards

A field of knowledge used as a root in this synthetic example.
??
{title}
'''
        (self.vault / "Wiki" / (discipline + ".md")).write_text(text, encoding="utf-8")
        (self.notes / "Example_Fields_nd.md").write_text("Synthetic field definitions.", encoding="utf-8")

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
        # A verified online page may be cited beside the local PDF by its URL.
        entry.write_text('''---
title: "Control sample"
type: Concept
sources:
  - "[[Doe_Study_2025.pdf#page=1]]"
  - "https://en.wikipedia.org/wiki/Scientific_control"
created: 2026-08-30
updated: 2026-08-30
description: "A control sample provides a baseline for comparing the effect of an experimental treatment."
tags:
  - "#biology"
parents:
  - "[[biology]]"
read: false
issues: ""
---
A **control sample** provides a baseline for comparing an experimental treatment with an otherwise matched condition. The treatment is withheld while the preparation and measurement procedure remain the same. A difference between the treated and untreated groups can then be interpreted within the limits of that comparison.

**Related:**

---

## Flashcards

An untreated experimental specimen prepared and measured like the treated group to provide a baseline.
??
Control sample
''', encoding="utf-8")
        self.write_discipline_root("biology")
        # A complete generated MOC is an ordinary nested bullet list.
        (self.vault / "MOCs").mkdir()
        (self.vault / "MOCs/biology-moc.md").write_text(
            "- [[Wiki/biology|Biology]]\n  - [[Wiki/control-sample|Control sample]]\n", encoding="utf-8")
        index = self.vault / "index.json"
        self.run_script("skills/wiki-build/scripts/vault_index.py", wiki, "-o", index)
        inventory = json.loads(index.read_text(encoding="utf-8"))
        self.assertEqual(inventory["entry_count"], 2)
        # The URL item is recorded as provenance, never as a malformed reference.
        self.assertEqual(inventory["problems"], [])
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
        (self.vault / "MOCs/biology-moc.md").write_text(
            "Introductory prose left by an older generation.\n"
            "- [[Wiki/biology|Biology]]\n  - [[Wiki/control-sample|Control sample]]\n", encoding="utf-8")
        self.run_script("skills/wiki-lint/scripts/scan_vault.py", wiki,
                        "--images", self.images, "--out", scan)
        revised_report = json.loads(scan.read_text(encoding="utf-8"))
        self.assertTrue(any(
            finding["kind"] == "malformed-line" and finding["line"] == 1
            for finding in revised_report["hierarchy_diagnostic"]["moc_consistency_findings"]))

    @staticmethod
    def averages_entry(title, created, prose, card):
        return f'''---
title: "{title}"
type: Concept
sources:
  - "https://example.org/averages"
created: {created}
updated: {created}
description: "The {title.lower()} is one way to average a collection of numbers."
tags:
  - "#mathematics"
parents: []
read: false
issues: ""
---
{prose}

**Related:**

---

## Flashcards

{card}
??
{title}
'''

    def test_wiki_build_review_tree_then_publish_files(self):
        # wiki-build step 7: review_tree.py lints the drafts that one
        # manifest lists, and publish_files.py publishes that same manifest
        # only against the snapshots taken before the entries were read.
        wiki = self.vault / "Wiki"
        run = Path(self.scratch.name) / "run"
        (run / "drafts").mkdir(parents=True)
        existing = wiki / "arithmetic-mean.md"
        existing.write_text(self.averages_entry(
            "Arithmetic mean", "2026-09-05",
            "The **arithmetic mean** of a collection is its sum divided by "
            "its size.",
            "The sum of a collection of numbers divided by how many numbers "
            "it holds."), encoding="utf-8")
        created_draft = run / "drafts/geometric-mean.md"
        merged_draft = run / "drafts/arithmetic-mean.md"

        def draft_geometric(link, draft=created_draft):
            contrast = "Unlike the %s, it" % link if link else "It"
            draft.write_text(self.averages_entry(
                "Geometric mean", "2026-09-06",
                "The **geometric mean** of $n$ positive numbers is the $n$-th "
                "root of their product. %s averages ratios and growth rates."
                % contrast,
                "The $n$-th root of the product of $n$ positive numbers."),
                encoding="utf-8")

        def draft_merge():
            text = existing.read_text(encoding="utf-8")
            merged_draft.write_text(text.replace(
                "updated: 2026-09-05", "updated: 2026-09-06").replace(
                " divided by its size.", " divided by its size. The "
                "[[geometric-mean|geometric mean]] instead averages ratios."),
                encoding="utf-8")

        manifest = run / "manifest.json"
        manifest.write_text(json.dumps([
            {"path": "Wiki/geometric-mean.md", "draft": str(created_draft)},
            {"path": "Wiki/arithmetic-mean.md", "draft": str(merged_draft)},
        ]), encoding="utf-8")
        snapshots = run / "snapshots.json"
        publisher = "shared/scripts/publish_files.py"
        recorded = json.loads(self.run_script(
            publisher, "snapshot", "--vault", self.vault, "-o", snapshots,
            "Wiki/geometric-mean.md", "Wiki/arithmetic-mean.md").stdout)
        self.assertEqual(recorded["snapshots"][0]["state"], "absent")
        self.assertNotEqual(recorded["snapshots"][1]["state"], "absent")
        draft_geometric("[[harmonic-mean|harmonic mean]]")
        draft_merge()

        def review():
            return json.loads(self.run_script(
                "skills/wiki-build/scripts/review_tree.py", "--vault",
                self.vault, "--wiki", wiki, "--manifest", manifest,
                "--out", run / "review").stdout)

        # The review lints the staged drafts, not the public Wiki.
        first = review()
        self.assertFalse(first["clean"])
        self.assertEqual([row["target"] for row in first["dangling"]],
                         ["harmonic-mean"])
        draft_geometric("[[arithmetic-mean|arithmetic mean]]")
        reviewed = review()
        self.assertTrue(reviewed["clean"], reviewed)
        self.assertEqual(sorted(reviewed["staged"]),
                         ["Wiki/arithmetic-mean.md", "Wiki/geometric-mean.md"])

        vault_names = sorted(path.name for path in self.vault.iterdir())
        original = existing.read_bytes()
        planned = json.loads(self.run_script(
            publisher, "publish", "--vault", self.vault, "--snapshots",
            snapshots, "--manifest", manifest, "--dry-run").stdout)
        self.assertEqual([row["action"] for row in planned["results"]],
                         ["create", "replace"])
        self.assertFalse((wiki / "geometric-mean.md").exists())
        self.assertEqual(existing.read_bytes(), original)

        # A late edit to a snapshotted entry refuses the whole publication.
        existing.write_text(original.decode("utf-8").replace(
            "its sum divided", "its total divided"), encoding="utf-8")
        edited = existing.read_bytes()
        refused = json.loads(self.run_script(
            publisher, "publish", "--vault", self.vault, "--snapshots",
            snapshots, "--manifest", manifest, expected=1).stdout)
        self.assertEqual([row["action"] for row in refused["results"]],
                         ["pending", "refused"])
        self.assertFalse((wiki / "geometric-mean.md").exists())
        self.assertEqual(existing.read_bytes(), edited)
        self.assertEqual(sorted(path.name for path in self.vault.iterdir()),
                         vault_names)

        # Re-snapshot the changed entry, rebuild its draft from the newer
        # file, review again and publish the reviewed bytes.
        self.run_script(publisher, "snapshot", "--vault", self.vault, "-o",
                        snapshots, "--replace", "Wiki/arithmetic-mean.md")
        draft_merge()
        self.assertTrue(review()["clean"])
        published = json.loads(self.run_script(
            publisher, "publish", "--vault", self.vault, "--snapshots",
            snapshots, "--manifest", manifest).stdout)
        self.assertEqual([row["action"] for row in published["results"]],
                         ["created", "replaced"])
        self.assertEqual((wiki / "geometric-mean.md").read_bytes(),
                         created_draft.read_bytes())
        self.assertEqual(existing.read_bytes(), merged_draft.read_bytes())
        self.assertIn(b"its total divided", existing.read_bytes())
        self.assertEqual(sorted(path.name for path in self.vault.iterdir()),
                         vault_names)
        lint = run / "lint.json"
        self.run_script("skills/wiki-build/scripts/lint_entry.py", wiki,
                        "-o", lint)
        self.assertTrue(
            json.loads(lint.read_text(encoding="utf-8"))["summary"]["clean"])

        # With Wiki absent, the review creates nothing and only an explicit
        # --create-dir lets the publication create the folder.
        fresh = Path(self.scratch.name) / "fresh vault"
        fresh.mkdir()
        fresh_draft = run / "drafts/fresh-geometric-mean.md"
        draft_geometric(None, fresh_draft)
        fresh_manifest = run / "fresh-manifest.json"
        fresh_manifest.write_text(json.dumps([
            {"path": "Wiki/geometric-mean.md", "draft": str(fresh_draft)},
        ]), encoding="utf-8")
        fresh_snapshots = run / "fresh-snapshots.json"
        self.run_script(publisher, "snapshot", "--vault", fresh, "-o",
                        fresh_snapshots, "Wiki/geometric-mean.md")
        fresh_review = json.loads(self.run_script(
            "skills/wiki-build/scripts/review_tree.py", "--vault", fresh,
            "--wiki", fresh / "Wiki", "--manifest", fresh_manifest,
            "--out", run / "fresh-review").stdout)
        self.assertTrue(fresh_review["clean"], fresh_review)
        self.assertEqual(list(fresh.iterdir()), [])
        publish = (publisher, "publish", "--vault", fresh, "--snapshots",
                   fresh_snapshots, "--manifest", fresh_manifest)
        missing = json.loads(self.run_script(*publish, expected=1).stdout)
        self.assertIn("--create-dir Wiki", missing["results"][0]["detail"])
        self.assertEqual(list(fresh.iterdir()), [])
        self.run_script(*publish, "--create-dir", "Wiki")
        self.assertEqual((fresh / "Wiki/geometric-mean.md").read_bytes(),
                         fresh_draft.read_bytes())

    def test_overlaid_tree_omits_a_symlinked_folder_the_real_wiki_probes(self):
        # source-cases.md's overlaid tree: an unmirrored path is absent from
        # the tree and its index, so a multi-source run also probes and
        # queries the real Wiki while the tree reports one.
        wiki = self.vault / "Wiki"
        run = Path(self.scratch.name) / "run"
        (run / "drafts").mkdir(parents=True)
        synced = Path(self.scratch.name) / "synced elsewhere"
        synced.mkdir()
        try:
            (wiki / "ml").symlink_to(synced, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable")
        (self.pdfs / "Kmeans_Book_2024.pdf").write_bytes(b"%PDF-1.4\n")
        (synced / "k-means.md").write_text(self.averages_entry(
            "K-means", "2026-09-05",
            "**K-means** splits a collection into $k$ groups around their "
            "means.", "A clustering method that splits data into k groups "
            "around their means.").replace(
                "https://example.org/averages",
                "[[Kmeans_Book_2024.pdf#page=3]]"), encoding="utf-8")
        draft = run / "drafts/geometric-mean.md"
        draft.write_text(self.averages_entry(
            "Geometric mean", "2026-09-06",
            "The **geometric mean** of $n$ positive numbers is the $n$-th "
            "root of their product.",
            "The $n$-th root of the product of $n$ positive numbers."),
            encoding="utf-8")
        manifest = run / "manifest.json"
        manifest.write_text(json.dumps([
            {"path": "Wiki/geometric-mean.md", "draft": str(draft)}]),
            encoding="utf-8")
        review = json.loads(self.run_script(
            "skills/wiki-build/scripts/review_tree.py", "--vault", self.vault,
            "--wiki", wiki, "--manifest", manifest,
            "--out", run / "review").stdout)
        self.assertEqual([row["path"] for row in review["unmirrored"]],
                         ["Wiki/ml"])
        titles = run / "candidates.json"
        titles.write_text(json.dumps(["K-means"]), encoding="utf-8")
        source = self.pdfs / "Kmeans_Book_2024.pdf"

        def probe_and_cover(tree, *origin):
            index = run / "index.json"
            self.run_script("skills/wiki-build/scripts/vault_index.py", tree,
                            "-o", index)
            probe = json.loads(self.run_script(
                "skills/wiki-build/scripts/find_collisions.py", "--index",
                index, "--titles", titles).stdout)["results"][0]
            coverage = json.loads(self.run_script(
                "skills/wiki-build/scripts/vault_index.py", tree, "--vault",
                self.vault, "--source", source, *origin).stdout)
            return ((probe["verdict"],
                     [match["entry_path"] for match in probe["matches"]]),
                    [(item["relpath"], item["identity_confirmed"])
                     for item in coverage["source_matches"]])

        self.assertEqual(probe_and_cover(review["tree"], "--wiki-origin", wiki),
                         (("create", []), []))
        self.assertEqual(probe_and_cover(wiki),
                         (("merge", [os.path.join("ml", "k-means.md")]),
                          [(os.path.join("ml", "k-means.md"), True)]))

    def test_case_only_retitle_respells_the_same_entry_file(self):
        # wiki-lint's retitle protocol: a filename that differs from its
        # title's slug only in case is the entry's own file, so the scanner
        # calls the destination free. The entry is published under its old
        # spelling, re-recorded and respelled with publish_files.py move.
        wiki = self.vault / "Wiki"
        run = Path(self.scratch.name) / "run"
        (run / "drafts").mkdir(parents=True)
        entry = wiki / "Midrange.md"
        entry.write_text(self.averages_entry(
            "Midrange", "2026-09-05",
            "The **midrange** of a collection is the mean of its largest and "
            "smallest values.",
            "The mean of the largest and smallest values of a collection."),
            encoding="utf-8")
        entry.chmod(0o600)
        mean = wiki / "arithmetic-mean.md"
        mean.write_text(self.averages_entry(
            "Arithmetic mean", "2026-09-05",
            "The **arithmetic mean** of a collection is its sum divided by "
            "its size. The [[Midrange]] uses only the two extreme values.",
            "The sum of a collection of numbers divided by how many numbers "
            "it holds."), encoding="utf-8")
        publisher = "shared/scripts/publish_files.py"
        snapshots = run / "lint-snapshots.json"

        def scan():
            return json.loads(self.run_script(
                "skills/wiki-lint/scripts/scan_vault.py", wiki).stdout)

        def names():
            return sorted(path.name for path in wiki.iterdir())

        def publish(path, draft):
            manifest = run / "manifest.json"
            manifest.write_text(json.dumps([{"path": path, "draft": str(draft)}]),
                                encoding="utf-8")
            return json.loads(self.run_script(
                publisher, "publish", "--vault", self.vault, "--snapshots",
                snapshots, "--manifest", manifest).stdout)

        before = scan()
        self.assertEqual(before["rename_candidates"], [
            {"slug": "Midrange", "new_slug": "midrange", "inbound_links": 1,
             "target_exists": False}])
        self.assertIn(("Midrange", "item5"),
                      {(row["slug"], row["item"]) for row in before["problems"]})

        # Step 1 records only the source entry and the inbound file.
        self.run_script(publisher, "snapshot", "--vault", self.vault, "-o",
                        snapshots, "Wiki/Midrange.md", "Wiki/arithmetic-mean.md")
        entry_draft = run / "drafts/midrange.md"
        entry_draft.write_bytes(entry.read_bytes().replace(
            b"updated: 2026-09-05", b"updated: 2026-09-06"))
        mean_draft = run / "drafts/arithmetic-mean.md"
        mean_draft.write_bytes(mean.read_bytes().replace(
            b"[[Midrange]]", b"[[midrange]]"))

        # Step 4: publish in place, re-record, then respell the same file.
        self.assertEqual([row["action"] for row in publish(
            "Wiki/Midrange.md", entry_draft)["results"]], ["replaced"])
        self.run_script(publisher, "snapshot", "--vault", self.vault, "-o",
                        snapshots, "--replace", "Wiki/Midrange.md")
        inode = (entry.stat().st_dev, entry.stat().st_ino)
        move = (publisher, "move", "--vault", self.vault, "--snapshots",
                snapshots, "Wiki/Midrange.md", "Wiki/midrange.md")
        moved = json.loads(self.run_script(*move).stdout)
        self.assertEqual([row["action"] for row in moved["results"]],
                         ["respelled"])
        respelled = wiki / "midrange.md"
        self.assertEqual(names(), ["arithmetic-mean.md", "midrange.md"])
        self.assertEqual((respelled.stat().st_dev, respelled.stat().st_ino),
                         inode)
        self.assertEqual(respelled.read_bytes(), entry_draft.read_bytes())
        self.assertEqual(respelled.stat().st_mode & 0o777, 0o600)
        self.assertEqual(sorted(path.name for path in self.vault.iterdir()
                                if path.name.startswith(".")), [])
        rerun = json.loads(self.run_script(*move).stdout)
        self.assertEqual([row["action"] for row in rerun["results"]],
                         ["respelled"])
        self.assertEqual([row["action"] for row in publish(
            "Wiki/arithmetic-mean.md", mean_draft)["results"]], ["replaced"])

        after = scan()
        self.assertEqual(after["rename_candidates"], [])
        self.assertFalse([row for row in after["problems"]
                          if row["item"] in ("item5", "item10")
                          or row["item"].startswith("item10/")],
                         after["problems"])

    def test_suggestion_log_refuses_a_symlinked_reviews_folder(self):
        # SUGGESTIONS.md's recipe passes --owned-dir Reviews, so the helper
        # refuses a Reviews/ that is a symlink to another vault folder.
        run = Path(self.scratch.name) / "run"
        run.mkdir()
        (self.vault / "Other").mkdir()
        (self.vault / "Reviews").symlink_to("Other")
        log = "Reviews/wiki-lint-suggestions.md"
        snapshots = run / "log-snapshots.json"
        publisher = "shared/scripts/publish_files.py"
        refused = json.loads(self.run_script(
            publisher, "snapshot", "--vault", self.vault, "--owned-dir",
            "Reviews", "-o", snapshots, log, expected=1).stdout)
        self.assertEqual(refused["snapshots"][0]["state"], "refused")
        self.run_script(publisher, "snapshot", "--vault", self.vault, "-o",
                        snapshots, log)
        draft = run / "log.md"
        draft.write_text("# Suggestions\n", encoding="utf-8")
        manifest = run / "log-manifest.json"
        manifest.write_text(json.dumps([{"path": log, "draft": str(draft)}]),
                            encoding="utf-8")
        published = json.loads(self.run_script(
            publisher, "publish", "--vault", self.vault, "--owned-dir",
            "Reviews", "--snapshots", snapshots, "--manifest", manifest,
            expected=1).stdout)
        self.assertEqual([row["action"] for row in published["results"]],
                         ["refused"])
        self.assertEqual(list((self.vault / "Other").iterdir()), [])

    def test_user_issues_reach_wiki_lint_and_the_builder_preserves_them(self):
        # `issues:` is the user's issue inbox (CONVENTIONS §2d). The scanner
        # lists a non-blank value, scalar or list, as a wiki-lint worklist
        # row, and the builder's linter only asks to preserve it. Every blank
        # spelling Obsidian may write conforms, a missing key is a Task 1
        # format repair, and any other shape is report-only.
        wiki = self.vault / "Wiki"
        canonical = 'read: false\nissues: ""\n'
        malformed = ({"item2/issues-malformed"}, {"2-issues-malformed": "warning"})
        cases = {
            # slug: (title, frontmatter that replaces `canonical`,
            #        scanner item-2 keys, builder 2-* findings)
            "arithmetic-mean": ("Arithmetic mean", canonical, set(), {}),
            "geometric-mean": (
                "Geometric mean",
                "read: false\nissues: The card is vague. Add a worked example.\n",
                set(), {"2-user-issues": "info"}),
            "harmonic-mean": (
                "Harmonic mean",
                'read: true\nissues:\n  - "Explain rates more simply."\n'
                "  - Wrong parent\n",
                set(), {"2-user-issues": "info"}),
            # An empty list item is dropped; the rest is the user's text.
            "midhinge": ("Midhinge", "read: false\nissues:\n  -\n  - Fix the card\n",
                         set(), {"2-user-issues": "info"}),
            "quadratic-mean": (
                "Quadratic mean", "read: false\n",
                {"item2/issues-missing"}, {"2-issues-missing": "error"}),
            # With read: absent too, each key is reported on its own.
            "midrange": ("Midrange", "",
                         {"item2/issues-missing", "item2/read-missing"},
                         {"2-issues-missing": "error", "2-read-state": "info"}),
            "weighted-mean": ("Weighted mean", "read: false\nissues:\n", set(), {}),
            "truncated-mean": ("Truncated mean", "read: false\nissues: null\n",
                               set(), {}),
            "trimmed-mean": ("Trimmed mean", "read: false\nissues: ~\n", set(), {}),
            "power-mean": ("Power mean", "read: false\nissues: ''\n", set(), {}),
            "logarithmic-mean": ("Logarithmic mean", "read: false\nissues: []\n",
                                 set(), {}),
            "interquartile-mean": (
                "Interquartile mean", "read: false\nissues:\n  card: too long\n",
                *malformed),
            "trimean": ("Trimean", "read: false\nissues: {note: fix it}\n",
                        *malformed),
            "generalized-mean": (
                "Generalized mean", "read: false\nissues:\n  - [one, two]\n",
                *malformed),
            "winsorized-mean": (
                "Winsorized mean", "read: false\nissues:\n  -\n    - Wrong parent\n",
                *malformed),
            # Text the validators cannot read as one line is malformed too.
            "contraharmonic-mean": (
                "Contraharmonic mean",
                "read: false\nissues: Fix this: the card is vague\n", *malformed),
            "heronian-mean": (
                "Heronian mean",
                'read: false\nissues: "The card is vague.\n  Add an example."\n',
                *malformed),
            "lehmer-mean": (
                "Lehmer mean", "read: false\nissues: |\n  The card is vague.\n",
                *malformed),
            # An unquoted '#' comment would cut the user's text off, even to
            # blank, so both validators report it instead of reading it short.
            "chisini-mean": (
                "Chisini mean", "read: false\nissues: #1 the card is wrong\n",
                *malformed),
            "exponential-mean": (
                "Exponential mean", "read: false\nissues:\n  - Fix the #2 card\n",
                *malformed),
            "weighted-median": (
                "Weighted median", 'issues: ""\nread: false\n',
                {"item2"}, {"2-field-order": "error"}),
        }
        for slug, (title, frontmatter, _scan, _lint) in cases.items():
            prose = f"The **{title.lower()}** is a synthetic average of a collection."
            if slug == "arithmetic-mean":
                prose += " Unlike the [[Nonexistent average]], it weighs all values."
            text = self.averages_entry(
                title, "2026-09-05", prose,
                "A synthetic average that exercises one spelling of the issues "
                "field.")
            self.assertIn(canonical, text)
            (wiki / f"{slug}.md").write_text(
                text.replace(canonical, frontmatter), encoding="utf-8")
        before = {path.name: path.read_bytes() for path in wiki.iterdir()}

        scan = json.loads(self.run_script(
            "skills/wiki-lint/scripts/scan_vault.py", wiki,
            "--images", self.images).stdout)
        # One row per entry with issues, sorted by slug; a scalar is one issue.
        self.assertEqual(scan["user_issues"], [
            {"slug": "geometric-mean", "form": "string",
             "issues": ["The card is vague. Add a worked example."]},
            {"slug": "harmonic-mean", "form": "list",
             "issues": ["Explain rates more simply.", "Wrong parent"]},
            {"slug": "midhinge", "form": "list", "issues": ["Fix the card"]},
        ])
        # A malformed value is only an item-2 report: it leaves the alias
        # inventory complete, so vault-wide inferences such as a dangling
        # link still run.
        self.assertIn(("arithmetic-mean", "item10/dangling"),
                      {(row["slug"], row["item"]) for row in scan["problems"]})
        lint = self.vault / "issues-lint.json"
        self.run_script("skills/wiki-build/scripts/lint_entry.py", wiki,
                        "-o", lint)
        built = {Path(row["file"]).stem: row["findings"] for row in
                 json.loads(lint.read_text(encoding="utf-8"))["entries"]}
        for slug, (_title, _frontmatter, scan_keys, lint_keys) in cases.items():
            with self.subTest(slug=slug):
                rows = [row for row in scan["problems"] if row["slug"] == slug
                        and row["item"].split("/")[0] == "item2"]
                self.assertEqual({row["item"] for row in rows}, scan_keys, rows)
                # The issues key is never named by the generic missing-key loop.
                self.assertFalse(any(row["message"] == "missing issues: key"
                                     for row in rows), rows)
                if scan_keys == {"item2"}:
                    self.assertIn("fields out of schema order", rows[0]["message"])
                findings = [row for row in built[slug]
                            if row["item"].startswith("2-")]
                self.assertEqual({row["item"]: row["severity"] for row in findings},
                                 lint_keys, findings)
                # The user's text is never a fixable YAML error to repair.
                self.assertFalse([row for row in scan["problems"]
                                  if row["slug"] == slug and row["item"] == "item1"])
                self.assertFalse([row for row in built[slug]
                                  if row["item"].startswith("1-")])
        self.assertIn('`issues: ""` directly after read:', next(
            row["message"] for row in scan["problems"]
            if row["item"] == "item2/issues-missing"))

        # wiki-build step 7: a merge into an entry with user issues keeps the
        # value byte-for-byte, and the review's only item-2 finding on the
        # draft is the inherited, report-only reminder to preserve it.
        run = Path(self.scratch.name) / "issues-run"
        run.mkdir()
        draft = run / "geometric-mean.md"
        existing = (wiki / "geometric-mean.md").read_text(encoding="utf-8")
        merged = existing.replace(
            "updated: 2026-09-05", "updated: 2026-09-06").replace(
            "of a collection.", "of a collection of positive numbers.")
        self.assertIn("\nissues: The card is vague. Add a worked example.\n---\n",
                      merged)
        draft.write_text(merged, encoding="utf-8")
        manifest = run / "manifest.json"
        manifest.write_text(json.dumps([
            {"path": "Wiki/geometric-mean.md", "draft": str(draft)},
        ]), encoding="utf-8")
        review = json.loads(self.run_script(
            "skills/wiki-build/scripts/review_tree.py", "--vault", self.vault,
            "--wiki", wiki, "--manifest", manifest, "--out", run / "review").stdout)
        self.assertEqual(
            [(row["item"], row.get("inherited", False),
              (row["evidence"] or {}).get("report_only"))
             for row in review["on_staged"]
             if row["file"] == "Wiki/geometric-mean.md"
             and row["item"].startswith("2-")],
            [("2-user-issues", True, True)])
        # The validators and the review only read: the user's text stays
        # byte-for-byte.
        self.assertEqual({path.name: path.read_bytes() for path in wiki.iterdir()},
                         before)

    def test_user_text_after_the_card_is_reported_never_removed(self):
        # A block after the card that is not a card, such as the user's own
        # three-line note, is no extra card: a wiki-build merge review and
        # the scanner each report it once, report-only, and keep its bytes.
        wiki = self.vault / "Wiki"
        entry = wiki / "geometric-mean.md"
        existing = self.averages_entry(
            "Geometric mean", "2026-09-05",
            "The **geometric mean** of a collection of positive numbers is "
            "the nth root of their product.",
            "The nth root of the product of a collection of positive numbers."
        ) + ("\nMy own note: compare it with the arithmetic mean.\n"
             "It weighs every value alike.\n"
             "Ask about this in the reading group.\n")
        entry.write_text(existing, encoding="utf-8")
        run = Path(self.scratch.name) / "note-run"
        run.mkdir()
        draft = run / "geometric-mean.md"
        draft.write_text(existing.replace("updated: 2026-09-05",
                                          "updated: 2026-09-06"),
                         encoding="utf-8")
        manifest = run / "manifest.json"
        manifest.write_text(json.dumps([
            {"path": "Wiki/geometric-mean.md", "draft": str(draft)},
        ]), encoding="utf-8")
        review = json.loads(self.run_script(
            "skills/wiki-build/scripts/review_tree.py", "--vault", self.vault,
            "--wiki", wiki, "--manifest", manifest, "--out", run / "review").stdout)
        self.assertEqual(
            [(row["severity"], row.get("inherited", False), row["evidence"])
             for row in review["on_staged"] if row["item"] == "19-flashcards"],
            [("warning", True, {"block": 2, "report_only": True})])
        scan = json.loads(self.run_script(
            "skills/wiki-lint/scripts/scan_vault.py", wiki,
            "--images", self.images).stdout)
        rows = [row["message"] for row in scan["problems"]
                if row["slug"] == "geometric-mean" and row["item"] == "item19"]
        self.assertEqual(len(rows), 1, rows)
        self.assertTrue(rows[0].startswith("block 2 is not a card"), rows)
        self.assertEqual(entry.read_text(encoding="utf-8"), existing)

    def test_root_without_card_and_parents_link_down(self):
        # A discipline root needs no Flashcards section, and the scanner lists
        # a parent whose prose and footer leave a child unlinked for Task 3.
        wiki = self.vault / "Wiki"
        self.write_discipline_root("biology")
        root = wiki / "biology.md"
        root.write_text(
            root.read_text(encoding="utf-8").split("\n---\n\n## Flashcards", 1)[0]
            .replace("**Related:**", "**Related:** [[biological-cell|Biological cell]]"),
            encoding="utf-8")
        self.assertNotIn("## Flashcards", root.read_text(encoding="utf-8"))

        def write_member(slug, title, parent, opener, cue, related):
            (wiki / f"{slug}.md").write_text(f'''---
title: "{title}"
type: Concept
sources:
  - "[[Example_Fields_nd.md]]"
created: 2026-08-30
updated: 2026-08-30
description: "{opener.replace('**', '')}"
tags:
  - "#biology"
parents:
  - "[[{parent}]]"
read: false
issues: ""
---
{opener}

**Related:** {related}

---

## Flashcards

{cue}
??
{title}
''', encoding="utf-8")

        write_member(
            "biological-cell", "Biological cell", "biology",
            "A **biological cell** is the smallest unit of an organism that can live on its own.",
            "The smallest membrane-bounded unit of an organism that can live on its own.",
            "[[biology|Biology]]")
        write_member(
            "organelle", "Organelle", "biological-cell",
            "An **organelle** is a specialized structure inside a cell that performs a distinct function.",
            "A specialized structure inside a cell that performs a distinct function.",
            "[[biological-cell|Biological cell]]")
        (self.vault / "MOCs").mkdir()
        (self.vault / "MOCs/biology-moc.md").write_text(
            "- [[Wiki/biology|Biology]]\n  - [[Wiki/biological-cell|Biological cell]]\n"
            "    - [[Wiki/organelle|Organelle]]\n", encoding="utf-8")

        lint = self.vault / "lint.json"
        self.run_script("skills/wiki-build/scripts/lint_entry.py", wiki, "-o", lint)
        self.assertTrue(
            json.loads(lint.read_text(encoding="utf-8"))["summary"]["clean"])

        def scan():
            report = json.loads(self.run_script(
                "skills/wiki-lint/scripts/scan_vault.py", wiki,
                "--images", self.images).stdout)
            self.assertEqual(report["problems"], [])
            return report["hierarchy_diagnostic"]

        diagnostic = scan()
        self.assertEqual(diagnostic["moc_consistency_findings"], [])
        self.assertEqual(
            [(row["slug"], row["unlinked"]) for row in diagnostic["unlinked_children"]],
            [("biological-cell", ["organelle"])])
        cell = wiki / "biological-cell.md"
        cell.write_text(cell.read_text(encoding="utf-8").replace(
            "**Related:** [[biology|Biology]]",
            "**Related:** [[biology|Biology]] · [[organelle|Organelle]]"), encoding="utf-8")
        self.assertEqual(scan()["unlinked_children"], [])

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
issues: ""
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
        misc = mocs / "misc-moc.md"
        self.write_discipline_root("misc")
        tree = "- [[Wiki/misc|Misc]]\n  - [[Wiki/reference-label|Reference label]]\n"
        misc.write_text(tree, encoding="utf-8")
        entry.write_text(fallback.replace("parents: []", 'parents:\n  - "[[misc]]"'), encoding="utf-8")
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
                         .replace("parents: []", 'parents:\n  - "[[computer-science]]"'), encoding="utf-8")
        discipline = mocs / "computer-science-moc.md"
        self.write_discipline_root("computer-science")
        discipline.write_text(tree.replace("[[Wiki/misc|Misc]]", "[[Wiki/computer-science|Computer science]]"), encoding="utf-8")
        stale = scan()
        self.assertTrue(any(
            row.get("discipline") == "misc" and row.get("slug") == "reference-label"
            for row in stale["hierarchy_diagnostic"]["moc_consistency_findings"]))
        misc.write_text("- [[Wiki/misc|Misc]]\n", encoding="utf-8")
        tagged = scan()
        self.assertEqual(tagged["untagged_entries"], [])
        self.assertEqual(tagged["hierarchy_diagnostic"]["moc_consistency_findings"], [])
        self.assertFalse(any(row.get("discipline") == "misc" for row in
                             tagged["hierarchy_diagnostic"]["moc_inventory_findings"]))

        # Replacing a specific tag with #misc requires a Misc placement again, even when the old
        # discipline MOC and its matching parent still exist.
        entry.write_text(fallback.replace("parents: []", 'parents:\n  - "[[computer-science]]"'), encoding="utf-8")
        returning = scan()
        self.assertEqual(returning["hierarchy_diagnostic"]["placement_gaps"][0]["missing_disciplines"], ["misc"])
        entry.write_text(fallback.replace("parents: []", 'parents:\n  - "[[misc]]"'), encoding="utf-8")
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
        # A LEGACY research extract: current wiki-add writes none and cites an
        # online page by its URL, but an extract already cited by an entry
        # stays a valid source and keeps clipping-clean's ownership guards.
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
issues: ""
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
        # A new entry cites the researched online page itself, not an extract.
        created.write_text(r'''---
title: "Arithmetic mean"
type: Concept
sources:
  - "https://example.org/averages"
created: 2026-09-05
updated: 2026-09-05
description: "The arithmetic mean is the sum of a collection of numbers divided by its size."
tags:
  - "#mathematics"
parents: []
read: false
issues: ""
---
The **arithmetic mean** of a collection is its sum divided by its size.
For $n$ observations $x_i$:

$$
\bar{x}=\frac{1}{n}\sum_{i=1}^{n}x_i
$$

**Related:**

---

## Flashcards

The sum divided by the count, $n^{-1}\sum_i x_i$, for $n$ observations $x_i$.
??
Arithmetic mean
''', encoding="utf-8")
        lint = scratch / "topic-entry-lint.json"
        self.run_script("skills/wiki-build/scripts/lint_entry.py", created, "-o", lint)
        self.assertTrue(json.loads(lint.read_text(encoding="utf-8"))["summary"]["clean"])
        # The scanner accepts the same URL citation, and the builder's index
        # neither rejects it nor counts it as a citation of the legacy extract.
        scan = json.loads(self.run_script(
            "skills/wiki-lint/scripts/scan_vault.py", wiki,
            "--images", self.images).stdout)
        self.assertEqual([row for row in scan["problems"]
                          if row["slug"] == "arithmetic-mean"
                          and row["item"].startswith("item4")], [])
        self.run_script("skills/wiki-build/scripts/vault_index.py", wiki,
                        "--source", source.name, "-o", index)
        inventory = json.loads(index.read_text(encoding="utf-8"))
        self.assertEqual([row["slug"] for row in inventory["source_matches"]],
                         ["geometric-mean"])
        self.assertFalse(any(problem.startswith("arithmetic-mean.md:")
                             for problem in inventory["problems"]),
                         inventory["problems"])
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
        # The legacy extract stays a named URL owner that no reprocessing
        # exclusion can hide, even though the new entry cites the URL itself.
        self.assertEqual([Path(path).name for path in
                          ownership["checked"][0]["research_extracts"]],
                         [source.name])
        refused = json.loads(self.run_script(
            "skills/clipping-clean/scripts/dedup_index.py", self.notes,
            "--url", "https://example.org/averages", "--exclude", source,
            expected=1).stdout)
        self.assertIn("research extract", refused["error"])
        self.assertNotIn("checked", refused)
        self.assertEqual(source.read_bytes(), original_source)

    def test_topic_research_files_a_new_pdf_under_a_proven_free_name(self):
        # wiki-add's new-PDF path: the free-name checks run on the private
        # download, the PDF is filed exclusively against an `absent`
        # snapshot, and only the filed copy passes the intake gate.
        name = "Doe_Averages_2025"
        run = Path(self.scratch.name) / "research"
        run.mkdir()
        download = run / (name + ".pdf")
        self.make_pdf(download)
        canonical = self.run_script("shared/scripts/naming.py", "canonical",
                                    download.name).stdout
        self.assertIn("canonical", canonical)
        target = self.pdfs / download.name

        def owners(selected, expected):
            report = json.loads(self.run_script(
                "shared/scripts/vault_artifacts.py", "pdfs", "--vault",
                self.vault, "--selected", selected, expected=expected).stdout)
            self.assertTrue(report["complete"])
            return report["selection"]

        def stem_checks(expected):
            slug = json.loads(self.run_script(
                "skills/clipping-clean/scripts/dedup_index.py", self.notes,
                "--slug", name).stdout)["slug_checks"][0]["status"]
            preflight = json.loads(self.run_script(
                "skills/clipping-clean/scripts/fetch_images.py", "preflight",
                "--vault", self.vault, "--slug", name,
                expected=expected).stdout)
            return slug, preflight["ok"]

        free = owners(download, 1)
        self.assertEqual((free["matches"], free["unique"], free["reason"]),
                         ([], False, "no vault PDF owns this portable basename"))
        self.assertEqual(stem_checks(0), ("free", True))
        snapshots = run / "pdf-snapshots-1.json"
        recorded = json.loads(self.run_script(
            "shared/scripts/publish_files.py", "snapshot", "--vault",
            self.vault, "-o", snapshots, "Sources/PDFs/" + download.name).stdout)
        self.assertEqual(recorded["snapshots"][0]["state"], "absent")
        manifest = run / "pdf-manifest-1.json"
        manifest.write_text(json.dumps([
            {"path": "Sources/PDFs/" + download.name, "draft": str(download)},
        ]), encoding="utf-8")
        filed = json.loads(self.run_script(
            "shared/scripts/publish_files.py", "publish", "--vault",
            self.vault, "--snapshots", snapshots, "--manifest",
            manifest).stdout)
        self.assertEqual(filed["results"][0]["action"], "created")
        self.assertEqual(digest(target), digest(download))

        # The intake gate accepts the filed path; the same checks now report
        # the name taken, so a second download could not be filed over it.
        gate = owners(target, 0)
        self.assertTrue(gate["unique"])
        self.assertEqual([Path(path).name for path in gate["matches"]],
                         [download.name])
        taken = owners(download, 0)
        self.assertEqual([Path(path).resolve() for path in taken["matches"]],
                         [target.resolve()])
        self.assertEqual(stem_checks(1), ("free", False))

    def test_builder_and_linter_share_the_same_entry_contract_floor(self):
        wiki = self.vault / "Wiki"

        def write_entry(slug, title, body, *, type_="Concept", aliases=(),
                        source="[[Clean.pdf#page=1]]", sources=(),
                        description=None,
                        tags_block='tags:\n  - "#statistics"', card=None,
                        related=None, extra_cards=None):
            alias_yaml = ""
            if aliases:
                alias_yaml = "aliases:\n" + "".join(
                    f'  - "{alias}"\n' for alias in aliases)
            # Several double-quoted items, in order, replace the one `source`.
            source_yaml = "".join(f'  - "{item}"\n' for item in sources or (source,))
            footer = "\n\n**Related:**" + (f" {related}" if related else "")
            term = card if card is not None else title
            # Raw cards after the primary card, each block blank-line separated.
            more_cards = f"\n{extra_cards.rstrip()}\n" if extra_cards else ""
            text = f'''---
title: "{title}"
type: {type_}
{alias_yaml}sources:
{source_yaml}created: 2026-08-31
updated: 2026-08-31
description: "{description or title + ' is a synthetic alignment fixture.'}"
{tags_block}
parents: []
read: false
issues: ""
---
{body}{footer}

---

## Flashcards

A compact definition used only to exercise the shared contract.
??
{term}
{more_cards}'''
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
        # The acronym-expansion, bare-slug and cross-domain-alias floors are
        # shared checks (entry_checks.py); both tools must apply them alike.
        write_entry("mnist", "MNIST", "**MNIST** is a handwritten-digit dataset.")
        write_entry(
            "atp", "ATP", "**ATP** (adenosine triphosphate) carries energy.",
            aliases=("adenosine-triphosphate",),
            card="ATP (adenosine triphosphate)")
        write_entry(
            "tree-of-life", "Tree of life", "The **tree of life** models descent.")
        write_entry(
            "entropy-information-theory", "Entropy (information theory)",
            "**Entropy** is the expected information content of a variable.",
            aliases=("entropy",), card="Entropy")
        write_entry(
            "online-machine-learning", "Online machine learning",
            "**Online machine learning** updates a model one instance at a time.",
            aliases=("online-learning",))
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
        # The card set: one `??` definition card per entry. A further card is
        # an extra card that the run removes; a card simplified to `?` needs
        # its `??`.
        write_entry(
            "extra-cards", "Extra cards",
            "**Extra cards** is a deliberately malformed fixture.",
            extra_cards=(
                "Another claim about the fixture, stated once.\n??\nOther term\n\n"
                "Why does the fixture exist?\n?\nTo carry a legacy question card."))
        # With no definition card, the run rewrites the first card into it and
        # removes the rest; it never asks to keep every card.
        write_entry(
            "no-definition-card", "No definition card",
            "**No definition card** is a deliberately malformed fixture.",
            card="Other term",
            extra_cards="Why does the fixture exist?\n?\nTo carry a legacy question card.")
        write_entry(
            "simplified-primary", "Simplified primary",
            "**Simplified primary** is a deliberately malformed fixture.")
        simplified_primary = wiki / "simplified-primary.md"
        simplified_primary.write_text(
            simplified_primary.read_text(encoding="utf-8").replace(
                "\n??\n", "\n?\n", 1),
            encoding="utf-8")
        card_set_faults = {
            "extra-cards": "holds 3 cards",
            "no-definition-card": "rewrite the first card into the definition card",
            "simplified-primary": "must be exactly",
        }
        # An online page is cited by its full http(s) URL (CONVENTIONS
        # section 7), alone or beside local sources. A URL whose path ends in a
        # local stem names no vault document, so it pairs with no note.
        url_clean = {
            "web-only-source": ("Web only source",
                                ("https://arxiv.org/abs/2305.18290",)),
            "web-and-paper-sources": ("Web and paper sources",
                                      ("https://arxiv.org/abs/2305.18290",
                                       "[[Clean.pdf#page=2]]")),
            "plain-web-source": ("Plain web source",
                                 ("http://example.org:8080/notes/page?q=1#part",)),
            "web-file-beside-note": ("Web file beside note",
                                     ("https://example.org/files/Clean.pdf",
                                      "[[Clean.md]]")),
        }
        url_faults = {
            "repeated-web-source": ("Repeated web source",
                                    ("https://example.org/a", "https://example.org/a")),
            "file-transfer-source": ("File transfer source",
                                     ("ftp://example.org/Clean.pdf",)),
            "spaced-web-source": ("Spaced web source", ("https://example.org/a b",)),
            "linked-label-source": ("Linked label source",
                                    ("[Averages](https://example.org/averages)",)),
        }
        for slug, (title, items) in {**url_clean, **url_faults}.items():
            write_entry(slug, title, f"**{title}** is a source-form fixture.",
                        sources=items)
        # A valid URL spelled as a bare YAML item is a quoting fault only.
        write_entry(
            "unquoted-web-source", "Unquoted web source",
            "**Unquoted web source** is a source-form fixture.",
            source="https://example.org/unquoted")
        unquoted_web = wiki / "unquoted-web-source.md"
        unquoted_web.write_text(
            unquoted_web.read_text(encoding="utf-8").replace(
                '  - "https://example.org/unquoted"',
                "  - https://example.org/unquoted", 1),
            encoding="utf-8")
        # A split book is cited in one form: both checkers pair a chapter PDF
        # with its whole-book PDF.
        write_entry(
            "book-beside-chapter", "Book beside chapter",
            "**Book beside chapter** is a source-form fixture.",
            sources=("[[Prince_UDL_2026.pdf#page=40]]",
                     "[[Prince_UDL_2026_02_SupLearn.pdf#page=3]]"))

        lint = json.loads(self.run_script(
            "skills/wiki-build/scripts/lint_entry.py", wiki, "--compact").stdout)
        lint_findings = {Path(entry["file"]).stem: entry["findings"]
                         for entry in lint["entries"]}
        lint_items = {
            stem: {finding["item"] for finding in findings}
            for stem, findings in lint_findings.items()
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
                     "canonical-code-shapes", "atp"):
            self.assertEqual(lint_items[slug], set(), slug)
        for slug, item in (("mnist", "9-acronym-expansion"),
                           ("tree-of-life", "5-bare-common-noun")):
            self.assertIn(item, lint_items[slug], (slug, lint_findings[slug]))
        for slug in ("entropy-information-theory", "online-machine-learning"):
            self.assertTrue(any(
                finding["item"] == "18-alias-form"
                and "bare cross-domain term" in finding["message"]
                for finding in lint_findings[slug]), (slug, lint_findings[slug]))
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
        for slug, fragment in card_set_faults.items():
            self.assertTrue(any(
                finding["item"] == "19-flashcards" and fragment in finding["message"]
                for finding in lint_findings[slug]), (slug, lint_findings[slug]))
        # An extra card is a fixable error on a builder draft: the run keeps
        # the one definition card and removes the rest. An extra card's own
        # findings ask only for its removal, never for its separator to
        # change; the scanner below agrees.
        set_findings = [finding for finding in lint_findings["extra-cards"]
                        if finding["item"] == "19-flashcards"
                        and "holds 3 cards" in finding["message"]]
        self.assertEqual(len(set_findings), 1, lint_findings["extra-cards"])
        self.assertEqual(set_findings[0]["severity"], "error", set_findings)
        self.assertFalse(set_findings[0]["evidence"].get("report_only"),
                         set_findings)
        self.assertIn("keep it, remove every other card and quote each "
                      "removed card verbatim, attachments included, in the "
                      "report", set_findings[0]["message"], set_findings)
        extra_findings = [finding for finding in lint_findings["extra-cards"]
                          if (finding.get("evidence") or {}).get("card") == 3]
        self.assertTrue(extra_findings, lint_findings["extra-cards"])
        for finding in extra_findings:
            self.assertFalse(finding["evidence"].get("report_only"), finding)
            self.assertIn("extra card 3", finding["message"], finding)
            self.assertIn("remove this extra card", finding["message"], finding)
            self.assertNotIn("must be exactly", finding["message"])
        self.assertFalse([finding for finding in lint_findings["extra-cards"]
                          if (finding.get("evidence") or {}).get("card") == 1],
                         lint_findings["extra-cards"])
        for slug in ("extra-cards", "no-definition-card"):
            for finding in lint_findings[slug]:
                for retired in ("report-only", "never repair",
                                "preserve every"):
                    self.assertNotIn(retired, finding["message"], finding)
        no_definition = [finding for finding in lint_findings["no-definition-card"]
                         if "no card carries the primary answer" in finding["message"]]
        self.assertEqual(len(no_definition), 1, lint_findings["no-definition-card"])
        self.assertEqual(no_definition[0]["severity"], "error", no_definition)
        self.assertIn('"No definition card"', no_definition[0]["message"])
        self.assertIn("remove every other card", no_definition[0]["message"])
        # The card the run removes asks only for its removal, never for its
        # own `?` separator to become `??`.
        doomed = [finding for finding in lint_findings["no-definition-card"]
                  if (finding.get("evidence") or {}).get("card") == 2]
        self.assertTrue(doomed, lint_findings["no-definition-card"])
        for finding in doomed:
            self.assertTrue(finding["evidence"].get("extra_card"), finding)
            self.assertIn("extra card 2", finding["message"], finding)
            self.assertIn("remove this extra card", finding["message"], finding)
            self.assertNotIn("must be exactly", finding["message"], finding)

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
                     "canonical-code-shapes", "atp"):
            self.assertEqual(scan_items.get(slug, set()), set(), slug)
        self.assertIn("item9/acronym-expansion", scan_items.get("mnist", set()))
        self.assertTrue(any(
            problem["slug"] == "tree-of-life" and problem["item"] == "item5"
            and "bare-slug" in problem["message"]
            for problem in scan["problems"]), scan_items.get("tree-of-life"))
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
        for slug, fragment in card_set_faults.items():
            self.assertTrue(any(
                problem["slug"] == slug and problem["item"] == "item19"
                and fragment in problem["message"]
                for problem in scan["problems"]), slug)
        extra_messages = [problem["message"] for problem in scan["problems"]
                          if problem["slug"] == "extra-cards"]
        extra_problems = [message for message in extra_messages
                          if "card 3" in message]
        self.assertTrue(extra_problems, extra_messages)
        self.assertTrue(any(
            problem["slug"] == "extra-cards"
            and "holds 3 cards" in problem["message"]
            and "keep it, remove every other card and quote each removed "
            "card verbatim, attachments included, in the report"
            in problem["message"]
            for problem in scan["problems"]), extra_messages)
        for message in extra_problems:
            self.assertIn("extra card 3", message)
            self.assertIn("remove this extra card", message)
            self.assertNotIn("must be exactly", message)
        self.assertFalse([message for message in extra_messages
                          if "card 1" in message], extra_messages)
        for problem in scan["problems"]:
            if problem["slug"] in ("extra-cards", "no-definition-card"):
                for retired in ("report-only", "never repair",
                                "preserve every"):
                    self.assertNotIn(retired, problem["message"], problem)
        self.assertTrue(any(
            problem["slug"] == "no-definition-card"
            and 'no card carries the primary answer "No definition card"'
            in problem["message"]
            and "remove every other card" in problem["message"]
            for problem in scan["problems"]), scan_items.get("no-definition-card"))
        doomed = [problem["message"] for problem in scan["problems"]
                  if problem["slug"] == "no-definition-card"
                  and "card 2" in problem["message"]]
        self.assertTrue(doomed, scan_items.get("no-definition-card"))
        for message in doomed:
            self.assertTrue(message.startswith(
                "extra card 2 (remove this extra card"), message)
            self.assertNotIn("must be exactly", message)
        for slug in ("related-anchored", "related-wrong-label"):
            self.assertIn("item11", scan_items.get(slug, set()), scan_items.get(slug))
        self.assertNotIn("item10/dup",
                         scan_items.get("duplicate-link-forms", set()))
        # Both checkers share one source-form predicate: the same URL items
        # pass, and the same repeated or malformed items fail.
        for slug in url_clean:
            self.assertEqual(lint_items[slug], set(), (slug, lint_findings[slug]))
            self.assertEqual(scan_items.get(slug, set()), set(), slug)
        for slug in url_faults:
            self.assertIn("4-sources", lint_items[slug], slug)
            self.assertIn("item4", scan_items.get(slug, set()), slug)
        self.assertTrue(any(
            finding["item"] == "4-sources" and "listed 2 times" in finding["message"]
            for finding in lint_findings["repeated-web-source"]))
        self.assertIn(
            'source "https://example.org/a" is listed 2 times',
            " ".join(problem["message"] for problem in scan["problems"]
                     if problem["slug"] == "repeated-web-source"))
        self.assertNotIn("4-duplicate-source", lint_items["web-file-beside-note"])
        self.assertNotIn("item4/source-identity",
                         scan_items.get("web-file-beside-note", set()))
        self.assertIn("4-duplicate-source", lint_items["book-beside-chapter"])
        self.assertIn("item4/source-identity",
                      scan_items.get("book-beside-chapter", set()))
        # Obsidian's Properties editor strips the quotes from a URL source;
        # both validators accept the lossless plain spelling (CONVENTIONS §2a).
        self.assertNotIn("2-quoting", lint_items["unquoted-web-source"])
        self.assertNotIn("4-sources", lint_items["unquoted-web-source"])
        self.assertNotIn("item2", scan_items.get("unquoted-web-source", set()))
        self.assertNotIn("item4", scan_items.get("unquoted-web-source", set()))
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
        for slug in ("entropy-information-theory", "online-machine-learning"):
            self.assertIn("item18/cross-domain-alias",
                          scan_items.get(slug, set()), slug)
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
        # The index records a URL as provenance, not as a malformed local
        # reference, while the malformed forms stay index problems.
        for slug in (*url_clean, "repeated-web-source", "unquoted-web-source"):
            self.assertFalse(any(problem.startswith(f"{slug}.md: sources:")
                                 for problem in index["problems"]), slug)
        for slug in ("file-transfer-source", "spaced-web-source",
                     "linked-label-source"):
            self.assertTrue(any(problem.startswith(f"{slug}.md: sources:")
                                for problem in index["problems"]), slug)
        # A source query matches only the local citation, never a URL whose
        # path happens to end in the queried filename.
        clean_matches = {match["slug"]: match["sources"] for match in json.loads(
            self.run_script("skills/wiki-build/scripts/vault_index.py", wiki,
                            "--source", "Clean.pdf").stdout)["source_matches"]}
        self.assertEqual(clean_matches.get("web-and-paper-sources"),
                         ["[[Clean.pdf#page=2]]"])
        for slug in ("web-only-source", "plain-web-source", "web-file-beside-note"):
            self.assertNotIn(slug, clean_matches)

    def test_builder_and_linter_agree_on_parents_form_and_empty_sources(self):
        # lint_entry's 2-parents-form agrees with the scanner's
        # item2/parents-form and its moc-parent and root-parent-mismatch
        # hierarchy findings on a value's form. Resolving a target's case or
        # path spelling needs the vault inventory, so only the scan does it.
        # Both file an empty sources: under item 4 and a missing key under
        # item 2.
        wiki = self.vault / "Wiki"
        (self.vault / "MOCs").mkdir()
        (self.vault / "MOCs/mathematics-moc.md").write_text(
            "- [[Wiki/mathematics|Mathematics]]\n", encoding="utf-8")
        canonical_parents = "parents: []\n"
        canonical_sources = 'sources:\n  - "https://example.org/averages"\n'
        form = ({"item2/parents-form"}, set(), {"2-parents-form"})
        cases = {
            # slug: (title, parents block, sources block,
            #        scanner item-2 keys, hierarchy kinds, builder 2-* items)
            "mathematics": ("Mathematics", canonical_parents,
                            canonical_sources, set(), set(), set()),
            "statistics": ("Statistics", 'parents:\n  - "[[mathematics]]"\n',
                           canonical_sources, set(), {"root-parent-mismatch"},
                           {"2-parents-form"}),
            "arithmetic-mean": ("Arithmetic mean",
                                'parents:\n  - "[[mathematics]]"\n',
                                canonical_sources, set(), set(), set()),
            "geometric-mean": ("Geometric mean",
                               'parents: ["[[mathematics]]"]\n',
                               canonical_sources, *form),
            "harmonic-mean": ("Harmonic mean", 'parents: "[[mathematics]]"\n',
                              canonical_sources, *form),
            "midrange": ("Midrange", "parents: [ ]\n", canonical_sources, *form),
            "midhinge": ("Midhinge", 'parents:\n  - "mathematics"\n',
                         canonical_sources, *form),
            "trimean": ("Trimean",
                        'parents:\n  - "[[mathematics|Mathematics]]"\n',
                        canonical_sources, *form),
            "power-mean": ("Power mean",
                           'parents:\n  - "[[mathematics#History]]"\n',
                           canonical_sources, *form),
            "lehmer-mean": ("Lehmer mean",
                            'parents:\n  - "[[mathematics.md]]"\n',
                            canonical_sources, *form),
            "chisini-mean": ("Chisini mean",
                             'parents:\n  - "[[mathematics]]"\n'
                             '  - "[[mathematics]]"\n',
                             canonical_sources, *form),
            "quadratic-mean": ("Quadratic mean",
                               'parents:\n  - "[[MOCs/mathematics-moc]]"\n',
                               canonical_sources, set(), {"moc-parent"},
                               {"2-parents-form"}),
            "contraharmonic-mean": ("Contraharmonic mean",
                                    'parents:\n  - "[[Mathematics]]"\n',
                                    canonical_sources, {"item2/parents-form"},
                                    set(), set()),
            "heronian-mean": ("Heronian mean",
                              'parents:\n  - "[[Wiki/mathematics]]"\n',
                              canonical_sources, {"item2/parents-form"},
                              set(), set()),
            "weighted-mean": ("Weighted mean", canonical_parents, "sources: []\n",
                              set(), set(), set()),
            "truncated-mean": ("Truncated mean", canonical_parents, "sources:\n",
                               set(), set(), set()),
            "trimmed-mean": ("Trimmed mean", canonical_parents, "",
                             {"item2"}, set(), {"2-field-order"}),
        }
        for slug, (title, parents, sources, *_expected) in cases.items():
            text = self.averages_entry(
                title, "2026-09-05",
                f"The **{title.lower()}** is a synthetic fixture for one "
                "parents: or sources: spelling.",
                "A synthetic fixture for one parents: or sources: spelling.")
            text = text.replace('"#mathematics"', '"#statistics"') \
                if slug == "statistics" else text
            self.assertIn(canonical_parents, text)
            self.assertIn(canonical_sources, text)
            (wiki / f"{slug}.md").write_text(
                text.replace(canonical_parents, parents)
                .replace(canonical_sources, sources), encoding="utf-8")

        scan = json.loads(self.run_script(
            "skills/wiki-lint/scripts/scan_vault.py", wiki,
            "--images", self.images).stdout)
        lint = json.loads(self.run_script(
            "skills/wiki-build/scripts/lint_entry.py", wiki, "--compact").stdout)
        built = {Path(row["file"]).stem: row["findings"]
                 for row in lint["entries"]}
        hierarchy = scan["hierarchy_diagnostic"]["parent_state_findings"]
        for slug, (*_spelling, scan_keys, kinds, lint_keys) in cases.items():
            with self.subTest(slug=slug):
                rows = [row for row in scan["problems"] if row["slug"] == slug]
                self.assertEqual({row["item"] for row in rows
                                  if row["item"].split("/")[0] == "item2"},
                                 scan_keys, rows)
                self.assertEqual({row["kind"] for row in hierarchy
                                  if row["slug"] == slug
                                  and row["kind"] in ("moc-parent",
                                                      "root-parent-mismatch")},
                                 kinds, hierarchy)
                findings = built[slug]
                self.assertEqual({row["item"] for row in findings
                                  if row["item"].startswith("2-")},
                                 lint_keys, findings)
                empty = slug in ("weighted-mean", "truncated-mean",
                                 "trimmed-mean")
                self.assertEqual(any(row["item"] == "item4"
                                     and "sources: is empty" in row["message"]
                                     for row in rows), empty, rows)
                self.assertEqual(any(row["item"] == "4-sources"
                                     and "sources: is empty" in row["message"]
                                     for row in findings),
                                 slug in ("weighted-mean", "truncated-mean"),
                                 findings)
        self.assertTrue(any(row["message"] == "missing sources: key"
                            for row in scan["problems"]
                            if row["slug"] == "trimmed-mean"))
        self.assertEqual([row["message"] for row in built["trimmed-mean"]
                          if row["item"] == "2-field-order"],
                         ["mandatory key 'sources' is missing (the key is never "
                          "omitted, even when the value is blank)"])

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
issues: ""
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

        # A noncanonical display is a form finding, never a missing one; a
        # backslash ending a display's last line once crashed both tools.
        entry.write_text(equationless.replace(
            "$\\operatorname{Var}(X)$.\n",
            "$\\operatorname{Var}(X)$:\n\n"
            "$$\\sigma = \\sqrt{\\operatorname{Var}(X)}\n$$\n\n"
            "Squaring both sides gives the variance back:\n\n"
            "$$\n\\sigma^2 = \\operatorname{Var}(X) \\\n$$\n"),
            encoding="utf-8")
        builder = json.loads(self.run_script(
            "skills/wiki-build/scripts/lint_entry.py", entry,
            "--compact").stdout)
        builder_items = {finding["item"]
                         for finding in builder["entries"][0]["findings"]}
        self.assertIn("12-equation-format", builder_items)
        self.assertNotIn("12-equation-coverage-candidate", builder_items)
        self.assertNotIn("0-lint-error", builder_items)
        scanner = json.loads(self.run_script(
            "skills/wiki-lint/scripts/scan_vault.py", self.vault / "Wiki",
            "--indent", "0").stdout)
        scanner_items = {problem["item"] for problem in scanner["problems"]
                         if problem["slug"] == "synthetic-deviation"}
        self.assertIn("item12/equation-format", scanner_items)
        self.assertNotIn("item12/equation-coverage-candidate", scanner_items)


if __name__ == "__main__":
    unittest.main()
