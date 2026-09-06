#!/usr/bin/env python3
"""Build independently installable knowledge and investments plugins."""

import argparse
from contextlib import contextmanager
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import unicodedata
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SHARED_SCRIPTS = ROOT / "shared/scripts"
if str(SHARED_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SHARED_SCRIPTS))

import atomic_move


PLUGIN_NAMES = ("knowledge", "investments")
PACKAGE_TREES = ("skills", "shared")
PACKAGE_INVENTORY = "tools/package-files.json"
IGNORED_PACKAGE_FILES = {".DS_Store"}
IGNORED_PACKAGE_SUFFIXES = {".pyc", ".pyo"}
IGNORED_PACKAGE_DIRS = {"__pycache__"}


def _validate_package_names(files):
    """Reject unsafe archive names and names that collapse together."""
    owners = {}
    for name in files:
        if not isinstance(name, str) or not name:
            raise ValueError("plugin archive contains an empty or non-text path")
        if name.startswith("/"):
            raise ValueError("plugin archive path must be relative: %r" % name)
        components = name.split("/")
        if any(component in ("", ".", "..") for component in components):
            raise ValueError("plugin archive path is not relative and normalized: %r" % name)
        if any(ord(char) < 32 for component in components for char in component):
            raise ValueError(
                "plugin archive path uses a control character: %r" % name)
        normalized = unicodedata.normalize("NFC", name)
        if normalized != name:
            raise ValueError(
                "plugin archive path is not NFC-normalized: %r" % name)
        key = normalized.casefold()
        previous = owners.setdefault(key, name)
        if previous != name:
            raise ValueError(
                "plugin archive paths collide by case or Unicode normalization: "
                "%r and %r" % (previous, name))


def _package_inventory(root, snapshots=None):
    """Validate exact per-plugin destination/source maps and source coverage."""
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate package-map key: %s" % key)
            result[key] = value
        return result

    raw = _read_package_source(root, root / PACKAGE_INVENTORY, snapshots)
    maps = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs)
    if not isinstance(maps, dict) or set(maps) != set(PLUGIN_NAMES):
        raise ValueError("package maps must contain exactly knowledge and investments")
    sources = set()
    for plugin, mapping in maps.items():
        if not isinstance(mapping, dict) or not mapping:
            raise ValueError("%s package map must be a nonempty object" % plugin)
        _validate_package_names(mapping)
        if not all(isinstance(source, str) for source in mapping.values()):
            raise ValueError("package-map sources must be repository-relative paths")
        _validate_package_names(dict.fromkeys(mapping.values()))
        required = {".claude-plugin/plugin.json", "README.md", "requirements.txt"}
        if not required <= set(mapping):
            raise ValueError("%s package map omits required runtime metadata" % plugin)
        if ".codex-plugin/plugin.json" in mapping:
            raise ValueError("Codex manifests are generated, never mapped inputs")
        manifest_path = "plugins/%s/.claude-plugin/plugin.json" % plugin
        if mapping[".claude-plugin/plugin.json"] != manifest_path:
            raise ValueError("%s authored manifest must be %s" % (plugin, manifest_path))
        for destination, source in mapping.items():
            if destination.startswith(("skills/", "shared/")) and destination != source:
                raise ValueError("runtime skill/shared paths must retain their source layout")
            if not (destination in required or destination.startswith(("skills/", "shared/"))):
                raise ValueError("unexpected runtime package path: %s" % destination)
            if source.startswith("plugins/") and source != "plugins/%s/%s" % (plugin, destination):
                raise ValueError("a plugin cannot depend on another generated tree: %s" % source)
        sources.update(mapping.values())

    actual = set()
    for tree in PACKAGE_TREES:
        directory = root / tree
        reject_symlinks(root, directory)
        for path in sorted(directory.rglob("*")):
            relative = path.relative_to(root)
            if any(part in IGNORED_PACKAGE_DIRS for part in relative.parts):
                continue
            reject_symlinks(root, path)
            if path.is_dir():
                continue
            if (path.name in IGNORED_PACKAGE_FILES
                    or path.suffix.lower() in IGNORED_PACKAGE_SUFFIXES):
                continue
            if not path.is_file():
                raise ValueError("plugin source contains a non-regular path: %s" % relative)
            actual.add(relative.as_posix())
    listed = {source for source in sources
              if any(source.startswith(tree + "/") for tree in PACKAGE_TREES)}
    if actual != listed:
        raise ValueError("%s is stale (unlisted files: %s; missing files: %s)" %
                         (PACKAGE_INVENTORY, ", ".join(sorted(actual - listed)),
                          ", ".join(sorted(listed - actual))))
    skill_owners = {}
    for plugin, mapping in maps.items():
        for destination in mapping:
            if destination.startswith("skills/"):
                skill = destination.split("/")[1]
                owner = skill_owners.setdefault(skill, plugin)
                if owner != plugin:
                    raise ValueError("skill %s appears in both plugins" % skill)
    if skill_owners.get("market-research") != "investments":
        raise ValueError("market-research must belong to investments")
    if any(owner != "knowledge" for skill, owner in skill_owners.items()
           if skill != "market-research"):
        raise ValueError("knowledge skills must belong to knowledge")
    return maps


def _validate_distribution_tree(root, plugin, files):
    """Refuse unlisted output files; never delete unexpected runtime residue."""
    directory = root / "plugins" / plugin
    reject_symlinks(root, directory)
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if any(part in IGNORED_PACKAGE_DIRS for part in relative.parts):
            continue
        reject_symlinks(root, path)
        if path.is_dir():
            continue
        if (path.name in IGNORED_PACKAGE_FILES
                or path.suffix.lower() in IGNORED_PACKAGE_SUFFIXES):
            continue
        if not path.is_file() or relative.as_posix() not in files:
            raise ValueError("unlisted or non-regular generated path: %s; inspect it "
                             "before removing an obsolete generated asset" % path.relative_to(root))


def reject_symlinks(root, path):
    """Keep source reads and generated writes inside a self-contained tree."""
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        try:
            item = os.lstat(current)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(item.st_mode):
            raise ValueError("plugin path is a symlink: %s" % current.relative_to(root))


def _stable_regular_snapshot(path, label):
    """Read one regular file without accepting an identity/content race.

    The equality key omits ctime and link count because guarded publication
    temporarily creates private hard links to the authorized inode. Those
    fields remain part of the before/after stability check.
    """
    path = os.fspath(path)
    try:
        before = os.lstat(path)
    except OSError as exc:
        raise OSError(
            getattr(exc, "errno", None) or errno.EIO,
            "%s is missing or unreadable (%s)" % (label, exc),
            path,
        ) from exc
    if not stat.S_ISREG(before.st_mode):
        raise OSError(
            errno.EINVAL,
            "%s is a symlink or non-regular file" % label,
            path,
        )

    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise OSError(
            getattr(exc, "errno", None) or errno.EIO,
            "%s changed or could not be opened safely (%s)" % (label, exc),
            path,
        ) from exc

    digest = hashlib.sha256()
    chunks = []
    with os.fdopen(descriptor, "rb") as source:
        opened_before = os.fstat(source.fileno())
        if (not stat.S_ISREG(opened_before.st_mode)
                or (before.st_dev, before.st_ino,
                    stat.S_IFMT(before.st_mode)) !=
                (opened_before.st_dev, opened_before.st_ino,
                 stat.S_IFMT(opened_before.st_mode))):
            raise OSError(
                errno.EBUSY,
                "%s changed while it was opened" % label,
                path,
            )
        for chunk in iter(lambda: source.read(65536), b""):
            chunks.append(chunk)
            digest.update(chunk)
        opened_after = os.fstat(source.fileno())

    try:
        after = os.lstat(path)
    except OSError as exc:
        raise OSError(
            getattr(exc, "errno", None) or errno.EIO,
            "%s changed while it was read (%s)" % (label, exc),
            path,
        ) from exc

    def stable(item):
        return (
            item.st_dev,
            item.st_ino,
            stat.S_IFMT(item.st_mode),
            stat.S_IMODE(item.st_mode),
            item.st_size,
            getattr(item, "st_mtime_ns", int(item.st_mtime * 1e9)),
            getattr(item, "st_ctime_ns", int(item.st_ctime * 1e9)),
        )

    if not (stable(before) == stable(opened_before)
            == stable(opened_after) == stable(after)):
        raise OSError(
            errno.EBUSY,
            "%s changed while its bytes were read" % label,
            path,
        )
    return (
        (after.st_dev, after.st_ino, stat.S_IFMT(after.st_mode)),
        digest.hexdigest(),
        stat.S_IMODE(after.st_mode),
        after.st_size,
        b"".join(chunks),
    )


def _stable_output_snapshot(path):
    """Return an identity/content snapshot for a generated output."""
    return _stable_regular_snapshot(path, "generated output")


def _read_package_source(root, path, snapshots=None):
    """Read one allowlisted source without following a swapped leaf link."""
    reject_symlinks(root, path)
    snapshot = _stable_regular_snapshot(path, "package source")
    # Catch a directory-component substitution that happened during the read;
    # the bytes are discarded and can never reach the archive.
    reject_symlinks(root, path)
    if snapshots is not None:
        previous = snapshots.setdefault(path, snapshot)
        if previous != snapshot:
            raise OSError(errno.EBUSY, "package source changed during collection", os.fspath(path))
    return snapshot[4]


def _verify_sources(root, snapshots):
    """Require all derived files to use the same unchanged source snapshots."""
    for path, expected in snapshots.items():
        reject_symlinks(root, path)
        current = _stable_regular_snapshot(path, "package source")
        reject_symlinks(root, path)
        if current != expected:
            raise OSError(errno.EBUSY, "package source changed after planning", os.fspath(path))


def _observe_output(path):
    """Return an exact output snapshot, or ``None`` for an unoccupied name."""
    if not os.path.lexists(path):
        return None
    return _stable_output_snapshot(path)


def _snapshot_matches(snapshot, content):
    """Compare generated bytes with a snapshot without rereading the path."""
    return snapshot is not None and snapshot[4] == content


def _directory_identity(path):
    """Return one ordinary directory's no-follow filesystem identity."""
    path = os.fspath(path)
    item = os.lstat(path)
    if (not stat.S_ISDIR(item.st_mode)
            or stat.S_ISLNK(item.st_mode)):
        raise OSError(errno.ENOTDIR,
                      "generated output parent is a symlink or non-directory",
                      path)
    return item.st_dev, item.st_ino, stat.S_IFMT(item.st_mode)


def _observe_parent(path):
    """Return a directory identity, or ``None`` only when it is absent."""
    if not os.path.lexists(path):
        return None
    return _directory_identity(path)


def _create_output_parent(root, path):
    """Create nested output directories through verified parent descriptors."""
    root = Path(os.path.abspath(root))
    path = Path(os.path.abspath(path))
    try:
        parts = path.relative_to(root).parts
    except ValueError as exc:
        raise OSError(errno.EPERM, "generated output parent is outside repository", os.fspath(path)) from exc
    current = root
    for part in parts:
        expected = _directory_identity(current)
        with _bound_output_parent(current, expected):
            try:
                os.mkdir(part, 0o755)
            except FileExistsError:
                pass
            identity = _directory_identity(part)
        current = current / part
        reject_symlinks(root, current)
        if _directory_identity(current) != identity:
            raise OSError(errno.EBUSY, "generated directory changed during creation", os.fspath(current))
    return _directory_identity(path)


@contextmanager
def _bound_output_parent(path, expected):
    """Run relative pathname operations inside the planned parent directory.

    A no-follow directory descriptor binds the write to the authorized parent.
    A final logical-path check makes a parent renamed before entry a conflict.
    """
    path = os.fspath(path)
    if expected is None:
        raise OSError(errno.ENOENT,
                      "generated output parent was absent during planning",
                      path)
    parent_fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    previous_fd = None
    try:
        opened = os.fstat(parent_fd)
        if ((opened.st_dev, opened.st_ino, stat.S_IFMT(opened.st_mode))
                != expected or not stat.S_ISDIR(opened.st_mode)):
            raise OSError(errno.EBUSY,
                          "generated output parent changed after planning",
                          path)
        previous_fd = os.open(".", os.O_RDONLY | os.O_DIRECTORY)
        os.fchdir(parent_fd)
        if _directory_identity(path) != expected:
            raise OSError(errno.EBUSY,
                          "generated output parent changed after planning",
                          path)
        yield
    finally:
        if previous_fd is not None:
            os.fchdir(previous_fd)
            os.close(previous_fd)
        os.close(parent_fd)


def _publish_bound(name, content, expected):
    """Publish inside a parent already bound as the current directory."""
    stage_parent = os.curdir
    # Python 3.12+ makes mkdtemp's result absolute even when ``dir`` is
    # relative. Keep only the newly created leaf so cleanup remains anchored
    # to this bound directory if its logical pathname is renamed meanwhile.
    stage_dir = os.path.basename(tempfile.mkdtemp(
        prefix=".plugin-build-stage-", dir=stage_parent))
    keep_stage = False
    try:
        staged = os.path.join(stage_dir, name)
        mode = expected[2] if expected is not None else 0o644
        with open(staged, "xb") as output:
            output.write(content)
            atomic_move.set_private_mode(output, mode)
            output.flush()
            os.fsync(output.fileno())
        try:
            if expected is None:
                return atomic_move.publish_new(
                    staged,
                    name,
                    _stable_output_snapshot,
                    stage_parent,
                    recovery_prefix=".plugin-build-recovery-",
                )
            return atomic_move.replace_expected(
                staged,
                name,
                expected,
                _stable_output_snapshot,
                stage_dir,
                stage_parent=stage_parent,
                recovery_prefix=".plugin-build-recovery-",
            )
        except OSError as exc:
            keep_stage = bool(getattr(exc, "keep_stage", False))
            raise
    finally:
        if not keep_stage:
            shutil.rmtree(stage_dir, ignore_errors=True)


def _remove_bound(name, published):
    """Remove exactly one publication inside the already-bound parent."""
    stage_parent = os.curdir
    stage_dir = os.path.basename(tempfile.mkdtemp(
        prefix=".plugin-build-rollback-", dir=stage_parent))
    keep_stage = False
    try:
        try:
            return atomic_move.remove_expected(
                name,
                published,
                _stable_output_snapshot,
                stage_dir,
                stage_parent,
                recovery_prefix=".plugin-build-recovery-",
            )
        except OSError as exc:
            keep_stage = bool(getattr(exc, "keep_stage", False))
            raise
    finally:
        if not keep_stage:
            shutil.rmtree(stage_dir, ignore_errors=True)


def _publish_generated(root, path, content, expected, expected_parent=None):
    """Publish generated bytes only over the exact output seen at planning."""
    root = Path(os.path.abspath(root))
    path = Path(os.path.abspath(path))
    reject_symlinks(root, path)
    if expected_parent is None:
        expected_parent = _directory_identity(path.parent)
    with _bound_output_parent(path.parent, expected_parent):
        # Relative names stay bound to the verified parent even if its logical
        # pathname is renamed after the guard's final check.
        published = _publish_bound(path.name, content, expected)
        try:
            if _directory_identity(path.parent) != expected_parent:
                raise OSError(errno.EBUSY,
                              "generated output parent changed during publication",
                              os.fspath(path.parent))
        except OSError as parent_exc:
            try:
                if expected is None:
                    _remove_bound(path.name, published)
                else:
                    _publish_bound(path.name, expected[4], published)
            except OSError as rollback_exc:
                raise OSError(
                    getattr(parent_exc, "errno", None) or errno.EBUSY,
                    "%s; rollback could not restore the planned output: %s" %
                    (parent_exc, rollback_exc),
                    os.fspath(path),
                ) from parent_exc
            raise
        return published


def _observe_bound_output(root, path, expected_parent):
    """Snapshot an output through its planned, bound parent directory."""
    root = Path(os.path.abspath(root))
    path = Path(os.path.abspath(path))
    reject_symlinks(root, path)
    with _bound_output_parent(path.parent, expected_parent):
        snapshot = _observe_output(path.name)
        if _directory_identity(path.parent) != expected_parent:
            raise OSError(errno.EBUSY,
                          "generated output parent changed while reading",
                          os.fspath(path.parent))
        return snapshot


def _verify_generated_outputs(root, outputs, observed_parents):
    """Return stable snapshots only when every output matches computed bytes."""
    verified = {}
    for path, content in outputs.items():
        snapshot = _observe_bound_output(
            root, path, observed_parents[path])
        if not _snapshot_matches(snapshot, content):
            raise OSError(errno.EBUSY,
                          "generated output does not match computed bytes",
                          os.fspath(path))
        verified[path] = snapshot
    return verified


def _publish_outputs(root, outputs, observed, observed_parents, validate_inputs=None):
    """Publish generated files and conditionally undo a partial group."""
    stale = [path for path, content in outputs.items()
             if not _snapshot_matches(observed[path], content)]

    # The snapshots authorize the complete derived group. Revalidate every member
    # and parent before exposing the first new byte.
    for path in outputs:
        if (_observe_bound_output(root, path, observed_parents[path])
                != observed[path]):
            raise OSError(errno.EBUSY,
                          "generated output changed after planning",
                          os.fspath(path))

    published = []
    try:
        if validate_inputs is not None:
            validate_inputs()
        for path in stale:
            snapshot = _publish_generated(
                root, path, outputs[path], observed[path],
                observed_parents[path])
            published.append((path, snapshot))
        if validate_inputs is not None:
            validate_inputs()
        _verify_generated_outputs(root, outputs, observed_parents)
        return stale
    except (OSError, ValueError) as exc:
        # A concurrent build may have completed the remaining output after
        # this run observed it. Accept that convergence before undoing an
        # earlier publication that the successful build relied on.
        try:
            if validate_inputs is not None:
                validate_inputs()
            _verify_generated_outputs(root, outputs, observed_parents)
            return stale
        except (OSError, ValueError):
            pass
        rollback_errors = []
        for path, snapshot in reversed(published):
            try:
                previous = observed[path]
                if previous is None:
                    _remove_generated(path, snapshot, observed_parents[path])
                else:
                    _publish_generated(
                        root, path, previous[4], snapshot,
                        observed_parents[path])
            except (OSError, ValueError) as rollback_exc:
                rollback_errors.append("%s: %s" % (path, rollback_exc))
        if rollback_errors:
            raise OSError(
                getattr(exc, "errno", None) or errno.EBUSY,
                "%s; rollback could not restore %s" %
                (exc, "; ".join(rollback_errors)),
            ) from exc
        raise


def _remove_generated(path, published, expected_parent):
    """Conditionally restore an output's planned absence during rollback."""
    path = Path(os.path.abspath(path))
    with _bound_output_parent(path.parent, expected_parent):
        return _remove_bound(path.name, published)


def _codex_manifest_bytes(authored):
    """Derive host presentation fields from one authored plugin manifest."""
    manifest = json.loads(authored)
    name = manifest.get("name")
    if name not in PLUGIN_NAMES:
        raise ValueError("unknown plugin manifest name: %r" % name)
    presentation = {
        "knowledge": (
            "Build and maintain an Obsidian knowledge base",
            ["Organize my PDFs and clean my web clippings.",
             "Research queued topics and create missing wiki entries.",
             "Audit my wiki and rebuild its maps of content."]),
        "investments": (
            "Research buying opportunities and track investment theses",
            ["Research buying opportunities and write today's investment note.",
             "Review the outcomes of earlier buying recommendations."]),
    }
    subtitle, prompts = presentation[name]
    manifest["skills"] = "./skills/"
    manifest["interface"] = {
        "displayName": name.capitalize(),
        "shortDescription": subtitle,
        "longDescription": manifest["description"],
        "developerName": manifest["author"]["name"],
        "category": "Productivity",
        "capabilities": ["Read", "Write"],
        "defaultPrompt": prompts,
    }
    return (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def codex_manifest(root, plugin_name):
    """Keep each plugin's common metadata authored once."""
    if plugin_name not in PLUGIN_NAMES:
        raise ValueError("unknown plugin: %s" % plugin_name)
    path = root / "plugins" / plugin_name / ".claude-plugin/plugin.json"
    authored = _read_package_source(root, path)
    if json.loads(authored).get("name") != plugin_name:
        raise ValueError("authored plugin name disagrees with its package")
    return _codex_manifest_bytes(authored)


def package_files(root, plugin_name, *, snapshots=None):
    """Collect one independent runtime package from exact canonical sources."""
    maps = _package_inventory(root, snapshots)
    if plugin_name not in maps:
        raise ValueError("unknown plugin: %s" % plugin_name)
    files = {destination: _read_package_source(root, root / source, snapshots)
             for destination, source in maps[plugin_name].items()}
    if json.loads(files[".claude-plugin/plugin.json"]).get("name") != plugin_name:
        raise ValueError("authored plugin name disagrees with its package")
    files[".codex-plugin/plugin.json"] = _codex_manifest_bytes(
        files[".claude-plugin/plugin.json"])
    _validate_package_names(files)
    return files


def generated_outputs(root, *, snapshots=None):
    """Return all loose runtime files and reproducible archives to publish."""
    outputs = {}
    snapshots = {} if snapshots is None else snapshots
    maps = _package_inventory(root, snapshots)
    for name in PLUGIN_NAMES:
        files = package_files(root, name, snapshots=snapshots)
        _validate_distribution_tree(root, name, files)
        outputs.update({root / "plugins" / name / relative: content
                        for relative, content in files.items()
                        if maps[name].get(relative) != "plugins/%s/%s" % (name, relative)})
        outputs[root / (name + ".plugin")] = archive_bytes(files)
    return outputs


def archive_bytes(files):
    """Stable order, timestamps and modes make rebuilds byte-for-byte identical."""
    _validate_package_names(files)
    output = io.BytesIO()
    # Stored entries avoid zlib-version-dependent byte streams.  The plugin is
    # small enough that cross-host reproducibility is worth the size tradeoff.
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, content)
    return output.getvalue()


def _configure_utf8_stdio():
    """Keep Unicode paths and diagnostics writable on redirected streams."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (OSError, ValueError):
                pass


def main():
    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if generated files are stale; write nothing")
    args = parser.parse_args()
    root = ROOT
    try:
        sources = {}
        outputs = generated_outputs(root, snapshots=sources)
        paths = tuple(outputs)
        for path in paths:
            reject_symlinks(root, path)
        observed_parents = {
            path: _observe_parent(path.parent) for path in paths
        }
        if not args.check:
            for path in paths:
                if observed_parents[path] is None:
                    observed_parents[path] = _create_output_parent(
                        root, path.parent)
        observed = {
            path: (None if observed_parents[path] is None else
                   _observe_bound_output(root, path, observed_parents[path]))
            for path in paths
        }
    except (OSError, ValueError) as exc:
        parser.exit(2, "Cannot build plugin: %s\n" % exc)
    if args.check:
        try:
            _verify_sources(root, sources)
            current = {
                path: (None if observed_parents[path] is None else
                       _observe_bound_output(
                           root, path, observed_parents[path]))
                for path in outputs
            }
        except (OSError, ValueError) as exc:
            parser.exit(2, "Cannot check generated output: %s\n" % exc)
        stale = [path for path, content in outputs.items()
                 if not _snapshot_matches(current[path], content)]
        for path in stale:
            print("Stale or missing: " + str(path.relative_to(root)))
        if stale:
            print("Run python3 tools/build_plugin.py")
        else:
            print("Both plugin trees and archives match their canonical sources.")
        return int(bool(stale))
    try:
        stale = _publish_outputs(root, outputs, observed, observed_parents,
                                 validate_inputs=lambda: _verify_sources(root, sources))
        for path in stale:
            print("Built " + str(path.relative_to(root)))
    except (OSError, ValueError) as exc:
        parser.exit(2, "Cannot publish generated output: %s\n" % exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
