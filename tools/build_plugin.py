#!/usr/bin/env python3
"""Generate the Codex manifest and a reproducible, complete plugin archive."""

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


PACKAGE_ROOT_FILES = (
    ".gitattributes",
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "requirements.txt",
    "requirements-dev.txt",
)
PACKAGE_TREES = (".claude-plugin", "skills", "shared", "tests", "tools")
PACKAGE_INVENTORY = "tools/package-files.txt"
IGNORED_PACKAGE_FILES = {".DS_Store"}
IGNORED_PACKAGE_SUFFIXES = {".pyc", ".pyo"}
IGNORED_PACKAGE_DIRS = {"__pycache__"}
WINDOWS_RESERVED_STEMS = {
    "CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
    *("COM%d" % number for number in range(1, 10)),
    *("LPT%d" % number for number in range(1, 10)),
    *("COM%s" % number for number in "¹²³"),
    *("LPT%s" % number for number in "¹²³"),
}
WINDOWS_FORBIDDEN_CHARS = frozenset('<>:"\\|?*')


def _validate_package_names(files):
    """Reject archive names that collapse or cannot unpack portably."""
    owners = {}
    for name in files:
        if not isinstance(name, str) or not name:
            raise ValueError("plugin archive contains an empty or non-text path")
        if name.startswith("/") or "\\" in name:
            raise ValueError("plugin archive path is not portable: %r" % name)
        components = name.split("/")
        if any(component in ("", ".", "..") for component in components):
            raise ValueError("plugin archive path is not relative and normalized: %r" % name)
        for component in components:
            if component[-1:] in (" ", "."):
                raise ValueError(
                    "plugin archive path has a trailing space or dot: %r" % name)
            if any(ord(char) < 32 or char in WINDOWS_FORBIDDEN_CHARS
                   for char in component):
                raise ValueError(
                    "plugin archive path uses a Windows-forbidden character: %r" % name)
            stem = component.split(".", 1)[0].upper()
            if stem in WINDOWS_RESERVED_STEMS:
                raise ValueError(
                    "plugin archive path uses a Windows-reserved name: %r" % name)
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


def _package_inventory(root):
    """Read the exact package inventory and reject drift in either direction."""
    raw = _read_package_source(root, root / PACKAGE_INVENTORY)
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("%s is not UTF-8" % PACKAGE_INVENTORY) from exc
    names = decoded.splitlines()
    if not names or any(not name or name != name.strip() for name in names):
        raise ValueError(
            "%s must contain one nonblank normalized path per line" %
            PACKAGE_INVENTORY)
    if names != sorted(set(names)):
        raise ValueError(
            "%s must be sorted and contain no duplicates" % PACKAGE_INVENTORY)
    _validate_package_names(dict.fromkeys(names, b""))
    allowed_roots = set(PACKAGE_ROOT_FILES)
    for name in names:
        if (name not in allowed_roots
                and not any(name.startswith(tree + "/")
                            for tree in PACKAGE_TREES)):
            raise ValueError(
                "%s lists a path outside the package boundary: %s" %
                (PACKAGE_INVENTORY, name))
    missing_roots = sorted(allowed_roots - set(names))
    if missing_roots:
        raise ValueError(
            "%s omits required root files: %s" %
            (PACKAGE_INVENTORY, ", ".join(missing_roots)))

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
                raise ValueError(
                    "plugin package contains a non-regular path: %s" % relative)
            actual.add(relative.as_posix())
    listed_tree_files = {
        name for name in names
        if any(name.startswith(tree + "/") for tree in PACKAGE_TREES)
    }
    unlisted = sorted(actual - listed_tree_files)
    absent = sorted(listed_tree_files - actual)
    if unlisted or absent:
        details = []
        if unlisted:
            details.append("unlisted files: %s" % ", ".join(unlisted))
        if absent:
            details.append("missing files: %s" % ", ".join(absent))
        raise ValueError("%s is stale (%s)" %
                         (PACKAGE_INVENTORY, "; ".join(details)))
    return names


def reject_symlinks(root, path):
    """Keep source reads and generated writes inside a self-contained tree."""
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        try:
            item = os.lstat(current)
        except FileNotFoundError:
            continue
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        attributes = getattr(item, "st_file_attributes", 0)
        if (stat.S_ISLNK(item.st_mode)
                or bool(reparse and attributes & reparse)):
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

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
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

    # Native Windows can expose a stable file's permission and timestamp
    # metadata differently through path stat and handle stat. Compare each API
    # with itself across the read, and use the portable identity triple to bind
    # the path observations to the opened handle on both sides. Requiring the
    # complete lstat tuple to equal the complete fstat tuple produces false
    # race alarms even though neither view changed.
    identity = lambda item: (
        item.st_dev, item.st_ino, stat.S_IFMT(item.st_mode))
    if not (stable(before) == stable(after)
            and stable(opened_before) == stable(opened_after)
            and identity(before) == identity(opened_before)
            and identity(after) == identity(opened_after)):
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


def _read_package_source(root, path):
    """Read one allowlisted source without following a swapped leaf link."""
    reject_symlinks(root, path)
    snapshot = _stable_regular_snapshot(path, "package source")
    # Catch a directory-component substitution that happened during the read;
    # the bytes are discarded and can never reach the archive.
    reject_symlinks(root, path)
    return snapshot[4]


def _observe_output(path):
    """Return an exact output snapshot, or ``None`` for an unoccupied name."""
    if not os.path.lexists(path):
        return None
    return _stable_output_snapshot(path)


def _snapshot_matches(snapshot, content):
    """Compare generated bytes with a snapshot without rereading the path."""
    return bool(
        snapshot is not None
        and snapshot[3] == len(content)
        and snapshot[1] == hashlib.sha256(content).hexdigest()
        and snapshot[4] == content
    )


def _directory_identity(path):
    """Return one ordinary directory's no-follow filesystem identity."""
    path = os.fspath(path)
    item = os.lstat(path)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = getattr(item, "st_file_attributes", 0)
    if (not stat.S_ISDIR(item.st_mode)
            or stat.S_ISLNK(item.st_mode)
            or bool(reparse and attributes & reparse)):
        raise OSError(errno.ENOTDIR,
                      "generated output parent is a symlink, junction, or "
                      "non-directory", path)
    return item.st_dev, item.st_ino, stat.S_IFMT(item.st_mode)


def _observe_parent(path):
    """Return a directory identity, or ``None`` only when it is absent."""
    if not os.path.lexists(path):
        return None
    return _directory_identity(path)


def _create_output_parent(root, path):
    """Create one direct generated-output directory, then bind its identity."""
    root = Path(os.path.abspath(root))
    path = Path(os.path.abspath(path))
    if path.parent != root:
        raise OSError(errno.EPERM,
                      "generated output parent must be directly under plugin root",
                      os.fspath(path))
    reject_symlinks(root, path)
    try:
        os.mkdir(path, 0o755)
    except FileExistsError:
        pass                       # a racing builder may have created it
    reject_symlinks(root, path)
    return _directory_identity(path)


@contextmanager
def _bound_output_parent(path, expected):
    """Run relative pathname operations inside the planned parent directory.

    POSIX uses a no-follow directory descriptor. The fallback changes into the
    directory and verifies the resulting current-directory identity before any
    write; native Windows pins the process current directory during the block.
    A final logical-path check makes a parent renamed before entry a conflict.
    """
    path = os.fspath(path)
    if expected is None:
        raise OSError(errno.ENOENT,
                      "generated output parent was absent during planning",
                      path)
    fchdir = getattr(os, "fchdir", None)
    if callable(fchdir):
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        parent_fd = os.open(path, flags)
        previous_fd = None
        try:
            opened = os.fstat(parent_fd)
            if ((opened.st_dev, opened.st_ino, stat.S_IFMT(opened.st_mode))
                    != expected or not stat.S_ISDIR(opened.st_mode)):
                raise OSError(errno.EBUSY,
                              "generated output parent changed after planning",
                              path)
            previous_fd = os.open(
                ".", os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            fchdir(parent_fd)
            if _directory_identity(path) != expected:
                raise OSError(errno.EBUSY,
                              "generated output parent changed after planning",
                              path)
            yield
        finally:
            if previous_fd is not None:
                fchdir(previous_fd)
                os.close(previous_fd)
            os.close(parent_fd)
        return

    previous = os.getcwd()
    try:
        os.chdir(path)
        if (_directory_identity(".") != expected
                or _directory_identity(path) != expected):
            raise OSError(errno.EBUSY,
                          "generated output parent changed after planning",
                          path)
        yield
    finally:
        os.chdir(previous)


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
            atomic_move.set_private_mode(output, staged, mode)
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


def _publish_outputs(root, outputs, observed, observed_parents):
    """Publish the generated pair and conditionally undo a partial group."""
    stale = [path for path, content in outputs.items()
             if not _snapshot_matches(observed[path], content)]

    # The snapshots authorize the whole derived pair. Revalidate every member
    # and parent before exposing the first new byte.
    for path in outputs:
        if (_observe_bound_output(root, path, observed_parents[path])
                != observed[path]):
            raise OSError(errno.EBUSY,
                          "generated output changed after planning",
                          os.fspath(path))

    published = []
    try:
        for path in stale:
            snapshot = _publish_generated(
                root, path, outputs[path], observed[path],
                observed_parents[path])
            published.append((path, snapshot))
        _verify_generated_outputs(root, outputs, observed_parents)
        return stale
    except (OSError, ValueError) as exc:
        # A concurrent build may have completed the remaining output after
        # this run observed it. Accept that convergence before undoing an
        # earlier publication that the successful build relied on.
        try:
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
    """Derive Codex presentation metadata from exact authored bytes."""
    manifest = json.loads(authored)
    manifest["skills"] = "./skills/"
    manifest["interface"] = {
        "displayName": "Obsidian",
        "shortDescription": "Turn documents and clippings into a maintained Obsidian vault",
        "longDescription": manifest["description"],
        "developerName": manifest["author"]["name"],
        "category": "Productivity",
        "capabilities": ["Read", "Write"],
        "defaultPrompt": [
            "Organize the PDFs and process the web clippings in my Obsidian inbox.",
            "Summarize a research paper with its key figures in my Obsidian vault.",
            "Audit the wiki entries and rebuild my maps of content.",
        ],
    }
    return (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def codex_manifest(root):
    """Keep common metadata authored once; add only Codex presentation fields."""
    path = root / ".claude-plugin/plugin.json"
    return _codex_manifest_bytes(_read_package_source(root, path))


def package_files(root):
    """Collect the complete intentional package tree without local residue."""
    names = _package_inventory(root)
    files = {
        name: _read_package_source(root, root / name)
        for name in names
    }
    files[".codex-plugin/plugin.json"] = _codex_manifest_bytes(
        files[".claude-plugin/plugin.json"])
    _validate_package_names(files)
    return files


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
    """Keep paths and diagnostics writable through legacy Windows pipes."""
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
        paths = (root / ".codex-plugin/plugin.json", root / "obsidian.plugin")
        for path in paths:
            reject_symlinks(root, path)
        files = package_files(root)
        outputs = {
            root / ".codex-plugin/plugin.json":
                files[".codex-plugin/plugin.json"],
            root / "obsidian.plugin": archive_bytes(files),
        }
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
            print("Codex manifest and obsidian.plugin match the source tree.")
        return int(bool(stale))
    try:
        stale = _publish_outputs(root, outputs, observed, observed_parents)
        for path in stale:
            print("Built " + str(path.relative_to(root)))
    except (OSError, ValueError) as exc:
        parser.exit(2, "Cannot publish generated output: %s\n" % exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
