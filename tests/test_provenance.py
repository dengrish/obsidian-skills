#!/usr/bin/env python3
"""Check provenance across published note formats and an isolated runtime CLI.

Fixtures use temporary directories only. No live vault, installed cache, Git,
network, credentials or model-generated research is required.
"""

import copy
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "shared/scripts"
sys.dont_write_bytecode = True


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    with patch.dict(os.environ, {"OBSIDIAN_VAULT_SHARED": str(SHARED)}):
        spec.loader.exec_module(module)
    return module


provenance = load("note_provenance", SHARED / "note_provenance.py")
wiki = load("provenance_wiki_lint", ROOT / "skills/wiki-build/scripts/lint_entry.py")
scanner = load("provenance_vault_scan", ROOT / "skills/wiki-lint/scripts/scan_vault.py")
summary = load("provenance_summary_lint", ROOT / "skills/paper-summarize/scripts/note_lint.py")
market = load("provenance_market_notes", ROOT / "skills/market-research/scripts/market_notes.py")


def record(skill="knowledge:wiki-build", version="1.0.2"):
    return {
        "skill": skill,
        "plugin_version": version,
        "source_commit": "a" * 40,
        "source_url": "https://github.com/dengrish/obsidian-skills/commit/" + "a" * 40,
        "source_status": "committed",
        "runtime_sha256": "b" * 64,
    }


class NoteFormatTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="obsidian-provenance-test-")
        self.addCleanup(self.temporary.cleanup)
        self.vault = Path(self.temporary.name)
        (self.vault / "Wiki").mkdir()
        (self.vault / "MOCs").mkdir()

    def scan(self):
        return scanner.scan(str(self.vault / "Wiki"))

    def add_entry(self):
        entry = scanner._st_entry(
            "First", "**First** is a worked example.",
            tags=('"#statistics"',), parents=('"[[MOCs/statistics]]"',))
        (self.vault / "Wiki/first.md").write_text(entry, encoding="utf-8")
        return entry

    def test_wiki_footer_is_not_flashcard_content_or_a_source_link(self):
        original = wiki._st_good()
        self.assertEqual(wiki.lint_text(original, "roc-curve.md")["findings"], [])
        stamped = provenance.stamp_text(original, record())
        self.assertEqual(wiki.lint_text(stamped, "roc-curve.md")["findings"], [])
        body, metadata = provenance.split_provenance(stamped)
        self.assertEqual(body.rstrip(), original.rstrip())
        self.assertEqual(metadata["generated_by"]["skill"], "knowledge:wiki-build")

    def test_wiki_studied_card_attachments_survive_metadata_update(self):
        original = wiki._st_good().rstrip("\n") + (
            " <!--SR:!2026-09-20,30,250!2026-09-21,31,250--> ^roc-card\n")
        created = provenance.stamp_text(original, record())
        updated = provenance.stamp_text(
            original.replace("updated: 2026-01-02", "updated: 2026-01-03"),
            record("knowledge:wiki-lint", "1.0.3"), previous=created)
        self.assertIn("<!--SR:!2026-09-20,30,250!2026-09-21,31,250--> ^roc-card\n", updated)
        self.assertEqual(wiki.lint_text(updated, "roc-curve.md")["findings"], [])
        _, metadata = provenance.split_provenance(updated)
        self.assertEqual(metadata["generated_by"], record())
        self.assertEqual(metadata["updated_by"]["skill"], "knowledge:wiki-lint")

    def test_summary_footer_does_not_join_final_list_or_consume_prose_budget(self):
        before = summary.lint(summary.GOOD, mode="empirical")
        self.assertEqual(before, [])
        stamped = provenance.stamp_text(summary.GOOD, record("knowledge:paper-summarize"))
        self.assertEqual(summary.lint(stamped, mode="empirical"), before)

    def test_stamped_moc_retains_complete_entry_placement(self):
        entry = self.add_entry()
        (self.vault / "Wiki/first.md").write_text(
            provenance.stamp_text(entry, record("knowledge:wiki-add")), encoding="utf-8")
        (self.vault / "MOCs/statistics.md").write_text(
            provenance.stamp_text("- [[Wiki/first|First]]\n", record("knowledge:wiki-lint")),
            encoding="utf-8")
        result = self.scan()
        hierarchy = result["hierarchy_diagnostic"]
        self.assertEqual(hierarchy["moc_consistency_findings"], [])
        self.assertEqual(hierarchy["placement_gaps"], [])
        self.assertEqual(hierarchy["moc_file_states"][0]["state"], "readable")
        self.assertEqual(scanner._st_keys(result, "first"), [])

    def test_footer_only_misc_is_an_empty_generated_outline(self):
        (self.vault / "MOCs/misc.md").write_text(
            provenance.stamp_text("", record("knowledge:wiki-lint")), encoding="utf-8")
        hierarchy = self.scan()["hierarchy_diagnostic"]
        self.assertEqual(hierarchy["moc_consistency_findings"], [])
        self.assertEqual([(row["discipline"], row["state"], row["entries"])
                          for row in hierarchy["moc_file_states"]], [("misc", "empty", 0)])

    def test_malformed_misplaced_and_duplicate_footers_cannot_hide_in_note_formats(self):
        good_footer = provenance.stamp_text("", record()).strip()
        malformed = "<!-- skill-provenance: {invalid JSON} -->"
        tails = {
            "malformed": "\n\n" + malformed + "\n",
            "misplaced": "\n\n" + good_footer + "\n\nVisible text afterward.\n",
            "duplicate": "\n\n" + good_footer + "\n\n" + good_footer + "\n",
            "attached-to-card": "\n" + good_footer + "\n",
        }
        for kind, tail in tails.items():
            with self.subTest(kind=kind):
                candidate = wiki._st_good().rstrip("\n") + tail
                findings = wiki.lint_text(candidate, "roc-curve.md")["findings"]
                self.assertIn("2-provenance", {finding["item"] for finding in findings})
                self.assertTrue(any("skill provenance" in message
                                    for _, message in summary.lint(
                                        summary.GOOD.rstrip("\n") + tail, mode="empirical")))
                entry = self.add_entry().rstrip("\n") + tail
                (self.vault / "Wiki/first.md").write_text(entry, encoding="utf-8")
                (self.vault / "MOCs/statistics.md").write_text(
                    "- [[Wiki/first|First]]" + tail, encoding="utf-8")
                result = self.scan()
                self.assertIn("item2/provenance", scanner._st_keys(result, "first"))
                self.assertIn("invalid-provenance", {finding["kind"] for finding
                              in result["hierarchy_diagnostic"]["moc_consistency_findings"]})

    def test_unknown_historical_summary_attributes_only_its_actual_update(self):
        original = summary.GOOD
        changed = original.replace("Prose.\n", "Revised prose.\n", 1)
        updater = record("knowledge:paper-summarize")
        stamped = provenance.stamp_text(changed, updater, previous=original)
        self.assertEqual(summary.lint(stamped, mode="empirical"), [])
        _, metadata = provenance.split_provenance(stamped)
        self.assertIsNone(metadata["generated_by"])
        self.assertEqual(metadata["updated_by"], updater)
        self.assertEqual(provenance.stamp_text(original, updater, previous=original), original)

    def test_malformed_market_provenance_is_reported_without_aborting_history(self):
        folder = self.vault / "Investments"
        folder.mkdir()
        path = folder / "2026-09-05-market-research.md"
        depth = sys.getrecursionlimit() + 100
        payloads = [
            (json.dumps({"schema": 1, "generated_by": dict(
                record("investments:market-research"), source_status=status)}), "source status")
            for status in ([], {})
        ] + [
            ('{"schema":1,"generated_by":' + '[' * depth + '0' + ']' * depth + '}',
             "nesting is too deep"),
            ('{"\\ud800":1,"\\ud800":2}', "duplicate provenance JSON key"),
        ]
        for payload, expected in payloads:
            with self.subTest(expected=expected, prefix=payload[:60]):
                data = ("Note.\n\n<!-- skill-provenance: " + payload + " -->\n").encode("utf-8")
                path.write_bytes(data)
                now = datetime.fromisoformat("2026-09-06T11:30:00-04:00")
                for result in (market.context(self.vault, now), market.outcomes(self.vault, now=now)):
                    self.assertFalse(result["complete"])
                    self.assertTrue(any(expected in finding["error"] for finding in result["findings"]))
                    json.dumps(result, ensure_ascii=False).encode("utf-8")
                self.assertEqual(path.read_bytes(), data)


class RuntimeCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="obsidian-runtime-provenance-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.plugin = self.directory / "knowledge"
        self.plugin.mkdir()
        host_manifest = {"name": "knowledge", "version": "1.0.2",
                         "repository": "https://github.com/dengrish/obsidian-skills"}
        files = {
            ".claude-plugin/plugin.json": json.dumps(host_manifest).encode(),
            ".codex-plugin/plugin.json": json.dumps(host_manifest).encode(),
            "skills/wiki-build/SKILL.md": b"---\nname: wiki-build\n---\nA test skill.\n",
            "shared/scripts/note_provenance.py": (SHARED / "note_provenance.py").read_bytes(),
        }
        for relative, content in files.items():
            destination = self.plugin / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        inventory = {relative: hashlib.sha256(content).hexdigest()
                     for relative, content in files.items()}
        self.manifest = {
            "schema": 1, "plugin": "knowledge", "plugin_version": "1.0.2",
            "repository": host_manifest["repository"],
            "source_commit": None, "source_url": None, "source_status": "unavailable",
            "runtime_sha256": hashlib.sha256(json.dumps(
                inventory, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "files": inventory,
        }
        self.write_manifest()
        self.environment = os.environ.copy()
        self.environment.pop("OBSIDIAN_VAULT_SHARED", None)
        self.environment["PYTHONDONTWRITEBYTECODE"] = "1"

    def write_manifest(self):
        (self.plugin / "provenance.json").write_text(json.dumps(self.manifest), encoding="utf-8")

    def cli(self, command, *arguments, helper=None):
        return subprocess.run(
            [sys.executable, "-I", "-B", str(helper or self.plugin / "shared/scripts/note_provenance.py"),
             command, "--plugin", str(self.plugin), "--skill", "wiki-build", *map(str, arguments)],
            capture_output=True, text=True, encoding="utf-8", env=self.environment, cwd=self.directory)

    def test_isolated_runtime_inspection_and_create_only_cli(self):
        inspected = self.cli("inspect")
        self.assertEqual(inspected.returncode, 0, inspected.stderr)
        expected = json.loads(inspected.stdout)
        self.assertEqual(expected["source_status"], "unavailable")
        self.assertEqual(expected["runtime_sha256"], self.manifest["runtime_sha256"])
        draft, output = self.directory / "draft.md", self.directory / "stamped.md"
        draft.write_text(wiki._st_good(), encoding="utf-8")
        written = self.cli("stamp", "--draft", draft, "--output", output)
        self.assertEqual(written.returncode, 0, written.stderr)
        first_bytes = output.read_bytes()
        _, metadata = provenance.split_provenance(first_bytes.decode())
        self.assertEqual(metadata["generated_by"], expected)
        retry = self.cli("stamp", "--draft", draft, "--output", output)
        self.assertNotEqual(retry.returncode, 0)
        self.assertEqual(output.read_bytes(), first_bytes)
        self.assertEqual(draft.read_text(encoding="utf-8"), wiki._st_good())

    def test_cli_cannot_stamp_using_a_different_helpers_runtime_identity(self):
        inspected = self.cli("inspect", helper=SHARED / "note_provenance.py")
        self.assertNotEqual(inspected.returncode, 0)
        self.assertIn("own provenance helper", inspected.stderr)

    def test_normalized_repository_identity_matches_both_host_manifests(self):
        for relative in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
            path = self.plugin / relative
            value = json.loads(path.read_bytes())
            value["repository"] += ".git/"
            content = json.dumps(value).encode("utf-8")
            path.write_bytes(content)
            self.manifest["files"][relative] = hashlib.sha256(content).hexdigest()
        self.manifest["runtime_sha256"] = hashlib.sha256(json.dumps(
            self.manifest["files"], sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        self.write_manifest()
        checked = self.cli("inspect")
        self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_runtime_changed_missing_extra_and_symlink_files_are_rejected(self):
        skill = self.plugin / "skills/wiki-build/SKILL.md"
        original = skill.read_bytes()
        for kind in ("changed", "missing", "extra", "symlink"):
            with self.subTest(kind=kind):
                extra = self.plugin / "shared/scripts/unknown.py"
                if kind == "changed":
                    skill.write_bytes(original + b"Changed instructions.\n")
                elif kind == "missing":
                    skill.unlink()
                elif kind == "extra":
                    extra.write_text("print('unexpected code')\n", encoding="utf-8")
                else:
                    skill.unlink()
                    target = self.directory / "external-skill.md"
                    target.write_bytes(original)
                    skill.symlink_to(target)
                inspected = self.cli("inspect")
                self.assertNotEqual(inspected.returncode, 0)
                if kind in {"changed", "missing", "symlink"}:
                    if skill.is_symlink():
                        skill.unlink()
                    skill.write_bytes(original)
                else:
                    extra.unlink()
                self.assertEqual(self.cli("inspect").returncode, 0)

    def test_inventory_fingerprint_and_host_version_cannot_disagree(self):
        pristine = copy.deepcopy(self.manifest)
        self.manifest["runtime_sha256"] = "0" * 64
        self.write_manifest()
        inspected = self.cli("inspect")
        self.assertNotEqual(inspected.returncode, 0)
        self.assertIn("fingerprint", inspected.stderr)

        self.manifest = pristine
        self.manifest["plugin_version"] = "9.9.9"
        self.write_manifest()
        inspected = self.cli("inspect")
        self.assertNotEqual(inspected.returncode, 0)
        self.assertIn("manifest disagrees", inspected.stderr)

    def test_malformed_manifest_values_are_validation_errors(self):
        for key in ("source_status", "plugin"):
            for value in ([], {}):
                with self.subTest(key=key, value=value):
                    original = self.manifest[key]
                    self.manifest[key] = value
                    self.write_manifest()
                    with patch.dict(os.environ, {"OBSIDIAN_VAULT_SHARED": str(self.plugin / "shared/scripts")}):
                        with self.assertRaises(ValueError):
                            provenance.verified_record(self.plugin, "wiki-build")
                    self.manifest[key] = original
        self.write_manifest()

    def test_non_utf8_inventory_paths_fail_before_runtime_comparison(self):
        pristine = copy.deepcopy(self.manifest)
        for relative in ("\ud800", "shared/\udfff.py", "skills/wiki-build/\ud800/SKILL.md"):
            with self.subTest(relative=ascii(relative)):
                self.manifest = copy.deepcopy(pristine)
                self.manifest["files"][relative] = "c" * 64
                # A matching inventory digest must not allow invalid path text
                # to reach the mismatch diagnostic and break its UTF-8 output.
                self.manifest["runtime_sha256"] = hashlib.sha256(json.dumps(
                    self.manifest["files"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                self.write_manifest()
                with patch.dict(os.environ, {"OBSIDIAN_VAULT_SHARED": str(self.plugin / "shared/scripts")}):
                    with self.assertRaisesRegex(ValueError, "inventory path must be valid UTF-8") as caught:
                        provenance.verified_record(self.plugin, "wiki-build")
                str(caught.exception).encode("utf-8")
                inspected = self.cli("inspect")
                self.assertEqual(inspected.returncode, 1)
                self.assertEqual(inspected.stdout, "")
                self.assertIn("inventory path must be valid UTF-8", inspected.stderr)
                self.assertNotIn("Traceback", inspected.stderr)
        self.manifest = pristine
        self.write_manifest()
        self.assertEqual(self.cli("inspect").returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
