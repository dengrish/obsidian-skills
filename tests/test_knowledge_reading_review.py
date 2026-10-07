#!/usr/bin/env python3
"""Exercise figure repair handoffs and summary-note lint gates in disposable vaults."""

import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import pymupdf


ROOT = Path(__file__).resolve().parents[1]
FIGURES = ROOT / "skills" / "figure-extract" / "scripts"
READING = ROOT / "skills" / "paper-summarize" / "scripts"
SHARED = ROOT / "shared" / "scripts"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    with patch.dict(os.environ, {"OBSIDIAN_VAULT_SHARED": str(SHARED)}):
        spec.loader.exec_module(module)
    return module


def worked_example_note(name="worked-example.md"):
    """The first untagged fence after the worked example's output heading."""
    doc = (ROOT / "skills" / "paper-summarize" / "references"
           / name).read_text(encoding="utf-8")
    lines = doc.split("\n")
    i = lines.index("## The output note") + 1
    while i < len(lines):
        if lines[i] == "```":
            end = lines.index("```", i + 1)
            return "\n".join(lines[i + 1:end]) + "\n"
        if lines[i].startswith("```"):
            i = lines.index("```", i + 1)
        i += 1
    return None


def argument_note():
    return '''---
title: Event Record Interoperability Profile
format: Report
sources:
  - "[[Group_EventRecords_2025.pdf]]"
author:
  - Standards Working Group
published: 2025-01-01
created: 2026-09-23
description: The profile defines required event fields and optional extensions.
tags:
  - "#engineering"
read: false
---
> [!Summary]
> - The profile requires an identifier and a timestamp for every exchanged event.
> - Extensions may add fields without replacing the required ones.
> - The profile does not specify a transport protocol.

___

## The profile defines a common record for events

The profile addresses records exchanged between independent systems.

## Two required fields define the minimum record

The normative text separates required fields from optional extensions.

## Every exchanged event needs an identifier and a timestamp

Each record must include an identifier and a timestamp. Extensions may add fields.<sup>[[Group_EventRecords_2025.pdf#page=1|1]]</sup>

## Extensions preserve the shared minimum record

The profile permits local detail while retaining the two required fields.

## The profile leaves transport choices to implementations

- **Scope.** Transport behavior is outside the profile.<sup>[[Group_EventRecords_2025.pdf#page=2|2]]</sup>

## The normative text supplies one example record

- **Sources.** The PDF supplies the requirements and an example.<sup>[[Group_EventRecords_2025.pdf#page=2|2]]</sup>
'''


class FigureRepairWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="knowledge-reading-")
        self.addCleanup(self.tmp.cleanup)
        self.vault = Path(self.tmp.name) / "vault"
        self.source = self.vault / "Sources" / "PDFs" / "x-123456789-abcdef123456.pdf"
        self.source.parent.mkdir(parents=True)
        self.images = self.vault / "Sources" / "Images"
        self.images.mkdir()
        with pymupdf.open() as doc:
            page = doc.new_page(width=612, height=792)
            page.draw_rect(pymupdf.Rect(100, 150, 500, 350),
                           color=(0.1, 0.2, 0.7), fill=(0.2, 0.3, 0.8))
            page.insert_text((100, 380), "Figure 1. A synthetic blue rectangle.")
            doc.save(self.source)

    def run_tool(self, name, *args):
        env = dict(os.environ, OBSIDIAN_VAULT_SHARED=str(ROOT / "shared" / "scripts"))
        return subprocess.run(
            [sys.executable, str(FIGURES / name), *map(str, args)],
            cwd=self.vault, env=env, text=True, encoding="utf-8", capture_output=True, timeout=60)

    def repair(self, *args):
        return self.run_tool(
            "extract_figures.py", self.source, "--out", self.images,
            "--stem", self.source.stem, "--crop", "1:1:120,170,400,300",
            "--dpi", "72", "--overwrite", *args)

    def test_named_attachment_can_be_repaired_and_reviewed_without_renaming(self):
        original_source = self.source.read_bytes()
        extracted = self.run_tool(
            "batch_extract.py", "--src", self.source, "--out", self.images,
            "--dpi", "72", "--allow-unorganized")
        self.assertEqual(extracted.returncode, 0, extracted.stdout + extracted.stderr)
        image = self.images / (self.source.stem + "_fig_1.png")
        original_crop = image.read_bytes()

        refused = self.repair()
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(image.read_bytes(), original_crop)

        repaired = self.repair("--allow-unorganized")
        self.assertEqual(repaired.returncode, 0, repaired.stdout + repaired.stderr)
        repaired_crop = image.read_bytes()
        self.assertNotEqual(repaired_crop, original_crop)
        self.assertIn("--allow-unorganized", repaired.stdout + repaired.stderr)

        reviewed = self.run_tool(
            "batch_extract.py", "--src", self.source, "--out", self.images,
            "--dpi", "72", "--allow-unorganized", "--mark-reviewed",
            self.source.stem + ":1", "--overwrite")
        self.assertEqual(reviewed.returncode, 0, reviewed.stdout + reviewed.stderr)
        self.assertEqual(image.read_bytes(), repaired_crop)
        self.assertEqual(self.source.read_bytes(), original_source)
        manifest = (self.images / ".figure-manifest.tsv").read_text(encoding="utf-8")
        self.assertIn(hashlib.sha256(repaired_crop).hexdigest(), manifest)

    def test_override_keeps_the_whole_vault_duplicate_source_guard(self):
        duplicate = self.vault / "Archive" / self.source.name
        duplicate.parent.mkdir()
        duplicate.write_bytes(self.source.read_bytes())
        result = self.repair("--allow-unorganized")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unique basename", result.stdout + result.stderr)
        self.assertEqual(list(self.images.iterdir()), [])

    def test_override_does_not_claim_an_existing_foreign_figure(self):
        image = self.images / (self.source.stem + "_fig_1.png")
        occupied_bytes = b"another producer's occupied filename"
        image.write_bytes(occupied_bytes)
        result = self.repair("--allow-unorganized")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ownership is unknown", result.stdout + result.stderr)
        self.assertEqual(image.read_bytes(), occupied_bytes)
        self.assertFalse((self.images / ".figure-manifest.tsv").exists())


class SummaryPublicationGateTests(unittest.TestCase):
    def test_scalar_continuations_cannot_hide_invalid_frontmatter(self):
        with tempfile.TemporaryDirectory(prefix="summary-gate-") as scratch:
            note = Path(scratch) / "Group_EventRecords_2025.md"
            env = dict(os.environ, OBSIDIAN_VAULT_SHARED=str(ROOT / "shared" / "scripts"))

            def check(text):
                note.write_text(text, encoding="utf-8")
                return subprocess.run(
                    [sys.executable, str(READING / "note_lint.py"), str(note),
                     "--mode", "argument"], cwd=scratch, env=env, text=True, encoding="utf-8",
                    capture_output=True, timeout=60)

            good = argument_note()
            result = check(good)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for scalar in ("title: Event Record Interoperability Profile",
                           "published: 2025-01-01", "read: false"):
                with self.subTest(scalar=scalar):
                    result = check(good.replace(scalar, scalar + "\n  bogus: value"))
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            commented = check(good.replace("read: false", "read: false\n  # A user comment"))
            self.assertEqual(commented.returncode, 0, commented.stdout + commented.stderr)

    def test_worked_example_note_lints_clean_without_an_image_inventory(self):
        text = worked_example_note()
        self.assertIsNotNone(text, "no untagged fence follows '## The output note'")
        self.assertTrue(text.startswith("---\n"), text[:80])
        note_lint = load("reading_review_note_lint", READING / "note_lint.py")
        advisories = []
        self.assertEqual(
            note_lint.lint(text, mode="empirical", advisories=advisories), [])
        self.assertEqual(advisories, [])

    def test_argument_worked_example_note_lints_clean_in_argument_mode(self):
        text = worked_example_note("worked-example-argument.md")
        self.assertIsNotNone(text, "no untagged fence follows '## The output note'")
        self.assertTrue(text.startswith("---\n"), text[:80])
        note_lint = load("reading_review_note_lint", READING / "note_lint.py")
        advisories = []
        self.assertEqual(
            note_lint.lint(text, mode="argument", advisories=advisories), [])
        self.assertEqual(advisories, [])


if __name__ == "__main__":
    unittest.main()
