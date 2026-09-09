#!/usr/bin/env python3
"""Checks for installation layout and supported-platform execution."""

import ast
import hashlib
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
from urllib.parse import unquote, urlsplit
import zipfile

import yaml


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SKILLS = {
    "knowledge": {
        "clipping-clean", "paper-summarize", "figure-extract", "pdf-organize",
        "wiki-add", "wiki-build", "wiki-lint",
    },
    "investments": {"stock-research", "feed-collect"},
}


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
    for name in PLUGIN_SKILLS:
        authored = destination / "plugins" / name / ".claude-plugin"
        authored.mkdir(parents=True)
        shutil.copy2(ROOT / "plugins" / name / ".claude-plugin/plugin.json",
                     authored / "plugin.json")
        shutil.copy2(ROOT / "plugins" / name / "README.md",
                     authored.parent / "README.md")
        requirements = ROOT / "plugins" / name / "requirements.txt"
        if name == "investments":
            shutil.copy2(requirements, authored.parent / "requirements.txt")


class CompatibilityTests(unittest.TestCase):
    def test_readme_roster_counts_use_their_own_package_scope(self):
        conventions = load("convention_roster_counts", ROOT / "tests/test_conventions.py")
        canonical = (ROOT / "shared/CONVENTIONS.md").read_text(encoding="utf-8")
        for relative, intro, fails in (
                ("README.md", "Nine skills are packaged as two plugins.", False),
                ("plugins/knowledge/README.md", "Seven skills for organizing sources.", False),
                ("plugins/knowledge/README.md", "Eight skills for organizing sources.", True),
                ("plugins/investments/README.md", "Two skills for collection and market research.", False),
                ("plugins/investments/README.md", "One skill for market research.", True)):
            with self.subTest(relative=relative, intro=intro):
                report = conventions.Report()
                prose = "# Overview\n\n" + intro + "\n\nUse the `wiki-build` skill.\n"
                with patch.object(conventions, "walk_plugin_files", return_value=[
                        (str(ROOT / relative), prose)]):
                    conventions.check_skill_roster(report, canonical)
                self.assertEqual(bool(report.by_status("FAIL")), fails, report.render())
        self.assertEqual(conventions.stated_roster_counts(
            "README.md", "# Overview\n\nOrganize a vault.\n\nFour skills for PDFs help here."), [])
        self.assertEqual(conventions.stated_roster_counts(
            "SKILL.md", "Four skills for PDFs help here."), [])

    def test_convention_defects_and_broken_checks_fail_the_run(self):
        conventions = load("convention_failures", ROOT / "tests/test_conventions.py")
        conv = (ROOT / "shared/CONVENTIONS.md").read_text(encoding="utf-8")
        for check, prose, expected in (
                (conventions.check_reference_paths,
                 "Consult `shared/MissingGuide.md`.\n", "MissingGuide.md"),
                (conventions.check_skill_roster,
                 "Use the `missing-producer` skill.\n", "missing-producer")):
            with self.subTest(check=check.__name__):
                report = conventions.Report()
                with patch.object(conventions, "walk_plugin_files", return_value=[
                        (str(ROOT / "README.md"), prose)]):
                    check(report, conv)
                self.assertEqual(report.exit_code(), 1)
                self.assertTrue(any(expected in row[3]
                                    for row in report.by_status("FAIL")))
                self.assertIn("RESULT: FAIL", report.render())

        # A marketplace's compound name cannot serve as its own evidence
        # that the prose is naming a skill (the suffix alone used to do so).
        self.assertEqual(conventions._roster_candidates(
            "The marketplace remains `obsidian-skills`.\n",
            set(conventions.skill_names()), set()), [])

        def no_results(report, canonical):
            pass

        def empty_population(report, canonical):
            report.ok("fixture", "discovery ran")
            report.saw("fixture", "inputs", 0)

        def crashes(report, canonical):
            raise ValueError("fixture failure")

        for check, expected in ((no_results, "NO results"),
                                (empty_population, "VACUOUS"),
                                (crashes, "CRASHED")):
            with self.subTest(check=check.__name__):
                output = io.StringIO()
                with patch.object(conventions, "CHECKS", [check]), \
                        patch.object(sys, "stdout", output):
                    code = conventions.main(["--json"])
                result = json.loads(output.getvalue())
                self.assertEqual(code, 1)
                self.assertFalse(result["ok"])
                self.assertTrue(any(expected in row["message"]
                                    for row in result["results"]))

    def test_moc_placement_checks_instructions_not_selftest_fixtures(self):
        conventions = load("convention_moc_fixtures", ROOT / "tests/test_conventions.py")
        conv = (ROOT / "shared/CONVENTIONS.md").read_text(encoding="utf-8")
        cases = (
            ("fixture.py", 'def run_self_test():\n    path = "Wiki/test-moc.md"\n', False),
            ("fixture.py", 'def write_moc():\n    path = "Wiki/test-moc.md"\n', True),
            ("fixture.md", 'Write the MOC to `Wiki/test-moc.md`.\n', True),
        )
        for path, text, should_fail in cases:
            with self.subTest(path=path, text=text):
                report = conventions.Report()
                with patch.object(conventions, "walk_skill_files", return_value=[
                        ("wiki-lint", path, text),
                        ("wiki-lint", "valid.md", "MOCs/<discipline>.md")]):
                    conventions.check_moc_placement(report, conv)
                self.assertEqual(bool(report.by_status("FAIL")), should_fail)

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
            ROOT / "skills/figure-extract/scripts/requirements.txt"
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

    def test_manifests_share_metadata_and_each_plugin_owns_its_skill_tree(self):
        seen = set()
        for name, expected_skills in PLUGIN_SKILLS.items():
            with self.subTest(plugin=name):
                root = ROOT / "plugins" / name
                claude = json.loads(
                    (root / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
                codex = json.loads(
                    (root / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
                self.assertEqual(claude["name"], name)
                for key, value in claude.items():
                    self.assertEqual(codex[key], value, key)
                claude_skills = root / claude.get("skills", "skills")
                codex_skills = root / codex["skills"]
                self.assertEqual(claude_skills.resolve(), codex_skills.resolve())
                skills = sorted(claude_skills.glob("*/SKILL.md"))
                roster = {path.parent.name for path in skills}
                self.assertEqual(roster, expected_skills)
                self.assertFalse(seen & roster)
                seen.update(roster)
                for path in skills:
                    self.assertTrue(
                        (path.parent / "../../shared/RUNTIME.md").resolve().is_file())
        self.assertEqual(seen, {
            path.parent.name for path in (ROOT / "skills").glob("*/SKILL.md")})
        for retired in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json",
                        "obsidian.plugin"):
            self.assertFalse(os.path.lexists(ROOT / retired), retired)

    def test_marketplace_metadata_identifies_both_authored_plugins(self):
        marketplace = json.loads(
            (ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
        self.assertEqual(marketplace["name"], "obsidian-skills")
        self.assertIsInstance(marketplace["description"], str)
        self.assertTrue(marketplace["description"].strip())
        self.assertEqual(len(marketplace["plugins"]), len(PLUGIN_SKILLS))
        entries = {entry["name"]: entry for entry in marketplace["plugins"]}
        self.assertEqual(set(entries), set(PLUGIN_SKILLS))
        for name, entry in entries.items():
            with self.subTest(plugin=name):
                manifest = json.loads((ROOT / "plugins" / name /
                    ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
                self.assertEqual(marketplace["owner"], manifest["author"])
                self.assertEqual(entry["name"], manifest["name"])
                self.assertEqual(entry["source"], "./plugins/" + name)
                self.assertEqual(entry["description"], manifest["description"])

    def test_archives_and_distribution_trees_are_complete_and_current(self):
        build = load("build_plugin", ROOT / "tools/build_plugin.py")
        for plugin_name, roster in PLUGIN_SKILLS.items():
            with self.subTest(plugin=plugin_name):
                expected = build.package_files(ROOT, plugin_name)
                content = (ROOT / (plugin_name + ".plugin")).read_bytes()
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
                        self.assertEqual(
                            (ROOT / "plugins" / plugin_name / name).read_bytes(),
                            data, name)
                self.assertEqual(content, build.archive_bytes(expected))
                distribution = ROOT / "plugins" / plugin_name
                actual = set()
                for path in distribution.rglob("*"):
                    self.assertFalse(path.is_symlink(), str(path))
                    if (path.is_file() and "__pycache__" not in path.parts
                            and path.name != ".DS_Store"
                            and path.suffix not in (".pyc", ".pyo")):
                        actual.add(path.relative_to(distribution).as_posix())
                self.assertEqual(actual, set(expected))
                self.assertEqual({
                    Path(name).parts[1] for name in expected
                    if name.startswith("skills/")}, roster)
                self.assertFalse(any(
                    name.startswith(("tools/", "tests/", "plugins/"))
                    for name in expected))

    def test_packaged_market_cli_uses_private_credentials_without_local_launchers(self):
        with tempfile.TemporaryDirectory(prefix="obsidian-market-config-") as tmp:
            root = Path(tmp).resolve()
            install = root / "installed plugin"
            with zipfile.ZipFile(ROOT / "investments.plugin") as archive:
                archive.extractall(install)
            private = root / "private config"
            private.mkdir(mode=0o700)
            config = private / "researcher's credentials.json"
            fixtures = {
                "ALPACA_API_KEY": "synthetic-alpaca-id",
                "ALPACA_SECRET_KEY": "synthetic-alpaca-secret",
                "ALPHA_VANTAGE_API_KEY": "synthetic-alpha-key",
                "SEC_USER_AGENT": "Synthetic Research test@example.invalid",
                "FRED_API_KEY": "a" * 32,
            }
            config.write_text(json.dumps(fixtures), encoding="utf-8")
            config.chmod(0o600)
            before = config.read_bytes()
            script = install / "skills/stock-research/scripts/market_data.py"
            env = {key: value for key, value in os.environ.items() if key not in fixtures}
            env.pop('OBSIDIAN_VAULT_SHARED', None)

            def invoke(*args):
                return subprocess.run(
                    [sys.executable, "-I", "-S", "-B", str(script), *map(str, args)],
                    cwd=root, env=env, capture_output=True, text=True,
                    encoding="utf-8", timeout=30)

            result = invoke("check", "--credentials-file", config)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            data = json.loads(result.stdout)
            self.assertTrue(data["complete"])
            self.assertTrue(all(row["configured"] for row in data["data"]))
            self.assertEqual(data["requests"], [])
            for secret in fixtures.values():
                self.assertNotIn(secret, result.stdout + result.stderr)
            self.assertEqual(config.read_bytes(), before)

            # The optional parser must not make core research depend on site
            # packages; missing it fails before any SEC network request.
            self.assertFalse(data["optional_dependencies"]["sec_filing_parser"]["available"])
            filing = invoke("sec-filing", "--cik", "320193", "--accession",
                            "0000320193-23-000106", "--as-of", "2026-09-04T15:30:00Z",
                            "--credentials-file", config)
            self.assertEqual(filing.returncode, 2, filing.stdout + filing.stderr)
            unavailable = json.loads(filing.stdout)
            self.assertEqual(unavailable["requests"], [])
            self.assertIn("parser", unavailable["error"]["message"].lower())

            screen = install / "skills/stock-research/scripts/market_screen.py"
            screen_help = subprocess.run(
                [sys.executable, "-I", "-S", "-B", str(screen), "--help"],
                cwd=root, env=env, capture_output=True, text=True,
                encoding="utf-8", timeout=30)
            self.assertEqual(screen_help.returncode, 0, screen_help.stderr)

            for helper in ('market_estimates.py', 'market_ownership.py', 'market_capitalization.py',
                           'market_estimate_history.py', 'market_price_capture.py', 'market_comparison.py',
                           'stock_coverage.py'):
                isolated = subprocess.run(
                    [sys.executable, '-I', '-S', '-B', str(script.parent / helper), '--test'],
                    cwd=root, env=env, capture_output=True, text=True, encoding='utf-8', timeout=60)
                self.assertEqual(isolated.returncode, 0, helper + ': ' + isolated.stdout + isolated.stderr)

            # A selected partial file cannot silently pick up an unrelated
            # account from the process environment, including in an installed copy.
            config.write_text(json.dumps({"FRED_API_KEY": fixtures["FRED_API_KEY"]}),
                              encoding="utf-8")
            env.update({key: value for key, value in fixtures.items() if key != "FRED_API_KEY"})
            partial = invoke("check", "--credentials-file", config)
            self.assertEqual(partial.returncode, 2, partial.stdout + partial.stderr)
            rows = {row["source"]: row for row in json.loads(partial.stdout)["data"]}
            self.assertTrue(rows["fred"]["configured"])
            self.assertFalse(rows["alpaca"]["configured"])
            self.assertFalse(rows["sec"]["configured"])
            self.assertFalse(rows["alpha_vantage"]["configured"])

            help_result = invoke("check", "--credentials-file", private / "missing.json", "--help")
            self.assertEqual(help_result.returncode, 0, help_result.stdout + help_result.stderr)
            self.assertIn("--credentials-file", help_result.stdout)

    def test_packaged_feed_collector_runs_without_repository_or_site_packages(self):
        with tempfile.TemporaryDirectory(prefix="obsidian-feed-package-") as tmp:
            root = Path(tmp).resolve()
            install = root / "installed plugin"
            with zipfile.ZipFile(ROOT / "investments.plugin") as archive:
                archive.extractall(install)
            env = {key: value for key, value in os.environ.items()
                   if key not in {"OBSIDIAN_VAULT_SHARED", "X_BEARER_TOKEN"}}
            for name in ("feed_collect.py", "rss_collect.py", "rss_source.py"):
                script = install / "skills/feed-collect/scripts" / name
                for option in ("--help", "--test"):
                    with self.subTest(script=name, option=option):
                        result = subprocess.run(
                            [sys.executable, "-I", "-S", "-B", str(script), option],
                            cwd=root, env=env, capture_output=True, text=True,
                            encoding="utf-8", timeout=60)
                        self.assertEqual(result.returncode, 0,
                                         result.stdout + result.stderr)
                        if option == "--help" and name == "feed_collect.py":
                            self.assertIn("collect", result.stdout)
                            self.assertIn("reconcile", result.stdout)

    def test_packaging_derives_the_loose_and_archived_codex_manifest_once(self):
        build = load("build_plugin_single_manifest", ROOT / "tools/build_plugin.py")
        derived = b"one exact derived manifest\n"
        for name in PLUGIN_SKILLS:
            with self.subTest(plugin=name), patch.object(
                    build, "_codex_manifest_bytes", return_value=derived) as convert:
                files = build.package_files(ROOT, name)
            convert.assert_called_once_with(files[".claude-plugin/plugin.json"])
            self.assertEqual(files[".codex-plugin/plugin.json"], derived)

    def test_provenance_fingerprints_every_distributed_file_except_itself(self):
        build = load("build_plugin_provenance_inventory", ROOT / "tools/build_plugin.py")
        with tempfile.TemporaryDirectory(prefix="plugin-provenance-no-git-") as tmp:
            root = Path(tmp) / "source"
            copy_package_source(root)
            for name in PLUGIN_SKILLS:
                with self.subTest(plugin=name):
                    files = build.package_files(root, name)
                    provenance = json.loads(files["provenance.json"])
                    hashes = {
                        path: hashlib.sha256(data).hexdigest()
                        for path, data in files.items() if path != "provenance.json"}
                    self.assertEqual(provenance["schema"], 1)
                    self.assertEqual(provenance["plugin"], name)
                    self.assertEqual(provenance["plugin_version"], json.loads(
                        files[".claude-plugin/plugin.json"])["version"])
                    self.assertEqual(provenance["files"], hashes)
                    self.assertEqual(provenance["runtime_sha256"], hashlib.sha256(
                        json.dumps(hashes, sort_keys=True, separators=(",", ":"))
                        .encode("utf-8")).hexdigest())
                    self.assertEqual(provenance["source_status"], "unavailable")
                    self.assertIsNone(provenance["source_commit"])
                    self.assertIsNone(provenance["source_url"])
                    self.assertEqual(files, build.package_files(root, name))

    @unittest.skipUnless(shutil.which("git"), "Git is required for source identity checks")
    def test_provenance_tracks_canonical_commits_without_release_self_reference(self):
        build = load("build_plugin_provenance_git", ROOT / "tools/build_plugin.py")
        with tempfile.TemporaryDirectory(prefix="plugin-provenance-git-") as tmp:
            root = Path(tmp) / "source"
            copy_package_source(root)
            environment = {key: value for key, value in os.environ.items()
                           if not key.startswith("GIT_")}
            environment.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")

            def git(*args):
                completed = subprocess.run(
                    ["git", "-c", "user.name=Provenance Test", "-c",
                     "user.email=test@example.invalid", "-c", "commit.gpgsign=false",
                     "-c", "core.hooksPath=" + os.devnull, "-C", str(root), *args],
                    env=environment, capture_output=True, check=True)
                return completed.stdout.decode("utf-8").strip()

            def commit(message):
                git("add", "--all")
                git("commit", "-m", message)
                return git("rev-parse", "HEAD")

            def metadata(name):
                return json.loads(build.package_files(root, name)["provenance.json"])

            git("init")
            first = commit("Canonical source snapshot")
            initial = {name: metadata(name) for name in PLUGIN_SKILLS}
            for row in initial.values():
                self.assertEqual(row["source_status"], "committed")
                self.assertEqual(row["source_commit"], first)
                self.assertEqual(row["source_url"], row["repository"] + "/commit/" + first)

            for path, data in build.generated_outputs(root).items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            generated = commit("Generated distributions")
            self.assertNotEqual(first, generated)
            self.assertEqual({name: metadata(name) for name in PLUGIN_SKILLS}, initial)

            investment_skill = root / "skills/stock-research/SKILL.md"
            original_investment = investment_skill.read_bytes()
            investment_skill.write_bytes(original_investment + b"\nInvestment change.\n")
            investment_commit = commit("Investment source update")
            investment = metadata("investments")
            self.assertEqual(investment["source_commit"], investment_commit)
            self.assertEqual(metadata("knowledge"), initial["knowledge"])

            # Another plugin's new mapped input must not move this one's identity.
            asset = root / "skills/wiki-build/assets/provenance-test.txt"
            asset.parent.mkdir(parents=True)
            asset.write_bytes(b"New knowledge input.\n")
            map_path = root / build.PACKAGE_INVENTORY
            mapping = json.loads(map_path.read_bytes())
            relative = asset.relative_to(root).as_posix()
            mapping["knowledge"][relative] = relative
            map_path.write_text(json.dumps(mapping, indent=2) + "\n", encoding="utf-8")
            knowledge_commit = commit("Knowledge asset and map update")
            self.assertEqual(metadata("knowledge")["source_commit"], knowledge_commit)
            self.assertEqual(metadata("investments"), investment)

            # A map-only change still needs the commit containing the actual map.
            mapping["knowledge"]["requirements.txt"] = "plugins/knowledge/requirements.txt"
            map_path.write_text(json.dumps(mapping, indent=2) + "\n", encoding="utf-8")
            map_commit = commit("Knowledge-only mapping update")
            knowledge = metadata("knowledge")
            self.assertEqual(knowledge["source_commit"], map_commit)
            self.assertEqual(metadata("investments"), investment)

            # A merge can be the first snapshot containing both a source edit
            # and a map-only edit. Looking at either path set alone omits it.
            git("checkout", "-b", "provenance-map-only")
            mapping["knowledge"]["requirements.txt"] = "requirements.txt"
            map_path.write_text(json.dumps(mapping, indent=2) + "\n", encoding="utf-8")
            commit("Mapping change on one branch")
            git("checkout", "-b", "provenance-source-only", map_commit)
            knowledge_skill = root / "skills/wiki-build/SKILL.md"
            knowledge_skill.write_bytes(knowledge_skill.read_bytes() + b"\nSeparate branch edit.\n")
            commit("Source change on another branch")
            git("merge", "--no-ff", "provenance-map-only", "-m", "Combine source and map")
            merged = git("rev-parse", "HEAD")
            knowledge = metadata("knowledge")
            self.assertEqual(knowledge["source_status"], "committed")
            self.assertEqual(knowledge["source_commit"], merged)
            (root / "generated-test-output.txt").write_text("Derived output.\n", encoding="utf-8")
            commit("Generated-only output after merge")
            self.assertEqual(metadata("knowledge"), knowledge)
            self.assertEqual(metadata("investments"), investment)

            investment_skill.write_bytes(investment_skill.read_bytes() + b"\nUncommitted change.\n")
            dirty = metadata("investments")
            self.assertEqual(dirty["source_status"], "uncommitted")
            self.assertIsNone(dirty["source_commit"])
            self.assertIsNone(dirty["source_url"])
            self.assertNotEqual(dirty["runtime_sha256"], investment["runtime_sha256"])
            self.assertEqual(metadata("knowledge"), knowledge)
            investment_skill.write_bytes(original_investment)
            self.assertEqual(metadata("investments")["source_status"], "uncommitted")

            helper = root / "tools/build_plugin.py"
            helper.write_bytes(helper.read_bytes() + b"\n# Uncommitted build helper.\n")
            self.assertEqual(metadata("knowledge")["source_status"], "uncommitted")

            # A shallow boundary must not be mistaken for the source's first commit.
            shallow = Path(tmp) / "shallow"
            subprocess.run(["git", "clone", "--depth=1", root.as_uri(), str(shallow)],
                           env=environment, capture_output=True, check=True)
            shallow_metadata = json.loads(
                build.package_files(shallow, "investments")["provenance.json"])
            self.assertEqual(shallow_metadata["source_status"], "unavailable")
            self.assertIsNone(shallow_metadata["source_commit"])

    def test_changing_one_plugins_skill_does_not_change_its_siblings_archive(self):
        build = load("build_plugin_profile_isolation", ROOT / "tools/build_plugin.py")
        with tempfile.TemporaryDirectory(prefix="independent-profile-bytes-") as tmp:
            root = Path(tmp) / "source"
            copy_package_source(root)
            for name, skills in PLUGIN_SKILLS.items():
                with self.subTest(plugin=name):
                    before = {
                        plugin: build.archive_bytes(build.package_files(root, plugin))
                        for plugin in PLUGIN_SKILLS}
                    changed = root / "skills" / sorted(skills)[0] / "SKILL.md"
                    with changed.open("a", encoding="utf-8") as output:
                        output.write("\nProfile-specific runtime update.\n")
                    after = {
                        plugin: build.archive_bytes(build.package_files(root, plugin))
                        for plugin in PLUGIN_SKILLS}
                    for plugin in PLUGIN_SKILLS:
                        if plugin == name:
                            self.assertNotEqual(before[plugin], after[plugin])
                        else:
                            self.assertEqual(before[plugin], after[plugin])

    def test_build_preserves_authored_edits_and_rolls_back_generated_publications(self):
        build = load("build_plugin_authored_races", ROOT / "tools/build_plugin.py")
        for phase in ("after collection", "during publication"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory(
                    prefix="plugin-authored-race-") as tmp:
                root = Path(tmp).resolve() / "source"
                copy_package_source(root)
                initial_sources = {}
                initial = build.generated_outputs(root, snapshots=initial_sources)
                for path in initial:
                    if not path.parent.exists():
                        build._create_output_parent(root, path.parent)
                parents = {path: build._directory_identity(path.parent) for path in initial}
                observed = {path: build._observe_output(path) for path in initial}
                build._publish_outputs(root, initial, observed, parents,
                    validate_inputs=lambda: build._verify_sources(root, initial_sources))

                # A real runtime change makes this publication nontrivial.
                changed = root / "skills/wiki-build/SKILL.md"
                with changed.open("a", encoding="utf-8") as output:
                    output.write("\nPlanned runtime change.\n")
                sources = {}
                outputs = build.generated_outputs(root, snapshots=sources)
                inventory = json.loads((root / build.PACKAGE_INVENTORY).read_text(
                    encoding="utf-8"))
                for name, mapping in inventory.items():
                    for destination, origin in mapping.items():
                        authored_output = root / "plugins" / name / destination
                        if authored_output == root / origin:
                            self.assertNotIn(authored_output, outputs)
                observed = {path: build._observe_output(path) for path in outputs}
                self.assertTrue(any(observed[path][4] != data
                                    for path, data in outputs.items()))
                authored = root / "plugins/knowledge/README.md"
                saved = authored.read_bytes() + b"\nConcurrent authored README edit.\n"
                injected = {"done": False}
                publish = build._publish_generated

                def publish_then_edit(*args, **kwargs):
                    result = publish(*args, **kwargs)
                    if not injected["done"]:
                        authored.write_bytes(saved)
                        injected["done"] = True
                    return result

                if phase == "after collection":
                    authored.write_bytes(saved)
                with patch.object(build, "_publish_generated",
                        side_effect=publish_then_edit if phase == "during publication"
                        else publish):
                    with self.assertRaisesRegex(OSError, "package source changed"):
                        build._publish_outputs(root, outputs, observed, parents,
                            validate_inputs=lambda: build._verify_sources(root, sources))
                if phase == "during publication":
                    self.assertTrue(injected["done"])
                self.assertEqual(authored.read_bytes(), saved)
                for path, previous in observed.items():
                    self.assertEqual(path.read_bytes(), previous[4], str(path))
                self.assertFalse(any(root.rglob(".plugin-build-*")))

    def test_build_rejects_shared_sources_changed_between_profiles(self):
        build = load("build_plugin_cross_profile_race", ROOT / "tools/build_plugin.py")
        with tempfile.TemporaryDirectory(prefix="plugin-cross-profile-race-") as tmp:
            root = Path(tmp).resolve() / "source"
            copy_package_source(root)
            common = root / "shared/RUNTIME.md"
            saved = common.read_bytes() + b"\nChanged between profile snapshots.\n"
            collect = build.package_files
            collected = []

            def change_shared_after_first_profile(*args, **kwargs):
                result = collect(*args, **kwargs)
                collected.append(args[1])
                if len(collected) == 1:
                    common.write_bytes(saved)
                return result

            with patch.object(build, "package_files",
                              side_effect=change_shared_after_first_profile):
                with self.assertRaisesRegex(OSError, "package source changed"):
                    build.generated_outputs(root)
            self.assertEqual(len(collected), 1)
            self.assertEqual(common.read_bytes(), saved)
            for name in PLUGIN_SKILLS:
                self.assertFalse((root / (name + ".plugin")).exists())
                self.assertFalse((root / "plugins" / name / "skills").exists())

    def test_package_inventory_includes_declared_assets_and_rejects_unknown_files(self):
        build = load("build_plugin_inventory", ROOT / "tools/build_plugin.py")
        with tempfile.TemporaryDirectory(prefix="obsidian-package-inventory-") as tmp:
            root = Path(tmp) / "plugin"
            copy_package_source(root)
            asset = root / "skills/wiki-build/assets/diagram.svg"
            asset.parent.mkdir(parents=True)
            asset.write_bytes(b"<svg/>\n")
            with self.assertRaisesRegex(ValueError, "unlisted files"):
                build.package_files(root, "knowledge")

            inventory = root / build.PACKAGE_INVENTORY
            profiles = json.loads(inventory.read_text(encoding="utf-8"))
            relative = asset.relative_to(root).as_posix()
            profiles["knowledge"][relative] = relative
            inventory.write_text(
                json.dumps(profiles, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            packaged = build.package_files(root, "knowledge")
            self.assertEqual(packaged["skills/wiki-build/assets/diagram.svg"],
                             b"<svg/>\n")

            (root / "skills/.DS_Store").write_bytes(b"finder metadata")
            cache = root / "skills/wiki-build/__pycache__"
            cache.mkdir()
            (cache / "helper.pyc").write_bytes(b"bytecode")
            self.assertEqual(build.package_files(root, "knowledge")[
                "skills/wiki-build/assets/diagram.svg"], b"<svg/>\n")

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
            for name in ("skills/linked.md", "plugins/knowledge/README.md",
                         "plugins/knowledge/.claude-plugin/plugin.json", "shared"):
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
                            build.package_files(root, "knowledge")
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
            victim = root / "plugins/knowledge/README.md"
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
                    build.package_files(root, "knowledge")
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
                    build.package_files(root, "knowledge")

    def test_stable_readers_reject_same_file_changes_during_read(self):
        build = load("build_plugin_changed_read", ROOT / "tools/build_plugin.py")
        atomic = load("atomic_move_changed_read", ROOT / "shared/scripts/atomic_move.py")
        index = load(
            "vault_index_changed_read",
            ROOT / "skills/wiki-build/scripts/vault_index.py")
        lint = load(
            "lint_entry_changed_read",
            ROOT / "skills/wiki-build/scripts/lint_entry.py")
        scan = load(
            "scan_vault_changed_read",
            ROOT / "skills/wiki-lint/scripts/scan_vault.py")

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
            moc.write_text("- [[Wiki/anchor|Anchor]]\n", encoding="utf-8")
            with patch.object(scan.os, "fstat",
                              side_effect=changing_fstat(moc)):
                self.assertEqual(
                    scan.moc_file_state(moc)["state"], "unreadable")

            wiki = root / "Wiki"
            wiki.mkdir()
            wiki_note = wiki / "anchor.md"
            wiki_note.write_text(note_text, encoding="utf-8")
            with patch.object(scan.os, "fstat",
                              side_effect=changing_fstat(wiki_note)):
                scanned = scan.scan(wiki)
            self.assertTrue(any(problem["item"] == "item0"
                                for problem in scanned["problems"]))

    @unittest.skipUnless(hasattr(os, "mkfifo") and hasattr(os, "O_NONBLOCK"),
                         "host has no POSIX FIFO support")
    def test_stable_readers_reject_a_regular_file_replaced_by_a_fifo(self):
        build = load("build_plugin_fifo_read", ROOT / "tools/build_plugin.py")
        index = load("vault_index_fifo_read", ROOT / "skills/wiki-build/scripts/vault_index.py")
        lint = load("lint_entry_fifo_read", ROOT / "skills/wiki-build/scripts/lint_entry.py")
        scan = load("scan_vault_fifo_read", ROOT / "skills/wiki-lint/scripts/scan_vault.py")

        def build_refuses(path):
            with self.assertRaises(OSError):
                build._stable_regular_snapshot(path, "package source")
            return True

        readers = (
            ("package", build_refuses),
            ("index", lambda path: bool(index.index_entry(path)["errors"])),
            ("entry lint", lambda path: any(
                row["item"] == "0-unreadable"
                for row in lint.lint_file(path)["findings"])),
            ("wiki scan", lambda path: any(
                row["item"] == "item0"
                for row in scan.scan(path.parent)["problems"])),
            ("MOC", lambda path: scan.moc_file_state(path)["state"] == "unreadable"),
        )
        with tempfile.TemporaryDirectory(prefix="obsidian-fifo-read-") as tmp:
            victim = Path(tmp) / "probe.md"
            for name, reader in readers:
                with self.subTest(reader=name):
                    victim.write_text("regular bytes before open\n", encoding="utf-8")
                    observed_flags = []
                    real_open = os.open

                    def swap_for_fifo(path, flags, *args, **kwargs):
                        if (os.path.abspath(path) == os.path.abspath(victim)
                                and not observed_flags):
                            observed_flags.append(flags)
                            victim.unlink()
                            os.mkfifo(victim)
                            # Keep a regressed reader from hanging the suite;
                            # assert its original flags after exercising the
                            # real descriptor-type rejection below.
                            flags |= os.O_NONBLOCK
                        return real_open(path, flags, *args, **kwargs)

                    try:
                        with patch.object(os, "open", side_effect=swap_for_fifo):
                            self.assertTrue(reader(victim))
                        self.assertEqual(len(observed_flags), 1)
                        self.assertTrue(observed_flags[0] & os.O_NONBLOCK)
                    finally:
                        victim.unlink()

    @unittest.skipUnless(CAN_CREATE_SYMLINK,
                         "host does not grant symlink privileges")
    def test_build_does_not_write_through_output_symlinks(self):
        with tempfile.TemporaryDirectory(prefix="obsidian-build-boundary-") as tmp:
            root = Path(tmp) / "plugin"
            copy_package_source(root)
            script = root / "tools/build_plugin.py"
            foreign = Path(tmp) / "outside.txt"
            foreign.write_text("preserve external bytes", encoding="utf-8")
            (root / "knowledge.plugin").symlink_to(foreign)
            result = subprocess.run([sys.executable, str(script)], cwd=tmp,
                                    capture_output=True, text=True,
                                    encoding="utf-8", timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symlink", result.stderr)
            self.assertEqual(
                foreign.read_text(encoding="utf-8"),
                "preserve external bytes")
            self.assertTrue((root / "knowledge.plugin").is_symlink())

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
                return_value=[("wiki-build", "fixture.md", example)]):
            conventions.check_yaml_examples(report, canonical)
        failures = [row[3] for row in report.by_status("FAIL")
                    if row[0] == "yaml-example"]
        self.assertTrue(any("tags:" in message for message in failures),
                        failures)

    def test_frontmatter_declared_lists_keep_unknown_keys_visible(self):
        conventions = load("convention_complete_schema_lists",
                           ROOT / "tests/test_conventions.py")
        conv = (ROOT / "shared/CONVENTIONS.md").read_text(encoding="utf-8")
        schemas = conventions._canonical_schemas(conv)
        valid = "\n".join("Field order: " + ", ".join(keys) + "."
                          for keys in schemas.values())
        source = schemas["source-note"]
        renderers = {
            "plain": lambda keys: "Field order: " + ", ".join(keys) + ".",
            "backticks": lambda keys: "Schema order is " +
            ", ".join("`" + key + "`" for key in keys) + ".",
            "constant": lambda keys: "SCHEMA = (" +
            ", ".join(repr(key) for key in keys) + ")",
            "numbered": lambda keys: "Frontmatter fields:\n" + "\n".join(
                "%d. `%s` — Required field." % (i, key)
                for i, key in enumerate(keys, 1)),
        }
        for index in (0, len(source) // 2, len(source) - 1):
            keys = list(source)
            keys[index] = "unexpected_property"
            for form, render in renderers.items():
                with self.subTest(index=index, form=form):
                    path = str(ROOT / "skills/paper-summarize/references/schema-probe.md")
                    report = conventions.Report()
                    with patch.object(conventions, "walk_skill_files", return_value=[
                            ("paper-summarize", path, valid + "\n\n" + render(keys))]):
                        conventions.check_frontmatter(report, conv)
                    self.assertEqual(report.exit_code(), 1)
                    self.assertTrue(any(
                        "unexpected_property" in row[3] and "not in the canonical" in row[3]
                        for row in report.by_status("FAIL")), report.results)

    def test_frontmatter_larger_record_slices_still_check_order_only(self):
        conventions = load("convention_schema_record_slices",
                           ROOT / "tests/test_conventions.py")
        conv = (ROOT / "shared/CONVENTIONS.md").read_text(encoding="utf-8")
        schemas = conventions._canonical_schemas(conv)
        valid = "\n".join("Field order: " + ", ".join(keys) + "."
                          for keys in schemas.values())
        entry = [key for key in schemas["wiki-entry"] if key != "read"]
        renderers = {
            "record": lambda keys: "Per-entry record: " + ", ".join(keys) + ".",
            "constant": lambda keys: "INDEX_FIELDS = [" +
            ", ".join(repr(key) for key in keys) + "]",
            "response": lambda keys: "The response has fields: " +
            ", ".join("`" + key + "`" for key in keys) + ".",
        }
        for reordered in (False, True):
            members = list(entry)
            if reordered:
                members[0], members[1] = members[1], members[0]
            for prefix in ([], ["slug", "path", "relpath"]):
                keys = prefix + members + ["body_wikilink_targets", "errors"]
                for form, render in renderers.items():
                    with self.subTest(reordered=reordered, prefix=prefix, form=form):
                        path = str(ROOT / "skills/wiki-build/references/index-probe.md")
                        report = conventions.Report()
                        with patch.object(conventions, "walk_skill_files", return_value=[
                                ("wiki-build", path, valid + "\n\n" + render(keys))]):
                            conventions.check_frontmatter(report, conv)
                        self.assertEqual(report.exit_code(), int(reordered), report.results)
                        if reordered:
                            self.assertTrue(any("out of order" in row[3]
                                                for row in report.by_status("FAIL")))
                        else:
                            self.assertTrue(any("order only" in row[3]
                                                for row in report.by_status("PASS")))

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
        for relative in ("skills/paper-summarize/scripts/note_lint.py",
                         "shared/scripts/vault_artifacts.py"):
            with self.subTest(module=relative):
                module = conventions.mod_generic(str(ROOT / relative))
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
            ROOT / "skills/wiki-build/scripts/lint_entry.py")
        linter = load(
            "compat_linter_source_identity",
            ROOT / "skills/wiki-lint/scripts/scan_vault.py")
        cases = (
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

    def test_source_note_consumers_agree_on_origin_ownership(self):
        clipping = load(
            "compat_clipping_origin", ROOT / "skills/clipping-clean/scripts/dedup_index.py")
        paper = load(
            "compat_paper_origin", ROOT / "skills/paper-summarize/scripts/paper_scan.py")
        organizer = load(
            "compat_organizer_origin", ROOT / "skills/pdf-organize/scripts/organize.py")
        pdf = "[[Doe_Study_2025.pdf]]"
        url = "https://example.org/observed#section"
        cases = (
            (f'sources:\n  - "{url}"\nsource: "{pdf}"', url),
            (f'"sources": ["{url}"]', url),
            (f'"so\\u0075rces": ["{pdf}"]', pdf),
            (f"'sources':\n- '{pdf}' # origin", pdf),
            (f'tags:\n- "#misc"\nsources:\n- "{pdf}"', pdf),
            (f'"sources": ["{url}"]\nsources:\n  - "{pdf}"', None),
            (f'"sources": ["{url}"]\nsource: "{pdf}"', url),
            (f'sources: "{url}"\nsource: "{pdf}"', None),
            (f'sources: []\nsource: "{pdf}"', None),
            (f'sources:\n  - "{pdf}"\n  - [nested]', None),
            (f'sources:\n  - "{pdf}"\n  - null', None),
            (f'"source": "{url}"\nsource: "{pdf}"', None),
            (f'? sources\n: ["{url}"]\nsource: "{pdf}"', None),
            (f'<<: *other\nsource: "{pdf}"', None),
            (f'source: "{pdf}"', pdf),
        )
        with tempfile.TemporaryDirectory(prefix="obsidian-origin-readers-") as tmp:
            note = Path(tmp) / "note.md"
            for metadata, expected in cases:
                with self.subTest(metadata=metadata):
                    note.write_text(
                        "---\n" + metadata + "\n---\nOrdinary note body.\n",
                        encoding="utf-8")
                    self.assertEqual(clipping.read_source(note), expected)
                    self.assertEqual(paper.note_source(note), expected)
                    self.assertEqual(
                        organizer._note_is_about(note, "Doe_Study_2025"), expected == pdf)

    def test_heading_contract_requires_its_reference_and_ordered_examples(self):
        conventions = load("convention_heading_contract", ROOT / "tests/test_conventions.py")
        format_path = ROOT / "skills/paper-summarize/references/note-format.md"
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
            ("clipping-clean", "", 0),
            ("paper-summarize", "", 1),
            ("wiki-build", "*The study design.*", 0),
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
        scripts = ROOT / "skills/figure-extract/scripts"
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

    def test_each_plugin_runs_with_repository_and_sibling_paths_unavailable(self):
        # A complete runtime must work by itself from a vault whose path, like
        # real host cache paths, contains spaces. Isolated Python removes the
        # checkout/PYTHONPATH import route; the hook also rejects explicit reads
        # from the checkout or the unavailable sibling. The dependency venv is
        # allowed when CI/development keeps it inside the source checkout.
        runner = r"""
import os
import runpy
import sys
script, source_root, sibling_root = sys.argv[1:4]
arguments = sys.argv[4:]
source_root = os.path.realpath(source_root)
sibling_root = os.path.realpath(sibling_root)
dependency_root = os.path.realpath(sys.prefix)
def beneath(path, root):
    return path == root or path.startswith(root + os.sep)
def audit(event, args):
    if event in ("open", "os.listdir", "os.scandir"):
        path = args[0]
    elif event == "import" and len(args) > 1:
        path = args[1]
    else:
        return
    if not isinstance(path, (str, bytes)):
        return
    path = os.path.realpath(os.fsdecode(path))
    if beneath(path, sibling_root) or (
            beneath(path, source_root) and not beneath(path, dependency_root)):
        raise PermissionError("Independent plugin cannot read " + path)
sys.addaudithook(audit)
for forbidden in (os.path.join(source_root, "shared", "scripts", "slugify.py"),
                  os.path.join(sibling_root, "skills", "unavailable.py")):
    try:
        open(forbidden, "rb")
    except PermissionError:
        pass
    else:
        raise AssertionError("The isolation hook did not deny " + forbidden)
# runpy does not supply the script directory like an ordinary CLI launch.
# Restore only that installed directory, never a repository or sibling path.
sys.path.insert(0, os.path.dirname(os.path.abspath(script)))
sys.argv = [script] + arguments
runpy.run_path(script, run_name="__main__")
"""
        for name in PLUGIN_SKILLS:
            with self.subTest(plugin=name), tempfile.TemporaryDirectory(
                    prefix="independent-plugin-") as tmp:
                root = Path(tmp).resolve()
                install = root / (name + " plugin with spaces")
                vault = root / "vault with spaces"
                vault.mkdir()
                sibling_name = next(other for other in PLUGIN_SKILLS if other != name)
                sibling = root / sibling_name
                self.assertFalse(sibling.exists())
                with zipfile.ZipFile(ROOT / (name + ".plugin")) as archive:
                    archive.extractall(install)
                env = dict(os.environ)
                for variable in ("OBSIDIAN_VAULT_SHARED", "PYTHONPATH", "PYTHONHOME"):
                    env.pop(variable, None)
                scripts = sorted((install / "skills").glob("*/scripts/*.py"))
                scripts += sorted((install / "shared/scripts").glob("*.py"))
                self.assertTrue(scripts)
                for path in scripts:
                    with self.subTest(script=path.relative_to(install).as_posix()):
                        result = subprocess.run(
                            [sys.executable, "-I", "-B", "-c", runner,
                             str(path), str(ROOT), str(sibling), "--help"],
                            cwd=vault, env=env, capture_output=True, text=True,
                            encoding="utf-8", timeout=30)
                        self.assertEqual(result.returncode, 0,
                                         result.stdout + result.stderr)
                self.assertFalse(sibling.exists())
                self.assertEqual(list(vault.iterdir()), [])

    def test_each_installed_plugin_resolves_its_local_markdown_links(self):
        conventions = load("installed_link_masks", ROOT / "tests/test_conventions.py")
        link = re.compile(r"\]\(\s*<?([^\s)>]+)>?(?:\s+[^)]*)?\)")
        for name in PLUGIN_SKILLS:
            with self.subTest(plugin=name), tempfile.TemporaryDirectory(
                    prefix="independent-plugin-links-") as tmp:
                install = Path(tmp).resolve() / (name + " plugin")
                with zipfile.ZipFile(ROOT / (name + ".plugin")) as archive:
                    archive.extractall(install)
                checked = 0
                for path in sorted(install.rglob("*.md")):
                    visible = conventions._mask_markdown_code(
                        path.read_text(encoding="utf-8"))
                    for match in link.finditer(visible):
                        target = urlsplit(match.group(1))
                        if target.scheme or target.netloc:
                            continue
                        checked += 1
                        resolved = ((path.parent / unquote(target.path)).resolve()
                                    if target.path else path)
                        self.assertTrue(resolved.is_relative_to(install),
                            "%s: local link escapes %s: %s" %
                            (path.relative_to(install), name, match.group(1)))
                        self.assertTrue(resolved.exists(),
                            "%s: missing installed link %s" %
                            (path.relative_to(install), match.group(1)))
                        if target.fragment and resolved.suffix == ".md":
                            anchors = conventions._markdown_heading_anchors(
                                resolved.read_text(encoding="utf-8"))
                            self.assertIn(unquote(target.fragment), anchors,
                                "%s: missing installed heading %s" %
                                (path.relative_to(install), match.group(1)))
                self.assertGreater(checked, 0, "No local links were checked for " + name)

    def test_source_build_checks_without_writing_and_rebuilds_missing_outputs(self):
        with tempfile.TemporaryDirectory(prefix="independent-source-build-") as tmp:
            root = Path(tmp).resolve() / "source checkout"
            copy_package_source(root)
            working = Path(tmp) / "unrelated working directory"
            working.mkdir()
            check = [sys.executable, str(root / "tools/build_plugin.py"), "--check"]
            env = dict(os.environ)
            env.pop("OBSIDIAN_VAULT_SHARED", None)
            missing = subprocess.run(
                check, cwd=working, env=env, capture_output=True, timeout=30)
            self.assertEqual(missing.returncode, 1, missing.stdout + missing.stderr)
            for name in PLUGIN_SKILLS:
                self.assertFalse((root / "plugins" / name / ".codex-plugin").exists())
                self.assertFalse((root / "plugins" / name / "skills").exists())
                self.assertFalse((root / (name + ".plugin")).exists())
            built = subprocess.run(
                check[:-1], cwd=working, env=env, capture_output=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            for name in PLUGIN_SKILLS:
                self.assertTrue((root / "plugins" / name / ".codex-plugin/plugin.json").is_file())
                self.assertTrue((root / (name + ".plugin")).is_file())
            current = subprocess.run(
                check, cwd=working, env=env, capture_output=True, timeout=30)
            self.assertEqual(current.returncode, 0, current.stdout + current.stderr)
            with (root / "shared/RUNTIME.md").open("a", encoding="utf-8") as output:
                output.write("\nChanged after packaging.\n")
            stale = subprocess.run(
                check, cwd=working, env=env, capture_output=True, timeout=30)
            self.assertEqual(stale.returncode, 1, stale.stdout + stale.stderr)

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
                 ROOT / "skills/paper-summarize/scripts/note_lint.py",
                 note, "--mode", "empirical"),
                ("paper scan", 0,
                 ROOT / "skills/paper-summarize/scripts/paper_scan.py",
                 "--src", pdfs, "--notes", notes, "--images", images,
                 "--allow-unorganized"),
                ("paper text", 0,
                 ROOT / "skills/paper-summarize/scripts/paper_text.py",
                 pdf, "--pages"),
                ("automatic crop", 0,
                 ROOT / "skills/figure-extract/scripts/auto_fig_bbox.py",
                 pdf, "--pages", "1", "--emit", "extract"),
                ("explicit crop", 0,
                 ROOT / "skills/figure-extract/scripts/extract_figures.py",
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
        fetch = load("fetch_images", ROOT / "skills/clipping-clean/scripts/fetch_images.py")
        public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("177.0.0.1", 0))]
        with patch.object(fetch.socket, "getaddrinfo", return_value=public) as resolve:
            for host in ("0177.0.0.1", "0x7f000001", "2130706433", "127.1"):
                with self.subTest(host=host), self.assertRaises(ValueError):
                    fetch.check_url("http://" + host + "/image.png")
            resolve.assert_not_called()
            fetch.check_url("https://177.0.0.1/image.png")
            resolve.assert_called_once()

    def test_generated_commands_preserve_interpreter_and_literal_paths(self):
        scripts = ROOT / "skills/figure-extract/scripts"
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
