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


if __name__ == "__main__":
    unittest.main()
