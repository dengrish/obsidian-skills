#!/usr/bin/env python3
"""Check a paper-summarizer note against the fixed format in references/note-format.md.

Prose cannot hold a format steady across notes written weeks apart.  Every rule
below is one the shape has already drifted on -- an extra heading, a blank line
above the callout, a quoted `read`, a caption pushed one line down -- and each
drift is invisible from inside the note that has it.

    python3 note_lint.py '<note.md>' --mode empirical [--allow-unorganized]
    python3 note_lint.py '<note.md>' --mode argument --images '<vault>/Sources/Images'
    python3 note_lint.py --test

Exit 0 with no violations, 1 with one line per violation, 2 for a bad invocation.
Advisories are reported separately and do not affect the exit code. Review
them before publication; they cover judgment calls that a mechanical check
must not turn into hard failures.

Stdlib only. The nine-key schema and list shapes are checked here; scalar
decoding is shared with the source-ownership readers so valid YAML escapes do
not make citations point at a different document.
"""

import argparse
import datetime
import os
import re
import stat
import sys
import unicodedata

_OBSIDIAN_SHARED_MODULES = ('naming', 'vault_artifacts', 'yaml_scalars')

# --- obsidian shared-layer bootstrap (canonical; see shared/CONVENTIONS.md) ---
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

from naming import core_stem, looks_canonical
from vault_artifacts import inventory_source_figures
from yaml_scalars import parse_scalar, strip_comment

# --- the format, as data -----------------------------------------------------

# CONVENTIONS.md 2b, in order.  No key is optional; the `sources` list holds
# the PDF wikilink first, then any printed DOI/arXiv URL as item 2.
SCHEMA = ("title", "format", "sources", "author", "published",
          "created", "description", "tags", "read")
OPTIONAL_KEYS = frozenset()

# references/note-format.md.  Six sections, always these roles, always this order -- but
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
    # The body-mode table describes section roles. Copying one of its cells is
    # still a generic label, even when it happens to meet the length checks.
    "research question and why it remained open",
    "design, population/system and procedure",
    "main findings, including harms and nulls",
    "implications licensed by the design",
    "design and reporting constraints",
    "data, code and relevant materials",
    "problem, thesis or organizing question",
    "stated scope, evidence base, premises and reasoning or selection approach",
    "main argument, framework, conclusions, requirements or recommendations",
    "what follows from the argument and how its contribution can be used",
    "evidence gaps, assumptions, counterarguments and applicability bounds",
    "supplied sources, code or supporting materials that matter to the argument",
    "affected work and the issue that prompted the notice",
    "issuer, stated grounds, evidence and process behind the action",
    "exact correction, withdrawal, warning or other change to the record",
    "consequences for the affected claims, versions or uses",
    "what the notice does not decide, change or supply evidence about",
    "affected record, supporting evidence or accompanying material named by the notice",
})

# references/note-format.md: this note's enum, not a clipping's Article/Post/Video.
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

# references/note-format.md: Limitations is the one section with a cap, because a list
# nobody reads to the end of buries the item that mattered.
MIN_LIMITATIONS, MAX_LIMITATIONS = 1, 4
PREFERRED_MIN_EMPIRICAL_LIMITATIONS = 2
# The sixth section uses document-mode-specific availability/record labels.
MIN_AVAILABILITY, MAX_AVAILABILITY = 1, 3
MAX_LIMITATION_CHARS = 420

MODES = ("empirical", "argument", "notice")
AVAILABILITY_LABELS_BY_MODE = {
    "empirical": frozenset({"data", "code", "materials"}),
    "argument": frozenset({"sources", "materials", "data", "code"}),
    "notice": frozenset({"record", "evidence", "materials"}),
}
REQUIRED_AVAILABILITY_LABELS_BY_MODE = {
    "empirical": frozenset({"data"}),
    "argument": frozenset(),
    "notice": frozenset(),
}

#: Strong brevity targets, reviewed for justified clarity exceptions under
#: references/note-format.md. Keep the existing constant names for callers;
#: exceeding either target is an advisory, not a format violation.
MAX_SENTENCE_WORDS = 25
MAX_STEP_WORDS = 20

#: One topic per paragraph, six sentences at most. Soft line breaks do not
#: start a new Markdown paragraph.
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
#: secondary ones at a sentence each (references/note-format.md), and this is what makes
#: that a fact rather than an intention.  Exhibits are excluded because a
#: figure and its caption are how a result gets shorter, not longer.
MAX_RESULTS_CHARS = 2400

#: Tokens that end in a period without ending a sentence.  Compared
#: case-folded, after trailing markup is stripped.
_ABBREVIATIONS = frozenset({
    "e.g.", "i.e.", "cf.", "vs.", "al.", "approx.", "ca.", "no.", "eq.",
    "ref.", "refs.", "vol.", "pp.", "st.", "dr.", "prof.", "sp.", "spp.",
    "min.", "max.", "ml.", "mg.", "fig.", "figs.", "tab.", "sect.", "ver.",
    "u.s.",
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
_NUMBER = re.compile(r"[-+]?(?:[0-9][0-9_]*(?:\.[0-9_]*)?"
                     r"(?:[eE][-+]?[0-9]+)?|\.[0-9]+(?:[eE][-+]?[0-9]+)?"
                     r"|0[xob][0-9a-fA-F_]+|\.(?:inf|nan))", re.I)
_EMBED = re.compile(r"\A!\[\[([^\]]+)\]\]\Z")
_ANY_EMBED = re.compile(r"!\[\[[^\]\n]+\]\]")
_AVAILABILITY_BULLET = re.compile(
    r"\A-\s+\*\*(Data|Code|Materials|Sources|Record|Evidence)\.\*\*\s+",
    re.I)
# `[[Stem.pdf#page=5|5]]` -- group 1 the target, group 2 the display text if any.
_PAGE_LINK = re.compile(r"\[\[([^\]|]*#page=[^\]|]*)(?:\|([^\]]*))?\]\]")
# The whole citation: the link wrapped in <sup>, which is how Obsidian renders a
# superscript.  Nothing between the tags and the brackets.
_CITATION = re.compile(r"<sup>\[\[[^\]|]*#page=[^\]|]*(?:\|[^\]]*)?\]\]</sup>")
# An exhibit number in any spelling: "Figure 2", "Fig. 1.2", "FIGURE S1",
# "Figures 2 and 3", "Supplementary Figure 1", "Extended Data Figure 1", and the
# same for tables.  No trailing delimiter is required: "Figure 2 The arms
# separated" is still a numbered caption.
_MARK = r"(?:supplementary\s+|suppl\.?\s*|supp\.?\s*|extended\s+data\s+)?"
_NUM = r"\s*[A-Za-z]?[0-9]+(?:[.\-][0-9A-Za-z]+)*"
# Abbreviations need a separator: TAB1 and FIG4 are also scientific identifiers,
# so a compact identifier alone is not evidence of an external exhibit pointer.
_FIG_NUM_BODY = _MARK + r"(?:figures?|figs?(?:\.|\s))" + _NUM
_TAB_NUM_BODY = _MARK + r"(?:tables?|tabs?(?:\.|\s))" + _NUM
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
_FIG_NUM_ONE = _MARK + r"(?:figure|fig(?:\.|\s))" + _NUM
_TAB_NUM_ONE = _MARK + r"(?:table|tab(?:\.|\s))" + _NUM
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
    r"|\b(?:figures|tables|figs(?:\.|\s)|tabs(?:\.|\s))\s*[A-Za-z]?[0-9]+"
    r"(?:\s*(?:-|–|to|and|,)\s*[A-Za-z]?[0-9]+)+)", re.I)
# A bare URL, stripped before the exhibit sweep: `.../figures/fig2` is a path
# segment, not a pointer out of the note.
_URLS = re.compile(r"(?:https?://|www\.)\S+|\b[\w.-]+\.(?:com|org|net|io|ai)/\S*")
# The only second source item a local-document note may carry. Provenance
# (whether the identifier is actually printed in the PDF) remains a source
# review; this enforces the normalized shapes the schema can check.
_PRINTED_ORIGIN_URL = re.compile(
    r"\Ahttps://(?:doi\.org/\S+|arxiv\.org/abs/\S+)\Z")
# A markdown table row: a leading pipe and at least two cells.  Prose that
# happens to open with a pipe -- `|d| > 0.8 marked a large effect` -- is not a
# table, and treating it as one produced two findings on a correct sentence.
_TABLE_ROW = re.compile(r"\A\s*\|.*\|\s*\Z")
# The `|---|---|` row.  A pipe block without one renders as literal pipes.
_TABLE_SEP = re.compile(r"\A\s*\|(?:\s*:?-{2,}:?\s*\|)+\s*\Z")
# A footnote marker or definition.  Matched, not substring-searched: `[^a-z]` in
# an inline code span is a character class, not a footnote.
_FOOTNOTE = re.compile(r"\[\^[^\]\s]+\]|\A\[\^[^\]]+\]:")


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
        self.advisories = []
        self.source = None

    def fail(self, line, msg):
        """`line` is 1-indexed, or 0 when the finding is about the whole file."""
        self.findings.append((line, msg))

    def advise(self, line, msg):
        """Record a non-blocking writing judgment at a 1-indexed line."""
        self.advisories.append((line, msg))


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
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"\A([A-Za-z_][A-Za-z0-9_-]*):(.*)\Z", line)
        if m and not line.startswith((" ", "\t", "-")):
            cur = m.group(1)
            keys.append(cur)
            kv[cur] = [strip_comment(m.group(2)).strip(), []]
        elif cur is not None:
            kv[cur][1].append(line)
            if cur not in ("author", "tags", "sources") and not line.startswith(("-", " ", "\t")):
                note.fail(i + 1, "front-matter line under `%s` is neither a key nor "
                                 "a list item, so it is silently ignored: %r"
                          % (cur, line[:50]))
        else:
            note.fail(i + 1, "front-matter line before any key: %r" % line)
    return keys, kv, end + 1


def _check_front_matter(note, keys, kv, allow_unorganized=False):
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

    def decoded(raw, label):
        try:
            return parse_scalar(raw)
        except ValueError as exc:
            note.fail(2, "invalid YAML in %s: %s" % (label, exc))
            return None, "invalid"

    def non_string(value):
        return (value is None or value.casefold() in
                ("null", "~", "true", "false", "yes", "no", "on", "off")
                or _NUMBER.fullmatch(value) or _DATE.fullmatch(value))

    for key in ("title", "description"):
        value = scalar(key)
        if value is None:
            continue
        quoted = bool(value) and value[0] in "\"'"
        parsed, style = decoded(value, "`%s`" % key)
        if style == "invalid":
            if quoted and (len(value) < 2 or value[-1] != value[0]):
                note.fail(2, "`%s` has an unterminated quoted YAML string" % key)
            elif not quoted:
                note.fail(2, "quote `%s` as a YAML string; its unquoted value "
                             "contains YAML syntax" % key)
        elif style == "bare" and non_string(parsed):
            note.fail(2, "quote `%s` as a YAML string; its unquoted value "
                         "is not a string" % key)
        elif not parsed or not parsed.strip():
            note.fail(2, "`%s` is empty" % key)

    fmt = scalar("format")
    if fmt is not None and fmt not in FORMATS:
        note.fail(2, "`format: %s` is not one of %s -- Article/Post/Video is a "
                     "clipping's enum and is wrong on a summary note"
                     % (fmt, "/".join(FORMATS)))

    if "sources" in kv:
        if kv["sources"][0]:
            note.fail(2, "`sources` is a block-form list; found a scalar value")
        raw_items = [l.strip() for l in kv["sources"][1] if l.strip()]
        for item in raw_items:
            if not item.startswith("- "):
                note.fail(2, "`sources` entry is not a block-list item: %r" % item)
        items = [i[1:].strip() if i.startswith("-") else i for i in raw_items]
        if not items:
            note.fail(2, "`sources` is empty -- item 1 is the PDF wikilink")
        inner = []
        for n, it in enumerate(items, 1):
            value, style = decoded(it, "`sources` item %d" % n)
            if style != "double":
                note.fail(2, "`sources` item %d must be double-quoted" % n)
            inner.append(value.strip() if isinstance(value, str) else "")
        if inner:
            first = inner[0]
            if not (first.startswith("[[") and first.endswith("]]")):
                note.fail(2, "`sources` item 1 must be the PDF wikilink, "
                             "e.g. \"[[Doe_X_2025.pdf]]\"")
            elif not first[2:-2].lower().endswith(".pdf"):
                note.fail(2, "`sources` item 1 must name a .pdf")
            elif re.search(r"[\[\]#|/\\\r\n]", first[2:-2]):
                note.fail(2, "`sources` item 1 must be one PDF wikilink without "
                             "an alias, page anchor or path qualification")
            else:
                note.source = first[2:-2]
        for n, it in enumerate(inner[1:], 2):
            if it.startswith("[["):
                note.fail(2, "`sources` item %d is a wikilink; only item 1 "
                             "names the PDF -- later items are the document's "
                             "printed URL(s)" % n)
            elif not _PRINTED_ORIGIN_URL.fullmatch(it):
                note.fail(2, "`sources` item %d must be a printed DOI or arXiv "
                             "identifier normalized to https://doi.org/... or "
                             "https://arxiv.org/abs/..." % n)
        if len(inner) > 2:
            note.fail(2, "`sources` holds %d items -- two is the maximum "
                         "(the PDF, then its printed URL)" % len(inner))
        if len(inner) > 1 and fmt == "Book":
            note.fail(2, "a `sources` URL item is never written on `format: Book`")

    source_is_canonical = bool(note.source and looks_canonical(note.source))
    source_core = core_stem(note.source) if source_is_canonical else ""
    source_parts = source_core.split("_")
    source_year = source_parts[2] if len(source_parts) >= 3 else None
    source_is_undated = source_year == "nd"
    if note.source and not source_is_canonical and not allow_unorganized:
        note.fail(2, "`sources` item 1 must use pdf-organizer's canonical PDF "
                     "filename before this summary can be published; pass "
                     "--allow-unorganized only with the deliberate scan override")
    for key in ("published", "created"):
        val = scalar(key)
        if val is None:
            continue
        if key == "published" and val == "null":
            if not source_is_undated and not allow_unorganized:
                note.fail(2, "`published: null` is reserved for a source PDF "
                             "whose canonical stem carries the `nd` year segment")
            continue
        if not _DATE.match(val):
            note.fail(2, "`%s: %s` must be a full YYYY-MM-DD date%s"
                         % (key, val, " (pad an unstated month or day with 01)"
                            if key == "published" else ""))
            continue
        valid_date = True
        try:
            datetime.date(*(int(p) for p in val.split("-")))
        except ValueError:
            valid_date = False
            note.fail(2, "`%s: %s` is not a real date" % (key, val))
        if key == "published" and source_is_undated:
            note.fail(2, "a dated `published` value conflicts with the source "
                         "PDF's canonical `nd` year segment; rename the source "
                         "through pdf-organizer first")
        elif (key == "published" and valid_date and source_year
              and source_year != val[:4]):
            note.fail(2, "the `published` year %s conflicts with the source PDF's "
                         "canonical %s year segment; rename the source through "
                         "pdf-organizer or correct the metadata"
                      % (val[:4], source_year))

    desc = scalar("description")
    if desc is not None:
        try:
            bare = parse_scalar(desc)[0]
        except ValueError:
            bare = None     # the malformed scalar was reported above
        if bare == "":
            note.fail(2, "`description` is empty")
        elif isinstance(bare, str) and len(bare) > MAX_DESCRIPTION:
            note.fail(2, "`description` is %d characters, over the %d limit"
                         % (len(bare), MAX_DESCRIPTION))

    if "author" in kv:
        inline = kv["author"][0]
        items = [l.strip() for l in kv["author"][1] if l.strip()]
        if inline:
            if inline != "[]" or items:
                note.fail(2, "`author` must be a block-form list when populated, "
                             "or exactly `author: []` when unknown")
            items = []
        elif not items:
            note.fail(2, "a missing author uses exactly `author: []`; bare "
                         "`author:` is YAML null, not an empty list")
        for it in items:
            if not it.startswith("- "):
                note.fail(2, "`author` entry is not a block-list item: %r" % it)
            elif "[[" in it:
                note.fail(2, "`author` entries carry no [[...]] wrapper: %r" % it)
            else:
                value, style = decoded(it[2:].strip(), "`author` entry")
                if not value or (style == "bare" and non_string(value)):
                    note.fail(2, "`author` entries must be non-empty YAML strings")

    if "tags" in kv:
        if kv["tags"][0]:
            note.fail(2, "`tags` must be a block-form list, not inline")
        items = [l.strip() for l in kv["tags"][1] if l.strip()]
        # A present-but-blank `tags:` is the documented no-discipline case.
        # The schema check still requires the key; populated values must keep
        # their block-list shape, quoting and enum membership below.
        for it in items:
            if not it.startswith("- "):
                note.fail(2, "`tags` entry is not a block-list item: %r" % it)
                continue
            val = it[2:].strip()
            inner, style = decoded(val, "`tags` entry")
            if style != "double":
                note.fail(2, "tag %s must be double-quoted -- an unquoted # "
                             "starts a YAML comment and the tag vanishes" % val)
                continue
            if not inner.startswith("#"):
                note.fail(2, "tag %s must be #-prefixed" % val)
            elif inner[1:] not in TAG_ENUM:
                note.fail(2, "tag %s is not in the CONVENTIONS.md 3 enum" % val)

    read = scalar("read")
    if read is not None and read not in ("false", "true"):
        note.fail(2, "`read: %s` must be a bare boolean (false on creation; "
                     "preserve true on rewrites). A quoted \"false\" is a "
                     "string and renders permanently ticked" % read)


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
            if _URLS.search(stripped[4:]):
                note.fail(i + 1, "the Summary callout contains a URL; keep "
                                 "source links in frontmatter or Availability")
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


def _check_structure(note, body_start, fenced, mode):
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
                  "%s -- each headed by a short sentence about this document, not by "
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
                             "this document -- say what this section actually found"
                      % (idx + 1, role, text))
            continue
        if len(bare) < MIN_HEADING:
            note.fail(n + 1, "heading %d (%s) is %d characters; a heading is a short "
                             "sentence about this document, at least %d"
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
                                         "to %d mode-appropriate disclosure or "
                                         "record items, with no reference list "
                                         "after them"
                              % (len(bullets), MIN_AVAILABILITY, MAX_AVAILABILITY))
                labels = []
                for bullet in bullets:
                    match = _AVAILABILITY_BULLET.match(bullet)
                    if not match:
                        note.fail(start + 1, "Availability bullets begin with "
                                             "a documented label: `**Data.**`, "
                                             "`**Code.**`, `**Materials.**`, "
                                             "`**Sources.**`, `**Record.**`, or "
                                             "`**Evidence.**`")
                        continue
                    labels.append(match.group(1).casefold())
                duplicates = sorted({label for label in labels
                                     if labels.count(label) > 1})
                if duplicates:
                    note.fail(start + 1, "Availability repeats label(s): %s"
                              % ", ".join(duplicates))
                allowed = AVAILABILITY_LABELS_BY_MODE[mode]
                wrong = sorted(set(labels) - allowed)
                if wrong:
                    note.fail(start + 1, "Availability label(s) %s do not apply in "
                                         "%s mode; use only %s"
                              % (", ".join(wrong), mode, ", ".join(sorted(allowed))))
                required = REQUIRED_AVAILABILITY_LABELS_BY_MODE[mode]
                missing = sorted(required - set(labels))
                if missing:
                    note.fail(start + 1, "%s mode requires separate Availability "
                                         "label(s): %s"
                              % (mode.capitalize(), ", ".join(missing)))
                for bullet, match in zip(bullets, [
                        _AVAILABILITY_BULLET.match(item) for item in bullets]):
                    if match and not bullet[match.end():].strip():
                        note.fail(start + 1, "an Availability bullet has a label but "
                                             "no disclosure or record text")
                        break
            if name == "Limitations":
                bullets = [l for l in content if l.startswith("- ")]
                if not MIN_LIMITATIONS <= len(bullets) <= MAX_LIMITATIONS:
                    note.fail(start + 1, "Limitations has %d bullets; it holds %d to "
                                         "%d in every mode -- only what would change how "
                                         "a reader acts on the document "
                                         "(references/note-format.md)"
                              % (len(bullets), MIN_LIMITATIONS, MAX_LIMITATIONS))
                elif (mode == "empirical"
                      and len(bullets) < PREFERRED_MIN_EMPIRICAL_LIMITATIONS):
                    note.advise(start + 1, "an empirical note normally carries at least "
                                "%d material limitations; keep one only when a second "
                                "would be filler, and explain the exception in the run report"
                                % PREFERRED_MIN_EMPIRICAL_LIMITATIONS)
                for b in bullets:
                    if not b[2:].strip():
                        note.fail(start + 1, "a Limitations bullet has no content")
                        break
                    if len(b) > MAX_LIMITATION_CHARS:
                        note.fail(start + 1, "a Limitations bullet is %d characters, "
                                             "over %d -- state the caveat, or move "
                                             "the detail beside the number it "
                                             "qualifies in Results"
                                  % (len(b), MAX_LIMITATION_CHARS))
                        break
            # Every line, not just one: a trailing paragraph after the last
            # bullet is how a reference list gets back into a note that is
            # supposed to end at Availability (the note-format terminator).
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
        # cap.  wiki-build's lint_entry guards this exact shape
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


def _check_prose(note, bounds, captions, fenced, body_start, mode):
    """Flag sentence-length targets; enforce paragraph, procedure and Results caps.

    Counts cannot decide whether a longer sentence is needed for clarity.
    Keep those advisories separate from the required structural limits.
    """
    for n, s, step in _prose_blocks(note, body_start, captions, fenced):
        target = MAX_STEP_WORDS if step else MAX_SENTENCE_WORDS
        counted = sentences(s)
        for sent in counted:
            words = len(sent.split())
            if words > target:
                note.advise(n + 1, "a %s runs %d words, over the %d-word target -- "
                                   "split or shorten first; retain only if that would "
                                   "obscure meaning, scope or a needed qualification. "
                                   "Explain the exception in the run report "
                                   "(references/note-format.md). Starts: %r"
                            % ("step" if step else "sentence", words, target,
                             " ".join(sent.split()[:9]) + "…"))
                break
        if not step and len(counted) > MAX_PARAGRAPH_SENTENCES:
            note.fail(n + 1, "a paragraph holds %d sentences, over %d -- one "
                             "topic per paragraph, six sentences at most "
                             "(references/note-format.md)"
                      % (len(counted), MAX_PARAGRAPH_SENTENCES))

    # In empirical mode, Methods carries a walked-through procedure as 3--8
    # numbered steps. A non-empirical source may still report a real procedure
    # (for example, a standards-development process or a notice review), but it
    # must not inherit the empirical minimum. Every numbered procedure remains
    # contiguous and capped so a source section is not copied wholesale.
    span = next(((s, e) for name, s, e in bounds if name == "Methods"), None)
    if span is not None:
        steps = [note.raw_lines[n].strip() for n in range(*span)
                 if n not in fenced and _STEP.match(note.raw_lines[n].strip())]
        if steps and mode == "empirical" \
                and not MIN_STEPS <= len(steps) <= MAX_STEPS:
            note.fail(span[0] + 1, "the empirical procedure lists %d numbered "
                                   "steps; it has %d to %d "
                                   "(references/note-format.md)"
                      % (len(steps), MIN_STEPS, MAX_STEPS))
        elif steps and mode != "empirical" and len(steps) > MAX_STEPS:
            note.fail(span[0] + 1, "the reported procedure lists %d numbered "
                                   "steps; keep at most %d in a concise reading "
                                   "note (references/note-format.md)"
                      % (len(steps), MAX_STEPS))
        numbers = [int(_STEP.match(s).group(1)) for s in steps]
        if numbers and numbers != list(range(1, len(numbers) + 1)):
            note.fail(span[0] + 1, "the procedure steps are numbered %s; they "
                                   "must run 1..%d in their reported order"
                      % (", ".join(str(x) for x in numbers), len(numbers)))

    span = next(((s, e) for name, s, e in bounds if name == "Results"), None)
    if span is None:
        return
    prose = _prose_lines(note, span[0], span[1], captions, fenced)
    chars = sum(len(t) for _n, t in prose)
    if chars > MAX_RESULTS_CHARS:
        note.fail(span[0] + 1, "Results holds %d characters of prose, over %d -- "
                               "it carries the document's main result developed "
                               "properly, with any secondary finding at a "
                               "sentence each (references/note-format.md). Exhibits and "
                               "their captions are not counted."
                  % (chars, MAX_RESULTS_CHARS))


def _prose_blocks(note, body_start, captions, fenced):
    """Yield readable paragraphs/list items with their first source line.

    A soft-wrapped sentence is still one sentence, and seven adjacent lines
    are still one paragraph. Blank lines, exhibits, headings, fences and new
    list items separate blocks; wrapped numbered steps retain their 20-word target.
    """
    pending = []
    first, is_step = 0, False
    for n in range(body_start, len(note.raw_lines)):
        s = note.raw_lines[n].strip()
        boundary = (n in fenced or not s or s == "___"
                    or s.startswith("## ") or s == "> [!Summary]"
                    or _TABLE_ROW.match(s) or _EMBED.match(s))
        if boundary:
            if pending:
                yield first, " ".join(pending), is_step
                pending = []
            continue
        # A callout marker is presentation, not part of the sentence.
        s = re.sub(r"\A>\s*", "", s)
        step = _STEP.match(s)
        bullet = s.startswith("- ")
        if step or bullet or n in captions:
            if pending:
                yield first, " ".join(pending), is_step
                pending = []
        if not pending:
            first, is_step = n, bool(step)
        pending.append(step.group(2) if step else s[2:] if bullet else s)
        if n in captions:
            yield first, " ".join(pending), is_step
            pending = []
    if pending:
        yield first, " ".join(pending), is_step


def _source_figure_inventory(images, source):
    """Return portable candidate names, or an error that blocks embedding.

    The source-scoped shared inventory rejects leaf symlinks, non-regular
    occupants, nested matches, staging residue and portable-name ambiguity.
    Looking up each embed with ``isfile`` follows symlinks and can therefore
    certify a file outside ``Sources/Images`` as a usable figure.
    """
    if not source or os.path.basename(source) != source \
            or not source.casefold().endswith(".pdf"):
        return None, None
    stem = os.path.splitext(source)[0]
    try:
        inventory = inventory_source_figures(images, stem)
    except ValueError as exc:
        return None, "cannot establish the source figure inventory: %s" % exc
    if inventory.safe:
        return {_name_key(os.path.basename(path))
                for path in inventory.candidates}, None

    details = []
    if inventory.blocked_matches:
        details.append("blocked source-keyed occupant(s): " + ", ".join(
            inventory.blocked_matches[:4]))
    details.extend("%s (%s)" % (finding.path, finding.message)
                   for finding in inventory.findings
                   if finding.severity == "error")
    return None, ("source figure inventory is unsafe: "
                  + "; ".join(details[:5] or [
                      "the image-folder inventory did not complete safely"]))


def _direct_regular_image(images, name):
    """No-follow fallback when invalid frontmatter provides no source stem."""
    try:
        item = os.lstat(os.path.join(images, name))
    except OSError:
        return False
    return stat.S_ISREG(item.st_mode)


def _check_figures(note, bounds, images, fenced, source=None):
    """Returns the set of line numbers that are captions, for later checks.

    A caption is *the line under an embed*, and nothing else.  Sniffing for one
    by asterisks matches any paragraph that happens to end on an italicised
    term -- `... the organism was *Escherichia coli*` -- and every check keyed
    off that guess then fires on ordinary prose.
    """
    lines = note.raw_lines
    available, inventory_error = ((None, None) if images is None else
                                  _source_figure_inventory(images, source))
    inventory_error_reported = False
    found_span = next(((s, e) for name, s, e in bounds
                       if name == "Results"), None)
    embeds, captions = 0, set()
    for n, l in enumerate(lines):
        if n in fenced:
            continue
        m = _EMBED.match(l.strip())
        if not m:
            if _ANY_EMBED.search(l):
                note.fail(n + 1, "a figure embed must occupy its own line; "
                                 "inline text around `![[...]]` breaks caption "
                                 "and inventory checks")
            continue
        embeds += 1
        name = m.group(1).split("|")[0].strip()
        filename_only = bool(
            name and name not in (".", "..")
            and "/" not in name and "\\" not in name
            and os.path.basename(name) == name)
        if not filename_only:
            note.fail(
                n + 1,
                "figure embed target %r must be one filename only, without "
                "path separators or dot segments; path qualification can "
                "escape the selected Sources/Images inventory" % name,
            )
        if filename_only and source and not _name_key(name).startswith(
                _name_key(os.path.splitext(source)[0]) + "_fig"):
            note.fail(n + 1, "figure embed %r is not filed under this note's "
                             "`sources:` PDF %r; select from its figure inventory"
                      % (name, source))
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
        if filename_only and images is not None:
            if inventory_error:
                if not inventory_error_reported:
                    note.fail(n + 1, inventory_error)
                    inventory_error_reported = True
            elif available is not None:
                if _name_key(name) not in available:
                    note.fail(n + 1, "embed names a file that is not in the safe "
                                     "source figure inventory: %s (Obsidian renders "
                                     "this as plain text, silently)" % name)
            elif not _direct_regular_image(images, name):
                note.fail(n + 1, "embed names a file that is not a direct regular "
                                 "file in the image folder: %s (Obsidian renders "
                                 "this as plain text, silently)" % name)
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
                                 "two numbers belong in a sentence "
                                 "(references/figures.md)")
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
    """references/figures.md: the note points at nothing the reader does not have.

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
                             "never carry the number (references/figures.md)"
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
        prose = re.sub(r"(?<!`)(`+)(?!`).*?(?<!`)\1(?!`)", " ", l)
        if _FOOTNOTE.search(prose):
            note.fail(n + 1, "footnote syntax in the note; page references are "
                             "inline links now (references/note-format.md)")
        wrapped = {c.start() for c in _CITATION.finditer(l)}
        for m in _PAGE_LINK.finditer(l):
            target, alias = m.group(1), m.group(2)
            page = target.rsplit("#page=", 1)[1]
            valid_page = bool(re.fullmatch(r"[0-9]+", page)) and int(page) >= 1
            open_at = m.start() - len("<sup>")
            if open_at not in wrapped:
                note.fail(n + 1, "page citation is not wrapped in `<sup>...</sup>`, "
                                 "so it renders full size: write "
                                 "`<sup>[[%s|%s]]</sup>`"
                          % (target, page))
            elif open_at > 0 and l[open_at - 1].isspace():
                note.fail(n + 1, "space before the citation; a superscript "
                                 "attaches to the character it follows, with no "
                                 "gap -- `…planned 220.<sup>…</sup>`")
            elif open_at == 0:
                note.fail(n + 1, "citation opens the line; it attaches to the end "
                                 "of the text it supports")
            if not valid_page:
                note.fail(n + 1, "page citations use physical pages starting at 1; "
                                 "page %s does not exist" % page)
            where = ("the front matter" if n < body_start else
                     "the callout" if n in in_callout else
                     "a caption" if n in captions else
                     "a heading" if l.lstrip().startswith("#") else
                     "a table" if _TABLE_ROW.match(l) else None)
            if where:
                note.fail(n + 1, "page citation in %s; citations are body-prose "
                                 "only" % where)
            if alias is None:
                note.fail(n + 1, "page citation shows its whole target; give it the "
                                 "page number as display text -- `[[%s|%s]]`"
                                 % (target, page))
            elif valid_page and (not re.fullmatch(r"[0-9]+", alias.strip())
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
            elif source and _name_key(base) != _name_key(source):
                note.fail(n + 1, "page citation points at %r, but this note's "
                                 "`sources:` item 1 is %r" % (base, source))



def _name_key(name):
    return unicodedata.normalize("NFC", name).casefold()


def lint(text, path="<note>", images=None, *, mode,
         allow_unorganized=False, advisories=None):
    """Return sorted blocking (line, message) pairs, preserving the list API.

    An empty result means no format violations. If supplied, append sorted
    advisories to the caller's list; they need review but never suppress a
    violation or change the returned list's shape.
    """
    if mode not in MODES:
        raise ValueError("mode must be one of: %s" % ", ".join(MODES))
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
    _check_front_matter(note, keys, kv, allow_unorganized)
    after = _check_callout(note, body_start, fenced)
    _check_rule(note, after)
    bounds = _check_structure(note, body_start, fenced, mode)
    src = note.source
    captions = _check_figures(note, bounds, images, fenced, src)
    captions |= _check_tables(note, bounds, fenced)
    _check_exhibit_numbers(note, body_start, captions, fenced)
    _check_prose(note, bounds, captions, fenced, body_start, mode)
    _check_citations(note, body_start, captions, fenced, src)
    if advisories is not None:
        advisories.extend(sorted(note.advisories))
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
        ("foreign figure despite a plausible filename",
         _mutate("Doe_X_2025_fig_2.png", "Other_Study_2025_fig_2.png"),
         "not filed under this note's"),
        ("legacy figure separator remains valid",
         _mutate("Doe_X_2025_fig_2.png", "doe_x_2025_figure_2.webp"), CLEAN),
        ("zero is not a physical page",
         _mutate("#page=5|5", "#page=0|0"), "physical pages starting at 1"),
        ("negative page cannot evade citation validation",
         _mutate("#page=5|5", "#page=-1|-1"), "physical pages starting at 1"),
        ("a word is not a physical page",
         _mutate("#page=5|5", "#page=five|5"), "physical pages starting at 1"),
        ("sources require the actual YAML list marker",
         _mutate('  - "[[Doe_X_2025.pdf]]"', '  "[[Doe_X_2025.pdf]]"'),
         "not a block-list item"),
        ("an unquoted title colon makes invalid YAML",
         _mutate('title: "A Title: With a Colon"', 'title: A Title: With a Colon'),
         "quote `title` as a YAML string"),
        ("null title is not a string",
         _mutate('title: "A Title: With a Colon"', 'title: null'),
         "quote `title` as a YAML string"),
        ("empty quoted title has no text",
         _mutate('title: "A Title: With a Colon"', 'title: ""'), "`title` is empty"),
        ("whitespace-only quoted title has no text",
         _mutate('title: "A Title: With a Colon"', "title: '  '"), "`title` is empty"),
        ("numeric title must be a string",
         _mutate('title: "A Title: With a Colon"', 'title: 12345'),
         "quote `title` as a YAML string"),
        ("quoted numeric title is text",
         _mutate('title: "A Title: With a Colon"', 'title: "12345"'), CLEAN),
        ("a title string must close its quote",
         _mutate('title: "A Title: With a Colon"', 'title: "Unfinished'),
         "unterminated quoted YAML string"),
        ("embedded unescaped title quotes are invalid YAML",
         _mutate('title: "A Title: With a Colon"', 'title: "A "quoted" trial"'),
         "invalid YAML in `title`"),
        ("a description cannot carry an unknown YAML escape",
         _mutate('description: Doe cut recurrence from 45% to 8% in a 219-patient trial.',
                 'description: "A \\q trial"'), "invalid YAML in `description`"),
        ("a commented null is still not a title string",
         _mutate('title: "A Title: With a Colon"', 'title: null # not recorded'),
         "quote `title` as a YAML string"),
        ("escaped ASCII in sources resolves to the real paper",
         _mutate('"[[Doe_X_2025.pdf]]"', '"[[\\x44oe_X_2025.pdf]]"'), CLEAN),
        ("comments and indentless sources retain their block-list meaning",
         _mutate('sources:\n  - "[[Doe_X_2025.pdf]]"',
                 'sources: # recorded origin\n# verified locally\n'
                 '- "[[\\x44oe_X_2025.pdf]]" # verified'), CLEAN),
        ("comments on plain schema fields and escaped tags are valid YAML",
         GOOD.replace('read: false', 'read: false # unread')
             .replace('format: Paper', 'format: Paper # local document')
             .replace('  - "#medicine"', '  - "#\\x6dedicine" # discipline'), CLEAN),
        ("noncanonical Unicode source spelling is rejected before identity matching",
         GOOD.replace("Doe_X_2025", "Müller_X_2025").replace(
             '"[[Müller_X_2025.pdf]]"', '"[[Mu\u0308ller_X_2025.pdf]]"'),
         "canonical PDF filename"),
        ("quote escapes count as decoded description characters",
         _mutate('description: Doe cut recurrence from 45% to 8% in a 219-patient trial.',
                 'description: "' + '\\u00e9' * 110 + '"'), CLEAN),
        ("null is not an author name",
         _mutate('  - Priya N. Doe', '  - null'), "non-empty YAML strings"),
        ("a mapping is not an author name",
         _mutate('  - Priya N. Doe', '  - Team: Trial group'), "invalid YAML in `author`"),
        ("the canonical authorless source note is an empty list",
         _mutate('author:\n  - Priya N. Doe', 'author: []'), CLEAN),
        ("a bare author is YAML null, not the authorless list",
         _mutate('author:\n  - Priya N. Doe', 'author:'), "exactly `author: []`"),
        ("an inline populated author is not the empty exception",
         _mutate('author:\n  - Priya N. Doe', 'author: [Priya N. Doe]'),
         "block-form list when populated"),
        ("heading citations are not body prose",
         _mutate(I_H, I_H + '<sup>[[Doe_X_2025.pdf#page=6|6]]</sup>'),
         "page citation in a heading"),
        ("table citations are not body prose",
         _mutate('| Transplant | 8.2% |',
                 '| Transplant | 8.2%.<sup>[[Doe_X_2025.pdf#page=5|5]]</sup> |'),
         "page citation in a table"),
        ("read true survives an authorized rewrite",
         _mutate("read: false", "read: true"), CLEAN),
        ("a soft-wrapped long sentence is counted as one",
         _mutate("Prose.",
                 "The investigators compared the outcomes for each of the treated participants\n"
                 "with the corresponding measurements from the matched untreated participants\n"
                 "in every ward during the scheduled follow-up visit."),
         "__ADVISORY__a sentence runs"),
        ("a soft-wrapped paragraph retains its sentence count",
         _mutate("Prose.", "One is stated.\nTwo follows.\nThree lands.\n"
                 "Four holds.\nFive stands.\nSix ends.\nSeven overflows."),
         "one topic per paragraph"),
        ("blank lines separate short paragraphs",
         _mutate("Prose.", "One is stated.\n\nTwo follows.\n\nThree lands.\n\n"
                 "Four holds.\n\nFive stands.\n\nSix ends.\n\nSeven follows."), CLEAN),
        ("a wrapped numbered step keeps its tighter target",
         _mutate(M_H + "\n\nProse.", M_H + "\n\nProse.\n\n"
                 "1. The investigators collected the original measurements from every participant\n"
                 "   and compared those measurements with the same measurements from matched controls across all participating hospitals.\n"
                 "2. They fitted the model.\n3. They evaluated the predictions."),
         "__ADVISORY__a step runs 24 words"),
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
        ("U.S. is not a sentence end",
         _mutate("Prose.", "The U.S. trial enrolled adults. The result held."),
         CLEAN),
        ("...and six real sentences still trip the cap",
         _mutate("## Worth offering after a second recurrence in adults\n\nProse.",
                 "## Worth offering after a second recurrence in adults\n\n"
                 "One is stated. Two follows. Three lands. Four holds. "
                 "Five stands. Six ends. Seven overflows."),
         "one topic per paragraph"),
        ("blank line above callout",
         _mutate("---\n> [!Summary]", "---\n\n> [!Summary]"), "blank line between"),
        ("URL in Summary callout",
         _mutate("> - Three.", "> - Details are at https://example.org/data."),
         "callout contains a URL"),
        ("quoted read", _mutate("read: false", 'read: "false"'), "bare boolean"),
        ("bare year", _mutate("published: 2025-01-03", "published: 2025"),
         "full YYYY-MM-DD"),
        ("undated source uses an explicit null",
         GOOD.replace("Doe_X_2025", "Doe_X_nd")
         .replace("published: 2025-01-03", "published: null", 1), CLEAN),
        ("junk after an nd year does not create a canonical undated source",
         GOOD.replace("Doe_X_2025", "Doe_X_nd_junk")
         .replace("published: 2025-01-03", "published: null", 1),
         "canonical PDF filename"),
        ("null publication date requires an nd source stem",
         _mutate("published: 2025-01-03", "published: null"),
         "reserved for a source PDF"),
        ("dated publication conflicts with an nd source stem",
         _mutate("[[Doe_X_2025.pdf]]", "[[Doe_X_nd.pdf]]"),
         "conflicts with the source PDF"),
        ("publication year matches the canonical source year",
         _mutate("published: 2025-01-03", "published: 2024-01-03"),
         "published` year 2024 conflicts"),
        ("blank tags when no discipline applies",
         _mutate('tags:\n  - "#medicine"', 'tags:'), CLEAN),
        ("commented blank tags retain the no-discipline meaning",
         _mutate('tags:\n  - "#medicine"',
                 'tags: # no discipline applies\n# intentionally unclassified'), CLEAN),
        ("the tags key is still required",
         _mutate('tags:\n  - "#medicine"\n', ''), "missing: tags"),
        ("an inline empty list is not the documented blank tags form",
         _mutate('tags:\n  - "#medicine"', 'tags: []'), "block-form list, not inline"),
        ("a populated tag still requires a list marker",
         _mutate('  - "#medicine"', '  "#medicine"'), "not a block-list item"),
        ("an empty string is not a discipline tag",
         _mutate('  - "#medicine"', '  - ""'), "must be #-prefixed"),
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
        ("one source-backed limitation is enough for a compact argument",
         _mutate("- **One.** Prose.\n- **Two.** Prose.", "- **One.** Prose."),
         CLEAN, "argument"),
        ("one empirical limitation asks for an anti-filler review",
         _mutate("- **One.** Prose.\n- **Two.** Prose.", "- **One.** Prose."),
         "__ADVISORY__a second would be filler"),
        ("five limitations",
         _mutate("- **One.** Prose.\n- **Two.** Prose.",
                 "\n".join("- **Item %d.** Prose here." % i for i in range(1, 6))),
         "it holds 1 to 4 in every mode"),
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
        ("empirical Availability requires Data",
         _mutate("- **Data.** Not stated.\n", ""),
         "requires separate Availability label(s): data"),
        ("empirical Availability omits inapplicable Code without boilerplate",
         _mutate("- **Code.** github.example/x\n", ""), CLEAN),
        ("Availability can use one mode-specific record item",
         _mutate("- **Data.** Not stated.\n- **Code.** github.example/x",
                 "- **Record.** The correction identifies the affected version."),
         CLEAN, "notice"),
        ("argument Availability accepts a supplied source",
         _mutate("- **Data.** Not stated.\n- **Code.** github.example/x",
                 "- **Sources.** The normative specification is supplied."),
         CLEAN, "argument"),
        ("notice mode rejects empirical availability labels",
         GOOD, "do not apply in notice mode", "notice"),
        ("Availability disclosure text cannot be empty",
         _mutate("- **Data.** Not stated.", "- **Data.** "),
         "no disclosure or record text"),
        ("a Limitations bullet cannot be empty",
         _mutate("- **One.** Prose.\n- **Two.** Prose.",
                 "- \n- **Two.** Prose."),
         "has no content"),
        ("Availability labels cannot repeat",
         _mutate("- **Code.** github.example/x",
                 "- **Data.** The supplement is public."),
         "repeats label"),
        ("Availability uses named disclosure bullets",
         _mutate("- **Code.** github.example/x",
                 "- **Software.** github.example/x"),
         "Availability bullets begin"),
        ("inline figure embed is rejected",
         _mutate("![[Doe_X_2025_fig_2.png]]",
                 "Result: ![[Doe_X_2025_fig_2.png]]"),
         "embed must occupy its own line"),
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
        ("body-mode role prose is not a document-specific heading",
         _mutate("## Worth offering after a second recurrence in adults",
                 "## What follows from the argument and how its contribution can be used"),
         "is the label"),
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
        ("a named footnote reference is still forbidden citation syntax",
         _mutate("Prose.", "Prose.[^source]"), "footnote"),
        ("numeric footnote examples inside code are literal text",
         _mutate("Prose.", "The token ``[^1]`` is literal code."), CLEAN),
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
        ("path-qualified PDF source is not a bare wikilink",
         _mutate('"[[Doe_X_2025.pdf]]"', '"[[Sources/PDFs/Doe_X_2025.pdf]]"'),
         "path qualification"),
        ("path-qualified figure cannot escape the image inventory",
         _mutate("![[Doe_X_2025_fig_2.png]]",
                 "![[Doe_X_2025_fig/../../outside.png]]"),
         "one filename only"),
        ("backslash-qualified figure is not a portable bare target",
         _mutate("![[Doe_X_2025_fig_2.png]]",
                 "![[Doe_X_2025_fig_2\\outside.png]]"),
         "one filename only"),
        ("empty sources list",
         _mutate('sources:\n  - "[[Doe_X_2025.pdf]]"\n  - "https://arxiv.org/abs/2501.02045"',
                 "sources:"), "is empty"),
        ("sources item 2 a wikilink",
         _mutate('  - "https://arxiv.org/abs/2501.02045"', '  - "[[Other_Y_2020.pdf]]"'),
         "only item 1 names the PDF"),
        ("sources item 2 is not an arbitrary web URL",
         _mutate('  - "https://arxiv.org/abs/2501.02045"',
                 '  - "https://publisher.example/paper"'),
         "printed DOI or arXiv"),
        ("sources item 2 uses canonical HTTPS DOI form",
         _mutate('  - "https://arxiv.org/abs/2501.02045"',
                 '  - "http://doi.org/10.1000/example"'),
         "normalized to https://doi.org"),
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
        ("scientific identifiers are not compact figure or table pointers",
         _mutate("More prose.<sup>", "TAB1 binds TAK1, and FIG4 regulates lipids.<sup>"),
         CLEAN),
        ("a caption may open with a scientific identifier",
         _mutate("*The arms separated", "*TAB1 and FIG4 differed"), CLEAN),
        ("a dotted abbreviated figure pointer remains a finding",
         _mutate("More prose.<sup>", "See Fig.2.<sup>"),
         "'Fig.2' points at something"),
        ("a spaced abbreviated figure pointer remains a finding",
         _mutate("More prose.<sup>", "See Fig 2.<sup>"),
         "'Fig 2' points at something"),
        ("a dotted abbreviated table pointer remains a finding",
         _mutate("More prose.<sup>", "See Tab.2.<sup>"),
         "'Tab.2' points at something"),
        ("a compact full figure label remains a finding",
         _mutate("More prose.<sup>", "See Figure2.<sup>"),
         "'Figure2' points at something"),
        ("a compact full table label remains a finding",
         _mutate("More prose.<sup>", "See Table2.<sup>"),
         "'Table2' points at something"),
        ("an abbreviated plural range remains a finding",
         _mutate("More prose.<sup>", "See Figs.2 and 3.<sup>"),
         "'Figs.2 and 3' points at something"),
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

        # --- sentence targets and required paragraph limits ----------------
        ("a sentence over the target is advisory only",
         _mutate("More prose.",
                 " ".join(["Recurrence"] * (MAX_SENTENCE_WORDS + 1)) + "."),
         "__ADVISORY__over the %d-word target" % MAX_SENTENCE_WORDS),
        ("NEAR MISS: a sentence exactly at the target is clean",
         _mutate("More prose.",
                 " ".join(["Recurrence"] * MAX_SENTENCE_WORDS) + "."),
         CLEAN),
        ("a long sentence in a caption is caught too",
         _mutate("*The arms separated",
                 "*" + " ".join(["Separation"] * (MAX_SENTENCE_WORDS + 1))
                 + ". The arms separated"),
         "__ADVISORY__a sentence runs"),
        ("a long sentence in the callout is caught too",
         _mutate("> - Two.",
                 "> - " + " ".join(["Message"] * (MAX_SENTENCE_WORDS + 1)) + "."),
         "__ADVISORY__a sentence runs"),
        ("NEAR MISS: a decimal does not end a sentence, so the clauses either "
         "side of one are counted together",
         _mutate("More prose.",
                 " ".join(["Recurrence"] * 14) + " r = 0.51 "
                 + " ".join(["and"] * 14) + " end."),
         "__ADVISORY__a sentence runs"),
        ("NEAR MISS: `et al.` does not end a sentence either",
         _mutate("More prose.",
                 " ".join(["Recurrence"] * 12) + " per Smith et al. 2019 "
                 + " ".join(["again"] * 12) + "."),
         "__ADVISORY__a sentence runs"),
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
         "empirical procedure lists"),
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
         "empirical procedure lists"),
        ("one reported procedure step is valid outside empirical mode",
         _mutate("## A 219-patient double-blind trial of transplant capsules\n\nProse.",
                 "## A 219-patient double-blind trial of transplant capsules\n\nProse.\n\n"
                 "1. The standards committee recorded its final decision."),
         CLEAN, "argument"),
        ("two reported procedure steps are valid outside empirical mode",
         _mutate("## A 219-patient double-blind trial of transplant capsules\n\nProse.",
                 "## A 219-patient double-blind trial of transplant capsules\n\nProse.\n\n"
                 "1. The committee reviewed the proposal.\n"
                 "2. The committee published its decision."),
         CLEAN, "argument"),
        ("a non-empirical reported procedure retains the concise cap",
         _mutate("## A 219-patient double-blind trial of transplant capsules\n\nProse.",
                 "## A 219-patient double-blind trial of transplant capsules\n\nProse.\n\n"
                 + "\n".join("%d. The committee completed one stage." % i
                              for i in range(1, MAX_STEPS + 2))),
         "keep at most", "argument"),
        ("steps out of order",
         _mutate("## A 219-patient double-blind trial of transplant capsules\n\nProse.",
                 "## A 219-patient double-blind trial of transplant capsules\n\nProse.\n\n"
                 "1. The team did a thing.\n3. The team did another.\n"
                 "4. The team did a third."),
         "must run 1.."),
        ("non-empirical procedure numbering remains contiguous",
         _mutate("## A 219-patient double-blind trial of transplant capsules\n\nProse.",
                 "## A 219-patient double-blind trial of transplant capsules\n\nProse.\n\n"
                 "1. The committee reviewed the proposal.\n"
                 "3. The committee published its decision."),
         "must run 1..", "argument"),
        ("a step over the 20-word target is advisory only",
         _mutate("## A 219-patient double-blind trial of transplant capsules\n\nProse.",
                 "## A 219-patient double-blind trial of transplant capsules\n\nProse.\n\n"
                 "1. " + " ".join(["The"] * (MAX_STEP_WORDS + 1)) + ".\n"
                 "2. The team did another.\n3. The team did a third."),
         "__ADVISORY__a step runs %d words" % (MAX_STEP_WORDS + 1)),
        ("NEAR MISS: a step exactly at 20 words is clean, though the same "
         "words as prose would still be under the 25-word target",
         _mutate("## A 219-patient double-blind trial of transplant capsules\n\nProse.",
                 "## A 219-patient double-blind trial of transplant capsules\n\nProse.\n\n"
                 "1. " + " ".join(["The"] * MAX_STEP_WORDS) + ".\n"
                 "2. The team did another.\n3. The team did a third."),
         CLEAN),
    ]


def _selftest():
    """CLEAN must produce nothing; a needle must produce a violation containing
    it; `__ADVISORY__x` must produce exactly one advisory and no violations;
    `__ONLY__x` must produce one violation containing x and nothing else --
    which is how a check that reports one fault as seven gets caught."""
    ok = fail = 0
    for case in _cases():
        name, note_text, needle = case[:3]
        mode = case[3] if len(case) == 4 else "empirical"
        advisories = []
        got = lint(note_text, mode=mode, advisories=advisories)
        if needle is CLEAN:
            good = not got and not advisories
        elif needle is None:
            good = bool(got)
        elif needle.startswith("__ADVISORY__"):
            want = needle[len("__ADVISORY__"):]
            good = not got and len(advisories) == 1 and want in advisories[0][1]
        elif needle.startswith("__ONLY__"):
            want = needle[len("__ONLY__"):]
            good = len(got) == 1 and want in got[0][1]
        else:
            good = any(needle in m for _, m in got)
        if good:
            ok += 1
        else:
            fail += 1
            print("FAIL  %-30s expected %r, got violations: %s; advisories: %s"
                  % (name, needle, "; ".join(m for _, m in got) or "(none)",
                     "; ".join(m for _, m in advisories) or "(none)"))

    # Exercise both the original list-returning API and the command's status:
    # an advisory must not block publication or hide a real violation. Image
    # bytes still need visual review, but the inventory itself must be direct,
    # regular and source-scoped before an embed can pass.
    import contextlib
    import io
    import tempfile
    long_note = _mutate("More prose.",
                        " ".join(["Recurrence"] * (MAX_SENTENCE_WORDS + 1)) + ".")
    if lint(long_note, mode="empirical") == []:
        ok += 1
    else:
        fail += 1
        print("FAIL  the original lint API returns only blocking violations")
    unorganized = GOOD.replace("Doe_X_2025", "Müller_X_2025")
    if lint(unorganized, mode="empirical", allow_unorganized=True) == []:
        ok += 1
    else:
        fail += 1
        print("FAIL  the deliberate unorganized-source lint override was ignored")
    unorganized_undated = unorganized.replace("published: 2025-01-03",
                                               "published: null")
    if lint(unorganized_undated, mode="empirical", allow_unorganized=True) == []:
        ok += 1
    else:
        fail += 1
        print("FAIL  the unorganized-source override rejected an explicit null date")
    with tempfile.TemporaryDirectory() as scratch:
        image_path = os.path.join(scratch, "Doe_X_2025_fig_2.png")
        with open(image_path, "wb") as fh:
            fh.write(b"")
        with tempfile.TemporaryDirectory() as outside:
            outside_image = os.path.join(outside, "outside.png")
            with open(outside_image, "wb") as fh:
                fh.write(b"outside")
            linked_image = os.path.join(scratch, "Doe_X_2025_fig_7.png")
            try:
                os.symlink(outside_image, linked_image)
            except (OSError, NotImplementedError):
                linked_image = None
            if linked_image is not None:
                linked_note = GOOD.replace(
                    "Doe_X_2025_fig_2.png", "Doe_X_2025_fig_7.png")
                linked_findings = lint(linked_note, images=scratch,
                                       mode="empirical")
                if any("source figure inventory is unsafe" in message
                       and linked_image in message
                       for _line, message in linked_findings):
                    ok += 1
                else:
                    fail += 1
                    print("FAIL  a source-keyed symlink outside Images passed "
                          "the figure inventory: %r" % linked_findings)
                os.unlink(linked_image)
        invalid_note = (long_note.replace("read: false", 'read: "false"')
                        .replace("#page=5|5", "#page=0|0")
                        .replace("Doe_X_2025_fig_2.png", "Doe_X_2025_fig_9.png"))
        for name, text, status, required in [
                ("CLI clean note with existing image", GOOD, 0, [": clean"]),
                ("CLI sentence advisory does not fail", long_note, 0,
                 [": advisory:", "no violations", "1 advisory(s)"]),
                ("CLI advisory preserves schema, citation and image failures",
                 invalid_note, 1,
                 [": advisory:", "bare boolean", "physical pages starting at 1",
                  "embed names a file", "violation(s)"])]:
            note_path = os.path.join(scratch, "note.md")
            with open(note_path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main([note_path, "--mode", "empirical",
                               "--images", scratch])
            if result == status and all(part in output.getvalue() for part in required):
                ok += 1
            else:
                fail += 1
                print("FAIL  %s: status %r, output %r"
                      % (name, result, output.getvalue()))
        crlf_path = os.path.join(scratch, "crlf-note.md")
        with open(crlf_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(GOOD.replace("\n", "\r\n"))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main([crlf_path, "--mode", "empirical",
                           "--images", scratch])
        if result == 1 and "CRLF line endings" in output.getvalue():
            ok += 1
        else:
            fail += 1
            print("FAIL  the public CLI normalized CRLF before linting: "
                  "status %r, output %r" % (result, output.getvalue()))
        note_path = os.path.join(scratch, "note-without-images.md")
        with open(note_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(GOOD)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main([note_path, "--mode", "empirical"])
        if result == 1 and "--images is required" in output.getvalue():
            ok += 1
        else:
            fail += 1
            print("FAIL  CLI omitted --images without disclosing unchecked "
                  "embeds: status %r, output %r" %
                  (result, output.getvalue()))
    # Same trailer as every other script in the plugin ("N/M self-test cases
    # pass"), which README.md documents as uniform and this one alone did not
    # emit -- so a caller grepping for it read a passing run as a missing suite.
    print("%d/%d self-test cases pass" % (ok, ok + fail))
    return 0 if not fail else 1


def _configure_stdio():
    """Keep user paths and note text writable through narrow host pipes."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (AttributeError, OSError, ValueError):
                pass


def main(argv=None):
    _configure_stdio()
    p = argparse.ArgumentParser(
        description="Check a summary note against paper-summarizer's format.")
    p.add_argument("note", nargs="?", help="the .md note to check")
    p.add_argument("--images", help="image folder; also verify every embed resolves")
    p.add_argument("--mode", choices=MODES,
                   help="selected body mode (required when checking a note)")
    p.add_argument("--allow-unorganized", action="store_true",
                   help="accept a deliberately unorganized PDF source name; its "
                        "year segment cannot be cross-checked")
    p.add_argument("--test", action="store_true", help="run the self-tests")
    a = p.parse_args(argv)
    if a.test:
        return _selftest()
    if not a.note:
        p.error("give a note path, or --test")
    if not a.mode:
        p.error("--mode is required when checking a note because the body mode "
                "is not stored in the note")
    if not os.path.isfile(a.note):
        sys.stderr.write("not a file: %s\n" % a.note)
        return 2
    if a.images is not None and not os.path.isdir(a.images):
        sys.stderr.write("--images is not a directory: %s\n" % a.images)
        return 2
    # Preserve physical line endings. Universal-newline translation would
    # turn CRLF into LF before ``lint`` can enforce the repository's LF-only
    # note contract, so the public CLI would accept bytes the library API
    # correctly rejects.
    with open(a.note, encoding="utf-8", newline="") as fh:
        text = fh.read()
    advisories = []
    findings = lint(text, a.note, a.images, mode=a.mode,
                    allow_unorganized=a.allow_unorganized,
                    advisories=advisories)
    if a.images is None:
        fenced = _fenced(text.splitlines())
        for index, line in enumerate(text.splitlines()):
            if index not in fenced and _ANY_EMBED.search(line):
                findings.append((
                    index + 1,
                    "--images is required when the note embeds a figure; "
                    "resolution and source ownership were not checked",
                ))
                break
        findings.sort()
    for line, msg in findings:
        print("%s:%s: %s" % (a.note, line if line else "-", msg))
    for line, msg in advisories:
        print("%s:%s: advisory: %s" % (a.note, line if line else "-", msg))
    if findings:
        print("%d violation(s)" % len(findings))
    elif advisories:
        print("%s: no violations" % a.note)
    else:
        print("%s: clean" % a.note)
    if advisories:
        print("%d advisory(s); review before publication" % len(advisories))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
