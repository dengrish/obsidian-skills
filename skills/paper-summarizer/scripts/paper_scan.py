#!/usr/bin/env python3
"""What to summarise, and which figures are already on disk for it.

One filesystem pass, before any PDF is opened, answers the three questions
that decide a run:

  * **Which PDFs are in scope, and which are already summarised.**  A paper is
    done iff exactly one `Articles/` basename matches '<pdf stem>.md' under the
    vault's portable NFC/case identity **and that note's `sources:` item 1 (or
    its legacy scalar `source:`) names this PDF**.  The second half is not
    pedantry: `Articles/` is shared with
    clipping-processor, whose notes carry the same `LastName_Thing_Year.md`
    shape, so a bare existence check would read somebody else's clipping as
    "already summarised" — or, worse, overwrite it.  A note of the right name
    with the wrong `source:` is a `collision`, and nothing is written.
  * **Which must be refused** because pdf-organizer has not named them
    (`CONVENTIONS.md` §1a).  Every figure and every note in this pipeline keys
    to the PDF's on-disk stem, so a rename afterwards orphans the whole set
    under a name nothing looks for — invisibly.
  * **Which figures exist for each stem**, under §8a's consumer glob
    `[source_stem]_fig*` — matched on `_fig`, never the stricter `_fig_`, and
    at any extension.

Stdlib only, and it opens no PDF: `paper_text.py` is the one that does.  The
canonical-stem and chapter-of-which-book rules are imported from
`shared/scripts/naming.py`, never restated here.

    python3 '<skill>/scripts/paper_scan.py' \
        --src '<vault>/Sources/PDFs' \
        --notes '<vault>/Articles' \
        --images '<vault>/Sources/Images'

**Point `--src` at the whole of `Sources/PDFs/`, never at a subfolder of it.**
The book skip is *run-scoped*: it can only recognise a book by finding one of
its chapters in the same scan, and pdf-organizer keeps the book at the top of
`Sources/PDFs/` while its chapters go in `Sources/PDFs/<Work>/`.  Scan below
that top level and the two never meet, so the book reads as an ordinary paper
and gets a summary with no figures behind it.  Chapters are then skipped in
their own right (`chapter`), so scanning wide does not turn into a whole book's
worth of summaries.

This is an inventory boundary, not a processing instruction. When the user
named one PDF or a narrower folder, the main skill processes only matching rows
from this whole-tree result. A row outside the requested scope is context for
identity and book detection, not authorization to summarize that source.

`--notes` is the flat `Articles/` folder, which this skill shares with
clipping-processor. A note whose basename differs only by case or Unicode
normalization still occupies the target's portable identity. Its origin decides
whether it is ours; a foreign or multiply occupied identity is a `collision`,
never a second note or an overwrite.

Add `--json` for the machine-readable form, `--test` to run the self-test.
Three overrides relax a skip: `--allow-unorganized`, `--include-split-books`
and `--include-chapters`.
Naming a single PDF processes it whatever it is -- explicit naming overrides
every folder filter, so a named chapter is a `new`, not a `chapter`.
"""

_OBSIDIAN_SHARED_MODULES = ('naming', 'vault_artifacts', 'yaml_scalars')

# --- obsidian shared-layer bootstrap (canonical; see shared/CONVENTIONS.md) ---
import os as _os, sys as _sys
_here = _os.path.dirname(_os.path.abspath(__file__))
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

import argparse
import json
import os
import re
import stat
import sys
import unicodedata

from naming import chapter_book_stem, core_stem, looks_canonical, stem_of
from vault_artifacts import inventory_pdfs, inventory_source_figures
from yaml_scalars import parse_scalar, strip_comment

#: Figure-label namespaces, ranked so a listing reads main → appendix →
#: supplementary → Supporting Information → Extended Data.  Longest prefix
#: first: `SI1` must not be read as `S` + `I1`.
_NAMESPACES = (("SI", 3), ("ED", 4), ("S", 2), ("A", 1))

#: Sorts after every real number, so an unparseable label lands at the end of
#: its namespace instead of at the front.
_BIG = 10 ** 9

#: The status set, whole.  Nothing else is ever emitted, and the order here is
#: the order the resolver applies them in (see `classify`).
STATUSES = ("book", "chapter", "unorganized", "collision", "legacy",
            "done", "new")

#: The note's origin, in either shape it takes on disk.  The CURRENT schema
#: (CONVENTIONS.md 2b) is a block-form `sources:` list whose item 1 is the
#: origin; the scalar `source:` is the retired pre-rename shape, still read
#: as a fallback so an unmigrated note stays recognisable.  Reading only the
#: scalar turned every note this skill itself writes into a `collision`, so
#: no paper was ever `done` and the report told the user a foreign note was
#: in the way.  All three are anchored at column 0, because an INDENTED key
#: is nested under some other key and is not the note's -- reading one turns
#: a note that is ours into a `collision` and stops the paper ever being
#: summarised.  Case-insensitive, and the same two-key logic as
#: clipping-processor's `dedup_index.read_source`: the two skills read each
#: other's notes out of one folder and must agree about what is parseable.
_SOURCES_KEY_RE = re.compile(r"\Asources\s*:\s*(.*)\Z", re.I)
_SOURCES_ITEM_RE = re.compile(r"\A[ \t]*-[ \t]+(.*)\Z")
_SOURCE_RE = re.compile(r"\Asource\s*:\s*(.*)\Z", re.I)

def _yaml_scalar(raw):
    """Decode source scalars using the same rules as clipping dedup."""
    return parse_scalar(raw)[0]

#: The document a `source:` wikilink names, if it is one at all.  Obsidian
#: resolves a wikilink by basename, so only the last path segment matters, and
#: a display pipe or a heading anchor is not part of the name.
_WIKILINK_RE = re.compile(r"\A!?\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]\Z")


#: A panel's label is its figure's label with a lowercase letter on the end
#: (`CONVENTIONS.md` §8b): `1a` is panel a of Figure 1, `S2c` is panel c of
#: Supplementary Figure 2.  A whole figure's label never ends in a lowercase
#: letter -- every caption form the extractor recognises ends in a digit, and
#: `Figure 1a` is rejected as a caption because it is a panel pointer -- so
#: this split reads the convention rather than guessing at it.
_PANEL_LABEL_RE = re.compile(r"\A(.*[0-9])([a-z])\Z")


def panel_parent(label):
    """(figure label, panel letter); the letter is '' for a whole figure."""
    match = _PANEL_LABEL_RE.match(label)
    return (match.group(1), match.group(2)) if match else (label, "")


def _name_key(name):
    return unicodedata.normalize("NFC", name).casefold()


def article_note_index(notes):
    """Map portable Markdown basenames to every direct `Articles/` occupant.

    `Articles/` is flat, and its two producers share one basename namespace.
    Looking up only the exact spelling makes a case/NFD variant appear absent
    on a case-sensitive host even though Obsidian and supported insensitive
    hosts treat it as the same note. Directories and symlinks ending in `.md`
    stay in the index: they occupy the publication identity even though they
    can never establish summary ownership.
    """
    try:
        names = os.listdir(notes)
    except OSError as exc:
        raise ValueError("cannot inspect existing notes in %r: %s" %
                         (notes, exc)) from exc
    by_name = {}
    for name in names:
        if _name_key(os.path.splitext(name)[1]) != ".md":
            continue
        by_name.setdefault(_name_key(name), []).append(
            os.path.join(notes, name))
    for paths in by_name.values():
        paths.sort(key=lambda path: (_name_key(os.path.basename(path)),
                                     os.path.basename(path)))
    return by_name


def label_sort_key(label):
    """Order figure labels the way a reader expects to meet them.

    A panel sorts immediately after the figure it belongs to and before the
    next one -- 1, 1a, 1b, 2 -- because that is the order a reader meets them
    on the page, and because a panel filed after every whole figure reads as a
    separate exhibit rather than as part of one.
    """
    base, panel = panel_parent(label)
    rank, rest = 0, base
    for prefix, r in _NAMESPACES:
        tail = base[len(prefix):]
        if base.startswith(prefix) and re.match(r"\A-?\d", tail):
            rank, rest = r, tail.lstrip("-")
            break
    nums = tuple(int(p) if p.isdecimal() else _BIG
                 for p in rest.split("-") if p)
    return (rank, nums or (_BIG,), panel, label)


_FIG_SEP = re.compile(r"_fig(?:ure)?s?[._-]?", re.I)


def figures_for(attachments, stem):
    """Every figure filed under `stem`, in label order.

    §8a's glob, exactly: the prefix is `<stem>_fig` with no trailing
    underscore, and any extension counts.  Tightening either half is a silent
    total loss on a vault holding figures written before the spellings
    converged (§8c).
    """
    inventory = inventory_source_figures(attachments, stem)
    if not inventory.safe:
        details = []
        if inventory.blocked_matches:
            details.append("blocked source-keyed occupant(s): " + ", ".join(
                inventory.blocked_matches[:4]))
        errors = [finding for finding in inventory.findings
                  if finding.severity == "error"]
        if errors:
            details.extend("%s (%s)" % (finding.path, finding.message)
                           for finding in errors[:4])
        if not details:
            details.append("the image-folder inventory did not complete safely")
        raise ValueError("cannot use figure inventory for %r: %s" %
                         (stem, "; ".join(details)))

    stem_key = _name_key(stem)
    out = []
    for path in inventory.candidates:
        name = os.path.basename(path)
        # Case-folded on both sides, using the portable source/figure identity
        # shared with organize.py. A figure written
        # `doe_foo_2025_fig_1.png` belongs to this stem's collision class; missing it
        # reports zero figures, which SKILL.md step 1 reads as "the extractor
        # never ran" -- a wrong diagnosis that ships a figureless note.
        base, ext = os.path.splitext(name)
        # The glob is deliberately loose (`_fig*`, §8c), so the separator is not
        # guaranteed to be exactly `_fig`: a hand-named `..._figure_3.png` is
        # this stem's figure, and slicing by the prefix length alone labelled it
        # `ure_3`.  Take the label from after whatever `_fig`-ish separator the
        # file actually carries.
        stem_end = next(i for i, char in enumerate(base)
                        if char == "_" and _name_key(base[:i]) == stem_key)
        tail = base[stem_end:]
        m = _FIG_SEP.match(tail)
        label = tail[m.end():] if m else tail.lstrip("_")
        parent, panel = panel_parent(label)
        # `panel_of` is the whole figure this file is a piece of, or None when
        # it IS the whole figure.  §8b: a consumer embeds the composite by
        # default and reaches for a panel only when the point is that panel's,
        # so it needs the two told apart before it starts choosing -- and the
        # unused-figure diagnostic needs it too, or a five-panel figure
        # reports five unused exhibits nobody was ever going to place.
        out.append({"file": name,
                    "label": label,
                    "panel": panel or None,
                    "panel_of": parent if panel else None,
                    "ext": ext.lower()})
    out.sort(key=lambda f: label_sort_key(f["label"]))
    # Two files claiming ONE label is a finding, not a detail to hand on
    # silently.  `Sources/Images/` is flat and shared (CONVENTIONS §1, §8), so
    # `<stem>_fig_2.png` and `<stem>_fig_2.webp` are two legal files written by
    # two producers, they never collide on disk and nothing deduplicates them.
    # `references/figures.md` says "the label picks the file and then stops" —
    # so when a label picks two files, the skill choosing a figure by label has
    # no basis to prefer either, and until now nothing told it so. Folded so
    # `_fig_S1.png` beside `_fig_s1.webp` is the same ambiguity on every host.
    by_label = {}
    for f in out:
        by_label.setdefault(f["label"].casefold(), []).append(f)
    for peers in by_label.values():
        for f in peers:
            f["duplicate_label"] = len(peers) > 1
    return out


def note_source(path):
    """The note's origin from its frontmatter, or None.

    The origin is item 1 of the block-form `sources:` list (schema 2b — the
    shape this skill itself writes); a legacy scalar `source:` is read as a
    fallback so an unmigrated note stays recognisable.  Deliberately the same
    two-key logic and tolerances as clipping-processor's
    `dedup_index.read_source` — a BOM, leading blank lines before the opening
    fence, quote and trailing-comment stripping, and a value returned only
    once the CLOSING fence has been seen (an unterminated `---` is not
    frontmatter to Obsidian, and scanning on into the body would take
    whatever `source:` the prose happens to contain) — because the two skills
    read each other's notes out of one folder and must agree about what is
    parseable. The complete note must decode strictly as UTF-8 before its
    frontmatter can establish ownership; invalid bytes anywhere return None.
    """
    try:
        # Decode the whole note before accepting its claimed origin. Otherwise
        # valid-looking frontmatter can establish ownership even when invalid
        # bytes later in the body make the note itself unreadable.
        with open(path, "r", encoding="utf-8-sig", errors="strict") as fh:
            lines = iter(fh.read().splitlines())
        for first in lines:
            if first.strip():
                break
        else:
            return None
        if first.strip() != "---":
            return None
        found = {}
        pending = False
        for raw in lines:
            if raw.strip() == "---":
                return found.get("sources", found.get("source")) or None
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            if pending:
                pending = False
                mi = _SOURCES_ITEM_RE.match(raw)
                if mi:
                    found["sources"] = _yaml_scalar(mi.group(1))
                    continue
            m = _SOURCES_KEY_RE.match(raw)
            if m:
                if "sources" in found:
                    return None                # duplicate origin keys are ambiguous
                found["sources"] = None
                # A current field, even when unreadable, takes precedence
                # over legacy metadata; it cannot authorize a fallback.
                pending = not strip_comment(m.group(1)).strip()
                continue
            m = _SOURCE_RE.match(raw)
            if m:
                if "source" in found:
                    return None
                found["source"] = _yaml_scalar(m.group(1))
    except UnicodeError:
        return None
    except (OSError, ValueError):
        return None
    return None


#: A body that is nothing but one PDF embed.  That is the shape of the light
#: embed-note an older clipping-processor wrote for a PDF; those notes are
#: still on disk in long-lived vaults, they now sit in `Articles/`, and they
#: carry exactly the `source:` a summary note carries.  Without this probe one
#: reads as this skill's own output and the paper is never summarised, while
#: the batch report says it already was.
_EMBED_ONLY_RE = re.compile(r"\A!\[\[[^\]\n]+\]\]\Z")


def body_is_embed_only(path):
    """True when the note's body is a single `![[…]]` line and nothing else."""
    try:
        with open(path, "r", encoding="utf-8-sig", errors="strict") as fh:
            text = fh.read()
    except (OSError, UnicodeError):
        return False
    # Split on the frontmatter FENCES, which are whole lines.  A bare
    # `text.split("---", 2)` also splits on a `---` inside a frontmatter value
    # (`title: "A Study --- Part One"`), which shifts the body window and
    # makes a legacy embed-note read as a real summary -- the exact outcome
    # this function exists to prevent.
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    body_lines = lines
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                body_lines = lines[i + 1:]
                break
        else:
            body_lines = []
    kept = [ln.strip() for ln in body_lines]
    # Drop the callout, the rule and the blank lines the note shape puts there.
    kept = [ln for ln in kept
            if ln and not ln.startswith(">") and not set(ln) <= set("_-*")]
    return len(kept) == 1 and bool(_EMBED_ONLY_RE.match(kept[0]))


def source_names(source, stem):
    """True when this `source:` value is a wikilink naming `stem`'s PDF.

    A URL is False (it is a clipping note). A wikilink to a *different*
    document is False. Case-folded so ownership does not change with the host
    filesystem; the exact stored spelling remains canonical.
    """
    if not source:
        return False
    # `note_source` already strips a surrounding quote pair, but this is also
    # called on values read some other way -- and the failure of being strict
    # here is a `collision` on a note that is in fact ours, which stops a run
    # for no reason.
    source = source.strip()
    if len(source) >= 2 and source[0] == source[-1] and source[0] in "\"'":
        source = source[1:-1].strip()
    m = _WIKILINK_RE.match(source)
    if not m:
        return False
    base = m.group(1).strip().rstrip("/").split("/")[-1]
    return (base.lower().endswith(".pdf")
            and _name_key(os.path.splitext(base)[0]) == _name_key(stem))


def find_pdfs(src):
    """Every usable `.pdf` at or under `src`, path-sorted.

    A non-PDF file as `--src` raises rather than returning nothing: a clean
    zero-work run is exactly what the `--src` guard exists to stop, and a
    mistyped path that happens to hit a `.md` produced one. Directory symlinks
    are followed under their logical vault paths, with ancestor cycles and
    unreadable subtrees reported as incomplete rather than silently skipped.
    """
    src = os.path.abspath(os.path.expanduser(os.fspath(src)))
    try:
        root_entry = os.lstat(src)
    except OSError as exc:
        raise ValueError("cannot inspect --src %r: %s" % (src, exc)) from exc
    root_mode = root_entry.st_mode
    if stat.S_ISLNK(root_mode):
        try:
            target = os.stat(src)
        except OSError as exc:
            raise ValueError("--src %r is a dangling or unreadable symlink: %s"
                             % (src, exc)) from exc
        root_mode = target.st_mode
    if stat.S_ISREG(root_mode):
        if not src.lower().endswith(".pdf"):
            raise ValueError("%s is a file but not a .pdf; --src takes a PDF or "
                             "a folder of them" % src)
        return [src]
    if not stat.S_ISDIR(root_mode):
        raise ValueError("%s is neither a PDF nor a directory" % src)

    inventory = inventory_pdfs(src, include_hidden=False)
    if not inventory.complete:
        details = "; ".join(
            "%s: %s" % (item.path, item.message)
            for item in inventory.findings if item.severity == "error")
        raise ValueError("cannot complete PDF scan of %r: %s" %
                         (src, details or "inventory incomplete"))
    invalid = []
    usable = []
    for entry in inventory.entries:
        if entry.kind == "regular":
            usable.append(entry.path)
            continue
        if entry.kind == "symlink":
            try:
                target = os.stat(entry.path)
            except OSError as exc:
                invalid.append("%s (dangling or unreadable symlink: %s)" %
                               (entry.path, exc))
                continue
            if stat.S_ISREG(target.st_mode):
                usable.append(entry.path)
                continue
        invalid.append("%s (%s)" % (entry.path, entry.kind))
    if invalid:
        raise ValueError("PDF namespace contains non-regular occupant(s): %s" %
                         "; ".join(invalid))
    return sorted(usable)


def books_in(stems):
    """Core stems that some *other* stem in the same set is a chapter of.

    Case-folded, for the reason `batch_extract.split_book_chapters` folds:
    `kuhn_x_2012_01_Intro.pdf` and `Kuhn_X_2012.pdf` must receive the same
    book/chapter decision on every supported filesystem. The
    two skills split the same folder and disagreeing is worse than either
    answer — the extractor skipped the book and this scan called it `new`, so
    the model was routed to extract from the book alone, writing byte-identical
    figures under two stems that never collide and never deduplicate (§8).
    Three other comparisons in this file already fold; this one did not.
    """
    return {_name_key(b) for b in
            (chapter_book_stem(s, is_stem=True) for s in stems) if b}


def classify(stem, books, note_state, allow_unorganized=False,
             include_books=False, include_chapters=False):
    """One PDF's status.  Two skips, then a refusal, then the note check.

    `note_state` is "absent", "ours" (a note of this stem whose `source:` names
    this PDF and whose body is a real summary), "legacy" (same `source:`, but
    the body is a bare PDF embed — an older skill's note, not ours) or
    "theirs" (a note of this stem that belongs to something else).

    The two skips come first because both are decisions about *scope* — this
    PDF is not the unit of work — while the refusal is about the file itself.
    Ordering them the other way would report a book or a chapter as
    `unorganized` whenever it carried a name pdf-organizer had not produced,
    which routes a scoping decision to the user as a naming complaint.  For an
    ordinary canonical tree the order is not observable, and it is written this
    way to match `pdf-figure-extractor`'s, where it *is* observable.

    `include_chapters` is what explicit single-file naming sets: a chapter is
    skipped by a folder sweep and processed when the user names it.
    """
    # Folded on BOTH sides: `books_in` folds what it produces, and a caller
    # passing a raw set (the self-test does) must get the same answer.
    if _name_key(core_stem(stem, is_stem=True)) in {_name_key(b) for b in books} \
            and not include_books:
        return "book"
    if chapter_book_stem(stem, is_stem=True) and not include_chapters:
        return "chapter"
    if not looks_canonical(stem, is_stem=True) and not allow_unorganized:
        return "unorganized"
    if note_state == "theirs":
        return "collision"
    if note_state == "legacy":
        return "legacy"
    return "done" if note_state == "ours" else "new"


def scan(src, notes, images, allow_unorganized=False,
         include_books=False, include_chapters=None):
    note_index = article_note_index(notes)
    # Explicit naming overrides every folder filter, here as everywhere else
    # in this plugin: `--src` pointed at one PDF means process that PDF.
    if include_chapters is None:
        include_chapters = os.path.isfile(src)
    pdfs = find_pdfs(src)
    stems = [stem_of(p) for p in pdfs]
    books = books_in(stems)
    by_stem = {}
    for path, stem in zip(pdfs, stems):
        by_stem.setdefault(_name_key(stem), []).append(path)
    rows = []
    for path, stem in zip(pdfs, stems):
        expected_note = os.path.join(notes, stem + ".md")
        note_matches = note_index.get(_name_key(stem + ".md"), [])
        note_conflicts = list(note_matches) if len(note_matches) > 1 else []
        note = note_matches[0] if len(note_matches) == 1 else expected_note
        if not note_matches:
            state, existing = "absent", None
        elif note_conflicts:
            # More than one portable-equivalent basename has no unique owner,
            # even if one spelling happens to equal the PDF stem exactly.
            state, existing = "theirs", None
        elif os.path.islink(note) or not os.path.isfile(note):
            # A directory or dangling symlink still occupies the destination.
            # Never follow a symlink to classify a path as safe to rewrite.
            state, existing = "theirs", None
        else:
            existing = note_source(note)
            if not source_names(existing, stem):
                state = "theirs"
            elif body_is_embed_only(note):
                state = "legacy"
            else:
                state = "ours"
        conflicts = [p for p in by_stem[_name_key(stem)] if p != path]
        status = classify(stem, books, state, allow_unorganized,
                          include_books, include_chapters)
        if conflicts and status not in ("book", "chapter", "unorganized"):
            # Basename-only sources cannot distinguish two different PDFs in
            # nested folders, and both would otherwise write the same note.
            status = "collision"
        rows.append({
            "pdf": path,
            "stem": stem,
            "note": note,
            "note_source": existing,
            "status": status,
            "source_conflicts": conflicts,
            "note_conflicts": note_conflicts,
            "figures": figures_for(images, stem),
        })
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES}
    return {"src": src, "notes": notes, "images": images,
            "counts": counts, "pdfs": rows}


def render(result):
    lines = []
    c = result["counts"]
    lines.append("%d PDF(s): %d new, %d already summarised, %d book(s) and "
                 "%d chapter(s) skipped, %d refused as unorganized, "
                 "%d name collision(s), %d legacy embed-note(s)"
                 % (sum(c.values()), c["new"], c["done"], c["book"],
                    c["chapter"], c["unorganized"], c["collision"],
                    c["legacy"]))
    for row in result["pdfs"]:
        figs = row["figures"]
        # Whole figures and panels are counted apart, and the labels shown are
        # the WHOLE figures. A stem whose four figures yielded 27 files has
        # four exhibits, and a bare `figures: 27` followed by a list starting
        # `1, 1a, 1b, 1c` reads as twenty-seven of them -- which then flows
        # into a note that treats each panel as a candidate and into a report
        # that calls twenty-three of them unused (references/figures.md).
        # The JSON has carried `panel_of` since panels existed; this is the
        # human-readable half saying the same thing.
        whole = [f for f in figs if not f.get("panel_of")]
        panels = len(figs) - len(whole)
        shown = ", ".join(f["label"] or "?" for f in whole[:12])
        if len(whole) > 12:
            shown += ", …"
        lines.append("  [%-11s] %s" % (row["status"], row["stem"]))
        lines.append("      figures: %d%s%s"
                     % (len(whole), ("  (" + shown + ")") if whole else "",
                        ("  + %d panel(s) of them, in %d file(s)"
                         % (panels, len(figs))) if panels else ""))
        dup = {}
        for f in figs:
            if f.get("duplicate_label"):
                dup.setdefault(f["label"] or "?", []).append(f["file"])
        for label, names in sorted(dup.items()):
            lines.append("      duplicate label %s: %s -- two files claim one "
                         "figure number. The label is what picks the file "
                         "(references/figures.md), so here it picks two, and "
                         "nothing on disk breaks: Sources/Images/ is flat and "
                         "shared, and the two extensions never collide. Ask "
                         "the user which is current; do not embed either on a "
                         "guess." % (label, ", ".join(names)))
        if row["status"] == "unorganized":
            lines.append("      run pdf-organizer on this file first, or pass "
                         "--allow-unorganized and accept that a later rename "
                         "orphans its figures and its note (CONVENTIONS.md §1a)")
        if row["status"] == "book":
            lines.append("      its chapters are in this scan, so this whole-book "
                         "PDF is skipped to avoid a duplicate. Chapters remain "
                         "separate rows and a folder sweep normally skips them "
                         "too; name one or pass --include-chapters to select it")
        if row["status"] == "collision":
            if row.get("source_conflicts"):
                lines.append("      %s shares this PDF basename and the same "
                             "output note: %s. Nothing may be written until "
                             "pdf-organizer gives the sources distinct names."
                             % (", ".join(row["source_conflicts"]), row["note"]))
            if row.get("note_conflicts"):
                lines.append("      several Articles basenames occupy this "
                             "note's portable case/Unicode identity: %s. "
                             "Nothing may be written until the duplicate "
                             "ownership is resolved."
                             % ", ".join(row["note_conflicts"]))
            if not row.get("source_conflicts") and not row.get("note_conflicts"):
                lines.append("      %s already exists and its source: is %r -- a "
                         "different note under the same name. Do NOT write "
                         "over it; report both and let the user rename one."
                         % (row["note"], row["note_source"]))
        if row["status"] == "legacy":
            lines.append("      %s is an embed-note left by an older skill, "
                         "not a summary. Nothing here overwrites a user file: "
                         "report it, and let the user move or rename it if "
                         "they want the summary written." % row["note"])
        if row["status"] == "chapter":
            lines.append("      a book chapter: skipped by a folder sweep, "
                         "because a whole book's worth of summaries is rarely "
                         "the ask. Name it to summarise it.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------

#: (label, expected position among its peers) is fragile to write down, so the
#: cases are stated as an unsorted list and its one correct ordering.
_SORT_CASES = [
    (["10", "2", "1-2", "1", "S1", "A1", "SI1", "ED1", "2-10", "2-2"],
     ["1", "1-2", "2", "2-2", "2-10", "10", "A1", "S1", "SI1", "ED1"]),
    (["S2-3", "S1", "S10"], ["S1", "S2-3", "S10"]),
    (["A-1", "A-2"], ["A-1", "A-2"]),
    # A panel sits with its own figure, not after every figure (§8b).
    (["2", "1b", "1", "1a", "S1a", "S1"],
     ["1", "1a", "1b", "2", "S1", "S1a"]),
    (["²", "2", "1"], ["1", "2", "²"]),
]

#: (label, parent, panel letter). A whole figure's label never ends in a
#: lowercase letter; a panel's always does (`CONVENTIONS.md` §8b).
_PANEL_CASES = [
    ("1", "1", ""),
    ("1a", "1", "a"),
    ("S2c", "S2", "c"),
    ("1-2b", "1-2", "b"),
    ("ED2a", "ED2", "a"),
    # NEAR MISS: an uppercase tail is not a panel -- `A1` is an appendix
    # figure, and folding it to `A` + `1` would file it under a figure that
    # does not exist.
    ("A1", "A1", ""),
    ("SI1", "SI1", ""),
]

#: (stem, books-in-run, note state, expected status).
_CLASSIFY_CASES = [
    ("Vaswani_AttnAllYouNeed_2017", set(), "absent", "new"),
    ("Vaswani_AttnAllYouNeed_2017", set(), "ours", "done"),
    # a note of this name that belongs to something else -- a clipping sharing
    # the folder, or a summary of a different PDF -- is never written over
    ("Vaswani_AttnAllYouNeed_2017", set(), "theirs", "collision"),
    # the book of a chapter in the same run, with and without its own `_src`
    ("Prince_UDL_2026", {"Prince_UDL_2026"}, "absent", "book"),
    ("Prince_UDL_2026_src", {"Prince_UDL_2026"}, "absent", "book"),
    # a chapter is never its own book -- it is a chapter, and a sweep skips it
    ("Prince_UDL_2026_01_Intro", {"Prince_UDL_2026"}, "absent", "chapter"),
    # ... even when its book is not in the scan at all
    ("Prince_UDL_2026_01_Intro", set(), "absent", "chapter"),
    # a `_2` disambiguator names a different document, so it pairs with nothing
    ("Prince_UDL_2026_2", {"Prince_UDL_2026"}, "absent", "new"),
    # unorganized names are refused before anything is written
    ("download (1)", set(), "absent", "unorganized"),
    ("attention is all you need", set(), "absent", "unorganized"),
    # the legacy mid-`_src` chapter: recognised as a chapter even though
    # `looks_canonical` rejects the spelling, so the skip beats the refusal
    ("Prince_UDL_2026_src_01_Intro", {"Prince_UDL_2026"}, "absent", "chapter"),
    # A book whose chapters are spelled in another case shares their portable
    # source identity, and pdf-figure-extractor pairs them. Raw-string
    # comparison called this book `new`, so the model
    # was sent to extract from the book AND from every chapter, filing the same
    # figures twice under two stems that never collide (§8).
    ("Kuhn_X_2012", {"kuhn_x_2012"}, "absent", "book"),
    ("Kuhn_X_2012_src", {"kuhn_x_2012"}, "absent", "book"),
    # NEAR MISS: folding must not pair two genuinely different documents.
    ("Kuhn_Y_2012", {"kuhn_x_2012"}, "absent", "new"),
]


def run_self_test():
    bad = 0
    n = 0
    for unsorted_labels, expected in _SORT_CASES:
        n += 1
        got = sorted(unsorted_labels, key=label_sort_key)
        if got != expected:
            bad += 1
            print("FAIL sort %r -> %r, expected %r"
                  % (unsorted_labels, got, expected))
    for label, parent, panel in _PANEL_CASES:
        n += 1
        got = panel_parent(label)
        if got != (parent, panel):
            bad += 1
            print("FAIL panel_parent %r -> %r, expected %r"
                  % (label, got, (parent, panel)))
    for stem, books, state, expected in _CLASSIFY_CASES:
        n += 1
        got = classify(stem, books, state)
        if got != expected:
            bad += 1
            print("FAIL classify(%r, books=%r, state=%r) -> %r, expected %r"
                  % (stem, sorted(books), state, got, expected))
    # `source_names` is what turns a note on disk into that third argument, and
    # it is the whole of the guard against overwriting somebody else's note.
    for src, stem, want in (
            ('"[[Doe_Foo_2025.pdf]]"',                "Doe_Foo_2025",  True),
            ("[[Doe_Foo_2025.pdf]]",                  "Doe_Foo_2025",  True),
            ("[[Sources/PDFs/Doe_Foo_2025.pdf]]",     "Doe_Foo_2025",  True),
            ("[[Doe_Foo_2025.pdf|the paper]]",        "Doe_Foo_2025",  True),
            ("[[doe_foo_2025.pdf]]",                  "Doe_Foo_2025",  True),
            ("[[Mu\u0308ller_Foo_2025.pdf]]",          "Müller_Foo_2025", True),
            ("[[Doe_Foo_2025.PDF#page=3|3]]",         "Doe_Foo_2025",  True),
            ("[[Doe_Foo_2025.md]]",                   "Doe_Foo_2025",  False),
            ("[[Doe_Foo_2025]]",                      "Doe_Foo_2025",  False),
            ("[[Doe_Foo_2025.pdf",                     "Doe_Foo_2025",  False),
            ("[[Doe_Bar_2025.pdf]]",                  "Doe_Foo_2025",  False),
            ("https://example.com/doe-foo",           "Doe_Foo_2025",  False),
            ("", "Doe_Foo_2025", False),
            (None, "Doe_Foo_2025", False)):
        n += 1
        if source_names(src, stem) is not want:
            bad += 1
            print("FAIL source_names(%r, %r) -> %r, expected %r"
                  % (src, stem, source_names(src, stem), want))
    # `body_is_embed_only` is the second half of the same guard: a legacy
    # embed-note carries a summary note's exact `source:`, so only the body
    # tells them apart, and getting it wrong reports an unsummarised paper as
    # done forever.
    import tempfile
    _d = tempfile.mkdtemp()
    os.makedirs(os.path.join(_d, "notes"), exist_ok=True)

    # PDF discovery shares the plugin-wide identity-aware walker. A linked
    # source folder is part of the logical source tree; a link back to an
    # ancestor is an incomplete inventory, never a clean empty run.
    _walk_root = os.path.join(_d, "pdf-walk")
    _linked_target = os.path.join(_d, "linked-pdf-target")
    os.makedirs(_walk_root)
    os.makedirs(_linked_target)
    _linked_pdf = os.path.join(_linked_target, "Linked_Study_2025.pdf")
    with open(_linked_pdf, "wb") as fh:
        fh.write(b"%PDF fixture")
    _linked_dir = os.path.join(_walk_root, "linked")
    try:
        os.symlink(_linked_target, _linked_dir, target_is_directory=True)
        _have_walk_links = True
    except (OSError, NotImplementedError):
        _have_walk_links = False
    n += 1
    if _have_walk_links:
        _found = find_pdfs(_walk_root)
        _want = [os.path.join(_linked_dir, "Linked_Study_2025.pdf")]
        if _found != _want:
            bad += 1
            print("FAIL linked PDF subtree was skipped: %r, expected %r"
                  % (_found, _want))
    _loop = os.path.join(_walk_root, "loop")
    if _have_walk_links:
        os.symlink(_walk_root, _loop, target_is_directory=True)
        try:
            find_pdfs(_walk_root)
            _cycle_refused = False
        except ValueError as exc:
            _cycle_refused = "ancestor" in str(exc)
        n += 1
        if not _cycle_refused:
            bad += 1
            print("FAIL PDF directory-symlink cycle was not reported")
        os.unlink(_loop)
    else:
        n += 1
    _pdf_directory = os.path.join(_walk_root, "Not_A_Paper_2025.pdf")
    os.makedirs(_pdf_directory)
    try:
        find_pdfs(_walk_root)
        _nonregular_refused = False
    except ValueError as exc:
        _nonregular_refused = "non-regular" in str(exc)
    n += 1
    if not _nonregular_refused:
        bad += 1
        print("FAIL PDF-named directory was treated as a paper")
    os.rmdir(_pdf_directory)

    def _note(name, body):
        p = os.path.join(_d, name)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(body)
        return p

    def _note_bytes(name, body):
        p = os.path.join(_d, name)
        with open(p, "wb") as fh:
            fh.write(body)
        return p

    _fm = '---\ntitle: x\nsource: "[[Doe_Foo_2025.pdf]]"\nread: false\n---\n'
    for label, body, want in (
            ("bare embed", _fm + "![[Doe_Foo_2025.pdf]]\n", True),
            ("legacy note with leading blank lines",
             "\n\n" + _fm + "![[Doe_Foo_2025.pdf]]\n", True),
            ("embed under a callout and a rule",
             _fm + "> [!Summary]\n> - a bullet\n\n___\n\n"
                   "![[Doe_Foo_2025.pdf]]\n", True),
            ("a real summary body",
             _fm + "> [!Summary]\n> - a bullet\n\n___\n\n"
                   "## Methods\n\nA trial.\n", False),
            ("a summary that also embeds a figure",
             _fm + "___\n\n## Results\n\n"
                   "![[Doe_Foo_2025_fig_2.png]]\n*Figure 2 — x.*\n", False),
            ("no frontmatter at all", "![[Doe_Foo_2025.pdf]]\n", True)):
        n += 1
        got = body_is_embed_only(_note(label.replace(" ", "_") + ".md", body))
        if got is not want:
            bad += 1
            print("FAIL body_is_embed_only(%s) -> %r, expected %r"
                  % (label, got, want))
    # The two overrides do what they say, and only that.
    n += 1
    if classify("download (1)", set(), "absent", allow_unorganized=True) != "new":
        bad += 1
        print("FAIL --allow-unorganized did not clear the refusal")
    n += 1
    if classify("Prince_UDL_2026", {"Prince_UDL_2026"}, "absent",
                include_books=True) != "new":
        bad += 1
        print("FAIL --include-split-books did not clear the book skip")
    n += 1
    if classify("Prince_UDL_2026_01_Intro", set(), "absent",
                include_chapters=True) != "new":
        bad += 1
        print("FAIL explicit naming did not clear the chapter skip")
    # The two skips must beat the refusal, or a scoping decision reaches the
    # user as a naming complaint.  This is the ordering the docstring claims.
    n += 1
    if classify("Prince_UDL_2026_src_01_Intro", {"Prince_UDL_2026"},
                "absent") != "chapter":
        bad += 1
        print("FAIL the chapter skip did not beat the canonical refusal")
    # --- the two readers, against the shapes a real vault produces --------
    # These were untested: stubbing `note_source` to return None (every paper
    # a `collision`, nothing ever summarised) or `figures_for` to return []
    # (every note figureless) left the suite green.
    _fm_cases = [
        # --- the CURRENT schema (CONVENTIONS 2b): block-form `sources:`,
        # item 1 is the origin.  This is the shape this skill itself writes
        # (note_lint.py's SCHEMA), and the reader used to see only the
        # retired scalar -- so every note written to the documented schema
        # classified as a `collision` and no paper was ever `done`.
        ('---\nsources:\n  - "[[Doe_Foo_2025.pdf]]"\n---\n',
         "[[Doe_Foo_2025.pdf]]"),
        ('---\nsources: # original PDF\n- "[[Doe_Foo_2025.pdf]]"\n---\n',
         "[[Doe_Foo_2025.pdf]]"),
        ('---\nsources:\n- "[[\\x44oe_Foo_2025.pdf]]"\n---\n',
         "[[Doe_Foo_2025.pdf]]"),
        ("---\nsource: 'https://example.com/o''brien'\n---\n",
         "https://example.com/o'brien"),
        ('---\nsources:\n  -"[[Doe_Foo_2025.pdf]]"\n---\n', None),
        ('---\nsources:\n  - "[[Doe_Foo_2025.pdf]]\n---\n', None),
        ('---\nsources:\n  - "[[Doe_Foo_2025.pdf]]"extra\n---\n', None),
        ('---\nsources:\n  - "[[Doe_Foo_2025.pdf#page=1]]"\n---\n',
         "[[Doe_Foo_2025.pdf#page=1]]"),
        # item 2 (the printed-origin URL) is not the origin; item 1 is.
        ('---\nsources:\n  - "[[Doe_Foo_2025.pdf]]"\n'
         '  - "https://doi.org/10.1000/x"\n---\n', "[[Doe_Foo_2025.pdf]]"),
        # a clipping's list: item 1 is a URL, so the note is not ours.
        ('---\nsources:\n  - "https://example.com/clip"\n---\n',
         "https://example.com/clip"),
        ('---\nsources:\n  - https://example.com/unquoted\n---\n',
         "https://example.com/unquoted"),
        # a trailing YAML comment is a comment, not part of the value.
        ('---\nsources:\n  - "[[Doe_Foo_2025.pdf]]" # main\n---\n',
         "[[Doe_Foo_2025.pdf]]"),
        # a comment or blank line BETWEEN `sources:` and item 1 is valid YAML;
        # consuming the pending flag on one classified the note `collision`.
        ('---\nsources:\n  # verified\n  - "[[Doe_Foo_2025.pdf]]"\n---\n',
         "[[Doe_Foo_2025.pdf]]"),
        ('---\nsources:\n\n  - "[[Doe_Foo_2025.pdf]]"\n---\n',
         "[[Doe_Foo_2025.pdf]]"),
        # an INDENTED `sources:` belongs to another key and is not ours.
        ('---\ncitation:\n  sources:\n    - "[[Other_2020.pdf]]"\n---\n',
         None),
        # an unterminated fence is not frontmatter (dedup_index's rule too).
        ('---\nsources:\n  - "[[Doe_Foo_2025.pdf]]"\n\nprose\n', None),
        # --- the retired scalar, still read so legacy notes keep working ---
        ('---\nsource: "[[Doe_Foo_2025.pdf]]"\n---\n', "[[Doe_Foo_2025.pdf]]"),
        # A capitalised key: clipping-processor's reader folds case, and a
        # disagreement here turns one skill's note into the other's collision.
        ('---\nSource: "[[Doe_Foo_2025.pdf]]"\n---\n', "[[Doe_Foo_2025.pdf]]"),
        # An INDENTED `source:` is nested under another key and is not ours.
        ('---\ncitation:\n  source: "[[Other_2020.pdf]]"\n'
         'source: "[[Doe_Foo_2025.pdf]]"\n---\n', "[[Doe_Foo_2025.pdf]]"),
        ('---\nsource: https://example.com/x\n---\n', "https://example.com/x"),
        ('---\nsource: "[[Doe_Foo_2025.pdf]]"\nsources:\n'
         '  - "https://example.com/clip"\n---\n', "https://example.com/clip"),
        ('---\nsources:\n  - "https://example.com/clip"\n'
         'source: "[[Doe_Foo_2025.pdf]]"\n---\n', "https://example.com/clip"),
        ('---\nsource: "[[Doe_Foo_2025.pdf]]"\nsources:\n---\n', None),
        ('---\nsource: "[[Doe_Foo_2025.pdf]]"\nsources: null\n---\n', None),
        ('---\nsource: "[[Doe_Foo_2025.pdf]]"\nsources:\n'
         '  - "unterminated\n---\n', None),
        ('---\nsources:\n  - "[[Doe_Foo_2025.pdf]]"\n'
         'sources:\n  - "https://example.com/clip"\n---\n', None),
        ('---\nsource: "[[Doe_Foo_2025.pdf]]"\n'
         'source: "https://example.com/clip"\n---\n', None),
        ('---\ntitle: no source here\n---\n', None),
        ('no frontmatter at all\n', None),
        ('\ufeff---\nsource: "[[Doe_Foo_2025.pdf]]"\n---\n',
         "[[Doe_Foo_2025.pdf]]"),
    ]
    for i, (body, want) in enumerate(_fm_cases):
        n += 1
        got = note_source(_note("fm_%d.md" % i, body))
        if got != want:
            bad += 1
            print("FAIL note_source(case %d) -> %r, expected %r"
                  % (i, got, want))
    invalid_frontmatter = _note_bytes(
        "invalid-frontmatter.md",
        b'---\ntitle: \xff\nsources:\n  - "[[Doe_Foo_2025.pdf]]"\n---\n')
    n += 1
    if note_source(invalid_frontmatter) is not None:
        bad += 1
        print("FAIL invalid UTF-8 in frontmatter established note ownership")
    invalid_body = _note_bytes(
        "invalid-body.md",
        b'---\nsources:\n  - "[[Doe_Foo_2025.pdf]]"\n---\n'
        b'![[Doe_Foo_2025.pdf]]\n\xff\n')
    n += 1
    if note_source(invalid_body) is not None:
        bad += 1
        print("FAIL invalid UTF-8 in the body established note ownership")
    n += 1
    if body_is_embed_only(invalid_body):
        bad += 1
        print("FAIL invalid UTF-8 was accepted as a legacy embed-only note")
    # A `---` inside a frontmatter VALUE must not shift the body window.
    n += 1
    if not body_is_embed_only(_note(
            "dashy.md",
            '---\ntitle: "A Study --- Part One"\n'
            'source: "[[Doe_Foo_2025.pdf]]"\n---\n![[Doe_Foo_2025.pdf]]\n')):
        bad += 1
        print("FAIL a `---` inside a frontmatter value defeated the "
              "legacy-embed probe")

    _img = os.path.join(_d, "images")
    os.makedirs(_img)
    for f in ("Doe_Foo_2025_fig_1.png", "doe_foo_2025_fig_10.png",
              "Doe_Foo_2025_fig_S1.png", "Doe_Foo_2025_2_fig_1.png",
              "Doe_Foo_2025_fig_1a.png", "Doe_Foo_2025_fig_1b.png",
              "Other_Paper_2020_fig_1.png"):
        open(os.path.join(_img, f), "w").close()
    n += 1
    got = [f["label"] for f in figures_for(_img, "Doe_Foo_2025")]
    # Case-folded portable matching, labels sliced off the raw name, and a stem that merely has this one as a
    # prefix (`_2`) kept out. Panels sit with their own figure.
    if got != ["1", "1a", "1b", "10", "S1"]:
        bad += 1
        print("FAIL figures_for labels -> %r, expected "
              "['1', '1a', '1b', '10', 'S1']" % got)
    # A panel carries the figure it belongs to; a whole figure carries None,
    # which is what lets a consumer prefer the composite (§8b).
    n += 1
    got = {f["label"]: f["panel_of"] for f in figures_for(_img, "Doe_Foo_2025")}
    want = {"1": None, "1a": "1", "1b": "1", "10": None, "S1": None}
    if got != want:
        bad += 1
        print("FAIL figures_for panel_of -> %r, expected %r" % (got, want))
    n += 1
    try:
        figures_for(os.path.join(_d, "no-such-folder"), "Doe_Foo_2025")
    except ValueError:
        pass
    else:
        bad += 1
        print("FAIL a missing figure folder was treated as a complete empty inventory")
    # A leaf symlink can resolve outside Sources/Images and `isfile()` follows
    # it. The shared inventory must keep that occupant visible while refusing
    # to hand it to the summarizer as an embeddable figure.
    outside_figure = os.path.join(_d, "outside.png")
    open(outside_figure, "wb").close()
    symlink_figure = os.path.join(_img, "Doe_Foo_2025_fig_99.png")
    symlink_supported = True
    try:
        os.symlink(outside_figure, symlink_figure)
    except (OSError, NotImplementedError):
        symlink_supported = False
    n += 1
    try:
        figures_for(_img, "Doe_Foo_2025")
    except ValueError as exc:
        symlink_blocked = "symlink" in str(exc) or symlink_figure in str(exc)
    else:
        symlink_blocked = False
    if symlink_supported:
        os.unlink(symlink_figure)
    if symlink_supported and not symlink_blocked:
        bad += 1
        print("FAIL a source-keyed leaf symlink was accepted as a figure")
    # NEAR MISS: distinct labels in a normal folder are never a collision.
    n += 1
    if any(f["duplicate_label"] for f in figures_for(_img, "Doe_Foo_2025")):
        bad += 1
        print("FAIL figures_for flagged a duplicate label among distinct labels")
    unicode_name = "Mu\u0308ller_Trial_2025_fig_1.png"
    open(os.path.join(_img, unicode_name), "w").close()
    n += 1
    unicode_figures = figures_for(_img, "Müller_Trial_2025")
    if [(f["file"], f["label"]) for f in unicode_figures] != [(unicode_name, "1")]:
        bad += 1
        print("FAIL figures_for lost a canonically equivalent Unicode filename")
    open(os.path.join(_img, "STRASSE_Trial_2025_fig_2.png"), "w").close()
    n += 1
    if [f["label"] for f in figures_for(_img, "Straße_Trial_2025")] != ["2"]:
        bad += 1
        print("FAIL casefold expansion shifted the figure label")
    # Two producers can legally occupy `<stem>_fig_2` at two extensions --
    # `Sources/Images/` is flat and shared, the files never collide on disk and
    # nothing deduplicates them -- so the skill picking a figure BY LABEL gets
    # two files for one label and no way to prefer either.  Nothing reported it.
    _img2 = os.path.join(_d, "images-dup")
    os.makedirs(_img2)
    for f in ("Dup_Paper_2025_fig_2.png", "Dup_Paper_2025_fig_2.webp",
              "Dup_Paper_2025_fig_S1.png", "Dup_Paper_2025_fig_s1.webp",
              "Dup_Paper_2025_fig_3.png"):
        open(os.path.join(_img2, f), "w").close()
    _dupfigs = figures_for(_img2, "Dup_Paper_2025")
    n += 1
    got = sorted(f["file"] for f in _dupfigs if f["duplicate_label"])
    want = ["Dup_Paper_2025_fig_2.png", "Dup_Paper_2025_fig_2.webp",
            "Dup_Paper_2025_fig_S1.png", "Dup_Paper_2025_fig_s1.webp"]
    if got != want:
        bad += 1
        print("FAIL figures_for duplicate_label -> %r, expected %r" % (got, want))
    n += 1
    if [f["duplicate_label"] for f in _dupfigs
            if f["file"] == "Dup_Paper_2025_fig_3.png"] != [False]:
        bad += 1
        print("FAIL figures_for flagged a label only one file claims")
    n += 1
    _rendered = render({"counts": {s: 0 for s in STATUSES},
                        "pdfs": [{"status": "new", "stem": "Dup_Paper_2025",
                                  "figures": _dupfigs}]})
    if "duplicate label 2" not in _rendered \
            or "Dup_Paper_2025_fig_2.webp" not in _rendered:
        bad += 1
        print("FAIL render() did not report the duplicate label:\n%s" % _rendered)

    # render() counts whole figures and panels apart, and lists the whole
    # ones.  A bare `figures: 27` beginning `1, 1a, 1b` reads as 27 exhibits,
    # which is what makes a note treat every panel as a candidate and a report
    # call 23 of them unused (references/figures.md).
    _panelfigs = [{"label": "1", "panel": None, "panel_of": None,
                   "file": "Doe_Foo_2025_fig_1.png", "ext": ".png"},
                  {"label": "1a", "panel": "a", "panel_of": "1",
                   "file": "Doe_Foo_2025_fig_1a.png", "ext": ".png"},
                  {"label": "1b", "panel": "b", "panel_of": "1",
                   "file": "Doe_Foo_2025_fig_1b.png", "ext": ".png"},
                  {"label": "2", "panel": None, "panel_of": None,
                   "file": "Doe_Foo_2025_fig_2.png", "ext": ".png"}]
    _rendered = render({"counts": {s: 0 for s in STATUSES},
                        "pdfs": [{"status": "new", "stem": "Doe_Foo_2025",
                                  "figures": _panelfigs}]})
    n += 1
    if "figures: 2" not in _rendered:
        bad += 1
        print("FAIL render() counted panels as figures:\n%s" % _rendered)
    n += 1
    if "2 panel(s) of them, in 4 file(s)" not in _rendered:
        bad += 1
        print("FAIL render() did not report the panels:\n%s" % _rendered)
    n += 1
    if "1a" in _rendered:
        bad += 1
        print("FAIL render() listed a panel among the figure labels:\n%s"
              % _rendered)
    # NEAR MISS: a stem with no panels must not grow a panel clause.
    n += 1
    if "panel(s)" in render({"counts": {s: 0 for s in STATUSES},
                             "pdfs": [{"status": "new", "stem": "Doe_Bar_2025",
                                       "figures": _panelfigs[:1]}]}):
        bad += 1
        print("FAIL render() reported panels for a stem that has none")

    # --- scan(), end to end, over a vault holding both note kinds ---------
    _v = os.path.join(_d, "vault")
    for sub in ("Sources/PDFs/Prince_UDL_2026", "Sources/PDFs/Kuhn_X_2012",
                "Articles", "Sources/Images"):
        os.makedirs(os.path.join(_v, *sub.split("/")))

    def _mk(rel, body=""):
        p = os.path.join(_v, *rel.split("/"))
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(body)

    _mk("Sources/PDFs/Doe_Foo_2025.pdf")
    _mk("Sources/PDFs/Smith_Done_2024.pdf")
    _mk("Sources/PDFs/Graham_Clip_2012.pdf")
    _mk("Sources/PDFs/Legacy_Old_2019.pdf")
    _mk("Sources/PDFs/Link_Occupied_2025.pdf")
    _mk("Sources/PDFs/Dir_Occupied_2025.pdf")
    _mk("Sources/PDFs/Case_Owner_2025.pdf")
    _mk("Sources/PDFs/Case_Foreign_2025.pdf")
    os.symlink(os.path.join(_v, "missing.md"),
               os.path.join(_v, "Articles", "Link_Occupied_2025.md"))
    os.makedirs(os.path.join(_v, "Articles", "Dir_Occupied_2025.md"))
    _mk("Sources/PDFs/Prince_UDL_2026_src.pdf")
    _mk("Sources/PDFs/Prince_UDL_2026/Prince_UDL_2026_01_Intro.pdf")
    # The same pairing with the two halves spelled in different cases.
    # pdf-figure-extractor pairs these; this scan called the book `new`.
    _mk("Sources/PDFs/Kuhn_X_2012.pdf")
    _mk("Sources/PDFs/Kuhn_X_2012/kuhn_x_2012_01_Intro.pdf")
    _mk("Articles/Smith_Done_2024.md",
        '---\nsource: "[[Smith_Done_2024.pdf]]"\n---\n\n## Methods\n\nx\n')
    _mk("Articles/Graham_Clip_2012.md",
        '---\nsource: https://example.com/g\n---\nprose\n')
    _mk("Articles/Legacy_Old_2019.md",
        '---\nsource: "[[Legacy_Old_2019.pdf]]"\n---\n![[Legacy_Old_2019.pdf]]\n')
    # The same three states in the CURRENT 2b schema (block-form `sources:`),
    # which is what this skill's own step 5 writes.  Before the sources-list
    # reader, all three of these classified as `collision`.
    _mk("Sources/PDFs/Doe_New_2025.pdf")
    _mk("Articles/Doe_New_2025.md",
        '---\ntitle: x\nformat: Paper\nsources:\n'
        '  - "[[Doe_New_2025.pdf#page=1]]"\n---\n\n## Methods\n\nx\n')
    _mk("Sources/PDFs/Clip_Match_2024.pdf")
    _mk("Articles/Clip_Match_2024.md",
        '---\ntitle: x\nsources:\n  - "https://example.com/clip"\n---\nprose\n')
    _mk("Sources/PDFs/Embed_Old_2019.pdf")
    _mk("Articles/Embed_Old_2019.md",
        '---\nsources:\n  - "[[Embed_Old_2019.pdf]]"\n---\n'
        '![[Embed_Old_2019.pdf]]\n')
    _mk("Articles/case_owner_2025.md",
        '---\nsources:\n  - "[[Case_Owner_2025.pdf]]"\n---\n'
        '\n## Methods\n\nA completed summary.\n')
    _mk("Articles/case_foreign_2025.MD",
        '---\nsources:\n  - "https://example.com/foreign"\n---\n'
        'A clipping.\n')
    res = scan(os.path.join(_v, "Sources", "PDFs"),
               os.path.join(_v, "Articles"),
               os.path.join(_v, "Sources", "Images"))
    by_stem = {r["stem"]: r["status"] for r in res["pdfs"]}
    for stem, want in (("Doe_Foo_2025", "new"),
                       ("Smith_Done_2024", "done"),
                       ("Graham_Clip_2012", "collision"),
                       ("Legacy_Old_2019", "legacy"),
                       ("Link_Occupied_2025", "collision"),
                       ("Dir_Occupied_2025", "collision"),
                       ("Doe_New_2025", "done"),
                       ("Clip_Match_2024", "collision"),
                       ("Embed_Old_2019", "legacy"),
                       ("Case_Owner_2025", "done"),
                       ("Case_Foreign_2025", "collision"),
                       ("Prince_UDL_2026_src", "book"),
                       ("Prince_UDL_2026_01_Intro", "chapter"),
                       ("Kuhn_X_2012", "book"),
                       ("kuhn_x_2012_01_Intro", "chapter")):
        n += 1
        if by_stem.get(stem) != want:
            bad += 1
            print("FAIL scan(): %s -> %r, expected %r"
                  % (stem, by_stem.get(stem), want))
    n += 1
    if sum(res["counts"].values()) != len(res["pdfs"]):
        bad += 1
        print("FAIL scan(): the counts do not add up to the rows")
    n += 1
    # `render` reads a key per status; a status added to `classify` and not to
    # STATUSES would KeyError here rather than in front of a user.
    try:
        render(res)
    except Exception as exc:
        bad += 1
        print("FAIL render(): %s: %s" % (type(exc).__name__, exc))

    for sub in ("Sources/PDFs/first", "Sources/PDFs/second"):
        os.makedirs(os.path.join(_v, *sub.split("/")))
    _mk("Sources/PDFs/first/Dup_Study_2025.pdf", "first paper")
    _mk("Sources/PDFs/second/dup_study_2025.pdf", "different paper")
    conflicted = scan(os.path.join(_v, "Sources", "PDFs"),
                      os.path.join(_v, "Articles"), os.path.join(_v, "Sources", "Images"))
    duplicates = [row for row in conflicted["pdfs"]
                  if _name_key(row["stem"]) == "dup_study_2025"]
    n += 1
    if len(duplicates) != 2 or any(row["status"] != "collision"
                                    or len(row["source_conflicts"]) != 1 for row in duplicates):
        bad += 1
        print("FAIL two PDFs with one basename were allowed to share an output note")
    n += 1
    if "shares this PDF basename" not in render(conflicted):
        bad += 1
        print("FAIL source collisions did not explain the conflicting PDF paths")

    import contextlib
    import io
    from unittest.mock import patch

    # Articles has one portable basename namespace even on a case-sensitive
    # host. Exercise the inventory with spellings that such a host can store
    # side by side; NFD/NFC and extension case must collapse identically.
    portable_names = [
        "Doe_Study_2025.md", "doe_study_2025.MD",
        "Mu\u0308ller_Study_2025.md", "Müller_Study_2025.md",
        "unrelated.txt",
    ]
    with patch.object(os, "listdir", return_value=portable_names):
        portable_index = article_note_index("/Articles")
    expected_groups = {
        _name_key("Doe_Study_2025.md"): 2,
        _name_key("Müller_Study_2025.md"): 2,
    }
    n += 1
    if ({key: len(paths) for key, paths in portable_index.items()}
            != expected_groups):
        bad += 1
        print("FAIL Articles inventory did not collapse portable note names: %r"
              % portable_index)

    # Multiple portable-equivalent notes are ambiguous even when the exact
    # spelling is absent. No arbitrary candidate may establish ownership.
    one_pdf = os.path.join(_v, "Sources", "PDFs", "Doe_Foo_2025.pdf")
    duplicate_notes = {
        _name_key("Doe_Foo_2025.md"): [
            os.path.join(_v, "Articles", "Doe_Foo_2025.md"),
            os.path.join(_v, "Articles", "doe_foo_2025.MD"),
        ]
    }
    with patch(__name__ + ".article_note_index",
               return_value=duplicate_notes):
        duplicate_result = scan(
            one_pdf, os.path.join(_v, "Articles"),
            os.path.join(_v, "Sources", "Images"))
    duplicate_row = duplicate_result["pdfs"][0]
    n += 1
    if (duplicate_row["status"] != "collision"
            or duplicate_row["note_conflicts"] != duplicate_notes[
                _name_key("Doe_Foo_2025.md")]):
        bad += 1
        print("FAIL portable-equivalent Articles notes had an arbitrary owner: %r"
              % duplicate_row)
    n += 1
    if "portable case/Unicode identity" not in render(duplicate_result):
        bad += 1
        print("FAIL portable note collision was not explained in the report")

    # One NFD-spelled note can own the NFC-spelled PDF destination. Looking up
    # only the literal target path reports this as `new` on a sensitive host.
    unicode_pdf = os.path.join(
        _v, "Sources", "PDFs", "Müller_Owner_2025.pdf")
    _mk("Sources/PDFs/Müller_Owner_2025.pdf")
    _mk("Articles/Mu\u0308ller_Owner_2025.md",
        '---\nsources:\n  - "[[Müller_Owner_2025.pdf]]"\n---\n'
        '\n## Methods\n\nA completed summary.\n')
    unicode_result = scan(
        unicode_pdf, os.path.join(_v, "Articles"),
        os.path.join(_v, "Sources", "Images"), allow_unorganized=True)
    unicode_row = unicode_result["pdfs"][0]
    n += 1
    if (unicode_row["status"] != "done"
            or _name_key(os.path.basename(unicode_row["note"]))
            != _name_key("Müller_Owner_2025.md")):
        bad += 1
        print("FAIL NFD Articles note did not own its NFC PDF destination: %r"
              % unicode_row)

    # The public command must use the complete on-disk stem. Stripping a
    # second extension falsely accepted these unorganized PDF filenames.
    for stem in ("Edge_Source_2025", "Edge_Source_2025.revised", "Edge_Source_2025.pdf"):
        _mk("Sources/PDFs/%s.pdf" % stem)
    _mk("Sources/PDFs/Mixed_Origin_2025.pdf")
    _mk("Articles/Mixed_Origin_2025.md",
        '---\nsource: "[[Mixed_Origin_2025.pdf]]"\nsources:\n'
        '  - "https://example.com/separate-clipping"\n---\nUser-edited article.\n')
    argv = ["--src", os.path.join(_v, "Sources", "PDFs"),
            "--notes", os.path.join(_v, "Articles"),
            "--images", os.path.join(_v, "Sources", "Images"), "--json"]
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = main(argv)
    actual = {row["stem"]: row["status"]
              for row in json.loads(output.getvalue())["pdfs"]}
    for stem, expected in (("Edge_Source_2025", "new"),
                           ("Edge_Source_2025.revised", "unorganized"),
                           ("Edge_Source_2025.pdf", "unorganized"),
                           ("Mixed_Origin_2025", "collision")):
        n += 1
        if code != 0 or actual.get(stem) != expected:
            bad += 1
            print("FAIL public scan(): %s -> %r, expected %s"
                  % (stem, actual.get(stem), expected))

    # Real directory enumeration errors must not become clean inventories.
    # The independent integration fixture also exercises these with chmod000.
    scandir, listdir = os.scandir, os.listdir
    for blocked in (os.path.join(_v, "Sources", "PDFs", "first"),
                    os.path.join(_v, "Sources", "Images"),
                    os.path.join(_v, "Articles")):
        def denied_scan(path):
            if os.path.abspath(os.fspath(path)) == os.path.abspath(blocked):
                raise PermissionError(13, "permission denied", path)
            return scandir(path)

        def denied_list(path):
            if os.path.abspath(os.fspath(path)) == os.path.abspath(blocked):
                raise PermissionError(13, "permission denied", path)
            return listdir(path)

        output, errors = io.StringIO(), io.StringIO()
        with patch.object(os, "scandir", side_effect=denied_scan), \
                patch.object(os, "listdir", side_effect=denied_list), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = main(argv)
        n += 1
        if code != 2 or output.getvalue() or blocked not in errors.getvalue():
            bad += 1
            print("FAIL unreadable directory was reported as a complete scan: %s" % blocked)

    print("%d/%d self-test cases pass" % (n - bad, n))
    return 1 if bad else 0


def _build_parser():
    p = argparse.ArgumentParser(
        description="Which PDFs to summarise, and what figures they already "
                    "have.")
    p.add_argument("--src", help="a PDF, or a folder walked recursively")
    p.add_argument("--notes", help="the Articles/ folder this skill writes to")
    p.add_argument("--images", help="the flat Sources/Images/ folder")
    p.add_argument("--allow-unorganized", action="store_true",
                   help="scan PDFs pdf-organizer has not named (see §1a)")
    p.add_argument("--include-split-books", action="store_true",
                   help="do not skip a book whose chapters are in the scan")
    p.add_argument("--include-chapters", action="store_true",
                   help="sweep book chapters too (implied when --src is a file)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--test", action="store_true", help="run the self-test")
    return p


def main(argv=None):
    args = _build_parser().parse_args(argv)
    if args.test:
        return run_self_test()
    missing = [f for f in ("src", "notes", "images")
               if not getattr(args, f)]
    if missing:
        print("missing required argument(s): %s"
              % ", ".join("--" + m for m in missing), file=sys.stderr)
        return 2
    for flag, path, must_exist in (("--src", args.src, True),
                                   ("--images", args.images, True),
                                   ("--notes", args.notes, True)):
        # A mistyped folder must not read as "empty".  `--src` would report a
        # clean zero-work run, `--images` would report every stem as having
        # no figures (which SKILL.md step 1 reads as "the extractor has not
        # run"), and `--notes` would turn every `done`, `collision` and
        # `legacy` into `new` -- disabling the whole overwrite guard while
        # reporting a healthy run. Create the folder before scanning; this
        # script does not, because a typo would create the typo.
        # `isdir`, not `exists`: a path that is a *file* satisfies `exists`
        # and then lists nothing, which is the silent-empty case this guard
        # is here to stop.  `--src` is the one that may legitimately be a
        # file, so it is checked as either.
        ok = os.path.isdir(path) or (flag == "--src" and os.path.isfile(path))
        if must_exist and not ok:
            print("%s is not a directory: %s. Nothing was scanned; this is "
                  "not an empty vault." % (flag, path), file=sys.stderr)
            return 2
    try:
        result = scan(args.src, args.notes, args.images,
                      args.allow_unorganized, args.include_split_books,
                      True if args.include_chapters else None)
    except ValueError as exc:
        print("%s Nothing was scanned; this is not an empty vault." % exc,
              file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2) if args.json else render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
