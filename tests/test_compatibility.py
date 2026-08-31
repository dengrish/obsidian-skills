#!/usr/bin/env python3
"""Host-independent checks for installation layout and portable execution."""

import importlib.util
import io
import json
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CompatibilityTests(unittest.TestCase):
    def test_skill_frontmatter_parses_as_yaml(self):
        for path in sorted((ROOT / "skills").glob("*/SKILL.md")):
            with self.subTest(skill=path.parent.name):
                text = path.read_text(encoding="utf-8")
                self.assertTrue(text.startswith("---\n"))
                metadata = yaml.safe_load(text.split("---", 2)[1])
                self.assertEqual(metadata["name"], path.parent.name)
                self.assertIsInstance(metadata["description"], str)
                self.assertTrue(metadata["description"].strip())
                self.assertLessEqual(len(metadata["description"]), 1024)

    def test_manifests_share_metadata_and_skill_tree(self):
        claude = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())
        codex = json.loads((ROOT / ".codex-plugin/plugin.json").read_text())
        for key, value in claude.items():
            self.assertEqual(codex[key], value, key)
        claude_skills = ROOT / claude.get("skills", "skills")
        codex_skills = ROOT / codex["skills"]
        self.assertEqual(claude_skills.resolve(), codex_skills.resolve())
        skills = sorted(claude_skills.glob("*/SKILL.md"))
        self.assertEqual(len(skills), 6)
        for path in skills:
            self.assertTrue((path.parent / "../../shared/RUNTIME.md").resolve().is_file())

    def test_archive_is_complete_and_current(self):
        build = load("build_plugin", ROOT / "tools/build_plugin.py")
        expected = build.package_files(ROOT)
        content = (ROOT / "obsidian.plugin").read_bytes()
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertEqual(set(archive.namelist()), set(expected))
            self.assertEqual(len(archive.namelist()), len(expected))
            for name, data in expected.items():
                self.assertEqual(archive.read(name), data, name)
                self.assertFalse(Path(name).is_absolute())
                self.assertNotIn("..", Path(name).parts)
        self.assertEqual(content, build.archive_bytes(expected))

    def test_packaged_helpers_run_outside_plugin_directory(self):
        # Hosts execute helpers while their cwd is the user's vault, and
        # plugin cache paths commonly contain spaces. Exercise the real CLIs.
        with tempfile.TemporaryDirectory(prefix="obsidian-install-") as tmp:
            install = Path(tmp) / "plugin with spaces"
            vault = Path(tmp) / "vault with spaces"
            vault.mkdir()
            with zipfile.ZipFile(ROOT / "obsidian.plugin") as archive:
                archive.extractall(install)
            for path in sorted((install / "skills").glob("*/scripts/*.py")):
                with self.subTest(script=path.name):
                    result = subprocess.run(
                        [sys.executable, str(path), "--help"], cwd=vault,
                        capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            # Both instruction and shared-resource references survive copying.
            imported = (install / "CLAUDE.md").read_text().strip().removeprefix("@")
            self.assertEqual((install / imported).read_bytes(), (ROOT / "AGENTS.md").read_bytes())
            check = [sys.executable, str(install / "tools/build_plugin.py"), "--check"]
            # The archive does not contain itself: build it in the isolated copy.
            subprocess.run(check[:-1], cwd=vault, check=True, capture_output=True)
            self.assertEqual(subprocess.run(check, cwd=vault, capture_output=True).returncode, 0)
            with (install / "shared/RUNTIME.md").open("a") as output:
                output.write("\nChanged after packaging.\n")
            self.assertNotEqual(subprocess.run(check, cwd=vault, capture_output=True).returncode, 0)

    def test_ambiguous_numeric_hosts_cannot_depend_on_resolver(self):
        fetch = load("fetch_images", ROOT / "skills/clipping-processor/scripts/fetch_images.py")
        public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("177.0.0.1", 0))]
        with patch.object(fetch.socket, "getaddrinfo", return_value=public) as resolve:
            for host in ("0177.0.0.1", "0x7f000001", "2130706433", "127.1"):
                with self.subTest(host=host), self.assertRaises(ValueError):
                    fetch.check_url("http://" + host + "/image.png")
            resolve.assert_not_called()
            fetch.check_url("https://177.0.0.1/image.png")
            resolve.assert_called_once()

    def test_generated_commands_preserve_interpreter_and_literal_paths(self):
        scripts = ROOT / "skills/pdf-figure-extractor/scripts"
        sys.path.insert(0, str(scripts))
        try:
            batch = load("batch_extract", scripts / "batch_extract.py")
            interpreter = "/tmp/python environment/bin/python3"
            with patch.object(batch.sys, "executable", interpreter):
                command = batch.mark_reviewed_command(
                    "/tmp/vault's PDFs", "/tmp/images $literal", "Doe_Paper_2026", "1")
            self.assertEqual(shlex.split(command), [
                interpreter, str(scripts / "batch_extract.py"),
                "--src", "/tmp/vault's PDFs", "--out", "/tmp/images $literal",
                "--mark-reviewed", "Doe_Paper_2026:1",
            ])
        finally:
            sys.path.remove(str(scripts))


if __name__ == "__main__":
    unittest.main()
