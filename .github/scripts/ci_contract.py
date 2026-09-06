#!/usr/bin/env python3
"""Derive dependency floors and enforce independent plugin release versions."""

import argparse
import json
from pathlib import Path
import re
import subprocess


REQUIREMENT = re.compile(
    r"(?P<name>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)"
    r"(?:\[[A-Za-z0-9._,-]+\])?\s*>=\s*"
    r"(?P<version>[A-Za-z0-9](?:[A-Za-z0-9.!+_-]*[A-Za-z0-9])?)"
    r"(?:\s*;\s*(?P<marker>.+))?"
)
INCLUDE = re.compile(r"(?:-r\s+|--requirement(?:=|\s+))(?P<path>\S+)")
SEMVER = re.compile(
    r"(?P<major>0|[1-9][0-9]*)\."
    r"(?P<minor>0|[1-9][0-9]*)\."
    r"(?P<patch>0|[1-9][0-9]*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)
PACKAGE_INVENTORY = "tools/package-files.txt"
PACKAGE_MAPS = "tools/package-files.json"
PLUGIN_NAMES = ("knowledge", "investments")
LEGACY_MANIFEST = ".claude-plugin/plugin.json"
LEGACY_PACKAGE_ROOT_FILES = {
    ".gitattributes",
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "requirements.txt",
    "requirements-dev.txt",
}
LEGACY_PACKAGE_TREES = {
    ".claude-plugin",
    "skills",
    "shared",
    "tests",
    "tools",
}
IGNORED_PACKAGE_FILES = {".DS_Store"}
IGNORED_PACKAGE_SUFFIXES = {".pyc", ".pyo"}
IGNORED_PACKAGE_DIRS = {"__pycache__"}


class ContractError(ValueError):
    """A checked CI contract is ambiguous or violated."""


def _inside(root, path):
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def declared_floors(requirements, repository):
    """Return exact constraints for recursively included ``name>=floor`` lines."""
    repository = repository.resolve()
    floors = {}
    active = set()
    visited = set()

    def visit(path):
        path = path.resolve()
        if not _inside(repository, path):
            raise ContractError("requirements include escapes the repository: %s" % path)
        if path in active:
            raise ContractError("cyclic requirements include: %s" % path)
        if path in visited:
            return
        active.add(path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ContractError("cannot read requirements file %s: %s" %
                                (path.relative_to(repository), exc)) from exc
        for number, original in enumerate(text.splitlines(), 1):
            line = re.sub(r"\s+#.*$", "", original).strip()
            if not line or line.startswith("#"):
                continue
            include = INCLUDE.fullmatch(line)
            if include:
                visit(path.parent / include.group("path"))
                continue
            requirement = REQUIREMENT.fullmatch(line)
            if not requirement:
                raise ContractError(
                    "%s:%d must be a recursive include or one simple "
                    "name>=floor requirement; extend this checker before using "
                    "another requirement form" %
                    (path.relative_to(repository), number))
            name = requirement.group("name")
            key = re.sub(r"[-_.]+", "-", name).lower()
            marker = requirement.group("marker")
            value = (name, requirement.group("version"), marker)
            floor_key = (key, marker or "")
            previous = floors.get(floor_key)
            if previous is not None and previous[1] != value[1]:
                raise ContractError(
                    "conflicting declared floors for %s: %s and %s" %
                    (name, previous[1], value[1]))
            floors[floor_key] = value
        active.remove(path)
        visited.add(path)

    visit(requirements)
    if not floors:
        raise ContractError("no declared dependency floors were found")
    return [
        "%s==%s%s" % (name, version, " ; " + marker if marker else "")
        for _, (name, version, marker) in sorted(floors.items())
    ]


def write_floors(requirements, output, repository):
    lines = declared_floors(requirements, repository)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Wrote exact constraints for %d declared dependency floors." % len(lines))


def _git(repository, *arguments, check=True):
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ContractError("git %s failed: %s" %
                            (" ".join(arguments), detail or result.returncode))
    return result


def _git_text(repository, *arguments):
    return _git(repository, *arguments).stdout.decode("utf-8")


def _revision_file(repository, revision, name, required=True):
    result = _git(repository, "show", "%s:%s" % (revision, name), check=False)
    if result.returncode:
        if required:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise ContractError("cannot read %s from %s: %s" %
                                (name, revision, detail or result.returncode))
        return None
    try:
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError("%s is not UTF-8 in %s" % (name, revision)) from exc


def _revision_blob(repository, revision, name):
    """Return a path's blob bytes, or ``None`` when it is absent/non-blob."""
    result = _git(
        repository, "cat-file", "blob", "%s:%s" % (revision, name),
        check=False)
    return result.stdout if result.returncode == 0 else None


def _inventory(repository, revision):
    text = _revision_file(
        repository, revision, PACKAGE_INVENTORY, required=False)
    if text is None:
        return None
    names = text.splitlines()
    if not names or any(not name or name != name.strip() for name in names):
        raise ContractError("%s is malformed in %s" %
                            (PACKAGE_INVENTORY, revision))
    return set(names)


def _legacy_package_path(name):
    path = Path(name)
    if (path.name in IGNORED_PACKAGE_FILES
            or path.suffix.lower() in IGNORED_PACKAGE_SUFFIXES
            or any(part in IGNORED_PACKAGE_DIRS for part in path.parts)):
        return False
    if name in LEGACY_PACKAGE_ROOT_FILES:
        return True
    return name.split("/", 1)[0] in LEGACY_PACKAGE_TREES


def packaged_changes(changed, base_inventory, head_inventory):
    """Select listed inputs and unlisted files inside the package boundary."""
    package = {PACKAGE_INVENTORY}
    for inventory in (base_inventory, head_inventory):
        if inventory is not None:
            package.update(inventory)
    return sorted(
        name for name in changed
        if name in package or _legacy_package_path(name))


def parse_semver(value):
    match = SEMVER.fullmatch(value)
    if not match:
        raise ContractError("plugin version is not SemVer: %r" % value)
    core = tuple(int(match.group(name)) for name in ("major", "minor", "patch"))
    prerelease = match.group("prerelease")
    identifiers = None if prerelease is None else prerelease.split(".")
    if identifiers is not None and any(
            item.isdigit() and len(item) > 1 and item.startswith("0")
            for item in identifiers):
        raise ContractError(
            "plugin version has a zero-padded numeric prerelease field: %r" %
            value)
    return core, identifiers


def semver_is_greater(candidate, baseline):
    candidate_core, candidate_pre = parse_semver(candidate)
    baseline_core, baseline_pre = parse_semver(baseline)
    if candidate_core != baseline_core:
        return candidate_core > baseline_core
    if candidate_pre is None or baseline_pre is None:
        return candidate_pre is None and baseline_pre is not None
    for left, right in zip(candidate_pre, baseline_pre):
        if left == right:
            continue
        left_numeric = left.isdigit()
        right_numeric = right.isdigit()
        if left_numeric and right_numeric:
            return int(left) > int(right)
        if left_numeric != right_numeric:
            return not left_numeric
        return left > right
    return len(candidate_pre) > len(baseline_pre)


def _manifest_version(repository, revision,
                      name=".claude-plugin/plugin.json", expected_name=None):
    text = _revision_file(repository, revision, name)
    try:
        manifest = json.loads(text)
        version = manifest["version"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ContractError("authored manifest %s is invalid in %s: %s" %
                            (name, revision, exc)) from exc
    if expected_name is not None and manifest.get("name") != expected_name:
        raise ContractError("authored manifest %s must name plugin %r in %s" %
                            (name, expected_name, revision))
    if not isinstance(version, str):
        raise ContractError("authored manifest version is not text in %s" % revision)
    parse_semver(version)
    return version


def _require_version_advance(plugin, candidate, baseline, changes):
    """Compare one distribution's release identity with its own baseline."""
    if not semver_is_greater(candidate, baseline):
        preview = ", ".join(changes[:8])
        if len(changes) > 8:
            preview += ", and %d more" % (len(changes) - 8)
        raise ContractError(
            "%s packaged source changed (%s), but authored plugin version %s "
            "does not advance base version %s" %
            (plugin, preview, candidate, baseline))
    print("%s packaged source changed and version advances %s -> %s." %
          (plugin, baseline, candidate))


def _split_versions(repository, revision):
    """Require both fixed release identities once the split layout is present."""
    manifests = {
        plugin: "plugins/%s/.claude-plugin/plugin.json" % plugin
        for plugin in PLUGIN_NAMES
    }
    present = {
        plugin for plugin, name in manifests.items()
        if _revision_blob(repository, revision, name) is not None
    }
    if not present:
        return None
    if present != set(PLUGIN_NAMES):
        raise ContractError(
            "split release is incomplete in %s; both knowledge and investments "
            "authored manifests are required" % revision)
    if _revision_blob(repository, revision, LEGACY_MANIFEST) is not None:
        raise ContractError(
            "split release in %s must remove the legacy obsidian authored "
            "manifest" % revision)
    return {
        plugin: _manifest_version(
            repository, revision, name, expected_name=plugin)
        for plugin, name in manifests.items()
    }


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("duplicate JSON key in package maps: %r" % key)
        result[key] = value
    return result


def _valid_relative_path(value):
    return (
        isinstance(value, str) and bool(value)
        and "\\" not in value and not value.startswith("/")
        and not any(ord(character) < 32 for character in value)
        and all(part not in ("", ".", "..") for part in value.split("/"))
    )


def _package_maps(repository, revision):
    """Read historical input maps as data, never execute a past build script."""
    text = _revision_file(repository, revision, PACKAGE_MAPS, required=False)
    if text is None:
        return None
    try:
        maps = json.loads(text, object_pairs_hook=_unique_json_object)
    except json.JSONDecodeError as exc:
        raise ContractError("%s is invalid in %s: %s" %
                            (PACKAGE_MAPS, revision, exc)) from exc
    if not isinstance(maps, dict) or set(maps) != set(PLUGIN_NAMES):
        raise ContractError("%s must define exactly knowledge and investments "
                            "in %s" % (PACKAGE_MAPS, revision))
    for plugin, files in maps.items():
        if not isinstance(files, dict) or not files or any(
                not _valid_relative_path(destination)
                or not _valid_relative_path(source)
                for destination, source in files.items()):
            raise ContractError("%s has invalid %s package paths in %s" %
                                (PACKAGE_MAPS, plugin, revision))
        manifest = "plugins/%s/.claude-plugin/plugin.json" % plugin
        if files.get(".claude-plugin/plugin.json") != manifest:
            raise ContractError("%s must map %s's own authored manifest in %s" %
                                (PACKAGE_MAPS, plugin, revision))
    return maps


def _split_state(repository, revision):
    versions = _split_versions(repository, revision)
    maps = _package_maps(repository, revision)
    if (versions is None) != (maps is None):
        raise ContractError("split release in %s requires both authored "
                            "manifests and %s" % (revision, PACKAGE_MAPS))
    return versions, maps


def plugin_packaged_changes(plugin, changed, base_map, head_map,
                            comparison_map=None):
    """Attribute mapped inputs, outputs and map edits to one distribution."""
    if comparison_map is None:
        comparison_map = base_map
    sources = (set(base_map.values()) | set(head_map.values())
               | set(comparison_map.values()))
    prefix = "plugins/%s/" % plugin
    archive = "%s.plugin" % plugin
    selected = {
        name for name in changed
        if name in sources or name.startswith(prefix) or name == archive
    }
    # Only this plugin's projection matters: editing a knowledge entry in the
    # common map must not require an investments release, or vice versa.
    if comparison_map != head_map:
        selected.add(PACKAGE_MAPS + "[%s]" % plugin)
    return sorted(selected)


def check_version_bump(repository, base, comparison):
    repository = repository.resolve()
    if not base:
        raise ContractError("an event base revision is required")
    if set(base) == {"0"}:
        raise ContractError(
            "the pushed ref has no prior revision; the version gate cannot "
            "verify a release baseline")
    resolved_base = _git_text(
        repository, "rev-parse", "--verify", "--end-of-options",
        "%s^{commit}" % base).strip()
    if comparison == "pull-request":
        diff_base = _git_text(
            repository, "merge-base", resolved_base, "HEAD").strip()
    elif comparison == "push":
        # Compare the old and new ref tips directly. A merge-base comparison
        # would miss a force push that rolls the packaged tree back to an
        # ancestor of the previous tip.
        diff_base = resolved_base
    else:
        raise ContractError("unknown comparison mode: %r" % comparison)
    changed_bytes = _git(
        repository, "diff", "--no-renames", "--name-only",
        "--diff-filter=ACDMRTUXB", "-z",
        diff_base, "HEAD").stdout
    try:
        changed = [name for name in changed_bytes.decode("utf-8").split("\0")
                   if name]
    except UnicodeDecodeError as exc:
        raise ContractError("changed repository paths are not UTF-8") from exc
    # Git reports mode-only changes, while the archive deliberately gives every
    # entry the same fixed mode. Compare blobs so those do not force a release.
    changed = [
        name for name in changed
        if _revision_blob(repository, diff_base, name)
        != _revision_blob(repository, "HEAD", name)
    ]
    baseline_versions, baseline_maps = _split_state(repository, resolved_base)
    candidate_versions, candidate_maps = _split_state(repository, "HEAD")
    if baseline_versions is not None and candidate_versions is None:
        raise ContractError(
            "the split knowledge/investments release cannot roll back to the "
            "legacy layout or remove both plugin identities")
    if candidate_versions is not None:
        if baseline_versions is None:
            # New names have independent release histories. This is a one-way
            # migration from the actual legacy identity, not an exemption that
            # can be reused by deleting a released plugin's manifest or map.
            legacy_version = _manifest_version(
                repository, resolved_base, LEGACY_MANIFEST,
                expected_name="obsidian")
            print("Legacy obsidian %s becomes independent first releases: %s." %
                  (legacy_version, ", ".join(
                      "%s %s" % (plugin, candidate_versions[plugin])
                      for plugin in PLUGIN_NAMES)))
            return
        comparison_maps = _package_maps(repository, diff_base) or {
            plugin: {} for plugin in PLUGIN_NAMES
        }
        any_changes = False
        for plugin in PLUGIN_NAMES:
            changes = plugin_packaged_changes(
                plugin, changed, baseline_maps[plugin], candidate_maps[plugin],
                comparison_map=comparison_maps[plugin])
            if changes:
                any_changes = True
                _require_version_advance(
                    plugin, candidate_versions[plugin],
                    baseline_versions[plugin], changes)
        if not any_changes:
            print("No packaged source changed; no plugin version bump is required.")
        return
    package_changes = packaged_changes(
        changed,
        _inventory(repository, resolved_base),
        _inventory(repository, "HEAD"),
    )
    if not package_changes:
        print("No packaged source changed; no plugin version bump is required.")
        return
    baseline = _manifest_version(repository, resolved_base)
    candidate = _manifest_version(repository, "HEAD")
    _require_version_advance("obsidian", candidate, baseline, package_changes)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    floors = subparsers.add_parser(
        "floors", help="derive exact constraints from all declared lower bounds")
    floors.add_argument("requirements", type=Path)
    floors.add_argument("--output", type=Path, required=True)
    floors.add_argument("--repository", type=Path, default=Path.cwd())
    version = subparsers.add_parser(
        "version", help="require each affected plugin's release version to advance")
    version.add_argument("--base", required=True)
    version.add_argument(
        "--comparison", choices=("pull-request", "push"), required=True)
    version.add_argument("--repository", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        if args.command == "floors":
            write_floors(
                args.requirements.resolve(), args.output.resolve(),
                args.repository.resolve())
        else:
            check_version_bump(
                args.repository, args.base.strip(), args.comparison)
    except ContractError as exc:
        parser.exit(1, "CI contract failed: %s\n" % exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
