#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lint_entry.py -- mechanical Quality Checklist checks for wiki entries.

Runs only the objectively checkable items of SKILL.md's Quality Checklist --
the ones the skill itself labels "mechanical".  Everything requiring
judgement (prose quality, tag calibration, alias semantics, merge integrity,
example discipline) is deliberately NOT checked here; those stay with the
model.

Implemented checks (Quality Checklist item -> finding ``item`` slug):

  1   1-valid-yaml            frontmatter fenced by ---, parses, no dupe keys
  2   2-field-order           schema order; mandatory keys present
                              (parents: present, `[]` when empty; read: last)
  2   2-type-enum             type: is one of the 15 enum values
  2   2-quoting               Quoting Policy: title/description and every
                              aliases/sources/tags/parents item double-quoted;
                              type/created/updated/read never quoted;
                              double quotes, never single
  3   3-dates                 created/updated are YYYY-MM-DD; created <= updated
  4   4-duplicate-source      no two sources: items name the same document: a
                              .md item whose stem equals a .pdf item's stem is
                              the PDF and its clipping-processor note, i.e. one
                              source recorded twice (stems compared case- and
                              NFC-insensitively, anchor and folder stripped)
  5   5-slug                  re-run slugify on title:; must equal the filename
  7   7-description           <= 110 chars (count reported), plain text, no
                              LaTeX/markdown/wikilinks, capitalised, ends "."
  8   8-tags                  #-prefixed, double-quoted, in the 27-slug enum
  9   9-sentence-length       any body-prose sentence of >= 35 words (warning:
                              item 9's split rule; captions, table rows,
                              display math and embeds are excluded, and how to
                              split stays the model's call)
  10  10-duplicate-wikilink   same TARGET SLUG linked >1x in body prose
                              (counted by target, not display text; the
                              Related footer is exempt).  This is item 10's
                              MECHANICAL HALF ONLY -- whether every target
                              resolves is a whole-VAULT question and belongs
                              to wiki-linter's scanner (CONVENTIONS.md §9),
                              which already carries the four carve-outs that
                              make the answer safe to act on
  16  16-bold-opener          first bolded span of the opening sentence equals
                              title:, with the parenthetical base-term and the
                              symbol/variable math-skeleton carve-outs
  17  17-alias-completeness   an alternative name the body introduces for the
                              entry's own subject -- an italicized also-called
                              synonym, or the opener's acronym/expansion
                              parenthetical -- whose slug is missing from
                              aliases: (warning: the same-entity test and the
                              cross-domain carve-out stay with the model)
  19  19-flashcards          `## Flashcards` present on every full entry,
                              preceded by a `---` separator, holding exactly
                              one card; line 2 exactly `??` (or the user's
                              `!!`); line 3 the canonical title (base term for
                              a parenthetical title, math skeleton for a
                              symbol title; optional trailing acronym
                              parenthetical)
  19  19-flashcard-leak       case-insensitive substring search of card line 1
                              (including inside $...$) for the title and each
                              alias, in both the raw and the de-hyphenated
                              surface form
  --  stub-*                  stub structural rules: one-sentence body, no
                              Related footer, no images, no Flashcards,
                              sources: ["stub"], >=1 tag
  18  18-alias-collision      across a folder, no two entries share an alias
  18  18-alias-duplicate      the same alias listed twice within one entry
  18  18-alias-form           every alias is itself in slug form (warning)

NOT implemented (out of scope by design): item 4's FORM rules (extension
present, ``#page=N`` anchor shape -- wiki-linter's scanner owns those; only
item 4's same-document rule is checked here), items 6, 9 beyond the opener and
the sentence-length flag, 11-15, 17 beyond the introduced-alias scan, and the
interpretive halves of 8/18/19.

Severity: ``error`` (a stated rule is violated), ``warning`` (very likely a
violation but the rule has a documented carve-out), ``info`` (advisory).

Module use:
    from lint_entry import lint_file, lint_path
    report = lint_path("/path/to/Wiki")

CLI:
    lint_entry.py <entry.md | wiki-folder>
      [--severity error|warning|info]   drop findings below this floor
      [-o out.json]                     write JSON here instead of stdout
      [--compact]                       compact JSON

Output: {root, entries:[{file, findings:[{item, severity, message,
evidence}], is_stub, title, aliases, description_chars}], alias_collisions[],
summary, problems[]}.  ``18-alias-collision`` only has meaning in folder
scope; ``18-alias-form`` (each alias is itself in slug form) is a warning.

A populated ``parents:`` is deliberately NOT flagged -- wiki-linter writes
that field on every full entry, so a value there is the expected steady
state.  Its quoting is covered by ``2-quoting`` and its presence by
``2-field-order``.

``read: true`` is likewise NOT flagged: the value is the user's, and this
script checks only that the key is present (``2-field-order``), sits last in
the schema (``2-field-order``) and is unquoted (``2-quoting``) -- a quoted
``"false"`` is a string, which Obsidian's checkbox renders as permanently
checked.  Whether a merge should have RESET the field is not mechanisable --
no script can see whether a body gained substance -- and a missing ``read:``
is reported for a human to resolve, never repaired: writing ``read: false``
into an entry the user had already marked read destroys the state the field
exists to hold.

``importance:`` was dropped from the schema (it measured 97 high / 7 medium /
1 low across 123 entries -- a field carrying no information).  New entries
omit the key; legacy entries in the vault still carry it, populated.  It gets
the same treatment as a populated ``parents:`` -- NO finding at any severity:
it is absent from ``MANDATORY_KEYS`` (never required), absent from
``NEVER_QUOTED`` (its value is never inspected), and there is no enum or stub
check for it.  It stays in ``vault_index.SCHEMA_ORDER`` on purpose, so that a
legacy entry carrying it in its historical slot is neither reported as an
out-of-order key nor as an unknown one.

Exit code is ALWAYS 0 -- this is a reporting tool, not a gate.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
import unicodedata

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

from slugify import SlugError, base_term, has_parenthetical, slug_stem  # noqa: E402
from vault_index import (  # noqa: E402
    SCHEMA_ORDER,
    extract_wikilinks,
    fold_name,
    index_entry,
    iter_markdown_files,
    parse_frontmatter,
    split_sections,
    unquote_scalar,
)

__all__ = ["lint_text", "lint_file", "lint_path", "TAG_ENUM", "TYPE_ENUM"]

MANDATORY_KEYS = ["title", "type", "sources", "created", "updated",
                  "description", "tags", "parents", "read"]
OPTIONAL_KEYS = ["aliases"]

TYPE_ENUM = [
    "Concept", "Person", "Organization", "Dataset", "Software", "Device",
    "Event", "Standard", "Gene/Protein", "Organism", "Chemical", "Reaction",
    "Place", "Work", "Quote",
]

TAG_ENUM = [
    "mathematics", "statistics", "physics", "chemistry", "biology",
    "earth-science", "medicine", "engineering", "computer-science",
    "psychology", "sociology", "anthropology", "economics", "finance",
    "political-science", "linguistics", "history", "philosophy",
    "literature", "law", "business", "entrepreneurship", "education", "architecture", "art",
    "music", "machine-learning",
]

ALWAYS_DOUBLE_QUOTED = ["title", "description"]
NEVER_QUOTED = ["type", "created", "updated", "read"]
QUOTED_LIST_FIELDS = ["aliases", "sources", "tags", "parents"]

DESCRIPTION_MAX = 110

#: Item 9's sentence-length rule: any body-prose sentence of this many words
#: or more is flagged for splitting.  The prose target is ~25; the flag sits
#: at 35 so it fires on the unambiguous offenders, not on every long-ish
#: sentence -- the reference is `writing.md` §2, prose principle 9.
SENTENCE_MAX_WORDS = 35

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BOLD3_RE = re.compile(r"\*\*\*(.+?)\*\*\*")
_BOLD2_RE = re.compile(r"\*\*(.+?)\*\*")
#: Abbreviations whose trailing period is not a sentence end.  Matched
#: case-insensitively and only at a word boundary, against the text ending at
#: the candidate period -- never with a bare ``str.replace``, which is what the
#: first version did: it rewrote the ``c.`` inside ``Inc.`` and the ``d.``
#: inside ``Ltd.``, and it was case-sensitive, so the ``b.`` entry here never
#: matched the ``B.`` of a name.  Single letters are listed for documentation;
#: ``_INITIAL_RE`` below covers them in any case.
_ABBREVS = [
    "e.g.", "i.e.", "cf.", "et al.", "approx.", "vs.", "ca.", "c.", "fl.",
    "Dr.", "Prof.", "Mr.", "Mrs.", "Ms.", "St.", "Jr.", "Sr.", "Fig.",
    "No.", "b.", "d.", "r.", "U.S.", "U.K.",
]

#: ``<head>`` ends with a known abbreviation, at a word boundary.
_ABBREV_RE = re.compile(
    r"(?:^|[^0-9A-Za-z])(?:%s)$"
    % "|".join(re.escape(a) for a in sorted(_ABBREVS, key=len, reverse=True)),
    re.IGNORECASE)

#: ``<head>`` ends with a single-letter initial -- ``B. F. Skinner``,
#: ``W. E. B. Du Bois``, and the ``(b. 1960)`` / ``(fl. 1200)`` parentheticals
#: the stub format requires on a ``Person`` opener.  The left context is "not a
#: letter or digit" rather than "whitespace", because a stub body opens by
#: bolding the name, so the first initial is preceded by ``**`` and not by a
#: space (``**W. E. B. Du Bois** ...``).  Apostrophes are EXCLUDED from that
#: left context: the ``s`` of a sentence-final possessive (``the predictor's.
#: The next ...``) is preceded by ``'``, which read as an initial and MERGED
#: the two sentences -- four entries on a real vault re-flagged a phantom
#: 35+-word "sentence" every run.  A genuine initial preceded by an apostrophe
#: does not occur in practice; a possessive ends nearly every affected clause.
_INITIAL_RE = re.compile(r"(?:^|[^0-9A-Za-z'’])[A-Za-z]\.$")


def _f(item, severity, message, evidence=None):
    return {"item": item, "severity": severity, "message": message,
            "evidence": evidence}


# --------------------------------------------------------------------------
# small text helpers
# --------------------------------------------------------------------------

def math_skeleton(text):
    """Strip LaTeX wrappers down to the plain-text skeleton of a title.

    ``$\\mathbf{k}$-nearest neighbors`` -> ``k-nearest neighbors``.
    """
    s = text.replace("$", "")
    for _ in range(4):
        new = re.sub(r"\\[A-Za-z]+\s*\{([^{}]*)\}", r"\1", s)
        if new == s:
            break
        s = new
    s = re.sub(r"\\[A-Za-z]+", "", s)
    s = s.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", s).strip()


def first_letter_ci_equal(a, b):
    """Equality that is case-insensitive on the FIRST letter only (item 16)."""
    if a is None or b is None:
        return False
    if len(a) != len(b):
        return False
    if not a:
        return True
    return a[0].lower() == b[0].lower() and a[1:] == b[1:]


def count_sentences(text):
    """Rough sentence count: how many ``.``/``!``/``?`` runs really end a sentence.

    A run counts only when it is followed by whitespace or end-of-text *and*
    is not one of the three things that merely look like a sentence end:

    * **A decimal point or version dot** -- ``3.5``, ``GPT-4.5``, ``v1.2.3``.
      The dot has a digit hard up against it, so it is not a boundary at all.
    * **A single-letter initial** -- ``B. F. Skinner``, ``W. E. B. Du Bois``,
      and the ``(b. 1960)`` / ``(c. 1500)`` parentheticals a ``Person`` stub's
      opener carries.  This is the false positive that mattered: the skill's
      own conventions make every ``Person`` stub open with the bolded name, so
      an initialled subject reported ``found roughly 3`` on a one-sentence body
      forever, while the byte-identical body under ``Jane Doe`` reported
      nothing.
    * **A known abbreviation** -- ``et al.``, ``e.g.``, ``i.e.``, ``cf.``,
      ``vs.``, ``Dr.``, ``Prof.``, ``St.``, ``Jr.`` and the rest of
      ``_ABBREVS``, matched case-insensitively at a word boundary.

    It stays deliberately rough, and it errs toward *under*-counting: a
    sentence genuinely ending in an abbreviation or an initial ("...written in
    C. It compiles...") folds into the next one.  The only consumer is the stub
    one-sentence check, which reports "roughly N" at ``warning`` severity, so a
    missed split is cheap and a phantom split is not.
    """
    s = " ".join(text.split())
    count = 0
    for m in re.finditer(r"[.!?]+", s):
        nxt = s[m.end():m.end() + 1]
        if nxt and not nxt.isspace():
            continue          # not a boundary: `3.5`, `GPT-4.5`, `e.g.`'s inner dot
        if m.group(0) == ".":
            # Only the TAIL can match the $-anchored patterns (longest
            # abbreviation is 7 chars; 16 keeps the boundary char in view), and
            # searching the whole growing head made the scan quadratic -- 26 s
            # on a 125 KB body, stalling a folder lint on one oversized entry.
            head = s[max(0, m.end() - 16):m.end()]
            if _INITIAL_RE.search(head) or _ABBREV_RE.search(head):
                continue
        count += 1
    return count


def _valid_date(value):
    if not value or not _DATE_RE.match(value):
        return None
    try:
        return _dt.date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return None


def _style_of(raw):
    return unquote_scalar(raw)[1]


def source_stem(item):
    """``(stem, ext)`` of one ``sources:`` item, both case-folded.

    The pair is the identity of the DOCUMENT the item names, so everything
    that can vary without changing which document that is gets dropped: the
    ``[[ ]]`` wrapper, a ``#page=N`` anchor, a display pipe, and any folder
    qualification (``Sources/PDFs/X.pdf`` and ``X.pdf`` are one file).
    Case AND Unicode normalization are folded because the documented vault
    lives on a filesystem that is insensitive to both, where ``X.md``,
    ``x.md`` and the NFD spelling of either are all the same name.

    ``("", "")`` when the item carries no extension at all -- the ``"stub"``
    marker, or a malformed item whose missing extension is item 4's own
    finding rather than this one's.
    """
    inner = (item or "").strip()
    if inner.startswith("[[") and inner.endswith("]]"):
        inner = inner[2:-2]
    inner = inner.split("|", 1)[0]                       # display pipe
    inner = inner.split("#", 1)[0]                       # #page=N anchor
    inner = inner.replace("\\", "/").rsplit("/", 1)[-1]  # folder qualification
    stem, dot, ext = inner.rpartition(".")
    if not dot:
        return "", ""
    # NFC as well as case: a ``.pdf`` item read off an APFS disk is NFD and the
    # ``.md`` twin typed into a note is NFC -- one document to the filesystem
    # and to Obsidian, two unequal strings here, so the ``4-duplicate-source``
    # pair went unreported. CONVENTIONS.md 7 requires this to agree exactly
    # with wiki-linter's scan_vault.source_stem(); keep the two lines identical.
    return (unicodedata.normalize("NFC", stem.strip()).lower(),
            unicodedata.normalize("NFC", ext.strip()).lower())


def parse_flashcards(flashcard_lines):
    """Group the Flashcards section into cards (blank-line separated)."""
    cards, buf = [], []
    for line in flashcard_lines:
        if line.strip() == "":
            if buf:
                cards.append(buf)
                buf = []
        else:
            buf.append(line)
    if buf:
        cards.append(buf)
    return cards


# --------------------------------------------------------------------------
# the checks
# --------------------------------------------------------------------------

def _check_structure(fm, findings):
    if not fm.found:
        for err in fm.errors:
            findings.append(_f("1-valid-yaml", "error", err))
        return False
    for err in fm.errors:
        severity = "error" if "duplicate" in err or "unparseable" in err else "warning"
        findings.append(_f("1-valid-yaml", severity, err))
    return True


def _check_field_order(fm, findings):
    present, seen = [], set()
    for key in fm.order:                       # dedupe: duplicate keys are
        if key in SCHEMA_ORDER and key not in seen:  # already a 1-valid-yaml
            seen.add(key)                            # finding on their own
            present.append(key)
    expected = [k for k in SCHEMA_ORDER if k in present]
    if present != expected:
        findings.append(_f(
            "2-field-order", "error",
            "frontmatter keys are not in schema order",
            {"found": present, "expected": expected}))

    for key in MANDATORY_KEYS:
        if key not in fm.fields:
            findings.append(_f(
                "2-field-order", "error",
                "mandatory key %r is missing (the key is never omitted, even "
                "when the value is blank)" % key))

    # `importance` is no longer mandatory (it left the schema) but is still in
    # SCHEMA_ORDER, so a legacy entry that carries it in its historical slot
    # passes both the order check above and the unknown-key check below.
    unknown = [k for k in fm.order
               if k not in SCHEMA_ORDER and k not in OPTIONAL_KEYS]
    for key in unknown:
        findings.append(_f("2-field-order", "warning",
                           "key %r is not part of the entry schema" % key))

    # An empty `parents:` is written `parents: []`, never bare: a bare key is
    # YAML null, and the vault pins the property as multitext, so Obsidian
    # renders it as an empty TEXT field -- the declared type and the value on
    # disk disagree (CONVENTIONS.md 2a; scan_vault emits item2/parents-null
    # for the same fault).  `tags:` is the one key where blank is legal.
    parents = fm.get("parents")
    if parents is not None and parents.kind == "blank":
        findings.append(_f(
            "2-field-order", "error",
            "empty parents: is written `parents: []` (a bare key is YAML null "
            "against the vault's multitext property)",
            {"line": parents.line}))


def _check_type(fm, findings):
    field = fm.get("type")
    if field is None:
        return
    value = field.scalar
    if not value:
        findings.append(_f("2-type-enum", "error", "type: is blank; it is mandatory"))
    elif value not in TYPE_ENUM:
        findings.append(_f("2-type-enum", "error",
                           "type: %r is not one of the 15 enum values" % value,
                           {"value": value, "enum": TYPE_ENUM}))


def _check_quoting(fm, findings):
    for key in ALWAYS_DOUBLE_QUOTED:
        field = fm.get(key)
        if field is None:
            continue
        style = _style_of(field.raw_value)
        if style != "double":
            findings.append(_f(
                "2-quoting", "error",
                "%s: must be double-quoted (Quoting Policy)" % key,
                {"line": field.line, "raw": field.raw_value, "style": style}))

    for key in NEVER_QUOTED:
        field = fm.get(key)
        if field is None or field.kind == "blank":
            continue
        style = _style_of(field.raw_value)
        if style in ("double", "single"):
            findings.append(_f(
                "2-quoting", "error",
                "%s: must never be quoted -- it is a bare enum/date/boolean "
                "value" % key,
                {"line": field.line, "raw": field.raw_value, "style": style}))

    for key in QUOTED_LIST_FIELDS:
        field = fm.get(key)
        if field is None:
            continue
        for raw, line in zip(field.raw_items, field.item_lines):
            style = _style_of(raw)
            if style != "double":
                findings.append(_f(
                    "2-quoting", "error",
                    "every item under %s: must be double-quoted "
                    "(single quotes and bare values are both wrong)" % key,
                    {"line": line, "raw": raw, "style": style}))


def _check_dates(fm, findings):
    created = _valid_date(fm.scalar("created"))
    updated = _valid_date(fm.scalar("updated"))
    for key, parsed in (("created", created), ("updated", updated)):
        field = fm.get(key)
        raw = fm.scalar(key)
        if field is None:
            continue
        if parsed is None:
            findings.append(_f("3-dates", "error",
                               "%s: %r is not a valid YYYY-MM-DD date" % (key, raw),
                               {"line": field.line, "raw": raw}))
    if created and updated and created > updated:
        findings.append(_f("3-dates", "error",
                           "created (%s) is later than updated (%s)"
                           % (created, updated),
                           {"created": str(created), "updated": str(updated)}))


def _check_slug(fm, findings, filename):
    title = fm.scalar("title")
    stem = os.path.splitext(os.path.basename(filename))[0]
    if not title:
        findings.append(_f("5-slug", "error", "title: is blank or missing, so the "
                                              "slug check cannot run"))
        return
    try:
        expected = slug_stem(title)
    except SlugError as exc:
        findings.append(_f("5-slug", "error",
                           "title %r cannot be slugged: %s" % (title, exc)))
        return
    if expected != stem:
        findings.append(_f(
            "5-slug", "error",
            "filename does not match the slug of title: (expected %s.md)" % expected,
            {"title": title, "expected_filename": expected + ".md",
             "actual_filename": os.path.basename(filename)}))


def _check_description(fm, findings, title=None):
    field = fm.get("description")
    if field is None:
        return
    desc = field.scalar or ""
    length = len(desc)
    if length == 0:
        findings.append(_f("7-description", "error", "description: is blank"))
        return
    if length > DESCRIPTION_MAX:
        findings.append(_f(
            "7-description", "error",
            "description is %d characters (limit %d, over by %d)"
            % (length, DESCRIPTION_MAX, length - DESCRIPTION_MAX),
            {"chars": length, "limit": DESCRIPTION_MAX, "description": desc}))

    markup = []
    if "$" in desc:
        markup.append("$ (LaTeX / literal dollar)")
    # The rule forbids markdown CONSTRUCTS, not the character: "A 5* rating
    # system." is plain text.  Match a bold pair or a complete italic span, the
    # same pattern wiki-linter's scanner uses.
    if re.search(r"\*\*|\*\w[^*]*\*", desc):
        markup.append("* (markdown emphasis)")
    if "`" in desc:
        markup.append("` (backtick code)")
    if "[[" in desc:
        markup.append("[[ (wikilink)")
    if markup:
        findings.append(_f(
            "7-description", "error",
            "description must be plain text -- found %s" % ", ".join(markup),
            {"chars": length, "description": desc}))

    if desc[0].isalpha() and not desc[0].isupper():
        # Carve-out: the description's subject must be the canonical title form,
        # so a lowercase-initial title ("k-nearest neighbors", "scikit-learn")
        # legitimately produces a lowercase-initial description.  The skill's
        # "Capitalized first word" rule and its entity-as-subject rule collide
        # here; entity-as-subject wins.
        subjects = [s for s in (title, base_term(title) if title else None) if s]
        lowercase_title_subject = any(
            s[0].islower() and desc.startswith(s) for s in subjects)
        if not lowercase_title_subject:
            findings.append(_f("7-description", "info",
                               "description does not start with a capitalised word",
                               {"description": desc}))
    if not desc.rstrip().endswith("."):
        findings.append(_f("7-description", "info",
                           "description does not end with a period",
                           {"description": desc}))


def _check_tags(fm, findings, is_stub):
    field = fm.get("tags")
    if field is None:
        return
    values = [v for v in field.values if v not in (None, "")]
    if not values:
        if is_stub:
            findings.append(_f("8-tags", "error",
                               "stubs always get at least one tag -- blank tags: "
                               "is not allowed on a stub"))
        return
    for raw, value, line in zip(field.raw_items, field.values, field.item_lines):
        style = _style_of(raw)
        if style != "double":
            # already reported by the quoting check; add the specific failure mode
            if style == "bare" and raw.startswith("#"):
                findings.append(_f(
                    "8-tags", "error",
                    "unquoted %s parses as a YAML comment -- the discipline is "
                    "silently lost; write - \"%s\"" % (raw, raw),
                    {"line": line, "raw": raw}))
        if not value.startswith("#"):
            findings.append(_f("8-tags", "error",
                               "tag %r is not #-prefixed" % value,
                               {"line": line, "raw": raw}))
            continue
        slug = value[1:]
        if slug not in TAG_ENUM:
            findings.append(_f(
                "8-tags", "error",
                "tag #%s is not one of the 27 valid discipline slugs" % slug,
                {"line": line, "value": value, "enum": TAG_ENUM}))


def _check_aliases(fm, findings):
    """Every alias is itself a slug (writing.md, `aliases` field definition).

    An alias written as prose ("receiver operating characteristic") never
    matches anything: find_collisions.py probes aliases as slugs, so a
    non-slug alias is silently unprobed and the entry it should have caught
    gets written a second time.  Warning, not error -- the value is still
    readable, and the fix is mechanical.
    """
    field = fm.get("aliases")
    if field is None:
        return
    # The same alias twice on ONE entry is its own fault, not a cross-entry
    # collision (scan_vault reports it the same way, as a within-entry item18).
    # Counted raw, exactly as scan_vault counts it.
    values = [v for v in field.values if v]
    for dup in sorted({v for v in values if values.count(v) > 1}):
        findings.append(_f(
            "18-alias-duplicate", "error",
            "alias %r listed %d times within this entry -- keep one"
            % (dup, values.count(dup)),
            {"alias": dup, "count": values.count(dup)}))
    # Case/normalization-variant duplicates within the entry: by the fold_name
    # doctrine both tools apply cross-entry, "TPR" beside "tpr" is ONE name to
    # Obsidian listed twice -- the raw count above sees two strings, and the
    # cross-entry maps skip same-entry pairs, so the pair was reported by
    # nobody.  scan_vault reports the same finding; the two tools must agree.
    _fold_first = {}
    for v in values:
        _k = fold_name(v)
        if not _k:
            continue
        if _k in _fold_first and _fold_first[_k] != v:
            findings.append(_f(
                "18-alias-duplicate", "error",
                "aliases %r and %r differ only in case/normalization -- one "
                "name to Obsidian; keep one" % (_fold_first[_k], v),
                {"alias": v, "other": _fold_first[_k]}))
        _fold_first.setdefault(_k, v)
    for value, line in zip(field.values, field.item_lines):
        if not value:
            continue
        try:
            expected = slug_stem(value)
        except SlugError:
            findings.append(_f("18-alias-form", "warning",
                               "alias %r cannot be slugged at all" % value,
                               {"line": line, "alias": value}))
            continue
        if value != expected:
            findings.append(_f(
                "18-alias-form", "warning",
                "alias %r is not in slug form (expected %r) -- aliases follow the "
                "same slug rule as the filename, and the collision probes read "
                "them as slugs" % (value, expected),
                {"line": line, "alias": value, "expected": expected}))


# --------------------------------------------------------------------------
# item 17's introduced-alias scan, and item 9's sentence-length flag
# --------------------------------------------------------------------------

#: A synonym-introduction cue in body prose.  Per the emphasis rules
#: (flashcards-and-emphasis.md §5, Italic Pattern 8) the alternate name that
#: follows one of these is italicized, which is what keeps this scan quiet:
#: only an italic span inside the trailing window is a candidate.
_SYN_CUE_RE = re.compile(
    r"\b(?:also\s+(?:called|known\s+as|termed|named)|known\s+as|short\s+for|"
    r"informally\s+called|sometimes\s+called|or\s+simply|"
    # the shapes the first cut missed on a real vault: "which many people
    # call *X*" fired nothing, so the italicized synonym was never scanned
    r"referred\s+to\s+as|a\.k\.a\.?|"
    r"(?:often|commonly|usually)\s+called|"
    r"(?:many\s+)?people\s+call|some\s+call)\b", re.IGNORECASE)

#: An *italic* span -- single asterisks, not a ``**bold**`` pair.
_ITALIC_SPAN_RE = re.compile(r"(?<!\*)\*([^*\n]{2,60})\*(?!\*)")

#: The opener's acronym/expansion binding: ``**Bolded title** (counterpart)``
#: (prose principle 5(e)/(f)).  Scanned in the opening block only, so a
#: definition bullet's ``- **True positives** (TP)`` never reaches it.
_BOLD_PAREN_RE = re.compile(r"\*\*[^*\n]+\*\*\s*\(([A-Za-z][^()\n]{0,59})\)")

#: Parenthetical content that is annotation-but-not-a-name: dates, floruit
#: markers, cross-references.  Any of these disqualifies the candidate.
_NON_NAME_PAREN_RE = re.compile(
    r"^(?:b\.|c\.|d\.|fl\.|r\.|e\.g|i\.e|cf\.|vs\.|see\s|a\s|an\s|the\s|"
    r"annual|ongoing)|\d{3,4}", re.IGNORECASE)

#: A lexical marker LEADING the parenthetical name -- ``(singular,
#: *archaeon*)``, ``(formerly Facebook)``.  Annotation, not part of the name:
#: left in place, the candidate came out polluted ("singular, *archaeon*",
#: expected alias "singular-archaeon").
_PAREN_LEADIN_RE = re.compile(
    r"^(?:singular|plural|abbreviated|formerly|n[ée]e|or)[\s,:]+",
    re.IGNORECASE)


def _clean_paren_name(raw):
    """The name inside an opener parenthetical, markers stripped.

    ``(singular, *archaeon*)`` names *archaeon*: the lead-in word and the
    italic/bold markers are annotation around the name, not part of it.
    """
    s = " ".join((raw or "").split())
    s = _PAREN_LEADIN_RE.sub("", s)
    return s.replace("*", "").replace("_", "").strip()


def _opening_block(sections):
    """The first contiguous run of non-empty prose lines (the opener)."""
    block = []
    for line in sections["prose_lines"]:
        if line.strip():
            block.append(line.strip())
        elif block:
            break
    return " ".join(block)


def _alias_candidates(sections):
    """Names the body introduces for the entry's subject: ``(name, where)``."""
    prose = "\n".join(sections["prose_lines"])
    seen, out = set(), []

    def add(cand, where):
        cand = " ".join(cand.split()).strip(" ,;:.")
        if not cand or _NON_NAME_PAREN_RE.match(cand):
            return
        key = cand.lower()
        if key not in seen:
            seen.add(key)
            out.append((cand, where))

    for m in _BOLD_PAREN_RE.finditer(_opening_block(sections)):
        add(_clean_paren_name(m.group(1)), "opener parenthetical")
    for m in _SYN_CUE_RE.finditer(prose):
        window = prose[m.end():m.end() + 160].split("\n\n", 1)[0]
        for span in _ITALIC_SPAN_RE.finditer(window):
            add(span.group(1), "italicized synonym")
    return out


def _check_alias_completeness(fm, sections, findings, filename):
    """Item 17's completeness half: body-introduced names must be aliases.

    Warning, never error: the same-entity test ("*dummy attributes* names the
    produced attributes, not the encoding") and the cross-domain bare-term
    carve-out are judgment, so the finding hands the model a candidate, not a
    verdict.  The two mechanical exclusions ARE applied: a form that slugs
    identically to the filename, and one already in ``aliases:``.
    """
    stem = os.path.splitext(os.path.basename(filename))[0]
    have = {stem}
    for alias in fm.values("aliases"):
        if not alias:
            continue
        have.add(alias)
        try:
            have.add(slug_stem(alias))
        except SlugError:
            pass
    for cand, where in _alias_candidates(sections):
        try:
            cslug = slug_stem(cand)
        except SlugError:
            continue
        if cslug in have:
            continue
        findings.append(_f(
            "17-alias-completeness", "warning",
            "the body introduces %r (%s) as a name for the subject, but "
            "aliases: does not carry %r -- add it if it names this same "
            "entity; a cross-domain bare term or a wrong-entity name stays "
            "out (checklist item 17)" % (cand, where, cslug),
            {"candidate": cand, "where": where, "expected_alias": cslug}))


def _sentence_scan_text(sections):
    """Body prose ready for the sentence scan.

    Whole-line captions, table rows, image embeds and display math are not
    sentences and are dropped; wikilinks collapse to their display text and
    inline math to one token, so neither inflates a word count.
    """
    kept = []
    for raw in sections["prose_lines"]:
        s = raw.strip()
        if not s:
            kept.append("")
            continue
        if s.startswith("|"):
            continue
        if re.match(r"^!\[\[[^\]]+\]\]\s*$", s) or re.match(r"^!\[[^\]]*\]\([^)]*\)\s*$", s):
            continue
        if s.startswith("*") and s.endswith("*") and not s.startswith("**"):
            continue                                   # caption line
        kept.append(raw)
    text = "\n".join(kept)
    # A DISPLAY block ends the sentence around it: "... is defined as: $$...$$
    # where ..." merged into one phantom 35+-word "sentence" because a colon is
    # not a boundary, and the real parts on either side are each under the cap.
    # The placeholder's own period gives the splitter the boundary the block
    # visually is.  Inline math stays a plain token -- it sits INSIDE a sentence.
    text = re.sub(r"\$\$.*?\$\$", " EQN. ", text, flags=re.S)
    text = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\$[^$\n]*\$", " EQN ", text)
    return text


def _iter_sentences(text):
    """Yield sentences, using the same boundary rules as count_sentences."""
    s = " ".join(text.split())
    start = 0
    for m in re.finditer(r"[.!?]+", s):
        nxt = s[m.end():m.end() + 1]
        if nxt and not nxt.isspace():
            continue
        if m.group(0) == ".":
            # Tail slice for the same two reasons count_sentences gives.
            head = s[max(0, m.end() - 16):m.end()]
            if _INITIAL_RE.search(head) or _ABBREV_RE.search(head):
                continue
        chunk = s[start:m.end()].strip()
        if chunk:
            yield chunk
        start = m.end()
    tail = s[start:].strip()
    if tail:
        yield tail


def _check_sentence_length(sections, findings, is_stub):
    """Item 9's sentence-length flag.  Legacy stubs are exempt (length clause)."""
    if is_stub:
        return
    for sent in _iter_sentences(_sentence_scan_text(sections)):
        words = len(sent.split())
        if words >= SENTENCE_MAX_WORDS:
            findings.append(_f(
                "9-sentence-length", "warning",
                "a %d-word sentence -- item 9 splits any sentence of %d+ "
                "words into one idea per sentence" % (words, SENTENCE_MAX_WORDS),
                {"words": words, "sentence": sent[:200]}))


# NOTE: there is deliberately no _check_importance either.  The field was
# removed from the schema; new entries omit the key entirely, and the legacy
# entries that still carry it are left alone -- nothing strips it and nothing
# flags it, at any severity.  So there is no presence check (it is out of
# MANDATORY_KEYS), no quoting check (out of NEVER_QUOTED), no enum check, and
# no stub-must-be-blank check.  The key is still listed in
# vault_index.SCHEMA_ORDER, which is what keeps _check_field_order from
# reporting a legacy `importance:` as an unknown or misplaced key.


# NOTE: there is deliberately no _check_parents.  A populated `parents:` is the
# expected steady state -- wiki-linter's Task 3 writes that field on every full
# entry -- so flagging it fired on the whole vault after a single lint pass.  It
# was redundant anyway: `parents` is in QUOTED_LIST_FIELDS, so _check_quoting
# already reports an unquoted item, and it is in MANDATORY_KEYS, so
# _check_field_order already reports a missing key.


# --------------------------------------------------------------------------
# listing maskers -- BYTE-IDENTICAL copies of scan_vault.py's strip_fenced /
# strip_indented / strip_code and their regexes.  The duplicate-wikilink
# check must read the same LISTING-MASKED text the scanner's item10/dup
# reads: a `[[target]]` shown in a fence, an inline code span or an
# indented block is a sample, and counting it made a real single link
# report as a duplicate whose remedy edits the listing or drops the link.
# Keep these in lockstep with scan_vault.py (the two tools must agree).
# --------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")


def strip_fenced(text):
    """Blank every line inside a ``` / ~~~ fenced code block, line count kept.

    A fenced block is a LISTING: its contents are shown, not asserted, so a
    scan that reads them as frontmatter or as prose reports the sample rather
    than the entry.  Line count is preserved so any offset computed against the
    original still lines up.

    CommonMark 4.5: a fence closes only on a run of the SAME character at
    least as long as the opener, so a ``` sample shown inside a ```` block is
    content, not a close.  A blind toggle inverted the masking there, and the
    `[[link]]` inside the outer listing came back item10/dangling — whose
    Task-2 remedy edits the listing.
    """
    out, fence = [], None            # fence = the opening run, e.g. "````"
    for ln in (text or "").split("\n"):
        m = _FENCE_RE.match(ln)
        if m and fence is None:
            fence = m.group(1)
            out.append("")
            continue
        if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
            fence = None
            out.append("")
            continue
        out.append("" if fence is not None else ln)
    return "\n".join(out)


#: An inline code span: a run of N backticks, content, and a closing run of the
#: SAME length.  Not `` `[^`]*` ``, which reads ``` ``[[x]]`` ``` as two empty
#: spans around a bare `[[x]]` and leaves the link visible to whatever is
#: reading — an item-10 dangler whose remedy creates a file for a sample of
#: link syntax.  Line-bounded on purpose: a code span may legally span a line
#: break, but honouring that lets one stray backtick swallow the rest of an
#: entry and HIDE real links, which is the costlier direction to be wrong in.
_INLINE_CODE = re.compile(r"(`+)[^\n]*?\1(?!`)")

#: An indented code block's line: four spaces, or a tab (CommonMark 4.4).
_INDENT_CODE = re.compile(r"^(?: {4}|\t)")
#: A list-item opener, at CommonMark's ≤3 spaces of leading indent.  A list
#: item's continuation content is indented for exactly the reason code is,
#: which is the one case that must NOT be read as code.
_LIST_ITEM = re.compile(r"^ {0,3}(?:[-*+]|\d{1,9}[.)])(?:\s|$)")


def strip_indented(text):
    """Blank every line of an INDENTED (4-space / tab) code block.

    The third listing spelling, after ``` and ~~~.  Obsidian renders it as
    code like the other two, so a `[[target]]` inside one links nothing and
    reporting it as dangling prescribes creating a file for something only
    ever shown.

    CommonMark's rule, applied conservatively.  An indented code block may
    only start where a new block can start — after a blank line — so it never
    interrupts a paragraph.  The look-alike that is *not* code is a **list
    item's continuation content**, indented for exactly that reason, so a run
    whose nearest preceding non-blank line is a list item, or is itself
    indented (i.e. already inside one), is left alone.  Erring that way is
    deliberate and one-directional: masking a list continuation would HIDE a
    real dangling link, while declining to mask one only leaves the behaviour
    that was there before.  Line count is preserved, as `strip_fenced` does.
    """
    lines = (text or "").split("\n")
    out = list(lines)
    prev_nonblank = None
    i, n = 0, len(lines)
    while i < n:
        ln = lines[i]
        if not ln.strip():
            i += 1
            continue
        starts_block = (i == 0) or (not lines[i - 1].strip())
        in_list = prev_nonblank is not None and (
            _LIST_ITEM.match(prev_nonblank) or prev_nonblank[:1].isspace())
        if _INDENT_CODE.match(ln) and starts_block and not in_list:
            # Consume the block: indented lines, and the blank lines between
            # them, up to the last indented line.
            j, last = i, i
            while j < n:
                if not lines[j].strip():
                    j += 1
                    continue
                if not _INDENT_CODE.match(lines[j]):
                    break
                last = j
                j += 1
            for k in range(i, last + 1):
                out[k] = ""
            prev_nonblank = lines[last]
            i = last + 1
            continue
        prev_nonblank = ln
        i += 1
    return "\n".join(out)


def strip_code(text):
    """Every LISTING blanked: fenced, indented, and inline code spans.

    What is left is what this entry ASSERTS, with everything it merely SHOWS
    removed.  A scan that has to distinguish the two — item 10 is the one that
    matters, because its remediation CREATES the file it names — must read
    this and not the raw prose: a `[[target-note]]` printed in a listing or
    quoted in a code span is a sample of link syntax, not a link, and Obsidian
    renders it as literal text.  `build_backfill` already reads the
    fenced-stripped form, and for the same reason.

    All three markdown spellings of a listing are covered, because a check
    that knows only one of them is not a rule about listings — it is a rule
    about backticks, and the entry that used the other spelling gets the
    destructive finding.
    """
    return _INLINE_CODE.sub(lambda m: " " * len(m.group(0)),
                            strip_indented(strip_fenced(text)))


def _check_duplicate_wikilinks(sections, findings):
    # Extraction runs on the LISTING-MASKED prose (fenced blocks, inline code
    # spans, indented code), exactly as scan_vault's item10/dup reads
    # strip_code(prose): a target SHOWN in a listing and linked once in prose
    # is linked ONCE, and "keep first only" applied to that pair edits the
    # listing or drops the real link.  Evidence text still quotes the raw line.
    prose_lines = sections["prose_lines"]
    masked_lines = strip_code("\n".join(prose_lines)).split("\n")
    seen = {}
    for offset, line in enumerate(masked_lines):
        for target, label in extract_wikilinks(line):
            seen.setdefault(target, []).append(
                {"body_line": offset + 1, "display": label,
                 "text": prose_lines[offset].strip()})
    for target, hits in seen.items():
        if len(hits) > 1:
            findings.append(_f(
                "10-duplicate-wikilink", "error",
                "slug %r is wikilinked %d times in body prose -- keep the first "
                "and unlink the rest to bare text (counted by target slug, not "
                "display text; the Related footer is exempt)" % (target, len(hits)),
                {"target": target, "count": len(hits), "occurrences": hits}))


def _check_bold_opener(fm, sections, findings):
    title = fm.scalar("title")
    if not title:
        return
    # The opener is the first PARAGRAPH, not the first line: reading one line
    # made a hard-wrapped opening sentence whose bold lands on line 2 report
    # "the opening sentence has no bolded span".  (wiki-linter's scanner has
    # always compared against `prose.split("\n\n", 1)[0]`.)
    block = []
    for line in sections["prose_lines"]:
        if line.strip():
            block.append(line.strip())
        elif block:
            break
    opening = " ".join(block)
    if not opening:
        findings.append(_f("16-bold-opener", "error", "entry has no body prose"))
        return

    # The FIRST bolded span is the one item 16 owns.  `_BOLD3_RE or _BOLD2_RE`
    # preferred a ***bold-italic*** anywhere in the opener over an earlier
    # plain **bold**, so an opener whose first bold was wrong passed whenever
    # a bold-italic span appeared later (scan_vault flags the same opener).
    # On a tie (both start at the same offset, i.e. the span IS ***…***) the
    # bold-italic pattern wins so the inner text is captured without stars.
    m3, m2 = _BOLD3_RE.search(opening), _BOLD2_RE.search(opening)
    if m3 and m2:
        m = m3 if m3.start() <= m2.start() else m2
    else:
        m = m3 or m2
    if not m:
        findings.append(_f(
            "16-bold-opener", "error",
            "the opening sentence has no bolded span; it must open by bolding "
            "the entry title", {"opening": opening[:200]}))
        return

    bolded = m.group(1).strip()
    accepted = [title]
    if has_parenthetical(title):
        accepted.append(base_term(title))

    if any(first_letter_ci_equal(bolded, cand) for cand in accepted):
        return
    # symbol/variable carve-out: compare math-stripped skeletons
    skeleton = math_skeleton(bolded)
    if any(first_letter_ci_equal(skeleton, math_skeleton(cand))
           for cand in accepted):
        return

    findings.append(_f(
        "16-bold-opener", "error",
        "first bolded span %r does not equal title: %r "
        "(compared case-insensitively on the first letter only; base-term and "
        "math-skeleton carve-outs applied)" % (bolded, title),
        {"bolded": bolded, "title": title, "accepted": accepted,
         "bolded_skeleton": skeleton, "opening": opening[:200]}))


def _check_flashcards_present(fm, sections, findings, is_stub):
    """Item 19's PRESENCE half: every full entry carries `## Flashcards`.

    The leak scan below is item 19's other half and it only runs when a
    Flashcards section exists -- so an entry with no section at all passed the
    whole of item 19 silently, which is the one failure mode item 19 has that a
    reader cannot see by looking at the entry (nothing is wrong; something is
    missing).  SKILL.md's script table claims item 19; the three clauses
    checked here are exactly its mechanical ones -- present, preceded by a
    `---` separator of its own, at least one card.  The stub direction (a stub
    must NOT have one) is `stub-no-flashcards`.
    """
    if is_stub:
        return
    if sections["flashcards_index"] is None:
        findings.append(_f(
            "19-flashcards", "error",
            "full entry has no `## Flashcards` section -- item 19 requires one "
            "on every full entry, after the Related footer, preceded by a "
            "`---` separator line, holding at least one card"))
        return
    # A tolerated heading spelling (### level, extra/leading spaces) is a
    # PRESENT section with a heading to fix -- never a missing section, whose
    # remedy would add a second one beside the section Obsidian already
    # renders.  scan_vault reports the same finding; the two tools must agree.
    _head = (sections.get("flashcards_head") or "").rstrip("\r")
    if _head and not re.match(r"^## Flashcards[ \t]*$", _head):
        findings.append(_f(
            "19-flashcards", "error",
            "the Flashcards heading is spelled %r -- the canonical heading is "
            "exactly `## Flashcards`; fix the heading in place, do NOT add a "
            "second section" % _head.strip()[:30],
            {"line": fm.body_start_line + sections["flashcards_index"]}))
    if sections["separator_index"] is None:
        findings.append(_f(
            "19-flashcards", "error",
            "`## Flashcards` is not preceded by a `---` separator line of its "
            "own (Body Structure -> Flashcards)",
            {"line": fm.body_start_line + sections["flashcards_index"]}))
    cards = parse_flashcards(sections["flashcard_lines"])
    if not cards:
        findings.append(_f(
            "19-flashcards", "error",
            "the `## Flashcards` section holds no card -- item 19 requires "
            "exactly one"))
    elif len(cards) > 1:
        findings.append(_f(
            "19-flashcards", "error",
            "the `## Flashcards` section holds %d cards -- item 19 allows "
            "exactly one; a second term that warrants a card is a split into "
            "its own entry, not a second card" % len(cards),
            {"cards": len(cards)}))

    # Item 19's other two mechanical clauses (scan_vault checks both; the two
    # tools must agree).  Line 2 is exactly `??` -- or the user's `!!`, which
    # marks a card they disabled and is preserved, never converted.  Line 3 is
    # the canonical title: the base term for a parenthetical-disambiguated
    # title, the math-stripped skeleton for a symbol title (line 3 is plain
    # text, so `$k$-fold` can only ever appear there as `k-fold`), with an
    # optional trailing acronym-counterpart parenthetical -- compared with the
    # parenthetical stripped and case-insensitively, as scan_vault does.
    title = fm.scalar("title")
    accepted = set()
    for cand in ([title, base_term(title)] if title else []):
        if cand:
            accepted.add(cand.strip().lower())
            accepted.add(math_skeleton(cand).strip().lower())
    for card_no, card in enumerate(cards, 1):
        if len(card) < 3:
            # A 1- or 2-line block is not a card at all (canon: definition /
            # `??` / term, contiguous).  The length-gated checks below both
            # skipped it silently, so the one card broken enough to be missing
            # a line was the one card item 19 never flagged -- scan_vault
            # reports the same input as malformed; the two tools must agree.
            findings.append(_f(
                "19-flashcards", "error",
                "flashcard %d is malformed -- a card is 3 contiguous lines "
                "(definition / `??` / term), found %d (a blank line between "
                "lines 1-3 breaks the card)" % (card_no, len(card)),
                {"card": card_no, "lines": len(card)}))
            continue
        if len(card) >= 2:
            line2 = card[1].strip()
            if line2 not in ("??", "!!"):
                findings.append(_f(
                    "19-flashcards", "error",
                    "flashcard %d line 2 is %r -- it must be exactly `??` (or "
                    "the user's `!!`, preserved verbatim, never converted)"
                    % (card_no, line2[:20]),
                    {"card": card_no, "line2": line2[:40]}))
        if len(card) >= 3 and accepted:
            line3 = card[2].strip()
            m3 = re.match(r"^(?P<term>.*?)\s*(?:\([^()\n]*\))?\s*$", line3)
            term = (m3.group("term") if m3 else line3).strip()
            if term.lower() not in accepted:
                findings.append(_f(
                    "19-flashcards", "error",
                    "flashcard %d line 3 is %r -- it must be the canonical "
                    "title %r (base term for a parenthetical-disambiguated "
                    "title; an acronym counterpart may follow in parentheses)"
                    % (card_no, line3[:40], title),
                    {"card": card_no, "line3": line3[:60], "title": title}))


def _check_flashcard_leak(fm, sections, findings, is_stub):
    if is_stub or sections["flashcards_index"] is None:
        return
    title = fm.scalar("title")
    if not title:
        return
    needle_title = base_term(title) if has_parenthetical(title) else title
    # Both spellings of every surface: an alias is slug-form but a leak can be
    # written either way ("lloyd-algorithm" or "lloyd algorithm"), and a
    # hyphenated title leaks the same two ways.  scan_vault's alias_forms
    # checks both; the two tools must agree.  Deduped so a hyphen-free
    # surface is not tested (and reported) twice.
    needles, seen_forms = [], set()
    for kind, surface in [("title", needle_title)] + [
            ("alias", a) for a in fm.values("aliases") if a]:
        for form in (surface, surface.replace("-", " ")):
            if form and form.lower() not in seen_forms:
                seen_forms.add(form.lower())
                needles.append((kind, form))

    for card_no, card in enumerate(parse_flashcards(sections["flashcard_lines"]), 1):
        line1 = card[0]
        low = line1.lower()
        for kind, needle in needles:
            if not needle:
                continue
            # A bare substring test made every short title a guaranteed false
            # positive: for the entry titled "C", the "c" inside "create" fired.
            # And the severity discriminator used a LEFT-only boundary, so that
            # word-INITIAL substring was then escalated from warning to error.
            n = needle.lower()
            bounded = re.search(r"(?<![A-Za-z0-9])" + re.escape(n) + r"(?![A-Za-z0-9])",
                                low) is not None
            if len(n) <= 4:
                if not bounded:
                    continue          # short needle: whole-word match only
            elif n not in low:
                continue
            at_boundary = bounded
            findings.append(_f(
                "19-flashcard-leak",
                "error" if at_boundary else "warning",
                "flashcard %d line 1 leaks the %s %r (case-insensitive "
                "substring, math regions included)%s"
                % (card_no, kind, needle,
                   "" if at_boundary else " -- match is mid-word, likely incidental"),
                {"card": card_no, "needle": needle, "kind": kind,
                 "line1": line1}))


def _check_stub_structure(fm, sections, findings, is_stub):
    if not is_stub:
        return
    body_text = "\n".join(sections["lines"])
    prose = "\n".join(sections["prose_lines"]).strip()

    paragraphs = [p for p in re.split(r"\n\s*\n", prose) if p.strip()]
    if len(paragraphs) > 1:
        findings.append(_f(
            "stub-one-sentence-body", "error",
            "a stub body is one sentence; found %d paragraphs" % len(paragraphs),
            {"paragraphs": len(paragraphs)}))
    elif paragraphs:
        n = count_sentences(paragraphs[0])
        if n > 1:
            findings.append(_f(
                "stub-one-sentence-body", "warning",
                "a stub body is one sentence; found roughly %d" % n,
                {"body": paragraphs[0][:300]}))
    else:
        findings.append(_f("stub-one-sentence-body", "error",
                           "stub has no body sentence"))

    if sections["related_index"] is not None:
        findings.append(_f("stub-no-related", "error",
                           "stubs carry no **Related:** footer",
                           {"line": sections["related_line"]}))
    if "![[" in body_text:
        findings.append(_f("stub-no-images", "error",
                           "stubs never carry images",
                           {"embeds": re.findall(r"\!\[\[[^\]]+\]\]", body_text)}))
    if sections["flashcards_index"] is not None:
        findings.append(_f("stub-no-flashcards", "error",
                           "stubs have no ## Flashcards section"))


def _check_stub_sources(fm, findings):
    """Report a sources: list that mixes the stub marker with real wikilinks."""
    field = fm.get("sources")
    if field is None:
        # A missing key is already _check_field_order's MANDATORY_KEYS
        # finding; reporting it here too made one fault two findings.
        return False
    values = [v for v in field.values if v not in (None, "")]
    if not values:
        findings.append(_f("2-field-order", "error", "sources: is empty; it must "
                                                     "hold at least one item"))
        return False
    if "stub" in values and len(values) > 1:
        findings.append(_f(
            "stub-sources-marker", "error",
            'the literal "stub" marker must be the SOLE sources: item -- on '
            "promotion it is replaced by the real source, never appended",
            {"sources": values}))
    return values == ["stub"]


def _check_source_duplicates(fm, findings):
    """Item 4: no two ``sources:`` items may name the same document.

    ``paper-summarizer`` writes a note into ``Articles/`` for every PDF it
    summarises, named after that PDF's stem, so one document sits in the vault
    under two names -- ``Sources/PDFs/X.pdf`` and ``Articles/X.md`` -- and
    both are legal ``sources:`` values.  An entry carrying both records ONE document as
    two sources: it inflates the entry's apparent provenance, and the ``.md``
    half carries no ``#page=N``, so it also reads as a source with no
    locatable position.  Keep the PDF -- it is the one that can carry the
    anchor -- and drop the ``.md``.

    Only a stem collision ACROSS the two extensions is a finding.  An entry
    may legitimately cite several distinct PDFs and several distinct markdown
    clippings, and a web clipping has no PDF twin at all, so a ``.md`` source
    is only suspect when a ``.pdf`` source of the same stem sits beside it.
    """
    field = fm.get("sources")
    if field is None:
        return
    pdfs, mds = {}, []
    for value, line in zip(field.values, field.item_lines):
        stem, ext = source_stem(value)
        if not stem:
            continue
        if ext == "pdf":
            pdfs.setdefault(stem, (value, line))   # keep the first spelling
        elif ext == "md":
            mds.append((stem, value, line))
    for stem, md_value, md_line in mds:
        if stem not in pdfs:
            continue
        pdf_value, pdf_line = pdfs[stem]
        findings.append(_f(
            "4-duplicate-source", "error",
            "%s and %s name the same document -- the PDF and the "
            "note written about it -- so one source is "
            "recorded twice; delete the .md item and keep the .pdf one, which "
            "is the only one of the two that can carry a #page=N anchor"
            % (md_value, pdf_value),
            {"stem": stem, "delete": md_value, "delete_line": md_line,
             "keep": pdf_value, "keep_line": pdf_line}))


# --------------------------------------------------------------------------
# drivers
# --------------------------------------------------------------------------

def lint_text(text, filename):
    """Lint one entry given its text.  Returns the per-file result dict."""
    findings = []
    result = {"file": os.path.abspath(filename), "findings": findings,
              "is_stub": False, "title": None, "aliases": [],
              "description_chars": None}

    fm = parse_frontmatter(text)
    if not _check_structure(fm, findings):
        return result

    result["title"] = fm.scalar("title")
    result["aliases"] = [a for a in fm.values("aliases") if a]
    desc = fm.scalar("description")
    result["description_chars"] = len(desc) if desc else 0

    is_stub = _check_stub_sources(fm, findings)
    result["is_stub"] = is_stub
    sections = split_sections(fm.body)

    _check_field_order(fm, findings)
    _check_type(fm, findings)
    _check_quoting(fm, findings)
    _check_dates(fm, findings)
    _check_source_duplicates(fm, findings)
    _check_slug(fm, findings, filename)
    _check_description(fm, findings, title=result["title"])
    _check_tags(fm, findings, is_stub)
    _check_aliases(fm, findings)
    _check_alias_completeness(fm, sections, findings, filename)
    _check_sentence_length(sections, findings, is_stub)
    _check_duplicate_wikilinks(sections, findings)
    _check_bold_opener(fm, sections, findings)
    _check_flashcards_present(fm, sections, findings, is_stub)
    _check_flashcard_leak(fm, sections, findings, is_stub)
    _check_stub_structure(fm, sections, findings, is_stub)
    return result


def lint_file(path):
    """Lint one file on disk.  Never raises."""
    abspath = os.path.abspath(path)
    preamble = []
    try:
        # utf-8-sig, not utf-8: a BOM left lines[0] as "﻿---", so
        # parse_frontmatter reported "no YAML frontmatter", _check_structure
        # returned False, and all 13 remaining checks silently skipped -- the
        # entry came back reported as otherwise clean.
        with open(abspath, "r", encoding="utf-8-sig") as fh:
            text = fh.read()
    except UnicodeDecodeError as exc:
        preamble.append(_f("0-encoding", "error",
                           "file is not valid UTF-8 (%s); linted with "
                           "replacement characters" % exc))
        try:
            with open(abspath, "r", encoding="utf-8-sig", errors="replace") as fh:
                text = fh.read()
        except Exception as exc2:
            return {"file": abspath, "is_stub": False, "title": None,
                    "aliases": [], "description_chars": None,
                    "findings": preamble + [_f("0-unreadable", "error",
                                               "could not read file: %s: %s"
                                               % (type(exc2).__name__, exc2))]}
    except Exception as exc:
        return {"file": abspath, "is_stub": False, "title": None, "aliases": [],
                "description_chars": None,
                "findings": [_f("0-unreadable", "error",
                                "could not read file: %s: %s"
                                % (type(exc).__name__, exc))]}
    try:
        result = lint_text(text, abspath)
        result["findings"] = preamble + result["findings"]
        return result
    except Exception as exc:  # a malformed entry is a finding, never a crash
        return {"file": abspath, "is_stub": False, "title": None, "aliases": [],
                "description_chars": None,
                "findings": [_f("0-lint-error", "error",
                                "internal error while linting: %s: %s"
                                % (type(exc).__name__, exc))]}


def _check_alias_collisions(results):
    """Item 18, folder scope: no two entries share an ``aliases:`` string.

    Compared case- and normalization-folded (``vault_index.fold_name``):
    Obsidian resolves an alias exactly like a filename — case-insensitively —
    so ``Lambda-Rank`` on one entry and ``lambda-rank`` on another collide for
    every lookup a user actually performs, whatever the bytes say.
    """
    owners = {}                    # folded alias -> (display alias, [files])
    for res in results:
        for alias in res["aliases"]:
            entry = owners.setdefault(fold_name(alias), (alias, []))
            # One file, once: the same alias listed twice WITHIN one entry is
            # `18-alias-duplicate` (_check_aliases), not a collision with
            # itself -- un-deduped, a doubled alias reported the entry as
            # "claimed by 1 other entry", naming the same file twice.
            if res["file"] not in entry[1]:
                entry[1].append(res["file"])
    collisions = []
    for _folded, (alias, files) in sorted(owners.items()):
        if len(files) < 2:
            continue
        collisions.append({"alias": alias, "files": files})
        for res in results:
            if res["file"] in files:
                res["findings"].append(_f(
                    "18-alias-collision", "error",
                    "alias %r is also claimed by %d other entry/entries -- the "
                    "alias resolves to whichever entry a search hits first and "
                    "the other becomes silently unreachable" % (alias, len(files) - 1),
                    {"alias": alias,
                     "files": [os.path.basename(f) for f in files]}))
    return collisions


def lint_path(target, severity_floor=None):
    """Lint a single entry file or a whole folder (recursively)."""
    target = os.path.abspath(target)
    report = {"root": target, "entries": [], "alias_collisions": [],
              "summary": {}, "problems": []}

    if os.path.isdir(target):
        paths = iter_markdown_files(target)
        folder_mode = True
    elif os.path.isfile(target):
        paths = [target]
        folder_mode = False
    else:
        report["problems"].append("no such file or folder: %s" % target)
        report["summary"] = {"files": 0, "files_with_findings": 0,
                             "findings": 0, "by_severity": {}, "by_item": {}}
        return report

    results = [lint_file(p) for p in paths]
    if folder_mode:
        report["alias_collisions"] = _check_alias_collisions(results)

    order = {"error": 0, "warning": 1, "info": 2}
    floor = order.get(severity_floor, 2) if severity_floor else 2
    for res in results:
        res["findings"] = [f for f in res["findings"]
                           if order.get(f["severity"], 2) <= floor]
        res["findings"].sort(key=lambda f: (order.get(f["severity"], 3), f["item"]))

    by_severity, by_item = {}, {}
    total = 0
    for res in results:
        for finding in res["findings"]:
            total += 1
            by_severity[finding["severity"]] = by_severity.get(finding["severity"], 0) + 1
            by_item[finding["item"]] = by_item.get(finding["item"], 0) + 1

    report["entries"] = results
    report["summary"] = {
        "files": len(results),
        "stubs": sum(1 for r in results if r["is_stub"]),
        "files_with_findings": sum(1 for r in results if r["findings"]),
        "findings": total,
        "by_severity": dict(sorted(by_severity.items())),
        "by_item": dict(sorted(by_item.items())),
        "clean": total == 0,
    }
    return report


# --------------------------------------------------------------------------
# self-test
# --------------------------------------------------------------------------
#
# Table-driven, in the shape ``note_lint.py`` uses: one clean fixture, and one
# MUTATION of it per rule.  Each case states the EXACT set of finding items it
# expects, so a check that reports one fault as three fails here rather than in
# front of a user -- and so does a check that fires on the clean fixture, which
# is the failure mode that makes a linter get ignored.
#
#     python3 lint_entry.py --test

def _st_good():
    """A schema-clean entry that must produce NO finding at any severity."""
    return (
        '---\n'
        'title: "ROC curve"\n'
        'type: Concept\n'
        'aliases:\n'
        '  - "auroc"\n'
        'sources:\n'
        '  - "[[Doe_X_2025.pdf#page=2]]"\n'
        'created: 2026-01-01\n'
        'updated: 2026-01-02\n'
        'description: "A plot of true positive rate against false positive '
        'rate."\n'
        'tags:\n'
        '  - "#statistics"\n'
        'parents: []\n'
        'read: false\n'
        '---\n'
        'A **ROC curve** plots the trade-off between two error rates as a '
        'decision threshold moves.\n'
        '\n'
        '**Related:** [[precision|Precision]]\n'
        '\n'
        '---\n'
        '\n'
        '## Flashcards\n'
        '\n'
        'The plot tracing the trade-off between two error rates as a decision '
        'threshold moves.\n'
        '??\n'
        'ROC curve\n')


def _st_stub():
    """A schema-clean STUB, which is structurally a different entry."""
    return (
        '---\n'
        'title: "Precision"\n'
        'type: Concept\n'
        'sources:\n'
        '  - "stub"\n'
        'created: 2026-01-01\n'
        'updated: 2026-01-02\n'
        'description: "The share of predicted positives that are correct."\n'
        'tags:\n'
        '  - "#statistics"\n'
        'parents: []\n'
        'read: false\n'
        '---\n'
        '**Precision** is the share of predicted positives that are correct.\n')


def _st_items(result):
    return sorted({f["item"] for f in result["findings"]})


def run_self_test():
    import io
    import contextlib
    import shutil
    import tempfile
    cases = []

    def check(label, got, want):
        cases.append((label, got == want, got, want))

    good = _st_good()
    stub = _st_stub()

    def mutate(old, new, base=None):
        base = good if base is None else base
        assert old in base, "self-test fixture drift: %r" % old[:60]
        return base.replace(old, new, 1)

    def items(text, filename="roc-curve.md"):
        return _st_items(lint_text(text, filename))

    check("the clean fixture produces NO finding at any severity",
          items(good), [])
    check("the clean STUB produces no finding either",
          items(stub, "precision.md"), [])

    # -- item 1: valid YAML ------------------------------------------------
    check("no frontmatter at all", items("just prose\n"), ["1-valid-yaml"])
    check("an unterminated fence",
          items('---\ntitle: "ROC curve"\nnever closed\n'), ["1-valid-yaml"])
    check("a duplicate frontmatter key",
          items(mutate('type: Concept\n', 'type: Concept\ntype: Concept\n')),
          ["1-valid-yaml"])
    check("an indented key (a nested mapping is not in the schema)",
          items(mutate('type: Concept\n', 'type: Concept\n  nested: x\n')),
          ["1-valid-yaml"])

    # -- item 2: order, mandatory keys, unknown keys, type, quoting --------
    check("keys out of schema order",
          items(mutate('title: "ROC curve"\ntype: Concept\n',
                       'type: Concept\ntitle: "ROC curve"\n')),
          ["2-field-order"])
    check("a missing mandatory key",
          items(mutate("read: false\n", "")), ["2-field-order"])
    check("an off-schema key is a WARNING, not an error",
          [(f["item"], f["severity"])
           for f in lint_text(mutate("read: false\n", "mood: bright\nread: false\n"),
                              "roc-curve.md")["findings"]],
          [("2-field-order", "warning")])
    check("a legacy `importance:` in its historical slot is NOT a finding",
          items(mutate("parents: []\n", "importance: high\nparents: []\n")), [])
    check("a bare `parents:` (YAML null) is a 2-field-order error",
          items(mutate("parents: []\n", "parents:\n")), ["2-field-order"])
    # the LIST of items, not the deduped set: one fault must be ONE finding
    check("a missing sources: key is one finding, not two",
          [f["item"] for f in lint_text(
              mutate('sources:\n  - "[[Doe_X_2025.pdf#page=2]]"\n', ""),
              "roc-curve.md")["findings"]],
          ["2-field-order"])
    check("type: off the 15-value enum",
          items(mutate("type: Concept", "type: Widget")), ["2-type-enum"])
    # `type:` present-but-blank is a 2-type-enum finding only: the KEY is
    # there, so the mandatory-key check has nothing to say about it.
    check("type: blank", items(mutate("type: Concept", "type:")), ["2-type-enum"])
    check("title: not double-quoted",
          items(mutate('title: "ROC curve"', "title: ROC curve")), ["2-quoting"])
    check("type: quoted (it is a bare enum value)",
          items(mutate("type: Concept", 'type: "Concept"')), ["2-quoting"])
    check("read: quoted -- the string Obsidian renders as permanently checked",
          items(mutate("read: false", 'read: "false"')), ["2-quoting"])
    check("a single-quoted list item",
          items(mutate('  - "auroc"', "  - 'auroc'")), ["2-quoting"])
    check("an UNQUOTED #tag, which YAML reads as a comment",
          items(mutate('  - "#statistics"', "  - #statistics")),
          ["2-quoting", "8-tags"])

    # -- item 3: dates -----------------------------------------------------
    check("a malformed date", items(mutate("created: 2026-01-01", "created: 2026-1-1")),
          ["3-dates"])
    check("an impossible date", items(mutate("created: 2026-01-01", "created: 2026-02-30")),
          ["3-dates"])
    check("created after updated",
          items(mutate("created: 2026-01-01", "created: 2026-03-01")), ["3-dates"])

    # -- item 4: two sources naming one document ---------------------------
    check("a .md source beside the .pdf of the same stem",
          items(mutate('  - "[[Doe_X_2025.pdf#page=2]]"\n',
                       '  - "[[Doe_X_2025.pdf#page=2]]"\n  - "[[Doe_X_2025.md]]"\n')),
          ["4-duplicate-source"])
    check("...folded across case, NFC and folder qualification",
          items(mutate('  - "[[Doe_X_2025.pdf#page=2]]"\n',
                       '  - "[[Sources/PDFs/Doe_X_2025.pdf#page=2]]"\n'
                       '  - "[[Articles/doe_x_2025.md]]"\n')),
          ["4-duplicate-source"])
    check("two DISTINCT pdfs are not a duplicate",
          items(mutate('  - "[[Doe_X_2025.pdf#page=2]]"\n',
                       '  - "[[Doe_X_2025.pdf#page=2]]"\n  - "[[Roe_Y_2024.pdf#page=9]]"\n')),
          [])
    check("a clipping .md with no pdf twin is not a duplicate",
          items(mutate('  - "[[Doe_X_2025.pdf#page=2]]"\n',
                       '  - "[[Doe_X_2025.pdf#page=2]]"\n  - "[[Zed_Blog_2023.md]]"\n')),
          [])
    check("source_stem folds case/NFC and strips wrapper, pipe, anchor, folder",
          [source_stem(s) for s in ('"stub"', "[[Sources/PDFs/Doe_X_2025.pdf#page=2]]",
                                    "[[doe_x_2025.md|label]]")],
          [("", ""), ("doe_x_2025", "pdf"), ("doe_x_2025", "md")])

    # -- item 5: slug ------------------------------------------------------
    check("the filename does not match slug(title:)",
          items(good, "roc-curves.md"), ["5-slug"])
    check("a title that cannot be slugged at all",
          sorted(set(items(mutate('title: "ROC curve"', 'title: "機械学習"'),
                           "roc-curve.md"))),
          # 19-flashcards is real fallout: only the title was mutated, so card
          # line 3 ("ROC curve") genuinely no longer matches it
          ["16-bold-opener", "19-flashcards", "5-slug"])

    # -- item 7: description ----------------------------------------------
    check("a blank description",
          items(mutate('description: "A plot of true positive rate against '
                       'false positive rate."', 'description: ""')),
          ["7-description"])
    check("a description over the 110-character cap",
          items(mutate("false positive rate.", "false positive rate, written "
                       "out at rather more length than the hundred and ten "
                       "characters the rule allows.")),
          ["7-description"])
    check("markup in a description",
          items(mutate("A plot of true", "A plot of `true`")), ["7-description"])
    check("a description with no closing period is INFO, not an error",
          [(f["item"], f["severity"])
           for f in lint_text(mutate("false positive rate.", "false positive rate"),
                              "roc-curve.md")["findings"]],
          [("7-description", "info")])
    check("a lowercase-initial description is exempt when the TITLE is one",
          items(mutate('title: "ROC curve"\n', 'title: "k-nearest neighbors"\n')
                .replace("A **ROC curve** plots", "**k-nearest neighbors** plots")
                .replace('description: "A plot', 'description: "k-nearest neighbors is a plot')
                .replace("ROC curve\n", "k-nearest neighbors\n"),
                "k-nearest-neighbors.md"),
          [])

    # -- item 8: tags ------------------------------------------------------
    check("a tag with no # prefix",
          items(mutate('  - "#statistics"', '  - "statistics"')), ["8-tags"])
    check("a tag outside the 27-slug enum",
          items(mutate('  - "#statistics"', '  - "#astrology"')), ["8-tags"])
    check("a stub with blank tags: (the one field where a stub is stricter)",
          items(mutate('tags:\n  - "#statistics"\n', "tags:\n", base=stub),
                "precision.md"),
          ["8-tags"])

    # -- item 10: duplicate wikilinks --------------------------------------
    check("the same target linked twice in prose, under two labels",
          items(mutate("decision threshold moves.\n",
                       "decision threshold moves, per [[precision|precision]] "
                       "and [[precision|the positive predictive value]].\n")),
          ["10-duplicate-wikilink"])
    check("...counted by TARGET, so one link plus the Related footer is fine",
          items(mutate("decision threshold moves.\n",
                       "decision threshold moves, per [[precision|precision]].\n")),
          [])
    check("a ^block anchor is stripped, so the same target twice is still a dup",
          items(mutate("decision threshold moves.\n",
                       "decision threshold moves, per [[precision|p]] and "
                       "[[precision^init|q]].\n")),
          ["10-duplicate-wikilink"])

    # -- item 16: the bolded opener ----------------------------------------
    check("the opener bolds something other than the title",
          items(mutate("A **ROC curve** plots", "A **receiver curve** plots")),
          ["16-bold-opener"])
    check("an opener with no bold at all",
          items(mutate("A **ROC curve** plots", "A ROC curve plots")),
          ["16-bold-opener"])
    check("a hard-wrapped opener whose bold lands on line 2 is accepted",
          items(mutate("A **ROC curve** plots the trade-off",
                       "A\n**ROC curve** plots the trade-off")), [])
    check("the parenthetical base-term carve-out",
          items(mutate('title: "ROC curve"', 'title: "ROC curve (statistics)"')
                .replace("ROC curve\n??", "ROC curve\n??"),
                "roc-curve-statistics.md"), [])
    check("the math-skeleton carve-out",
          items(mutate('title: "ROC curve"', 'title: "$k$-fold"')
                .replace("A **ROC curve** plots", "A **k-fold** plots")
                .replace("ROC curve\n", "k-fold\n"), "k-fold.md"), [])

    # -- item 19: presence, then the answer leak ---------------------------
    check("a full entry with NO ## Flashcards section",
          items(mutate("\n---\n\n## Flashcards\n\nThe plot tracing the "
                       "trade-off between two error rates as a decision "
                       "threshold moves.\n??\nROC curve\n", "")),
          ["19-flashcards"])
    check("a ## Flashcards section with no card",
          items(mutate("The plot tracing the trade-off between two error rates "
                       "as a decision threshold moves.\n??\nROC curve\n", "")),
          ["19-flashcards"])
    check("a ## Flashcards section with a SECOND card",
          items(mutate("??\nROC curve\n",
                       "??\nROC curve\n\nAnother notion, stated briefly.\n??\nSecond idea\n")),
          ["19-flashcards"])
    check("a ## Flashcards heading with no --- separator above it",
          items(mutate("\n---\n\n## Flashcards", "\n## Flashcards")),
          ["19-flashcards"])
    check("card line 2 that is not exactly `??` (or `!!`)",
          items(mutate("??\nROC curve\n", "?\nROC curve\n")), ["19-flashcards"])
    check("a user-disabled `!!` card is preserved, not a line-2 finding",
          items(mutate("??\nROC curve\n", "!!\nROC curve\n")), [])
    check("card line 3 that is not the canonical title",
          items(mutate("??\nROC curve\n", "??\nThe ROC\n")), ["19-flashcards"])
    check("...but the title plus an acronym-counterpart parenthetical is fine",
          items(mutate("??\nROC curve\n", "??\nROC curve (RC)\n")), [])
    check("card line 1 leaking the title",
          items(mutate("The plot tracing the trade-off",
                       "The ROC curve traces the trade-off")),
          ["19-flashcard-leak"])
    check("card line 1 leaking an ALIAS, de-hyphenated",
          items(mutate('  - "auroc"', '  - "area-under-the-curve"')
                .replace("The plot tracing",
                         "The area under the curve, tracing")),
          ["19-flashcard-leak"])
    check("card line 1 leaking an alias in its HYPHENATED spelling",
          items(mutate('  - "auroc"', '  - "lloyd-algorithm"')
                .replace("The plot tracing",
                         "The lloyd-algorithm plot tracing")),
          ["19-flashcard-leak"])
    check("a leak inside $...$ is still a leak",
          items(mutate("The plot tracing", "The $\\text{ROC curve}$ tracing")),
          ["19-flashcard-leak"])
    check("a short title is not leaked by a mid-word substring",
          items(mutate('title: "ROC curve"', 'title: "C"')
                .replace("A **ROC curve** plots", "A **C** creates")
                .replace("ROC curve\n??", "C\n??").replace("\nROC curve\n", "\nC\n"),
                "c.md"), [])

    # -- stub structure ----------------------------------------------------
    check("a stub with a Related footer",
          items(mutate("correct.\n", "correct.\n\n**Related:** [[roc-curve|ROC curve]]\n",
                       base=stub), "precision.md"), ["stub-no-related"])
    check("a stub with an image (which is also a second block, hence both)",
          items(mutate("correct.\n", "correct.\n\n![[figure.png]]\n", base=stub),
                "precision.md"), ["stub-no-images", "stub-one-sentence-body"])
    check("a stub with a Flashcards section",
          items(mutate("correct.\n",
                       "correct.\n\n---\n\n## Flashcards\n\nDef.\n??\nPrecision\n",
                       base=stub), "precision.md"), ["stub-no-flashcards"])
    check("a stub body of two paragraphs",
          items(mutate("correct.\n", "correct.\n\nA second paragraph.\n", base=stub),
                "precision.md"), ["stub-one-sentence-body"])
    check("a Person stub's `(b. 1912)` initials do not read as three sentences",
          items(mutate('title: "Precision"', 'title: "A. M. Turing"', base=stub)
                .replace("type: Concept", "type: Person")
                .replace("**Precision** is the share of predicted positives "
                         "that are correct.",
                         "**A. M. Turing** (b. 1912, d. 1954) was a "
                         "mathematician, e.g. of computability.")
                .replace('description: "The share of predicted positives that '
                         'are correct."', 'description: "A mathematician."'),
                "a-m-turing.md"), [])
    check('the "stub" marker beside a real source',
          items(mutate('  - "stub"\n', '  - "stub"\n  - "[[Doe_X_2025.pdf#page=2]]"\n',
                       base=stub), "precision.md"),
          ["19-flashcards", "stub-sources-marker"])

    # -- item 9: the sentence-length flag ----------------------------------
    check("a 35+-word body sentence is flagged for splitting",
          items(mutate("A **ROC curve** plots the trade-off between two error "
                       "rates as a decision threshold moves.\n",
                       "A **ROC curve** plots the trade-off between two error "
                       "rates as a decision threshold moves across every "
                       "possible operating point, which analysts read as a "
                       "single summary picture of classifier behaviour over "
                       "all thresholds rather than one fixed choice of cutoff "
                       "for the model.\n")),
          ["9-sentence-length"])
    check("a legacy stub is exempt from the sentence-length flag",
          items(mutate("**Precision** is the share of predicted positives "
                       "that are correct.",
                       "**Precision** is the share of predicted positives "
                       "that are correct when a classifier's positive calls "
                       "are compared against the labels, a proportion "
                       "practitioners quote alongside recall to summarise "
                       "detection quality on imbalanced data over many "
                       "operating thresholds.", base=stub),
                "precision.md"),
          [])
    # A sentence-final POSSESSIVE is a boundary: the `'s.` tail read as an
    # initial and merged the two sentences, so two conforming sentences
    # re-flagged as one phantom 35+-word sentence on every run (four entries
    # on a real vault).
    check("a possessive before the period does not merge two sentences",
          items(mutate("A **ROC curve** plots the trade-off between two error "
                       "rates as a decision threshold moves.\n",
                       "A **ROC curve** plots the threshold trade-off that "
                       "analysts read from each classifier and its "
                       "predictor's. The same curve summarises ranking "
                       "quality over every operating point an evaluation "
                       "could pick for the model under test.\n")),
          [])
    check("...and a genuine initial still does not split (B. F. Skinner)",
          count_sentences("It was described by B. F. Skinner in 1948."), 1)
    # A DISPLAY math block ends the sentence around it: the colon-introduced
    # "$$...$$ where ..." shape merged into one phantom 35+-word "sentence".
    check("a display equation is a sentence boundary, not a merge point",
          items(mutate("A **ROC curve** plots the trade-off between two error "
                       "rates as a decision threshold moves.\n",
                       "A **ROC curve** plots one error-rate pair per "
                       "threshold, and analysts define the summary statistic "
                       "for the comparison as:\n\n$$A = \\int_0^1 f(x)\\,dx$$\n\n"
                       "where the integral runs over the false positive rate "
                       "and larger areas mean better ranking quality across "
                       "operating points.\n")),
          [])
    # Listings are SHOWN, not asserted: a link displayed in a fence, an inline
    # code span or an indented block beside one real prose link is ONE link
    # (scan_vault's item10/dup reads the same masked text; the remedy for a
    # false duplicate edits the listing or drops the real link).
    check("a wikilink shown in a fenced listing does not make a real link a "
          "duplicate",
          items(mutate("**Related:** [[precision|Precision]]",
                       "It links [[precision|Precision]] once in prose.\n\n"
                       "```\n[[precision]]\n```\n\n"
                       "**Related:** [[precision|Precision]]")),
          []),
    check("...same for an inline code span",
          items(mutate("**Related:** [[precision|Precision]]",
                       "It links [[precision|Precision]] once in prose, and "
                       "shows `[[precision]]` as syntax.\n\n"
                       "**Related:** [[precision|Precision]]")),
          [])
    # A 1- or 2-line card is malformed, not silently clean.
    check("a card missing its term line is a malformed-card error",
          items(mutate("threshold moves.\n??\nROC curve\n",
                       "threshold moves.\n??\n")),
          ["19-flashcards"])
    # A tolerated heading spelling is a PRESENT section plus a heading to fix.
    check("### Flashcards is present-but-noncanonical, never missing",
          (items(mutate("## Flashcards", "### Flashcards")),
           "canonical heading" in " ".join(
               f["message"] for f in lint_text(
                   mutate("## Flashcards", "### Flashcards"),
                   "roc-curve.md")["findings"])),
          (["19-flashcards"], True))
    # The FIRST bold is the opener bold: a later ***bold-italic*** must not
    # rescue a wrong first bold.
    check("a wrong first bold is flagged even when ***title*** appears later",
          items(mutate("A **ROC curve** plots",
                       "A **receiver plot**, formally the ***ROC curve***, "
                       "plots")),
          ["16-bold-opener"])
    # Case/normalization-variant aliases within one entry are one name twice.
    check("two alias spellings folding to one name are 18-alias-duplicate "
          "(the non-slug-form spelling is real fallout, reported too)",
          items(mutate('  - "auroc"', '  - "auroc"\n  - "AUROC"')),
          ["18-alias-duplicate", "18-alias-form"])
    # `aliases: [,]` holds no items: no phantom quoting findings.
    check("a degenerate flow list holds no phantom unquoted items",
          items(mutate('aliases:\n  - "auroc"\n', "aliases: [,]\n")),
          [])

    # -- item 17: the introduced-alias completeness scan --------------------
    check("an opener acronym parenthetical missing from aliases: is flagged",
          items(mutate("A **ROC curve** plots", "A **ROC curve** (RC) plots")),
          ["17-alias-completeness"])
    check("an italicized also-called synonym missing from aliases: is flagged",
          items(mutate("A **ROC curve** plots the trade-off",
                       "A **ROC curve**, also called the *operating "
                       "characteristic*, plots the trade-off")),
          ["17-alias-completeness"])
    check("...and is NOT flagged once the alias is present",
          items(mutate('  - "auroc"',
                       '  - "auroc"\n  - "operating-characteristic"')
                .replace("A **ROC curve** plots the trade-off",
                         "A **ROC curve**, also called the *operating "
                         "characteristic*, plots the trade-off")),
          [])
    check("a Person opener's date parenthetical is not an alias candidate",
          items(mutate('title: "Precision"', 'title: "A. M. Turing"', base=stub)
                .replace("type: Concept", "type: Person")
                .replace("**Precision** is the share of predicted positives "
                         "that are correct.",
                         "**A. M. Turing** (b. 1912, d. 1954) was a "
                         "mathematician, e.g. of computability.")
                .replace('description: "The share of predicted positives that '
                         'are correct."', 'description: "A mathematician."'),
                "a-m-turing.md"), [])
    check("the cue catches 'which many people call *X*'",
          [c for c, _w in _alias_candidates(split_sections(
              "**Min-max scaling** — which many people call *normalization* "
              "— rescales features to a fixed range."))],
          ["normalization"])
    check("an opener parenthetical's lead-in marker and italics are stripped",
          [c for c, _w in _alias_candidates(split_sections(
              "**Archaea** (singular, *archaeon*) are single-celled "
              "prokaryotes."))],
          ["archaeon"])

    # -- item 18: alias form, and alias collisions in FOLDER scope ----------
    check("an alias that is not itself in slug form is a WARNING",
          [(f["item"], f["severity"])
           for f in lint_text(mutate('  - "auroc"',
                                     '  - "receiver operating characteristic"'),
                              "roc-curve.md")["findings"]],
          [("18-alias-form", "warning")])

    tmp = tempfile.mkdtemp(prefix="lint_entry-selftest-")
    try:
        wiki = os.path.join(tmp, "Wiki")
        os.makedirs(os.path.join(wiki, "sub"))

        def put(rel, text, encoding="utf-8"):
            path = os.path.join(wiki, *rel.split("/"))
            mode, kw = (("wb", {}) if isinstance(text, bytes)
                        else ("w", {"encoding": encoding}))
            with open(path, mode, **kw) as fh:
                fh.write(text)
            return path

        put("roc-curve.md", good)
        put("precision.md", stub)
        # a second entry claiming the same alias, in a different CASE
        put("sub/sensitivity.md",
            good.replace('title: "ROC curve"', 'title: "Sensitivity"')
                .replace('  - "auroc"', '  - "AUROC"')
                .replace("A **ROC curve** plots", "**Sensitivity** plots")
                .replace("\nROC curve\n", "\nSensitivity\n"))
        # an entry listing the SAME alias twice: its own per-entry fault,
        # never a folder-scope collision with itself
        put("sub/dupalias.md",
            good.replace('title: "ROC curve"', 'title: "Dupalias"')
                .replace('  - "auroc"', '  - "dupme"\n  - "dupme"')
                .replace("A **ROC curve** plots", "**Dupalias** plots")
                .replace("\nROC curve\n", "\nDupalias\n"))
        report = lint_path(wiki)
        check("lint_path walks the folder recursively",
              report["summary"]["files"], 4)
        check("...and counts the stubs", report["summary"]["stubs"], 1)
        check("an alias claimed by two entries is a folder-scope collision",
              [c["alias"] for c in report["alias_collisions"]], ["auroc"])
        check("...compared case-folded, and reported on BOTH entries",
              sorted(os.path.basename(e["file"]) for e in report["entries"]
                     if any(f["item"] == "18-alias-collision" for f in e["findings"])),
              ["roc-curve.md", "sensitivity.md"])
        check("a within-entry duplicate alias is NOT a collision with itself",
              any(c["alias"] == "dupme" for c in report["alias_collisions"]),
              False)
        check("...but is the entry's own 18-alias-duplicate finding",
              [sorted({f["item"] for f in e["findings"]})
               for e in report["entries"]
               if e["file"].endswith("dupalias.md")],
              [["18-alias-duplicate"]])

        bom = put("bom.md", "﻿" + good.replace('title: "ROC curve"',
                                                    'title: "Bom"')
                  .replace("A **ROC curve** plots", "**Bom** plots")
                  .replace("\nROC curve\n", "\nBom\n"))
        check("a BOM does not defeat the parser (and skip all 13 checks)",
              _st_items(lint_file(bom)), [])
        binary = put("binary.md", b'---\ntitle: "Caf\xe9"\n---\nbody\n')
        check("a file that is not UTF-8 is reported and still linted",
              "0-encoding" in _st_items(lint_file(binary)), True)
        check("a missing path is a problem, not a traceback",
              lint_path(os.path.join(tmp, "nope"))["problems"] != [], True)

        floor = lint_path(wiki, severity_floor="error")
        check("--severity error drops warnings and info",
              sorted({f["severity"] for e in floor["entries"]
                      for f in e["findings"]}), ["error"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main([wiki, "-o", os.path.join(tmp, "out.json")])
        check("the exit code is always 0 -- this is a reporting tool, not a gate",
              (rc, os.path.isfile(os.path.join(tmp, "out.json"))), (0, True))

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main([])
        check("a run with no target exits 2 and says so",
              (rc, "target" in buf.getvalue()), (2, True))
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
        prog="lint_entry.py",
        description="Mechanical Quality Checklist checks for wiki-builder "
                    "entries (stdlib only).  Always exits 0.",
        epilog="example: lint_entry.py ~/Vault/Wiki --severity error",
    )
    # `nargs="?"`, so `--test` is reachable: argparse refuses a missing
    # positional before main() runs.  A real run without one is refused below,
    # by name and with exit 2.
    p.add_argument("target", nargs="?",
                   help="an entry .md file, or a wiki folder "
                        "(walked recursively)")
    p.add_argument("--test", action="store_true",
                   help="run the built-in self-test and exit")
    p.add_argument("--severity", choices=["error", "warning", "info"],
                   default="info",
                   help="lowest severity to report (default: info = everything)")
    p.add_argument("-o", "--output", help="write JSON here instead of stdout")
    p.add_argument("--compact", action="store_true", help="compact JSON output")
    return p


def main(argv=None):
    args = _build_parser().parse_args(argv)
    if args.test:
        return run_self_test()
    if not args.target:
        print(json.dumps({"ok": False,
                          "error": "missing required argument: target "
                                   "(an entry .md file or a wiki folder), or --test"},
                         indent=2))
        return 2
    report = lint_path(args.target, severity_floor=args.severity)
    dumped = json.dumps(report, ensure_ascii=False,
                        **({} if args.compact else {"indent": 2}))
    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(dumped + "\n")
            print(json.dumps({"ok": True, "output": os.path.abspath(args.output),
                              "summary": report["summary"]}, indent=2))
        except Exception as exc:
            print(json.dumps({"ok": False, "error": str(exc),
                              "summary": report["summary"]}, indent=2))
    else:
        print(dumped)
    return 0  # reporting tool, never a gate


if __name__ == "__main__":
    sys.exit(main())
