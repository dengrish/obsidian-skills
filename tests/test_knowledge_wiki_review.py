#!/usr/bin/env python3
"""Verify Wiki source-intake decisions through public CLIs in temporary vaults."""

import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "skills/wiki-build/scripts/vault_index.py"
BACKLOG = ROOT / "skills/wiki-add/scripts/backlog.py"
SCAN = ROOT / "skills/wiki-lint/scripts/scan_vault.py"


class SourceCoverageTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="knowledge-wiki-review-")
        self.root = Path(self.scratch.name)
        self.vault = self.root / "Vault with spaces"
        self.wiki = self.vault / "Wiki"
        self.wiki.mkdir(parents=True)

    def tearDown(self):
        self.scratch.cleanup()

    def source(self, relative):
        path = self.vault / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Verified source fixture.\n", encoding="utf-8")
        return path

    def note(self, slug, source, *, tree=None):
        path = (tree or self.wiki) / (slug + ".md")
        path.parent.mkdir(parents=True, exist_ok=True)
        title = path.stem.capitalize()
        path.write_text("\n".join([
            "---", "title: " + title, "type: Concept", "sources:",
            "  - " + json.dumps(source, ensure_ascii=False),
            "created: 2026-09-23", "updated: 2026-09-23",
            "description: A fixture verifies source identity.", "tags:",
            '  - "#engineering"', "parents: []", "read: false", "---",
            "**" + title + "** verifies a source.", "",
        ]), encoding="utf-8")
        return path

    def index(self, *sources, tree=None, origin=None, strict=True, returncode=0):
        command = [sys.executable, str(INDEX), str(tree or self.wiki)]
        if strict:
            command += ["--vault", str(self.vault)]
        if origin:
            command += ["--wiki-origin", str(origin)]
        for source in sources:
            command += ["--source", str(source)]
        environment = dict(os.environ, OBSIDIAN_VAULT_SHARED=str(ROOT / "shared/scripts"))
        result = subprocess.run(command, cwd=self.root, env=environment,
                                text=True, encoding="utf-8", capture_output=True, timeout=30)
        self.assertEqual(result.returncode, returncode, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def scan(self):
        images = self.vault / "Sources/Images"
        images.mkdir(parents=True, exist_ok=True)
        result = subprocess.run([sys.executable, str(SCAN), str(self.wiki),
                                 "--images", str(images)], cwd=self.root,
                                text=True, encoding="utf-8", capture_output=True, timeout=30,
                                env=dict(os.environ, OBSIDIAN_VAULT_SHARED=str(ROOT / "shared/scripts")))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_wrong_qualified_citation_never_proves_prior_pdf_coverage(self):
        source = self.source("Sources/PDFs/Doe_Example_2025.pdf")
        self.note("probe", "[[Missing/Doe_Example_2025.pdf#page=2]]")
        result = self.index(source)
        self.assertEqual(result["problems"], [])
        self.assertEqual(result["source_problems"], [])
        self.assertEqual(result["source_matches"], [])
        self.assertEqual(result["source_match_candidates"][0]["slug"], "probe")
        self.assertFalse(result["source_match_candidates"][0]["identity_confirmed"])

    def test_bare_suffix_relative_and_normalized_citations_confirm_one_owner(self):
        source = self.source("Sources/PDFs/García_Example_2025.pdf")
        targets = {
            "bare": "García_Example_2025.pdf",
            "qualified": "Sources/PDFs/García_Example_2025.pdf",
            "suffix": "PDFs/García_Example_2025.pdf",
            "nested/relative": "../../Sources/PDFs/García_Example_2025.pdf",
            "normalized": "sources/pdfs/GARCI\u0301A_EXAMPLE_2025.PDF",
        }
        for slug, target in targets.items():
            self.note(slug, "[[" + target + "#page=2]]")
        result = self.index(source.relative_to(self.vault))
        self.assertEqual(result["source_problems"], [])
        self.assertEqual({item["relpath"] for item in result["source_matches"]},
                         {slug + ".md" for slug in targets})
        self.assertTrue(all(item["identity_confirmed"] for item in result["source_matches"]))

    def test_markdown_qualification_and_duplicate_ownership_are_not_discarded(self):
        source = self.source("Articles/Explanation.md")
        self.note("actual", "[[Articles/Explanation.md]]")
        self.note("wrong", "[[Elsewhere/Explanation.md]]")
        result = self.index(source)
        self.assertEqual([item["slug"] for item in result["source_matches"]], ["actual"])
        self.source("Archive/Explanation.md")
        ambiguous = self.index(source)
        self.assertEqual(ambiguous["source_matches"], [])
        self.assertTrue(ambiguous["source_problems"])
        self.assertEqual(len(ambiguous["source_problems"][0]["owners"]), 2)

    def test_private_overlay_keeps_original_note_relative_location(self):
        source = self.source("Articles/Explanation.md")
        overlay = self.root / "private-overlay"
        self.note("nested/probe", "[[../../Articles/Explanation.md]]", tree=overlay)
        unresolved = self.index(source, tree=overlay)
        self.assertEqual(unresolved["source_matches"], [])
        self.assertTrue(unresolved["source_problems"])
        resolved = self.index(source, tree=overlay, origin=self.wiki)
        self.assertEqual(resolved["source_problems"], [])
        self.assertEqual([item["slug"] for item in resolved["source_matches"]], ["probe"])

    def test_legacy_basename_queries_are_explicitly_unconfirmed(self):
        self.note("probe", "[[Missing/Explanation.md]]")
        result = self.index("Explanation.md", strict=False)
        self.assertEqual(result["source_match_mode"], "unconfirmed-basename-candidates")
        self.assertFalse(result["source_matches"][0]["identity_confirmed"])

    def test_incomplete_source_inventory_cannot_confirm_coverage(self):
        source = self.source("Articles/Explanation.md")
        self.note("probe", "[[Explanation.md]]")
        (self.vault / "loop").symlink_to(self.vault, target_is_directory=True)
        result = self.index(source, returncode=1)
        self.assertFalse(result["source_inventory_complete"])
        self.assertEqual(result["source_matches"], [])
        self.assertTrue(result["source_problems"])

    def test_missing_or_symlink_markdown_source_is_not_coverage_evidence(self):
        actual = self.source("Articles/Explanation.md")
        self.note("probe", "[[Explanation.md]]")
        actual.unlink()
        missing = self.index(actual)
        self.assertEqual(missing["source_matches"], [])
        self.assertTrue(missing["source_problems"])
        outside = self.root / "outside.md"
        outside.write_text("Outside content.\n", encoding="utf-8")
        actual.symlink_to(outside)
        unsafe = self.index(actual)
        self.assertEqual(unsafe["source_matches"], [])
        self.assertTrue(unsafe["source_problems"])

    def test_existing_uppercase_markdown_entry_completes_queue_unchanged(self):
        note = self.note("topic", "[[Explanation.md]]")
        upper = note.with_suffix(".MD")
        note.rename(upper)
        before = upper.read_bytes()
        queue = self.vault / "add-to-wiki.md"
        queue.write_bytes(b"- [ ] Topic\r\n")
        snapshot = self.root / "queue-snapshot.json"
        environment = dict(os.environ, OBSIDIAN_VAULT_SHARED=str(ROOT / "shared/scripts"))
        scan = subprocess.run([sys.executable, str(BACKLOG), "scan", str(queue),
                               "--out", str(snapshot)], env=environment,
                              text=True, encoding="utf-8", capture_output=True, timeout=30)
        self.assertEqual(scan.returncode, 0, scan.stdout + scan.stderr)
        item = json.loads(snapshot.read_text(encoding="utf-8"))["items"][0]["id"]
        complete = subprocess.run([sys.executable, str(BACKLOG), "complete",
                                   "--snapshot", str(snapshot), "--item", item,
                                   "--wiki", str(self.wiki), "--entry", str(upper)],
                                  env=environment, text=True, encoding="utf-8", capture_output=True, timeout=30)
        self.assertEqual(complete.returncode, 0, complete.stdout + complete.stderr)
        self.assertEqual(queue.read_bytes(), b"- [x] Topic\r\n")
        self.assertEqual(upper.read_bytes(), before)

    def test_note_relative_links_and_parents_resolve_from_each_entry(self):
        self.note("neighbor", "[[Explanation.md]]")
        note = self.note("nested/probe", "[[Explanation.md]]")
        text = note.read_text(encoding="utf-8").replace("parents: []", 'parents:\n  - "[[../neighbor]]"')
        text += ("\nIts mechanism extends [[../neighbor#Mechanism|Neighbor]].\n"
                 "Neighbor remains a distinct topic.\n"
                 "\n**Related:** [[../neighbor|Neighbor]]\n")
        note.write_text(text, encoding="utf-8")
        result = self.scan()
        failures = [item for item in result["problems"] if item["slug"] == "probe"
                    and item["item"] in {"item10/dangling", "item10/case", "item11"}]
        self.assertEqual(failures, [])
        self.assertFalse(any(item["slug"] == "probe"
                             for item in result["hierarchy_diagnostic"]["unresolved_parents"]))
        self.assertFalse(any(item["slug"] == "probe" and item["target"] == "neighbor"
                             for item in result["backfill_candidates"]))

    def test_note_relative_link_never_becomes_an_arbitrary_suffix(self):
        self.note("deeper/neighbor", "[[Explanation.md]]")
        self.note("Other/elsewhere", "[[Explanation.md]]")
        note = self.note("nested/probe", "[[Explanation.md]]")
        note.write_text(note.read_text(encoding="utf-8") + "\nA link to [[../neighbor|Neighbor]] and "
                        "[[../../Other/elsewhere|Elsewhere]] is absent.\n", encoding="utf-8")
        result = self.scan()
        dangling = [item["message"] for item in result["problems"]
                    if item["slug"] == "probe" and item["item"] == "item10/dangling"]
        self.assertTrue(any('"../neighbor"' in item for item in dangling))
        self.assertTrue(any('"../../Other/elsewhere"' in item for item in dangling))

    def test_relative_moc_link_has_its_own_origin(self):
        self.note("neighbor", "[[Explanation.md]]")
        mocs = self.vault / "MOCs"
        mocs.mkdir()
        (mocs / "engineering-moc.md").write_text("- [[../Wiki/neighbor|Neighbor]]\n", encoding="utf-8")
        result = self.scan()
        findings = result["hierarchy_diagnostic"]["moc_consistency_findings"]
        self.assertFalse(any(item["kind"] == "unresolved-link" for item in findings))
        self.assertTrue(any(item["kind"] == "noncanonical-target"
                            and item["expected_target"] == "Wiki/neighbor" for item in findings))


class VaultRootScanTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="knowledge-wiki-root-review-")
        self.root = Path(self.scratch.name)
        self.vault = self.root / "Selected vault"
        self.environment = dict(os.environ, OBSIDIAN_VAULT_SHARED=str(ROOT / "shared/scripts"))

    def tearDown(self):
        self.scratch.cleanup()

    def fixture(self, wiki_relative="Knowledge/Wiki"):
        self.wiki = self.vault / wiki_relative
        self.wiki.mkdir(parents=True)
        mocs = self.vault / "MOCs"
        mocs.mkdir()
        for slug in ("misc", "alpha", "beta"):
            parents = [] if slug == "misc" else ["[[misc]]"]
            body = f"**{slug.title()}** is a fixture entry."
            if slug == "alpha":
                body += f" Its mechanism uses [[{wiki_relative}/beta|Beta]]."
            (self.wiki / (slug + ".md")).write_text("\n".join([
                "---", "title: " + slug.title(), "type: Concept", "aliases: []",
                'tags: ["#misc"]', "parents: " + json.dumps(parents),
                'sources: ["[[Example.md]]"]', "created: 2026-09-23",
                "updated: 2026-09-23", "read: false",
                "description: A fixture verifies vault path resolution.",
                "---", "", body, "",
            ]), encoding="utf-8")
        (mocs / "misc-moc.md").write_text(
            f"- [[{wiki_relative}/misc|Misc]]\n"
            f"  - [[{wiki_relative}/alpha|Alpha]]\n"
            f"  - [[{wiki_relative}/beta|Beta]]\n", encoding="utf-8")

    def snapshot(self):
        return {str(path.relative_to(self.vault)):
                path.read_bytes() if path.is_file() else None
                for path in self.vault.rglob("*")}

    def scan_cli(self, *args):
        return subprocess.run([sys.executable, str(SCAN), str(self.wiki), *map(str, args)],
                              cwd=self.root, env=self.environment, text=True,
                              encoding="utf-8", capture_output=True, timeout=30)

    def assert_resolved(self, report):
        self.assertEqual(report["vault_root"], str(self.vault))
        self.assertFalse(any(row["item"] == "item10/dangling"
                             for row in report["problems"]), report["problems"])
        hierarchy = report["hierarchy_diagnostic"]
        self.assertEqual(hierarchy["unresolved_parents"], [])
        self.assertEqual(hierarchy["moc_consistency_findings"], [])
        self.assertEqual([(row["path"], row["state"])
                          for row in hierarchy["moc_file_states"]],
                         [(str(self.vault / "MOCs/misc-moc.md"), "readable")])

    def test_explicit_vault_keeps_no_image_preview_links_and_hierarchy_resolved(self):
        self.fixture()
        before = self.snapshot()
        result = self.scan_cli("--vault", self.vault)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assert_resolved(report)
        self.assertEqual(report["image_folder_findings"], [])
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.vault / ".obsidian").exists())
        self.assertFalse((self.vault / "Sources").exists())

    def test_invalid_explicit_vault_is_usage_error_without_output_or_setup(self):
        self.fixture()
        regular_file = self.root / "not-a-directory"
        regular_file.write_text("Keep me.\n", encoding="utf-8")
        output = self.root / "existing-report.json"
        output.write_text("Original report.\n", encoding="utf-8")
        before = self.snapshot()
        for invalid in (self.root / "missing-vault", regular_file):
            with self.subTest(vault=invalid):
                result = self.scan_cli("--vault", invalid, "--out", output)
                self.assertEqual(result.returncode, 2)
                self.assertIn("--vault is not a directory", result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertEqual(output.read_text(encoding="utf-8"), "Original report.\n")
                self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.root / "missing-vault").exists())

    def test_omitted_vault_retains_images_marker_and_parent_inference(self):
        self.fixture()
        images = self.vault / "Sources/Images"
        images.mkdir(parents=True)
        result = self.scan_cli("--images", images)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_resolved(json.loads(result.stdout))
        (self.vault / ".obsidian").mkdir()
        result = self.scan_cli()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_resolved(json.loads(result.stdout))
        direct_wiki = self.root / "Legacy vault/Wiki"
        direct_wiki.mkdir(parents=True)
        self.wiki = direct_wiki
        result = self.scan_cli()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["vault_root"], str(direct_wiki.parent))

    def test_python_api_accepts_and_validates_explicit_vault(self):
        self.fixture()
        with patch.dict(os.environ, self.environment):
            scan = runpy.run_path(str(SCAN))["scan"]
        self.assert_resolved(scan(self.wiki, vault=self.vault))
        with self.assertRaisesRegex(ValueError, "vault is not a directory"):
            scan(self.wiki, vault=self.root / "missing-vault")


if __name__ == "__main__":
    unittest.main()
