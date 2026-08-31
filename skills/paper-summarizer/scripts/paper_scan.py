#!/usr/bin/env python3
"""What to summarise, and which figures are already on disk for it.

One filesystem pass, before any PDF is opened, answers the three questions
that decide a run:

  * **Which PDFs are in scope, and which are already summarised.**  A paper is
    done iff `Articles/<pdf stem>.md` exists **and that note's `sources:` item 1
    (or its legacy scalar `source:`) names this PDF**.  The second half is not
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

`--notes` is `Articles/`, which this skill shares with clipping-processor, so a
note already at the target name is not automatically ours: `source:` decides,
and a note belonging to something else is a `collision`, never an overwrite.

Add `--json` for the machine-readable form, `--test` to run the self-test.
Three overrides relax a skip: `--allow-unorganized`, `--include-split-books`
and `--include-chapters`.
Naming a single PDF processes it whatever it is -- explicit naming overrides
every folder filter, so a named chapter is a `new`, not a `chapter`.
"""

# --- obsidian shared-layer bootstrap (canonical; see shared/CONVENTIONS.md) ---
import os as _os, sys as _sys
_here = _os.path.dirname(_os.path.abspath(__file__))
_env = _os.environ.get("OBSIDIAN_VAULT_SHARED")
if _env:                                   # explicit override: authoritative, no fallback
    _tried = [_os.path.abspath(_os.path.expanduser(_env))]
else:                                      # plugin-relative walk-up, at most 5 levels
    _tried, _d = [], _here
    for _ in range(5):
        _tried.append(_os.path.join(_d, "shared", "scripts"))
        _d = _os.path.dirname(_d)
_shared = next((_p for _p in _tried if _os.path.isdir(_p)), None)
if _shared is None:
    raise SystemExit("""obsidian: cannot find the plugin's shared/scripts/ folder, which holds
the one canonical copy of the conventions this script depends on.
Looked for:
  %s
Fix: install the whole plugin tree, or set OBSIDIAN_VAULT_SHARED to the
shared/scripts/ directory (unset it to use the plugin-relative walk-up).
Do NOT paste a second copy of the algorithm into this skill -- a divergent
copy is the bug the shared layer exists to prevent.""" % "\n  ".join(_tried))
_sys.path[:] = [_p for _p in _sys.path if _p not in (_shared, _here)]
_sys.path.insert(0, _shared)               # shared/scripts/ FIRST
_sys.path.append(_here)                    # own dir LAST: a local copy cannot shadow it
# --- end bootstrap ---

import argparse
import json
import os
import re
import sys
import unicodedata

from naming import chapter_book_stem, core_stem, looks_canonical, stem_of
from yaml_scalars import parse_scalar

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
_SOURCES_KEY_RE = re.compile(r"\Asources\s*:\s*(?:#.*)?\Z", re.I)
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
    stem_key = _name_key(stem)
    fold = stem_key + "_fig"
    try:
        names = sorted(os.listdir(attachments))
    except OSError:
        return []
    out = []
    for name in names:
        # Case-folded on both sides, for the reason organize.py matches that
        # way: the documented vault sits on a case-insensitive volume, so a
        # figure written `doe_foo_2025_fig_1.png` IS this stem's. Missing it
        # reports zero figures, which SKILL.md step 1 reads as "the extractor
        # never ran" -- a wrong diagnosis that ships a figureless note.
        if not _name_key(name).startswith(fold):
            continue
        if not os.path.isfile(os.path.join(attachments, name)):
            continue
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
    # no basis to prefer either, and until now nothing told it so.  Folded,
    # because the vault's volume is case-insensitive: `_fig_S1.png` beside
    # `_fig_s1.webp` is the same ambiguity.
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
    parseable.
    """
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            for first in fh:
                if first.strip():
                    break
            else:
                return None
            if first.strip() != "---":
                return None
            found = None
            pending = False
            for line in fh:
                if line.strip() == "---":
                    return found or None   # the fence closed: it is ours
                if found is None:
                    raw = line.rstrip("\n")
                    if pending:
                        # Blank and comment-only lines between `sources:` and
                        # its first item are valid YAML (Obsidian still reads
                        # item 1); consuming the flag on one left the real item
                        # unread and the note classified `collision`.  The
                        # sibling readers (dedup_index, organize) skip the same way.
                        if not raw.strip() or raw.lstrip().startswith("#"):
                            continue
                        pending = False
                        mi = _SOURCES_ITEM_RE.match(raw)
                        if mi:
                            found = _yaml_scalar(mi.group(1))
                            continue
                    if _SOURCES_KEY_RE.match(raw):
                        pending = True     # the origin is the NEXT line
                        continue
                    m = _SOURCE_RE.match(raw)
                    if m:
                        found = _yaml_scalar(m.group(1))
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
        with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            text = fh.read()
    except OSError:
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

    A URL is False (it is a clipping note).  A wikilink to a *different*
    document is False.  Case-folded, because the documented vault sits on a
    case-insensitive volume and Obsidian resolves links that way too.
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
    """Every `.pdf` at or under `src`, path-sorted.  A file `src` is itself.

    A non-PDF file as `--src` raises rather than returning nothing: a clean
    zero-work run is exactly what the `--src` guard exists to stop, and a
    mistyped path that happens to hit a `.md` produced one.
    """
    if os.path.isfile(src):
        if not src.lower().endswith(".pdf"):
            raise ValueError("%s is a file but not a .pdf; --src takes a PDF or "
                             "a folder of them" % src)
        return [src]
    out = []
    for root, dirs, files in os.walk(src):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(files):
            if name.lower().endswith(".pdf") and not name.startswith("."):
                out.append(os.path.join(root, name))
    return sorted(out)


def books_in(stems):
    """Core stems that some *other* stem in the same set is a chapter of.

    Case-FOLDED, for the reason `batch_extract.split_book_chapters` folds:
    the documented vault sits on a case-insensitive volume, where
    `kuhn_x_2012_01_Intro.pdf` really is a chapter of `Kuhn_X_2012.pdf`.  The
    two skills split the same folder and disagreeing is worse than either
    answer — the extractor skipped the book and this scan called it `new`, so
    the model was routed to extract from the book alone, writing byte-identical
    figures under two stems that never collide and never deduplicate (§8).
    Three other comparisons in this file already fold; this one did not.
    """
    return {_name_key(b) for b in (chapter_book_stem(s) for s in stems) if b}


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
    if _name_key(core_stem(stem)) in {_name_key(b) for b in books} \
            and not include_books:
        return "book"
    if chapter_book_stem(stem) and not include_chapters:
        return "chapter"
    if not looks_canonical(stem) and not allow_unorganized:
        return "unorganized"
    if note_state == "theirs":
        return "collision"
    if note_state == "legacy":
        return "legacy"
    return "done" if note_state == "ours" else "new"


def scan(src, notes, images, allow_unorganized=False,
         include_books=False, include_chapters=None):
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
        note = os.path.join(notes, stem + ".md")
        if not os.path.lexists(note):
            state, existing = "absent", None
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
        # that calls twenty-three of them unused (SKILL.md steps 4 and 12).
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
            lines.append("      its chapters are in this scan and are the unit "
                         "to summarise; the book's own stem has no figures")
        if row["status"] == "collision":
            if row.get("source_conflicts"):
                lines.append("      %s shares this PDF basename and the same "
                             "output note: %s. Nothing may be written until "
                             "pdf-organizer gives the sources distinct names."
                             % (", ".join(row["source_conflicts"]), row["note"]))
            else:
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
    # A book whose chapters are spelled in another case is still its chapters'
    # book: the vault's volume is case-insensitive, and pdf-figure-extractor
    # pairs them.  Raw-string comparison called this book `new`, so the model
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

    def _note(name, body):
        p = os.path.join(_d, name)
        with open(p, "w", encoding="utf-8") as fh:
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
    # Case-folded matching (the vault is on a case-insensitive volume), the
    # labels sliced off the RAW name, and a stem that merely has this one as a
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
    if figures_for(os.path.join(_d, "no-such-folder"), "Doe_Foo_2025") != []:
        bad += 1
        print("FAIL figures_for on a missing folder should be empty")
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
    # call 23 of them unused (SKILL.md steps 4 and 12).
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
    os.symlink(os.path.join(_v, "missing.md"),
               os.path.join(_v, "Articles", "Link_Occupied_2025.md"))
    os.makedirs(os.path.join(_v, "Articles", "Dir_Occupied_2025.md"))
    _mk("Sources/PDFs/Prince_UDL_2026_src.pdf")
    _mk("Sources/PDFs/Prince_UDL_2026/Prince_UDL_2026_01_Intro.pdf")
    # The same pairing with the two halves spelled in different cases, which is
    # what a real vault on a case-insensitive volume holds.  pdf-figure-extractor
    # pairs these; this scan called the book `new`.
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
