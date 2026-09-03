#!/usr/bin/env python3
"""Host-independent checks for installation layout and portable execution."""

import importlib.util
import io
import json
import os
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
    def test_private_mode_and_wiki_slugs_are_native_windows_portable(self):
        atomic = load("compat_atomic_move", ROOT / "shared/scripts/atomic_move.py")
        slugger = load("compat_slugify", ROOT / "shared/scripts/slugify.py")
        with tempfile.TemporaryDirectory(prefix="obsidian-mode-portability-") as tmp:
            path = Path(tmp) / "staged"
            with path.open("xb") as staged, patch.object(
                    atomic.os, "fchmod", None, create=True):
                atomic.set_private_mode(staged, str(path), 0o640)
            self.assertTrue(path.is_file())
            if os.name != "nt":
                self.assertEqual(os.stat(path).st_mode & 0o777, 0o640)
        for title in ("CON", "prn", "AUX", "nul", "COM1", "com9",
                      "LPT1", "lpt9"):
            with self.subTest(title=title), self.assertRaises(slugger.SlugError):
                slugger.slugify(title)
        self.assertEqual(slugger.slugify("Convolution"), "convolution.md")

    def test_runtime_probe_accepts_both_supported_pymupdf_import_names(self):
        runtime = (ROOT / "shared/RUNTIME.md").read_text(encoding="utf-8")
        requirements = (
            ROOT / "skills/pdf-figure-extractor/scripts/requirements.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("PyMuPDF>=1.20", requirements)
        self.assertRegex(
            runtime,
            r"try:\n\s+import pymupdf\nexcept ImportError:\n\s+import fitz",
        )

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

    def test_marketplace_metadata_identifies_the_authored_plugin(self):
        manifest = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())
        marketplace = json.loads(
            (ROOT / ".claude-plugin/marketplace.json").read_text())
        self.assertEqual(marketplace["name"], "obsidian-skills")
        self.assertIsInstance(marketplace["description"], str)
        self.assertTrue(marketplace["description"].strip())
        self.assertEqual(marketplace["owner"], manifest["author"])
        self.assertEqual(len(marketplace["plugins"]), 1)
        entry = marketplace["plugins"][0]
        self.assertEqual(entry["name"], manifest["name"])
        self.assertEqual(entry["source"], "./")
        self.assertEqual(entry["description"], manifest["description"])

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

    def test_packaging_derives_the_loose_and_archived_codex_manifest_once(self):
        build = load("build_plugin_single_manifest", ROOT / "tools/build_plugin.py")
        derived = b"one exact derived manifest\n"
        with patch.object(build, "_codex_manifest_bytes",
                          return_value=derived) as convert:
            files = build.package_files(ROOT)
        convert.assert_called_once_with(files[".claude-plugin/plugin.json"])
        self.assertEqual(files[".codex-plugin/plugin.json"], derived)

    def test_packaging_does_not_read_through_source_symlinks(self):
        build = load("build_plugin", ROOT / "tools/build_plugin.py")
        with tempfile.TemporaryDirectory(prefix="obsidian-package-boundary-") as tmp:
            root = Path(tmp) / "plugin"
            root.mkdir()
            for name in ("AGENTS.md", "CLAUDE.md", "README.md", "requirements.txt", "requirements-dev.txt"):
                (root / name).write_bytes((ROOT / name).read_bytes())
            (root / ".claude-plugin").mkdir()
            (root / ".claude-plugin/plugin.json").write_bytes(
                (ROOT / ".claude-plugin/plugin.json").read_bytes())
            (root / "skills").mkdir()
            foreign = Path(tmp) / "outside.txt"
            foreign.write_text("not repository content", encoding="utf-8")
            for name in ("skills/linked.md", "README.md", ".claude-plugin/plugin.json", "shared"):
                with self.subTest(path=name):
                    path = root / name
                    original = path.read_bytes() if path.is_file() else None
                    if path.exists():
                        path.unlink()
                    path.symlink_to(foreign)
                    try:
                        with self.assertRaisesRegex(ValueError, "symlink"):
                            build.package_files(root)
                    finally:
                        path.unlink()
                        if original is not None:
                            path.write_bytes(original)
                    self.assertEqual(foreign.read_text(), "not repository content")

    def test_packaging_rejects_a_source_swapped_during_the_read(self):
        build = load("build_plugin_source_race", ROOT / "tools/build_plugin.py")
        with tempfile.TemporaryDirectory(prefix="obsidian-package-race-") as tmp:
            root = Path(tmp) / "plugin"
            root.mkdir()
            for name in ("AGENTS.md", "CLAUDE.md", "README.md",
                         "requirements.txt", "requirements-dev.txt"):
                (root / name).write_bytes((ROOT / name).read_bytes())
            (root / ".claude-plugin").mkdir()
            (root / ".claude-plugin/plugin.json").write_bytes(
                (ROOT / ".claude-plugin/plugin.json").read_bytes())
            victim = root / "README.md"
            original = victim.read_bytes()
            foreign = Path(tmp) / "outside.txt"
            foreign.write_bytes(b"never package these bytes")
            real_open = build.os.open
            injected = {"done": False}

            def swap_leaf(path, flags, *args, **kwargs):
                if (os.path.abspath(path) == os.path.abspath(victim)
                        and not injected["done"]):
                    injected["done"] = True
                    victim.unlink()
                    victim.symlink_to(foreign)
                return real_open(path, flags, *args, **kwargs)

            with patch.object(build.os, "open", side_effect=swap_leaf):
                with self.assertRaises((OSError, ValueError)):
                    build.package_files(root)
            self.assertTrue(victim.is_symlink())
            self.assertEqual(foreign.read_bytes(), b"never package these bytes")

            victim.unlink()
            victim.write_bytes(original)
            injected["done"] = False

            def change_in_place(path, flags, *args, **kwargs):
                if (os.path.abspath(path) == os.path.abspath(victim)
                        and not injected["done"]):
                    injected["done"] = True
                    with victim.open("ab") as output:
                        output.write(b"changed after lstat")
                return real_open(path, flags, *args, **kwargs)

            with patch.object(build.os, "open", side_effect=change_in_place):
                with self.assertRaises(OSError):
                    build.package_files(root)

    def test_build_does_not_write_through_output_symlinks(self):
        with tempfile.TemporaryDirectory(prefix="obsidian-build-boundary-") as tmp:
            root = Path(tmp) / "plugin"
            (root / "tools").mkdir(parents=True)
            (root / "shared/scripts").mkdir(parents=True)
            script = root / "tools/build_plugin.py"
            script.write_bytes((ROOT / "tools/build_plugin.py").read_bytes())
            (root / "shared/scripts/atomic_move.py").write_bytes(
                (ROOT / "shared/scripts/atomic_move.py").read_bytes())
            foreign = Path(tmp) / "outside.txt"
            foreign.write_text("preserve external bytes", encoding="utf-8")
            (root / "obsidian.plugin").symlink_to(foreign)
            result = subprocess.run([sys.executable, str(script)], cwd=tmp,
                                    capture_output=True, text=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symlink", result.stderr)
            self.assertEqual(foreign.read_text(), "preserve external bytes")
            self.assertTrue((root / "obsidian.plugin").is_symlink())

    def test_generated_publication_preserves_late_occupants_and_changes(self):
        build = load("build_plugin_publication", ROOT / "tools/build_plugin.py")
        with tempfile.TemporaryDirectory(prefix="obsidian-build-races-") as tmp:
            root = Path(tmp) / "plugin"
            root.mkdir()
            output = root / "generated/output.bin"
            output.parent.mkdir()
            real_link = build.atomic_move.link_noreplace

            foreign = root.parent / "foreign.bin"
            foreign.write_bytes(b"foreign bytes")

            def inject_symlink(source, target):
                if (Path(target).name == output.name
                        and not os.path.lexists(output)):
                    output.symlink_to(foreign)
                return real_link(source, target)

            with patch.object(build.atomic_move, "link_noreplace",
                              side_effect=inject_symlink):
                with self.assertRaises(OSError):
                    build._publish_generated(root, output, b"generated", None)
            self.assertTrue(output.is_symlink())
            self.assertEqual(foreign.read_bytes(), b"foreign bytes")
            output.unlink()

            late = b"another builder arrived first"

            def inject_occupant(source, target):
                if (Path(target).name == output.name
                        and not os.path.lexists(output)):
                    output.write_bytes(late)
                return real_link(source, target)

            with patch.object(build.atomic_move, "link_noreplace",
                              side_effect=inject_occupant):
                with self.assertRaises(OSError):
                    build._publish_generated(root, output, b"generated", None)
            self.assertEqual(output.read_bytes(), late)

            expected = build._observe_output(output)
            changed = b"edited during the build"
            injected = {"done": False}

            def inject_change(source, target):
                if (Path(source).name == output.name
                        and Path(target).name == ".atomic-observed"
                        and not injected["done"]):
                    injected["done"] = True
                    output.write_bytes(changed)
                return real_link(source, target)

            with patch.object(build.atomic_move, "link_noreplace",
                              side_effect=inject_change):
                with self.assertRaises(OSError):
                    build._publish_generated(
                        root, output, b"new generated bytes", expected)
            self.assertEqual(output.read_bytes(), changed)

    def test_generated_publication_uses_a_portable_bound_output_parent(self):
        build = load("build_plugin_output_parent", ROOT / "tools/build_plugin.py")
        with tempfile.TemporaryDirectory(prefix="obsidian-build-parent-") as tmp:
            root = Path(tmp) / "plugin"
            root.mkdir()
            output = root / "new/nested/generated.bin"
            output.parent.mkdir(parents=True)
            parent = build._directory_identity(output.parent)
            build._publish_generated(
                root, output, b"complete bytes", None, parent)
            self.assertEqual(output.read_bytes(), b"complete bytes")
            self.assertFalse(any(output.parent.glob(".plugin-build-stage-*")))

            fallback = output.parent / "fallback.bin"
            cwd = os.getcwd()
            with patch.object(build.os, "fchdir", None, create=True):
                build._publish_generated(
                    root, fallback, b"fallback bytes", None, parent)
            self.assertEqual(fallback.read_bytes(), b"fallback bytes")
            self.assertEqual(os.getcwd(), cwd)

    def test_generated_publication_rejects_a_late_parent_symlink(self):
        build = load("build_plugin_parent_race", ROOT / "tools/build_plugin.py")
        with tempfile.TemporaryDirectory(prefix="obsidian-build-parent-race-") as tmp:
            root = Path(tmp) / "plugin"
            parent = root / "generated"
            foreign = Path(tmp) / "foreign"
            parent.mkdir(parents=True)
            foreign.mkdir()
            output = parent / "output.bin"
            expected_parent = build._directory_identity(parent)
            original_parent = root / "original-parent"
            real_link = build.atomic_move.link_noreplace
            injected = {"done": False}

            def inject_parent(source, target):
                result = real_link(source, target)
                if (Path(target).name == output.name
                        and not injected["done"]):
                    injected["done"] = True
                    parent.rename(original_parent)
                    parent.symlink_to(foreign, target_is_directory=True)
                return result

            with patch.object(build.atomic_move, "link_noreplace",
                              side_effect=inject_parent):
                with self.assertRaises(OSError):
                    build._publish_generated(
                        root, output, b"generated", None, expected_parent)
            self.assertFalse((foreign / output.name).exists())
            self.assertFalse((original_parent / output.name).exists())
            self.assertFalse(any(
                original_parent.glob(".plugin-build-*")
            ))

    def test_generated_pair_rolls_back_when_the_second_output_changes(self):
        build = load("build_plugin_group_rollback", ROOT / "tools/build_plugin.py")
        with tempfile.TemporaryDirectory(prefix="obsidian-build-group-") as tmp:
            root = Path(tmp) / "plugin"
            root.mkdir()
            first = root / "first.generated"
            second = root / "second.generated"
            first.write_bytes(b"old first")
            second.write_bytes(b"old second")
            os.chmod(first, 0o640)
            observed = {
                first: build._observe_output(first),
                second: build._observe_output(second),
            }
            parent = build._directory_identity(root)
            parents = {first: parent, second: parent}
            outputs = {first: b"new first", second: b"new second"}
            real_publish = build._publish_generated
            injected = {"done": False}

            def inject_second(*args, **kwargs):
                path = Path(args[1])
                if path == second and not injected["done"]:
                    injected["done"] = True
                    second.write_bytes(b"late second edit")
                return real_publish(*args, **kwargs)

            with patch.object(build, "_publish_generated",
                              side_effect=inject_second):
                with self.assertRaises(OSError):
                    build._publish_outputs(root, outputs, observed, parents)
            self.assertEqual(first.read_bytes(), b"old first")
            self.assertEqual(second.read_bytes(), b"late second edit")
            if os.name != "nt":
                self.assertEqual(os.stat(first).st_mode & 0o777, 0o640)

    def test_generated_pair_accepts_a_concurrent_builder_converging(self):
        build = load("build_plugin_group_converge", ROOT / "tools/build_plugin.py")
        with tempfile.TemporaryDirectory(prefix="obsidian-build-converge-") as tmp:
            root = Path(tmp) / "plugin"
            root.mkdir()
            first = root / "first.generated"
            second = root / "second.generated"
            first.write_bytes(b"old first")
            second.write_bytes(b"old second")
            observed = {
                first: build._observe_output(first),
                second: build._observe_output(second),
            }
            parent = build._directory_identity(root)
            parents = {first: parent, second: parent}
            outputs = {first: b"new first", second: b"new second"}
            real_publish = build._publish_generated
            injected = {"done": False}

            def converge_second(*args, **kwargs):
                path = Path(args[1])
                if path == second and not injected["done"]:
                    injected["done"] = True
                    second.write_bytes(outputs[second])
                return real_publish(*args, **kwargs)

            with patch.object(build, "_publish_generated",
                              side_effect=converge_second):
                stale = build._publish_outputs(
                    root, outputs, observed, parents)
            self.assertEqual(stale, [first, second])
            self.assertEqual(first.read_bytes(), outputs[first])
            self.assertEqual(second.read_bytes(), outputs[second])

    def test_convention_probe_separates_text_parsers_from_slug_writers(self):
        conventions = load("convention_probe", ROOT / "tests/test_conventions.py")
        with tempfile.TemporaryDirectory(prefix="obsidian-probe-") as tmp:
            directory = Path(tmp)
            sentinel = directory / "must-not-be-written"
            sources = {
                "text_parser.py": (
                    "import re, unicodedata\n"
                    "TABLE = re.compile(r'-{2,}')\n"
                    "def lint(text):\n"
                    f"    open({str(sentinel)!r}, 'w').write(text)\n"
                    "    return unicodedata.normalize('NFC', text)\n"),
                "unsafe_slug.py": (
                    "def slug_stem(title):\n"
                    f"    open({str(sentinel)!r}, 'w').write(title)\n"
                    "    return title.lower().replace(' ', '-')\n"),
                "renamed_slug.py": (
                    "import re\n"
                    "def to_name(title):\n"
                    "    return re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')\n"),
            }
            results = {}
            for name, source in sources.items():
                path = directory / name
                path.write_text(source, encoding="utf-8")
                results[name] = conventions.probe_module(str(path))
                self.assertIsNone(conventions.probe_failure(results[name], name))
            self.assertEqual(results["text_parser.py"]["screened"], [])
            self.assertEqual(results["text_parser.py"]["producers"], [])
            self.assertIn("slug_stem", results["unsafe_slug.py"]["screened"])
            self.assertTrue(results["unsafe_slug.py"]["defines"]["slug_stem"])
            detected = results["renamed_slug.py"]["producers"]
            self.assertEqual([item["name"] for item in detected], ["to_name"])
            self.assertFalse(detected[0]["delegates"])
            self.assertTrue(any(case[0] == "C++" for case in detected[0]["diffs"]))
            self.assertFalse(sentinel.exists())

    def test_heading_check_preserves_import_paths_and_reports_unreadable_rules(self):
        conventions = load("convention_headings", ROOT / "tests/test_conventions.py")
        before = list(sys.path)
        module = conventions.mod_generic(str(ROOT / "skills/paper-summarizer/scripts/note_lint.py"))
        self.assertIsNotNone(module)
        self.assertEqual(sys.path, before)
        report = conventions.Report()
        with patch.object(conventions, "mod_generic", return_value=None):
            conventions.check_note_headings(report, (ROOT / "shared/CONVENTIONS.md").read_text())
        self.assertEqual(report.exit_code(), 1)
        self.assertTrue(any("GENERIC_HEADINGS" in row[3] for row in report.by_status("FAIL")))

    def test_heading_contract_requires_its_reference_and_ordered_examples(self):
        conventions = load("convention_heading_contract", ROOT / "tests/test_conventions.py")
        format_path = ROOT / "skills/paper-summarizer/references/note-format.md"
        conv = (ROOT / "shared/CONVENTIONS.md").read_text()
        isfile = conventions.os.path.isfile
        report = conventions.Report()
        with patch.object(conventions.os.path, "isfile", side_effect=lambda path:
                          False if Path(path) == format_path else isfile(path)):
            conventions.check_note_headings(report, conv)
        self.assertEqual(report.exit_code(), 1)
        self.assertTrue(any("contract is missing" in row[3]
                            for row in report.by_status("FAIL")))

        lines = format_path.read_text(encoding="utf-8").splitlines()
        question = next(i for i, line in enumerate(lines) if line.startswith("| Question |"))
        methods = next(i for i, line in enumerate(lines) if line.startswith("| Methods |"))
        reordered = list(lines)
        reordered[question], reordered[methods] = reordered[methods], reordered[question]
        duplicated = list(lines)
        duplicated.insert(question, duplicated[question])
        read = conventions.read
        for label, changed in (("reordered", reordered), ("duplicate", duplicated)):
            with self.subTest(examples=label):
                report = conventions.Report()
                with patch.object(conventions, "read", side_effect=lambda path:
                                  "\n".join(changed) if Path(path) == format_path else read(path)):
                    conventions.check_note_headings(report, conv)
                self.assertEqual(report.exit_code(), 1)
                self.assertTrue(any("role table" in row[3]
                                    for row in report.by_status("FAIL")))

    def test_figure_caption_checks_follow_the_writers_scope(self):
        conventions = load("convention_caption_scope", ROOT / "tests/test_conventions.py")
        conv = (ROOT / "shared/CONVENTIONS.md").read_text()
        for skill, caption, expected in (
            ("clipping-processor", "", 0),
            ("paper-summarizer", "", 1),
            ("wiki-builder", "*The study design.*", 0),
        ):
            with self.subTest(skill=skill, caption=bool(caption)):
                text = "`[source_stem]_fig*`\n\n![[Doe_Study_2025_fig_1.png]]\n" + caption + "\n"
                path = str(ROOT / "skills" / skill / "references" / "example.md")
                report = conventions.Report()
                with patch.object(conventions, "walk_skill_files", return_value=[(skill, path, text)]), \
                        patch.object(conventions, "FIG_NAME_MIN", 1):
                    conventions.check_figure_naming(report, conv)
                self.assertEqual(report.exit_code(), expected)
                if expected:
                    self.assertTrue(any("no italic caption" in row[3]
                                        for row in report.by_status("FAIL")))

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
