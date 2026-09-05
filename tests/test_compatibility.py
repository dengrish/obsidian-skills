#!/usr/bin/env python3
"""Checks for installation layout and supported-platform execution."""

import ast
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _can_create_symlink():
    """Whether this host grants the test process symlink privileges."""
    try:
        with tempfile.TemporaryDirectory(prefix="obsidian-symlink-probe-") as tmp:
            root = Path(tmp)
            target = root / "target"
            link = root / "link"
            target.write_text("probe", encoding="utf-8")
            link.symlink_to(target)
            return link.is_symlink()
    except (AttributeError, NotImplementedError, OSError):
        return False


CAN_CREATE_SYMLINK = _can_create_symlink()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def copy_package_source(destination):
    """Copy the authored package boundary without Git state or generated output."""
    destination.mkdir()
    for name in (".gitattributes", "AGENTS.md", "CLAUDE.md", "README.md",
                 "requirements.txt", "requirements-dev.txt"):
        shutil.copy2(ROOT / name, destination / name)
    for name in (".claude-plugin", "skills", "shared", "tests", "tools"):
        shutil.copytree(
            ROOT / name, destination / name,
            ignore=shutil.ignore_patterns(".DS_Store", "__pycache__", "*.pyc", "*.pyo"))


class CompatibilityTests(unittest.TestCase):
    def test_repository_normalizes_text_and_preserves_plugin_bytes(self):
        attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertEqual(attributes, "* text=auto eol=lf\n*.plugin binary\n")

    def test_python_text_boundaries_are_explicitly_utf8(self):
        problems = []
        roots = (ROOT / ".github", ROOT / "shared", ROOT / "skills",
                 ROOT / "tools", ROOT / "tests")
        for path in sorted(p for root in roots for p in root.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                keywords = {item.arg: item.value for item in node.keywords
                            if item.arg is not None}
                expansion = any(item.arg is None for item in node.keywords)
                if (isinstance(node.func, ast.Attribute)
                        and node.func.attr in ("read_text", "write_text")):
                    if "encoding" not in keywords:
                        problems.append(
                            "%s:%d %s() has no encoding" %
                            (path.relative_to(ROOT), node.lineno, node.func.attr))
                    continue
                if (isinstance(node.func, ast.Attribute)
                        and node.func.attr == "open"):
                    # Path.open() takes its mode as argument 1. Restrict this
                    # static check to literal mode strings so APIs such as
                    # ZipFile.open(member) and fitz.open(path) are not mistaken
                    # for text-file boundaries.
                    mode = keywords.get("mode")
                    if mode is None and node.args:
                        mode = node.args[0]
                    if (isinstance(mode, ast.Constant)
                            and isinstance(mode.value, str)
                            and re.fullmatch(r"[rwaxbt+]+", mode.value)
                            and "b" not in mode.value
                            and "encoding" not in keywords and not expansion):
                        problems.append(
                            "%s:%d Path.open(%r) has no encoding" %
                            (path.relative_to(ROOT), node.lineno, mode.value))
                    continue
                if isinstance(node.func, ast.Name) and node.func.id == "open":
                    mode = "r"
                    if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                        mode = node.args[1].value
                    if ("mode" in keywords
                            and isinstance(keywords["mode"], ast.Constant)):
                        mode = keywords["mode"].value
                    if (isinstance(mode, str) and "b" not in mode
                            and "encoding" not in keywords and not expansion):
                        problems.append(
                            "%s:%d open(%r) has no encoding" %
                            (path.relative_to(ROOT), node.lineno, mode))
                    continue
                if (isinstance(node.func, ast.Attribute)
                        and node.func.attr in
                        ("run", "Popen", "check_output", "check_call")):
                    text_mode = False
                    for key in ("text", "universal_newlines"):
                        value = keywords.get(key)
                        if value is not None and (
                                not isinstance(value, ast.Constant) or value.value):
                            text_mode = True
                    if text_mode and "encoding" not in keywords:
                        problems.append(
                            "%s:%d subprocess text mode has no encoding" %
                            (path.relative_to(ROOT), node.lineno))
        self.assertEqual(problems, [])

    def test_private_mode_is_applied(self):
        atomic = load("compat_atomic_move", ROOT / "shared/scripts/atomic_move.py")
        with tempfile.TemporaryDirectory(prefix="obsidian-mode-portability-") as tmp:
            path = Path(tmp) / "staged"
            with path.open("xb") as staged:
                atomic.set_private_mode(staged, 0o640)
            self.assertTrue(path.is_file())
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o640)

    def test_runtime_probe_enforces_supported_dependency_floors(self):
        runtime = (ROOT / "shared/RUNTIME.md").read_text(encoding="utf-8")
        figure_requirements = (
            ROOT / "skills/pdf-figure-extractor/scripts/requirements.txt"
        ).read_text(encoding="utf-8")
        root_requirements = (ROOT / "requirements.txt").read_text(
            encoding="utf-8")
        self.assertIn("PyMuPDF>=1.28.0", figure_requirements)
        self.assertIn("Pillow>=12.3.0", figure_requirements)
        self.assertIn("pypdf>=6.16.1", root_requirements)
        self.assertIn("Python 3.10+", runtime)
        for probe in (
                '"pypdf": (6, 16, 1)',
                '"PyMuPDF": (1, 28, 0)',
                '"Pillow": (12, 3, 0)'):
            self.assertIn(probe, runtime)
        self.assertIn("import pymupdf", runtime)
        self.assertNotIn("import fitz", runtime)

    def test_shared_helper_docs_use_the_plugin_python_floor(self):
        helpers = (
            "code_typography.py",
            "entry_structure.py",
            "equation_coverage.py",
            "introduced_aliases.py",
            "markdown_tables.py",
            "organism_names.py",
        )
        for name in helpers:
            with self.subTest(helper=name):
                source = (ROOT / "shared/scripts" / name).read_text(
                    encoding="utf-8")
                self.assertIn("Python 3.10+", source)
                self.assertNotIn("Python 3.8+", source)
                self.assertNotIn("Python 3.9+", source)

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
        claude = json.loads(
            (ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
        codex = json.loads(
            (ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        for key, value in claude.items():
            self.assertEqual(codex[key], value, key)
        claude_skills = ROOT / claude.get("skills", "skills")
        codex_skills = ROOT / codex["skills"]
        self.assertEqual(claude_skills.resolve(), codex_skills.resolve())
        skills = sorted(claude_skills.glob("*/SKILL.md"))
        self.assertEqual({path.parent.name for path in skills}, {
            "clipping-processor", "paper-summarizer", "pdf-figure-extractor",
            "pdf-organizer", "wiki-add", "wiki-builder", "wiki-linter",
        })
        for path in skills:
            self.assertTrue((path.parent / "../../shared/RUNTIME.md").resolve().is_file())

    def test_marketplace_metadata_identifies_the_authored_plugin(self):
        manifest = json.loads(
            (ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
        marketplace = json.loads(
            (ROOT / ".claude-plugin/marketplace.json").read_text(
                encoding="utf-8"))
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
            self.assertTrue(all(
                info.compress_type == zipfile.ZIP_STORED
                for info in archive.infolist()))
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

    def test_package_inventory_includes_declared_assets_and_rejects_unknown_files(self):
        build = load("build_plugin_inventory", ROOT / "tools/build_plugin.py")
        with tempfile.TemporaryDirectory(prefix="obsidian-package-inventory-") as tmp:
            root = Path(tmp) / "plugin"
            copy_package_source(root)
            asset = root / "skills/example/assets/diagram.svg"
            asset.parent.mkdir(parents=True)
            asset.write_bytes(b"<svg/>\n")
            with self.assertRaisesRegex(ValueError, "unlisted files"):
                build.package_files(root)

            inventory = root / build.PACKAGE_INVENTORY
            names = inventory.read_text(encoding="utf-8").splitlines()
            names.append(asset.relative_to(root).as_posix())
            inventory.write_text(
                "\n".join(sorted(names)) + "\n", encoding="utf-8")
            packaged = build.package_files(root)
            self.assertEqual(packaged["skills/example/assets/diagram.svg"],
                             b"<svg/>\n")

            (root / "skills/.DS_Store").write_bytes(b"finder metadata")
            cache = root / "skills/example/__pycache__"
            cache.mkdir()
            (cache / "helper.pyc").write_bytes(b"bytecode")
            self.assertEqual(build.package_files(root)[
                "skills/example/assets/diagram.svg"], b"<svg/>\n")

    def test_archive_rejects_unsafe_or_colliding_names(self):
        build = load("build_plugin_names", ROOT / "tools/build_plugin.py")
        cases = (
            {"/absolute.md": b"x"},
            {"../escape.md": b"x"},
            {"skills/control\x1f.md": b"x"},
            {"skills/Entry.md": b"a", "skills/entry.md": b"b"},
            {"skills/Cafe\N{COMBINING ACUTE ACCENT}.md": b"x"},
            {"skills/Caf\N{LATIN SMALL LETTER E WITH ACUTE}.md": b"a",
             "skills/Cafe\N{COMBINING ACUTE ACCENT}.md": b"b"},
        )
        for files in cases:
            with self.subTest(paths=tuple(files)), self.assertRaises(ValueError):
                build.archive_bytes(files)

    @unittest.skipUnless(CAN_CREATE_SYMLINK,
                         "host does not grant symlink privileges")
    def test_packaging_does_not_read_through_source_symlinks(self):
        build = load("build_plugin", ROOT / "tools/build_plugin.py")
        with tempfile.TemporaryDirectory(prefix="obsidian-package-boundary-") as tmp:
            root = Path(tmp) / "plugin"
            copy_package_source(root)
            foreign = Path(tmp) / "outside.txt"
            foreign.write_text("not repository content", encoding="utf-8")
            for name in ("skills/linked.md", "README.md", ".claude-plugin/plugin.json", "shared"):
                with self.subTest(path=name):
                    path = root / name
                    original = path.read_bytes() if path.is_file() else None
                    backup = root / (".package-test-saved-" + path.name)
                    if path.is_dir():
                        path.rename(backup)
                    elif path.exists():
                        path.unlink()
                    path.symlink_to(foreign)
                    try:
                        with self.assertRaisesRegex(ValueError, "symlink"):
                            build.package_files(root)
                    finally:
                        path.unlink()
                        if backup.exists():
                            backup.rename(path)
                        elif original is not None:
                            path.write_bytes(original)
                    self.assertEqual(
                        foreign.read_text(encoding="utf-8"),
                        "not repository content")

    @unittest.skipUnless(CAN_CREATE_SYMLINK,
                         "host does not grant symlink privileges")
    def test_packaging_rejects_a_source_swapped_during_the_read(self):
        build = load("build_plugin_source_race", ROOT / "tools/build_plugin.py")
        with tempfile.TemporaryDirectory(prefix="obsidian-package-race-") as tmp:
            root = Path(tmp) / "plugin"
            copy_package_source(root)
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

    def test_stable_readers_reject_same_file_changes_during_read(self):
        build = load("build_plugin_changed_read", ROOT / "tools/build_plugin.py")
        atomic = load("atomic_move_changed_read", ROOT / "shared/scripts/atomic_move.py")
        index = load(
            "vault_index_changed_read",
            ROOT / "skills/wiki-builder/scripts/vault_index.py")
        lint = load(
            "lint_entry_changed_read",
            ROOT / "skills/wiki-builder/scripts/lint_entry.py")
        scan = load(
            "scan_vault_changed_read",
            ROOT / "skills/wiki-linter/scripts/scan_vault.py")

        def changing_fstat(path):
            real_fstat = os.fstat
            calls = {"count": 0}

            def change_after_read(descriptor):
                calls["count"] += 1
                if calls["count"] == 2:
                    with path.open("ab") as output:
                        output.write(b"\nchanged during read\n")
                return real_fstat(descriptor)

            return change_after_read

        note_text = (
            '---\ntitle: "Anchor"\ntype: "Concept"\naliases: []\n'
            'sources: []\ncreated: "2026-01-01"\nupdated: "2026-01-01"\n'
            'description: "A stable test entry."\ntags: []\nparents: []\n'
            'read: false\n---\n\n**Anchor** is a stable test entry.\n'
        )
        with tempfile.TemporaryDirectory(prefix="obsidian-changed-read-") as tmp:
            root = Path(tmp)
            source = root / "source.md"
            source.write_bytes(b"stable source\n")
            with patch.object(build.os, "fstat",
                              side_effect=changing_fstat(source)):
                with self.assertRaisesRegex(OSError, "changed while its bytes"):
                    build._stable_regular_snapshot(source, "package source")

            source.write_bytes(b"stable source\n")
            with patch.object(atomic.os, "fstat",
                              side_effect=changing_fstat(source)):
                with self.assertRaisesRegex(OSError, "changed while it was read"):
                    atomic.regular_file_snapshot(source)

            note = root / "anchor.md"
            note.write_text(note_text, encoding="utf-8")
            with patch.object(index.os, "fstat",
                              side_effect=changing_fstat(note)):
                indexed = index.index_entry(note)
            self.assertTrue(any("changed while it was read" in error
                                for error in indexed["errors"]))

            note.write_text(note_text, encoding="utf-8")
            with patch.object(lint.os, "fstat",
                              side_effect=changing_fstat(note)):
                linted = lint.lint_file(note)
            self.assertTrue(any(finding["item"] == "0-unreadable"
                                for finding in linted["findings"]))

            moc = root / "MOC.md"
            moc.write_text(
                scan.MOC_TREE_START + "\n" + scan.MOC_TREE_END + "\n",
                encoding="utf-8")
            with patch.object(scan.os, "fstat",
                              side_effect=changing_fstat(moc)):
                self.assertEqual(
                    scan.moc_marker_state(moc)["state"], "unreadable")

            wiki = root / "Wiki"
            wiki.mkdir()
            wiki_note = wiki / "anchor.md"
            wiki_note.write_text(note_text, encoding="utf-8")
            with patch.object(scan.os, "fstat",
                              side_effect=changing_fstat(wiki_note)):
                scanned = scan.scan(wiki)
            self.assertTrue(any(problem["item"] == "item0"
                                for problem in scanned["problems"]))

    @unittest.skipUnless(CAN_CREATE_SYMLINK,
                         "host does not grant symlink privileges")
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
                                    capture_output=True, text=True,
                                    encoding="utf-8", timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symlink", result.stderr)
            self.assertEqual(
                foreign.read_text(encoding="utf-8"),
                "preserve external bytes")
            self.assertTrue((root / "obsidian.plugin").is_symlink())

    @unittest.skipUnless(CAN_CREATE_SYMLINK,
                         "host does not grant symlink privileges")
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

    def test_generated_publication_uses_a_bound_output_parent(self):
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

    @unittest.skipUnless(CAN_CREATE_SYMLINK,
                         "host does not grant symlink privileges")
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
            real_mkdtemp = build.tempfile.mkdtemp
            injected = {"done": False}

            def absolute_mkdtemp(*args, **kwargs):
                # Python 3.12+ always returns an absolute path. Simulate that
                # on the supported floor so this parent-rename cleanup stays
                # covered by every compatibility job.
                return os.path.abspath(real_mkdtemp(*args, **kwargs))

            def inject_parent(source, target):
                result = real_link(source, target)
                if (Path(target).name == output.name
                        and not injected["done"]):
                    injected["done"] = True
                    parent.rename(original_parent)
                    parent.symlink_to(foreign, target_is_directory=True)
                return result

            with patch.object(build.tempfile, "mkdtemp",
                              side_effect=absolute_mkdtemp), patch.object(
                                  build.atomic_move, "link_noreplace",
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

    def test_import_gate_covers_definition_time_and_arbitrary_methods(self):
        conventions = load("convention_import_gate", ROOT / "tests/test_conventions.py")
        unsafe = {
            "function default": "def f(value=run_now()):\n    return value\n",
            "function annotation": "def f(value: run_now()):\n    return value\n",
            "class body": "class C:\n    value = run_now()\n",
            "bare imported decorator":
                "from danger import mutate\n@mutate\ndef f():\n    pass\n",
            "bare imported base":
                "from danger import Base\nclass C(Base):\n    pass\n",
            "bare imported metaclass":
                "from danger import meta\nclass C(metaclass=meta):\n    pass\n",
            "method receiver": "value = imported.copy()\n",
            "subscript method receiver": "value = imported[0].copy()\n",
            "uppercase imported receiver":
                "import shutil as PAYLOAD\nvalue = PAYLOAD.copy('a', 'b')\n",
            "uppercase module alias":
                "import shutil\nPAYLOAD = shutil\n"
                "value = PAYLOAD.copy('a', 'b')\n",
            "trusted root imported from the wrong module":
                "from danger import re\nvalue = re.compile('x')\n",
            "walrus shadows qualified pure root":
                "(re := attacker)\nvalue = re.compile('x')\n",
            "walrus shadows pure builtin":
                "(sorted := attacker)\nvalue = sorted()\n",
        }
        for label, source in unsafe.items():
            with self.subTest(label=label):
                self.assertTrue(conventions.module_scope_effects(source))
        self.assertEqual(
            conventions.module_scope_effects(
                'VALUE = {"a": 1}.copy()\n'
                'TEXT = ",".join(("a", "b"))\n'
                'class LocalBase:\n    pass\n'
                'class LocalChild(LocalBase):\n    pass\n'
                'class Typed(metaclass=type):\n    pass\n'
                '@property\ndef value(self):\n    return 1\n'),
            [],
        )

        # Static refusal must happen before the probe imports the candidate.
        # Each spelling below used to return an empty effect list, so the child
        # process executed the callback with the repository as its cwd.
        with tempfile.TemporaryDirectory(prefix="obsidian-import-callback-") as tmp:
            directory = Path(tmp)
            callbacks = {
                "local_decorator": lambda sentinel: (
                    "def mutate(item):\n"
                    f"    open({str(sentinel)!r}, 'w').write('ran')\n"
                    "    return item\n"
                    "@mutate\n"
                    "def value():\n    return 1\n"),
                "shadowed_property": lambda sentinel: (
                    "def property(item):\n"
                    f"    open({str(sentinel)!r}, 'w').write('ran')\n"
                    "    return item\n"
                    "@property\n"
                    "def value():\n    return 1\n"),
                "local_base_callback": lambda sentinel: (
                    "class Base:\n"
                    "    def __init_subclass__(cls):\n"
                    f"        open({str(sentinel)!r}, 'w').write('ran')\n"
                    "class Child(Base):\n    pass\n"),
                "local_metaclass": lambda sentinel: (
                    "class Meta(type):\n"
                    "    def __new__(mcls, name, bases, namespace):\n"
                    f"        open({str(sentinel)!r}, 'w').write('ran')\n"
                    "        return type.__new__(mcls, name, bases, namespace)\n"
                    "class Child(metaclass=Meta):\n    pass\n"),
                "shadowed_pure_call": lambda sentinel: (
                    "def sorted():\n"
                    f"    open({str(sentinel)!r}, 'w').write('ran')\n"
                    "    return ()\n"
                    "VALUE = sorted()\n"),
                "walrus_shadowed_pure_call": lambda sentinel: (
                    "def attacker():\n"
                    f"    open({str(sentinel)!r}, 'w').write('ran')\n"
                    "    return ()\n"
                    "(sorted := attacker)\n"
                    "VALUE = sorted()\n"),
            }
            for label, source_for in callbacks.items():
                with self.subTest(local_callback=label):
                    sentinel = directory / (label + ".sentinel")
                    candidate = directory / (label + ".py")
                    candidate.write_text(source_for(sentinel), encoding="utf-8")
                    result = conventions.probe_module(str(candidate))
                    self.assertTrue(result["refused"], result)
                    self.assertFalse(sentinel.exists())

    def test_static_constant_reader_never_imports_the_target(self):
        conventions = load("convention_static_constants", ROOT / "tests/test_conventions.py")
        with tempfile.TemporaryDirectory(prefix="obsidian-static-constant-") as tmp:
            sentinel = Path(tmp) / "must-not-exist"
            source = Path(tmp) / "module.py"
            source.write_text(
                "from pathlib import Path\n"
                f"Path({str(sentinel)!r}).write_text('ran')\n"
                "GENERIC_HEADINGS = frozenset({'question', 'methods'})\n",
                encoding="utf-8",
            )
            namespace = conventions.mod_generic(str(source))
            self.assertEqual(
                namespace.GENERIC_HEADINGS, frozenset({"question", "methods"}))
            self.assertFalse(sentinel.exists())

    def test_documented_continuation_flags_are_checked(self):
        conventions = load("convention_continued_flags", ROOT / "tests/test_conventions.py")
        conv = (ROOT / "shared/CONVENTIONS.md").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory(prefix="obsidian-command-surface-") as tmp:
            script = Path(tmp) / "demo.py"
            script.write_text(
                "import argparse\n"
                "def main():\n"
                "    parser = argparse.ArgumentParser()\n"
                "    parser.add_argument('--real')\n",
                encoding="utf-8",
            )
            prose = "python3 scripts/demo.py " + "\\\n  --missing value\n"
            report = conventions.Report()
            with patch.object(conventions, "bundled_scripts", return_value=[str(script)]), \
                    patch.object(conventions, "walk_plugin_files",
                                 return_value=[(str(Path(tmp) / "guide.md"), prose)]):
                conventions.check_script_surface(report, conv)
            failures = report.by_status("FAIL")
            self.assertTrue(any("--missing" in row[3] for row in failures))

    def test_complete_yaml_examples_without_delimiters_are_still_checked(self):
        conventions = load(
            "convention_yaml_examples", ROOT / "tests/test_conventions.py")
        canonical = (ROOT / "shared/CONVENTIONS.md").read_text(
            encoding="utf-8")
        example = '''```yaml
title: "Fixture"
type: Concept
sources:
  - "[[Doe_Work_2025.pdf#page=1]]"
created: 2026-09-03
updated: 2026-09-03
description: "A fixture exercises semantic checking."
tags:
  - #statistics
parents: []
read: false
```
'''
        report = conventions.Report()
        with patch.object(
                conventions, "walk_skill_files",
                return_value=[("wiki-builder", "fixture.md", example)]):
            conventions.check_yaml_examples(report, canonical)
        failures = [row[3] for row in report.by_status("FAIL")
                    if row[0] == "yaml-example"]
        self.assertTrue(any("tags:" in message for message in failures),
                        failures)

    def test_reference_paths_require_exact_case(self):
        conventions = load("convention_reference_case", ROOT / "tests/test_conventions.py")
        exact = ROOT / "shared/CONVENTIONS.md"
        wrong = ROOT / "shared/conventions.md"
        self.assertTrue(conventions._exact_regular_file(str(exact)))
        self.assertFalse(conventions._exact_regular_file(str(wrong)))
        self.assertIsNotNone(
            conventions.PATH_REF.search("references/WrongCase.md"))

        report = conventions.Report()
        conv = (ROOT / "shared/CONVENTIONS.md").read_text(encoding="utf-8")
        with patch.object(
                conventions, "walk_plugin_files",
                return_value=[(str(ROOT / "README.md"),
                               "Consult `shared/MissingGuide.md`.\n")]):
            conventions.check_reference_paths(report, conv)
        self.assertTrue(any(
            "shared/MissingGuide.md" in row[3]
            for row in report.by_status("FAIL")))

    def test_heading_check_preserves_import_paths_and_reports_unreadable_rules(self):
        conventions = load("convention_headings", ROOT / "tests/test_conventions.py")
        before = list(sys.path)
        module = conventions.mod_generic(str(ROOT / "skills/paper-summarizer/scripts/note_lint.py"))
        self.assertIsNotNone(module)
        self.assertEqual(sys.path, before)
        report = conventions.Report()
        with patch.object(conventions, "mod_generic", return_value=None):
            conventions.check_note_headings(
                report,
                (ROOT / "shared/CONVENTIONS.md").read_text(encoding="utf-8"))
        self.assertEqual(report.exit_code(), 1)
        self.assertTrue(any("GENERIC_HEADINGS" in row[3] for row in report.by_status("FAIL")))

    def test_builder_and_linter_share_source_identity(self):
        builder = load(
            "compat_builder_source_identity",
            ROOT / "skills/wiki-builder/scripts/lint_entry.py")
        linter = load(
            "compat_linter_source_identity",
            ROOT / "skills/wiki-linter/scripts/scan_vault.py")
        cases = (
            "stub",
            "[[Doe_Study_2025.pdf#page=7]]",
            "[[Sources/PDFs/Doe_Study_2025.pdf#page=7|page 7]]",
            "[[Cafe\u0301.md]]",
            "[[CAFÉ.MD]]",
            "malformed-without-extension",
        )
        for item in cases:
            with self.subTest(item=item):
                self.assertEqual(builder.source_stem(item),
                                 linter.source_stem(item))

    def test_heading_contract_requires_its_reference_and_ordered_examples(self):
        conventions = load("convention_heading_contract", ROOT / "tests/test_conventions.py")
        format_path = ROOT / "skills/paper-summarizer/references/note-format.md"
        conv = (ROOT / "shared/CONVENTIONS.md").read_text(encoding="utf-8")
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

        original = format_path.read_text(encoding="utf-8")
        changed = original.replace("MAX_STEPS=8", "MAX_STEPS=9")
        self.assertNotEqual(changed, original)
        report = conventions.Report()
        with patch.object(
                conventions, "read",
                side_effect=lambda path: changed
                if Path(path) == format_path else read(path)):
            conventions.check_note_headings(report, conv)
        self.assertEqual(report.exit_code(), 1)
        self.assertTrue(any("numeric limits" in row[3]
                            for row in report.by_status("FAIL")))

    def test_figure_caption_checks_follow_the_writers_scope(self):
        conventions = load("convention_caption_scope", ROOT / "tests/test_conventions.py")
        conv = (ROOT / "shared/CONVENTIONS.md").read_text(encoding="utf-8")
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

    def test_figure_helper_help_works_before_dependencies_are_installed(self):
        scripts = ROOT / "skills/pdf-figure-extractor/scripts"
        invocations = {
            "auto_fig_bbox.py": ["missing.pdf"],
            "batch_extract.py": ["--src", "missing.pdf", "--out", "images"],
            "extract_figures.py": ["missing.pdf", "--out", "images",
                                   "--stem", "missing", "--crop",
                                   "1:1:0,0,10,10"],
            "render_page.py": ["missing.pdf", "1"],
        }
        for name, invocation in invocations.items():
            with self.subTest(script=name):
                result = subprocess.run(
                    [sys.executable, "-I", "-S", str(scripts / name), "--help"],
                    cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                    timeout=30)
                self.assertEqual(result.returncode, 0,
                                 result.stdout + result.stderr)
                self.assertIn("usage:", result.stdout)
                self.assertNotIn("PyMuPDF required", result.stderr)
                blocked = subprocess.run(
                    [sys.executable, "-I", "-S", str(scripts / name),
                     *invocation], cwd=ROOT, capture_output=True, text=True,
                    encoding="utf-8", timeout=30)
                self.assertNotEqual(blocked.returncode, 0)
                self.assertIn("PyMuPDF required", blocked.stderr)
                self.assertNotIn("Traceback", blocked.stderr)

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
                        capture_output=True, text=True, encoding="utf-8",
                        timeout=30)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            # Both instruction and shared-resource references survive copying.
            imported = (install / "CLAUDE.md").read_text(
                encoding="utf-8").strip().removeprefix("@")
            self.assertEqual((install / imported).read_bytes(), (ROOT / "AGENTS.md").read_bytes())
            check = [sys.executable, str(install / "tools/build_plugin.py"), "--check"]
            clean_env = dict(os.environ)
            clean_env.pop("OBSIDIAN_VAULT_SHARED", None)
            # A source checkout need not already contain the generated Codex
            # directory. `--check` stays write-free; the build creates it.
            shutil.rmtree(install / ".codex-plugin")
            missing = subprocess.run(
                check, cwd=vault, capture_output=True, env=clean_env)
            self.assertEqual(missing.returncode, 1)
            self.assertFalse((install / ".codex-plugin").exists())
            # The archive does not contain itself: build it in the isolated copy.
            subprocess.run(
                check[:-1], cwd=vault, check=True, capture_output=True,
                env=clean_env)
            self.assertTrue((install / ".codex-plugin/plugin.json").is_file())
            self.assertEqual(subprocess.run(
                check, cwd=vault, capture_output=True,
                env=clean_env).returncode, 0)
            with (install / "shared/RUNTIME.md").open(
                    "a", encoding="utf-8") as output:
                output.write("\nChanged after packaging.\n")
            self.assertNotEqual(subprocess.run(
                check, cwd=vault, capture_output=True,
                env=clean_env).returncode, 0)

    def test_unicode_cli_output_survives_a_narrow_redirected_stream(self):
        """Public CLIs must not fail after work under a narrow encoding."""
        import pymupdf

        with tempfile.TemporaryDirectory(prefix="obsidian-unicode-stdio-") as tmp:
            root = Path(tmp)
            pdf = root / "图.pdf"
            notes = root / "Articles"
            images = root / "Images"
            pdfs = root / "PDFs"
            crops = root / "Crops"
            for path in (notes, images, pdfs, crops):
                path.mkdir()
            with pymupdf.open() as document:
                page = document.new_page(width=400, height=400)
                page.insert_text((72, 50), "Study 图", fontname="china-s")
                page.draw_rect((100, 100, 250, 220),
                               color=(0, 0, 0), fill=(0.2, 0.5, 0.8))
                page.insert_text((100, 250), "Figure 1. Sample")
                document.save(pdf)
            (pdfs / pdf.name).write_bytes(pdf.read_bytes())
            note = notes / "图.md"
            note.write_text("not a valid note\n", encoding="utf-8")

            env = dict(os.environ)
            env.update({
                "PYTHONIOENCODING": "ascii:strict",
                "PYTHONDONTWRITEBYTECODE": "1",
                "OBSIDIAN_VAULT_SHARED": str(ROOT / "shared/scripts"),
            })
            commands = (
                ("plurals", 0, ROOT / "shared/scripts/plurals.py",
                 "singular", "图"),
                ("note lint", 1,
                 ROOT / "skills/paper-summarizer/scripts/note_lint.py",
                 note, "--mode", "empirical"),
                ("paper scan", 0,
                 ROOT / "skills/paper-summarizer/scripts/paper_scan.py",
                 "--src", pdfs, "--notes", notes, "--images", images,
                 "--allow-unorganized"),
                ("paper text", 0,
                 ROOT / "skills/paper-summarizer/scripts/paper_text.py",
                 pdf, "--pages"),
                ("automatic crop", 0,
                 ROOT / "skills/pdf-figure-extractor/scripts/auto_fig_bbox.py",
                 pdf, "--pages", "1", "--emit", "extract"),
                ("explicit crop", 0,
                 ROOT / "skills/pdf-figure-extractor/scripts/extract_figures.py",
                 pdf, "--out", crops, "--stem", pdf.stem,
                 "--crop", "1:1:50,50,300,300", "--dpi", "72",
                 "--no-caption-check"),
            )
            for label, expected, script, *arguments in commands:
                with self.subTest(command=label):
                    result = subprocess.run(
                        [sys.executable, str(script), *map(str, arguments)],
                        env=env, capture_output=True, timeout=30)
                    output = result.stdout + result.stderr
                    self.assertEqual(result.returncode, expected,
                                     output.decode("utf-8", "replace"))
                    output.decode("utf-8")
                    self.assertIn("图".encode("utf-8"), output)
                    self.assertNotIn(b"UnicodeEncodeError", output)

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
            with tempfile.TemporaryDirectory(
                    prefix="obsidian-generated-command-") as tmp:
                base = Path(tmp)
                interpreter = str(base / "python environment" / "python3")
                source = str(base / "vault's PDFs")
                output = str(base / "images $literal")
                with patch.object(batch.sys, "executable", interpreter):
                    command = batch.mark_reviewed_command(
                        source, output, "Doe_Paper_2026", "1")
                self.assertEqual(shlex.split(command), [
                    interpreter, str(scripts / "batch_extract.py"),
                    "--src", source, "--out", output,
                    "--mark-reviewed", "Doe_Paper_2026:1",
                ])
        finally:
            sys.path.remove(str(scripts))


if __name__ == "__main__":
    unittest.main()
