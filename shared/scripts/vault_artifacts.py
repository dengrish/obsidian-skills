#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Portable inventories for vault sources and source-keyed figures.

Obsidian resolves bare PDF links and image embeds by basename.  A literal
``Path.rglob`` or shell glob is not enough for that namespace: it can miss
case/NFC equivalents, directory symlinks, broken symlink occupants, nested
image residue, and an unreadable subtree.  This stdlib-only module is the one
implementation used by producers and consumers that need to prove a name is
unambiguous.

CLI examples::

    python3 vault_artifacts.py pdfs --vault /path/to/vault \
        --selected /path/to/vault/Sources/PDFs/Doe_Study_2025.pdf
    python3 vault_artifacts.py figures --images /path/to/vault/Sources/Images \
        --stem Doe_Study_2025
    python3 vault_artifacts.py --test

Both inventory commands print JSON.  ``pdfs --selected`` exits zero only when
the walk is complete and exactly one usable regular file (or symlink to one)
owns the selected portable basename.  ``figures`` exits zero only when the flat folder was read completely
and every source-keyed occupant is safe to consider; ``candidates`` contains
only direct, regular, non-staging files with an unambiguous portable name.
Warnings such as unrelated staging residue remain visible in ``findings`` but
do not turn a sound source inventory into a false absence.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

from portable_names import portable_identity

__all__ = [
    "ArtifactFinding",
    "PDFEntry",
    "PDFInventory",
    "SourceInventory",
    "PDFSelection",
    "FigureInventory",
    "portable_identity",
    "local_link_matches",
    "inventory_pdfs",
    "inventory_sources",
    "verify_selected_pdf",
    "source_stem_groups",
    "output_vault_root",
    "on_disk_spelling",
    "UnlistedFolderError",
    "inventory_source_figures",
    "looks_staging",
    "run_self_test",
]


def _sort_key(value):
    text = os.fspath(value).replace(os.sep, "/")
    return portable_identity(text), text


def local_link_matches(target, actual, *, note_dir="", allow_suffix=True):
    """Match a decoded local link path to one known vault-relative file.

    Accept a bare basename, a vault-relative or note-relative path, or a
    component-aligned shortest suffix. Never discard a wrong qualification.
    This is a lexical match, not an inventory/uniqueness or write-authority
    check; callers must separately prove the selected file has one owner.
    Ordinary Markdown paths use allow_suffix=False; shortest-suffix lookup is
    an Obsidian wikilink behavior.
    """
    def parts(value):
        # A folder's whitespace is part of its name. Trimming each component
        # can turn a wrongly qualified citation into ownership of another file.
        return value.replace("\\", "/").split("/")

    def collapse(pieces):
        result = []
        for piece in pieces:
            if piece in ("", "."):
                continue
            if piece == "..":
                if not result:
                    return None
                result.pop()
            else:
                result.append(portable_identity(piece))
        return result

    if not isinstance(target, str) or not isinstance(actual, str):
        return False
    target, actual = target.strip(), actual.strip()
    if (not target or not actual or target.startswith(("/", "\\"))
            or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target)
            or any(char in target for char in "\r\n\0")):
        return False
    wanted, known = parts(target), collapse(parts(actual))
    if not known or not wanted[-1]:
        return False
    # An explicit ./ or ../ prefix fixes the origin at the containing note.
    # It cannot also resolve from the vault root after removing the prefix.
    candidates = [collapse(parts(note_dir) + wanted)]
    if wanted[0] not in (".", ".."):
        candidates.append(collapse(wanted))
    for candidate in candidates:
        if candidate == known:
            return True
    # An explicit relative path cannot also mean an arbitrary suffix.
    return (allow_suffix and not any(piece in ("", ".", "..") for piece in wanted)
            and len(wanted) <= len(known)
            and [portable_identity(piece) for piece in wanted] == known[-len(wanted):])


def _snapshot(item):
    return (
        item.st_dev,
        item.st_ino,
        item.st_size,
        getattr(item, "st_mtime_ns", int(item.st_mtime * 1e9)),
        getattr(item, "st_ctime_ns", int(item.st_ctime * 1e9)),
    )


def _logical_path_key(path):
    # Preserve both case and Unicode spelling. On filesystems such as ext4,
    # NFC and NFD names can be distinct directory entries even though they
    # share a portable output stem. Actual filesystem aliases are compared
    # with samefile below, never inferred from text normalization.
    return os.path.abspath(os.fspath(path))


class ArtifactFinding:
    __slots__ = ("kind", "path", "message", "severity")

    def __init__(self, kind, path, message, severity="error"):
        self.kind = kind
        self.path = path
        self.message = message
        self.severity = severity

    def to_dict(self):
        return {"kind": self.kind, "path": self.path,
                "message": self.message, "severity": self.severity}


class PDFEntry:
    __slots__ = ("path", "kind")

    def __init__(self, path, kind):
        self.path = path
        self.kind = kind

    def to_dict(self):
        return {"path": self.path, "kind": self.kind}


class PDFInventory:
    __slots__ = ("root", "entries", "findings", "complete")

    def __init__(self, root, entries, findings, complete):
        self.root = root
        self.entries = entries
        self.findings = findings
        self.complete = complete

    @property
    def paths(self):
        return [Path(entry.path) for entry in self.entries]

    @property
    def groups(self):
        groups = defaultdict(list)
        for entry in self.entries:
            groups[portable_identity(os.path.basename(entry.path))].append(
                entry.path)
        return {
            key: sorted(paths, key=_sort_key)
            for key, paths in sorted(groups.items())
        }

    def to_dict(self):
        return {
            "kind": "pdfs",
            "root": self.root,
            "complete": self.complete,
            "pdfs": [entry.to_dict() for entry in self.entries],
            "groups": self.groups,
            "findings": [item.to_dict() for item in self.findings],
        }


class SourceInventory(PDFInventory):
    """PDF and Markdown basename owners, with the PDF inventory interface."""
    __slots__ = ()

    def to_dict(self):
        answer = super().to_dict()
        answer["kind"] = "sources"
        answer["sources"] = answer.pop("pdfs")
        return answer


class PDFSelection:
    __slots__ = ("inventory", "selected", "portable_basename", "matches",
                 "unique", "reason")

    def __init__(self, inventory, selected, portable_basename, matches, unique,
                 reason):
        self.inventory = inventory
        self.selected = selected
        self.portable_basename = portable_basename
        self.matches = matches
        self.unique = unique
        self.reason = reason

    def to_dict(self):
        answer = self.inventory.to_dict()
        answer["selection"] = {
            "selected": self.selected,
            "portable_basename": self.portable_basename,
            "matches": self.matches,
            "unique": self.unique,
            "reason": self.reason,
        }
        return answer


class FigureInventory:
    __slots__ = ("images", "stem", "candidates", "blocked_matches",
                 "findings", "complete", "safe")

    def __init__(self, images, stem, candidates, blocked_matches, findings,
                 complete, safe):
        self.images = images
        self.stem = stem
        self.candidates = candidates
        self.blocked_matches = blocked_matches
        self.findings = findings
        self.complete = complete
        self.safe = safe

    def to_dict(self):
        return {
            "kind": "figures",
            "images": self.images,
            "stem": self.stem,
            "prefix": self.stem + "_fig",
            "complete": self.complete,
            "safe": self.safe,
            "candidates": self.candidates,
            "blocked_matches": self.blocked_matches,
            "findings": [item.to_dict() for item in self.findings],
        }


def inventory_pdfs(root, *, include_hidden=False):
    """Inventory every portable PDF basename below *root*, without hiding owners."""
    return _inventory_sources(root, include_hidden=include_hidden,
                              extensions={".pdf"}, kind="pdf")


def inventory_sources(root, *, include_hidden=False):
    """Inventory PDF and Markdown owners for source-citation resolution.

    This is a namespace inventory, not permission to read or rewrite each
    source. Occupied directory/symlink names participate, and an unreadable
    subtree or cycle makes absence and uniqueness conclusions incomplete.
    """
    return _inventory_sources(root, include_hidden=include_hidden,
                              extensions={".pdf", ".md"}, kind="source")


def _inventory_sources(root, *, include_hidden, extensions, kind):
    """Shared traversal for selected source-file extensions.

    Directory symlinks are followed.  Physical identities are tracked per
    ancestor chain, which permits two distinct logical aliases of one subtree
    to remain visible while stopping a link back to an ancestor. A source-named
    symlink is an occupant even when dangling. If it targets a directory, the
    occupant is recorded and the directory is still traversed; otherwise a
    name such as ``archive.pdf`` could hide colliding sources below it and make a
    later uniqueness claim unsound. Other non-regular source-named entries are
    also retained and reported.

    Dot-prefixed entries and subtrees are skipped by default because consumer
    source scopes exclude vault internals such as ``.trash`` and ``.obsidian``.
    ``include_hidden=True`` is an explicit forensic inventory mode.
    """
    root_path = Path(os.path.abspath(os.path.expanduser(os.fspath(root))))
    inventory_type = PDFInventory if kind == "pdf" else SourceInventory
    label = "PDF" if kind == "pdf" else "source"
    entries = []
    findings = []
    complete = True

    def finding(kind, path, message, severity="error"):
        nonlocal complete
        findings.append(ArtifactFinding(kind, os.fspath(path), message, severity))
        if severity == "error" and kind in {
                "unreadable", "changed-during-inventory", "directory-cycle"}:
            complete = False

    try:
        root_stat = os.stat(root_path)
    except OSError as exc:
        finding("unreadable", root_path,
                "cannot read inventory root: %s: %s" %
                (type(exc).__name__, exc))
        return inventory_type(str(root_path), [], findings, False)
    if not stat.S_ISDIR(root_stat.st_mode):
        finding("unreadable", root_path, "inventory root is not a directory")
        return inventory_type(str(root_path), [], findings, False)

    def walk(directory, ancestors):
        try:
            before = os.stat(directory)
        except OSError as exc:
            finding("unreadable", directory,
                    "cannot stat directory: %s: %s" %
                    (type(exc).__name__, exc))
            return
        identity = before.st_dev, before.st_ino
        if identity in ancestors:
            finding("directory-cycle", directory,
                    "directory symlink reaches an ancestor; recursive %s "
                    "inventory is incomplete" % label)
            return
        try:
            with os.scandir(directory) as scan:
                children = list(scan)
        except OSError as exc:
            finding("unreadable", directory,
                    "cannot list directory: %s: %s" %
                    (type(exc).__name__, exc))
            return
        children.sort(key=lambda entry: _sort_key(entry.name))
        lineage = ancestors | {identity}
        for child in children:
            if not include_hidden and child.name.startswith("."):
                continue
            path = Path(child.path)
            try:
                child_lstat = child.stat(follow_symlinks=False)
            except OSError as exc:
                finding("unreadable", path,
                        "cannot inspect directory entry: %s: %s" %
                        (type(exc).__name__, exc))
                continue
            is_link = stat.S_ISLNK(child_lstat.st_mode)
            source_named = any(portable_identity(child.name).endswith(extension)
                               for extension in extensions)

            # A source-shaped symlink is a namespace occupant in its own right.
            # Record it before directory following, but do not let its suffix
            # hide a directory target: nested source basenames still participate
            # in the vault-wide namespace.
            if is_link and source_named:
                entries.append(PDFEntry(str(path), "symlink"))

            is_directory = stat.S_ISDIR(child_lstat.st_mode)
            if is_link:
                try:
                    target = child.stat(follow_symlinks=True)
                    is_directory = stat.S_ISDIR(target.st_mode)
                except FileNotFoundError:
                    # A broken non-source symlink owns no source basename and hides
                    # no traversable subtree, so it is harmless to this scope.
                    is_directory = False
                except OSError as exc:
                    is_directory = False
                    finding("unreadable", path,
                            "cannot inspect symlink target while inventorying "
                            "possible %s subtrees: %s: %s" %
                            (label, type(exc).__name__, exc))
            if is_directory:
                walk(path, lineage)
                if source_named and not is_link:
                    entries.append(PDFEntry(str(path), "directory"))
                    finding(kind + "-nonregular", path,
                            label + " basename is occupied by a directory",
                            severity="warning")
                continue

            # The source-shaped symlink was already retained above. A regular,
            # dangling or non-directory target contributes no subtree and must
            # not be recorded a second time as a generic non-regular entry.
            if is_link and source_named:
                continue

            if not source_named:
                continue
            if stat.S_ISREG(child_lstat.st_mode):
                entries.append(PDFEntry(str(path), "regular"))
            else:
                entries.append(PDFEntry(str(path), "nonregular"))
                finding(kind + "-nonregular", path,
                        label + " basename is occupied by a non-regular file",
                        severity="warning")
        try:
            after = os.stat(directory)
        except OSError as exc:
            finding("changed-during-inventory", directory,
                    "directory disappeared or became unreadable during "
                    "inventory: %s" % exc)
        else:
            if _snapshot(before) != _snapshot(after):
                finding("changed-during-inventory", directory,
                        "directory contents changed during %s inventory" % label)

    walk(root_path, set())
    entries.sort(key=lambda entry: _sort_key(entry.path))
    findings.sort(key=lambda item: (_sort_key(item.path), item.kind))
    return inventory_type(str(root_path), entries, findings, complete)


def _same_logical_or_file(first, second):
    if _logical_path_key(first) == _logical_path_key(second):
        return True
    try:
        return os.path.samefile(first, second)
    except (OSError, ValueError):
        return False


def _lexically_within(path, root):
    try:
        return os.path.commonpath(
            [os.path.abspath(os.fspath(path)), os.path.abspath(os.fspath(root))]
        ) == os.path.abspath(os.fspath(root))
    except (OSError, ValueError):
        return False


def verify_selected_pdf(vault_root, selected, *, inventory=None):
    """Return a vault-wide uniqueness decision for *selected*'s basename.

    An external selected path is allowed when exactly one usable vault pathname
    owns that basename; this supports a readable scratch copy of an encrypted
    source without inventing a second vault identity. A selected path lexically
    in the vault must itself be that sole occupant (path aliases are compared
    with ``samefile`` where the platform can establish them). A dangling link
    or link to a non-file remains an owner for collision reporting but cannot
    verify a processable source.
    """
    inv = inventory or inventory_pdfs(vault_root)
    selected_path = os.path.abspath(os.path.expanduser(os.fspath(selected)))
    basename = os.path.basename(selected_path)
    key = portable_identity(basename)
    matches = list(inv.groups.get(key, []))
    kinds = {entry.path: entry.kind for entry in inv.entries}
    if not inv.complete:
        unique = False
        reason = "vault PDF inventory is incomplete"
    elif len(matches) != 1:
        unique = False
        reason = ("no vault PDF owns this portable basename" if not matches
                  else "%d vault PDF pathnames share this portable basename"
                  % len(matches))
    elif (_lexically_within(selected_path, inv.root)
          and not _same_logical_or_file(selected_path, matches[0])):
        unique = False
        reason = "selected in-vault pathname is not the sole inventoried owner"
    elif kinds.get(matches[0]) in {"directory", "nonregular"}:
        unique = False
        reason = "the sole portable basename owner is not a file or symlink"
    elif kinds.get(matches[0]) == "symlink":
        try:
            target = os.stat(matches[0])
        except OSError:
            unique = False
            reason = "the sole portable basename owner is a dangling or unreadable symlink"
        else:
            unique = stat.S_ISREG(target.st_mode)
            reason = ("exactly one vault PDF pathname owns this portable basename"
                      if unique else
                      "the sole portable basename owner is a symlink to a non-file")
    else:
        unique = True
        reason = "exactly one vault PDF pathname owns this portable basename"
    return PDFSelection(inv, selected_path, key, matches, unique, reason)


def _selected_already_in_inventory(selected, inventoried):
    """True only when selected aliases an existing inventoried entry.

    Inventoried logical aliases are deliberately *not* collapsed with one
    another: two vault paths to one inode still create two bare-name owners.
    This helper is only for avoiding a false extra member when a caller's
    selected spelling is a case-insensitive or symlink alias of the same
    portable basename already returned by the inventory. A differently named
    link still owns its selected output stem, even when its inode is shared.
    """
    name = portable_identity(os.path.basename(selected))
    return any(name == portable_identity(os.path.basename(path))
               and _same_logical_or_file(selected, path)
               for path in inventoried)


def source_stem_groups(selected, vault_inventory=()):
    """Portable stem groups, preserving distinct inventoried logical names."""
    inventoried = []
    seen_inventory = set()
    for path in vault_inventory:
        path = Path(path)
        logical = _logical_path_key(path)
        if logical in seen_inventory:
            continue
        seen_inventory.add(logical)
        inventoried.append(path)
    combined = list(inventoried)
    seen_selected = set()
    for source in selected:
        source = Path(source)
        logical = _logical_path_key(source)
        if logical in seen_selected:
            continue
        seen_selected.add(logical)
        if _selected_already_in_inventory(source, inventoried):
            continue
        combined.append(source)
    groups = defaultdict(list)
    for source in combined:
        groups[portable_identity(source.stem)].append(source)
    return {
        key: sorted(paths, key=lambda path: _sort_key(str(path)))
        for key, paths in groups.items()
    }


def output_vault_root(out_dir):
    """Infer a vault only from logical canonical ``Sources/Images`` output.

    Existing case aliases on a case-insensitive filesystem still identify the
    canonical entries.  Merely spelling a new arbitrary scratch path
    ``sources/images`` does not opt it into vault behavior.
    """
    images = Path(os.path.abspath(os.path.expanduser(os.fspath(out_dir))))
    sources = images.parent
    exact = images.name == "Images" and sources.name == "Sources"
    if exact:
        return sources.parent
    if not os.path.lexists(images) or not os.path.lexists(sources):
        return None
    try:
        if (os.path.samefile(images, sources / "Images")
                and os.path.samefile(sources, sources.parent / "Sources")):
            return sources.parent
    except (OSError, ValueError):
        return None
    return None


class UnlistedFolderError(ValueError):
    """The folder cannot be listed, so the stored spelling is unconfirmed."""


def on_disk_spelling(path):
    """Return *path* with its basename as its folder stores it.

    A case- or normalization-insensitive filesystem opens a file under any
    portable-equivalent spelling, but a stem taken from a typed path must use
    the stored one.  A typed basename the folder lists exactly is kept.
    Otherwise the one listed name with the same portable identity that is the
    same file replaces it.  More than one such name raises ``ValueError``; an
    unreadable folder raises its subclass ``UnlistedFolderError``, so a caller
    may keep the typed name.  No such name leaves *path* unchanged.
    """
    path = os.path.abspath(os.path.expanduser(os.fspath(path)))
    directory, name = os.path.split(path)
    try:
        names = os.listdir(directory)
    except OSError as exc:
        raise UnlistedFolderError(
            "cannot list %r to read the stored spelling of %r: %s"
            % (directory, name, exc)) from exc
    if name in names:
        return path
    key = portable_identity(name)
    stored = []
    for entry in names:
        if portable_identity(entry) != key:
            continue
        try:
            if os.path.samefile(os.path.join(directory, entry), path):
                stored.append(entry)
        except (OSError, ValueError):
            continue
    if len(stored) > 1:
        raise ValueError("%r matches more than one stored name: %s"
                         % (path, ", ".join(sorted(stored, key=_sort_key))))
    return os.path.join(directory, stored[0]) if stored else path


_STAGING_SUFFIX = re.compile(
    r"\.(?:tmp|temp|part|partial|download|crdownload)(?:\.\d+)?\Z", re.I)


def looks_staging(relative):
    """Whether a folder-relative path has a recognizable staging name.

    A component is staging when it starts ``.tmp``, ``.temp`` or ``.trash``,
    contains ``.dltmp``, or ends in a download/temporary suffix
    (``.tmp``/``.temp``/``.part``/``.partial``/``.download``/``.crdownload``,
    optionally numbered). The figure inventory here and wiki-lint's
    image-folder findings share this one test.
    """
    for part in relative.replace("\\", "/").split("/"):
        low = part.casefold()
        if low.startswith((".tmp", ".temp", ".trash")):
            return True
        if ".dltmp" in low or _STAGING_SUFFIX.search(low):
            return True
    return False


def _valid_stem(stem):
    value = os.fspath(stem)
    # Separators are refused below, so `..` is unsafe only as a whole
    # fragment, which the strip already rejects: `Why... it matters` is fine.
    if not value or not value.strip(". ") or "\x00" in value:
        return False
    return not any(sep and sep in value for sep in {"/", "\\", os.sep, os.altsep})


def inventory_source_figures(images, stem):
    """Inventory one resolved source's loose ``[stem]_fig*`` namespace.

    Only unambiguous direct regular files can appear in ``candidates``.  The
    direct folder is checked by literal NFC/case-folded prefix, so shell glob
    characters in legacy source names have no special meaning.  Nested paths
    are inspected only to report violations of the flat-folder contract.  A
    symlinked directory directly in the folder has its direct entries listed
    once; deeper symlinks and recognizable private staging directories are
    never followed.
    """
    if not _valid_stem(stem):
        raise ValueError("stem must be one filename fragment, not a path")
    root = Path(os.path.abspath(os.path.expanduser(os.fspath(images))))
    prefix = portable_identity(os.fspath(stem) + "_fig")
    findings = []
    direct = []
    blocked = []
    complete = True

    def add(kind, path, message, severity="error"):
        nonlocal complete
        findings.append(ArtifactFinding(kind, os.fspath(path), message, severity))
        if kind in {"unreadable", "changed-during-inventory"}:
            complete = False

    try:
        root_before = os.stat(root)
        if not stat.S_ISDIR(root_before.st_mode):
            raise NotADirectoryError(str(root))
        with os.scandir(root) as scan:
            top = list(scan)
    except OSError as exc:
        add("unreadable", root, "cannot read image folder: %s: %s" %
            (type(exc).__name__, exc))
        return FigureInventory(str(root), os.fspath(stem), [], [], findings,
                               False, False)
    top.sort(key=lambda entry: _sort_key(entry.name))

    def matching_name(name):
        return portable_identity(name).startswith(prefix)

    def walk_nested(directory, relative, ancestors):
        nonlocal complete
        staging = looks_staging(relative)
        add("staging-residue" if staging else "nested-directory", directory,
            ("recognizable staging residue under the flat image folder"
             if staging else "directory is nested under the flat image folder"),
            severity="warning")
        if staging:
            return
        try:
            before = os.stat(directory)
            identity = before.st_dev, before.st_ino
            if identity in ancestors:
                add("directory-cycle", directory,
                    "nested directory reaches an ancestor; it is not a figure candidate",
                    severity="warning")
                return
            with os.scandir(directory) as scan:
                children = list(scan)
        except OSError as exc:
            add("unreadable", directory,
                "cannot inspect nested image residue: %s: %s" %
                (type(exc).__name__, exc))
            return
        children.sort(key=lambda entry: _sort_key(entry.name))
        lineage = ancestors | {identity}
        for child in children:
            path = Path(child.path)
            child_rel = relative + "/" + child.name
            try:
                item = child.stat(follow_symlinks=False)
            except OSError as exc:
                add("unreadable", path,
                    "cannot inspect nested image entry: %s: %s" %
                    (type(exc).__name__, exc))
                continue
            if stat.S_ISLNK(item.st_mode):
                if matching_name(child.name):
                    blocked.append(str(path))
                    add("nested-match", path,
                        "source-keyed image is nested/symlinked and cannot be consumed")
                else:
                    add("nested-symlink", path,
                        "symlink is nested under the flat image folder",
                        severity="warning")
                continue
            if stat.S_ISDIR(item.st_mode):
                walk_nested(path, child_rel, lineage)
                continue
            if matching_name(child.name):
                if looks_staging(child_rel):
                    add("staging-match", path,
                        "source-keyed staging artifact is excluded",
                        severity="warning")
                else:
                    blocked.append(str(path))
                    add("nested-match", path,
                        "source-keyed image is nested under the flat image folder")
        try:
            after = os.stat(directory)
        except OSError as exc:
            add("changed-during-inventory", directory,
                "nested directory changed during inventory: %s" % exc)
        else:
            if _snapshot(before) != _snapshot(after):
                add("changed-during-inventory", directory,
                    "nested directory contents changed during inventory")

    def inspect_symlink(path, relative):
        """Report a top-level link; list a linked directory's entries once."""
        try:
            target = os.stat(path)
        except (FileNotFoundError, NotADirectoryError):
            target = None
        except OSError as exc:
            if exc.errno != errno.ELOOP:
                add("unreadable", path, "cannot inspect symlink target: %s: %s"
                    % (type(exc).__name__, exc))
                return
            target = None
        if target is None or not stat.S_ISDIR(target.st_mode):
            add("nested-symlink", path,
                "symlink in the flat image folder is not a figure",
                severity="warning")
            return
        add("nested-symlink", path,
            "symlinked directory in the flat image folder; only its direct "
            "entries are inspected", severity="warning")
        if (target.st_dev, target.st_ino) == (root_before.st_dev,
                                              root_before.st_ino):
            add("directory-cycle", path,
                "symlink reaches the image folder itself", severity="warning")
            return
        try:
            with os.scandir(path) as scan:
                names = sorted((entry.name for entry in scan), key=_sort_key)
        except OSError as exc:
            add("unreadable", path, "cannot inspect symlinked directory: %s: %s"
                % (type(exc).__name__, exc))
            return
        for name in names:
            if not matching_name(name):
                continue
            if looks_staging(relative + "/" + name):
                add("staging-match", path / name,
                    "source-keyed staging artifact is excluded",
                    severity="warning")
            else:
                blocked.append(str(path / name))
                add("nested-match", path / name,
                    "source-keyed image sits in a symlinked directory under "
                    "the flat image folder")

    for child in top:
        path = Path(child.path)
        relative = child.name
        try:
            item = child.stat(follow_symlinks=False)
        except OSError as exc:
            add("unreadable", path, "cannot inspect image entry: %s: %s" %
                (type(exc).__name__, exc))
            continue
        match = matching_name(child.name)
        staging = looks_staging(relative)
        if stat.S_ISLNK(item.st_mode):
            if match:
                blocked.append(str(path))
                add("symlink-match", path,
                    "source-keyed occupant is a symlink, not a regular figure")
            elif staging:
                add("staging-residue", path,
                    "recognizable staging symlink in image folder",
                    severity="warning")
            else:
                inspect_symlink(path, relative)
            continue
        if stat.S_ISDIR(item.st_mode):
            if match:
                blocked.append(str(path))
                add("nonregular-match", path,
                    "source-keyed occupant is a directory, not a regular figure")
            walk_nested(path, relative, set())
            continue
        if not match:
            if staging:
                add("staging-residue", path,
                    "recognizable staging artifact in image folder",
                    severity="warning")
            continue
        if staging:
            blocked.append(str(path))
            add("staging-match", path,
                "source-keyed staging artifact is excluded",
                severity="warning")
        elif stat.S_ISREG(item.st_mode):
            direct.append(str(path))
        else:
            blocked.append(str(path))
            add("nonregular-match", path,
                "source-keyed occupant is not a regular figure")

    # The folder itself can change while its entries are classified.
    try:
        root_after = os.stat(root)
    except OSError as exc:
        add("changed-during-inventory", root,
            "image folder changed during inventory: %s" % exc)
    else:
        if _snapshot(root_before) != _snapshot(root_after):
            add("changed-during-inventory", root,
                "image folder contents changed during inventory")

    by_name = defaultdict(list)
    for path in direct + blocked:
        by_name[portable_identity(os.path.basename(path))].append(path)
    ambiguous = set()
    for paths in by_name.values():
        logical = sorted(set(paths), key=_sort_key)
        if len(logical) > 1:
            ambiguous.update(logical)
            add("ambiguous-name", logical[0],
                "portable-equivalent source figure names: %s" %
                ", ".join(logical))
    candidates = sorted((path for path in direct if path not in ambiguous),
                        key=_sort_key)
    blocked = sorted(set(blocked) | ambiguous, key=_sort_key)
    findings.sort(key=lambda item: (_sort_key(item.path), item.kind))
    safe = (complete and not blocked
            and not any(item.severity == "error" for item in findings))
    return FigureInventory(str(root), os.fspath(stem), candidates, blocked,
                           findings, complete, safe)


def run_self_test():
    """Exercise portable identities, traversal, selection and figure scope."""
    import contextlib
    import io
    from unittest import mock

    state = {"n": 0, "bad": 0}

    def check(label, got, want):
        state["n"] += 1
        if got != want:
            state["bad"] += 1
            print("FAIL %s -> %r, expected %r" % (label, got, want))

    def ok(label, condition):
        state["n"] += 1
        if not condition:
            state["bad"] += 1
            print("FAIL %s" % label)

    for target, actual, note_dir, expected in (
            ("Study.pdf", "Sources/PDFs/Study.pdf", "Articles", True),
            ("PDFs/Study.pdf", "Sources/PDFs/Study.pdf", "Articles", True),
            ("../Sources/PDFs/Study.pdf", "Sources/PDFs/Study.pdf", "Articles", True),
            ("./Sources/PDFs/Study.pdf", "Sources/PDFs/Study.pdf", "Articles", False),
            ("./Sources/PDFs/Study.pdf", "Sources/PDFs/Study.pdf", "", True),
            ("./sub/Study.pdf", "Articles/sub/Study.pdf", "Articles", True),
            ("../../Sources/PDFs/Study.pdf", "Sources/PDFs/Study.pdf", "Articles", False),
            ("Missing/Study.pdf", "Sources/PDFs/Study.pdf", "Articles", False),
            ("Other/PDFs/Study.pdf", "Sources/PDFs/Study.pdf", "Articles", False),
            ("Sources/PDFs/Study.pdf/", "Sources/PDFs/Study.pdf", "Articles", False),
            ("/Sources/PDFs/Study.pdf", "Sources/PDFs/Study.pdf", "Articles", False),
            ("https://example.org/Study.pdf", "Sources/PDFs/Study.pdf", "", False),
            ("Sources/PDFs/Other.pdf", "Sources/PDFs/Study.pdf", "", False),
            ("Sources/ PDFs/Study.pdf", "Sources/PDFs/Study.pdf", "Articles", False),
            ("Sources/PDFs /Study.pdf", "Sources/PDFs/Study.pdf", "Articles", False),
            ("Sources/ PDFs/Study.pdf", "Sources/ PDFs/Study.pdf", "Articles", True),
            ("pdfs/Cafe\u0301.pdf", "Sources/PDFs/Caf\u00e9.pdf", "Articles", True),
            ("sub/Study.pdf", "Articles/sub/Study.pdf", "Articles", True)):
        check("qualified local target: " + target,
              local_link_matches(target, actual, note_dir=note_dir), expected)

    check("staging names: prefixes, .dltmp, numbered suffixes, any component",
          [looks_staging(name) for name in (
              ".tmp-render/x.png", ".TEMP_x.png", ".trash/old.png",
              "Doe_X_2025_fig_1.png.dltmp", "a.dltmp.b.png",
              "Doe_X_2025_fig_1.png.part", "x.png.PARTIAL.2",
              "x.png.crdownload", "x.download", "sub\\y.tmp/fig.png")],
          [True] * 10)
    check("not staging: ordinary figures, inner suffixes and a newline",
          [looks_staging(name) for name in (
              "Doe_X_2025_fig_1.png", "tmp.png", "x.tmp.png", "temporal.png",
              "partial_fig.png", "sub/fig.png", "x.tmp\n", "")],
          [False] * 8)

    tmp = tempfile.mkdtemp(prefix="vault-artifacts-selftest-")
    try:
        vault = Path(tmp) / "vault"
        pdfs = vault / "Sources" / "PDFs"
        images = vault / "Sources" / "Images"
        pdfs.mkdir(parents=True)
        images.mkdir()
        selected = pdfs / "García_Study_2025.pdf"
        selected.write_bytes(b"%PDF fixture")
        nested = pdfs / "nested"
        nested.mkdir()
        other = nested / "Other_Work_2024.PDF"
        other.write_bytes(b"%PDF fixture")

        inv = inventory_pdfs(vault)
        check("recursive PDF inventory is complete", inv.complete, True)
        check("recursive PDF inventory includes extension case variants",
              [p.name for p in inv.paths],
              ["García_Study_2025.pdf", "Other_Work_2024.PDF"])
        check("portable PDF groups normalize and fold",
              inv.groups[portable_identity("Garci\u0301a_Study_2025.PDF")],
              [str(selected)])
        decision = verify_selected_pdf(vault, selected, inventory=inv)
        check("one selected vault basename is unique", decision.unique, True)

        articles = vault / "Articles"
        articles.mkdir()
        article = articles / "García_Study_2025.md"
        article.write_text("Clipped source.\n", encoding="utf-8")
        markdown_collision = nested / "Garci\u0301a_Study_2025.MD"
        markdown_collision.write_text("Another source.\n", encoding="utf-8")
        ignored = articles / "unrelated.txt"
        ignored.write_text("Not a source citation.\n", encoding="utf-8")
        source_inv = inventory_sources(vault)
        check("source inventory includes PDFs and portable Markdown owners",
              set(source_inv.paths), {selected, other, article, markdown_collision})
        check("source inventory retains ambiguous Markdown basenames",
              len(source_inv.groups[portable_identity(article.name)]), 2)
        check("source inventory exposes its own result kind",
              (source_inv.to_dict()["kind"], len(source_inv.to_dict()["sources"])),
              ("sources", 4))
        check("PDF inventory does not acquire Markdown owners",
              set(inventory_pdfs(vault).paths), {selected, other})
        scan_sources = os.scandir
        def unreadable_articles(path):
            if Path(path) == articles:
                raise PermissionError("fixture: unreadable Articles")
            return scan_sources(path)
        with mock.patch.object(os, "scandir", unreadable_articles):
            blocked = inventory_sources(vault)
        check("unreadable Markdown tree blocks complete source ownership",
              (blocked.complete, any(f.kind == "unreadable" for f in blocked.findings)),
              (False, True))
        markdown_collision.unlink()
        article.unlink()
        ignored.unlink()
        articles.rmdir()

        hidden = vault / ".trash"
        hidden.mkdir()
        hidden_pdf = hidden / "Discarded_Study_2020.pdf"
        hidden_pdf.write_bytes(b"%PDF fixture")
        check("default consumer inventory excludes dot-prefixed vault trees",
              [p.name for p in inventory_pdfs(vault).paths],
              ["García_Study_2025.pdf", "Other_Work_2024.PDF"])
        check("forensic inventory can include dot-prefixed vault trees",
              "Discarded_Study_2020.pdf" in
              [p.name for p in inventory_pdfs(vault, include_hidden=True).paths],
              True)
        hidden_pdf.unlink()
        hidden.rmdir()

        collision_dir = vault / "Archive"
        collision_dir.mkdir()
        collision = collision_dir / "Garci\u0301a_Study_2025.PDF"
        collision.write_bytes(b"different")
        collision_inv = inventory_pdfs(vault)
        decision = verify_selected_pdf(vault, selected, inventory=collision_inv)
        check("NFC/case-equivalent PDF basename collides", decision.unique, False)
        check("both logical PDF owners are reported", len(decision.matches), 2)
        collision.unlink()
        collision_dir.rmdir()

        # A PDF-shaped dangling link still occupies the basename.
        dangling = pdfs / "Dangling_Study_2025.pdf"
        have_symlinks = True
        try:
            dangling.symlink_to(pdfs / "missing-target.pdf")
        except (OSError, NotImplementedError):
            have_symlinks = False
        link_inv = inventory_pdfs(vault)
        ok("dangling PDF symlink is an occupant (or symlinks unavailable)",
           not have_symlinks or str(dangling) in [str(path) for path in link_inv.paths])
        ok("a dangling PDF symlink cannot verify a selected source",
           not have_symlinks or not verify_selected_pdf(
               vault, Path(tmp) / dangling.name, inventory=link_inv).unique)

        # A directory link can itself own a PDF-shaped basename. Recording the
        # link and then stopping used to hide every PDF below it, including a
        # portable collision with the selected source.
        pdf_named_target = Path(tmp) / "pdf-named-link-target"
        pdf_named_target.mkdir()
        hidden_collision = pdf_named_target / "GARCÍA_STUDY_2025.PDF"
        hidden_collision.write_bytes(b"different")
        pdf_named_link = vault / "bundle.pdf"
        if have_symlinks:
            try:
                pdf_named_link.symlink_to(pdf_named_target,
                                          target_is_directory=True)
            except (OSError, NotImplementedError):
                have_pdf_named_dir_link = False
            else:
                have_pdf_named_dir_link = True
        else:
            have_pdf_named_dir_link = False
        pdf_named_inv = inventory_pdfs(vault)
        ok("a PDF-named directory symlink remains an occupant",
           not have_pdf_named_dir_link or any(
               entry.path == str(pdf_named_link) and entry.kind == "symlink"
               for entry in pdf_named_inv.entries))
        ok("a PDF-named directory symlink does not hide nested PDFs",
           not have_pdf_named_dir_link or str(pdf_named_link / hidden_collision.name)
           in [str(path) for path in pdf_named_inv.paths])
        ok("a collision below a PDF-named directory symlink blocks uniqueness",
           not have_pdf_named_dir_link or not verify_selected_pdf(
               vault, selected, inventory=pdf_named_inv).unique)
        if have_pdf_named_dir_link:
            pdf_named_link.unlink()

        nonregular_pdf = pdfs / "Not_A_File_2025.pdf"
        nonregular_pdf.mkdir()
        nonregular_inv = inventory_pdfs(vault)
        ok("a PDF-named non-regular occupant is retained and reported",
           any(entry.path == str(nonregular_pdf) and entry.kind == "directory"
               for entry in nonregular_inv.entries)
           and any(item.kind == "pdf-nonregular"
                   and item.path == str(nonregular_pdf)
                   for item in nonregular_inv.findings))
        check("a non-regular sole owner cannot verify an external selected PDF",
              verify_selected_pdf(
                  vault, Path(tmp) / nonregular_pdf.name,
                  inventory=nonregular_inv).unique, False)
        nonregular_pdf.rmdir()

        # Follow a directory link once, retain the logical alias, and refuse a
        # cycle instead of silently returning a partial walk.
        alias = vault / "LinkedPDFs"
        loop = pdfs / "loop"
        if have_symlinks:
            alias.symlink_to(nested, target_is_directory=True)
            loop.symlink_to(vault, target_is_directory=True)
        linked_inv = inventory_pdfs(vault)
        ok("directory symlink contents are inventoried",
           not have_symlinks or str(alias / other.name) in
           [str(path) for path in linked_inv.paths])
        ok("a symlink loop makes incompleteness explicit",
           not have_symlinks or (not linked_inv.complete and any(
               item.kind == "directory-cycle" for item in linked_inv.findings)))
        if have_symlinks:
            loop.unlink()
            alias.unlink()

        # Selected aliases are not added as phantom collision members, while
        # two aliases already present in the inventory remain two owners.
        inv = inventory_pdfs(vault)
        case_alias = pdfs / "GARCÍA_STUDY_2025.PDF"
        selected_alias = (case_alias if os.path.exists(case_alias)
                          else Path(tmp) / "GARCÍA_STUDY_2025.PDF")
        if have_symlinks:
            if selected_alias != case_alias:
                selected_alias.symlink_to(selected)
            groups = source_stem_groups([selected_alias], inv.paths)
            check("selected same-file alias does not false-collide",
                  len(groups[portable_identity(selected.stem)]), 1)
            renamed_alias = Path(tmp) / "Doe_Copy_2025.pdf"
            renamed_alias.symlink_to(selected)
            groups = source_stem_groups([renamed_alias], inv.paths)
            check("differently named same-file selection retains its output stem",
                  groups.get(portable_identity(renamed_alias.stem)),
                  [renamed_alias])
            renamed_alias.unlink()
            alias_inside = pdfs / "GARCÍA_STUDY_2025.PDF"
            if os.path.lexists(alias_inside):
                ok("inventoried-alias regression skipped when the filesystem "
                   "cannot hold both case spellings", True)
            else:
                alias_inside.symlink_to(selected)
                aliased_inv = inventory_pdfs(vault)
                groups = source_stem_groups([selected], aliased_inv.paths)
                check("two inventoried logical aliases remain a collision",
                      len(groups[portable_identity(selected.stem)]), 2)
                alias_inside.unlink()
            if selected_alias != case_alias:
                selected_alias.unlink()
        else:
            ok("selected-alias regression skipped without symlinks", True)
            ok("inventoried-alias regression skipped without symlinks", True)

        # Model names returned by a normalization-sensitive filesystem without
        # requiring this host to be able to create both spellings. Inventories
        # are observations of logical entries; their names must survive grouping.
        unicode_paths = [
            Path(tmp) / "unicode-inventory" / "Café_Study_2025.pdf",
            Path(tmp) / "unicode-inventory" / "Cafe\u0301_Study_2025.pdf",
        ]
        unicode_key = portable_identity(unicode_paths[0].stem)
        for label, selected_paths, inventoried_paths in (
                ("inventoried", unicode_paths[:1], unicode_paths),
                ("selected", unicode_paths, [])):
            groups = source_stem_groups(selected_paths, inventoried_paths)
            check("distinct NFC/NFD %s names remain a collision" % label,
                  len(groups[unicode_key]), 2)
        groups = source_stem_groups(unicode_paths, unicode_paths)
        check("exact selected paths are not double-counted with NFC/NFD owners",
              len(groups[unicode_key]), 2)

        # Simulate an unreadable subtree deterministically; chmod is not a
        # useful test when the suite runs as a privileged user.
        real_scandir = os.scandir

        def refuse_nested(path):
            if os.path.abspath(os.fspath(path)) == os.path.abspath(str(nested)):
                raise PermissionError("injected unreadable subtree")
            return real_scandir(path)

        with mock.patch.object(os, "scandir", side_effect=refuse_nested):
            incomplete = inventory_pdfs(vault)
        check("unreadable PDF subtree marks inventory incomplete",
              incomplete.complete, False)
        ok("unreadable PDF subtree is named",
           any(item.kind == "unreadable" and item.path == str(nested)
               for item in incomplete.findings))

        check("arbitrary output is not a vault",
              output_vault_root(Path(tmp) / "figure-output"), None)
        check("canonical image output implies its vault",
              output_vault_root(images), vault)
        lower_alias = vault / "Sources" / "images"
        if os.path.exists(lower_alias):
            check("case-insensitive alias still implies its vault",
                  output_vault_root(lower_alias), vault)
        else:
            ok("case-insensitive output-alias regression skipped on this filesystem", True)
        check("uncreated lowercase scratch spelling is not inferred as canonical",
              output_vault_root(Path(tmp) / "scratch" / "sources" / "images"), None)

        # A typed case or Unicode variant takes the folder's stored spelling.
        # The listing is mocked so every host runs the same cases.
        check("a stored basename keeps its typed spelling",
              on_disk_spelling(selected), str(selected))
        typed = str(pdfs / "garcía_study_2025.PDF")
        stored_nfd = "García_Study_2025.pdf"
        with mock.patch.object(os, "listdir", return_value=[stored_nfd, "x.pdf"]), \
                mock.patch.object(os.path, "samefile", return_value=True):
            check("a typed variant takes the stored spelling",
                  on_disk_spelling(typed), str(pdfs / stored_nfd))
        with mock.patch.object(os, "listdir", return_value=[stored_nfd]), \
                mock.patch.object(os.path, "samefile", return_value=False):
            check("an equivalent name that is another file is not the spelling",
                  on_disk_spelling(typed), typed)
        with mock.patch.object(os, "listdir",
                               return_value=[stored_nfd, "García_Study_2025.pdf"]), \
                mock.patch.object(os.path, "samefile", return_value=True):
            try:
                on_disk_spelling(typed)
                two_stored = None
            except ValueError as exc:
                two_stored = str(exc)
                two_stored_unlisted = isinstance(exc, UnlistedFolderError)
        ok("two stored names for one typed variant are refused",
           two_stored is not None and stored_nfd in two_stored)
        with mock.patch.object(os, "listdir", side_effect=PermissionError("injected")):
            try:
                on_disk_spelling(typed)
                unlisted = False
            except ValueError as exc:
                unlisted = isinstance(exc, UnlistedFolderError)
        ok("an unreadable folder cannot prove the stored spelling", unlisted)
        ok("only an unreadable folder raises UnlistedFolderError",
           two_stored is not None and not two_stored_unlisted)

        # Source figure matching is literal, loose at ``_fig``, portable, and
        # accepts any extension.  A glob metacharacter in a legacy stem remains
        # a literal character.
        for name in ("García_Study_2025_fig1.JPG",
                     "Garci\u0301a_Study_2025_FIG_2.webp",
                     "Other_Work_2024_fig_1.png"):
            (images / name).write_bytes(b"image")
        literal = images / "Study[1]_fig_1.png"
        literal.write_bytes(b"image")
        fig_inv = inventory_source_figures(images, "GARCÍA_STUDY_2025")
        check("flat figure inventory finds loose portable prefix",
              [Path(path).name for path in fig_inv.candidates],
              ["García_Study_2025_fig1.JPG",
               "Garci\u0301a_Study_2025_FIG_2.webp"])
        check("safe direct figures need no blocking findings", fig_inv.safe, True)
        check("glob metacharacters are literal",
              [Path(path).name for path in
               inventory_source_figures(images, "Study[1]").candidates],
              [literal.name])

        # A symlinked directory directly in the image folder is listed once,
        # so a source-keyed figure behind it blocks as a real nested one does.
        # A link back to the image folder is a cycle, not a second copy.
        linked_target = Path(tmp) / "linked-figures"
        linked_target.mkdir()
        (linked_target / "García_Study_2025_fig_6.png").write_bytes(b"image")
        (linked_target / "Other_Work_2024_fig_2.png").write_bytes(b"image")
        folder_link = images / "linked"
        self_link = images / "self"
        dangling_link = images / "gone"
        if have_symlinks:
            folder_link.symlink_to(linked_target, target_is_directory=True)
        linked_fig_inv = inventory_source_figures(images, "García_Study_2025")
        ok("a source-keyed figure behind a top-level directory symlink blocks",
           not have_symlinks or (
               linked_fig_inv.blocked_matches
               == [str(folder_link / "García_Study_2025_fig_6.png")]
               and not linked_fig_inv.safe
               and any(item.kind == "nested-symlink"
                       and item.path == str(folder_link)
                       for item in linked_fig_inv.findings)))
        if have_symlinks:
            folder_link.unlink()
            self_link.symlink_to(images, target_is_directory=True)
            dangling_link.symlink_to(Path(tmp) / "missing-folder")
        self_inv = inventory_source_figures(images, "García_Study_2025")
        ok("a top-level link to the image folder is a cycle, not a second copy",
           not have_symlinks or (
               self_inv.candidates == fig_inv.candidates
               and self_inv.blocked_matches == [] and self_inv.safe
               and any(item.kind == "directory-cycle"
                       and item.path == str(self_link)
                       for item in self_inv.findings)
               and any(item.kind == "nested-symlink"
                       and item.path == str(dangling_link)
                       and item.severity == "warning"
                       for item in self_inv.findings)))
        if have_symlinks:
            self_link.unlink()
            dangling_link.unlink()

        unrelated_nested = images / "archive"
        unrelated_nested.mkdir()
        (unrelated_nested / "Other_Work_2024_fig_9.png").write_bytes(b"image")
        unrelated_inv = inventory_source_figures(images, "García_Study_2025")
        ok("a fully read nested directory with no source match is report-only",
           unrelated_inv.safe and any(
               item.kind == "nested-directory"
               and item.path == str(unrelated_nested)
               and item.severity == "warning"
               for item in unrelated_inv.findings))

        staging = images / "García_Study_2025_fig_3.png.tmp"
        staging.write_bytes(b"partial")
        nested_images = images / "nested"
        nested_images.mkdir()
        nested_match = nested_images / "García_Study_2025_fig_4.png"
        nested_match.write_bytes(b"image")
        blocked_inv = inventory_source_figures(images, "García_Study_2025")
        ok("staging source match is excluded",
           str(staging) not in blocked_inv.candidates)
        ok("nested source match is reported and blocks a safe inventory",
           str(nested_match) in blocked_inv.blocked_matches and not blocked_inv.safe)
        ok("nested folder residue remains visible",
           any(item.kind == "nested-directory" for item in blocked_inv.findings))

        symlink_match = images / "García_Study_2025_fig_5.png"
        if have_symlinks:
            symlink_match.symlink_to(images / "missing.png")
        symlink_inv = inventory_source_figures(images, "García_Study_2025")
        ok("source-keyed symlink is never a candidate",
           not have_symlinks or (str(symlink_match) in symlink_inv.blocked_matches
                                 and str(symlink_match) not in symlink_inv.candidates))
        if have_symlinks:
            symlink_match.unlink()

        # Portable-equivalent direct names are ambiguous on a filesystem that
        # can hold both spellings.  Do not assume that property on every host.
        ambiguous = images / "GARCÍA_STUDY_2025_FIG1.jpg"
        try:
            ambiguous.write_bytes(b"other")
            can_hold_both = ambiguous.exists() and (
                ambiguous.stat().st_ino !=
                (images / "García_Study_2025_fig1.JPG").stat().st_ino)
        except OSError:
            can_hold_both = False
        amb_inv = inventory_source_figures(images, "García_Study_2025")
        ok("portable-equivalent figure names are blocked when host permits both",
           not can_hold_both or (not amb_inv.safe and any(
               item.kind == "ambiguous-name" for item in amb_inv.findings)))

        with mock.patch.object(os, "scandir", side_effect=PermissionError("injected")):
            unreadable = inventory_source_figures(images, "García_Study_2025")
        check("unreadable Images scope is incomplete",
              (unreadable.complete, unreadable.safe), (False, False))
        check("unreadable Images scope proves no candidates",
              unreadable.candidates, [])

        check("path-shaped source stem is rejected",
              _valid_stem("../escape"), False)
        check("ordinary source stem is accepted",
              _valid_stem("Doe_Study_2025_src"), True)
        check("an ellipsis inside a source stem is accepted",
              _valid_stem("Why... it matters"), True)
        check("a dots-only source stem is rejected",
              [_valid_stem(v) for v in ("..", "...", ". .")], [False] * 3)

        # An explicitly supplied empty value is still a selection request. It
        # must not fall through to the inventory-only success path merely
        # because an empty string is falsey in Python.
        with contextlib.redirect_stdout(io.StringIO()):
            empty_selection_code = main([
                "pdfs", "--vault", str(vault), "--selected", "",
            ])
        check("an empty --selected value cannot bypass uniqueness",
              empty_selection_code, 1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("%d/%d self-test cases pass" %
          (state["n"] - state["bad"], state["n"]))
    return 1 if state["bad"] else 0


def main(argv=None):
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (OSError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true", help="run self-tests")
    sub = parser.add_subparsers(dest="command")
    pdfs = sub.add_parser("pdfs", help="inventory portable PDF basenames")
    pdfs.add_argument("--vault", required=True, help="selected vault root")
    pdfs.add_argument("--selected", help="PDF whose basename must be unique")
    pdfs.add_argument("--include-hidden", action="store_true",
                      help="also inventory dot-prefixed files and subtrees")
    figures = sub.add_parser("figures", help="inventory one source's figures")
    figures.add_argument("--images", required=True,
                         help="flat Sources/Images folder")
    figures.add_argument("--stem", required=True,
                         help="resolved source filename without extension")
    args = parser.parse_args(argv)
    if args.test:
        return run_self_test()
    if args.command == "pdfs":
        inventory = inventory_pdfs(args.vault,
                                   include_hidden=args.include_hidden)
        has_selection = args.selected is not None
        result = (verify_selected_pdf(args.vault, args.selected,
                                      inventory=inventory)
                  if has_selection else inventory)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0 if (result.unique if has_selection else inventory.complete) else 1
    if args.command == "figures":
        try:
            result = inventory_source_figures(args.images, args.stem)
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0 if result.safe else 1
    parser.error("choose 'pdfs' or 'figures', or use --test")


if __name__ == "__main__":
    sys.exit(main())
