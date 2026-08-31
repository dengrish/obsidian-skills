#!/usr/bin/env python3
"""Exercise cross-skill handoffs through the public CLIs in isolated vaults.

Run with the interpreter holding requirements-dev.txt. No live vault, network,
host configuration or installed plugin cache is used.
"""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import yaml

try:
    import pymupdf
except ImportError:
    import fitz as pymupdf
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
            cwd=self.vault, env=self.env, capture_output=True, text=True, timeout=60)
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
        note.write_text(summary_note(pdf.stem), encoding="utf-8")
        self.run_script("skills/paper-summarizer/scripts/note_lint.py", note,
                        "--images", self.images)
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
                        "--images", self.images)
        self.assertEqual(self.scan_papers()["counts"]["done"], 1)

    def test_canonical_inbox_pdf_can_be_filed_without_changing_identity(self):
        source = self.vault / "Inbox/Doe_Study_2025.pdf"
        self.make_pdf(source)
        original = digest(source)
        self.run_script("skills/pdf-organizer/scripts/organize.py", "rename",
                        "--vault", self.vault, source, "--to", source.name,
                        "--dest", self.pdfs, "--apply")
        self.assertFalse(source.exists())
        self.assertEqual(digest(self.pdfs / source.name), original)

    def test_clipping_image_reprocess_keeps_duplicate_detection_and_stems_aligned(self):
        fetch = "skills/clipping-processor/scripts/fetch_images.py"
        dedup = "skills/clipping-processor/scripts/dedup_index.py"
        old, new = "Smith_Cell_Signals_2026", "Smith_Cell_Receptors_2026"
        raw = self.vault / "Inbox/capture.md"
        raw.write_text('---\nsources:\n  - "https://example.org/study?utm_source=clip"\n---\nBody.\n',
                       encoding="utf-8")

        def verdict(exclude=None):
            args = [self.notes, "--raw", raw]
            if exclude:
                args.extend(["--exclude", exclude])
            return json.loads(self.run_script(dedup, *args).stdout)["checked"][0]

        self.assertEqual(verdict()["status"], "new")
        rendered = Path(self.scratch.name) / "browser render.png"
        Image.new("RGB", (64, 48), (20, 100, 180)).save(rendered)
        self.run_script(fetch, "place", "--attachments", self.images,
                        "--slug", old, "--index", 1, "--from-file", rendered)
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
        note = self.notes / (old + ".md")
        # Default YAML serialization uses valid, indentless block lists.
        # Duplicate detection must survive that representation too.
        metadata = {"title": "Cell signals", "format": "Article",
                    "sources": ["https://example.org/study"], "read": True}
        body = ('---\n' + yaml.safe_dump(metadata, sort_keys=False) + '---\n'
                + f'![[{old}_fig_1.png]]\n*The cells exchange signals.*\n')
        note.write_text(body, encoding="utf-8")
        self.assertEqual(verdict()["status"], "duplicate")
        self.assertEqual(verdict(note)["status"], "new")
        rename = ["rename", "--attachments", self.images, "--sources", self.pdfs,
                  "--old-slug", old, "--new-slug", new]
        self.run_script(fetch, *rename, "--dry-run")
        self.assertEqual(digest(image), original)
        self.run_script(fetch, *rename)
        note.rename(self.notes / (new + ".md"))
        (self.notes / (new + ".md")).write_text(body.replace(old, new), encoding="utf-8")
        self.assertFalse(image.exists())
        self.assertEqual(digest(self.images / (new + "_fig_1.png")), original)
        current = verdict()
        self.assertEqual(current["status"], "duplicate")
        self.assertEqual(current["matches"], [str(self.notes / (new + ".md"))])

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

---

## Flashcards

An untreated experimental specimen prepared and measured like the treated group to provide a baseline.
??
Control sample
''', encoding="utf-8")
        (self.vault / "biology-moc.md").write_text(
            "- [[control-sample|Control sample]]\n", encoding="utf-8")
        index = self.vault / "index.json"
        self.run_script("skills/wiki-builder/scripts/vault_index.py", wiki, "-o", index)
        self.assertEqual(json.loads(index.read_text())["entry_count"], 1)
        candidates = self.vault / "candidates.json"
        candidates.write_text(json.dumps(["Control sample", "Unrelated device"]))
        collisions = json.loads(self.run_script(
            "skills/wiki-builder/scripts/find_collisions.py", "--index", index,
            "--titles", candidates).stdout)
        self.assertEqual([r["verdict"] for r in collisions["results"]], ["merge", "create"])
        lint = self.vault / "lint.json"
        self.run_script("skills/wiki-builder/scripts/lint_entry.py", wiki, "-o", lint)
        self.assertTrue(json.loads(lint.read_text())["summary"]["clean"])
        scan = self.vault / "scan.json"
        self.run_script("skills/wiki-linter/scripts/scan_vault.py", wiki,
                        "--images", self.images, "--out", scan)
        report = json.loads(scan.read_text())
        self.assertEqual(report["problems"], [])
        self.assertEqual(report["backfill_candidates"], [])
        for key in ("self_parented", "parent_cycles"):
            self.assertEqual(report["hierarchy_diagnostic"][key], [])


if __name__ == "__main__":
    unittest.main()
