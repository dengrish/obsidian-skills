#!/usr/bin/env python3
"""Focused tests for CI-only dependency and release checks."""

import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "ci_contract", HERE / "ci_contract.py")
CI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CI)


class CiContractTests(unittest.TestCase):
    @staticmethod
    def git(repository, *arguments):
        subprocess.run(
            ["git", "-C", str(repository), *arguments], check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def initialize_repository(self, root):
        self.git(root, "init", "-q")
        self.git(root, "config", "user.name", "CI fixture")
        self.git(root, "config", "user.email", "ci@example.invalid")

    def commit(self, root, message="fixture change"):
        self.git(root, "add", ".")
        self.git(root, "commit", "-q", "-m", message)
        return CI._git_text(root, "rev-parse", "HEAD").strip()

    @staticmethod
    def write(root, name, text):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def version(self, root, plugin, version):
        self.write(root, "plugins/%s/.claude-plugin/plugin.json" % plugin,
                   json.dumps({"name": plugin, "version": version}) + "\n")

    def split_fixture(self, root):
        maps = {}
        for plugin, skill in (("knowledge", "wiki-add"),
                              ("investments", "market-research")):
            self.version(root, plugin, "1.0.0")
            source = "skills/%s/SKILL.md" % skill
            self.write(root, source, plugin + " workflow\n")
            maps[plugin] = {
                ".claude-plugin/plugin.json":
                    "plugins/%s/.claude-plugin/plugin.json" % plugin,
                source: source,
                "shared/RUNTIME.md": "shared/RUNTIME.md",
            }
        self.write(root, "shared/RUNTIME.md", "Shared runtime\n")
        self.write(root, "shared/CONVENTIONS.md", "Knowledge conventions\n")
        maps["knowledge"]["shared/CONVENTIONS.md"] = "shared/CONVENTIONS.md"
        self.write(root, CI.PACKAGE_MAPS, json.dumps(maps) + "\n")
        return maps

    def test_declared_floors_follow_recursive_requirements(self):
        with tempfile.TemporaryDirectory(prefix="obsidian-ci-floors-") as tmp:
            root = Path(tmp)
            nested = root / "nested"
            nested.mkdir()
            (root / "requirements-dev.txt").write_text(
                "-r nested/runtime.txt\nPyYAML>=6.0  # tests\n",
                encoding="utf-8")
            (nested / "runtime.txt").write_text(
                "Pillow>=9.1\npypdf>=4.0\n", encoding="utf-8")
            self.assertEqual(
                CI.declared_floors(root / "requirements-dev.txt", root),
                ["Pillow==9.1", "pypdf==4.0", "PyYAML==6.0"],
            )
            (nested / "runtime.txt").write_text(
                "Pillow>=9.1,<12\n", encoding="utf-8")
            with self.assertRaisesRegex(CI.ContractError, "simple name>=floor"):
                CI.declared_floors(root / "requirements-dev.txt", root)

    def test_semver_order_includes_prereleases(self):
        precedence = (
            "1.0.0-alpha",
            "1.0.0-alpha.1",
            "1.0.0-alpha.beta",
            "1.0.0-beta",
            "1.0.0-beta.2",
            "1.0.0-beta.11",
            "1.0.0-rc.1",
            "1.0.0",
        )
        for baseline, candidate in zip(precedence, precedence[1:]):
            with self.subTest(candidate=candidate, baseline=baseline):
                self.assertTrue(CI.semver_is_greater(candidate, baseline))
                self.assertFalse(CI.semver_is_greater(baseline, candidate))
        self.assertTrue(CI.semver_is_greater("1.0.1", "1.0.0"))
        self.assertTrue(CI.semver_is_greater("2.0.0-alpha", "1.99.99"))
        self.assertFalse(CI.semver_is_greater("1.2.3+new", "1.2.3+old"))
        with self.assertRaises(CI.ContractError):
            CI.parse_semver("1.2")
        with self.assertRaises(CI.ContractError):
            CI.parse_semver("1.2.3-rc.01")

    def test_packaged_change_selection_uses_both_inventories(self):
        changed = {
            ".github/workflows/validate.yml",
            "skills/new.md",
            "skills/removed.md",
            "skills/unlisted.svg",
            "skills/cache/__pycache__/helper.pyc",
            "tools/.DS_Store",
            "tools/package-files.txt",
        }
        self.assertEqual(
            CI.packaged_changes(
                changed,
                {"skills/removed.md", "tools/package-files.txt"},
                {"skills/new.md", "tools/package-files.txt"},
            ),
            ["skills/new.md", "skills/removed.md", "skills/unlisted.svg",
             "tools/package-files.txt"],
        )
        self.assertEqual(
            CI.packaged_changes(changed, None, {"skills/new.md"}),
            ["skills/new.md", "skills/removed.md", "skills/unlisted.svg",
             "tools/package-files.txt"],
        )

    def test_workflow_pins_actions_and_uses_a_portable_locale(self):
        workflow = (HERE.parent / "workflows/validate.yml").read_text(
            encoding="utf-8")
        uses = re.findall(r"^\s*uses:\s+([^#\s]+)", workflow, re.MULTILINE)
        remote_uses = [use for use in uses if not use.startswith("./")]
        self.assertEqual(len(remote_uses), 4)
        self.assertTrue(all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", use)
                            for use in remote_uses))
        self.assertNotIn("C.UTF-8", workflow)
        self.assertIn("LANG: C\n", workflow)
        self.assertIn("LC_ALL: C\n", workflow)
        self.assertNotIn('python_utf8: "0"', workflow)
        event_gate = (
            "if: github.event_name == 'pull_request' || "
            "github.event_name == 'push'")
        self.assertEqual(workflow.count(event_gate), 2)
        self.assertIn("--comparison \"$COMPARISON_MODE\"", workflow)

    def test_version_gate_ignores_ci_and_requires_packaged_change_bump(self):
        with tempfile.TemporaryDirectory(prefix="obsidian-ci-version-") as tmp:
            root = Path(tmp)
            (root / ".claude-plugin").mkdir()
            (root / ".github").mkdir()
            (root / "skills").mkdir()
            (root / "tools").mkdir()
            manifest = root / ".claude-plugin/plugin.json"
            manifest.write_text(
                json.dumps({"name": "fixture", "version": "1.2.3"}) + "\n",
                encoding="utf-8")
            (root / "skills/entry.md").write_text("one\n", encoding="utf-8")
            inventory = [
                ".claude-plugin/plugin.json",
                "skills/entry.md",
                "tools/package-files.txt",
            ]
            (root / "tools/package-files.txt").write_text(
                "\n".join(inventory) + "\n", encoding="utf-8")
            self.git(root, "init", "-q")
            self.git(root, "config", "user.name", "CI fixture")
            self.git(root, "config", "user.email", "ci@example.invalid")
            self.git(root, "add", ".")
            self.git(root, "commit", "-q", "-m", "base")
            base = CI._git_text(root, "rev-parse", "HEAD").strip()

            (root / ".github/workflow.yml").write_text(
                "name: changed\n", encoding="utf-8")
            self.git(root, "add", ".")
            self.git(root, "commit", "-q", "-m", "ci only")
            CI.check_version_bump(root, base, "pull-request")

            self.git(
                root, "update-index", "--chmod=+x", "skills/entry.md")
            self.git(root, "commit", "-q", "-m", "mode only")
            CI.check_version_bump(root, base, "pull-request")

            (root / "skills/unlisted.svg").write_text(
                "<svg/>\n", encoding="utf-8")
            self.git(root, "add", ".")
            self.git(root, "commit", "-q", "-m", "package without bump")
            with self.assertRaisesRegex(
                    CI.ContractError,
                    r"skills/unlisted\.svg.*does not advance base version"):
                CI.check_version_bump(root, base, "pull-request")

            manifest.write_text(
                json.dumps({"name": "fixture", "version": "1.2.4"}) + "\n",
                encoding="utf-8")
            self.git(root, "add", ".")
            self.git(root, "commit", "-q", "-m", "bump")
            CI.check_version_bump(root, base, "pull-request")

            with self.assertRaisesRegex(CI.ContractError, "base revision"):
                CI.check_version_bump(root, "", "push")
            with self.assertRaisesRegex(
                    CI.ContractError, r"git rev-parse .* failed"):
                CI.check_version_bump(root, "deadbeef", "push")
            with self.assertRaisesRegex(
                    CI.ContractError, "no prior revision"):
                CI.check_version_bump(root, "0" * 40, "push")

    def test_force_push_compares_old_and_new_tips(self):
        with tempfile.TemporaryDirectory(prefix="obsidian-ci-force-push-") as tmp:
            root = Path(tmp)
            (root / ".claude-plugin").mkdir()
            (root / ".github").mkdir()
            (root / "skills").mkdir()
            (root / "tools").mkdir()
            manifest = root / ".claude-plugin/plugin.json"
            entry = root / "skills/entry.md"
            inventory = [
                ".claude-plugin/plugin.json",
                "skills/entry.md",
                "tools/package-files.txt",
            ]
            manifest.write_text(
                json.dumps({"name": "fixture", "version": "1.2.3"}) + "\n",
                encoding="utf-8")
            entry.write_text("base\n", encoding="utf-8")
            (root / "tools/package-files.txt").write_text(
                "\n".join(inventory) + "\n", encoding="utf-8")
            self.git(root, "init", "-q")
            self.git(root, "config", "user.name", "CI fixture")
            self.git(root, "config", "user.email", "ci@example.invalid")
            self.git(root, "add", ".")
            self.git(root, "commit", "-q", "-m", "base")
            common = CI._git_text(root, "rev-parse", "HEAD").strip()

            manifest.write_text(
                json.dumps({"name": "fixture", "version": "1.2.4"}) + "\n",
                encoding="utf-8")
            entry.write_text("published\n", encoding="utf-8")
            self.git(root, "add", ".")
            self.git(root, "commit", "-q", "-m", "published tip")
            old_tip = CI._git_text(root, "rev-parse", "HEAD").strip()

            self.git(root, "checkout", "-q", "--detach", common)
            (root / ".github/rewrite.yml").write_text(
                "name: rewritten history\n", encoding="utf-8")
            self.git(root, "add", ".")
            self.git(root, "commit", "-q", "-m", "rewritten tip")

            # A pull-request comparison sees only the CI-only change from the
            # common ancestor. A push comparison sees the packaged rollback
            # from the old ref tip and rejects the version regression.
            CI.check_version_bump(root, old_tip, "pull-request")
            with self.assertRaisesRegex(
                    CI.ContractError, "does not advance base version"):
                CI.check_version_bump(root, old_tip, "push")

    def test_split_workflow_changes_require_only_their_own_version(self):
        for plugin, source in (("knowledge", "skills/wiki-add/SKILL.md"),
                               ("investments", "skills/market-research/SKILL.md"),
                               ("knowledge", "shared/CONVENTIONS.md")):
            with self.subTest(plugin=plugin, source=source), \
                    tempfile.TemporaryDirectory(prefix="split-ci-own-") as tmp:
                root = Path(tmp)
                self.split_fixture(root)
                self.initialize_repository(root)
                base = self.commit(root, "split base")
                self.write(root, source, "Changed runtime\n")
                self.commit(root)
                with self.assertRaisesRegex(CI.ContractError,
                                            plugin + " packaged source changed"):
                    CI.check_version_bump(root, base, "push")
                self.version(root, plugin, "1.0.1")
                self.commit(root, "bump affected plugin")
                CI.check_version_bump(root, base, "push")

    def test_shared_inputs_require_every_consumer_version_to_advance(self):
        with tempfile.TemporaryDirectory(prefix="split-ci-shared-") as tmp:
            root = Path(tmp)
            self.split_fixture(root)
            self.initialize_repository(root)
            base = self.commit(root)
            self.write(root, "shared/RUNTIME.md", "Changed shared runtime\n")
            self.version(root, "knowledge", "1.0.1")
            self.commit(root)
            with self.assertRaisesRegex(CI.ContractError,
                                        "investments packaged source changed"):
                CI.check_version_bump(root, base, "pull-request")
            self.version(root, "investments", "1.0.1")
            self.commit(root)
            CI.check_version_bump(root, base, "pull-request")

    def test_input_map_projection_and_removed_dependencies_are_versioned(self):
        for operation in ("add", "remove", "redirect"):
            with self.subTest(operation=operation), \
                    tempfile.TemporaryDirectory(prefix="split-ci-map-") as tmp:
                root = Path(tmp)
                maps = self.split_fixture(root)
                self.initialize_repository(root)
                base = self.commit(root)
                if operation == "remove":
                    del maps["knowledge"]["shared/CONVENTIONS.md"]
                    (root / "shared/CONVENTIONS.md").unlink()
                else:
                    self.write(root, "shared/new.md", "Additional knowledge input\n")
                    destination = ("shared/new.md" if operation == "add"
                                   else "shared/CONVENTIONS.md")
                    maps["knowledge"][destination] = "shared/new.md"
                self.write(root, CI.PACKAGE_MAPS, json.dumps(maps) + "\n")
                self.commit(root)
                with self.assertRaisesRegex(CI.ContractError,
                                            "knowledge packaged source changed"):
                    CI.check_version_bump(root, base, "push")
                self.version(root, "knowledge", "1.0.1")
                self.commit(root)
                CI.check_version_bump(root, base, "push")

    def test_ci_inventory_formatting_and_mode_changes_do_not_force_releases(self):
        with tempfile.TemporaryDirectory(prefix="split-ci-unchanged-") as tmp:
            root = Path(tmp)
            maps = self.split_fixture(root)
            self.initialize_repository(root)
            base = self.commit(root)
            self.write(root, ".github/ci.yml", "CI change\n")
            self.write(root, "tests/new_test.py", "# Contributor-only test\n")
            self.write(root, CI.PACKAGE_MAPS, json.dumps(maps, indent=2) + "\n")
            self.commit(root)
            self.git(root, "update-index", "--chmod=+x", "skills/wiki-add/SKILL.md")
            self.git(root, "commit", "-q", "-m", "mode only")
            CI.check_version_bump(root, base, "pull-request")

    def test_pull_request_attributes_map_changes_from_its_merge_base(self):
        with tempfile.TemporaryDirectory(prefix="split-ci-merge-base-") as tmp:
            root = Path(tmp)
            maps = self.split_fixture(root)
            self.initialize_repository(root)
            common = self.commit(root)
            self.write(root, "shared/new.md", "New knowledge dependency\n")
            maps["knowledge"]["shared/new.md"] = "shared/new.md"
            self.write(root, CI.PACKAGE_MAPS, json.dumps(maps) + "\n")
            self.version(root, "knowledge", "1.0.1")
            published = self.commit(root, "upstream knowledge release")
            self.git(root, "checkout", "-q", "--detach", common)
            self.write(root, ".github/branch.yml", "CI-only branch\n")
            self.commit(root)
            # The branch did not remove the upstream map entry; it has never
            # incorporated it. Compare actual PR changes from the merge base.
            CI.check_version_bump(root, published, "pull-request")
            with self.assertRaisesRegex(CI.ContractError,
                                        "knowledge packaged source changed"):
                CI.check_version_bump(root, published, "push")

    def test_generated_outputs_belong_to_their_own_distribution(self):
        for output in ("plugins/investments/.codex-plugin/plugin.json",
                       "plugins/investments/skills/market-research/SKILL.md",
                       "investments.plugin"):
            with self.subTest(output=output), \
                    tempfile.TemporaryDirectory(prefix="split-ci-output-") as tmp:
                root = Path(tmp)
                self.split_fixture(root)
                self.initialize_repository(root)
                base = self.commit(root)
                self.write(root, output, "Generated output changed\n")
                self.commit(root)
                with self.assertRaisesRegex(CI.ContractError,
                                            "investments packaged source changed"):
                    CI.check_version_bump(root, base, "push")
                self.version(root, "investments", "1.0.1")
                self.commit(root)
                CI.check_version_bump(root, base, "push")

    def test_legacy_split_transition_starts_two_new_release_histories(self):
        with tempfile.TemporaryDirectory(prefix="split-ci-transition-") as tmp:
            root = Path(tmp)
            self.write(root, CI.LEGACY_MANIFEST,
                       json.dumps({"name": "obsidian", "version": "1.47.3"}))
            self.initialize_repository(root)
            base = self.commit(root, "legacy distribution")
            self.split_fixture(root)
            (root / CI.LEGACY_MANIFEST).unlink()
            split = self.commit(root, "new identities")
            CI.check_version_bump(root, base, "push")
            CI.check_version_bump(root, base, "pull-request")
            # A first-release exemption cannot be repeated after the split.
            self.write(root, "skills/market-research/SKILL.md", "Changed\n")
            self.commit(root)
            with self.assertRaisesRegex(CI.ContractError,
                                        "investments packaged source changed"):
                CI.check_version_bump(root, split, "push")

    def test_split_transition_rejects_partial_and_ambiguous_release_layouts(self):
        for corruption in ("missing-investments", "old-manifest", "wrong-name",
                           "missing-map", "wrong-legacy-name"):
            with self.subTest(corruption=corruption), \
                    tempfile.TemporaryDirectory(prefix="split-ci-invalid-") as tmp:
                root = Path(tmp)
                legacy_name = "other" if corruption == "wrong-legacy-name" else "obsidian"
                self.write(root, CI.LEGACY_MANIFEST,
                           json.dumps({"name": legacy_name, "version": "1.47.3"}))
                self.initialize_repository(root)
                base = self.commit(root)
                self.split_fixture(root)
                if corruption != "old-manifest":
                    (root / CI.LEGACY_MANIFEST).unlink()
                if corruption == "missing-investments":
                    (root / "plugins/investments/.claude-plugin/plugin.json").unlink()
                elif corruption == "wrong-name":
                    self.write(root, "plugins/knowledge/.claude-plugin/plugin.json",
                               json.dumps({"name": "replacement", "version": "1.0.0"}))
                elif corruption == "missing-map":
                    (root / CI.PACKAGE_MAPS).unlink()
                self.commit(root)
                with self.assertRaises(CI.ContractError):
                    CI.check_version_bump(root, base, "push")

    def test_split_force_push_rejects_rollback_and_disappearing_distributions(self):
        with tempfile.TemporaryDirectory(prefix="split-ci-rollback-") as tmp:
            root = Path(tmp)
            self.write(root, CI.LEGACY_MANIFEST,
                       json.dumps({"name": "obsidian", "version": "1.47.3"}))
            self.initialize_repository(root)
            legacy = self.commit(root)
            self.split_fixture(root)
            (root / CI.LEGACY_MANIFEST).unlink()
            split = self.commit(root)
            self.version(root, "investments", "1.0.1")
            self.write(root, "skills/market-research/SKILL.md", "Published\n")
            published = self.commit(root)
            self.git(root, "checkout", "-q", "--detach", split)
            self.write(root, ".github/rewrite.yml", "CI rewrite\n")
            self.commit(root)
            CI.check_version_bump(root, published, "pull-request")
            with self.assertRaisesRegex(CI.ContractError,
                                        "investments packaged source changed"):
                CI.check_version_bump(root, published, "push")
            self.git(root, "checkout", "-q", "--detach", legacy)
            with self.assertRaisesRegex(CI.ContractError, "cannot roll back"):
                CI.check_version_bump(root, published, "push")

    def test_invalid_or_ambiguous_maps_cannot_disable_the_gate(self):
        corruptions = (
            '{"knowledge": {}, "knowledge": {}, "investments": {}}',
            '{"knowledge": {}}',
            '{"knowledge": [], "investments": {}}',
            '{"knowledge": {"../escaped": "shared/RUNTIME.md"}, "investments": {}}',
        )
        for corruption in corruptions:
            with self.subTest(corruption=corruption), \
                    tempfile.TemporaryDirectory(prefix="split-ci-bad-map-") as tmp:
                root = Path(tmp)
                self.split_fixture(root)
                self.initialize_repository(root)
                base = self.commit(root)
                self.write(root, CI.PACKAGE_MAPS, corruption)
                self.commit(root)
                with self.assertRaises(CI.ContractError):
                    CI.check_version_bump(root, base, "push")


if __name__ == "__main__":
    unittest.main()
