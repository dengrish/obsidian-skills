#!/usr/bin/env python3
"""Exercise cross-skill handoffs through the public CLIs in isolated vaults.

Run with the interpreter holding requirements-dev.txt. No live vault, network,
host configuration or installed plugin cache is used.
"""

import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
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
        result = subprocess.run(
            [sys.executable, str(ROOT / relative), *map(str, args)],
            cwd=self.vault, env=self.env, capture_output=True, text=True,
            encoding="utf-8", timeout=60)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

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
            "skills/paper-summarizer/scripts/paper_scan.py", "--src", self.pdfs,
            "--notes", self.notes, "--images", self.images, "--json").stdout)

    def test_paper_note_lint_applies_the_selected_nonempirical_mode(self):
        note = self.notes / "Doe_Correction_2025.md"
        note.write_text(notice_note("Doe_Correction_2025"),
                        encoding="utf-8", newline="\n")
        missing_mode = self.run_script(
            "skills/paper-summarizer/scripts/note_lint.py", note, expected=2)
        self.assertIn("--mode is required", missing_mode.stderr)
        self.run_script("skills/paper-summarizer/scripts/note_lint.py", note,
                        "--mode", "notice")

    def test_pdf_repair_and_rename_preserve_notes_images_and_ledgers(self):
        organizer = "skills/pdf-organizer/scripts/organize.py"
        batch = "skills/pdf-figure-extractor/scripts/batch_extract.py"
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
        self.run_script("skills/pdf-figure-extractor/scripts/extract_figures.py", pdf,
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
        self.run_script("skills/paper-summarizer/scripts/note_lint.py", note,
                        "--mode", "empirical", "--images", self.images)
        self.assertEqual(self.scan_papers()["counts"]["done"], 1)
        references = self.vault / "Wiki/reference.md"
        references.write_text("[[Doe_Study_2025.md]]\n[[Doe_Study_2025.pdf#page=1]]\n",
                              encoding="utf-8")
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
        for filename in (".figure-manifest.tsv", ".figure-review.txt"):
            record = (self.images / filename).read_text(encoding="utf-8")
            self.assertIn("Doe_Renamed_2025", record)
            self.assertNotIn("Doe_Study_2025", record)
        self.run_script(batch, "--src", renamed, "--out", self.images, "--dpi", 72)
        self.assertEqual(digest(renamed_figure), repaired)
        self.run_script("skills/paper-summarizer/scripts/note_lint.py", renamed_note,
                        "--mode", "empirical", "--images", self.images)
        self.assertEqual(self.scan_papers()["counts"]["done"], 1)

    def test_pdf_year_rename_keeps_owned_summary_metadata_aligned(self):
        organizer = "skills/pdf-organizer/scripts/organize.py"
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
        self.run_script("skills/paper-summarizer/scripts/note_lint.py", note,
                        "--mode", "notice")

        self.run_script(
            organizer, "rename", "--vault", self.vault, source,
            "--to", "Doe_Correction_nd.pdf", "--apply")
        source = self.pdfs / "Doe_Correction_nd.pdf"
        note = self.notes / "Doe_Correction_nd.md"
        self.assertIn("published: null", note.read_text(encoding="utf-8"))
        self.run_script("skills/paper-summarizer/scripts/note_lint.py", note,
                        "--mode", "notice")

        self.run_script(
            organizer, "rename", "--vault", self.vault, source,
            "--to", "Doe_Correction_2027.pdf", "--apply")
        note = self.notes / "Doe_Correction_2027.md"
        self.assertIn("published: 2027-01-01",
                      note.read_text(encoding="utf-8"))
        self.assertIn("published: 1999-12-31",
                      citing_note.read_text(encoding="utf-8"))
        self.run_script("skills/paper-summarizer/scripts/note_lint.py", note,
                        "--mode", "notice")

    def test_canonical_inbox_pdf_can_be_filed_without_changing_identity(self):
        source = self.vault / "Inbox/Doe_Study_2025.pdf"
        self.make_pdf(source)
        original = digest(source)
        self.run_script("skills/pdf-organizer/scripts/organize.py", "rename",
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
        self.run_script("skills/pdf-organizer/scripts/organize.py", "split", book,
                        "--chapters", chapter_plan, "--out", chapter_dir,
                        "--vault", self.vault)
        chapter_paths = [chapter_dir / item["filename"] for item in chapters]
        self.assertTrue(all(path.is_file() for path in chapter_paths))

        sweep = self.scan_papers()
        self.assertEqual(sweep["counts"]["book"], 1)
        self.assertEqual(sweep["counts"]["chapter"], 2)
        selected = json.loads(self.run_script(
            "skills/paper-summarizer/scripts/paper_scan.py",
            "--src", chapter_paths[0], "--notes", self.notes,
            "--images", self.images, "--json").stdout)
        self.assertEqual(selected["counts"]["new"], 1)
        self.run_script("skills/pdf-figure-extractor/scripts/batch_extract.py",
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
        batch = "skills/pdf-figure-extractor/scripts/batch_extract.py"
        self.run_script(batch, "--src", self.pdfs, "--out", self.images,
                        "--dpi", 72, expected=1)
        self.assertEqual(list(self.images.iterdir()), [])
        self.assertEqual({path: digest(path) for path in sources}, original)

        self.run_script("skills/pdf-organizer/scripts/organize.py", "rename",
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
        self.run_script("skills/pdf-figure-extractor/scripts/batch_extract.py",
                        "--src", source, "--out", self.images, "--dpi", 72)
        figure = self.images / "Doe_Study_2025_fig_1.png"
        note = self.notes / "Doe_Study_2025.md"
        body = summary_note(source.stem).replace(
            'sources:\n  - "[[Doe_Study_2025.pdf]]"',
            'sources: # recorded origin\n- "[[\\x44oe_Study_2025.pdf]]" # verified')
        note.write_text(body, encoding="utf-8", newline="\n")
        self.assertEqual(self.scan_papers()["counts"]["done"], 1)
        self.run_script("skills/paper-summarizer/scripts/note_lint.py", note,
                        "--mode", "empirical", "--images", self.images)
        original = digest(figure)
        self.run_script("skills/pdf-organizer/scripts/organize.py", "rename",
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
        self.run_script("skills/paper-summarizer/scripts/note_lint.py", renamed_note,
                        "--mode", "empirical", "--images", self.images)

    def test_pdf_rename_preserves_publisher_urls_and_foreign_clipping(self):
        source = self.vault / "Inbox/download.pdf"
        self.make_pdf(source)
        clipping = self.notes / "download.md"
        clipping.write_text(
            "---\nsources: # capture\n- 'https://example.org/O''Reilly/download.pdf'\n"
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
        self.run_script("skills/pdf-organizer/scripts/organize.py", "rename",
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
        self.run_script("skills/pdf-organizer/scripts/organize.py", "rename",
                        "--vault", self.vault, source,
                        "--to", "Doe_Study_2025.pdf", "--dest", self.pdfs, "--apply")
        self.assertTrue((self.pdfs / "Doe_Study_2025.pdf").is_file())
        self.assertEqual(digest(clipping), before[clipping])
        self.assertEqual(digest(relocated), before[figure])
        self.assertEqual(reference.read_text(encoding="utf-8"),
                         f'[[Doe_Study_2025.pdf#page=1]]\n[Publisher]({publisher})\n')

    def test_clipping_slug_requires_a_date_decision_and_supports_undated(self):
        script = "skills/clipping-processor/scripts/slug.py"
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
        fetch = "skills/clipping-processor/scripts/fetch_images.py"
        dedup = "skills/clipping-processor/scripts/dedup_index.py"

        def clipping_slug(topic):
            result = json.loads(self.run_script(
                "skills/clipping-processor/scripts/slug.py",
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
        self.run_script("skills/pdf-figure-extractor/scripts/batch_extract.py",
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
            f'[[{old}|the clipping]]\n![[Sources/Images/{old}_fig_1.png]]\n',
            encoding="utf-8")
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
            f'[[{new}|the clipping]]\n![[Sources/Images/{new}_fig_1.png]]\n',
            encoding="utf-8")
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
            "skills/clipping-processor/scripts/dedup_index.py", articles,
            "--raw", raw, "--slug", "Doe_Fresh_Article_2025").stdout)
        self.assertEqual(dedup["checked"][0]["status"], "new")
        self.assertEqual(dedup["slug_checks"][0]["status"], "free")
        papers = json.loads(self.run_script(
            "skills/paper-summarizer/scripts/paper_scan.py", "--src", pdfs,
            "--notes", articles, "--images", images, "--json").stdout)
        self.assertEqual(papers["counts"]["new"], 1)
        self.assertFalse((fresh / "Wiki").exists())

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
            "skills/paper-summarizer/scripts/paper_text.py", source,
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
  - "[[biology-moc]]"
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
        # Freeze the existing vault format independently of scanner constants:
        # renaming the skill must still recognize previously managed MOCs.
        (self.vault / "biology-moc.md").write_text(
            "<!-- wiki-linter:moc-tree:start -->\n"
            "- [[control-sample|Control sample]]\n"
            "<!-- wiki-linter:moc-tree:end -->\n", encoding="utf-8")
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
        marker_states = {row["discipline"]: row["state"] for row in
                         report["hierarchy_diagnostic"]["moc_marker_states"]}
        self.assertEqual(marker_states["biology"], "marked")
        self.assertEqual(report["hierarchy_diagnostic"]["moc_consistency_findings"], [])

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
            "skills/clipping-processor/scripts/dedup_index.py", self.notes,
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
        self.assertIn("item17/alias-candidate",
                      scan_items.get("introduced-alias", set()))
        self.assertIn("item7", scan_items.get("two-sentence-description", set()))
        self.assertIn("item1", scan_items.get("malformed-flow-list", set()))
        self.assertIn("item9", scan_items.get("malformed-person-date", set()))
        self.assertIn("item16", scan_items.get("bare-code-shapes", set()))
        for slug in ("related-anchored", "related-wrong-label"):
            self.assertIn("item11", scan_items.get(slug, set()), scan_items.get(slug))
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
