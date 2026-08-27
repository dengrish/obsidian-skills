#!/usr/bin/env python3
"""Check a paper-summarizer note against the fixed format of SKILL.md step 11.

Prose cannot hold a format steady across notes written weeks apart.  Every rule
below is one the shape has already drifted on -- an extra heading, a blank line
above the callout, a quoted `read`, a caption pushed one line down -- and each
drift is invisible from inside the note that has it.

    python3 note_lint.py '<note.md>'
    python3 note_lint.py '<note.md>' --images '<vault>/Sources/Images'
    python3 note_lint.py --test

Exit 0 clean, 1 with one line per violation, 2 for a bad invocation.

Stdlib only, no import-time effects.  The YAML is parsed by hand: the schema is
ten known keys with known shapes, PyYAML is not on a stock macOS, and a real
parser would accept plenty this format does not.
"""

import argparse
import datetime
import os
import re
import sys

# --- the format, as data -----------------------------------------------------

# CONVENTIONS.md 2b, in order.  No key is optional; the `sources` list holds
# the PDF wikilink first, then any printed DOI/arXiv URL as item 2.
SCHEMA = ("title", "format", "sources", "author", "published",
          "created", "description", "tags", "read")
OPTIONAL_KEYS = frozenset()

# SKILL.md step 7.  Six sections, always these roles, always this order -- but
# the *heading text* is written per paper, a short sentence about what that
# section says.  Position is what carries the role, so these names never appear
# in a note; they are what the note's sections are, not what they are called.
ROLES = ("Question", "Methods", "Results",
         "Interpretation", "Limitations", "Availability")

# The sections that are bullet lists rather than paragraphs, by position.
BULLET_ROLES = frozenset({"Limitations", "Availability"})

# A heading is a short sentence, so: long enough to say something, short enough
# to scan in Obsidian's outline pane, and more than one word.
MIN_HEADING, MAX_HEADING = 20, 90
MIN_HEADING_WORDS = 3

# Falling back to the role name is the failure this whole rule exists to stop --
# and it is what an unattended run reaches for first.  Anything here, alone on
# a heading line, is a label rather than a description.
GENERIC_HEADINGS = frozenset({
    "question", "methods", "method", "results", "result", "interpretation",
    "limitations", "availability", "background", "introduction", "discussion",
    "conclusion", "conclusions", "abstract", "summary", "findings", "aims",
    "objective", "objectives", "design", "study design", "what they did",
    "what they found", "what it means", "what they wanted to find out",
    "data and code", "provenance", "materials and methods", "key messages",
    "overview", "analysis", "implications", "caveats", "the question",
    "the study", "the findings", "data", "code", "references",
})

# SKILL.md step 5: this note's enum, not a clipping's Article/Post/Video.
FORMATS = ("Paper", "Book", "Report")

# CONVENTIONS.md 3.  Stated here as data because this script is the thing that
# enforces it; the prose home is CONVENTIONS.md and the harness checks they agree.
TAG_ENUM = (
    "mathematics", "statistics", "physics", "chemistry", "biology",
    "earth-science", "medicine", "engineering", "computer-science",
    "psychology", "sociology", "anthropology", "economics", "finance",
    "political-science", "linguistics", "history", "philosophy", "literature",
    "law", "business", "entrepreneurship", "education", "architecture", "art", "music",
    "machine-learning",
)

# SKILL.md step 8: Limitations is the one section with a cap, because a list
# nobody reads to the end of buries the item that mattered.
MIN_LIMITATIONS, MAX_LIMITATIONS = 2, 4
# Step 9: data, code, and materials only.
MIN_AVAILABILITY, MAX_AVAILABILITY = 1, 3
MAX_LIMITATION_CHARS = 420

#: The house sentence limits: 25 words of prose, 20 inside a numbered step
#: (SKILL.md step 7a).  The cap used to be 45, chosen as a generous edge around
#: a 30-word target; a third of the sentences in a finished note still sat
#: above 25, and those were the ones that had to be read twice.  These two
#: numbers came in with a controlled-language standard that this skill no
#: longer follows -- they stayed because the prose they produce is what the
#: vault wanted, not because a specification asked for them.
MAX_SENTENCE_WORDS = 25
MAX_STEP_WORDS = 20

#: One topic per paragraph, six sentences at most.  A markdown paragraph here
#: is one line, so this is a per-line count.
MAX_PARAGRAPH_SENTENCES = 6

#: Methods carries the experiment as numbered steps.  Fewer than three is not a
#: procedure; more than eight is the paper's methods section copied across.
MIN_STEPS = 3
MAX_STEPS = 8

#: A numbered step: `1. The team measured 24 mutants.`
_STEP = re.compile(r"\A(\d+)\.\s+(.*)\Z")

#: Results prose -- what is left after the embeds, the captions and the rebuilt
#: tables -- over this many characters is a Results carrying more than one
#: finding.  The section used to have no cap at all, on the reasoning that a
#: paper with four experiments gets four; the cost was a section nobody read to
#: the end of.  The rule now is one finding developed properly, with the
#: secondary ones at a sentence each (SKILL.md step 7), and this is what makes
#: that a fact rather than an intention.  Exhibits are excluded because a
#: figure and its caption are how a result gets shorter, not longer.
MAX_RESULTS_CHARS = 2400

#: Tokens that end in a period without ending a sentence.  Compared
#: case-folded, after trailing markup is stripped.
_ABBREVIATIONS = frozenset({
    "e.g.", "i.e.", "cf.", "vs.", "al.", "approx.", "ca.", "no.", "eq.",
    "ref.", "refs.", "vol.", "pp.", "st.", "dr.", "prof.", "sp.", "spp.",
    "min.", "max.", "ml.", "mg.", "fig.", "figs.", "tab.", "sect.", "ver.",
})

MAX_DESCRIPTION = 110
MAX_FIGURES = 4
MAX_TABLES = 4
MIN_BULLETS, MAX_BULLETS = 3, 7

# Self-test sentinel: this case must produce no findings at all.
CLEAN = object()

# A horizontal rule in any spelling CommonMark accepts, other than our `___`.
_OTHER_RULE = re.compile(r"\A(?:-\s*-\s*-[-\s]*|\*\s*\*\s*\*[\*\s]*|_\s*_\s*_[_\s]*)\Z")
_DATE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")
_EMBED = re.compile(r"\A!\[\[([^\]]+)\]\]\Z")
# `[[Stem.pdf#page=5|5]]` -- group 1 the target, group 2 the display text if any.
_PAGE_LINK = re.compile(r"\[\[([^\]|]*#page=\d+)(?:\|([^\]]*))?\]\]")
# The whole citation: the link wrapped in <sup>, which is how Obsidian renders a
# superscript.  Nothing between the tags and the brackets.
_CITATION = re.compile(r"<sup>\[\[[^\]|]*#page=\d+(?:\|[^\]]*)?\]\]</sup>")
# An exhibit number in any spelling: "Figure 2", "Fig. 1.2", "FIGURE S1",
# "Figures 2 and 3", "Supplementary Figure 1", "Extended Data Figure 1", and the
# same for tables.  No trailing delimiter is required: "Figure 2 The arms
# separated" is still a numbered caption.
_MARK = r"(?:supplementary\s+|suppl\.?\s*|supp\.?\s*|extended\s+data\s+)?"
_NUM = r"\s*[A-Za-z]?[0-9]+(?:[.\-][0-9A-Za-z]+)*"
_FIG_NUM_BODY = _MARK + r"fig(?:ure|\.)?s?" + _NUM
_TAB_NUM_BODY = _MARK + r"tab(?:le|\.)?s?" + _NUM
# `_EXHIBIT_NUM` matches one anywhere in a line; `_CAP_NUM` only at the head of
# a caption, where it is the classic "Figure 2 -- " label.
_CAP_NUM = re.compile(r"\A\*?\s*[(\[]?\s*(?:" + _FIG_NUM_BODY + r"|"
                      + _TAB_NUM_BODY + r")", re.I)
# The SINGULAR spellings only.  `_EXHIBIT_NUM`'s first alternative must not
# carry the `s?`, or it matches every plural first and the range-required
# branch below is unreachable -- which is what it was: "the revenue figures
# 2024" was reported as a pointer at Figure 2024, and the rule stated below was
# never in force.  `_FIG_NUM_BODY`/`_TAB_NUM_BODY` keep their `s?` because
# `_CAP_NUM` needs it: a caption opening "Figures 2 and 3 --" is an exhibit
# label whatever else is true of the plural.
_FIG_NUM_ONE = _MARK + r"fig(?:ure|\.)?" + _NUM
_TAB_NUM_ONE = _MARK + r"tab(?:le|\.)?" + _NUM
# The plural forms -- "figures 45% and 8%", "the revenue figures 2024" -- are
# where this over-fires: "figures" is an ordinary English word for numbers.  A
# reference to an exhibit is singular ("Figure 2") or an explicit range
# ("Figures 2 and 3", "Figures 2-4"); a plural followed by a bare number that
# is not part of a range is prose.  The second alternative is where every
# plural now lands, so a range still fires -- and fires on the WHOLE range,
# which is what the finding then quotes back.
_EXHIBIT_NUM = re.compile(
    r"\b(?:(?:" + _FIG_NUM_ONE + r"|" + _TAB_NUM_ONE + r")"
    r"(?![0-9]*\s*%)"                       # "figure 45%" is prose
    r"|\b(?:fig(?:ure)?s|tab(?:le)?s)\s*[A-Za-z]?[0-9]+"
    r"(?:\s*(?:-|–|to|and|,)\s*[A-Za-z]?[0-9]+)+)", re.I)
# A bare URL, stripped before the exhibit sweep: `.../figures/fig2` is a path
# segment, not a pointer out of the note.
_URLS = re.compile(r"(?:https?://|www\.)\S+|\b[\w.-]+\.(?:com|org|net|io|ai)/\S*")
# A markdown table row: a leading pipe and at least two cells.  Prose that
# happens to open with a pipe -- `|d| > 0.8 marked a large effect` -- is not a
# table, and treating it as one produced two findings on a correct sentence.
_TABLE_ROW = re.compile(r"\A\s*\|.*\|\s*\Z")
# The `|---|---|` row.  A pipe block without one renders as literal pipes.
_TABLE_SEP = re.compile(r"\A\s*\|(?:\s*:?-{2,}:?\s*\|)+\s*\Z")
# A footnote marker or definition.  Matched, not substring-searched: `[^a-z]` in
# an inline code span is a character class, not a footnote.
_FOOTNOTE = re.compile(r"\[\^[0-9]+\]|\A\[\^[^\]]+\]:")


def _fenced(lines):
    """Line numbers inside ``` or ~~~ fences.

    Nothing inside a fence is note structure: a `##` in a shell comment is not a
    section, a `|` in a table of output is not a table, and a `___` in a code
    sample is not the rule.  Left unhandled, one fence in Methods cascades into
    a dozen findings against correct text.
    """
    inside, fence, out = False, None, set()
    for n, l in enumerate(lines):
        s = l.strip()
        m = re.match(r"\A(`{3,}|~{3,})", s)
        if m and (not inside or s.startswith(fence)):
            if inside:
                inside, fence = False, None
            else:
                inside, fence = True, m.group(1)
            out.add(n)
            continue
        if inside:
            out.add(n)
    return out


def _is_caption(line):
    """An italic caption line: opened by one `*`, closed by one, not empty.

    The close is the fiddly half.  A caption legitimately ends on an emphasised
    term -- a species name, a bolded value -- so the last run of asterisks may
    be longer than one; what disqualifies a line is opening with `**`, which is
    bold rather than a caption.
    """
    s = line.rstrip()
    if not s.startswith("*") or s.startswith("**") or not s.endswith("*"):
        return False
    return len(s.strip("*").strip()) > 0


class Note(object):
    """One parsed note.  Nothing here raises; a malformed note is findings."""

    def __init__(self, text, path="<note>"):
        self.path = path
        self.text = text
        self.raw_lines = text.split("\n")
        self.findings = []

    def fail(self, line, msg):
        """`line` is 1-indexed, or 0 when the finding is about the whole file."""
        self.findings.append((line, msg))


def _split_front_matter(note):
    """Return (keys, kv, body_start) -- body_start is a 0-indexed line number.

    A note with no readable front matter still lints its body: reporting one
    error and stopping hides every other defect behind the first one.
    """
    lines = note.raw_lines
    if not lines or lines[0] != "---":
        note.fail(1, "file must open with `---` on line 1 "
                     "(no blank line, no BOM, nothing above it)")
        return [], {}, 0
    end = None
    for i in range(1, len(lines)):
        if lines[i] == "---":
            end = i
            break
    if end is None:
        note.fail(1, "front matter is never closed by a `---` line")
        return [], {}, 1
    keys, kv, cur = [], {}, None
    for i in range(1, end):
        line = lines[i]
        if not line.strip():
            continue
        m = re.match(r"\A([A-Za-z_][A-Za-z0-9_-]*):(.*)\Z", line)
        if m and not line.startswith((" ", "\t", "-")):
            cur = m.group(1)
            keys.append(cur)
            kv[cur] = [m.group(2).strip(), []]
        elif cur is not None:
            kv[cur][1].append(line)
            if cur not in ("author", "tags", "sources") and not line.startswith(("-", " ", "\t")):
                note.fail(i + 1, "front-matter line under `%s` is neither a key nor "
                                 "a list item, so it is silently ignored: %r"
                          % (cur, line[:50]))
        else:
            note.fail(i + 1, "front-matter line before any key: %r" % line)
    return keys, kv, end + 1


def _check_front_matter(note, keys, kv):
    seen = [k for k in keys]
    if len(set(seen)) != len(seen):
        dupes = sorted({k for k in seen if seen.count(k) > 1})
        note.fail(2, "duplicate front-matter key(s): %s" % ", ".join(dupes))
    unknown = [k for k in seen if k not in SCHEMA]
    if unknown:
        note.fail(2, "front-matter key(s) not in the CONVENTIONS.md 2b schema: %s"
                     % ", ".join(unknown))
    missing = [k for k in SCHEMA if k not in seen and k not in OPTIONAL_KEYS]
    if missing:
        note.fail(2, "front-matter key(s) missing: %s" % ", ".join(missing))
    known = [k for k in seen if k in SCHEMA]
    if known != [k for k in SCHEMA if k in known]:
        note.fail(2, "front-matter keys out of schema order; expected %s, got %s"
                     % (" ".join(k for k in SCHEMA if k in known), " ".join(known)))
    if known and known[-1] != "read" and "read" in known:
        note.fail(2, "`read` must be the last key in the schema")

    def scalar(key):
        return kv[key][0] if key in kv else None

    fmt = scalar("format")
    if fmt is not None and fmt not in FORMATS:
        note.fail(2, "`format: %s` is not one of %s -- Article/Post/Video is a "
                     "clipping's enum and is wrong on a summary note"
                     % (fmt, "/".join(FORMATS)))

    if "sources" in kv:
        if kv["sources"][0]:
            note.fail(2, "`sources` is a block-form list; found a scalar value")
        raw_items = [l.strip() for l in kv["sources"][1] if l.strip()]
        items = [i[1:].strip() if i.startswith("-") else i for i in raw_items]
        if not items:
            note.fail(2, "`sources` is empty -- item 1 is the PDF wikilink")
        for n, it in enumerate(items, 1):
            if not (len(it) >= 2 and it[0] == '"' and it[-1] == '"'):
                note.fail(2, "`sources` item %d must be double-quoted" % n)
        inner = [i.strip('"').strip() for i in items]
        if inner:
            first = inner[0]
            if not (first.startswith("[[") and first.endswith("]]")):
                note.fail(2, "`sources` item 1 must be the PDF wikilink, "
                             "e.g. \"[[Doe_X_2025.pdf]]\"")
            elif not first[2:-2].lower().endswith(".pdf"):
                note.fail(2, "`sources` item 1 must name a .pdf")
        for n, it in enumerate(inner[1:], 2):
            if it.startswith("[["):
                note.fail(2, "`sources` item %d is a wikilink; only item 1 "
                             "names the PDF -- later items are the document's "
                             "printed URL(s)" % n)
            elif not (it.startswith("https://") or it.startswith("http://")):
                note.fail(2, "`sources` item %d is neither the PDF wikilink "
                             "nor a URL" % n)
        if len(inner) > 2:
            note.fail(2, "`sources` holds %d items -- two is the maximum "
                         "(the PDF, then its printed URL)" % len(inner))
        if len(inner) > 1 and fmt == "Book":
            note.fail(2, "a `sources` URL item is never written on `format: Book`")

    for key in ("published", "created"):
        val = scalar(key)
        if val is None:
            continue
        if not _DATE.match(val):
            note.fail(2, "`%s: %s` must be a full YYYY-MM-DD date%s"
                         % (key, val, " (pad an unstated month or day with 01)"
                            if key == "published" else ""))
            continue
        try:
            datetime.date(*(int(p) for p in val.split("-")))
        except ValueError:
            note.fail(2, "`%s: %s` is not a real date" % (key, val))

    desc = scalar("description")
    if desc is not None:
        bare = desc[1:-1] if len(desc) >= 2 and desc[0] == desc[-1] == '"' else desc
        if not bare:
            note.fail(2, "`description` is empty")
        elif len(bare) > MAX_DESCRIPTION:
            note.fail(2, "`description` is %d characters, over the %d limit"
                         % (len(bare), MAX_DESCRIPTION))

    if "author" in kv:
        if kv["author"][0]:
            note.fail(2, "`author` must be a block-form list, not inline")
        items = [l.strip() for l in kv["author"][1] if l.strip()]
        if not items:
            note.fail(2, "`author` has no entries")
        for it in items:
            if not it.startswith("- "):
                note.fail(2, "`author` entry is not a block-list item: %r" % it)
            elif "[[" in it:
                note.fail(2, "`author` entries carry no [[...]] wrapper: %r" % it)

    if "tags" in kv:
        if kv["tags"][0]:
            note.fail(2, "`tags` must be a block-form list, not inline")
        items = [l.strip() for l in kv["tags"][1] if l.strip()]
        if not items:
            note.fail(2, "`tags` has no entries")
        for it in items:
            if not it.startswith("- "):
                note.fail(2, "`tags` entry is not a block-list item: %r" % it)
                continue
            val = it[2:].strip()
            if not (len(val) >= 2 and val[0] == '"' and val[-1] == '"'):
                note.fail(2, "tag %s must be double-quoted -- an unquoted # "
                             "starts a YAML comment and the tag vanishes" % val)
                continue
            inner = val[1:-1]
            if not inner.startswith("#"):
                note.fail(2, "tag %s must be #-prefixed" % val)
            elif inner[1:] not in TAG_ENUM:
                note.fail(2, "tag %s is not in the CONVENTIONS.md 3 enum" % val)

    read = scalar("read")
    if read is not None and read not in ("false", "true"):
        note.fail(2, "`read: %s` must be the bare boolean false (a quoted "
                     "\"false\" is a string and renders permanently ticked)" % read)


def _check_callout(note, body_start, fenced):
    lines = note.raw_lines
    for n, l in enumerate(lines):
        if n > body_start and n not in fenced and l.strip() == "> [!Summary]":
            note.fail(n + 1, "a second `> [!Summary]` callout; the note has one, "
                             "at the top")
    i = body_start
    if i >= len(lines):
        note.fail(0, "note has no body")
        return i
    if not lines[i].strip():
        note.fail(i + 1, "blank line between the closing `---` and the callout; "
                         "`> [!Summary]` opens on the very next line")
        while i < len(lines) and not lines[i].strip():
            i += 1
    if i >= len(lines) or lines[i].strip() != "> [!Summary]":
        note.fail(i + 1, "expected `> [!Summary]` here, found %r"
                         % (lines[i] if i < len(lines) else ""))
        if i >= len(lines) or not lines[i].startswith(">"):
            return i
        # It is a callout, just mis-spelled: keep going so the bullet count and
        # the `___` that follows are checked against the right lines.
    i += 1
    bullets = 0
    while i < len(lines) and lines[i].startswith(">"):
        stripped = lines[i]
        if stripped.startswith("> - "):
            bullets += 1
            if not stripped[4:].strip():
                note.fail(i + 1, "empty callout bullet")
        elif stripped.strip() == ">":
            note.fail(i + 1, "blank line inside the callout")
        else:
            note.fail(i + 1, "callout holds `> - ` bullets only, no continuation "
                             "or nested lines: %r" % stripped)
        i += 1
    if not MIN_BULLETS <= bullets <= MAX_BULLETS:
        note.fail(body_start + 1, "callout has %d bullets; the range is %d to %d"
                                  % (bullets, MIN_BULLETS, MAX_BULLETS))
    return i


def _check_rule(note, i):
    """One blank, `___`, one blank.  Returns the line after the second blank."""
    lines = note.raw_lines
    if i < len(lines) and not lines[i].strip():
        i += 1
    else:
        note.fail(i + 1, "expected a blank line between the callout and `___`")
    if i < len(lines) and lines[i].strip() == "___":
        i += 1
    else:
        note.fail(i + 1, "expected `___` alone on its line after the callout")
        return i
    if i < len(lines) and not lines[i].strip():
        i += 1
    else:
        note.fail(i + 1, "expected a blank line between `___` and the first heading")
    return i


def _check_structure(note, body_start, fenced):
    lines = note.raw_lines
    rules = [n for n, l in enumerate(lines[body_start:], body_start)
             if l.strip() == "___" and n not in fenced]
    if len(rules) != 1:
        note.fail(rules[1] + 1 if len(rules) > 1 else 0,
                  "the note carries exactly one `___` rule; found %d" % len(rules))
    for n, l in enumerate(lines[body_start:], body_start):
        s = l.strip()
        if n in fenced:
            continue
        if s and s != "___" and _OTHER_RULE.match(s):
            note.fail(n + 1, "horizontal rule %r below the front matter; the only "
                             "rule in the note is the single `___`" % s)

    heads = [(n, l[3:].strip()) for n, l in enumerate(lines[body_start:], body_start)
             if l.startswith("## ") and n not in fenced]
    if len(heads) != len(ROLES):
        note.fail(heads[0][0] + 1 if heads else 0,
                  "the note has %d `##` sections; it has exactly %d, in this order: "
                  "%s -- each headed by a short sentence about this paper, not by "
                  "the role name. (Every other section check is skipped until the "
                  "count is right: with the sections misaligned they would report "
                  "the wrong role for correct text.)"
                  % (len(heads), len(ROLES), ", ".join(ROLES)))
        return []
    # Each heading: a short sentence about this paper, not a label.  The role is
    # carried by position, so the text is free -- but it has a shape.
    for idx, (n, text) in enumerate(heads):
        role = ROLES[idx] if idx < len(ROLES) else "?"
        bare = text.strip().rstrip(":").strip()
        if bare.casefold() in GENERIC_HEADINGS:
            note.fail(n + 1, "heading %d (%s) is the label %r, not a sentence about "
                             "this paper -- say what this section actually found"
                      % (idx + 1, role, text))
            continue
        if len(bare) < MIN_HEADING:
            note.fail(n + 1, "heading %d (%s) is %d characters; a heading is a short "
                             "sentence about this paper, at least %d"
                      % (idx + 1, role, len(bare), MIN_HEADING))
        elif len(bare) > MAX_HEADING:
            note.fail(n + 1, "heading %d (%s) is %d characters; keep it under %d so "
                             "it scans in the outline pane"
                      % (idx + 1, role, len(bare), MAX_HEADING))
        if len(bare.split()) < MIN_HEADING_WORDS:
            note.fail(n + 1, "heading %d (%s) is %d word(s); a short sentence needs "
                             "at least %d" % (idx + 1, role, len(bare.split()),
                                              MIN_HEADING_WORDS))
        if bare.endswith("."):
            note.fail(n + 1, "heading %d (%s) ends in a full stop; a heading is a "
                             "sentence in shape, not in punctuation"
                      % (idx + 1, role))
        # Sentence case, with the scientific exceptions left alone: a first
        # word carrying an upper-case letter (`mRNA`) or a digit (`p53`) is a
        # name, not a lower-case sentence opening.
        first = bare.split()[0] if bare.split() else ""
        if "a" <= bare[:1] <= "z" and first.isalpha() and first.islower():
            note.fail(n + 1, "heading %d (%s) starts lower-case: %r"
                      % (idx + 1, role, text))
        if bare.isupper():
            note.fail(n + 1, "heading %d (%s) is in capitals; a heading is a "
                             "sentence, in sentence case" % (idx + 1, role))
    for n, l in enumerate(lines[body_start:], body_start):
        if n in fenced:
            continue
        if re.match(r"\A#(?!#)\s", l):
            note.fail(n + 1, "no `#` heading in the note: %r" % l)
        elif re.match(r"\A###+\s", l):
            note.fail(n + 1, "no `###` subheading in the note: %r" % l)

    # Section bodies: non-empty, and the right kind (bullets vs prose).
    bounds = []
    for idx, (n, text) in enumerate(heads):
        stop = heads[idx + 1][0] if idx + 1 < len(heads) else len(lines)
        bounds.append((ROLES[idx] if idx < len(ROLES) else "?", n, stop))
    for name, start, stop in bounds:
        block = [l for l in lines[start + 1:stop]]
        content = [l for l in block if l.strip()]
        if not content:
            note.fail(start + 1, "the %s section is empty" % name)
            continue
        if start + 1 < len(lines) and lines[start + 1].strip():
            note.fail(start + 2, "no blank line under the %s heading" % name)
        if start > 0 and lines[start - 1].strip():
            note.fail(start + 1, "no blank line above the %s heading" % name)
        if name in BULLET_ROLES:
            if not any(l.startswith("- ") for l in content):
                note.fail(start + 1, "the %s section is a `- ` bullet list" % name)
            if name == "Availability":
                bullets = [l for l in content if l.startswith("- ")]
                if not MIN_AVAILABILITY <= len(bullets) <= MAX_AVAILABILITY:
                    note.fail(start + 1, "Availability has %d bullets; it holds %d "
                                         "to %d -- data, code, and materials only, "
                                         "with no reference list after them"
                              % (len(bullets), MIN_AVAILABILITY, MAX_AVAILABILITY))
            if name == "Limitations":
                bullets = [l for l in content if l.startswith("- ")]
                if not MIN_LIMITATIONS <= len(bullets) <= MAX_LIMITATIONS:
                    note.fail(start + 1, "Limitations has %d bullets; it holds %d to "
                                         "%d -- only what would change how a reader "
                                         "acts on the finding (SKILL.md step 8)"
                              % (len(bullets), MIN_LIMITATIONS, MAX_LIMITATIONS))
                for b in bullets:
                    if len(b) > MAX_LIMITATION_CHARS:
                        note.fail(start + 1, "a Limitations bullet is %d characters, "
                                             "over %d -- state the caveat, or move "
                                             "the detail beside the number it "
                                             "qualifies in Results"
                                  % (len(b), MAX_LIMITATION_CHARS))
                        break
            # Every line, not just one: a trailing paragraph after the last
            # bullet is how a reference list gets back into a note that is
            # supposed to end at Availability (step 11, rule 11).
            for l in content:
                if not (l.startswith("- ") or l[:1] in (" ", "\t")):
                    note.fail(start + 1, "the %s section holds only `- ` bullets; "
                                         "found %r -- the note ends here, with no "
                                         "reference list or trailing block"
                              % (name, l[:50]))
                    break
        else:
            if content and all(l.startswith("- ") for l in content):
                note.fail(start + 1, "the %s section is prose, not a bullet list"
                                     % name)
    return bounds


_TRAILING_MARKUP = "*_\"'’”)]}"


def sentences(text):
    """Split prose into sentences, without breaking on decimals or `et al.`.

    A regex on `[.!?]\\s+` splits `r = 0.51.` correctly and `E. coli` wrongly,
    and a note about a bacterium is full of the second.  So the split is
    token-based and asks two questions at each candidate: is the token an
    abbreviation, and does the next one start the way a sentence starts.
    `0.51.` followed by `The` is a boundary; `E.` followed by `coli` is not,
    and neither is `et al.` followed by `2019`.

    Page citations are removed first.  They sit *after* the full stop with no
    space (`…220.<sup>[[…]]</sup> Next…`), so left in place they weld the
    citation onto the front of the following sentence and every word count
    downstream is wrong by four.
    """
    text = _CITATION.sub("", text)
    tokens = text.split()
    out, buf = [], []
    for i, tok in enumerate(tokens):
        buf.append(tok)
        bare = tok.rstrip(_TRAILING_MARKUP)
        if not bare or bare[-1] not in ".!?":
            continue
        if bare.casefold() in _ABBREVIATIONS:
            continue
        # A single-letter initial is not a sentence end: `B. F. Skinner` split
        # into three "sentences" because `F.` starts with a capital — phantom
        # sentences that pushed a conforming paragraph over the 6-sentence
        # cap.  wiki-builder's lint_entry guards this exact shape
        # (`_INITIAL_RE`, "the false positive that mattered"); the two
        # splitters must agree on it.
        if len(bare) == 2 and bare[0].isalpha() and bare[1] == ".":
            continue
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if nxt is not None:
            head = nxt.lstrip(_TRAILING_MARKUP + "-—([{")
            # A sentence starts with a capital, a digit or nothing at all.
            # Anything else -- `coli*`, a lower-case continuation -- means the
            # period belonged to the token, not to the sentence.
            if head and not (head[0].isupper() or head[0].isdigit()):
                continue
        out.append(" ".join(buf))
        buf = []
    if buf:
        out.append(" ".join(buf))
    return out


def _prose_lines(note, start, end, captions, fenced):
    """(line number, text) for the prose of a section: no exhibits, no headings.

    Embeds, caption lines, table rows and separators are all exhibit material.
    They are excluded from the length budget because an exhibit is how a result
    gets *shorter*; they are not excluded from the sentence check, which the
    caller applies to captions in their own right.
    """
    out = []
    for n in range(start, end):
        if n in fenced or n in captions:
            continue
        line = note.raw_lines[n]
        s = line.strip()
        if not s or s == "___" or s.startswith("## "):
            continue
        if _EMBED.match(s) or _TABLE_ROW.match(s) or _TABLE_SEP.match(s):
            continue
        # Citation markup is not prose: `<sup>[[Doe_X_2025.pdf#page=5|5]]</sup>`
        # is 39 characters the reader sees as a raised `5`, and counting it
        # would make the budget shrink every time a claim was properly cited.
        out.append((n, _CITATION.sub("", s)))
    return out


def _check_prose(note, bounds, captions, fenced, body_start):
    """The two readability rules that can be checked mechanically.

    Neither can tell whether the note is *clear* -- that is the writing, and no
    linter reaches it.  What they catch is the two shapes that make a note
    unreadable whatever the writing: the sentence that carries three claims,
    and the Results section that carries the whole paper.
    """
    for n in range(body_start, len(note.raw_lines)):
        if n in fenced:
            continue
        s = note.raw_lines[n].strip()
        if not s or s == "___" or s.startswith("## "):
            continue
        if _TABLE_ROW.match(s) or _TABLE_SEP.match(s) or _EMBED.match(s):
            continue
        # Callout bullets, list bullets and numbered steps are sentences in
        # their own right.  A step takes STE's tighter procedural limit.
        s = re.sub(r"\A>\s*-\s+", "", s)
        s = re.sub(r"\A-\s+", "", s)
        step = _STEP.match(s)
        if step:
            s = step.group(2)
        cap = MAX_STEP_WORDS if step else MAX_SENTENCE_WORDS
        counted = sentences(s)
        for sent in counted:
            words = len(sent.split())
            if words > cap:
                note.fail(n + 1, "a %s runs %d words, over %d -- one idea per "
                                 "sentence: a sentence is capped at %d words "
                                 "and a numbered step at %d (SKILL.md step 7a). "
                                 "Starts: %r"
                          % ("step" if step else "sentence", words, cap,
                             MAX_SENTENCE_WORDS, MAX_STEP_WORDS,
                             " ".join(sent.split()[:9]) + "…"))
                break
        if not step and len(counted) > MAX_PARAGRAPH_SENTENCES:
            note.fail(n + 1, "a paragraph holds %d sentences, over %d -- one "
                             "topic per paragraph, six sentences at most "
                             "(SKILL.md step 7a)"
                      % (len(counted), MAX_PARAGRAPH_SENTENCES))

    # Methods carries the experiment as numbered steps.  The list is not
    # required -- a theory paper has no procedure to walk through -- but a list
    # that is there has a shape, and a two-step or twelve-step one is either
    # not a procedure or the paper's methods section copied across.
    span = next(((s, e) for name, s, e in bounds if name == "Methods"), None)
    if span is not None:
        steps = [note.raw_lines[n].strip() for n in range(*span)
                 if n not in fenced and _STEP.match(note.raw_lines[n].strip())]
        if steps and not MIN_STEPS <= len(steps) <= MAX_STEPS:
            note.fail(span[0] + 1, "Methods lists %d numbered steps; a walked-"
                                   "through experiment has %d to %d (SKILL.md "
                                   "step 7)"
                      % (len(steps), MIN_STEPS, MAX_STEPS))
        numbers = [int(_STEP.match(s).group(1)) for s in steps]
        if numbers and numbers != list(range(1, len(numbers) + 1)):
            note.fail(span[0] + 1, "the Methods steps are numbered %s; they run "
                                   "1..%d in the order the researchers worked"
                      % (", ".join(str(x) for x in numbers), len(numbers)))

    span = next(((s, e) for name, s, e in bounds if name == "Results"), None)
    if span is None:
        return
    prose = _prose_lines(note, span[0], span[1], captions, fenced)
    chars = sum(len(t) for _n, t in prose)
    if chars > MAX_RESULTS_CHARS:
        note.fail(span[0] + 1, "Results holds %d characters of prose, over %d -- "
                               "it carries the paper's main result developed "
                               "properly, with any secondary finding at a "
                               "sentence each (SKILL.md step 7). Exhibits and "
                               "their captions are not counted."
                  % (chars, MAX_RESULTS_CHARS))


def _check_figures(note, bounds, images, fenced):
    """Returns the set of line numbers that are captions, for later checks.

    A caption is *the line under an embed*, and nothing else.  Sniffing for one
    by asterisks matches any paragraph that happens to end on an italicised
    term -- `... the organism was *Escherichia coli*` -- and every check keyed
    off that guess then fires on ordinary prose.
    """
    lines = note.raw_lines
    found_span = next(((s, e) for name, s, e in bounds
                       if name == "Results"), None)
    embeds, captions = 0, set()
    for n, l in enumerate(lines):
        if n in fenced:
            continue
        m = _EMBED.match(l.strip())
        if not m:
            continue
        embeds += 1
        name = m.group(1).split("|")[0].strip()
        if found_span and not (found_span[0] < n < found_span[1]):
            note.fail(n + 1, "figure embed outside the Results section: %s" % name)
        if n + 1 >= len(lines):
            note.fail(n + 1, "embed %s is the last line of the file; its caption "
                             "goes on the next line" % name)
            continue
        nxt = lines[n + 1]
        if not nxt.strip():
            note.fail(n + 2, "blank line between the embed %s and its caption; the "
                             "caption goes on the very next line" % name)
        elif not _is_caption(nxt):
            note.fail(n + 2, "embed %s has no italic caption on the next line "
                             "(single asterisks -- `**bold**` is not a caption)"
                             % name)
        else:
            captions.add(n + 1)
            if _CAP_NUM.match(nxt.strip()):
                note.fail(n + 2, "caption opens with an exhibit number, which this "
                                 "note never carries: %r" % nxt.strip()[:60])
        if images is not None and not os.path.isfile(os.path.join(images, name)):
            note.fail(n + 1, "embed names a file that is not in the image folder: "
                             "%s (Obsidian renders this as plain text, silently)"
                             % name)
    if embeds > MAX_FIGURES:
        note.fail(0, "%d figure embeds; the cap is %d" % (embeds, MAX_FIGURES))
    return captions


def _check_tables(note, bounds, fenced):
    """Rebuilt tables: in Results, captioned, capped.  Returns caption lines."""
    lines = note.raw_lines
    results = next(((s, e) for name, s, e in bounds if name == "Results"), None)
    blocks, cur = [], None
    for n, l in enumerate(lines):
        if n not in fenced and _TABLE_ROW.match(l):
            if cur is None:
                cur = [n, n]
            else:
                cur[1] = n
        elif cur is not None:
            blocks.append(tuple(cur))
            cur = None
    if cur is not None:
        blocks.append(tuple(cur))

    captions = set()
    for start, stop in blocks:
        if stop - start < 2:
            note.fail(start + 1, "a one- or two-line `|` block is not a table; "
                                 "two numbers belong in a sentence (step 4)")
        if not any(_TABLE_SEP.match(lines[i]) for i in range(start, stop + 1)):
            note.fail(start + 1, "table has no `|---|---|` separator row, so it "
                                 "renders as literal pipes")
        if results and not (results[0] < start and stop < results[1]):
            note.fail(start + 1, "rebuilt table outside the Results section")
        if stop + 1 >= len(lines):
            note.fail(stop + 1, "the table is the last block in the file; its "
                                "caption goes on the next line")
            continue
        nxt = lines[stop + 1]
        if not nxt.strip():
            note.fail(stop + 2, "blank line between the table and its caption; the "
                                "caption goes on the very next line")
        elif not _is_caption(nxt):
            note.fail(stop + 2, "rebuilt table has no italic caption on the next "
                                "line (single asterisks -- `**bold**` is not a "
                                "caption)")
        else:
            captions.add(stop + 1)
            if _CAP_NUM.match(nxt.strip()):
                note.fail(stop + 2, "caption opens with an exhibit number, which "
                                    "this note never carries: %r"
                          % nxt.strip()[:60])
    if len(blocks) > MAX_TABLES:
        note.fail(0, "%d rebuilt tables; the cap is %d" % (len(blocks), MAX_TABLES))
    return captions


def _check_exhibit_numbers(note, body_start, captions, fenced):
    """SKILL.md step 4: the note points at nothing the reader does not have.

    A figure or table number is a pointer out of the note, so it is banned in
    prose and in captions alike -- and a figure number is also a second name for
    a file, which is the drift `_CAP_NUM` was written for.
    """
    for n, l in enumerate(note.raw_lines):
        if (n < body_start or n in fenced or _EMBED.match(l.strip())
                or _TABLE_ROW.match(l)):
            continue
        l = _URLS.sub(" ", l)
        if n in captions and _CAP_NUM.match(l.strip()):
            continue                      # already reported, with a better message
        m = _EXHIBIT_NUM.search(l)
        if m:
            note.fail(n + 1, "%r points at something outside the note; if it "
                             "matters, embed the figure or rebuild the table, and "
                             "never carry the number (SKILL.md step 4)"
                             % m.group(0).strip())


def _check_citations(note, body_start, captions, fenced, source=None):
    """A citation is an inline wikilink whose display text is the page number.

    `[[Doe_X_2025.pdf#page=5|5]]` -- the reader sees `5`, the click opens page 5,
    and nothing has to be kept in sync with a list at the bottom of the file.
    """
    lines = note.raw_lines
    in_callout = set()
    n = body_start
    while n < len(lines) and (lines[n].startswith(">") or not lines[n].strip()):
        if lines[n].startswith(">"):
            in_callout.add(n)
        n += 1
        if n < len(lines) and lines[n].strip() == "___":
            break
    for n, l in enumerate(lines):
        if n in fenced:
            continue
        if _FOOTNOTE.search(l):
            note.fail(n + 1, "footnote syntax in the note; page references are "
                             "inline links now (SKILL.md step 9a)")
        wrapped = {c.start() for c in _CITATION.finditer(l)}
        for m in _PAGE_LINK.finditer(l):
            target, alias = m.group(1), m.group(2)
            open_at = m.start() - len("<sup>")
            if open_at not in wrapped:
                note.fail(n + 1, "page citation is not wrapped in `<sup>...</sup>`, "
                                 "so it renders full size: write "
                                 "`<sup>[[%s|%s]]</sup>`"
                          % (target, re.search(r"#page=(\d+)", target).group(1)))
            elif open_at > 0 and l[open_at - 1].isspace():
                note.fail(n + 1, "space before the citation; a superscript "
                                 "attaches to the character it follows, with no "
                                 "gap -- `…planned 220.<sup>…</sup>`")
            elif open_at == 0:
                note.fail(n + 1, "citation opens the line; it attaches to the end "
                                 "of the text it supports")
            page = re.search(r"#page=(\d+)", target).group(1)
            where = ("the front matter" if n < body_start else
                     "the callout" if n in in_callout else
                     "a caption" if n in captions else None)
            if where:
                note.fail(n + 1, "page citation in %s; citations are body-prose "
                                 "only" % where)
            if alias is None:
                note.fail(n + 1, "page citation shows its whole target; give it the "
                                 "page number as display text -- `[[%s|%s]]`"
                                 % (target, page))
            elif (not re.fullmatch(r"[0-9]+", alias.strip())
                  or int(alias) != int(page)):
                note.fail(n + 1, "page citation display text is %r but the link "
                                 "opens page %s; they must match" % (alias, page))
            # The citation must point at *this* note's PDF. A link left over
            # from the previous note of a batch resolves fine in Obsidian and
            # sends the reader into a different paper.
            base = target.split("#")[0].rstrip().split("/")[-1]
            if not base.lower().endswith(".pdf"):
                note.fail(n + 1, "page citation target %r does not name a .pdf"
                                 % base)
            elif source and base.casefold() != source.casefold():
                note.fail(n + 1, "page citation points at %r, but this note's "
                                 "`sources:` item 1 is %r" % (base, source))



def lint(text, path="<note>", images=None):
    """Return a sorted list of (line, message).  Empty means the note is clean."""
    note = Note(text, path)
    # CRLF first, and normalise before anything else looks at a line.  Left in
    # place it makes every `---` fence read as `---\r`, so the note reports as
    # having no front matter and seven other things that are all the same fault.
    if "\r\n" in text:
        note.fail(0, "file has CRLF line endings; write it with LF newlines "
                     "(every finding below was re-checked against the LF form)")
        text = text.replace("\r\n", "\n")
        note.text = text
    if not text.endswith("\n"):
        note.fail(0, "file must end with a single newline")
    elif text.endswith("\n\n"):
        note.fail(0, "file ends with more than one newline")
    note.raw_lines = text[:-1].split("\n") if text.endswith("\n") else text.split("\n")
    keys, kv, body_start = _split_front_matter(note)
    fenced = _fenced(note.raw_lines)
    _check_front_matter(note, keys, kv)
    after = _check_callout(note, body_start, fenced)
    _check_rule(note, after)
    bounds = _check_structure(note, body_start, fenced)
    captions = _check_figures(note, bounds, images, fenced)
    captions |= _check_tables(note, bounds, fenced)
    _check_exhibit_numbers(note, body_start, captions, fenced)
    _check_prose(note, bounds, captions, fenced, body_start)
    _sitems = [l.strip() for l in kv.get("sources", ["", []])[1] if l.strip()]
    src = (_sitems[0][1:].strip() if _sitems and _sitems[0].startswith("-")
           else (_sitems[0] if _sitems else "")).strip('"').strip()
    src = src[2:-2].split("/")[-1] if src.startswith("[[") and src.endswith("]]") else None
    _check_citations(note, body_start, captions, fenced, src)
    return sorted(note.findings)


# --- self-tests --------------------------------------------------------------

GOOD = """---
title: "A Title: With a Colon"
format: Paper
sources:
  - "[[Doe_X_2025.pdf]]"
  - "https://arxiv.org/abs/2501.02045"
author:
  - Priya N. Doe
published: 2025-01-03
created: 2026-08-10
description: Doe cut recurrence from 45% to 8% in a 219-patient trial.
tags:
  - "#medicine"
read: false
---
> [!Summary]
> - One.
> - Two.
> - Three.

___

## Recurrent C. difficile relapses again after vancomycin

Prose.

## A 219-patient double-blind trial of transplant capsules

Prose.

## Recurrence fell from 45% to 8% within eight weeks

A claim with a citation.<sup>[[Doe_X_2025.pdf#page=5|5]]</sup>

![[Doe_X_2025_fig_2.png]]
*The arms separated inside a fortnight. Kaplan-Meier curves for the two arms.*

| Arm | Recurrence |
|---|---|
| Transplant | 8.2% |
| Placebo | 45.0% |
*Recurrence was five times lower on transplant. The primary outcome only; the secondary outcomes are in the paper.*

More prose.<sup>[[Doe_X_2025.pdf#page=6|6]]</sup>

## Worth offering after a second recurrence in adults

Prose.

## Eight weeks of follow-up and one dominant donor

- **One.** Prose.
- **Two.** Prose.

## Participant data on request, no analysis code

- **Data.** Not stated.
- **Code.** github.example/x
"""


def _mutate(old, new):
    assert old in GOOD, "self-test fixture drift: %r" % old[:50]
    return GOOD.replace(old, new, 1)


def _cases():
    I_H = "## Worth offering after a second recurrence in adults"
    M_H = "## A 219-patient double-blind trial of transplant capsules"
    AV_H = "## Participant data on request, no analysis code"
    LIM_H = "## Eight weeks of follow-up and one dominant donor"
    return [
        ("clean", GOOD, CLEAN),
        # A single-letter initial is not a sentence boundary: "B. F. Skinner"
        # split into three "sentences", pushing a conforming 5-sentence
        # paragraph over the 6-sentence cap (lint_entry guards this shape;
        # the two splitters must agree).
        ("initials are not sentence ends",
         _mutate("## Worth offering after a second recurrence in adults\n\nProse.",
                 "## Worth offering after a second recurrence in adults\n\n"
                 "The design follows B. F. Skinner closely. One. Two. "
                 "Three. Four."),
         CLEAN),
        ("...and six real sentences still trip the cap",
         _mutate("## Worth offering after a second recurrence in adults\n\nProse.",
                 "## Worth offering after a second recurrence in adults\n\n"
                 "One is stated. Two follows. Three lands. Four holds. "
                 "Five stands. Six ends. Seven overflows."),
         "one topic per paragraph"),
        ("blank line above callout",
         _mutate("---\n> [!Summary]", "---\n\n> [!Summary]"), "blank line between"),
        ("quoted read", _mutate("read: false", 'read: "false"'), "bare boolean"),
        ("bare year", _mutate("published: 2025-01-03", "published: 2025"),
         "full YYYY-MM-DD"),
        ("unquoted tag", _mutate('  - "#medicine"', "  - #medicine"), "double-quoted"),
        ("tag off enum", _mutate('  - "#medicine"', '  - "#astrology"'), "enum"),
        ("keys reordered",
         _mutate('format: Paper\nsources:',
                 'sources:\n  - "PLACEHOLDER.pdf"\nformat: Paper'), "out of schema order"),
        ("missing key", _mutate("format: Paper\n", ""), "missing: format"),
        ("extra key", _mutate("read: false", "mood: bright\nread: false"),
         "not in the CONVENTIONS.md 2b schema"),
        ("read not last", _mutate("description: Doe", "read: false\ndescription: Doe")
         .replace("tags:\n  - \"#medicine\"\nread: false\n---", "tags:\n  - \"#medicine\"\n---"),
         "last key"),
        ("description too long",
         _mutate("description: Doe cut recurrence from 45% to 8% in a 219-patient trial.",
                 "description: " + "x" * 111), "over the 110 limit"),
        ("heading is a bare label",
         _mutate("## Participant data on request, no analysis code", "## Availability"), "not a sentence about"),
        ("heading is another bare label",
         _mutate("## Eight weeks of follow-up and one dominant donor", "## Limitations"), "not a sentence about"),
        ("heading too short", _mutate("## Participant data on request, no analysis code", "## Data notes"), "at least 20"),
        ("heading too long",
         _mutate("## Participant data on request, no analysis code", "## " + "Availability of the participant data and the "
                 "analysis code, and every condition attached to either of them"),
         "keep it under 90"),
        ("heading ends in a full stop",
         _mutate("## Participant data on request, no analysis code", "## Participant data on request, no analysis code."),
         "full stop"),
        ("heading starts lower-case",
         _mutate("## Participant data on request, no analysis code", "## participant data on request, no analysis code"),
         "lower-case"),
        ("heading dropped", _mutate(LIM_H + "\n\n- **One.** Prose.\n- **Two.** Prose.\n\n", ""),
         "the note has"),
        ("extra heading", _mutate(AV_H, "## An extra section nobody asked for\n\nProse.\n\n" + AV_H),
         "the note has"),
        ("subheading", _mutate(M_H + "\n\nProse.",
                               M_H + "\n\n### Sub\n\nProse."), "###"),
        ("two rules", _mutate("___\n\n## Recurrent",
                              "___\n\n___\n\n## Recurrent"), "exactly one `___`"),
        ("no blank above the rule", _mutate("> - Three.\n\n___", "> - Three.\n___"),
         "blank line between the callout and `___`"),
        ("no blank below the rule", _mutate("___\n\n## Recurrent", "___\n## Recurrent"),
         "blank line between `___` and the first heading"),
        ("rule is not `___`", _mutate("\n___\n", "\n***\n"),
         "expected `___` alone on its line"),
        ("stray hr", _mutate("## Worth offering after a second recurrence in adults\n\nProse.",
                             "## Interpretation\n\n***\n\nProse."), "horizontal rule"),
        ("empty section", _mutate("## Worth offering after a second recurrence in adults\n\nProse.\n",
                 "## Worth offering after a second recurrence in adults\n"),
         "is empty"),
        ("limitations as prose",
         _mutate("- **One.** Prose.\n- **Two.** Prose.", "Just prose."),
         "is a `- ` bullet list"),
        ("caption gap", _mutate("]]\n*The arms", "]]\n\n*The arms"), "blank line between"),
        ("caption numbered", _mutate("*The arms separated", "*Figure 2 - The arms separated"),
         "opens with an exhibit number"),
        ("caption numbered, dotted", _mutate("*The arms separated",
                                             "*Fig. 1.2: The arms separated"),
         "opens with an exhibit number"),
        ("caption numbered, supplementary",
         _mutate("*The arms separated", "*Supplementary Figure 1 - The arms separated"),
         "opens with an exhibit number"),
        ("no caption", _mutate("*The arms separated inside a fortnight. Kaplan-Meier "
                               "curves for the two arms.*", "Plain text."),
         "no italic caption"),
        ("embed outside results",
         _mutate("## Worth offering after a second recurrence in adults\n\nProse.",
                 "## Interpretation\n\n![[Doe_X_2025_fig_3.png]]\n*A caption here.*\n\nProse."),
         "outside the Results section"),
        ("five figures",
         _mutate("More prose.<sup>[[Doe_X_2025.pdf#page=6|6]]</sup>",
                 "\n".join("![[Doe_X_2025_fig_%d.png]]\n*Caption %d here.*\n" % (i, i)
                           for i in range(3, 7)) + "\nMore prose."), "the cap is 4"),
        ("unaliased page link",
         _mutate("<sup>[[Doe_X_2025.pdf#page=5|5]]</sup>",
                 "<sup>[[Doe_X_2025.pdf#page=5]]</sup>"),
         "shows its whole target"),
        ("alias does not match the page",
         _mutate("[[Doe_X_2025.pdf#page=5|5]]", "[[Doe_X_2025.pdf#page=5|7]]"),
         "they must match"),
        ("citation in the callout",
         _mutate("> - One.", "> - One.<sup>[[Doe_X_2025.pdf#page=5|5]]</sup>"),
         "citation in the callout"),
        ("citation in a caption",
         _mutate("curves for the two arms.*",
                 "curves.<sup>[[Doe_X_2025.pdf#page=5|5]]</sup>*"),
         "citation in a caption"),
        ("footnote syntax is gone",
         _mutate("More prose.<sup>[[Doe_X_2025.pdf#page=6|6]]</sup>", "More prose.[^1]"),
         "footnote syntax"),
        ("table outside Results",
         _mutate("## Worth offering after a second recurrence in adults\n\nProse.",
                 "## Worth offering after a second recurrence in adults\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n"
                 "*A caption for it.*\n\nProse."), "outside the Results section"),
        ("table with no caption",
         _mutate("*Recurrence was five times lower on transplant. The primary "
                 "outcome only; the secondary outcomes are in the paper.*",
                 "Plain text after the table."), "no italic caption"),
        ("table caption pushed a line down",
         _mutate("| Placebo | 45.0% |\n*Recurrence",
                 "| Placebo | 45.0% |\n\n*Recurrence"), "blank line between"),
        ("two-line pipe block is not a table",
         _mutate("| Arm | Recurrence |\n|---|---|\n| Transplant | 8.2% |\n"
                 "| Placebo | 45.0% |", "| Arm | Recurrence |\n|---|---|"),
         "not a table"),
        ("five tables",
         _mutate("More prose.<sup>[[Doe_X_2025.pdf#page=6|6]]</sup>",
                 "\n".join("| A%d | B |\n|---|---|\n| 1 | 2 |\n*Caption %d here.*\n"
                            % (i, i) for i in range(2, 6))
                 + "\nMore prose.<sup>[[Doe_X_2025.pdf#page=6|6]]</sup>"), "the cap is 4"),
        ("table number in prose",
         _mutate("More prose.<sup>[[Doe_X_2025.pdf#page=6|6]]</sup>",
                 "Table 5 reports the standard errors."), "points at something"),
        ("table number in a caption",
         _mutate("*Recurrence was five times lower", "*Table 2 - recurrence was "
                 "five times lower"), "opens with an exhibit number"),
        ("figure number in a table caption",
         _mutate("*Recurrence was five times lower", "*Figure 2 - recurrence was "
                 "five times lower"), "opens with an exhibit number"),
        ("bold line is not a caption",
         _mutate("*The arms separated inside a fortnight. Kaplan-Meier curves "
                 "for the two arms.*",
                 "**The arms separated inside a fortnight.**"), "no italic caption"),
        ("trailing reference list",
         _mutate("- **Code.** github.example/x",
                 "- **Code.** github.example/x\n\nReferences: Doe et al., 2025."),
         "no reference list"),
        ("citation into another paper",
         _mutate("[[Doe_X_2025.pdf#page=5|5]]", "[[Other_Paper_2019.pdf#page=5|5]]"),
         "`sources:` item 1"),
        ("citation target is not a pdf",
         _mutate("[[Doe_X_2025.pdf#page=5|5]]", "[[Doe_X_2025#page=5|5]]"),
         "does not name a .pdf"),
        ("citation not wrapped in sup",
         _mutate("More prose.<sup>[[Doe_X_2025.pdf#page=6|6]]</sup>",
                 "More prose [[Doe_X_2025.pdf#page=6|6]]."), "not wrapped in `<sup>"),
        ("space before the superscript",
         _mutate("More prose.<sup>[[Doe_X_2025.pdf#page=6|6]]</sup>",
                 "More prose. <sup>[[Doe_X_2025.pdf#page=6|6]]</sup>"),
         "space before the citation"),
        ("citation opens a line",
         _mutate("More prose.<sup>[[Doe_X_2025.pdf#page=6|6]]</sup>",
                 "More prose.\n\n<sup>[[Doe_X_2025.pdf#page=6|6]]</sup> Next."),
         "opens the line"),
        ("sup with a gap inside the tag",
         _mutate("<sup>[[Doe_X_2025.pdf#page=6|6]]</sup>",
                 "<sup> [[Doe_X_2025.pdf#page=6|6]] </sup>"), "not wrapped in `<sup>"),
        ("one limitation is too few",
         _mutate("- **One.** Prose.\n- **Two.** Prose.", "- **One.** Prose."),
         "it holds 2 to 4"),
        ("five limitations",
         _mutate("- **One.** Prose.\n- **Two.** Prose.",
                 "\n".join("- **Item %d.** Prose here." % i for i in range(1, 6))),
         "it holds 2 to 4"),
        ("four limitations is fine",
         _mutate("- **One.** Prose.\n- **Two.** Prose.",
                 "\n".join("- **Item %d.** Prose here." % i for i in range(1, 5))),
         CLEAN),
        ("one enormous limitation bullet",
         _mutate("- **One.** Prose.\n- **Two.** Prose.",
                 "- **One.** " + "Prose that keeps going. " * 20
                 + "\n- **Two.** Prose."), "over 420"),
        # --- the review pass of 2026-08-10, round two. Each of these was a
        # --- reproduced defect: a crash, a false positive on a correct note,
        # --- or a malformed note the linter accepted.
        ("superscript digit alias does not crash",
         _mutate("|6]]", "|\u2076]]"), "display text"),
        ("arabic-indic digit alias is not a page number",
         _mutate("|6]]", "|\u0666]]"), "display text"),
        ("a fenced block is not note structure",
         _mutate(M_H + "\n\nProse.",
                 M_H + "\n\nProse.\n\n```bash\n## build the cohort\n"
                 "cat a | awk '{print $1}'\n___\n| not | a table |\n```"), CLEAN),
        ("'figures' meaning numbers is prose",
         _mutate("More prose.<sup>", "The headline figures 45% and 8% both hold."
                 "<sup>"), CLEAN),
        ("a url containing /figures/ is not a pointer",
         _mutate("- **Code.** github.example/x",
                 "- **Code.** https://github.example/x/tree/main/figures/fig2"), CLEAN),
        ("a real figure range is still a pointer",
         _mutate("More prose.<sup>", "See Figures 2 and 3.<sup>"),
         "points at something"),
        ("pipe-led prose is not a table",
         _mutate("More prose.<sup>", "|d| > 0.8 marked a large effect.<sup>"), CLEAN),
        ("table with no separator row",
         _mutate("| Arm | Recurrence |\n|---|---|\n", "| Arm | Recurrence |\n"),
         "separator row"),
        ("a second callout",
         _mutate(I_H + "\n\nProse.",
                 I_H + "\n\n> [!Summary]\n> - Again.\n\nProse."),
         "a second `> [!Summary]`"),
        ("reference list in Availability",
         _mutate("- **Code.** github.example/x",
                 "- **Code.** github.example/x\n- Doe, P. (2025). Nature 600, 1-9."
                 "\n- Smith, J. (2024). NEJM 390, 22-30."),
         "Availability has 4 bullets"),
        ("front-matter continuation is not silently swallowed",
         _mutate("description: Doe cut recurrence from 45% to 8% in a 219-patient "
                 "trial.",
                 "description: Doe cut recurrence.\nand this line is ignored"),
         "silently ignored"),
        ("heading may open with a lower-case gene name",
         _mutate("## Recurrence fell from 45% to 8% within eight weeks",
                 "## p53 loss drove resistance in the treated arm"), CLEAN),
        ("heading may open with mRNA",
         _mutate("## Recurrence fell from 45% to 8% within eight weeks",
                 "## mRNA vaccination cut hospitalisation in over-65s"), CLEAN),
        ("heading in capitals",
         _mutate("## Recurrence fell from 45% to 8% within eight weeks",
                 "## RECURRENCE FELL FROM 45 TO 8 PERCENT IN EIGHT"), "in capitals"),
        ("caption may end on an emphasised term",
         _mutate("curves for the two arms.*", "curves for the two **arms**.*"),
         CLEAN),
        ("embed as the last line of the file",
         _mutate("- **Code.** github.example/x",
                 "- **Code.** github.example/x\n\n![[Doe_X_2025_fig_3.png]]"),
         "last line of the file"),
        ("missing read is reported once",
         _mutate("read: false\n---", "---"), "missing: read"),
        ("wrong section count stops the role-keyed checks",
         _mutate(I_H, "## An extra framing section slipped in here\n\nProse.\n\n"
                 + I_H), "__ONLY__the note has 7"),
        ("zero-padded page is fine",
         _mutate("[[Doe_X_2025.pdf#page=5|5]]", "[[Doe_X_2025.pdf#page=05|5]]"), CLEAN),
        ("a regex in a code span is not a footnote",
         _mutate("More prose.<sup>[[Doe_X_2025.pdf#page=6|6]]</sup>",
                 "The class `[^a-z]` excludes letters.<sup>[[Doe_X_2025.pdf#page=6|6]]</sup>"),
         CLEAN),
        ("supplementary table number",
         _mutate("More prose.<sup>[[Doe_X_2025.pdf#page=6|6]]</sup>",
                 "Supplementary Table 1 has the rest."), "points at something"),
        ("a table cell may hold a bare number",
         _mutate("| Transplant | 8.2% |", "| Transplant 2 | 8.2% |"), CLEAN),
        ("no trailing newline", GOOD.rstrip("\n"), "single newline"),
        ("two trailing newlines", GOOD + "\n", "more than one newline"),
        ("no front matter", GOOD[4:], "must open with `---`"),
        ("unclosed front matter", GOOD.replace("read: false\n---\n", "read: false\n"),
         "never closed"),
        ("bad format enum", _mutate("format: Paper", "format: Article"), "not one of"),
        ("unquoted sources item", _mutate('  - "[[Doe_X_2025.pdf]]"',
                                    "  - [[Doe_X_2025.pdf]]"), "double-quoted"),
        ("sources item 1 not a pdf", _mutate('"[[Doe_X_2025.pdf]]"', '"[[Doe_X_2025.md]]"'),
         "must name a .pdf"),
        ("empty sources list",
         _mutate('sources:\n  - "[[Doe_X_2025.pdf]]"\n  - "https://arxiv.org/abs/2501.02045"',
                 "sources:"), "is empty"),
        ("sources item 2 a wikilink",
         _mutate('  - "https://arxiv.org/abs/2501.02045"', '  - "[[Other_Y_2020.pdf]]"'),
         "only item 1 names the PDF"),
        ("url item on a Book", _mutate("format: Paper", "format: Book"),
         "never written on `format: Book`"),
        ("a retired url: key", _mutate('  - "https://arxiv.org/abs/2501.02045"\nauthor:',
                                       '  - "https://arxiv.org/abs/2501.02045"\nurl: https://x.example\nauthor:'),
         "not in the CONVENTIONS.md 2b schema"),
        ("two callout bullets", _mutate("> - Three.\n", ""), "the range is 3 to 7"),
        ("callout continuation", _mutate("> - Three.", "> - Three.\n>   more"),
         "bullets only"),
        ("inline author", _mutate("author:\n  - Priya N. Doe", "author: Priya N. Doe"),
         "block-form list"),
        ("wikilinked author", _mutate("  - Priya N. Doe", "  - [[Priya N. Doe]]"),
         "no [[...]] wrapper"),
        ("impossible date", _mutate("created: 2026-08-10", "created: 2026-13-10"),
         "not a real date"),
        # --- the review pass of 2026-08-10.  Each of these lint clean before the
        # fix that follows it, which is the only evidence the check does anything.
        ("italic term in prose is not a caption",              # was a false positive
         _mutate("More prose.<sup>[[Doe_X_2025.pdf#page=6|6]]</sup>",
                 "**Harms.** One patient had bacteraemia.<sup>"
                 "[[Doe_X_2025.pdf#page=6|6]]</sup> It was *Escherichia coli*"),
         CLEAN),
        ("italic-ended prose is not a caption, either",
         _mutate(I_H + "\n\nProse.", I_H + "\n\nA line ending in *emphasis*"),
         CLEAN),
        ("day impossible for the month",
         _mutate("published: 2025-01-03", "published: 2025-02-31"),
         "not a real date"),
        ("CRLF", GOOD.replace("\n", "\r\n"), "CRLF line endings"),
        ("CRLF reports only that",
         GOOD.replace("\n", "\r\n"), "__ONLY__CRLF line endings"),
        ("no blank line above a heading",
         _mutate("Prose.\n\n## A 219-patient double-blind trial of transplant capsules",
                 "Prose.\n## A 219-patient double-blind trial of transplant capsules"),
         "no blank line above the"),
        ("citation in the front matter",
         _mutate("description: Doe", "description: Doe.<sup>[[Doe_X_2025.pdf#page=5|5]]</sup>"),
         "citation in the front matter"),
        ("caption number, comma delimiter",
         _mutate("*The arms separated", "*Figure 2, left: the arms separated"),
         "opens with an exhibit number"),
        ("caption number, no delimiter",
         _mutate("*The arms separated", "*Figure 2 The arms separated"),
         "opens with an exhibit number"),
        ("caption number, parenthesised",
         _mutate("*The arms separated", "*(Figure 2) The arms separated"),
         "opens with an exhibit number"),
        ("caption number, plural",
         _mutate("*The arms separated", "*Figures 2 and 3 show the arms separated"),
         "opens with an exhibit number"),
        ("figure number later in a caption",
         _mutate("curves for the two arms.*", "curves, redrawn from Figure 2.*"),
         "points at something"),
        ("figure number in prose",
         _mutate("More prose.<sup>[[Doe_X_2025.pdf#page=6|6]]</sup>", "As Figure 2 shows, more prose."),
         "points at something"),
        ("`Figure` with no number is fine",
         _mutate("More prose.<sup>[[Doe_X_2025.pdf#page=6|6]]</sup>", "Figure-ground separation held."), CLEAN),
        # The plural rule this pattern's own comment states, which was dead
        # code: the singular alternative carried `s?`, so it matched every
        # plural first and the range-required branch never ran.
        ("a plural with a bare number is prose, not a pointer",
         _mutate("More prose.<sup>[[Doe_X_2025.pdf#page=6|6]]</sup>",
                 "The revenue figures 2024 held up."), CLEAN),
        ("...and the same for tables",
         _mutate("More prose.<sup>[[Doe_X_2025.pdf#page=6|6]]</sup>",
                 "Two tables 3 rows deep were merged."), CLEAN),
        ("NEAR MISS: an `and` range is still a pointer, and the finding now "
         "quotes the whole range rather than its first half",
         _mutate("More prose.<sup>", "See Figures 2 and 3.<sup>"),
         "'Figures 2 and 3' points at something"),
        ("NEAR MISS: a hyphen range is still a pointer",
         _mutate("More prose.<sup>", "See Figures 2-4.<sup>"),
         "'Figures 2-4' points at something"),
        ("NEAR MISS: a comma range of tables is still a pointer",
         _mutate("More prose.<sup>", "See Tables 1, 2.<sup>"),
         "'Tables 1, 2' points at something"),
        ("NEAR MISS: the singular is still a pointer",
         _mutate("More prose.<sup>", "See Figure 2.<sup>"),
         "'Figure 2' points at something"),
        ("NEAR MISS: a caption opening on a PLURAL exhibit label is still "
         "caught -- _CAP_NUM keeps the `s?` this pattern dropped",
         _mutate("*The arms separated", "*Figures 2 and 3 - the arms separated"),
         "opens with an exhibit number"),

        # --- sentence and paragraph limits (step 7a) -------------------------
        ("a sentence over the STE limit",
         _mutate("More prose.",
                 " ".join(["Recurrence"] * (MAX_SENTENCE_WORDS + 1)) + "."),
         "over %d" % MAX_SENTENCE_WORDS),
        ("NEAR MISS: a sentence exactly at the cap is clean",
         _mutate("More prose.",
                 " ".join(["Recurrence"] * MAX_SENTENCE_WORDS) + "."),
         CLEAN),
        ("a long sentence in a caption is caught too",
         _mutate("*The arms separated",
                 "*" + " ".join(["Separation"] * (MAX_SENTENCE_WORDS + 1))
                 + ". The arms separated"),
         "one idea per sentence"),
        ("a long sentence in the callout is caught too",
         _mutate("> - Two.",
                 "> - " + " ".join(["Message"] * (MAX_SENTENCE_WORDS + 1)) + "."),
         "one idea per sentence"),
        ("NEAR MISS: a decimal does not end a sentence, so the clauses either "
         "side of one are counted together",
         _mutate("More prose.",
                 " ".join(["Recurrence"] * 14) + " r = 0.51 "
                 + " ".join(["and"] * 14) + " end."),
         "one idea per sentence"),
        ("NEAR MISS: `et al.` does not end a sentence either",
         _mutate("More prose.",
                 " ".join(["Recurrence"] * 12) + " per Smith et al. 2019 "
                 + " ".join(["again"] * 12) + "."),
         "one idea per sentence"),
        ("a paragraph over six sentences",
         _mutate("More prose.", "Prose. " * (MAX_PARAGRAPH_SENTENCES + 1)),
         "one topic per paragraph"),
        ("NEAR MISS: exactly six sentences is clean",
         _mutate("More prose.", ("Prose. " * MAX_PARAGRAPH_SENTENCES).strip()),
         CLEAN),
        ("Results carrying the whole paper",
         _mutate("More prose.", ("Prose. " * 500).strip()),
         "Results holds"),
        ("NEAR MISS: the same bulk in Methods is not a Results violation",
         _mutate("## A 219-patient double-blind trial of transplant capsules\n\nProse.",
                 "## A 219-patient double-blind trial of transplant capsules\n\n"
                 + "\n\n".join(["Prose."] * 500)),
         CLEAN),
        ("NEAR MISS: prose exactly at the Results cap is clean, and the "
         "exhibits and captions beside it are not counted",
         _mutate("More prose.",
                 "\n\n".join(["P" * 200] * (MAX_RESULTS_CHARS // 202))),
         CLEAN),

        # --- numbered steps in Methods --------------------------------------
        ("Methods steps run past the cap",
         _mutate("## A 219-patient double-blind trial of transplant capsules\n\nProse.",
                 "## A 219-patient double-blind trial of transplant capsules\n\nProse.\n\n"
                 + "\n".join("%d. The team did a thing." % i
                              for i in range(1, MAX_STEPS + 2))),
         "numbered steps; a walked-"),
        ("NEAR MISS: a list at the cap is clean",
         _mutate("## A 219-patient double-blind trial of transplant capsules\n\nProse.",
                 "## A 219-patient double-blind trial of transplant capsules\n\nProse.\n\n"
                 + "\n".join("%d. The team did a thing." % i
                              for i in range(1, MAX_STEPS + 1))),
         CLEAN),
        ("too few steps to be a procedure",
         _mutate("## A 219-patient double-blind trial of transplant capsules\n\nProse.",
                 "## A 219-patient double-blind trial of transplant capsules\n\nProse.\n\n"
                 "1. The team did a thing.\n2. The team did another thing."),
         "numbered steps; a walked-"),
        ("steps out of order",
         _mutate("## A 219-patient double-blind trial of transplant capsules\n\nProse.",
                 "## A 219-patient double-blind trial of transplant capsules\n\nProse.\n\n"
                 "1. The team did a thing.\n3. The team did another.\n"
                 "4. The team did a third."),
         "they run 1.."),
        ("a step over the 20-word procedural limit",
         _mutate("## A 219-patient double-blind trial of transplant capsules\n\nProse.",
                 "## A 219-patient double-blind trial of transplant capsules\n\nProse.\n\n"
                 "1. " + " ".join(["The"] * (MAX_STEP_WORDS + 1)) + ".\n"
                 "2. The team did another.\n3. The team did a third."),
         "a step runs %d words" % (MAX_STEP_WORDS + 1)),
        ("NEAR MISS: a step exactly at 20 words is clean, though the same "
         "words as prose would still be under the 25-word cap",
         _mutate("## A 219-patient double-blind trial of transplant capsules\n\nProse.",
                 "## A 219-patient double-blind trial of transplant capsules\n\nProse.\n\n"
                 "1. " + " ".join(["The"] * MAX_STEP_WORDS) + ".\n"
                 "2. The team did another.\n3. The team did a third."),
         CLEAN),
    ]


def _selftest():
    """Three kinds of case: CLEAN (must produce nothing), a needle (must produce
    a finding containing it), and `__ONLY__x` (must produce x and nothing else --
    which is how a check that reports one fault as seven gets caught)."""
    ok = fail = 0
    for name, text, needle in _cases():
        got = lint(text)
        if needle is CLEAN:
            good = not got
        elif needle is None:
            good = bool(got)
        elif needle.startswith("__ONLY__"):
            want = needle[len("__ONLY__"):]
            good = len(got) == 1 and want in got[0][1]
        else:
            good = any(needle in m for _, m in got)
        if good:
            ok += 1
        else:
            fail += 1
            print("FAIL  %-30s expected %r, got: %s"
                  % (name, needle, "; ".join(m for _, m in got) or "(clean)"))
    # The clean fixture must also survive an --images check against real files.
    # Same trailer as every other script in the plugin ("N/M self-test cases
    # pass"), which README.md documents as uniform and this one alone did not
    # emit -- so a caller grepping for it read a passing run as a missing suite.
    print("%d/%d self-test cases pass" % (ok, ok + fail))
    return 0 if not fail else 1


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Check a summary note against paper-summarizer's format.")
    p.add_argument("note", nargs="?", help="the .md note to check")
    p.add_argument("--images", help="image folder; also verify every embed resolves")
    p.add_argument("--test", action="store_true", help="run the self-tests")
    a = p.parse_args(argv)
    if a.test:
        return _selftest()
    if not a.note:
        p.error("give a note path, or --test")
    if not os.path.isfile(a.note):
        sys.stderr.write("not a file: %s\n" % a.note)
        return 2
    if a.images is not None and not os.path.isdir(a.images):
        sys.stderr.write("--images is not a directory: %s\n" % a.images)
        return 2
    with open(a.note, encoding="utf-8") as fh:
        text = fh.read()
    findings = lint(text, a.note, a.images)
    for line, msg in findings:
        print("%s:%s: %s" % (a.note, line if line else "-", msg))
    if not findings:
        print("%s: clean" % a.note)
        return 0
    print("%d violation(s)" % len(findings))
    return 1


if __name__ == "__main__":
    sys.exit(main())
