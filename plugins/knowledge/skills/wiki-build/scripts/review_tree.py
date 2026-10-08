#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""review_tree.py -- lint the Wiki as it would look after publication.

Builds step 7's private combined review tree and runs the baseline/overlay
diff in one call:

  1. Mirror: byte-copy (never hard-link) every readable regular ``.md`` entry
     of the real Wiki into ``<out>/<wiki-name>`` at the same relative path,
     skipping dot-directories and dot-files. Symlinks are never followed;
     symlinks, non-regular and unreadable paths are listed under
     ``unmirrored`` with a reason.
  2. Baseline: lint the mirror in folder mode.
  3. Overlay: copy each manifest draft whose ``path`` is under the Wiki folder
     (it must end in ``.md``) to its place in the tree. Other manifest paths
     are ignored with a note.
  4. Combined: lint the overlaid tree in folder mode (alias collisions, label
     targets and the other cross-entry checks) and classify every finding:
     ``on_staged`` (in a manifest file; ``inherited: true`` when the same
     finding was already on that path's baseline copy), ``introduced`` (in an
     unmodified file and absent from the baseline), or baseline (counted).
     Findings match the baseline by message, less any cross-entry count.
     A literal-dollar or backticked-identifier finding matches when the
     staged copy adds no occurrence, even if it has fewer.
  5. Links: body and Related wikilinks of each staged entry. ``dangling``
     lists a target that matches no entry of the combined tree by filename
     stem or alias, nor, when bare, a file stem in the vault's ``MOCs``
     folder (case/NFC-insensitive); a path-qualified target must spell an
     entry's Wiki-relative path, whole or its end, unless no entry has its
     basename and an alias claims it. ``noncanonical`` lists a target that
     resolves but not by its exact filename: ``case`` (one owner spelled
     differently), ``path`` (an explicit ``.md`` suffix, or a Wiki or folder
     path that no other vault file with the basename needs, CONVENTIONS
     section 6), ``alias`` (no Wiki file has the name, bare or ending a
     path, the target names no note outside the Wiki, and one entry claims
     it) or ``ambiguous`` (a name or path several
     entries share, a bare name shared by an entry and a MOC, or an owner
     unmirrored paths or unread aliases leave uncertain). A ``path``
     replacement keeps a path that another entry, a MOC, a note outside the
     Wiki or an unmirrored file or folder may need, and qualifies a bare
     link whose name an outside note shares. For ``case``, ``path``
     and ``alias``, ``replacement`` is the whole link to write, keeping its
     anchor and, in body prose, its displayed text; a Related-footer label
     becomes the owner's canonical title. An unmirrored ``.md`` file owns a
     bare name it shares, so an alias link to it is skipped. Any unmirrored
     path, or an entry whose aliases cannot be read, makes an ``alias``
     result ``ambiguous``, and an unmirrored folder does the same to a bare
     ``case`` result. Self-links stay lint's ``10-self-link``, and a bare
     MOC stem no entry shares is MOC navigation, left to wiki-lint.
     ``MOCs/...`` targets, embeds, links in code and anchors after ``#`` are
     ignored. A dangling link, or an ambiguous one an unmirrored path may
     own, lists under ``unmirrored`` the unmirrored file matching its stem
     (otherwise every unmirrored file and, for a dangling link, every entry
     whose aliases are unread) and every unmirrored folder it
     may live in; an unmirrored folder or unread alias list adds a note. A
     dangling link the path's baseline copy already had also lists every
     unread vault folder outside the Wiki, which adds a note too.
     ``non_entry`` lists a target that names no entry or MOC but a real
     vault note outside the Wiki and ``MOCs``, as wiki-lint's
     ``item10/non-entry`` resolves it: a bare basename, a ``./`` or ``../``
     path from the entry's folder, or a vault path, whole or its end. It is
     never ``dangling`` or ``alias``, since a real note outranks an alias;
     ``inherited: true`` marks a link the path's baseline copy already had.

The manifest is the shared publication manifest: a JSON list of
``{"path": "Wiki/<slug>.md", "draft": "<absolute draft path>"}`` objects with
vault-relative, forward-slash paths.

``--out`` must not exist, or must be a directory this tool created earlier
(it holds the ``.review-tree`` sentinel); anything else is refused, as is an
``--out`` inside the vault or containing it, and a draft inside ``--out``.
These checks compare folder identities, so a case or Unicode-normalization
variant of a path is still recognized. The tree is rebuilt from scratch on
every call, so every run takes a fresh baseline.

Module use:
    from review_tree import review
    report = review("/vault/Wiki", "/scratch/manifest.json", "/scratch/review")

CLI:
    review_tree.py --wiki '<vault>/Wiki' --manifest MANIFEST.json
        --out '<scratch>/review' [--vault VAULT] [--compact]

Output: {ok, clean, tree, staged[], on_staged[], introduced[],
baseline_count, dangling[], noncanonical[], non_entry[], unmirrored[],
notes[]}. A finding is {file, item, severity, message, evidence}; a
dangling link {file, section, target, unmirrored?}; a noncanonical link
{file, section, target, kind, replacement?, unmirrored?}; a non-entry link
{file, section, target, inherited?}. ``clean`` is true when on_staged,
introduced, dangling and noncanonical are all empty and every non_entry
link is inherited.

Exit codes: 0 the review ran (clean or not), 2 it could not run (bad usage,
refused ``--out``, unreadable manifest or draft, incomplete lint); 1 a
failed ``--test``.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import posixpath
import shutil
import stat
import sys

_OBSIDIAN_SHARED_MODULES = (
    'code_typography',
    'entry_checks',
    'entry_structure',
    'equation_coverage',
    'introduced_aliases',
    'markdown_tables',
    'naming',
    'note_provenance',
    'organism_names',
    'plurals',
    'portable_names',
    'slugify',
    'vault_artifacts',
    'yaml_scalars',
)

# --- obsidian shared-layer bootstrap (canonical; see shared/RUNTIME.md) ---
import os as _os, sys as _sys
_here = _os.path.dirname(_os.path.realpath(__file__))
_required = tuple(_m + ".py" for _m in (
    globals().get("_OBSIDIAN_SHARED_MODULES") or ("slugify",)))
_env = _os.environ.get("OBSIDIAN_VAULT_SHARED")
if _env:                                   # explicit override: authoritative, no fallback
    _tried = [_os.path.abspath(_os.path.expanduser(_env))]
else:                                      # plugin-relative walk-up, at most 5 levels
    _tried, _d = [], _here
    for _ in range(5):
        _tried.append(_os.path.join(_d, "shared", "scripts"))
        _d = _os.path.dirname(_d)
    _tried.append(_here)                   # extracted skill with co-located helpers
_missing = {_p: [_m for _m in _required if not _os.path.isfile(_os.path.join(_p, _m))]
            for _p in _tried if _os.path.isdir(_p)}
_shared = next((_p for _p in _tried if _p in _missing and not _missing[_p]), None)
if _shared is None:
    raise SystemExit("""obsidian: cannot find the plugin's shared/scripts/ folder, which holds
the one canonical copy of the conventions this script depends on. A usable
folder must contain these required module(s): %s
Looked for:
  %s
Fix: install the whole plugin tree, or set OBSIDIAN_VAULT_SHARED to the
shared/scripts/ directory (unset it to use the plugin-relative walk-up).
Do NOT paste a second copy of the algorithm into this skill -- a divergent
copy is the bug the shared layer exists to prevent.""" % (
    ", ".join(_required), "\n  ".join(
        _p + (" (not a directory)" if _p not in _missing else
              " (missing: %s)" % ", ".join(_missing[_p]))
        for _p in _tried)))
_sys.path[:] = [_p for _p in _sys.path if _p not in (_shared, _here)]
_sys.path.insert(0, _shared)               # shared/scripts/ FIRST
if _here != _shared:
    _sys.path.insert(1, _here)              # sibling modules before unrelated paths
# --- end bootstrap ---

from entry_structure import (  # noqa: E402
    mask_body_comments,
    mask_escaped_wikilinks,
    title_display_form,
)
from lint_entry import lint_path  # noqa: E402
from vault_index import (  # noqa: E402
    _WIKILINK_RE,
    extract_wikilinks,
    fold_name,
    index_entry,
    parse_frontmatter,
    split_sections,
)
from vault_artifacts import within_folder  # noqa: E402

__all__ = ["ReviewError", "review"]

SENTINEL = ".review-tree"


class ReviewError(Exception):
    """The review could not run; nothing it reports would be trustworthy."""


def _read_regular(path):
    """Bytes of a regular file, refusing a symlink or other occupant."""
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                         | getattr(os, "O_NONBLOCK", 0))
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError("not a regular file")
        with os.fdopen(descriptor, "rb") as fh:
            descriptor = None
            return fh.read()
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _write(path, data):
    """Create ``path`` exclusively inside the private review directory."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "xb") as fh:
        fh.write(data)


# --------------------------------------------------------------------------
# inputs
# --------------------------------------------------------------------------

def load_manifest(path, wiki_parts, out):
    """``(staged, notes)`` from the shared manifest.

    ``staged`` holds ``(vault-relative path, Wiki-relative path, draft
    bytes)`` for every manifest path under the Wiki folder, in manifest
    order. Every draft is read here, before the tree is touched, and none
    may lie inside ``out``, whose tree every run deletes.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            items = json.load(fh)
    except (OSError, ValueError) as exc:
        raise ReviewError("cannot read manifest %s: %s" % (path, exc))
    if not isinstance(items, list):
        raise ReviewError("manifest must be a JSON list of {path, draft} objects")
    staged, notes, seen = [], [], {}
    folded_wiki = [fold_name(part) for part in wiki_parts]
    for item in items:
        if not (isinstance(item, dict) and isinstance(item.get("path"), str)
                and isinstance(item.get("draft"), str)):
            raise ReviewError("manifest item %r is not a {path, draft} object"
                              % (item,))
        rel, draft = item["path"], item["draft"]
        parts = rel.split("/")
        if (not rel or "\\" in rel or rel.startswith("/")
                or any(part in ("", ".", "..") for part in parts)):
            raise ReviewError("manifest path %r must be vault-relative with "
                              "forward slashes and no '.', '..' or empty "
                              "segment" % rel)
        if fold_name(rel) in seen:
            raise ReviewError("manifest names %r and %r, one portable path"
                              % (seen[fold_name(rel)], rel))
        seen[fold_name(rel)] = rel
        if within_folder(draft, out):
            raise ReviewError("draft for %s lies inside --out %s, which each "
                              "run rebuilds; keep drafts elsewhere"
                              % (rel, out))
        if ([fold_name(part) for part in parts[:len(wiki_parts)]]
                != folded_wiki or len(parts) <= len(wiki_parts)):
            notes.append("ignored %s: outside %s/" % (rel, "/".join(wiki_parts)))
            continue
        inner = parts[len(wiki_parts):]
        if any(part.startswith(".") for part in inner):
            raise ReviewError("manifest path %r is hidden from the lint walk "
                              "(a dot-file or dot-directory)" % rel)
        if not inner[-1].lower().endswith(".md"):
            raise ReviewError("manifest path %r is not a .md entry, so lint "
                              "would never read it" % rel)
        if not os.path.isabs(draft):
            raise ReviewError("draft for %s must be an absolute path: %r"
                              % (rel, draft))
        try:
            data = _read_regular(draft)
        except OSError as exc:
            raise ReviewError("draft for %s cannot be read: %s: %s"
                              % (rel, draft, exc))
        staged.append((rel, "/".join(inner), data))
    return staged, notes


def prepare_out(out, tree_name, forbidden):
    """Create or reuse ``out`` and return a fresh, empty ``<out>/<tree_name>``."""
    for root in forbidden:
        if within_folder(out, root) or within_folder(root, out):
            raise ReviewError("--out %s overlaps the vault or Wiki (%s)"
                              % (out, root))
    try:
        info = os.lstat(out)
    except FileNotFoundError:
        try:
            os.mkdir(out, 0o700)
            _write(os.path.join(out, SENTINEL), b"review_tree.py\n")
        except OSError as exc:
            raise ReviewError("cannot create --out %s: %s" % (out, exc))
    else:
        if not stat.S_ISDIR(info.st_mode):
            raise ReviewError("--out %s exists and is not a directory" % out)
        try:
            marker = os.lstat(os.path.join(out, SENTINEL))
        except OSError:
            marker = None
        if marker is None or not stat.S_ISREG(marker.st_mode):
            raise ReviewError("--out %s exists but was not created by "
                              "review_tree.py (no %s file); choose a new path"
                              % (out, SENTINEL))
    tree = os.path.join(out, tree_name)
    try:
        if os.path.islink(tree) or os.path.isfile(tree):
            os.unlink(tree)
        elif os.path.isdir(tree):
            shutil.rmtree(tree)
        os.mkdir(tree)
    except OSError as exc:
        raise ReviewError("cannot rebuild %s: %s" % (tree, exc))
    return tree


def mirror_wiki(wiki, tree, prefix):
    """Byte-copy readable regular entries; ``(mirrored, unmirrored, folders)``.

    ``mirrored`` maps each copied entry's folded Wiki-relative path to its
    spelling. ``unmirrored`` lists symlinks, non-regular and unreadable paths;
    ``folders`` holds those that are folders (symlinked or unreadable). An
    unreadable Wiki folder raises ReviewError.
    """
    mirrored, unmirrored, folders = {}, [], []

    def skip(rel, reason, folder=False):
        unmirrored.append({"path": prefix + rel, "reason": reason})
        if folder:
            folders.append(prefix + rel)

    def walk(source, rel_dir):
        try:
            with os.scandir(source) as listing:
                items = sorted(listing, key=lambda item: item.name)
        except OSError as exc:
            if not rel_dir:
                raise ReviewError("cannot read %s: %s" % (wiki, exc))
            skip(rel_dir.rstrip("/"), "unreadable directory: %s" % exc, True)
            return
        for item in items:
            if item.name.startswith("."):
                continue
            rel = rel_dir + item.name
            try:
                mode = item.stat(follow_symlinks=False).st_mode
            except OSError as exc:
                skip(rel, "unreadable: %s" % exc)
                continue
            if stat.S_ISLNK(mode):
                skip(rel, "symlink; not followed", item.is_dir())
            elif stat.S_ISDIR(mode):
                walk(item.path, rel + "/")
            elif not stat.S_ISREG(mode):
                skip(rel, "not a regular file")
            elif item.name.lower().endswith(".md"):
                try:
                    data = _read_regular(item.path)
                except OSError as exc:
                    skip(rel, "unreadable: %s" % exc)
                    continue
                try:
                    _write(os.path.join(tree, *rel.split("/")), data)
                except OSError as exc:
                    skip(rel, "cannot copy: %s" % exc)
                    continue
                mirrored[fold_name(rel)] = rel

    walk(wiki, "")
    return mirrored, unmirrored, folders


# --------------------------------------------------------------------------
# review
# --------------------------------------------------------------------------

def _lint(tree, cache):
    report = lint_path(tree, cache=cache)
    if report["problems"]:
        raise ReviewError("lint could not read the review tree completely: %s"
                          % "; ".join(report["problems"]))
    return report


def _findings(report, tree):
    """``(Wiki-relative path, finding)`` for every lint finding."""
    for entry in report["entries"]:
        rel = os.path.relpath(entry["file"], tree).replace(os.sep, "/")
        for finding in entry["findings"]:
            yield rel, finding


def _occurrences(finding):
    """The counted occurrences behind a finding whose message counts them.

    A trim can remove some of a neighbor's literal dollars or backticked
    identifiers and leave the rest untouched, which changes the message.
    """
    evidence = finding.get("evidence") or {}
    if finding["item"] == "12-literal-dollar":
        return collections.Counter({"$": evidence.get("count", 0)})
    if evidence.get("check") == "backticked-identifiers":
        return collections.Counter(evidence.get("identifiers") or [])
    return None


def _match_key(rel, finding):
    """A finding's baseline identity: its message, less cross-entry counts.

    A staged draft can change how many entries claim an alias, or how many
    links reach one target, without touching the file that reports it.  A
    finding that counts occurrences is matched without its count;
    ``review`` then compares the occurrences themselves.
    """
    detail, evidence = finding["message"], finding.get("evidence") or {}
    if finding["item"] == "18-alias-collision":
        detail = (fold_name(evidence.get("alias", "")),
                  "filename slug" in detail)
    elif finding["item"] == "10-duplicate-wikilink":
        detail = evidence.get("target")
    elif _occurrences(finding) is not None:
        detail = evidence.get("check")
    return fold_name(rel), finding["item"], detail


def _moc_stems(vault):
    """Folded stems of the ``.md`` files in the vault's flat ``MOCs`` folder."""
    try:
        names = os.listdir(os.path.join(vault, "MOCs"))
    except OSError:
        return set()
    return {fold_name(name[:-3]) for name in names
            if name.lower().endswith(".md") and not name.startswith(".")}


def _outside_notes(vault, wiki):
    """``(paths, unread)`` for the vault's notes outside the Wiki and MOCs.

    ``paths`` holds the folded vault-relative paths, without ``.md``, of the
    ``.md`` notes elsewhere in the vault, such as ``Articles/`` reading
    notes, which also own a bare name. Dot-folders, the Wiki folder and the
    vault-root ``MOCs`` folder are skipped. Folder symlinks are followed, as
    Obsidian indexes them, with a loop guard; one that points back into the
    vault is not walked, because the real folder already covers its files.
    ``unread`` lists, sorted, the vault-relative folders that could not be
    read.
    """
    paths, unread = set(), set()
    seen = set()
    try:
        wiki_id = os.stat(wiki)
        wiki_id = (wiki_id.st_dev, wiki_id.st_ino)
    except OSError:
        wiki_id = None

    def failed(path):
        unread.add(os.path.relpath(path, vault).replace(os.sep, "/"))

    def skipped(dirpath, name):
        path = os.path.join(dirpath, name)
        if name.startswith(".") or (dirpath == vault
                                    and fold_name(name) == "mocs"):
            return True
        if os.path.islink(path) and within_folder(path, vault):
            return True
        try:
            info = os.stat(path)
        except OSError:
            return False
        return (info.st_dev, info.st_ino) == wiki_id

    for dirpath, dirnames, filenames in os.walk(
            vault, followlinks=True,
            onerror=lambda exc: failed(exc.filename or vault)):
        try:
            info = os.stat(dirpath)
        except OSError:
            failed(dirpath)
            dirnames[:] = []
            continue
        if (info.st_dev, info.st_ino) in seen:
            dirnames[:] = []
            continue
        seen.add((info.st_dev, info.st_ino))
        dirnames[:] = [name for name in dirnames
                       if not skipped(dirpath, name)]
        for name in filenames:
            if (not name.startswith(".") and name.lower().endswith(".md")
                    and os.path.isfile(os.path.join(dirpath, name))):
                rel = os.path.relpath(os.path.join(dirpath, name), vault)
                paths.add(fold_name(rel.replace(os.sep, "/")[:-3]))
    return paths, sorted(unread)


def _names_outside(target, outside, note=None):
    """Whether a link target names a vault note outside the Wiki and MOCs.

    ``outside`` holds those notes' folded vault-relative paths without
    ``.md`` and ``note`` the linking entry's vault-relative path. A bare
    target names a basename, a ``./`` or ``../`` target the path from the
    entry's folder, and any other target a vault path, whole or its end,
    as wiki-lint's ``item10/non-entry`` resolves it.
    """
    written = target.replace("\\", "/").strip().strip("/")
    if written.lower().endswith(".md"):
        written = written[:-3]
    if written.startswith(("./", "../")):
        if note is None:
            return False
        written = posixpath.normpath(posixpath.join(
            posixpath.dirname(note), written))
        return not written.startswith("../") and fold_name(written) in outside
    key = fold_name(written)
    if "/" not in key:
        return any(path.rsplit("/", 1)[-1] == key for path in outside)
    return key in outside or any(path.endswith("/" + key) for path in outside)


def _link_stem(target):
    """The folded filename stem a link names, or None when it is exempt."""
    key = target.replace("\\", "/").strip().strip("/")
    if not key or ("/" in key and fold_name(key.split("/", 1)[0]) == "mocs"):
        return None
    stem = key.rsplit("/", 1)[-1]
    if stem.lower().endswith(".md"):
        stem = stem[:-3]
    return fold_name(stem)


def _link_regions(text):
    """``(section, text)`` for an entry's body prose and Related footer."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    sections = split_sections(parse_frontmatter(text).body)
    return (("body", "\n".join(sections["prose_lines"])),
            ("related", sections["related_line"] or ""))


def _path_lookup(written, wiki_parts):
    """A path target's folded key, less a leading Wiki qualifier and ``.md``."""
    rest = _root_split(written.split("/"), wiki_parts)[1]
    if rest[-1].lower().endswith(".md"):
        rest[-1] = rest[-1][:-3]
    return fold_name("/".join(rest))


def dangling_links(text, known, mocs=(), paths=None, wiki_parts=("Wiki",),
                   outside=(), note=None):
    """``(section, target)`` for each unresolved body or Related wikilink.

    ``known`` holds entry stems and aliases; ``mocs`` holds MOC stems, which
    resolve only a bare target. ``paths`` holds the entries' folded
    Wiki-relative paths without ``.md``: when given, a path-qualified target
    (other than ``./`` or ``../``) resolves only to an entry whose path it
    spells whole or ends, less a leading Wiki qualifier, or, when no entry
    has its basename, to an alias of that name. A target that names a note
    in ``outside`` from the entry at ``note`` (``_names_outside``) is not
    dangling: ``non_entry_links`` lists it.
    """
    stems = (None if paths is None
             else {path.rsplit("/", 1)[-1] for path in paths})
    found = []
    for section, region in _link_regions(text):
        for target, _label in extract_wikilinks(region):
            stem = _link_stem(target)
            written = target.replace("\\", "/").strip().strip("/")
            bare = "/" not in written
            if stem is None or (section, target) in found:
                continue
            if bare or stems is None or written.startswith(("./", "../")):
                resolved = stem in known or (bare and stem in mocs)
            else:
                lookup = _path_lookup(written, wiki_parts)
                resolved = (lookup in paths
                            or any(path.endswith("/" + lookup)
                                   for path in paths)
                            or (stem not in stems and stem in known))
            if not resolved and not _names_outside(target, outside, note):
                found.append((section, target))
    return found


def non_entry_links(text, paths, mocs=(), wiki_parts=("Wiki",), outside=(),
                    note=None):
    """``(section, target)`` for each link to a vault note outside the Wiki.

    The target names no entry file, by stem or by ``dangling_links``'s path
    rule (``paths`` as there), nor, when bare, a MOC stem in ``mocs``, and
    it names a note in ``outside`` from the entry at ``note``
    (``_names_outside``). A real note outranks an alias, so an alias of the
    same name does not claim it.
    """
    stems = {path.rsplit("/", 1)[-1] for path in paths}
    found = []
    for section, region in _link_regions(text):
        for target, _label in extract_wikilinks(region):
            stem = _link_stem(target)
            written = target.replace("\\", "/").strip().strip("/")
            bare = "/" not in written
            if stem is None or (section, target) in found:
                continue
            if bare or written.startswith(("./", "../")):
                entry = stem in stems or (bare and stem in mocs)
            else:
                lookup = _path_lookup(written, wiki_parts)
                entry = (lookup in paths
                         or any(path.endswith("/" + lookup) for path in paths))
            if not entry and _names_outside(target, outside, note):
                found.append((section, target))
    return found


def _aliases_readable(path):
    """Whether a tree entry's alias ownership is fully known.

    Unreadable bytes or an unparsed title or aliases field can hide an alias;
    a readable plain note with no frontmatter claims none (vault_index's
    ``identity_complete`` holds both rules).
    """
    try:
        text = _read_regular(path).decode("utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return False
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return index_entry(path, text=text)["identity_complete"]


def _root_split(parts, wiki_parts):
    """``(prefix, rest)``: a leading Wiki-folder qualifier, as spelled on disk.

    Accepts the vault-relative Wiki path, the folder's own name or ``Wiki``,
    longest first, as the linters do.
    """
    for spelled in (list(wiki_parts), list(wiki_parts[-1:]), ["Wiki"]):
        size = len(spelled)
        if (len(parts) > size and [fold_name(part) for part in parts[:size]]
                == [fold_name(part) for part in spelled]):
            return spelled, parts[size:]
    return [], parts


def noncanonical_links(text, stems, alias_owners, mocs=(), own=None,
                       wiki_parts=("Wiki",), titles=None, unmirrored=(),
                       folders=(), aliases_complete=True, others=(),
                       others_complete=False):
    """Body and Related links that resolve, but not by the exact filename.

    ``stems`` maps each folded filename stem to the Wiki-relative paths
    (without ``.md``) that carry it, ``alias_owners`` each folded alias to
    its owners' paths, ``titles`` each such path to its entry's title, and
    ``mocs`` holds MOC stems. ``own`` is the linking entry's path: its
    self-links are lint's ``10-self-link``. ``wiki_parts`` spell the Wiki's
    vault-relative path, which qualifies a replacement whose bare name a MOC
    or another file shares. ``others`` holds the folded vault-relative
    paths, without ``.md``, of the vault's notes outside the Wiki and MOCs;
    ``others_complete`` is true when every vault folder was read. A target
    that names one of them (``_names_outside``) is no ``alias`` result: a
    real note outranks an alias, and ``non_entry_links`` lists the link.

    A ``path`` record drops an explicit ``.md`` suffix, and a Wiki or folder
    path once the inventory proves no other file owns the bare name: no
    other entry, MOC, unmirrored file or outside note has it, no folder is
    unmirrored, and ``others_complete`` holds. A bare link whose name an
    outside note shares takes the qualified path instead.

    ``unmirrored`` lists the unmirrored ``.md`` files and ``folders`` the
    unmirrored folders, as reported paths; ``aliases_complete`` is false
    when a tree entry's aliases could not be read. An unmirrored file owns
    a bare name it shares: an alias link to that name is skipped, and the
    name is ambiguous when a mirrored file also carries it. Any unmirrored
    path or unread alias list makes an ``alias`` result ambiguous, and an
    unmirrored folder does the same to a bare ``case`` result; those records
    list the unmirrored paths.

    Returns ``{section, target, kind, replacement?, unmirrored?}`` records;
    dangling targets, ``MOCs/...`` targets and bare MOC stems no entry
    shares are skipped. A replacement keeps the link's anchor and, in body
    prose, its displayed text; a Related-footer label becomes the owner's
    canonical title.
    """
    paths = {fold_name(path): path
             for owners in stems.values() for path in owners}
    titles = titles or {}
    folders = list(folders)
    occupants = {}
    for path in unmirrored:
        occupants.setdefault(
            fold_name(path.rsplit("/", 1)[-1][:-3]), []).append(path)
    unread = list(unmirrored) + folders
    aliases_complete = aliases_complete and not unread
    own = fold_name(own) if own else None
    other_stems = {path.rsplit("/", 1)[-1] for path in others}
    found = []

    def claim(stem):
        """``(kind, owner)`` for a name no file carries; None when dangling."""
        claimants = alias_owners.get(stem, set())
        if len(claimants) > 1:
            return "ambiguous", None
        if claimants:
            return "alias", next(iter(claimants))
        return None

    for section, region in _link_regions(text):
        visible = mask_escaped_wikilinks(
            mask_body_comments(region, mask_code=True))
        for match in _WIKILINK_RE.finditer(visible):
            parsed = extract_wikilinks(match.group(0))
            if not parsed or _link_stem(parsed[0][0]) is None:
                continue
            target, label = parsed[0]
            stem = _link_stem(target)
            head = match.group(1).split("|", 1)[0]
            if head.endswith("\\") and "|" in match.group(1):
                head = head[:-1]
            anchor = head[len(head.split("#", 1)[0].split("^", 1)[0]):].strip()
            written = target.replace("\\", "/").strip().strip("/")
            parts = written.split("/")
            suffix = parts[-1][-3:] if parts[-1].lower().endswith(".md") else ""
            parts[-1] = parts[-1][:len(parts[-1]) - len(suffix)]
            files = stems.get(stem, set())
            occupied = occupants.get(stem, [])
            kind = owner = None
            where = []
            prefix, rest = [], parts
            bare = len(parts) == 1
            if bare:
                if not files and not occupied:
                    if stem in mocs:
                        continue              # MOC navigation is wiki-lint's
                    if stem in other_stems:
                        continue              # a real note outranks an alias
                    kind, owner = claim(stem) or (None, None)
                    if kind is None:
                        continue              # dangling
                elif len(files) + len(occupied) + (stem in mocs) > 1:
                    kind, where = "ambiguous", (occupied + folders
                                                if occupied else [])
                elif occupied:
                    continue                  # the unmirrored file owns it
                else:                         # a file outranks an alias
                    owner = next(iter(files))
            elif written.startswith(("./", "../")):
                continue
            else:
                prefix, rest = _root_split(parts, wiki_parts)
                lookup = fold_name("/".join(rest))
                owners = ([paths[lookup]] if lookup in paths else
                          [path for key, path in paths.items()
                           if key.endswith("/" + lookup)])
                if len(owners) > 1:
                    kind = "ambiguous"
                elif owners:
                    owner = owners[0]
                elif not files and not occupied:
                    if _names_outside(target, others):
                        continue              # a real note outranks an alias
                    kind, owner = claim(stem) or (None, None)  # by basename
                    if kind is None:
                        continue              # dangling
                else:
                    continue                  # dangling_links reports it
            replacement = None
            if kind != "ambiguous":
                if fold_name(owner) == own:
                    continue
                if kind == "alias":
                    name = owner.rsplit("/", 1)[-1]
                    shared = (fold_name(name) in mocs
                              or fold_name(name) in other_stems
                              or len(stems.get(fold_name(name), ())) > 1)
                    dest = ("/".join(list(wiki_parts) + [owner]) if shared
                            else name)
                    if not aliases_complete:
                        kind, where = "ambiguous", unread
                else:
                    keep = "/".join(prefix + owner.split("/")[-len(rest):])
                    name = owner.rsplit("/", 1)[-1]
                    if bare:
                        dest = ("/".join(list(wiki_parts) + [owner])
                                if stem in other_stems else name)
                    elif (others_complete and not folders and not occupied
                          and len(files) == 1 and stem not in mocs
                          and stem not in other_stems):
                        dest = name           # no other file needs the path
                    else:
                        dest = keep
                    if dest == written:
                        continue
                    kind = "path" if suffix or dest != keep else "case"
                    if bare and folders:
                        kind, where = "ambiguous", folders
            if kind != "ambiguous":
                display = target if label is None else label
                if section == "related" and titles.get(owner):
                    display = title_display_form(titles[owner])
                replacement = (
                    "[[%s]]" % dest
                    if section == "body" and not anchor and display == dest
                    else "[[%s%s|%s]]" % (dest, anchor, display))
            record = {"section": section, "target": target, "kind": kind}
            if replacement is not None:
                record["replacement"] = replacement
            if where:
                record["unmirrored"] = list(where)
            if record not in found:
                found.append(record)
    return found


def review(wiki, manifest, out, vault=None):
    """Run the whole review and return its report; raise ReviewError."""
    wiki = os.path.abspath(wiki)
    vault = os.path.abspath(vault) if vault else os.path.dirname(wiki)
    if not os.path.isdir(vault):
        raise ReviewError("vault folder not found: %s" % vault)
    wiki_rel = os.path.relpath(wiki, vault)
    if wiki_rel == os.curdir or wiki_rel.split(os.sep)[0] == os.pardir:
        raise ReviewError("--wiki %s is not a folder inside the vault %s"
                          % (wiki, vault))
    wiki_parts = wiki_rel.split(os.sep)
    prefix = "/".join(wiki_parts) + "/"
    notes = []
    if os.path.lexists(wiki) and not os.path.isdir(wiki):
        raise ReviewError("--wiki %s is not a directory" % wiki)
    if not os.path.lexists(wiki):
        notes.append("%s does not exist yet; the mirror is empty" % prefix)

    out = os.path.abspath(out)
    staged, manifest_notes = load_manifest(manifest, wiki_parts, out)
    notes += manifest_notes
    tree = prepare_out(out, os.path.basename(wiki), [vault, wiki])
    mirrored, unmirrored, folders = (mirror_wiki(wiki, tree, prefix)
                                     if os.path.isdir(wiki) else ({}, [], []))
    if folders:
        notes.append("dangling and noncanonical links and alias collisions "
                     "are incomplete for entries that may live in unmirrored "
                     "folder(s): %s" % ", ".join(folders))

    # Files the overlay leaves unchanged keep their baseline single-file lint.
    cache = {}
    baseline, counted = collections.Counter(), {}
    for rel, finding in _findings(_lint(tree, cache), tree):
        key = _match_key(rel, finding)
        baseline[key] += 1
        if _occurrences(finding) is not None:
            counted[key] = _occurrences(finding)

    staged_paths, replaced = {}, {}
    for rel, inner, data in staged:
        existing = mirrored.get(fold_name(inner))
        if existing is not None and existing != inner:
            raise ReviewError(
                "manifest path %s differs only in case or Unicode "
                "normalization from existing %s%s; use one spelling"
                % (rel, prefix, existing))
        target = os.path.join(tree, *inner.split("/"))
        try:
            if os.path.lexists(target):
                with open(target, "rb") as fh:
                    replaced[rel] = fh.read()
                os.unlink(target)          # the mirrored copy it replaces
            _write(target, data)
        except OSError as exc:
            raise ReviewError("cannot overlay %s: %s" % (rel, exc))
        staged_paths[fold_name(inner)] = rel

    combined = _lint(tree, cache)
    on_staged, introduced, baseline_count = [], [], 0
    for rel, finding in _findings(combined, tree):
        key = _match_key(rel, finding)
        record ={"file": staged_paths.get(key[0], prefix + rel),
                  "item": finding["item"], "severity": finding["severity"],
                  "message": finding["message"],
                  "evidence": finding.get("evidence")}
        seen_before = baseline[key] > 0
        if seen_before and key in counted:
            # Fewer of the same occurrences is the old finding; any added
            # occurrence makes it new.
            seen_before = not (_occurrences(finding) - counted[key])
        if seen_before:
            baseline[key] -= 1
        if key[0] in staged_paths:
            if seen_before:
                record["inherited"] = True
            on_staged.append(record)
        elif seen_before:
            baseline_count += 1
        else:
            introduced.append(record)

    known, stems, alias_owners, titles, unread = set(), {}, {}, {}, []
    entry_paths = set()
    for entry in combined["entries"]:
        known.add(fold_name(os.path.splitext(os.path.basename(entry["file"]))[0]))
        known.update(fold_name(alias) for alias in entry.get("aliases") or [])
        rel = os.path.relpath(entry["file"], tree).replace(os.sep, "/")
        path = os.path.splitext(rel)[0]
        entry_paths.add(fold_name(path))
        stems.setdefault(fold_name(path.rsplit("/", 1)[-1]), set()).add(path)
        for alias in entry.get("aliases") or []:
            alias_owners.setdefault(fold_name(alias), set()).add(path)
        if entry.get("title"):
            titles[path] = entry["title"]
        if not _aliases_readable(entry["file"]):
            unread.append(staged_paths.get(fold_name(rel), prefix + rel))
    # Unmirrored entry files a staged draft does not replace.
    leaves = [item["path"] for item in unmirrored
              if item["path"] not in folders
              and item["path"].lower().endswith(".md")
              and fold_name(item["path"][len(prefix):]) not in staged_paths]
    if leaves or unread:
        notes.append("alias ownership is incomplete (aliases unread in: %s); "
                     "alias links are listed as ambiguous"
                     % ", ".join(leaves + unread))
    unmirrored_stems = {}
    for leaf in leaves:
        unmirrored_stems.setdefault(
            fold_name(leaf.rsplit("/", 1)[-1][:-3]), leaf)
    mocs, dangling, noncanonical, non_entry = _moc_stems(vault), [], [], []
    others, others_unread = _outside_notes(vault, wiki)
    if others_unread:
        notes.append("notes outside the Wiki are incomplete (unread "
                     "folder(s): %s); a dangling link the entry already had "
                     "may name a note there" % ", ".join(others_unread))
    for rel, inner, data in staged:
        text = data.decode("utf-8-sig", errors="replace")
        note = rel[:-3]
        # A link the path's baseline copy already had is the user's to keep.
        old = (replaced[rel].decode("utf-8-sig", errors="replace")
               if rel in replaced else "")
        before = non_entry_links(old, entry_paths, mocs, wiki_parts, others,
                                 note)
        kept = (dangling_links(old, known, mocs, entry_paths, wiki_parts,
                               others, note) if others_unread else [])
        for section, target in non_entry_links(text, entry_paths, mocs,
                                               wiki_parts, others, note):
            record = {"file": rel, "section": section, "target": target}
            if (section, target) in before:
                record["inherited"] = True
            non_entry.append(record)
        for section, target in dangling_links(text, known, mocs, entry_paths,
                                              wiki_parts, others, note):
            record = {"file": rel, "section": section, "target": target}
            occupant = unmirrored_stems.get(_link_stem(target))
            # A file outranks an alias; otherwise every unmirrored leaf and
            # every entry whose aliases are unread may own the name.
            where = ([occupant] if occupant else leaves + unread) + folders
            if (section, target) in kept:
                where += others_unread
            if where:
                record["unmirrored"] = where
            dangling.append(record)
        noncanonical += [dict({"file": rel}, **record) for record in
                         noncanonical_links(text, stems, alias_owners, mocs,
                                            own=os.path.splitext(inner)[0],
                                            wiki_parts=wiki_parts,
                                            titles=titles, unmirrored=leaves,
                                            folders=folders,
                                            aliases_complete=not unread,
                                            others=others,
                                            others_complete=not others_unread)]

    return {
        "ok": True,
        "clean": not (on_staged or introduced or dangling or noncanonical
                      or any(not r.get("inherited") for r in non_entry)),
        "tree": tree,
        "staged": [rel for rel, _inner, _data in staged],
        "on_staged": on_staged,
        "introduced": introduced,
        "baseline_count": baseline_count,
        "dangling": dangling,
        "noncanonical": noncanonical,
        "non_entry": non_entry,
        "unmirrored": unmirrored,
        "notes": notes,
    }


# --------------------------------------------------------------------------
# self-test
# --------------------------------------------------------------------------

def _st_entry(title, description, card, aliases=(), body="", related=""):
    """A lint-clean Concept entry; ``body`` extends its opening sentence."""
    lines = ['---', 'title: "%s"' % title, 'type: Concept']
    if aliases:
        lines += ['aliases:'] + ['  - "%s"' % alias for alias in aliases]
    opener = description.rstrip(".").replace(title, "**%s**" % title, 1)
    lines += [
        'sources:', '  - "[[Doe_X_2025.pdf#page=2]]"',
        'created: 2026-01-01', 'updated: 2026-01-02',
        'description: "%s"' % description,
        'tags:', '  - "#statistics"', 'parents: []', 'read: false',
        'issues: ""', '---',
        opener + "." + body, '', '**Related:**' + related, '', '---', '',
        '## Flashcards', '', card, '??', title, '']
    return "\n".join(lines)


def run_self_test():
    import contextlib
    import io
    import tempfile
    cases = []

    def check(label, got, want):
        cases.append((label, got == want, got, want))

    tmp = tempfile.mkdtemp(prefix="review_tree-selftest-")
    try:
        vault = os.path.join(tmp, "vault")
        wiki = os.path.join(vault, "Wiki")
        drafts = os.path.join(tmp, "drafts")
        elsewhere = os.path.join(tmp, "elsewhere")
        for folder in (os.path.join(wiki, "metrics"), os.path.join(wiki, ".trash"),
                       os.path.join(vault, "MOCs"), elsewhere, drafts):
            os.makedirs(folder)

        def put(path, text):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            return path

        precision = _st_entry(
            "Precision", "Precision is the share of predicted positives that "
            "are correct.", "The share of predicted positive cases that are "
            "correct.", aliases=["positive-predictive-value"])
        recall = _st_entry(
            "Recall", "Recall is the share of actual positives that a "
            "classifier finds.", "The share of actual positive cases that a "
            "classifier finds.")
        # The pre-existing finding: a description without its final period.
        recall = recall.replace("classifier finds.\"", "classifier finds\"")
        put(os.path.join(wiki, "precision.md"), precision)
        put(os.path.join(wiki, "recall.md"), recall)
        put(os.path.join(wiki, "metrics", "accuracy.md"), _st_entry(
            "Accuracy", "Accuracy is the share of all predictions that are "
            "correct.", "The share of all predictions that are correct."))
        put(os.path.join(wiki, ".trash", "old.md"), "hidden\n")
        put(os.path.join(wiki, "notes.txt"), "not an entry\n")
        outside = put(os.path.join(tmp, "outside.md"), precision)
        os.symlink(outside, os.path.join(wiki, "linked.md"))
        os.symlink(elsewhere, os.path.join(wiki, "synced"))
        put(os.path.join(vault, "MOCs", "statistics-moc.md"), "- [[recall]]\n")

        f1_body = (" It combines [[Precision]] with "
                   "[[recall#Definition|recall]] and is reported beside "
                   "[[metrics/accuracy|accuracy]], "
                   "[[positive-predictive-value|positive predictive value]], "
                   "[[missing-entry|a missing entry]], [[linked|a linked "
                   "note]], `[[in-code]]`, "
                   "[[Statistics-MOC|the statistics outline]] and "
                   "[[MOCs/Statistics|the statistics map]].\n\n"
                   "![[figure.png]]\n*The figure.*")
        f1_draft = put(os.path.join(drafts, "f1-score.md"), _st_entry(
            "F1 score", "F1 score is the harmonic mean of precision and "
            "recall.", "The harmonic mean of the two error-rate shares.",
            body=f1_body, related=" [[another-missing|Another missing]]"
        ).replace('recall."\n', 'recall"\n'))
        spec_draft = put(os.path.join(drafts, "specificity.md"), _st_entry(
            "Specificity", "Specificity is the share of actual negatives "
            "that are correctly rejected.", "The share of actual negative "
            "cases that are correctly rejected.",
            aliases=["positive-predictive-value"]))
        moc_draft = put(os.path.join(drafts, "Statistics.md"), "# Map\n")

        def manifest(name, pairs):
            return put(os.path.join(tmp, name), json.dumps(
                [{"path": path, "draft": draft} for path, draft in pairs]))

        first = manifest("first.json", [
            ("Wiki/f1-score.md", f1_draft), ("Wiki/specificity.md", spec_draft),
            ("MOCs/Statistics.md", moc_draft)])
        out = os.path.join(tmp, "review")
        report = review(wiki, first, out)
        tree = os.path.join(out, "Wiki")

        def items(records, path=None):
            return sorted({r["item"] for r in records
                           if path is None or r["file"] == path})

        check("the review runs and reports the tree", (
            report["ok"], report["tree"], report["staged"]),
            (True, tree, ["Wiki/f1-score.md", "Wiki/specificity.md"]))
        check("a staged draft's own finding is on_staged",
              "7-description" in items(report["on_staged"], "Wiki/f1-score.md"),
              True)
        check("an alias collision is on_staged for the staged draft",
              items(report["on_staged"], "Wiki/specificity.md"),
              ["18-alias-collision"])
        check("the collision on the unmodified entry is introduced",
              [(r["file"], r["item"]) for r in report["introduced"]],
              [("Wiki/precision.md", "18-alias-collision")])
        check("a pre-existing finding stays in the baseline",
              (report["baseline_count"] >= 1,
               "Wiki/recall.md" in {r["file"] for r in
                                    report["on_staged"] + report["introduced"]}),
              (True, False))
        check("dangling body and Related links are listed; code, embeds, "
              "MOCs, MOC stems, anchors, aliases, paths and case variants "
              "are not dangling; each names what it may live in",
              [(r["file"], r["section"], r["target"], r.get("unmirrored"))
               for r in report["dangling"]],
              [("Wiki/f1-score.md", "body", "missing-entry",
                ["Wiki/linked.md", "Wiki/synced"]),
               ("Wiki/f1-score.md", "body", "linked",
                ["Wiki/linked.md", "Wiki/synced"]),
               ("Wiki/f1-score.md", "related", "another-missing",
                ["Wiki/linked.md", "Wiki/synced"])])
        check("beside an unmirrored folder a bare case variant is ambiguous "
              "and names the folder; a shared alias is ambiguous; exact "
              "names, paths, anchors and MOC stems are not noncanonical",
              report["noncanonical"],
              [{"file": "Wiki/f1-score.md", "section": "body",
                "target": "Precision", "kind": "ambiguous",
                "unmirrored": ["Wiki/synced"]},
               {"file": "Wiki/f1-score.md", "section": "body",
                "target": "positive-predictive-value", "kind": "ambiguous"}])
        check("symlinks are unmirrored and dot/non-entry files are skipped",
              (report["unmirrored"], sorted(os.listdir(tree))),
              ([{"path": "Wiki/linked.md", "reason": "symlink; not followed"},
                {"path": "Wiki/synced", "reason": "symlink; not followed"}],
               ["f1-score.md", "metrics", "precision.md", "recall.md",
                "specificity.md"]))
        check("an outside manifest path, an unmirrored folder and an "
              "unmirrored entry file add notes",
              report["notes"], [
                  "ignored MOCs/Statistics.md: outside Wiki/",
                  "dangling and noncanonical links and alias collisions are "
                  "incomplete for entries that may live in unmirrored "
                  "folder(s): Wiki/synced",
                  "alias ownership is incomplete (aliases unread in: "
                  "Wiki/linked.md); alias links are listed as ambiguous"])
        check("the report is not clean", report["clean"], False)
        mirror = os.path.join(tree, "precision.md")
        check("the mirror is a byte copy, not a hard link", (
            open(mirror, "rb").read() == precision.encode("utf-8"),
            os.stat(mirror).st_ino == os.stat(
                os.path.join(wiki, "precision.md")).st_ino), (True, False))

        put(f1_draft, _st_entry(
            "F1 score", "F1 score is the harmonic mean of precision and "
            "recall.", "The harmonic mean of the two error-rate shares.",
            body=" It combines [[precision]] with [[recall]].",
            related=" [[precision|Precision]] · [[recall|Recall]]"))
        rerun = review(wiki, manifest("second.json",
                                      [("Wiki/f1-score.md", f1_draft)]), out)
        check("a rerun rebuilds the tree cleanly from a fresh baseline", (
            rerun["clean"], rerun["on_staged"], rerun["introduced"],
            rerun["dangling"], rerun["noncanonical"], rerun["baseline_count"],
            os.path.exists(os.path.join(tree, "specificity.md"))),
            (True, [], [], [], [], report["baseline_count"], False))

        inherited = review(wiki, manifest("third.json", [(
            "Wiki/recall.md", put(os.path.join(drafts, "recall.md"), recall))]),
            out)
        check("a replacement's unchanged finding is on_staged and inherited",
              [(r["file"], r["item"], r.get("inherited"))
               for r in inherited["on_staged"]],
              [("Wiki/recall.md", "7-description", True)])

        shrink_wiki = os.path.join(tmp, "shrink-vault", "Wiki")
        os.makedirs(shrink_wiki)

        def measure(name, aliases=()):
            return _st_entry(name, "%s is a test measure." % name,
                             "A test measure.", aliases=aliases)

        for name in ("Alpha", "Beta", "Gamma"):
            put(os.path.join(shrink_wiki, name.lower() + ".md"),
                measure(name, ["ppv"]))
        gamma = put(os.path.join(drafts, "gamma.md"), measure("Gamma"))
        shrunk = review(shrink_wiki, manifest(
            "shrink.json", [("Wiki/gamma.md", gamma)]),
            os.path.join(tmp, "shrink-review"))
        check("shrinking a three-way alias collision introduces nothing",
              (shrunk["on_staged"], shrunk["introduced"],
               shrunk["baseline_count"]), ([], [], 2))

        # An ownership-handoff trim leaves some of a neighbor's counted
        # faults untouched: fewer of the same occurrences stay inherited.
        count_wiki = os.path.join(tmp, "count-vault", "Wiki")
        os.makedirs(count_wiki)

        def voting(body):
            return _st_entry("Hard voting", "Hard voting picks the class most "
                             "models predict.", "The class most models "
                             "predict.", body=body)

        put(os.path.join(count_wiki, "hard-voting.md"), voting(
            " A vote costs $1 and reads `alpha`.\n\nA recount costs $2 or $3 "
            "and reads `beta`."))

        def counted_faults(name, body):
            result = review(count_wiki, manifest(name, [(
                "Wiki/hard-voting.md",
                put(os.path.join(drafts, "hard-voting.md"), voting(body)))]),
                os.path.join(tmp, "count-review"))
            return sorted((r["item"], r.get("inherited"))
                          for r in result["on_staged"]
                          if r["item"] in ("12-literal-dollar", "6-api-surface"))

        check("a trim that leaves fewer literal dollars and backticked "
              "identifiers keeps both findings inherited",
              counted_faults("trim.json", " A vote costs $1 and reads `alpha`."),
              [("12-literal-dollar", True), ("6-api-surface", True)])
        check("an added literal dollar is a new finding",
              counted_faults("grow.json", " A vote costs $1, $2, $3 or $4 and "
                             "reads `alpha` and `beta`."),
              [("12-literal-dollar", None), ("6-api-surface", True)])
        check("a swapped backticked identifier is a new finding",
              counted_faults("swap.json", " A vote costs $1 and reads `gamma`."),
              [("12-literal-dollar", True), ("6-api-surface", None)])

        canon_vault = os.path.join(tmp, "canon-vault")
        canon_wiki = os.path.join(canon_vault, "Wiki")
        for folder in ("metrics", "scores"):
            os.makedirs(os.path.join(canon_wiki, folder))
            put(os.path.join(canon_wiki, folder, "accuracy.md"), measure(
                "Accuracy"))
        os.makedirs(os.path.join(canon_vault, "MOCs"))
        put(os.path.join(canon_vault, "MOCs", "statistics.md"), "# Map\n")
        put(os.path.join(canon_wiki, "precision.md"), precision)
        put(os.path.join(canon_wiki, "statistics.md"),
            measure("Statistics", ["stats"]))
        canon_draft = put(os.path.join(drafts, "canon.md"), _st_entry(
            "F1 score", "F1 score is the harmonic mean of precision and "
            "recall.", "The harmonic mean of the two error-rate shares.",
            aliases=["f-score"], body=(
                " It uses [[positive-predictive-value|positive predictive "
                "value]], [[positive-predictive-value#Definition]], "
                "[[stats|statistics]], [[statistics|statistics]], "
                "[[Wiki/statistics|statistics]], [[wiki/statistics|"
                "statistics]], [[accuracy]], [[Metrics/Accuracy|accuracy]], "
                "[[scores/accuracy|accuracy]] and [[f-score|F-score]]."),
            related=" [[Precision|Precision]]"))
        canon = review(canon_wiki, manifest(
            "canon.json", [("Wiki/f1-score.md", canon_draft)]),
            os.path.join(tmp, "canon-review"))
        check("a one-owner alias becomes its owner's slug, path-qualified "
              "beside a same-named MOC, with anchor and display kept; "
              "a case variant keeps its path qualifier",
              [(r["section"], r["target"], r["kind"], r.get("replacement"))
               for r in canon["noncanonical"]],
              [("body", "positive-predictive-value", "alias",
                "[[precision|positive predictive value]]"),
               ("body", "positive-predictive-value", "alias",
                "[[precision#Definition|positive-predictive-value]]"),
               ("body", "stats", "alias", "[[Wiki/statistics|statistics]]"),
               ("body", "statistics", "ambiguous", None),
               ("body", "wiki/statistics", "case",
                "[[Wiki/statistics|statistics]]"),
               ("body", "accuracy", "ambiguous", None),
               ("body", "Metrics/Accuracy", "case",
                "[[metrics/accuracy|accuracy]]"),
               ("related", "Precision", "case", "[[precision|Precision]]")])
        check("a link to the entry's own alias stays lint's self-link, and "
              "noncanonical links keep the review from being clean",
              ("10-self-link" in items(canon["on_staged"], "Wiki/f1-score.md"),
               canon["dangling"], canon["clean"]), (True, [], False))

        def links_review(name, files, body, related="", links=()):
            """Review one draft whose ``body`` links into ``files``."""
            base = os.path.join(tmp, name)
            base_wiki = os.path.join(base, "vault", "Wiki")
            os.makedirs(base_wiki)
            for rel, text in files.items():
                os.makedirs(os.path.dirname(os.path.join(base_wiki, rel)),
                            exist_ok=True)
                put(os.path.join(base_wiki, rel), text)
            for rel, target in links:
                os.makedirs(os.path.dirname(os.path.join(base_wiki, rel)),
                            exist_ok=True)
                os.symlink(target, os.path.join(base_wiki, rel))
            draft = put(os.path.join(base, "f1-score.md"), _st_entry(
                "F1 score", "F1 score is the harmonic mean of precision and "
                "recall.", "The harmonic mean of the two error-rate shares.",
                body=body, related=related))
            result = review(base_wiki, manifest(
                name + ".json", [("Wiki/f1-score.md", draft)]),
                os.path.join(base, "review"))
            return result, [(r["section"], r["target"], r["kind"],
                             r.get("replacement"), r.get("unmirrored"))
                            for r in result["noncanonical"]]

        _leaf, leaf_links = links_review(
            "leaf", {"roc-curve.md": measure("ROC curve", ["roc"]),
                     "precision.md": measure("Precision", ["ppv"]),
                     "recall.md": measure("Recall")},
            " It uses [[roc]], [[recall]], [[Precision|precision]] and "
            "[[ppv|PPV]].",
            links=[("roc.md", outside), ("metrics/recall.md", outside)])
        check("an unmirrored file owns a bare name it shares: its alias link "
              "is skipped, one a mirrored file also carries is ambiguous, and "
              "an alias link is ambiguous while unmirrored aliases are unread",
              leaf_links,
              [("body", "recall", "ambiguous", None,
                ["Wiki/metrics/recall.md"]),
               ("body", "Precision", "case", "[[precision]]", None),
               ("body", "ppv", "ambiguous", None,
                ["Wiki/metrics/recall.md", "Wiki/roc.md"])])

        external = os.path.join(tmp, "external")
        os.makedirs(external)
        put(os.path.join(external, "rate-of-change.md"),
            measure("Rate of change", ["roc"]))
        put(os.path.join(external, "precision.md"), measure("Precision"))
        _folder, folder_links = links_review(
            "folder", {"roc-curve.md": measure("ROC curve", ["roc"]),
                       "precision.md": measure("Precision")},
            " It uses [[roc]], [[Precision|precision]] and [[precision]].",
            links=[("sub", external)])
        check("an unmirrored folder makes alias and bare case links "
              "ambiguous and names the folder",
              folder_links,
              [("body", "roc", "ambiguous", None, ["Wiki/sub"]),
               ("body", "Precision", "ambiguous", None, ["Wiki/sub"])])

        broken, broken_links = links_review(
            "broken", {"roc-curve.md": measure("ROC curve", ["roc"]),
                       "rate-of-change.md": measure(
                           "Rate of change", ["roc"]).replace(
                               'aliases:\n  - "roc"', 'aliases: ["roc"')},
            " It uses [[roc]] and [[tpr]].")
        check("an unparsed aliases field makes an alias link ambiguous and "
              "adds a note",
              (broken_links, broken["notes"]),
              ([("body", "roc", "ambiguous", None, None)],
               ["alias ownership is incomplete (aliases unread in: "
                "Wiki/rate-of-change.md); alias links are listed as "
                "ambiguous"]))
        check("a dangling link names the entry whose aliases are unread",
              [(r["target"], r.get("unmirrored")) for r in broken["dangling"]],
              [("tpr", ["Wiki/rate-of-change.md"])])

        _paths, path_links = links_review(
            "paths", {"precision.md": measure("Precision", ["ppv"]),
                      "recall.md": measure("Recall", ["tpr"]),
                      "sensitivity.md": measure("Sensitivity", ["tpr"]),
                      "notes.md": "# Notes\n"},
            " It uses [[Wiki/ppv|PPV]], [[metrics/tpr|TPR]] and [[ppv|PPV]].",
            related=" [[ppv|PPV]] · [[Recall|recall]]")
        check("a path-qualified alias follows the bare alias rule by "
              "basename, and a plain note leaves alias ownership complete",
              [link for link in path_links if link[0] == "body"],
              [("body", "Wiki/ppv", "alias", "[[precision|PPV]]", None),
               ("body", "metrics/tpr", "ambiguous", None, None),
               ("body", "ppv", "alias", "[[precision|PPV]]", None)])
        check("a Related-footer replacement is labeled with the owner's "
              "canonical title",
              [link for link in path_links if link[0] == "related"],
              [("related", "ppv", "alias", "[[precision|Precision]]", None),
               ("related", "Recall", "case", "[[recall|Recall]]", None)])

        wrong, wrong_links = links_review(
            "wrong-path", {"precision.md": measure("Precision"),
                           "recall.md": measure("Recall", ["tpr"]),
                           "metrics/accuracy.md": measure("Accuracy")},
            " It uses [[metrics/precision|precision]], "
            "[[Wiki/nowhere/precision|p]], [[Wiki/precision|precision]], "
            "[[Wiki/metrics/accuracy|accuracy]], [[metrics/accuracy.md|"
            "accuracy]], [[Wiki/accuracy|accuracy]] and [[nowhere/tpr|TPR]].")
        check("a path whose folder holds no such entry is dangling even when "
              "its basename is an entry; whole, trailing and root-qualified "
              "paths resolve, a path no other file needs is dropped, and a "
              "path to an alias follows the alias rule",
              ([(r["section"], r["target"], r.get("unmirrored"))
                for r in wrong["dangling"]], wrong_links, wrong["clean"]),
              ([("body", "metrics/precision", None),
                ("body", "Wiki/nowhere/precision", None)],
               [("body", "Wiki/precision", "path", "[[precision]]", None),
                ("body", "Wiki/metrics/accuracy", "path", "[[accuracy]]",
                 None),
                ("body", "metrics/accuracy.md", "path", "[[accuracy]]", None),
                ("body", "Wiki/accuracy", "path", "[[accuracy]]", None),
                ("body", "nowhere/tpr", "alias", "[[recall|TPR]]", None)],
               False))

        # A path stays where another vault file owns the bare name: a note
        # outside the Wiki or a previous-layout MOC. A bare link or an alias
        # beside an outside note takes the qualified path.
        shared_vault = os.path.join(tmp, "shared-path", "vault")
        for folder in ("Articles", "MOCs"):
            os.makedirs(os.path.join(shared_vault, folder))
        put(os.path.join(shared_vault, "Articles", "variance.md"),
            "A reading note.\n")
        put(os.path.join(shared_vault, "MOCs", "statistics.md"), "- x\n")
        _shared, shared_links = links_review(
            "shared-path", {"variance.md": measure("Variance", ["var-alias"]),
                            "statistics.md": measure("Statistics"),
                            "mean.md": measure("Mean")},
            " It uses [[variance]], [[var-alias|var]], "
            "[[Wiki/variance|variance]], [[variance.md|variance]], "
            "[[Wiki/variance.md|variance]], [[Wiki/statistics|statistics]] "
            "and [[Wiki/mean|mean]].")
        check("a path another vault file needs is kept, less its .md",
              shared_links,
              [("body", "variance", "path", "[[Wiki/variance|variance]]",
                None),
               ("body", "var-alias", "alias", "[[Wiki/variance|var]]", None),
               ("body", "variance.md", "path", "[[Wiki/variance|variance]]",
                None),
               ("body", "Wiki/variance.md", "path",
                "[[Wiki/variance|variance]]", None),
               ("body", "Wiki/mean", "path", "[[mean]]", None)])
        _unproven, unproven_links = links_review(
            "unproven-path", {"precision.md": measure("Precision")},
            " It uses [[Wiki/precision|precision]] and "
            "[[Wiki/precision.md|precision]].", links=[("sub", external)])
        check("beside an unmirrored folder a path stays, less its .md",
              unproven_links,
              [("body", "Wiki/precision.md", "path",
                "[[Wiki/precision|precision]]", None)])
        # Obsidian indexes a symlinked folder, so its same-named note keeps a
        # path. A loop inside that folder is walked once.
        linked_store = os.path.join(tmp, "linked-store")
        os.makedirs(os.path.join(tmp, "linked-path", "vault"))
        os.makedirs(linked_store)
        put(os.path.join(linked_store, "mean.md"), "A shared note.\n")
        os.symlink(linked_store,
                   os.path.join(tmp, "linked-path", "vault", "Shared"))
        os.symlink(linked_store, os.path.join(linked_store, "loop"))
        _linked, linked_links = links_review(
            "linked-path", {"mean.md": measure("Mean")},
            " It uses [[Wiki/mean|mean]].")
        check("a note in a symlinked folder keeps the path it needs",
              (linked_links, _outside_notes(
                  os.path.join(tmp, "linked-path", "vault"),
                  os.path.join(tmp, "linked-path", "vault", "Wiki"))),
              ([], ({"shared/mean"}, [])))

        # A link to a real note outside the Wiki is not dangling, and the
        # note outranks an entry alias of its name (wiki-lint's
        # item10/non-entry). The merged entry's own such link is inherited.
        def outside_review(name, body):
            articles = os.path.join(tmp, name, "vault", "Articles")
            os.makedirs(articles)
            for stem in ("doe-paper", "gadget", "extra"):
                put(os.path.join(articles, stem + ".md"), "A reading note.\n")
            kept = _st_entry("F1 score", "F1 score is the harmonic mean of "
                             "precision and recall.", "The harmonic mean of "
                             "the two error-rate shares.",
                             body=" It cites [[doe-paper|Doe]].")
            result, links = links_review(
                name, {"tool.md": measure("Tool", ["gadget"]),
                       "f1-score.md": kept}, body)
            return result, links, [
                (r["section"], r["target"], r.get("inherited"))
                for r in result["non_entry"]]

        outside_new, outside_links, outside_rows = outside_review(
            "non-entry", " It cites [[doe-paper|Doe]], [[gadget]], "
            "[[Articles/gadget|g]], [[../Articles/extra|x]] and "
            "[[Articles/extra.md|x]].")
        check("a link to a note outside the Wiki is non_entry, never "
              "dangling or an alias; only the merged entry's own is "
              "inherited, and a new one keeps the review from being clean",
              (outside_rows, outside_new["dangling"], outside_links,
               outside_new["clean"]),
              ([("body", "doe-paper", True), ("body", "gadget", None),
                ("body", "Articles/gadget", None),
                ("body", "../Articles/extra", None),
                ("body", "Articles/extra.md", None)], [], [], False))
        outside_kept, _kept_links, kept_rows = outside_review(
            "non-entry-kept", " It cites [[doe-paper|Doe]].")
        check("an inherited non_entry link leaves the review clean",
              (kept_rows, outside_kept["clean"]),
              ([("body", "doe-paper", True)], True))
        # A note in an unreadable folder outside the Wiki may own a link the
        # merged entry already had: that dangling link lists the folder, so
        # it is kept. A new dangling link does not list it.
        private = os.path.join(tmp, "unread-outside", "vault", "Private")
        os.makedirs(private)
        put(os.path.join(private, "doe-paper.md"), "A reading note.\n")
        unread_want = ([("doe-paper", ["Private"]), ("nowhere", None)],
                       [True])
        os.chmod(private, 0)
        try:
            if os.access(private, os.R_OK):
                unread_seen = unread_want        # a superuser reads it
            else:
                unread_new, _unread_links = links_review(
                    "unread-outside", {"f1-score.md": _st_entry(
                        "F1 score", "F1 score is the harmonic mean of "
                        "precision and recall.", "The harmonic mean of the "
                        "two error-rate shares.",
                        body=" It cites [[doe-paper|Doe]].")},
                    " It cites [[doe-paper|Doe]] and [[nowhere]].")
                unread_seen = ([(r["target"], r.get("unmirrored"))
                                for r in unread_new["dangling"]],
                               ["Private" in n for n in unread_new["notes"]])
        finally:
            os.chmod(private, 0o755)
        check("a dangling link the entry already had lists an unread "
              "folder outside the Wiki, with a note", unread_seen,
              unread_want)

        # An online page's URL is a valid source item (CONVENTIONS section 7),
        # and a frontmatter URL is never a link, even when its last path
        # segment spells an entry's stem, in or out of case.
        def cites(text, *urls):
            return text.replace(
                '  - "[[Doe_X_2025.pdf#page=2]]"',
                "".join('  - "%s"\n' % url for url in urls)
                + '  - "[[Doe_X_2025.pdf#page=2]]"')

        web_wiki = os.path.join(tmp, "web-vault", "Wiki")
        os.makedirs(web_wiki)
        put(os.path.join(web_wiki, "precision.md"), measure("Precision"))
        put(os.path.join(web_wiki, "recall.md"), cites(
            measure("Recall"), "https://example.org/wiki/precision"))
        web_merge = put(os.path.join(drafts, "web-recall.md"), cites(
            _st_entry("Recall", "Recall is a test measure.", "A test measure.",
                      body=" It is read beside [[precision]]."),
            "https://example.org/wiki/precision"))
        web_new = put(os.path.join(drafts, "web-f1.md"), cites(
            _st_entry("F1 score", "F1 score is the harmonic mean of precision "
                      "and recall.", "The harmonic mean of the two error-rate "
                      "shares.", body=" It combines [[precision]] with "
                      "[[recall]]."),
            "https://example.org/wiki/Precision",
            "https://example.org/wiki/missing-entry"))
        web = review(web_wiki, manifest("web.json", [
            ("Wiki/recall.md", web_merge), ("Wiki/f1-score.md", web_new)]),
            os.path.join(tmp, "web-review"))
        check("a merge draft citing a URL plus a PDF over an entry that "
              "already cites the URL is clean, with no 4-sources finding",
              ("4-sources" in items(web["on_staged"] + web["introduced"]),
               web["on_staged"], web["introduced"], web["baseline_count"],
               web["clean"]),
              (False, [], [], 0, True))
        check("a URL item whose last path segment spells an entry stem is "
              "never dangling or noncanonical",
              (web["dangling"], web["noncanonical"]), ([], []))

        empty_vault = os.path.join(tmp, "empty-vault")
        os.makedirs(empty_vault)
        fresh = review(os.path.join(empty_vault, "Wiki"), manifest(
            "fresh.json", [("Wiki/f1-score.md", f1_draft)]),
            os.path.join(tmp, "fresh-review"))
        check("an absent Wiki reviews the staged entries alone", (
            fresh["on_staged"],
            [(r["section"], r["target"]) for r in fresh["dangling"]],
            fresh["notes"]),
            ([], [("body", "precision"), ("body", "recall"),
                  ("related", "precision"), ("related", "recall")],
             ["Wiki/ does not exist yet; the mirror is empty"]))

        def refused(label, **kwargs):
            args = {"wiki": wiki, "manifest": first, "out": out}
            args.update(kwargs)
            try:
                review(**args)
            except ReviewError as exc:
                check(label, True, True)
                return str(exc)
            check(label, "ran", "ReviewError")
            return ""

        plain = os.path.join(tmp, "plain")
        os.makedirs(plain)
        put(os.path.join(plain, "keep.md"), "keep\n")
        refused("an --out without the sentinel is refused", out=plain)
        check("a refused --out is left untouched", sorted(os.listdir(plain)),
              ["keep.md"])
        refused("an --out that is a file is refused",
                out=os.path.join(plain, "keep.md"))
        refused("an --out inside the vault is refused",
                out=os.path.join(vault, "review"))
        refused("an --out inside a case variant of the vault is refused",
                out=os.path.join(tmp, "VAULT", "review"))
        check("nothing is created inside the vault",
              os.path.exists(os.path.join(vault, "review")), False)
        inside = put(os.path.join(tree, "f1-draft.md"), "draft\n")
        refused("a draft inside --out is refused", manifest=manifest(
            "inside.json", [("Wiki/f1-score.md", inside)]))
        check("a draft inside --out survives the refusal",
              os.path.exists(inside), True)
        refused("a Wiki path without .md is refused", manifest=manifest(
            "extension.json", [("Wiki/f1-score", f1_draft)]))
        refused("a missing draft is refused", manifest=manifest(
            "missing.json", [("Wiki/x.md", os.path.join(drafts, "none.md"))]))
        refused("a path escaping the vault is refused", manifest=manifest(
            "escape.json", [("Wiki/../../x.md", f1_draft)]))
        refused("a case variant of an existing entry is refused",
                manifest=manifest("case.json",
                                  [("Wiki/PRECISION.md", f1_draft)]))

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["--wiki", wiki, "--manifest", first, "--out", out])
        check("the CLI exits 0 for a review with findings",
              (rc, json.loads(buf.getvalue())["clean"]), (0, False))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["--wiki", wiki, "--manifest", first, "--out", plain])
        check("the CLI exits 2 when the review cannot run",
              (rc, json.loads(buf.getvalue())["ok"]), (2, False))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [c for c in cases if not c[1]]
    for label, ok, got, want in cases:
        if not ok:
            print("FAIL  %s\n        got  %r\n        want %r" % (label, got, want))
    print("%d/%d self-test cases pass" % (len(cases) - len(failed), len(cases)))
    return 1 if failed else 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _build_parser():
    p = argparse.ArgumentParser(
        prog="review_tree.py",
        description="Lint a private copy of the Wiki with the staged drafts "
                    "overlaid, and report the findings they add (stdlib only).",
        epilog="example: review_tree.py --wiki ~/Vault/Wiki "
               "--manifest /tmp/run/manifest.json --out /tmp/run/review",
    )
    # Not `required=True`: that would make `--test` unreachable. A real run
    # missing one is refused below, by name and with exit 2.
    p.add_argument("--wiki", help="the real Wiki folder")
    p.add_argument("--manifest",
                   help='JSON list of {"path": "Wiki/<slug>.md", "draft": '
                        '"<absolute path>"} objects')
    p.add_argument("--out", help="scratch directory for the review tree "
                                 "(new, or created earlier by this tool)")
    p.add_argument("--vault", help="vault root the manifest paths are "
                                   "relative to (default: the Wiki's parent)")
    p.add_argument("--test", action="store_true",
                   help="run the built-in self-test and exit")
    p.add_argument("--compact", action="store_true", help="compact JSON output")
    return p


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, OSError):
            pass
    args = _build_parser().parse_args(argv)
    if args.test:
        return run_self_test()
    missing = [flag for flag, value in (("--wiki", args.wiki),
                                        ("--manifest", args.manifest),
                                        ("--out", args.out)) if not value]
    if missing:
        print(json.dumps({"ok": False, "error": "missing required argument: %s"
                          % ", ".join(missing)}, indent=2))
        return 2
    try:
        report = review(args.wiki, args.manifest, args.out, vault=args.vault)
    except Exception as exc:
        error = str(exc) if isinstance(exc, ReviewError) else "%s: %s" % (
            type(exc).__name__, exc)
        print(json.dumps({"ok": False, "error": error}, ensure_ascii=False,
                         indent=2))
        return 2
    print(json.dumps(report, ensure_ascii=False,
                     **({} if args.compact else {"indent": 2})))
    return 0


if __name__ == "__main__":
    sys.exit(main())
