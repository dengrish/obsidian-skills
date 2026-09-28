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
  5. Dangling links: body and Related wikilinks of each staged entry whose
     target matches no entry of the combined tree by filename stem or alias,
     nor, when bare, a file stem in the vault's ``MOCs`` folder
     (case/NFC-insensitive).
     ``MOCs/...`` targets, embeds, links in code and anchors after ``#`` are
     ignored. A dangling link lists under ``unmirrored`` the unmirrored file
     matching its stem and every unmirrored folder it may live in; an
     unmirrored folder also adds a note.

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
baseline_count, dangling[], unmirrored[], notes[]}. A finding is {file, item,
severity, message, evidence}; ``clean`` is true when on_staged, introduced
and dangling are all empty.

Exit codes: 0 the review ran (clean or not), 2 it could not run (bad usage,
refused ``--out``, unreadable manifest or draft, incomplete lint); 1 a
failed ``--test``.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
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

from lint_entry import lint_path  # noqa: E402
from vault_index import (  # noqa: E402
    extract_wikilinks,
    fold_name,
    parse_frontmatter,
    split_sections,
)

__all__ = ["ReviewError", "review"]

SENTINEL = ".review-tree"


class ReviewError(Exception):
    """The review could not run; nothing it reports would be trustworthy."""


def _within(path, root):
    """Whether ``path`` is the existing folder ``root`` or lies below it.

    Compares ``(st_dev, st_ino)`` identities rather than strings: realpath
    keeps the caller's letter case and Unicode normalization, which a case-
    or normalization-insensitive filesystem treats as the same folder.
    """
    try:
        info = os.stat(root)
    except OSError:
        return False
    target, path = (info.st_dev, info.st_ino), os.path.realpath(path)
    while True:
        try:
            info = os.stat(path)
        except OSError:
            pass                           # not created yet; check its parent
        else:
            if (info.st_dev, info.st_ino) == target:
                return True
        parent = os.path.dirname(path)
        if parent == path:
            return False
        path = parent


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
        if _within(draft, out):
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
        if _within(out, root) or _within(root, out):
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

def _lint(tree):
    report = lint_path(tree)
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


def _match_key(rel, finding):
    """A finding's baseline identity: its message, less cross-entry counts.

    A staged draft can change how many entries claim an alias, or how many
    links reach one target, without touching the file that reports it.
    """
    detail, evidence = finding["message"], finding.get("evidence") or {}
    if finding["item"] == "18-alias-collision":
        detail = (fold_name(evidence.get("alias", "")),
                  "filename slug" in detail)
    elif finding["item"] == "10-duplicate-wikilink":
        detail = evidence.get("target")
    return fold_name(rel), finding["item"], detail


def _moc_stems(vault):
    """Folded stems of the ``.md`` files in the vault's flat ``MOCs`` folder."""
    try:
        names = os.listdir(os.path.join(vault, "MOCs"))
    except OSError:
        return set()
    return {fold_name(name[:-3]) for name in names
            if name.lower().endswith(".md") and not name.startswith(".")}


def _link_stem(target):
    """The folded filename stem a link names, or None when it is exempt."""
    key = target.replace("\\", "/").strip().strip("/")
    if not key or ("/" in key and fold_name(key.split("/", 1)[0]) == "mocs"):
        return None
    stem = key.rsplit("/", 1)[-1]
    if stem.lower().endswith(".md"):
        stem = stem[:-3]
    return fold_name(stem)


def dangling_links(text, known, mocs=()):
    """``(section, target)`` for each unresolved body or Related wikilink.

    ``known`` holds entry stems and aliases; ``mocs`` holds MOC stems, which
    resolve only a bare target.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    sections = split_sections(parse_frontmatter(text).body)
    regions = (("body", "\n".join(sections["prose_lines"])),
               ("related", sections["related_line"] or ""))
    found = []
    for section, region in regions:
        for target, _label in extract_wikilinks(region):
            stem = _link_stem(target)
            bare = "/" not in target.replace("\\", "/").strip().strip("/")
            if (stem is None or stem in known or (bare and stem in mocs)
                    or (section, target) in found):
                continue
            found.append((section, target))
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
        notes.append("dangling links and alias collisions are incomplete for "
                     "entries that may live in unmirrored folder(s): %s"
                     % ", ".join(folders))

    baseline = collections.Counter(
        _match_key(rel, finding)
        for rel, finding in _findings(_lint(tree), tree))

    staged_paths = {}
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
                os.unlink(target)          # the mirrored copy it replaces
            _write(target, data)
        except OSError as exc:
            raise ReviewError("cannot overlay %s: %s" % (rel, exc))
        staged_paths[fold_name(inner)] = rel

    combined = _lint(tree)
    on_staged, introduced, baseline_count = [], [], 0
    for rel, finding in _findings(combined, tree):
        key = _match_key(rel, finding)
        record ={"file": staged_paths.get(key[0], prefix + rel),
                  "item": finding["item"], "severity": finding["severity"],
                  "message": finding["message"],
                  "evidence": finding.get("evidence")}
        seen_before = baseline[key] > 0
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

    known = set()
    for entry in combined["entries"]:
        known.add(fold_name(os.path.splitext(os.path.basename(entry["file"]))[0]))
        known.update(fold_name(alias) for alias in entry.get("aliases") or [])
    unmirrored_stems = {}
    for item in unmirrored:
        name = item["path"].rsplit("/", 1)[-1]
        if name.lower().endswith(".md"):
            unmirrored_stems.setdefault(fold_name(name[:-3]), item["path"])
    mocs, dangling = _moc_stems(vault), []
    for rel, _inner, data in staged:
        text = data.decode("utf-8-sig", errors="replace")
        for section, target in dangling_links(text, known, mocs):
            record = {"file": rel, "section": section, "target": target}
            occupant = unmirrored_stems.get(_link_stem(target))
            where = ([occupant] if occupant else []) + folders
            if where:
                record["unmirrored"] = where
            dangling.append(record)

    return {
        "ok": True,
        "clean": not (on_staged or introduced or dangling),
        "tree": tree,
        "staged": [rel for rel, _inner, _data in staged],
        "on_staged": on_staged,
        "introduced": introduced,
        "baseline_count": baseline_count,
        "dangling": dangling,
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
        'tags:', '  - "#statistics"', 'parents: []', 'read: false', '---',
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
              "resolve; each names what it may live in",
              [(r["file"], r["section"], r["target"], r.get("unmirrored"))
               for r in report["dangling"]],
              [("Wiki/f1-score.md", "body", "missing-entry", ["Wiki/synced"]),
               ("Wiki/f1-score.md", "body", "linked",
                ["Wiki/linked.md", "Wiki/synced"]),
               ("Wiki/f1-score.md", "related", "another-missing",
                ["Wiki/synced"])])
        check("symlinks are unmirrored and dot/non-entry files are skipped",
              (report["unmirrored"], sorted(os.listdir(tree))),
              ([{"path": "Wiki/linked.md", "reason": "symlink; not followed"},
                {"path": "Wiki/synced", "reason": "symlink; not followed"}],
               ["f1-score.md", "metrics", "precision.md", "recall.md",
                "specificity.md"]))
        check("an outside manifest path and an unmirrored folder add notes",
              report["notes"], [
                  "ignored MOCs/Statistics.md: outside Wiki/",
                  "dangling links and alias collisions are incomplete for "
                  "entries that may live in unmirrored folder(s): "
                  "Wiki/synced"])
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
            rerun["dangling"], rerun["baseline_count"],
            os.path.exists(os.path.join(tree, "specificity.md"))),
            (True, [], [], [], report["baseline_count"], False))

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
