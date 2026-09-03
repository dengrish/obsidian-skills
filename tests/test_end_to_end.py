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
        note.write_text(body, encoding="utf-8")
        self.assertEqual(self.scan_papers()["counts"]["done"], 1)
        self.run_script("skills/paper-summarizer/scripts/note_lint.py", note,
                        "--images", self.images)
        original = digest(figure)
        self.run_script("skills/pdf-organizer/scripts/organize.py", "rename",
                        "--vault", self.vault, source,
                        "--to", "Doe_Renamed_2025.pdf", "--apply")
        renamed_note = self.notes / "Doe_Renamed_2025.md"
        metadata = yaml.safe_load(renamed_note.read_text().split("---", 2)[1])
        self.assertEqual(metadata["sources"], ["[[Doe_Renamed_2025.pdf]]"])
        self.assertTrue(metadata["read"])
        self.assertEqual(str(metadata["created"]), "2026-08-30")
        self.assertEqual(digest(self.images / "Doe_Renamed_2025_fig_1.png"), original)
        self.assertEqual(self.scan_papers()["counts"]["done"], 1)
        self.run_script("skills/paper-summarizer/scripts/note_lint.py", renamed_note,
                        "--images", self.images)

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
        self.assertEqual(reference.read_text(),
                         f'[[Doe_Study_2025.pdf#page=1]]\n[Publisher]({publisher})\n')

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
                  "--owner-note", note,
                  "--old-slug", old, "--new-slug", new]
        external = self.vault / "Wiki/clipping-reference.md"
        external.write_text(
            f'[[{old}|the clipping]]\n![[Sources/Images/{old}_fig_1.png]]\n',
            encoding="utf-8")
        blocked = json.loads(self.run_script(
            fetch, *rename, "--dry-run", expected=1).stdout)
        self.assertEqual(blocked["renamed"], 0)
        self.assertEqual(blocked["failed"], 1)
        self.assertEqual(blocked["results"][0]["dependency_blockers"], [{
            "path": str(external.resolve()),
            "references": [old + ".md", old + "_fig_1.png"],
        }])
        dependency = json.loads(self.run_script(
            fetch, "dependencies", "--attachments", self.images,
            "--owner-note", note, "--old-slug", old, expected=1).stdout)
        self.assertFalse(dependency["ok"])
        self.assertEqual(dependency["blockers"],
                         blocked["results"][0]["dependency_blockers"])
        self.assertEqual(digest(image), original)
        # An external dependency rewrite is a separate authorized operation;
        # once the fixture supplies it, the clipping rename may proceed.
        external.write_text(
            f'[[{new}|the clipping]]\n![[Sources/Images/{new}_fig_1.png]]\n',
            encoding="utf-8")
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
            "skills/wiki-builder/scripts/lint_entry.py", wiki, "--compact").stdout)
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
            "skills/wiki-linter/scripts/scan_vault.py", wiki, "--indent", "0").stdout)
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
            "skills/wiki-builder/scripts/vault_index.py", wiki,
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

        builder = "skills/wiki-builder/scripts/lint_entry.py"
        linter = "skills/wiki-linter/scripts/scan_vault.py"
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
            "skills/wiki-builder/scripts/lint_entry.py", entry,
            "--compact").stdout)
        builder_items = {finding["item"]
                         for finding in builder["entries"][0]["findings"]}
        self.assertIn("12-equation-coverage-candidate", builder_items)

        scanner = json.loads(self.run_script(
            "skills/wiki-linter/scripts/scan_vault.py", self.vault / "Wiki",
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
            "skills/wiki-builder/scripts/lint_entry.py", entry,
            "--compact").stdout)
        self.assertNotIn(
            "12-equation-coverage-candidate",
            {finding["item"] for finding in builder["entries"][0]["findings"]})
        scanner = json.loads(self.run_script(
            "skills/wiki-linter/scripts/scan_vault.py", self.vault / "Wiki",
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
            "skills/wiki-builder/scripts/lint_entry.py", entry,
            "--compact").stdout)
        self.assertIn(
            "12-equation-coverage-candidate",
            {finding["item"] for finding in builder["entries"][0]["findings"]})
        scanner = json.loads(self.run_script(
            "skills/wiki-linter/scripts/scan_vault.py", self.vault / "Wiki",
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
            "skills/wiki-builder/scripts/lint_entry.py", entry,
            "--compact").stdout)
        self.assertNotIn(
            "12-equation-coverage-candidate",
            {finding["item"] for finding in builder["entries"][0]["findings"]})
        scanner = json.loads(self.run_script(
            "skills/wiki-linter/scripts/scan_vault.py", self.vault / "Wiki",
            "--indent", "0").stdout)
        self.assertNotIn(
            "item12/equation-coverage-candidate",
            {problem["item"] for problem in scanner["problems"]
             if problem["slug"] == "synthetic-deviation"})


if __name__ == "__main__":
    unittest.main()
