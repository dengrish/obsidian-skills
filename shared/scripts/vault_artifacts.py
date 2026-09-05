#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Portable inventories for vault PDFs and source-keyed figures.

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
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import unicodedata
from collections import defaultdict
from pathlib import Path

__all__ = [
    "ArtifactFinding",
    "PDFEntry",
    "PDFInventory",
    "PDFSelection",
    "FigureInventory",
    "portable_identity",
    "inventory_pdfs",
    "verify_selected_pdf",
    "source_stem_groups",
    "output_vault_root",
    "inventory_source_figures",
    "run_self_test",
]


def portable_identity(value):
    """NFC + Unicode case-fold identity, without changing stored spelling."""
    return unicodedata.normalize("NFC", os.fspath(value)).casefold()


def _sort_key(value):
    text = os.fspath(value).replace(os.sep, "/")
    return portable_identity(text), text


def _snapshot(item):
    return (
        item.st_dev,
        item.st_ino,
        item.st_size,
        getattr(item, "st_mtime_ns", int(item.st_mtime * 1e9)),
        getattr(item, "st_ctime_ns", int(item.st_ctime * 1e9)),
    )


def _is_pdf_name(name):
    return portable_identity(os.path.splitext(name)[1]) == ".pdf"


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
    """Inventory every ``.pdf`` directory entry below *root*.

    Directory symlinks are followed.  Physical identities are tracked per
    ancestor chain, which permits two distinct logical aliases of one subtree
    to remain visible while stopping a link back to an ancestor. A PDF-named
    symlink is an occupant even when dangling. If it targets a directory, the
    occupant is recorded and the directory is still traversed; otherwise a
    name such as ``archive.pdf`` could hide colliding PDFs below it and make a
    later uniqueness claim unsound. Other non-regular PDF-named entries are
    also retained and reported.

    Dot-prefixed entries and subtrees are skipped by default because consumer
    source scopes exclude vault internals such as ``.trash`` and ``.obsidian``.
    ``include_hidden=True`` is an explicit forensic inventory mode.
    """
    root_path = Path(os.path.abspath(os.path.expanduser(os.fspath(root))))
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
        return PDFInventory(str(root_path), [], findings, False)
    if not stat.S_ISDIR(root_stat.st_mode):
        finding("unreadable", root_path, "inventory root is not a directory")
        return PDFInventory(str(root_path), [], findings, False)

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
                    "directory symlink reaches an ancestor; recursive PDF "
                    "inventory is incomplete")
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
            pdf_named = _is_pdf_name(child.name)

            # A PDF-shaped symlink is a namespace occupant in its own right.
            # Record it before directory following, but do not let its suffix
            # hide a directory target: nested PDF basenames still participate
            # in the vault-wide namespace.
            if is_link and pdf_named:
                entries.append(PDFEntry(str(path), "symlink"))

            is_directory = stat.S_ISDIR(child_lstat.st_mode)
            if is_link:
                try:
                    target = child.stat(follow_symlinks=True)
                    is_directory = stat.S_ISDIR(target.st_mode)
                except FileNotFoundError:
                    # A broken non-PDF symlink owns no PDF basename and hides
                    # no traversable subtree, so it is harmless to this scope.
                    is_directory = False
                except OSError as exc:
                    is_directory = False
                    finding("unreadable", path,
                            "cannot inspect symlink target while inventorying "
                            "possible PDF subtrees: %s: %s" %
                            (type(exc).__name__, exc))
            if is_directory:
                walk(path, lineage)
                if pdf_named and not is_link:
                    entries.append(PDFEntry(str(path), "directory"))
                    finding("pdf-nonregular", path,
                            "PDF basename is occupied by a directory",
                            severity="warning")
                continue

            # The PDF-shaped symlink was already retained above. A regular,
            # dangling or non-directory target contributes no subtree and must
            # not be recorded a second time as a generic non-regular entry.
            if is_link and pdf_named:
                continue

            if not pdf_named:
                continue
            if stat.S_ISREG(child_lstat.st_mode):
                entries.append(PDFEntry(str(path), "regular"))
            else:
                entries.append(PDFEntry(str(path), "nonregular"))
                finding("pdf-nonregular", path,
                        "PDF basename is occupied by a non-regular file",
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
                        "directory contents changed during PDF inventory")

    walk(root_path, set())
    entries.sort(key=lambda entry: _sort_key(entry.path))
    findings.sort(key=lambda item: (_sort_key(item.path), item.kind))
    return PDFInventory(str(root_path), entries, findings, complete)


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


_STAGING_SUFFIX = re.compile(
    r"\.(?:tmp|temp|part|partial|download|crdownload)(?:\.\d+)?\Z", re.I)


def _looks_staging(relative):
    for part in relative.replace("\\", "/").split("/"):
        low = part.casefold()
        if low.startswith((".tmp", ".temp", ".trash")):
            return True
        if ".dltmp" in low or _STAGING_SUFFIX.search(low):
            return True
    return False


def _valid_stem(stem):
    value = os.fspath(stem)
    if not value or not value.strip(". ") or "\x00" in value or ".." in value:
        return False
    return not any(sep and sep in value for sep in {"/", "\\", os.sep, os.altsep})


def inventory_source_figures(images, stem):
    """Inventory one resolved source's loose ``[stem]_fig*`` namespace.

    Only unambiguous direct regular files can appear in ``candidates``.  The
    direct folder is checked by literal NFC/case-folded prefix, so shell glob
    characters in legacy source names have no special meaning.  Nested paths
    are inspected only to report violations of the flat-folder contract;
    nested symlink directories and recognizable private staging directories
    are never followed.
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
        staging = _looks_staging(relative)
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
                if _looks_staging(child_rel):
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
        staging = _looks_staging(relative)
        if stat.S_ISLNK(item.st_mode):
            if match:
                blocked.append(str(path))
                add("symlink-match", path,
                    "source-keyed occupant is a symlink, not a regular figure")
            elif staging:
                add("staging-residue", path,
                    "recognizable staging symlink in image folder",
                    severity="warning")
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
    pdfs.add_argument("--exclude-hidden", action="store_false",
                      dest="include_hidden", help=argparse.SUPPRESS)
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
