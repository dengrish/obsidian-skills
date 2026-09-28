#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lint_entry.py -- mechanical Quality Checklist checks for wiki entries.

Runs only the objectively checkable items of SKILL.md's Quality Checklist --
the ones the skill itself labels "mechanical".  Everything requiring
judgement (prose quality, tag calibration, alias semantics, merge integrity,
example discipline) is deliberately NOT checked here; those stay with the
model.

Implemented checks (Quality Checklist item -> finding ``item`` slug):

      0-encoding, 0-unreadable, 0-lint-error
                              the file could not be decoded (it is linted
                              with replacement characters), read, or linted
  1   1-valid-yaml            frontmatter fenced by ---, parses (a key's colon
                              is followed by a space), no dupe keys
  2   2-field-order           schema order; mandatory keys present
                              (parents: present, `[]` when empty; read: last)
  2   2-obsidian-key          an Obsidian-owned appearance/publish key; info,
                              report only, preserved on merge
  2   2-provenance            a legacy skill-provenance footer that does not
                              parse
  2   2-type-enum             type: is one of the 15 enum values
  2   2-quoting               Quoting Policy: lossless plain or double-quoted
                              title/description/aliases; sources/tags/parents
                              items double-quoted;
                              type/created/updated/read never quoted;
                              double quotes, never single
  2   2-read-state            read: holds a boolean answer; a null or unknown
                              value is report-only, never inferred as false
  3   3-dates                 created/updated are YYYY-MM-DD; created <= updated
  4   4-sources               sources: is a list of PDF wikilinks with positive
                              page anchors or unanchored markdown wikilinks
  4   4-duplicate-source      review a same-stem PDF/Markdown source pair;
                              provenance must establish whether the note is
                              about the PDF or is an independent clipping
                              (stems compared case- and
                              NFC-insensitively, anchor and folder stripped)
  5   5-slug                  re-run slugify on title:; must equal the filename
  5   5-bare-common-noun      the filename is a bare term from
                              special-titles.md's cross-domain corpus (shared
                              COMMON_NOUNS)
  6   6-api-surface           non-Software entry: fenced code or any
                              backticked identifier (error); a
                              code-identifier title or a library/how-to
                              failure string (warning, author test decides)
  7   7-description           one sentence, <= 110 chars (count reported),
                              plain text, no LaTeX/Markdown/HTML,
                              capitalised, ends "."
  8   8-tags                  exactly one #-prefixed, double-quoted enum slug
                              in block form; #misc is the sole fallback
  9   9-body-structure        body starts immediately with prose; body headings
                              use plain-text ATX `##`, never Setext
  9   9-person-event-date     Person/Event opener has a date parenthetical in
                              a documented form immediately after its bold
                              subject
      9-link-integration      navigation-only cue points directly at a body
                              wikilink (listings/displays masked)
  10  10-duplicate-wikilink   same TARGET SLUG linked >1x in body prose
                              (counted by target, not display text; the
                              Related footer is exempt).  This is item 10's
                              MECHANICAL HALF ONLY -- whether every target
                              resolves is a whole-VAULT question and belongs
                              to wiki-lint's scanner (CONVENTIONS.md §9),
                              which already carries the four carve-outs that
                              make the answer safe to act on
      10-table-cell-wikilink  rendered wikilink occurs inside a Markdown
                              table cell, where links are forbidden
      10-redundant-pipe       exact `[[slug|slug]]` in body prose; the Related
                              footer keeps its mandatory canonical-title pipe
      10-self-link            a body or Related link resolves to this entry
                              (its filename or own alias); single-file mode
                              compares bare targets, folder mode resolves all
  11  11-related-footer       exactly one terminal `**Related:**` line (bare
                              label or ` · `-separated whole wikilinks) before
                              the Flashcards separator, with a blank line
                              before `---`
  11  11-related-display      every Related-footer link is piped; folder mode
                              also requires the resolved target's canonical
                              title
  12  12-image-caption        every Obsidian or Markdown image embed has an
                              immediate italic, plain-text caption
      12-table-caption        every Markdown table has an immediate italic,
                              plain-text caption
      12-equation-coverage-candidate
                              corpus-backed defining prose or inline formula
                              lacks canonical nearby display form; agent reviews
      12-equation-format       an existing display has content on the same line
                              as its `$$` delimiters
      12-boilerplate-candidate
                              well-definedness boilerplate in body prose or card
                              line 1 (nonempty and count guards, sign ranges on
                              named strengths or rates, probabilities summing
                              to one, card sums over every term); agent reviews
      12-equation-typography  raw ell-norm or micrometre symbols in body/card
                              surfaces that require inline LaTeX
      12-literal-dollar       unescaped literal `$` in body prose; escape it
                              as `\\$`
  13  13-merge-scar           a schema key, stray `---` or bare digit line in
                              the explanatory body (listings masked)
  14  14-source-meta          source-meta phrasing or a bare `the author(s)`
                              (warning: a named entry is the carve-out)
  16  16-bold-opener          first outer-bold span equals the title/base/math
                              skeleton and uses the type-specific plain,
                              bold-italic, or mixed taxon/strain style
      16-code-typography      known bracket special tokens and common literal
                              file extensions use backticks in running prose
      16-unenumerated-bold    bold outside the title slot, `- **Term** —`
                              bullet anchors and **Related:**
      16-emphasis-markup      bold/italic wrapped around a wikilink, math or
                              code span (a pure-math title's opener excepted)
  17  17-alias-completeness   an alternative name the body introduces for the
                              entry's own subject -- an italicized also-called
                              synonym, or the opener's acronym/expansion
                              parenthetical -- whose slug is missing from
                              aliases: (warning: the same-entity test and the
                              cross-domain carve-out stay with the executing agent;
                              a single-word candidate of a qualified or
                              common-noun subject carries the scanner's hint)
  19  19-flashcards          `## Flashcards` present on every entry except a
                              discipline root (`<discipline>.md` whose sole
                              tag names it), preceded by a `---` separator;
                              cards are `??` definition, `?` understanding or
                              the user's `!!` (kind from line 1); one primary
                              definition card and at most two understanding
                              cards (extras report-only); line 1 one
                              capitalized sentence ending in a period (a
                              question mark on understanding cards) with
                              inline LaTeX as its only markup; the primary
                              card's line 3 the canonical title (base term,
                              math skeleton; optional opener-established,
                              alias-bound counterpart); an understanding
                              answer takes inline LaTeX only
      19-brevity-candidate   advisory: a definition cue over 25 words outside
                              math, a `, where` glossary or a semicolon clause;
                              an understanding answer over 20 words
  19  19-flashcard-leak       normalized answer-surface search of card line 1
                              (math included) for that card's own answer; a
                              definition card adds its counterpart and, on the
                              primary card, the entry aliases
  18  18-alias-collision      across a folder, no two entries share an alias
  18  18-alias-duplicate      the same alias listed twice within one entry
  18  18-alias-form           every alias is itself in slug form (warning); a
                              non-list field, empty item or self alias is an
                              error
  18  18-display-label        a wikilink display label carries LaTeX, code,
                              bold or italic markup
  18  18-label-target         folder mode, body prose: a label exactly names a
                              different entry, or shares no surface with the
                              resolved target's title/aliases (a math title's
                              plain form counts) and is neither an Organism
                              target's bound common name nor a cross-domain
                              set word the target introduces in italics
                              (warning)
  18  18-partial-label        folder mode, body prose: a label keeps only the
                              target title's modifiers and omits its head word;
                              an inflected or derived head, an alias, or a term
                              the target defines in italics passes (warning)

Items 5, 6, 13, 14, 16 and 18, and item 19's card set, primary card and
discipline-root test, share their per-entry rules with wiki-lint's scanner
through ``shared/scripts/entry_checks.py``. Item 10's self-link rule is
implemented here and in the scanner; ``SHARED_MUTATIONS`` holds both to the
same fixtures.

NOT implemented (out of scope by design): item 4's file existence and page
correctness, item 9's semantic flow/atomicity judgments, item 10's dangling
targets (a whole-vault question for wiki-lint's scanner and the review
orphan-link audit), item 12 beyond image/table caption form and its
conservative equation candidates, item 13's merge-content integrity, item
15, 17 beyond the introduced-alias scan, and the interpretive halves of
6/8/14/18/19.

Folder mode (a directory target) adds the checks a single file cannot run:
``18-alias-collision``, alias- and path-aware ``10-duplicate-wikilink`` and
``10-self-link``, ``18-label-target``, and the canonical-title half of
``11-related-display``. A link target may be qualified by the folder's own
name or by ``Wiki/``.

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
evidence}], title, aliases, description_chars}], alias_collisions[],
summary{..., clean}, problems[]}.

A populated ``parents:`` is deliberately NOT flagged -- wiki-lint writes
that field on every entry, so a value there is the expected steady
state.  Its quoting is covered by ``2-quoting`` and its presence by
``2-field-order``.

``read: true`` is likewise NOT flagged: the value is the user's, and this
script checks that the key is present (``2-field-order``), sits last in
the schema (``2-field-order``), carries a boolean answer (``2-read-state``),
and is unquoted (``2-quoting``) -- a quoted
``"false"`` is a string, which Obsidian's checkbox renders as permanently
checked.  Whether a merge should have RESET the field is not mechanisable --
no script can see whether a body gained substance -- and a missing, null, or
unrecognizable ``read:`` is left unchanged and reported as nonblocking
user-owned state, never repaired:
writing ``read: false``
into an entry the user had already marked read destroys the state the field
exists to hold.

A legacy ``importance:`` key (no longer in the schema; new entries omit it)
is treated like a populated ``parents:`` -- NO finding at any severity: it is
never required, its value is never inspected, and it stays in
``vault_index.SCHEMA_ORDER`` so that its historical slot is neither out of
order nor unknown.

Findings never set the exit status: read ``summary.clean`` and the findings.
Exit 0: complete report. Exit 1: incomplete scope (missing target or
unreadable directory), report-write failure, or a failed ``--test``. Exit 2:
missing target argument or other usage error.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
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

from slugify import SlugError, base_term, has_parenthetical, slug_stem  # noqa: E402
from introduced_aliases import (  # noqa: E402
    _BOLD_PAREN_RE,
    introduced_alias_candidates,
    missing_introduced_aliases,
)
from plurals import singular_keys  # noqa: E402
from organism_names import (  # noqa: E402
    organism_title_classification as _organism_title_classification,
    scientific_abbreviation_matches as _scientific_abbreviation_matches,
)
from code_typography import find_bare_code_shapes  # noqa: E402
from equation_coverage import (  # noqa: E402
    find_boilerplate_candidates,
    find_missing_display_equation_candidates,
    find_noncanonical_display_equation_candidates,
)
from note_provenance import split_provenance  # noqa: E402
from entry_structure import (  # noqa: E402
    CARD_SEPARATORS,
    description_subject_forms as _description_subject_forms,
    acronym_initial_forms as _initial_forms,
    markdown_image_spans as _markdown_image_spans,
    source_stem,
    strip_code,
    strip_fenced,
    strip_indented,
    answer_surface_match,
    body_opens_with_prose,
    count_sentences,
    ends_with_sentence_period,
    flashcard_brevity_hints,
    flashcard_kind,
    flashcard_line1_markup,
    flashcard_line1_faults,
    math_title_plain_text,
    normalized_answer_surface,
    opening_paragraph,
    opener_subject_date_status,
    parse_flashcard_blocks,
    title_display_form,
)
from markdown_tables import (  # noqa: E402
    caption_faults as _caption_faults,
    markdown_block_start,
    markdown_table_spans,
    mask_line_spans,
)
# Per-entry checks shared with wiki-lint's scanner (one copy).
from entry_checks import (  # noqa: E402
    BARE_WORD_ALIAS_HINT,
    BOLD_OUTER_RE as _BOLD_OUTER_RE,
    SHARED_MUTATIONS,
    SHARED_QUIET,
    api_surface_findings,
    bare_common_noun_slug,
    bare_word_alias_candidate,
    bold_parts as _bold_parts,
    cross_domain_synonym_label,
    display_label_links,
    emphasis_span_findings,
    flashcard_set_faults,
    is_discipline_root,
    label_drops_head,
    label_shares_surface,
    merge_scar_findings,
    organism_common_name_bound,
    primary_line3_faults,
    pure_math_opener_markup,
    source_meta_findings,
    unenumerated_bold_findings,
)
from vault_index import (  # noqa: E402
    SCHEMA_ORDER,
    extract_wikilinks,
    fold_name,
    iter_markdown_files,
    parse_frontmatter,
    split_sections,
    unquote_scalar,
)

__all__ = ["lint_text", "lint_file", "lint_path", "TAG_ENUM", "TYPE_ENUM"]

MANDATORY_KEYS = ["title", "type", "sources", "created", "updated",
                  "description", "tags", "parents", "read"]
OPTIONAL_KEYS = ["aliases"]

# Obsidian's own appearance/publish properties are outside the wiki-entry
# schema, but they are user configuration rather than stacked-merge debris.
# A merge must preserve them exactly; wiki-lint reports the same set under a
# report-only key.  Keep this list in parity with scan_vault.OBSIDIAN_KEYS.
OBSIDIAN_KEYS = {"cssclasses", "cssclass", "publish", "permalink", "cover",
                 "image", "banner", "icon"}

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
    "music", "machine-learning", "misc",
]

PLAIN_OR_DOUBLE_SCALARS = ["title", "description"]
NEVER_QUOTED = ["type", "created", "updated", "read"]
QUOTED_LIST_FIELDS = ["sources", "tags", "parents"]

DESCRIPTION_MAX = 110

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_YAML_TYPED_PLAIN_RE = re.compile(
    r"^(?:null|~|true|false|yes|no|on|off|\.nan|[+-]?\.inf|"
    r"[+-]?(?:0|[1-9][0-9_]*)(?:\.[0-9_]*)?(?:e[+-]?[0-9]+)?|"
    r"[0-9]{4}-[0-9]{2}-[0-9]{2})$", re.IGNORECASE)


def _f(item, severity, message, evidence=None):
    return {"item": item, "severity": severity, "message": message,
            "evidence": evidence}


def _organism_title_parts(title, aliases=(), opening=""):
    """Scientific taxon parts only when independent evidence proves the role."""
    status, parts = _organism_title_classification(
        title, aliases, opening)
    return parts if status == "scientific" else None


# --------------------------------------------------------------------------
# small text helpers
# --------------------------------------------------------------------------

def first_letter_ci_equal(a, b):
    """Equality that is case-insensitive on the FIRST letter only (item 16)."""
    if a is None or b is None:
        return False
    if len(a) != len(b):
        return False
    if not a:
        return True
    return a[0].lower() == b[0].lower() and a[1:] == b[1:]


def _valid_date(value):
    if not value or not _DATE_RE.match(value):
        return None
    try:
        return _dt.date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return None


def _style_of(raw):
    try:
        return unquote_scalar(raw)[1]
    except ValueError:
        return "invalid"  # The parser already reports the malformed scalar.


def _plain_string_allowed(value, style):
    """Whether a conservative plain scalar remains a YAML string.

    Requiring a Unicode letter first excludes every numeric/timestamp family
    (including YAML 1.1 octal, sexagesimal, and prefixed integers) without
    trying to emulate competing YAML schemas. Colon-space/end and space-hash
    are the two interior forms that change plain-scalar structure.
    """
    return (style == "bare" and isinstance(value, str) and bool(value)
            and value[:1].isalpha()
            and not _YAML_TYPED_PLAIN_RE.fullmatch(value.strip())
            and not re.search(r":(?:\s|$)|\s#", value))


def parse_flashcards(flashcard_lines):
    """Group card content, excluding protected review metadata from the view.

    The shared parser recognizes the Spaced Repetition plugin's inline,
    next-line, and metadata-callout storage forms plus attached block IDs.
    Counting any of them as card content prescribed deleting user-owned state.
    The source text is never changed; only the linting view omits that state.
    """
    return parse_flashcard_blocks("\n".join(flashcard_lines))


# --------------------------------------------------------------------------
# the checks
# --------------------------------------------------------------------------

def _check_structure(fm, findings):
    if not fm.found:
        for err in fm.errors:
            findings.append(_f("1-valid-yaml", "error", err))
        return False
    for err in fm.errors:
        findings.append(_f("1-valid-yaml", "error", err))
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
            if key == "read":
                findings.append(_f(
                    "2-read-state", "info",
                    "read: is missing -- preserve this unresolved user-owned "
                    "state and include it in the run report; do not invent false",
                    {"report_only": True}))
                continue
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
        if key.lower() in OBSIDIAN_KEYS:
            findings.append(_f(
                "2-obsidian-key", "info",
                "key %r is an Obsidian-owned appearance/publish property -- "
                "REPORT ONLY; preserve it exactly on merge" % key,
                {"key": key, "report_only": True}))
        else:
            findings.append(_f("2-field-order", "warning",
                               "key %r is not part of the entry schema -- preserve "
                               "this user metadata; a schema mismatch alone does "
                               "not authorize deleting or repurposing it" % key))

    # An empty `parents:` is written `parents: []`, never bare: a bare key is
    # YAML null, and the vault pins the property as multitext, so Obsidian
    # renders it as an empty TEXT field -- the declared type and the value on
    # disk disagree (CONVENTIONS.md 2a; scan_vault emits item2/parents-null
    # for the same fault). Tag presence and membership are checked by item 8.
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
    if field.kind != "scalar":
        findings.append(_f(
            "2-type-enum", "error",
            "type: must be one bare scalar, not %s" % field.kind,
            {"line": field.line, "kind": field.kind}))
        return
    value = field.scalar
    if not value:
        findings.append(_f("2-type-enum", "error", "type: is blank; it is mandatory"))
    elif value not in TYPE_ENUM:
        findings.append(_f("2-type-enum", "error",
                           "type: %r is not one of the 15 enum values" % value,
                           {"value": value, "enum": TYPE_ENUM}))


def _check_quoting(fm, findings):
    for key in PLAIN_OR_DOUBLE_SCALARS:
        field = fm.get(key)
        if field is None:
            continue
        style = _style_of(field.raw_value)
        if style != "double" and not _plain_string_allowed(
                field.scalar, style):
            findings.append(_f(
                "2-quoting", "error",
                "%s: must be double-quoted unless its plain YAML spelling "
                "round-trips as a string" % key,
                {"line": field.line, "raw": field.raw_value, "style": style}))

    for key in NEVER_QUOTED:
        if key == "read":
            continue  # _check_read distinguishes known answers from unknown state.
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

    aliases = fm.get("aliases")
    if aliases is not None:
        for raw, value, line in zip(
                aliases.raw_items, aliases.values, aliases.item_lines):
            style = _style_of(raw)
            if style != "double" and not _plain_string_allowed(value, style):
                findings.append(_f(
                    "2-quoting", "error",
                    "aliases: items must be double-quoted unless their plain "
                    "YAML spelling round-trips as a string",
                    {"line": line, "raw": raw, "style": style}))


def _check_read(fm, findings):
    """Validate the checkbox without inventing an answer for missing state."""
    field = fm.get("read")
    if field is None:
        return  # The missing-key finding already routes to the user.
    raw = field.raw_value.strip()
    try:
        value, style = unquote_scalar(raw)
    except ValueError:
        value, style = None, "invalid"
    if field.kind == "scalar" and style == "bare" and raw.lower() in {"true", "false"}:
        return
    if (field.kind == "scalar" and isinstance(value, str)
            and value.lower() in {"true", "false", "yes", "no", "0", "1"}):
        findings.append(_f(
            "2-quoting" if style in {"double", "single"} else "2-read-state", "error",
            "read: must be a bare true/false boolean; correct the spelling "
            "while preserving the existing answer",
            {"line": field.line, "raw": raw, "report_only": False}))
        return
    findings.append(_f(
        "2-read-state", "error",
        "read: has no recognizable boolean answer -- report it to the user; "
        "do not replace it with false or infer a review state",
        {"line": field.line, "raw": raw, "report_only": True}))


def _check_sources(fm, findings):
    """Item 4: a list of complete local-source wikilinks with physical pages."""
    field = fm.get("sources")
    if field is None:
        return  # The mandatory-key check already reports a missing field.
    if not any(value not in (None, "") for value in field.values):
        findings.append(_f(
            "2-field-order", "error",
            "sources: is empty; it must hold at least one item"))
    if not field.values:
        return
    if not field.is_list:
        findings.append(_f(
            "4-sources", "error", "sources: must be a list, not a scalar",
            {"line": field.line}))
    values = [value for value in field.values if value is not None]
    for duplicate in sorted({value for value in values
                             if values.count(value) > 1}):
        findings.append(_f(
            "4-sources", "error",
            "source %r is listed %d times -- keep one exact citation"
            % (duplicate, values.count(duplicate)),
            {"source": duplicate, "count": values.count(duplicate)}))
    for value, line in zip(field.values, field.item_lines):
        if value is None:
            findings.append(_f("4-sources", "error", "sources: contains a null or invalid item",
                               {"line": line}))
            continue
        if re.fullmatch(r"\[\[[^\[\]\r\n|#]+\.(?i:pdf)#page=[1-9][0-9]*\]\]", value):
            continue
        if re.fullmatch(r"\[\[[^\[\]\r\n|#]+\.(?i:md)\]\]", value):
            continue
        findings.append(_f(
            "4-sources", "error",
            "source must be [[Name.pdf#page=N]] with a positive physical "
            "page number, or [[Name.md]] without an anchor; URLs, display "
            "labels and incomplete wikilinks are not source references",
            {"line": line, "source": value}))


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


_LEADING_ARTICLE_RE = re.compile(r"^(?:a|an|the)\s+", re.IGNORECASE)
_SUBJECT_BOUNDARY_RE = re.compile(r"^(?:$|[\s,(:;\u2013\u2014])")


def _description_has_entity_subject(description, title):
    """Conservative mechanical floor for the entity-as-subject rule."""
    if not description or not title:
        return True  # Presence/title validity have their own findings.
    forms = _description_subject_forms(title)
    starts = [description.strip()]
    article = _LEADING_ARTICLE_RE.match(starts[0])
    # A leading article is optional only when it is not already part of the
    # canonical name.  This keeps "The Iliad" valid without accepting the
    # nonsensical "The The Iliad".
    if article and not any(_LEADING_ARTICLE_RE.match(form) for form in forms):
        starts.append(starts[0][article.end():])
    for text in starts:
        if has_parenthetical(title):
            full = text[:len(title)]
            if (first_letter_ci_equal(full, title)
                    and _SUBJECT_BOUNDARY_RE.match(text[len(title):])):
                continue
        for form in forms:
            prefix = text[:len(form)]
            if (first_letter_ci_equal(prefix, form)
                    and _SUBJECT_BOUNDARY_RE.match(text[len(form):])):
                return True
    return False


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
    # Description is plain text, whereas flashcard line 1 permits inline
    # LaTeX. Reuse the shared Markdown/HTML detector, then add the stricter
    # no-dollar rule above. The previous spot check missed ordinary Markdown
    # links, underscore emphasis, HTML, Obsidian tags/comments, highlights,
    # footnotes, and reference definitions; all render literally in Properties.
    markup.extend(flashcard_line1_markup(desc))
    if markup:
        findings.append(_f(
            "7-description", "error",
            "description must be plain text -- found %s" % ", ".join(markup),
            {"chars": length, "description": desc}))

    sentence_count = count_sentences(desc)
    if sentence_count > 1:
        findings.append(_f(
            "7-description", "error",
            "description must be one sentence; found roughly %d"
            % sentence_count,
            {"sentences": sentence_count, "description": desc}))

    if title and not _description_has_entity_subject(desc, title):
        findings.append(_f(
            "7-description", "error",
            "description subject must begin with the canonical title or base "
            "term (an optional leading article is allowed)",
            {"description": desc,
             "expected_subjects": _description_subject_forms(title)}))

    if desc[0].isalpha() and not desc[0].isupper():
        # Carve-out: the description's subject must be the canonical title form,
        # so a lowercase-initial title ("k-nearest neighbors", "scikit-learn")
        # legitimately produces a lowercase-initial description.  The skill's
        # "Capitalized first word" rule and its entity-as-subject rule collide
        # here; entity-as-subject wins.
        # A symbol-bearing title cannot appear literally in this plain-text
        # field: ``$k$-nearest neighbors`` has to be written
        # ``k-nearest neighbors`` here. Treat that mathematical plain form as
        # the canonical subject too, exactly as item 16 and line 3 do.
        subjects = []
        for subject in (title, base_term(title) if title else None):
            for form in (
                    subject,
                    math_title_plain_text(subject) if subject else None):
                if form and form not in subjects:
                    subjects.append(form)
        lowercase_title_subject = any(
            s[0].islower() and desc.startswith(s) for s in subjects)
        if not lowercase_title_subject:
            findings.append(_f("7-description", "error",
                               "description does not start with a capitalised word",
                               {"description": desc}))
    if not ends_with_sentence_period(desc):
        findings.append(_f("7-description", "error",
                           "description does not end with a period",
                           {"description": desc}))


def _check_body_structure(fm, sections, findings):
    """Item 9's deterministic entry-opening and heading floor.

    wiki-lint applies these same source-independent assertions vault-wide.
    Catching them here prevents a builder run from publishing a note that the
    next maintenance pass must immediately repair.
    """
    if fm.body.startswith(("\n", "\r\n")):
        findings.append(_f(
            "9-body-structure", "error",
            "body must begin immediately after frontmatter with no blank line"))

    prose = "\n".join(sections["prose_lines"])
    if not body_opens_with_prose(prose):
        findings.append(_f(
            "9-body-structure", "error",
            "body must open with a prose sentence that states the entry's main claim"))

    # Listings are presentation samples and must not be parsed as headings,
    # but inline code is itself forbidden heading markup.  `strip_code` masks
    # both, which made ``## `Example` `` look like a clean blank heading.
    visible_lines = strip_indented(strip_fenced(prose)).split("\n")
    _table_lines, table_spans = _markdown_tables(prose)
    table_rows = {
        line_i
        for header_i, end_i in table_spans
        for line_i in range(header_i, end_i + 1)
    }
    for line_i, line in enumerate(visible_lines):
        if line_i in table_rows:
            continue
        heading = re.match(r"^ {0,3}(#{1,6})[ \t]+(.+?)\s*$", line)
        if heading:
            faults = []
            if heading.group(1) != "##":
                faults.append("level must be exactly ##")
            heading_text = heading.group(2).rstrip("#").rstrip()
            heading_markup = []
            if "$" in heading_text:
                heading_markup.append("LaTeX")
            heading_markup.extend(flashcard_line1_markup(heading_text))
            if heading_markup:
                faults.append("plain text only (found %s)" % ", ".join(heading_markup))
            if faults:
                findings.append(_f(
                    "9-body-structure", "error",
                    "body heading is noncanonical: %s" % "; ".join(faults),
                    {"body_line": line_i + 1, "text": line.strip()[:160]}))

        # A Setext underline renders the preceding body line as a heading even
        # though it contains no '#'. The entry schema permits only ATX `##`
        # headings, so this must not escape both builder and whole-vault lint.
        previous = visible_lines[line_i - 1] if line_i > 0 else ""
        if (line_i > 0 and previous.strip()
                and not markdown_block_start(previous)
                and re.fullmatch(r" {0,3}(?:=+|-+)[ \t]*", line)):
            findings.append(_f(
                "9-body-structure", "error",
                "Setext body headings are noncanonical; use a plain-text `##` heading",
                {"body_line": line_i + 1,
                 "text": visible_lines[line_i - 1].strip()[:160]}))


_RELATED_RENDERED_RE = re.compile(
    r"^ {0,3}(?:>[ \t]*)?\*\*Related:\*\*(?:[ \t]*.*)?$")


def _check_related_footer(sections, findings):
    """Require one canonical terminal footer without hiding malformed forms."""
    visible = sections.get("visible_lines", sections["lines"])
    masked = strip_fenced("\n".join(visible)).split("\n")
    indexes = [index for index, line in enumerate(masked)
               if _RELATED_RENDERED_RE.match(line)]
    if not indexes:
        findings.append(_f(
            "11-related-footer", "error",
            "entry has no `**Related:**` footer before Flashcards"))
        return
    if len(indexes) > 1:
        findings.append(_f(
            "11-related-footer", "error",
            "entry has %d rendered Related footers; consolidate them into one"
            % len(indexes), {"body_lines": [index + 1 for index in indexes]}))
    index = indexes[0]
    line = visible[index].rstrip()
    form_bad = not line.startswith("**Related:**")
    if not form_bad:
        tail = line[len("**Related:**"):]
        if tail:
            if not tail.startswith(" "):
                form_bad = True
            else:
                parts = tail[1:].split(" · ")
                form_bad = (not parts or any(
                    re.fullmatch(r"\[\[[^\[\]\n]+\]\]", part) is None
                    for part in parts))
    if form_bad:
        findings.append(_f(
            "11-related-footer", "error",
            "Related footer must be exactly `**Related:**`, optionally followed "
            "by whole-line wikilinks separated with ` · `",
            {"body_line": index + 1, "text": line[:160]}))
    # Folder mode adds the resolved canonical title to these findings.
    for target, display in extract_wikilinks(line):
        if display is None:
            findings.append(_f(
                "11-related-display", "error",
                "Related footer link [[%s]] must be piped to the target's "
                "canonical plain-text title" % target,
                {"target": target}))

    flash = sections.get("flashcards_index")
    if flash is not None:
        if index >= flash:
            findings.append(_f(
                "11-related-footer", "error",
                "Related footer must precede the Flashcards separator and heading"))
            return
        nonblank = [i for i in range(index + 1, flash)
                    if visible[i].strip()]
        allowed_separator = nonblank[-1] if nonblank else None
        stray = [i for i in nonblank
                 if i != allowed_separator
                 or visible[i].strip() != "---"]
        if stray:
            findings.append(_f(
                "11-related-footer", "error",
                "body content appears after the Related footer before Flashcards",
                {"body_lines": [i + 1 for i in stray]}))
        if (allowed_separator is not None and allowed_separator == index + 1
                and sections["lines"][allowed_separator].strip() == "---"):
            findings.append(_f(
                "11-related-footer", "error",
                "leave a blank line after the Related footer; an immediate `---` "
                "renders the footer as a Setext heading",
                {"body_line": allowed_separator + 1}))
    elif any(line.strip() for line in visible[index + 1:]):
        findings.append(_f(
            "11-related-footer", "error",
            "body content appears after the Related footer; it must be terminal"))


def _check_tags(fm, findings):
    field = fm.get("tags")
    if field is None:
        return
    if field.kind in ("scalar", "flow_list"):
        findings.append(_f(
            "8-tags", "error",
            "tags: must be a block-form list (one double-quoted tag per `-` "
            "line), including the sole #misc fallback when no specific "
            "discipline applies; do not use scalar or flow-list syntax",
            {"line": field.line, "kind": field.kind}))
    values = [v for v in field.values if v not in (None, "")]
    # An unquoted # tag is a comment, not a parsed value. Its original text
    # still tells the user which discipline was lost and how to repair it.
    for raw, value, line in zip(field.raw_items, field.values, field.item_lines):
        if raw.startswith("#"):
            findings.append(_f(
                "8-tags", "error",
                "unquoted %s parses as a YAML comment -- the discipline is "
                "silently lost; write - \"%s\"" % (raw, raw),
                {"line": line, "raw": raw}))
    if not values:
        findings.append(_f(
            "8-tags", "error",
            "tags: must contain exactly one discipline tag; use only #misc "
            "when no specific discipline fits",
            {"line": field.line}))
        return
    if len(values) != 1 or len(field.values) != 1:
        findings.append(_f(
            "8-tags", "error",
            "tags: must contain exactly one discipline home; express cross-field "
            "relationships in prose and links",
            {"line": field.line, "values": values}))
    if "#misc" in values and (len(values) != 1 or len(field.values) != 1):
        findings.append(_f(
            "8-tags", "error",
            "#misc must be the sole tag; use the one specific discipline tag "
            "instead when it applies",
            {"line": field.line, "values": values}))
    for raw, value, line in zip(field.raw_items, field.values, field.item_lines):
        if not isinstance(value, str) or not value:
            continue
        if not value.startswith("#"):
            findings.append(_f("8-tags", "error",
                               "tag %r is not #-prefixed" % value,
                               {"line": line, "raw": raw}))
            continue
        slug = value[1:]
        if slug not in TAG_ENUM:
            findings.append(_f(
                "8-tags", "error",
                "tag #%s is not one of the %d valid discipline slugs"
                % (slug, len(TAG_ENUM)),
                {"line": line, "value": value, "enum": TAG_ENUM}))


def _check_aliases(fm, findings, filename):
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
    if not field.is_list:
        if field.kind == "blank":
            message = ("aliases: must be a list; a bare key is YAML null -- "
                       "remove this optional key when there are no aliases, or "
                       "write `aliases: []` for an explicit empty list")
        else:
            message = ("aliases: must be a list, not a scalar -- wrap the "
                       "existing value as one quoted list item without changing it")
        findings.append(_f(
            "18-alias-form", "error",
            message,
            {"line": field.line, "kind": field.kind}))
    # The same alias twice on ONE entry is its own fault, not a cross-entry
    # collision (scan_vault reports it the same way, as a within-entry item18).
    # Counted raw, exactly as scan_vault counts it.
    values = [v for v in field.values if v]
    for value, line in zip(field.values, field.item_lines):
        if value == "":
            findings.append(_f(
                "18-alias-form", "error",
                "aliases: contains an empty item -- remove the item; an empty "
                "string is not an alternate name",
                {"line": line, "alias": value}))
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
    own_slug = os.path.splitext(os.path.basename(filename))[0]
    own_family = singular_keys(fold_name(own_slug))
    alias_families = []
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
        if fold_name(expected) == fold_name(own_slug):
            findings.append(_f(
                "18-alias-form", "error",
                "alias %r resolves to this entry's own filename -- remove the "
                "redundant self-alias" % value,
                {"line": line, "alias": value, "slug": own_slug}))
        elif singular_keys(fold_name(expected)) & own_family:
            findings.append(_f(
                "18-alias-form", "error",
                "alias %r differs from this entry's filename only by "
                "singular/plural normalization -- remove the redundant alias"
                % value,
                {"line": line, "alias": value, "slug": own_slug}))
        elif value != expected:
            findings.append(_f(
                "18-alias-form", "warning",
                "alias %r is not in slug form (expected %r) -- aliases follow the "
                "same slug rule as the filename, and the collision probes read "
                "them as slugs" % (value, expected),
                {"line": line, "alias": value, "expected": expected}))
        family = singular_keys(fold_name(expected))
        for other, other_expected, other_family in alias_families:
            if (fold_name(expected) != fold_name(other_expected)
                    and family & other_family):
                findings.append(_f(
                    "18-alias-duplicate", "error",
                    "aliases %r and %r differ only by singular/plural "
                    "normalization -- keep one surface family"
                    % (other, value),
                    {"alias": value, "other": other}))
                break
        alias_families.append((value, expected, family))


# --------------------------------------------------------------------------
# item 17's introduced-alias scan
# --------------------------------------------------------------------------

#: A lexical marker LEADING the parenthetical name -- ``(singular,
#: *archaeon*)``, ``(formerly Facebook)``.  Annotation, not part of the name:
#: left in place, the candidate came out polluted ("singular, *archaeon*",
#: expected alias "singular-archaeon").
_PAREN_LEADIN_RE = re.compile(
    r"^(?:(?:short\s+for|originally\s+called|also\s+called|"
    r"also\s+known\s+as|known\s+as)|singular|plural|abbreviated|"
    r"formerly|n[ée]e|or)[\s,:]+", re.IGNORECASE)

_SHORT_FOR_PAREN_RE = re.compile(r"^short\s+for[\s,:]+", re.IGNORECASE)

#: A direct italic scientific abbreviation can be the title's own established
#: counterpart: ``**Saccharomyces cerevisiae** (*S. cerevisiae*)``.  This is
#: deliberately narrower than "any italic parenthetical" so an annotated
#: synonym does not become a flashcard counterpart merely because it is also
#: listed in aliases.
_SCI_ABBREV_RE = re.compile(r"^[A-Z]\.\s*[a-z][A-Za-z.-]*(?:\s+[a-z][A-Za-z.-]*)*$")


def _acronym_counterpart(term, candidate):
    """Whether the pair has an acronym/full-form relationship.

    The check is deliberately structural.  It rejects arbitrary alternate
    names such as Mark Twain/Samuel Clemens while admitting canonical shapes
    such as PCA, CART, Lasso, MLOps, OOB, and t-SNE.
    """
    term_words = re.findall(r"[A-Za-z0-9]+", term or "")
    cand_words = re.findall(r"[A-Za-z0-9]+", candidate or "")
    if not term_words or not cand_words:
        return False

    def compact_forms(value, words):
        forms = set()
        first = re.sub(r"[^A-Za-z0-9]", "", words[0])
        if len(first) >= 2:
            forms.add(first.casefold())
        uppers = "".join(ch for ch in value if ch.isupper())
        if len(uppers) >= 2:
            forms.add(uppers.casefold())
        whole = re.sub(r"[^A-Za-z0-9]", "", value)
        if len(words) == 1 and len(whole) >= 2:
            forms.add(whole.casefold())
        return forms

    def related(short, long):
        if len(short) < 2 or len(long) < len(short):
            return False
        if short == long or long.startswith(short):
            return True
        it = iter(long)
        return all(ch in it for ch in short)

    def acronym_tokens(value):
        """Compact tokens that visibly behave as abbreviations.

        Initials alone miss established forms whose letters come from a
        compound or morpheme (ATP, DNA, RNA, MLOps) and a short token carried
        beside a shared tail (OOB evaluation).  Requiring at least two written
        capitals keeps ordinary title-cased names and pseudonyms out.
        """
        out = set()
        for token in re.findall(r"[A-Za-z0-9]+", value or ""):
            compact = re.sub(r"[^A-Za-z0-9]", "", token)
            if (2 <= len(compact) <= 10
                    and sum(1 for ch in token if ch.isupper()) >= 2):
                out.add(compact.casefold())
        return out

    def lexical_compact(value):
        return re.sub(r"[^A-Za-z0-9]", "", value or "").casefold()

    term_compact = compact_forms(term, term_words)
    cand_compact = compact_forms(candidate, cand_words)
    initial_match = (
        any(related(short, initials)
            for short in cand_compact for initials in _initial_forms(term))
        or any(related(short, initials)
               for short in term_compact for initials in _initial_forms(candidate))
    )
    if initial_match:
        return True
    term_text, candidate_text = lexical_compact(term), lexical_compact(candidate)
    return (
        any(related(short, candidate_text) for short in acronym_tokens(term))
        or any(related(short, term_text) for short in acronym_tokens(candidate))
    )

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
    # A masked leading comment is blank; the opener starts at visible text.
    block = opening_paragraph("\n".join(sections["prose_lines"]).lstrip())
    return " ".join(line.strip() for line in block.splitlines())


def _alias_candidates(sections, subject_forms=None):
    """Names the body introduces for the entry's subject: ``(name, where)``."""
    prose_lines = strip_code("\n".join(sections["prose_lines"])).split("\n")
    return introduced_alias_candidates(prose_lines, subject_forms)


def _check_alias_completeness(fm, sections, findings, filename):
    """Item 17's completeness half: body-introduced names must be aliases.

    Warning, never error: the same-entity test ("*dummy attributes* names the
    produced attributes, not the encoding") and the cross-domain bare-term
    carve-out are judgment, so the finding hands the executing agent a candidate, not a
    verdict.  The three mechanical exclusions ARE applied: a form that slugs
    identically to the filename, a singular/plural form already covered by the filename or ``aliases:``,
    and a word from the designated cross-domain set, which never becomes an alias.
    """
    title = fm.scalar("title") or ""
    aliases = fm.values("aliases")
    stem = os.path.splitext(os.path.basename(filename))[0]
    prose_lines = strip_code("\n".join(sections["prose_lines"])).split("\n")
    for cand, where, cslug in missing_introduced_aliases(
            prose_lines, title, aliases, stem):
        # wiki-lint's scanner adds the same hint to its alias candidate.
        hint = ("; " + BARE_WORD_ALIAS_HINT
                if bare_word_alias_candidate(cslug, title, cand) else "")
        findings.append(_f(
            "17-alias-completeness", "warning",
            "the body introduces %r (%s) as a name for the subject, but "
            "aliases: does not carry %r -- add it if it names this same "
            "entity; a cross-domain bare term or a wrong-entity name stays "
            "out (checklist item 17)%s" % (cand, where, cslug, hint),
            {"candidate": cand, "where": where, "expected_alias": cslug}))


# NOTE: there is deliberately no _check_importance either.  The field was
# removed from the schema; new entries omit the key entirely, and the legacy
# entries that still carry it are left alone -- nothing strips it and nothing
# flags it, at any severity.  So there is no presence check (it is out of
# MANDATORY_KEYS), no quoting check (out of NEVER_QUOTED), no enum check, and
# no value-validation check.  The key is still listed in
# vault_index.SCHEMA_ORDER, which is what keeps _check_field_order from
# reporting a legacy `importance:` as an unknown or misplaced key.


# NOTE: there is deliberately no _check_parents.  A populated `parents:` is the
# expected steady state -- wiki-lint's Task 3 writes that field on every
# entry -- so flagging it fired on the whole vault after a single lint pass.  It
# was redundant anyway: `parents` is in QUOTED_LIST_FIELDS, so _check_quoting
# already reports an unquoted item, and it is in MANDATORY_KEYS, so
# _check_field_order already reports a missing key.


_OBSIDIAN_IMAGE_EMBED_LINE_RE = re.compile(
    r"^\s*!\[\[[^\]\n]*\.(?:png|jpe?g|gif|svg|webp|tiff?|bmp|avif|ico)"
    r"(?:\|[^\]\n]*)?\]\]\s*$", re.IGNORECASE)


def _markdown_image_line(line):
    stripped = (line or "").strip()
    matches = list(_markdown_image_spans(stripped))
    return bool(matches and matches[0][0] == 0 and matches[0][1] == len(stripped))


def _image_embed_lines(body):
    """Return original lines and real standalone image-embed line indexes."""
    original = body.split("\n")
    masked = strip_code(body).split("\n")
    return original, [
        i for i, line in enumerate(masked)
        if _OBSIDIAN_IMAGE_EMBED_LINE_RE.match(line) or _markdown_image_line(line)
    ]


def _check_image_captions(fm, sections, findings):
    """Item 12 image-caption adjacency and plainness for both embed forms."""
    body = "\n".join(sections["prose_lines"])
    lines, embeds = _image_embed_lines(body)
    for embed_i in embeds:
        caption = lines[embed_i + 1].strip() if embed_i + 1 < len(lines) else ""
        faults = _caption_faults(caption)
        if faults == ["missing italic caption"]:
            findings.append(_f(
                "12-image-caption", "error",
                "image embed needs an italic plain-text caption on the "
                "immediately following line",
                {"line": fm.body_start_line + embed_i,
                 "embed": lines[embed_i].strip()[:80]}))
        elif faults:
            findings.append(_f(
                "12-image-caption", "error",
                "image caption has %s; captions are italic plain text "
                "(only inline LaTeX is allowed)" % ", ".join(faults),
                {"line": fm.body_start_line + embed_i + 1,
                 "caption": caption[:80]}))


def _markdown_tables(body):
    """Return ``(original_lines, (header, end)...)`` for real Markdown tables.

    Fenced and indented listings are masked for detection, while captions are
    read from the original text so forbidden markup remains visible.
    """
    original = body.split("\n")
    return original, markdown_table_spans(strip_indented(strip_fenced(body)))


def _check_table_captions(fm, sections, findings):
    """Item 12's mechanical table-caption adjacency and plainness check."""
    body = "\n".join(sections["prose_lines"])
    lines, tables = _markdown_tables(body)
    for header_i, end_i in tables:
        caption = lines[end_i + 1].strip() if end_i + 1 < len(lines) else ""
        faults = _caption_faults(caption)
        if faults == ["missing italic caption"]:
            findings.append(_f(
                "12-table-caption", "error",
                "Markdown table needs an italic plain-text caption on the "
                "immediately following line",
                {"line": fm.body_start_line + header_i,
                 "header": lines[header_i].strip()[:80]}))
        elif faults:
            findings.append(_f(
                "12-table-caption", "error",
                "Markdown table caption has %s; captions are italic plain text "
                "(only inline LaTeX is allowed)" % ", ".join(faults),
                {"line": fm.body_start_line + end_i + 1,
                 "caption": caption[:80]}))


def _check_equation_coverage_candidates(fm, sections, findings):
    """Item 12's conservative floor for prose/inline defining math."""
    prose = "\n".join(sections["prose_lines"])
    masked = strip_code(prose)
    _lines, table_spans = _markdown_tables(prose)
    candidates = find_missing_display_equation_candidates(masked, table_spans)
    for candidate in candidates:
        candidate["line"] += fm.body_start_line - 1
    if candidates:
        findings.append(_f(
            "12-equation-coverage-candidate", "warning",
            "prose or inline math appears to define a calculation without "
            "a nearby display equation; first decide whether notation adds "
            "explanatory value under the equation policy. Keep a simple "
            "verbal rule in prose when a formula would only restate it. "
            "If useful, verify the relationship and define its symbols",
            {"matches": candidates, "agent_review": True}))
    form_candidates = find_noncanonical_display_equation_candidates(
        masked, table_spans)
    for candidate in form_candidates:
        candidate["line"] += fm.body_start_line - 1
    if form_candidates:
        findings.append(_f(
            "12-equation-format", "error",
            "display math has content on the same line as its `$$` delimiters; "
            "keep the existing equation and put each delimiter on its own line",
            {"matches": form_candidates}))
    boilerplate = find_boilerplate_candidates(masked, table_spans)
    for candidate in boilerplate:
        candidate["line"] += fm.body_start_line - 1
    for card_no, card in enumerate(
            parse_flashcards(sections["flashcard_lines"]), 1):
        for candidate in find_boilerplate_candidates(
                strip_code(card[0] if card else ""), card_line=True):
            candidate.pop("line", None)
            candidate["card"] = card_no
            boilerplate.append(candidate)
    if boilerplate:
        findings.append(_f(
            "12-boilerplate-candidate", "warning",
            "possible well-definedness boilerplate: a condition the formula "
            "already presupposes (a nonempty set, a count guard, a sign range "
            "on a named strength or rate, probabilities summing to one) or, "
            "on card line 1, index bounds that run over every term. Remove "
            "it unless the definition needs the range",
            {"matches": boilerplate, "agent_review": True}))


def _literal_dollar_count(text):
    """Count literal dollars after removing code and valid math spans."""
    visible = strip_code(text or "").replace(r"\$", " ")
    visible = re.sub(r"\$\$.*?\$\$", " ", visible, flags=re.DOTALL)
    # A closing math delimiter is not immediately followed by a digit. This
    # preserves both signs in ``$20 ... $30`` while accepting numeric math.
    visible = re.sub(r"(?<!\\)\$(?!\$)[^$\n]*\$(?!\d)", " ", visible)
    return visible.count("$")


def _check_literal_dollars(body, findings):
    count = _literal_dollar_count(body)
    if count:
        findings.append(_f(
            "12-literal-dollar", "error",
            "%d unescaped literal dollar sign%s in body prose; escape each "
            "currency or other literal sign as `\\$`" %
            (count, "" if count == 1 else "s")))


def _check_unicode_math(fm, sections, findings):
    """Catch raw mathematical Unicode in rendered prose/card surfaces."""
    prose = strip_code("\n".join(sections["prose_lines"]))
    for line_no, line in enumerate(prose.split("\n"), 1):
        if re.search(r"ℓ(?:[0-9₀-₉])", line):
            findings.append(_f(
                "12-equation-typography", "error",
                "raw ℓ-norm notation must use inline LaTeX, such as "
                "`$\\ell_1$` or `$\\ell_2$`",
                {"body_line": line_no, "text": line.strip()[:160]}))
        if re.search(r"(?<!\w)(?:μ|µ)m\b", line):
            findings.append(_f(
                "12-equation-typography", "error",
                "raw micrometre notation must use inline LaTeX, such as "
                "`$\\mu\\mathrm{m}$`",
                {"body_line": line_no, "text": line.strip()[:160]}))
    description = fm.scalar("description") or ""
    if re.search(r"ℓ(?:[0-9₀-₉])", description):
        findings.append(_f(
            "12-equation-typography", "error",
            "raw ℓ-norm notation in description must use plain words such "
            "as `ell-one` or `ell-two`; YAML descriptions do not render LaTeX",
            {"field": "description", "text": description[:160]}))
    for card_no, card in enumerate(
            parse_flashcards(sections["flashcard_lines"]), 1):
        line1 = card[0] if card else ""
        if re.search(r"ℓ(?:[0-9₀-₉])", line1):
            findings.append(_f(
                "12-equation-typography", "error",
                "raw ℓ-norm notation in flashcard %d line 1 must use inline "
                "LaTeX, such as `$\\ell_1$` or `$\\ell_2$`" % card_no,
                {"card": card_no, "line1": line1[:160]}))
        if re.search(r"(?<!\w)(?:μ|µ)m\b", line1):
            findings.append(_f(
                "12-equation-typography", "error",
                "raw micrometre notation in flashcard %d line 1 must use "
                "inline LaTeX, such as `$\\mu\\mathrm{m}$`" % card_no,
                {"card": card_no, "line1": line1[:160]}))


def _check_table_cell_wikilinks(fm, sections, findings):
    """Item 10: rendered wikilinks never belong inside table cells."""
    body = "\n".join(sections["prose_lines"])
    lines, tables = _markdown_tables(body)
    for header_i, end_i in tables:
        for line_i in range(header_i, end_i + 1):
            # Inline-code examples render literally and are not links.  Fenced
            # and indented listings cannot be table spans in _markdown_tables.
            for target, _label in extract_wikilinks(strip_code(lines[line_i])):
                findings.append(_f(
                    "10-table-cell-wikilink", "error",
                    "wikilinks are not allowed in Markdown table cells; use "
                    "plain text in the table and integrate the link in prose",
                    {"line": fm.body_start_line + line_i, "target": target,
                     "text": lines[line_i].strip()[:160]}))


_NAVIGATION_ONLY_LINK_RE = re.compile(
    r"(?:^|[.!?,;:]\s+|\(\s*|[—–-]\s+)"
    r"(?:see(?:\s+also)?|refer\s+to|consult|"
    r"for\s+(?:more\s+)?details,?\s+see)\s+\[\[", re.IGNORECASE)
_REDUNDANT_PIPE_RE = re.compile(
    r"(?<!!)\[\[(?P<target>[^\[\]\n|#^/\\]+)\|(?P=target)\]\]")


def _check_redundant_piped_wikilinks(sections, findings):
    """Reject an exact body-prose ``[[slug|slug]]`` alias."""
    raw_prose = "\n".join(sections["prose_lines"])
    prose = mask_line_spans(strip_code(raw_prose), _markdown_tables(raw_prose)[1])
    for match in _REDUNDANT_PIPE_RE.finditer(prose):
        target = match.group("target")
        findings.append(_f(
            "10-redundant-pipe", "error",
            "wikilink [[%s|%s]] in body prose has a display label identical "
            "to its slug; use [[%s]]" % (target, target, target),
            {"target": target, "region": "body prose"}))


def _check_integrated_wikilinks(fm, sections, findings):
    """Item 9: a body link participates in the claim rather than directing.

    This narrow floor catches only an imperative cue immediately governing a
    wikilink.  Listings, figures/captions, and tables/captions are presentation
    material and are masked.  Broader paragraph flow remains a reading task.
    """
    body = "\n".join(sections["prose_lines"])
    raw_lines = body.split("\n")
    masked_lines = strip_code(body).split("\n")
    skip = set()
    _original, tables = _markdown_tables(body)
    for header_i, end_i in tables:
        skip.update(range(header_i, min(len(raw_lines), end_i + 2)))
    _original, embeds = _image_embed_lines(body)
    for embed_i in embeds:
        skip.add(embed_i)
        skip.add(embed_i + 1)
    for i, line in enumerate(masked_lines):
        if i in skip or re.match(r"^\s*\*.*\*\s*$", line):
            continue
        if _NAVIGATION_ONLY_LINK_RE.search(line):
            findings.append(_f(
                "9-link-integration", "error",
                "navigation-only cross-reference; integrate the wikilink into "
                "the sentence's claim instead of directing the reader to see it",
                {"line": fm.body_start_line + i,
                 "text": raw_lines[i].strip()[:160]}))


def _body_wikilink_occurrences(sections):
    # Extraction runs on the LISTING-MASKED prose (fenced blocks, inline code
    # spans, indented code), exactly as scan_vault's item10/dup reads
    # strip_code(prose): a target SHOWN in a listing and linked once in prose
    # is linked ONCE, and "keep first only" applied to that pair edits the
    # listing or drops the real link.  Evidence text still quotes the raw line.
    prose_lines = sections["prose_lines"]
    body = "\n".join(prose_lines)
    masked_lines = strip_code(body).split("\n")
    # Tables and their captions are presentation surfaces rather than body
    # prose.  Item 10 reports a real link in a cell directly, while item 12
    # owns a caption link; neither should also distort the duplicate count.
    skip = set()
    _original, tables = _markdown_tables(body)
    for header_i, end_i in tables:
        skip.update(range(header_i, min(len(prose_lines), end_i + 2)))
    # Count the entry a link resolves to, not its raw spelling.  A single-file
    # lint can safely fold case/normalization and an explicit ``.md`` suffix,
    # but it must retain path qualification: ``[[a/target]]`` and
    # ``[[b/target]]`` may name two distinct files.  Folder mode resolves paths,
    # basenames, and aliases against the actual inventory below.
    occurrences = []
    for offset, line in enumerate(masked_lines):
        if offset in skip:
            continue
        for target, label in extract_wikilinks(line):
            key = _link_key(target)
            # Explicit MOC navigation is outside entry-link pruning. The
            # Wiki-only folder inventory cannot validate or own those notes.
            if not key or key.startswith("mocs/"):
                continue
            occurrences.append(
                {"key": key, "body_line": offset + 1, "target": target,
                 "display": label, "text": prose_lines[offset].strip()})
    return occurrences


def _append_duplicate_wikilink_findings(findings, occurrences, resolve=None):
    seen = {}
    for occurrence in occurrences:
        key = (resolve(occurrence) if resolve else occurrence["key"])
        if key is None:
            # Whole-folder resolution found several possible owners.  The
            # linter must preserve every occurrence until that ambiguity is
            # resolved; a duplicate-removal finding would choose by accident.
            continue
        seen.setdefault(key, []).append(occurrence)
    for key, hits in seen.items():
        if len(hits) > 1:
            findings.append(_f(
                "10-duplicate-wikilink", "error",
                "entry target %r is wikilinked %d times in body prose -- keep the first "
                "and unlink the rest to bare text (counted by target slug, not "
                "raw path/case/display spelling; the Related footer is exempt)"
                % (key, len(hits)),
                {"target": key, "count": len(hits), "occurrences": hits}))


def _check_duplicate_wikilinks(sections, findings):
    _append_duplicate_wikilink_findings(
        findings, _body_wikilink_occurrences(sections))


def _check_person_event_date(fm, sections, findings):
    """Enforce item 9's placement and exact-form floor for dates."""
    entry_type = fm.scalar("type") or ""
    if entry_type not in ("Person", "Event"):
        return
    prose = "\n".join(sections["prose_lines"]).strip()
    opener = opening_paragraph(prose)
    status = opener_subject_date_status(opener, entry_type)
    if status == "missing":
        findings.append(_f(
            "9-person-event-date", "error",
            "%s opener needs a date parenthetical immediately after the "
            "bolded subject" % entry_type))
    elif status == "malformed":
        findings.append(_f(
            "9-person-event-date", "error",
            "%s opener date parenthetical is not one of the exact forms in "
            "references/rare-types.md (including qualifier punctuation and "
            "en-dash spacing)" % entry_type))


def _check_code_typography(sections, findings):
    """Enforce item 16's backticks on safe, recognizable prose shapes."""
    body = "\n".join(sections["prose_lines"])
    masked = strip_code(body)
    tables = markdown_table_spans(masked)
    for occurrence in find_bare_code_shapes(masked, tables):
        findings.append(_f(
            "16-code-typography", "error",
            "bare %(kind)s %(token)r in running prose -- wrap the literal "
            "shape in backticks" % occurrence,
            occurrence))


# --------------------------------------------------------------------------
# checks shared with wiki-lint's scanner (shared/scripts/entry_checks.py)
# --------------------------------------------------------------------------

def _shared_prose(fm, sections):
    """``(prose, first_line)`` in the scanner's view of the explanatory body.

    The scanner reads the body without the blank lines after the frontmatter
    (``9-body-structure`` reports those), so they are dropped here too.
    ``first_line`` is the file line of the returned prose's first line.
    """
    lines = sections["prose_lines"]
    lead = 0
    while lead < len(lines) and lines[lead] == "":
        lead += 1
    return "\n".join(lines[lead:]), fm.body_start_line + lead


def _file_line(first_line, finding):
    line = finding.get("line")
    return first_line + line - 1 if line else None


def _check_bare_common_noun(findings, filename):
    """Item 5: a bare filename from special-titles.md's cross-domain corpus.

    The error is ``report_only``: a merge into an existing bare-slug entry
    reports the rename proposal it may not apply, while a new entry must
    still be qualified.
    """
    stem = os.path.splitext(os.path.basename(filename))[0]
    if bare_common_noun_slug(stem):
        findings.append(_f(
            "5-bare-common-noun", "error",
            "bare-slug common noun %r -- qualify a new entry's title as "
            "special-titles.md's cross-domain tests require and re-run "
            "find_collisions.py on it; an existing entry's rename stays a "
            "proposal" % stem,
            {"slug": stem, "report_only": True}))


def _check_api_surface(fm, sections, findings):
    """Item 6: API surface in a non-Software entry.

    Fenced code and the zero backticked-identifier cap are errors. The
    code-identifier title and the library/how-to failure strings are
    warnings: a name such as ``Amazon.com`` and a framing sentence may be a
    legitimate non-API use, so the author test in api-surface.md decides.
    """
    prose, _first_line = _shared_prose(fm, sections)
    for finding in api_surface_findings(
            fm.scalar("type") or "", fm.scalar("title") or "", prose, fm.body):
        severity = ("error" if finding["check"] in
                    ("fenced-code", "backticked-identifiers") else "warning")
        evidence = {"check": finding["check"]}
        for key in ("label", "identifiers"):
            if key in finding:
                evidence[key] = finding[key]
        findings.append(_f("6-api-surface", severity,
                           finding["message"], evidence))


def _check_merge_scars(fm, sections, findings):
    """Item 13: a schema key, stray ``---`` or bare digit line in the body."""
    prose, first_line = _shared_prose(fm, sections)
    for finding in merge_scar_findings(prose):
        findings.append(_f(
            "13-merge-scar", "error", finding["message"],
            {"check": finding["check"],
             "line": _file_line(first_line, finding)}))


def _check_source_meta(fm, sections, findings):
    """Item 14: source-meta phrasing (warning).

    The named-entry carve-out needs the vault: this gate accepts ``the
    author(s) of`` a wikilink, an emphasized title, or a capitalized name or
    acronym, and wiki-lint's scanner verifies that it names an existing
    entry.
    """
    prose, _first_line = _shared_prose(fm, sections)
    for finding in source_meta_findings(prose, fm.scalar("type") or ""):
        evidence = {"check": finding["check"]}
        if "text" in finding:
            evidence["text"] = finding["text"]
        findings.append(_f(
            "14-source-meta", "warning",
            finding["message"] + " -- re-subject the sentence on the concept "
            "(checklist item 14)", evidence))


def _check_emphasis(fm, sections, findings):
    """Item 16: unenumerated bold and emphasis around a link/math/code span."""
    prose, first_line = _shared_prose(fm, sections)
    tables = markdown_table_spans(strip_indented(strip_fenced(prose)))
    for finding in unenumerated_bold_findings(prose, tables):
        findings.append(_f(
            "16-unenumerated-bold", "error", finding["message"],
            {"span": finding["span"],
             "line": _file_line(first_line, finding)}))
    title = fm.scalar("title") or ""
    running_title = base_term(title) if has_parenthetical(title) else title
    opener_markup = pure_math_opener_markup(
        running_title, opening_paragraph(prose.lstrip()))
    for finding in emphasis_span_findings(
            prose, sections["related_line"] or "", tables,
            opener_markup=opener_markup):
        findings.append(_f(
            "16-emphasis-markup", "error", finding["message"],
            {"kind": finding["kind"], "span": finding["span"]}))


def _display_label_text(sections, related=True):
    """Listing- and table-masked body prose, plus the masked Related footer."""
    prose = "\n".join(sections["prose_lines"])
    text = mask_line_spans(strip_code(prose), _markdown_tables(prose)[1])
    if related:
        text += "\n" + strip_code(sections["related_line"] or "")
    return text


def _check_display_labels(sections, findings):
    """Item 18: wikilink display labels render as plain text."""
    for link in display_label_links(_display_label_text(sections)):
        if link["marks"]:
            findings.append(_f(
                "18-display-label", "error", link["message"],
                {"target": link["target"], "display": link["display"],
                 "markup": link["marks"]}))


def _link_key(target):
    """Portable key for a link target: path kept, ``.md`` and anchors gone."""
    normalized = target.replace("\\", "/").strip().strip("/")
    if normalized.lower().endswith(".md"):
        normalized = normalized[:-3]
    return fold_name(normalized)


def _self_link_occurrences(sections):
    """Rendered links in table-masked body prose and the Related footer."""
    prose = "\n".join(sections["prose_lines"])
    regions = (
        ("body prose",
         mask_line_spans(strip_code(prose), _markdown_tables(prose)[1])),
        ("Related footer", strip_code(sections["related_line"] or "")))
    occurrences = []
    for region, text in regions:
        for target, display in extract_wikilinks(text):
            key = _link_key(target)
            # Explicit MOC navigation never names this Wiki entry.
            if key and not key.startswith("mocs/"):
                occurrences.append({"target": target, "key": key,
                                    "display": display, "region": region})
    return occurrences


def _self_link_finding(occurrence):
    return _f(
        "10-self-link", "error",
        "wikilink target %r in %s resolves to this entry itself -- remove the "
        "redundant footer link or render a subject mention as plain text; if "
        "an anchored body link is deliberate navigation, use a local anchor"
        % (occurrence["target"], occurrence["region"]),
        {"target": occurrence["target"], "region": occurrence["region"]})


def _check_self_links(fm, sections, findings, filename):
    """Item 10: no link to the entry itself (its filename or its own alias).

    A single file cannot tell which folder a path-qualified target names, so
    only bare targets are compared here; folder mode re-resolves every link.
    """
    stem = os.path.splitext(os.path.basename(filename))[0]
    own = {fold_name(stem)} | {fold_name(a) for a in fm.values("aliases") if a}
    for occurrence in _self_link_occurrences(sections):
        if "/" not in occurrence["key"] and occurrence["key"] in own:
            findings.append(_self_link_finding(occurrence))


def _check_bold_opener(fm, sections, findings):
    title = fm.scalar("title")
    if not title:
        return
    # The opener is the first PARAGRAPH, not the first line: reading one line
    # made a hard-wrapped opening sentence whose bold lands on line 2 report
    # "the opening sentence has no bolded span".  (wiki-lint's scanner has
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

    # The FIRST outer-bold span is the one item 16 owns.  One parser handles
    # ordinary, triple-emphasis, and mixed taxon/strain title forms.
    m = _BOLD_OUTER_RE.search(opening)
    if not m:
        findings.append(_f(
            "16-bold-opener", "error",
            "the opening sentence has no bolded span; it must open by bolding "
            "the entry title", {"opening": opening[:200]}))
        return

    bolded, style, italic_prefix = _bold_parts(m)
    bolded = bolded.strip()
    # The parenthetical qualifier never appears in running prose.
    accepted = [base_term(title) if has_parenthetical(title) else title]
    entry_type = fm.scalar("type") or ""
    organism_status, organism_parts = (
        _organism_title_classification(
            accepted[0], fm.values("aliases"), opening)
        if entry_type == "Organism" else ("common", None))

    # Rank-marked taxa can have discontiguous italic spans inside the outer
    # bold. Their style is a source-aware agent judgment, but their visible title must still be
    # compared without leaving inner ``*`` markers in the text skeleton.
    compared_bolded = (bolded.replace("*", "").replace("_", "")
                       if organism_status == "ambiguous" else bolded)
    title_matches = any(first_letter_ci_equal(compared_bolded, cand)
                        for cand in accepted)
    # Symbol/variable carve-out: compare meaning-preserving mathematical
    # plain forms.
    skeleton = math_title_plain_text(compared_bolded)
    title_matches = title_matches or any(
        first_letter_ci_equal(skeleton, math_title_plain_text(cand))
        for cand in accepted)

    if title_matches:
        if organism_status == "ambiguous":
            # Typography still needs source-aware item-16 agent judgment,
            # but ambiguity has no persistent metadata to close a recurring
            # scanner warning.  Accept either style mechanically once the
            # visible title is right; the executing agent, not this regex, decides.
            return
        expected_style = "full-italic" if entry_type == "Work" else "plain"
        if organism_status == "scientific":
            expected_prefix, suffix = organism_parts
            expected_style = "mixed" if suffix else "full-italic"
        if style == expected_style and (
                expected_style != "mixed"
                or (italic_prefix == expected_prefix
                    and bolded == expected_prefix + organism_parts[1])):
            return
        if expected_style == "plain":
            readable = "**%s**" % accepted[0]
        elif expected_style == "full-italic":
            readable = "***%s***" % accepted[0]
        else:
            readable = "***%s*%s**" % organism_parts
        findings.append(_f(
            "16-bold-opener", "error",
            "the opening title has the wrong bold/italic combination for "
            "%s; use %s" % (entry_type or "this entry type", readable),
            {"title": title, "type": entry_type, "opening": opening[:200]}))
        return

    findings.append(_f(
        "16-bold-opener", "error",
        "first bolded span %r does not equal title: %r "
        "(compared case-insensitively on the first letter only; base-term and "
        "math-title plain-form carve-outs applied)" % (bolded, title),
        {"bolded": bolded, "title": title, "accepted": accepted,
         "bolded_skeleton": skeleton, "opening": opening[:200]}))


def _flashcard_primary_answer(fm, sections):
    """Return ``(term, counterpart)`` established by the entry itself.

    The main term has one exact plain-text spelling: ``title:`` verbatim, its
    base term for a disambiguation parenthetical, or its mathematical plain
    form for a symbol title. An opener parenthetical becomes a required counterpart only
    when its slug is actually present in ``aliases:``; that distinguishes an
    opener-established binding from a date or explanatory aside and avoids
    inferring counterpart semantics from an alias list that can also hold
    synonyms.
    """
    title = fm.scalar("title") or ""
    term = base_term(title) if has_parenthetical(title) else title
    term = title_display_form(term)
    alias_field = fm.get("aliases")
    aliases = {
        fold_name(a) for a in
        (alias_field.values if alias_field is not None and alias_field.is_list else [])
        if a
    }
    entry_type = fm.scalar("type") or ""
    opening = _opening_block(sections)
    organism_parts = (_organism_title_parts(
        term, fm.values("aliases"), opening)
        if entry_type == "Organism" else None)
    counterpart = None
    for match in _BOLD_PAREN_RE.finditer(_opening_block(sections)):
        visible, _style, _italic = _bold_parts(match)
        # Identity is compared in plain form, so a Greek title bolded as
        # LaTeX or spelled out still binds its counterpart.
        if not first_letter_ci_equal(math_title_plain_text(visible),
                                     math_title_plain_text(term)):
            continue
        raw_candidate = match.group("paren")
        # Item 17 treats annotated parentheticals such as
        # ``(singular, *archaeon*)`` as alias evidence.  They are not the
        # title's direct opener-established binding and therefore do not belong
        # on flashcard line 3.  Keep this narrower than `_clean_paren_name`,
        # whose lead-in stripping is correct for alias completeness.
        short_for = bool(_SHORT_FOR_PAREN_RE.match(raw_candidate))
        cleaned = _clean_paren_name(raw_candidate)
        scientific_abbreviation = bool(
            organism_parts
            and _scientific_abbreviation_matches(cleaned, organism_parts[0])
            and
            re.fullmatch(r"\*[^*\n]+\*", raw_candidate.strip())
            and _SCI_ABBREV_RE.fullmatch(cleaned))
        acronym_binding = _acronym_counterpart(term, cleaned)
        if short_for or scientific_abbreviation or acronym_binding:
            candidate = cleaned
        else:
            continue
        try:
            candidate_slug = fold_name(slug_stem(candidate))
        except SlugError:
            continue
        if candidate_slug in aliases:
            counterpart = candidate
            break
    return term, counterpart


_LINE3_RE = re.compile(r"(?P<term>.*?)(?: \((?P<paren>[^()\n]+)\))?")


def _line3_parts(line3):
    """Split card line 3 into its term and optional parenthetical."""
    line3 = line3.strip()
    match = _LINE3_RE.fullmatch(line3)
    return (match.group("term"), match.group("paren")) if match else (line3, None)


def _flashcard_line3_fault(line3, fm, sections):
    """Explain a line-3 contract violation, or return ``None``."""
    expected_term, required_counterpart = _flashcard_primary_answer(fm, sections)
    term, counterpart = _line3_parts(line3)
    if expected_term and term != expected_term:
        return "the term must be exactly %r (same canonical casing)" % expected_term

    if counterpart is not None:
        if required_counterpart is None:
            return ("the parenthetical %r is not established as the title's own "
                    "opener-established, alias-bound counterpart" % counterpart)
        if counterpart != required_counterpart:
            return "the established counterpart must appear exactly as (%s)" % required_counterpart
    if required_counterpart is not None and counterpart != required_counterpart:
        return "the established counterpart must appear exactly as (%s)" % required_counterpart
    return None


#: The frontmatter errors the scanner's ``parse_fm`` also collects (its
#: ``_fm_bad``): a line no key owns, or a value that does not parse.
_UNREADABLE_FM = re.compile(
    r"line \d+: (?:unparseable |unexpected indented key |invalid YAML flow)")


def _is_root_entry(fm, filename):
    """Whether this entry is a discipline root, which needs no card.

    The shared ``is_discipline_root`` test is the scanner's too, behind its
    ``tags_valid_single`` gate: one ``tags:`` key written as a list and no
    unreadable frontmatter line. A layout fault elsewhere (list indentation,
    a duplicated non-tag key) keeps the root in both tools.
    """
    field = fm.get("tags")
    tags = (field.values if field is not None and field.is_list
            and fm.order.count("tags") == 1
            and not any(_UNREADABLE_FM.match(e) for e in fm.errors)
            else None)
    stem = os.path.splitext(os.path.basename(filename))[0]
    return is_discipline_root(stem, tags, TAG_ENUM)


def _check_flashcards_present(fm, sections, findings, filename):
    """Item 19's mechanical clauses for the section and its card set.

    The leak scan below is item 19's other half and it only runs when a
    Flashcards section exists -- so an entry with no section at all passed the
    whole of item 19 silently, which is the one failure mode item 19 has that a
    reader cannot see by looking at the entry (nothing is wrong; something is
    missing).  Checked here: the section is present, preceded by a `---`
    separator of its own, and holds the primary `??` card plus at most two
    `?` understanding cards, each well formed.  A discipline root needs no
    card, so it skips the missing-section, no-card and no-primary findings;
    any card it keeps is checked as usual.
    """
    root = _is_root_entry(fm, filename)
    if sections["flashcards_index"] is None:
        if not root:
            findings.append(_f(
                "19-flashcards", "error",
                "entry has no `## Flashcards` section -- item 19 requires one "
                "on every entry, after the Related footer, preceded by a "
                "`---` separator line, holding the primary `??` card"))
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
    else:
        separator_index = sections["separator_index"]
        flashcards_index = sections["flashcards_index"]
        lines = sections["lines"]
        if (separator_index + 1 >= len(lines)
                or lines[separator_index + 1].strip()):
            findings.append(_f(
                "19-flashcards", "error",
                "the `---` separator must be followed by a blank line before "
                "`## Flashcards`",
                {"line": fm.body_start_line + separator_index}))
        if (flashcards_index + 1 >= len(lines)
                or lines[flashcards_index + 1].strip()):
            findings.append(_f(
                "19-flashcards", "error",
                "`## Flashcards` must be followed by a blank line before card "
                "line 1",
                {"line": fm.body_start_line + flashcards_index}))
    cards = parse_flashcards(sections["flashcard_lines"])
    if not cards and not root:
        findings.append(_f(
            "19-flashcards", "error",
            "the `## Flashcards` section holds no card -- item 19 requires "
            "the primary `??` definition card"))
    # The card-set shape comes from the complete cards only; a malformed
    # block keeps its own finding below. The scanner shares this helper.
    kinds = [flashcard_kind(card) for card in cards if len(card) >= 3]
    for message, report_only in flashcard_set_faults(kinds):
        if root and not report_only:
            continue                      # a root's missing primary card
        evidence = {"cards": len(cards), "kinds": kinds}
        if report_only:
            evidence["report_only"] = True
        findings.append(_f("19-flashcards", "error",
                           "the `## Flashcards` section holds " + message,
                           evidence))

    # Item 19's remaining mechanical clauses (scan_vault checks them too; the
    # two tools must agree). Line 2 is `??` (a definition card), `?` (an
    # understanding card) or the user's `!!`, which marks a card they
    # disabled, keeps the kind its line 1 shows, and is preserved, never
    # converted. A definition card's line 1 is one period-ended sentence; an
    # understanding card's is one question. The primary card's line 3 is the
    # canonical title: the base term for a parenthetical-disambiguated title,
    # the meaning-preserving plain form for a symbol title (line 3 is plain
    # text, so `$k$-fold` can only ever appear there as `k-fold`), plus the
    # entry's own opener-established, alias-bound counterpart.
    title = fm.scalar("title")
    line3_checks, brevity = [], []
    for card_no, card in enumerate(cards, 1):
        if len(card) < 3:
            # A 1- or 2-line block is not a card at all (canon: cue /
            # separator / answer, contiguous).  The length-gated checks below
            # both skipped it silently, so the one card broken enough to be
            # missing a line was the one card item 19 never flagged --
            # scan_vault reports the same input as malformed; the two tools
            # must agree.
            findings.append(_f(
                "19-flashcards", "error",
                "flashcard %d is malformed -- a card is 3 contiguous lines "
                "(cue / separator / answer), found %d (a blank line between "
                "lines 1-3 breaks the card)" % (card_no, len(card)),
                {"card": card_no, "lines": len(card)}))
            continue
        if len(card) > 3:
            findings.append(_f(
                "19-flashcards", "error",
                "flashcard %d has %d visible lines -- only the first three "
                "may be card content; recognized Spaced Repetition state may "
                "be attached to line 3, follow it as `<!--SR:` metadata, or "
                "use the exact `sr|card-metadata` callout, so other content "
                "after the answer is "
                "malformed" % (card_no, len(card)),
                {"card": card_no, "lines": len(card)}))
        understanding = flashcard_kind(card) == "understanding"
        # Preserve indentation for the shared block-Markdown check; sentence
        # checks normalize their own surrounding whitespace.
        line1, line2, line3 = card[0], card[1].strip(), card[2].strip()
        line1_faults = flashcard_line1_faults(line1, question=understanding)
        if line1_faults:
            findings.append(_f(
                "19-flashcards", "error",
                "flashcard %d line 1 %s -- %s and takes inline LaTeX only "
                "(no Markdown or HTML)" % (
                    card_no, " and ".join(line1_faults),
                    "an understanding question is one capitalized sentence "
                    "ending in `?`" if understanding else
                    "the definition must be one capitalized, "
                    "period-terminated sentence"),
                {"card": card_no, "faults": line1_faults,
                 "kind": "understanding" if understanding else "definition"}))
        if line2 not in CARD_SEPARATORS:
            findings.append(_f(
                "19-flashcards", "error",
                "flashcard %d line 2 is %r -- it must be exactly `??` (the "
                "primary definition card), `?` (an understanding card) or the "
                "user's `!!`, preserved verbatim, never converted"
                % (card_no, line2[:20]),
                {"card": card_no, "line2": line2[:40]}))
        if understanding:
            markup = flashcard_line1_markup(line3)
            if markup:
                findings.append(_f(
                    "19-flashcards", "error",
                    "flashcard %d answer has forbidden %s -- an understanding "
                    "answer takes inline LaTeX only"
                    % (card_no, ", ".join(markup)),
                    {"card": card_no, "faults": markup}))
            hints = flashcard_brevity_hints(line3, answer=True)
        else:
            if title:
                line3_checks.append(
                    (card_no, line3,
                     _flashcard_line3_fault(line3, fm, sections)))
            hints = flashcard_brevity_hints(line1)
        if hints:
            brevity.append({"card": card_no, "hints": hints})
    if brevity:
        findings.append(_f(
            "19-brevity-candidate", "warning",
            "possible over-long or two-idea card line; review it under the "
            "card rules and shorten only a genuine shortfall",
            {"matches": brevity, "agent_review": True}))

    # A preserved extra definition card keeps its own answer: with several,
    # only the primary card is held to the line-3 contract (the scanner makes
    # the same choice through entry_checks). Understanding cards never are.
    term, counterpart = _flashcard_primary_answer(fm, sections)
    faults, no_primary = primary_line3_faults(
        len(line3_checks), line3_checks, term, counterpart)
    if no_primary and not root:
        findings.append(_f(
            "19-flashcards", "error", no_primary,
            {"expected_line3": term + (" (%s)" % counterpart
                                       if counterpart else "")}))
    for card_no, line3, fault in faults:
        findings.append(_f(
            "19-flashcards", "error",
            "flashcard %d line 3 is %r -- %s" % (card_no, line3[:40], fault),
            {"card": card_no, "line3": line3[:60], "title": title}))


def _check_flashcard_leak(fm, sections, findings):
    if sections["flashcards_index"] is None:
        return
    title = fm.scalar("title")
    if not title:
        return
    # The shared normalizer folds Unicode punctuation, slash/dash variants,
    # and whitespace, so an answer cannot evade the leak floor by changing
    # ``bias/variance`` to ``bias – variance``. The two tools must agree.
    expected_term, _counterpart = _flashcard_primary_answer(fm, sections)
    aliases = [alias for alias in fm.values("aliases") if alias]
    for card_no, card in enumerate(parse_flashcards(sections["flashcard_lines"]), 1):
        line1 = card[0]
        if flashcard_kind(card) == "understanding":
            # A question may name the entity; it only must not hold its own
            # answer.
            raw_needles = ([("answer", card[2].strip())]
                           if len(card) >= 3 else [])
        else:
            term_main, paren = _line3_parts(card[2] if len(card) >= 3 else "")
            paren_is_discipline = False
            if paren:
                try:
                    paren_is_discipline = slug_stem(paren) in TAG_ENUM
                except SlugError:
                    pass
            raw_needles = [("answer", term_main)]
            if paren and not paren_is_discipline:
                raw_needles.append(("answer counterpart", paren))
            if expected_term and term_main == expected_term:
                raw_needles.extend(("alias", alias) for alias in aliases)

        needles, seen_forms = [], set()
        for kind, surface in raw_needles:
            normalized = normalized_answer_surface(surface)
            if normalized and normalized not in seen_forms:
                seen_forms.add(normalized)
                needles.append((kind, surface))
        for kind, needle in needles:
            match_kind = answer_surface_match(line1, needle)
            if match_kind is None:
                continue
            findings.append(_f(
                "19-flashcard-leak",
                "error",
                "flashcard %d line 1 leaks the %s %r (Unicode/case/punctuation "
                "normalized whole surface, math regions included)"
                % (card_no, kind, needle),
                {"card": card_no, "needle": needle, "kind": kind,
                 "line1": line1}))


def _check_source_duplicates(fm, findings):
    """Item 4: no two ``sources:`` items may name the same document.

    ``paper-summarize`` writes a note into ``Articles/`` for every PDF it
    summarises, named after that PDF's stem, so one document sits in the vault
    under two names -- ``Sources/PDFs/X.pdf`` and ``Articles/X.md`` -- and
    both are legal ``sources:`` values. However, an independent web clipping
    can have the same stem too. This check has no source-note provenance,
    so it reports a review candidate, never a deletion instruction.

    Only a stem collision ACROSS the two extensions is a finding.  An entry
    may legitimately cite several distinct PDFs and several distinct markdown
    clippings, so a ``.md`` source
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
            "4-duplicate-source", "warning",
            "%s and %s share a filename stem; review the markdown note's "
            "decoded sources: (or legacy source:) to establish whether it "
            "summarizes that PDF. A URL-origin clipping can be independent. "
            "Preserve both sources until their identity is confirmed"
            % (md_value, pdf_value),
            {"stem": stem, "markdown": md_value, "markdown_line": md_line,
             "pdf": pdf_value, "pdf_line": pdf_line, "review_only": True}))


# --------------------------------------------------------------------------
# drivers
# --------------------------------------------------------------------------

def lint_text(text, filename):
    """Lint one entry given its text.  Returns the per-file result dict."""
    # ``lint_file`` reads bytes to keep the pathname/descriptor race check
    # exact, so it does not receive Python text mode's universal-newline
    # translation. Normalize here as part of the programmatic API too: CRLF
    # and legacy CR notes have the same Markdown structure as LF notes.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    findings = []
    result = {"file": os.path.abspath(filename), "findings": findings,
              "title": None, "aliases": [],
              "description_chars": None}

    try:
        text, _provenance = split_provenance(text)
    except ValueError as exc:
        findings.append(_f("2-provenance", "error",
                           "invalid skill provenance: %s" % exc))
    fm = parse_frontmatter(text)
    if not _check_structure(fm, findings):
        return result

    result["title"] = fm.scalar("title")
    result["aliases"] = [a for a in fm.values("aliases") if a]
    desc = fm.scalar("description")
    result["description_chars"] = len(desc) if desc else 0

    sections = split_sections(fm.body)

    _check_field_order(fm, findings)
    _check_type(fm, findings)
    _check_quoting(fm, findings)
    _check_read(fm, findings)
    _check_dates(fm, findings)
    _check_sources(fm, findings)
    _check_source_duplicates(fm, findings)
    _check_slug(fm, findings, filename)
    _check_bare_common_noun(findings, filename)
    _check_description(fm, findings, title=result["title"])
    _check_tags(fm, findings)
    _check_aliases(fm, findings, filename)
    _check_alias_completeness(fm, sections, findings, filename)
    _check_body_structure(fm, sections, findings)
    _check_related_footer(sections, findings)
    _check_table_cell_wikilinks(fm, sections, findings)
    _check_redundant_piped_wikilinks(sections, findings)
    _check_duplicate_wikilinks(sections, findings)
    _check_self_links(fm, sections, findings, filename)
    _check_integrated_wikilinks(fm, sections, findings)
    _check_person_event_date(fm, sections, findings)
    _check_image_captions(fm, sections, findings)
    _check_equation_coverage_candidates(fm, sections, findings)
    _check_literal_dollars("\n".join(sections["prose_lines"]), findings)
    _check_unicode_math(fm, sections, findings)
    _check_table_captions(fm, sections, findings)
    _check_bold_opener(fm, sections, findings)
    _check_code_typography(sections, findings)
    _check_emphasis(fm, sections, findings)
    _check_api_surface(fm, sections, findings)
    _check_merge_scars(fm, sections, findings)
    _check_source_meta(fm, sections, findings)
    _check_display_labels(sections, findings)
    _check_flashcards_present(fm, sections, findings, filename)
    _check_flashcard_leak(fm, sections, findings)
    return result


def lint_file(path, _snapshot_text=None):
    """Lint one file on disk. Optionally retain its guarded text internally."""
    abspath = os.path.abspath(path)
    preamble = []
    descriptor = None
    try:
        before = os.stat(abspath, follow_symlinks=False)
        if stat.S_ISLNK(before.st_mode):
            raise OSError("leaf Markdown path is a symlink; its target is "
                          "outside this lint run's editable ownership")
        if not stat.S_ISREG(before.st_mode):
            raise OSError("leaf Markdown path is not a regular file")
        descriptor = os.open(
            abspath, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0))
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise OSError("leaf Markdown path changed while it was opened")
        with os.fdopen(descriptor, "rb") as fh:
            descriptor = None
            raw = fh.read()
            opened_after = os.fstat(fh.fileno())
        after = os.stat(abspath, follow_symlinks=False)
        stable = lambda item: (
            item.st_dev, item.st_ino, item.st_size,
            getattr(item, "st_mtime_ns", int(item.st_mtime * 1e9)),
            getattr(item, "st_ctime_ns", int(item.st_ctime * 1e9)),
            stat.S_IFMT(item.st_mode),
        )
        if not (stable(before) == stable(opened)
                == stable(opened_after) == stable(after)):
            raise OSError("leaf Markdown path changed while it was read")
        # utf-8-sig strips a BOM before the opening frontmatter fence.
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            text = raw.decode("utf-8-sig", errors="replace")
            preamble.append(_f("0-encoding", "error",
                               "file is not valid UTF-8 (%s); linted with "
                               "replacement characters" % exc))
    except UnicodeDecodeError as exc:
        preamble.append(_f("0-encoding", "error",
                           "file is not valid UTF-8 (%s); linted with "
                           "replacement characters" % exc))
    except Exception as exc:
        return {"file": abspath, "title": None, "aliases": [],
                "description_chars": None,
                "findings": [_f("0-unreadable", "error",
                                "could not read file: %s: %s"
                                % (type(exc).__name__, exc))]}
    finally:
        if descriptor is not None:
            os.close(descriptor)
    try:
        result = lint_text(text, abspath)
        result["findings"] = preamble + result["findings"]
        if _snapshot_text is not None:
            # Match lint_text's read-only newline view, including legacy CR.
            _snapshot_text[abspath] = text.replace("\r\n", "\n").replace("\r", "\n")
        return result
    except Exception as exc:  # a malformed entry is a finding, never a crash
        return {"file": abspath, "title": None, "aliases": [],
                "description_chars": None,
                "findings": [_f("0-lint-error", "error",
                                "internal error while linting: %s: %s"
                                % (type(exc).__name__, exc))]}


def _check_alias_collisions(results):
    """Item 18, folder scope: no two entries share an ``aliases:`` string.

    Compared with the portable case/normalization identity from
    ``vault_index.fold_name``. ``Lambda-Rank`` on one entry and ``lambda-rank``
    on another would otherwise have filesystem-dependent ownership.
    """
    owners = {}                    # folded alias -> (display alias, [files])
    filename_owners = {}
    for res in results:
        stem = os.path.splitext(os.path.basename(res["file"]))[0]
        filename_owners.setdefault(fold_name(stem), []).append(res["file"])
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
    for folded, (alias, alias_files) in sorted(owners.items()):
        target_files = filename_owners.get(folded, [])
        for alias_file in alias_files:
            others = [path for path in target_files if path != alias_file]
            if not others:
                continue
            collision_files = [alias_file] + others
            collisions.append({"alias": alias, "files": collision_files,
                               "kind": "alias-filename"})
            result = next(res for res in results if res["file"] == alias_file)
            result["findings"].append(_f(
                "18-alias-collision", "error",
                "alias %r is another entry's filename slug; the file owns that "
                "Obsidian destination and silently shadows this alias" % alias,
                {"alias": alias,
                 "files": [os.path.basename(path) for path in collision_files]}))
    return collisions


def _strip_wiki_root(key, root):
    """Drop a leading root qualifier: the folder's own name or ``Wiki/``.

    Root-qualified targets are how links name discipline roots and other
    basename collisions, and a private review tree need not be named ``Wiki``.
    scan_vault accepts the same prefixes, longest first.
    """
    prefixes = {fold_name(os.path.basename(os.path.abspath(root))) + "/", "wiki/"}
    for prefix in sorted(prefixes, key=lambda value: (-len(value), value)):
        if key.startswith(prefix):
            return key[len(prefix):]
    return key


def _recheck_folder_duplicate_wikilinks(results, root, snapshot_text):
    """Re-run item 10 with the folder's unambiguous alias ownership.

    A single-file lint can normalize ``.md`` and case while preserving paths,
    but only folder scope can know that ``[[sub/term]]``, ``[[term]]`` and an
    alias reach one entry.  File names outrank aliases, and ambiguous basenames
    or aliases remain unresolved rather than choosing an owner by walk order.
    Repeats of one missing target still count as one target.
    """
    resolve_target = _folder_resolver(results, root)[0]

    def resolve(occurrence):
        return resolve_target(occurrence["target"],
                              missing="unresolved-target:")

    for result in results:
        text = snapshot_text.get(result["file"])
        if text is None:
            continue
        fm = parse_frontmatter(text)
        if not fm.found:
            continue
        occurrences = _body_wikilink_occurrences(split_sections(fm.body))
        result["findings"] = [
            finding for finding in result["findings"]
            if finding["item"] != "10-duplicate-wikilink"
        ]
        _append_duplicate_wikilink_findings(
            result["findings"], occurrences, resolve=resolve)


def _malformed_alias_field(result):
    """Whether single-file lint found a scalar or blank ``aliases:`` field.

    scan_vault excludes such a field from its alias resolver too, so folder
    lint must not let malformed metadata establish ownership.
    """
    return any(
        finding["item"] == "18-alias-form"
        and (finding.get("evidence") or {}).get("kind") in ("scalar", "blank")
        for finding in result["findings"])


def _folder_resolver(results, root):
    """Folder-scope link resolution: ``(resolve, owner_for_file, owners)``.

    ``resolve(target)`` returns the owning entry's root-relative key, or
    ``None`` when the target is ambiguous or missing (with ``missing`` set, a
    missing target returns that prefix plus its key). An exact path wins; a
    shorter path suffix or a bare basename must identify one file; a unique
    alias applies only when no file has that basename. ``owners`` maps each
    key to its per-file result.
    """
    root = os.path.abspath(root)
    owners = {}
    basenames = {}
    owner_for_file = {}
    for result in results:
        relative = os.path.relpath(result["file"], root).replace(os.sep, "/")
        if relative.lower().endswith(".md"):
            relative = relative[:-3]
        owner = fold_name(relative)
        owner_for_file[result["file"]] = owner
        owners[owner] = result
        basenames.setdefault(owner.rsplit("/", 1)[-1], set()).add(owner)

    alias_owners = {}
    for result in results:
        if _malformed_alias_field(result):
            continue
        owner = owner_for_file[result["file"]]
        for alias in result.get("aliases", []):
            key = fold_name(alias)
            if key:
                alias_owners.setdefault(key, set()).add(owner)

    def resolve(target, missing=None):
        key = _link_key(target)
        lookup = _strip_wiki_root(key, root)
        basename = lookup.rsplit("/", 1)[-1]
        basename_matches = basenames.get(basename, set())
        if lookup in owners:
            if "/" in key or len(basename_matches) == 1:
                return lookup
            return None
        path_matches = {owner for owner in owners
                        if owner == lookup or owner.endswith("/" + lookup)}
        if len(path_matches) == 1:
            return next(iter(path_matches))
        if path_matches or basename in basenames:
            return None
        alias_matches = alias_owners.get(lookup, set())
        if len(alias_matches) == 1:
            return next(iter(alias_matches))
        return None if alias_matches or missing is None else missing + lookup

    return resolve, owner_for_file, owners


def _check_folder_related_labels(results, root, snapshot_text):
    """Item 11: resolve footer targets and require their canonical titles.

    The title comparison is folder-only. A single entry cannot know whether a
    target, basename, or alias has one owner, and choosing one would turn an
    ambiguous link into a destructive false prescription.
    """
    resolve, _owner_for_file, owners = _folder_resolver(results, root)
    titles = {owner: result["title"] for owner, result in owners.items()
              if result.get("title")}

    for result in results:
        text = snapshot_text.get(result["file"])
        if text is None:
            continue
        fm = parse_frontmatter(text)
        if not fm.found:
            continue
        related = split_sections(fm.body)["related_line"] or ""
        for target, display in extract_wikilinks(related):
            owner = resolve(target)
            raw_canonical = titles.get(owner) if owner else None
            canonical = (title_display_form(raw_canonical)
                         if raw_canonical else None)
            if not canonical:
                continue
            if display is None:
                # Enrich the single-file finding instead of repeating it.
                finding = _f(
                    "11-related-display", "error",
                    "Related footer link [[%s]] must be piped to the target's "
                    "canonical plain-text title %r" % (target, canonical),
                    {"target": target, "expected_display": canonical})
                findings = result["findings"]
                pending = next(
                    (i for i, old in enumerate(findings)
                     if old["item"] == "11-related-display"
                     and old.get("evidence") == {"target": target}), None)
                if pending is None:
                    findings.append(finding)
                else:
                    findings[pending] = finding
            elif display != canonical:
                result["findings"].append(_f(
                    "11-related-display", "error",
                    "Related footer display %r must equal the target's canonical "
                    "plain-text title %r" % (display, canonical),
                    {"target": target, "display": display,
                     "expected_display": canonical}))


def _check_folder_link_targets(results, root, snapshot_text):
    """Items 10 and 18 with folder ownership: self-links and label targets.

    Every self-link is re-resolved here, including path-qualified targets and
    aliases, replacing the single-file bare-target floor. A body-prose label
    with no markup is compared with the resolved target's title and aliases
    (warning): it must not exactly name a different entry, and it must share a
    surface with the target unless an Organism target binds it as a common
    name or the target's prose introduces it in italics as a designated
    cross-domain synonym. Related-footer labels are held to the stricter
    canonical title by ``11-related-display``.
    """
    resolve, owner_for_file, owners = _folder_resolver(results, root)
    organism_fields = {}

    def binds_common_name(owner, display):
        """Whether an Organism target binds ``display`` as its common name."""
        if owner not in organism_fields:
            target_fm = parse_frontmatter(
                snapshot_text.get(owners[owner]["file"]) or "")
            organism_fields[owner] = (
                (target_fm.scalar("type") or "", target_fm.scalar("title") or "",
                 target_fm.scalar("description") or "",
                 _shared_prose(target_fm,
                               split_sections(target_fm.body))[0])
                if target_fm.found else None)
        fields = organism_fields[owner]
        return bool(fields) and organism_common_name_bound(*fields, display)

    target_prose = {}

    def prose_of(owner):
        """The target's explanatory prose, for terms it defines in italics."""
        if owner not in target_prose:
            target_fm = parse_frontmatter(
                snapshot_text.get(owners[owner]["file"]) or "")
            target_prose[owner] = (
                _shared_prose(target_fm, split_sections(target_fm.body))[0]
                if target_fm.found else "")
        return target_prose[owner]

    for result in results:
        text = snapshot_text.get(result["file"])
        if text is None:
            continue
        fm = parse_frontmatter(text)
        if not fm.found:
            continue
        sections = split_sections(fm.body)
        own = owner_for_file[result["file"]]
        findings = [finding for finding in result["findings"]
                    if finding["item"] != "10-self-link"]
        for occurrence in _self_link_occurrences(sections):
            if resolve(occurrence["target"]) == own:
                findings.append(_self_link_finding(occurrence))
        for link in display_label_links(
                _display_label_text(sections, related=False)):
            owner = resolve(link["target"]) if not link["marks"] else None
            target = owners.get(owner) if owner else None
            if (target is None or not target.get("title")
                    or _malformed_alias_field(target)):
                continue
            display = link["display"]
            try:
                display_owner = resolve(slug_stem(display))
            except SlugError:
                display_owner = None
            evidence = {"target": link["target"], "display": display,
                        "target_title": target["title"]}
            surfaces = [target["title"]] + list(target.get("aliases", []))
            if display_owner is not None and display_owner != owner:
                findings.append(_f(
                    "18-label-target", "warning",
                    "wikilink [[%s|%s]] uses a display label that exactly names "
                    "a different entry, %r, rather than the chosen target %r -- "
                    "review the target or the label; do not auto-retarget"
                    % (link["target"], display,
                       owners[display_owner].get("title") or display_owner,
                       target["title"]),
                    dict(evidence, display_owner=display_owner)))
            elif not (label_shares_surface(display, surfaces)
                      or binds_common_name(owner, display)
                      or cross_domain_synonym_label(
                          display, surfaces, prose_of(owner))):
                findings.append(_f(
                    "18-label-target", "warning",
                    "wikilink [[%s|%s]]: the label shares no surface form with "
                    "the target's title %r or its aliases, and the target binds "
                    "no such Organism common name -- likely a wrong target or "
                    "an invented label"
                    % (link["target"], display, target["title"]), evidence))
            else:
                head = label_drops_head(
                    display, target["title"], list(target.get("aliases", [])),
                    prose_of(owner))
                if head and not binds_common_name(owner, display):
                    findings.append(_f(
                        "18-partial-label", "warning",
                        "wikilink [[%s|%s]]: the label keeps only modifiers of "
                        "the target's title %r and omits its head word %r -- "
                        "reword so the label names the target (its title, an "
                        "alias, an inflection or a derived form), or review "
                        "whether it names a different entity; do not "
                        "auto-retarget"
                        % (link["target"], display, target["title"], head),
                        dict(evidence, head=head)))
        result["findings"] = findings


def lint_path(target, severity_floor=None):
    """Lint a single entry file or a whole folder (recursively)."""
    target = os.path.abspath(target)
    report = {"root": target, "entries": [], "alias_collisions": [],
              "summary": {}, "problems": []}

    if os.path.isdir(target):
        def walk_error(exc):
            report["problems"].append("unreadable wiki directory: %s" % exc)
        paths = iter_markdown_files(target, on_error=walk_error)
        folder_mode = True
    elif os.path.isfile(target):
        paths = [target]
        folder_mode = False
    else:
        report["problems"].append("no such file or folder: %s" % target)
        report["summary"] = {"files": 0, "files_with_findings": 0,
                             "findings": 0, "by_severity": {}, "by_item": {},
                             "clean": False}
        return report

    # Cross-file checks consume the exact guarded reads used above. Reopening
    # a path could follow a later symlink or mix a newer body with old metadata.
    snapshot_text = {}
    results = [lint_file(p, _snapshot_text=snapshot_text) for p in paths]
    if folder_mode:
        report["alias_collisions"] = _check_alias_collisions(results)
        _recheck_folder_duplicate_wikilinks(results, target, snapshot_text)
        _check_folder_related_labels(results, target, snapshot_text)
        _check_folder_link_targets(results, target, snapshot_text)

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
        "files_with_findings": sum(1 for r in results if r["findings"]),
        "findings": total,
        "by_severity": dict(sorted(by_severity.items())),
        "by_item": dict(sorted(by_item.items())),
        "clean": total == 0 and not report["problems"],
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
        'description: "A ROC curve plots true positive rate against false '
        'positive rate."\n'
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


def _st_precision():
    """A complete second entry for link and folder-level checks."""
    return (
        '---\n'
        'title: "Precision"\n'
        'type: Concept\n'
        'sources:\n'
        '  - "[[Doe_X_2025.pdf#page=2]]"\n'
        'created: 2026-01-01\n'
        'updated: 2026-01-02\n'
        'description: "Precision is the share of predicted positives that are '
        'correct."\n'
        'tags:\n'
        '  - "#statistics"\n'
        'parents: []\n'
        'read: false\n'
        '---\n'
        '**Precision** is the share of predicted positives that are correct.\n'
        '\n**Related:**\n\n---\n\n## Flashcards\n\n'
        'The share of predicted positive cases that are correct.\n??\nPrecision\n')


def _st_decision_threshold():
    """A two-word entry for the head-word display-label check."""
    return (
        '---\n'
        'title: "Decision threshold"\n'
        'type: Concept\n'
        'sources:\n'
        '  - "[[Doe_X_2025.pdf#page=3]]"\n'
        'created: 2026-01-01\n'
        'updated: 2026-01-02\n'
        'description: "A decision threshold is the score cutoff that separates '
        'predicted classes."\n'
        'tags:\n'
        '  - "#statistics"\n'
        'parents: []\n'
        'read: false\n'
        '---\n'
        'A **decision threshold** is the score cutoff that separates predicted '
        'classes.\n'
        '\n**Related:**\n\n---\n\n## Flashcards\n\n'
        'The score cutoff that separates predicted classes.\n??\n'
        'Decision threshold\n')


def _st_label():
    """An entry introducing a cross-domain synonym for the label check."""
    return (
        '---\n'
        'title: "Label (machine learning)"\n'
        'type: Concept\n'
        'sources:\n'
        '  - "[[Doe_X_2025.pdf#page=4]]"\n'
        'created: 2026-01-01\n'
        'updated: 2026-01-02\n'
        'description: "A label is the answer a supervised model learns to '
        'predict."\n'
        'tags:\n'
        '  - "#statistics"\n'
        'parents: []\n'
        'read: false\n'
        '---\n'
        'A **label** is the answer a supervised model learns to predict. The '
        'word *target* is a near-synonym.\n'
        '\n**Related:**\n\n---\n\n## Flashcards\n\n'
        'The answer a supervised model learns to predict.\n??\nLabel\n')


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
    precision = _st_precision()

    def mutate(old, new, base=None):
        base = good if base is None else base
        assert old in base, "self-test fixture drift: %r" % old[:60]
        return base.replace(old, new, 1)

    def items(text, filename="roc-curve.md"):
        return _st_items(lint_text(text, filename))

    def retitled(title, alias, description, opener, card_term, type_="Concept"):
        """A schema-clean variant for title/alias binding regressions."""
        return (good.replace('title: "ROC curve"', 'title: "%s"' % title)
                    .replace('type: Concept', 'type: %s' % type_)
                    .replace('  - "auroc"', '  - "%s"' % alias)
                    .replace(
                        'description: "A ROC curve plots true positive rate '
                        'against false positive rate."',
                        'description: "%s"' % description)
                    .replace(
                        'A **ROC curve** plots the trade-off between two error '
                        'rates as a decision threshold moves.', opener)
                    .replace('\nROC curve\n', '\n%s\n' % card_term))

    check("the clean fixture produces NO finding at any severity",
          items(good), [])
    for opening, closing in (("<!--", "-->"), ("%%", "%%")):
        hidden = (opening + "\n## Flashcards\n**Related:** [[ghost]]\n"
                  "```\n" + closing + "\n\n")
        commented = good.replace("**Related:**", hidden + "**Related:**", 1)
        check("hidden section markers do not create phantom cards: " + opening,
              items(commented), [])
        between_sections = good.replace("\n---\n\n## Flashcards", "\n" + hidden
                                        + "---\n\n## Flashcards", 1)
        check("a hidden template after the footer is not stray content: " + opening,
              items(between_sections), [])
        # A duplicate inside a comment is not a second rendered occurrence.
        duplicated = good.replace("**Related:**", opening + " [[precision]] "
                                  + closing + "\n\n**Related:**", 1)
        check("hidden links cannot trigger duplicate repairs: " + opening,
              items(duplicated), [])
    check("CRLF and LF entries have the same lint result",
          items(good.replace("\n", "\r\n")), [])
    check("the complete second entry passes ordinary validation",
          items(precision, "precision.md"), [])
    check("empty source lists retain their mandatory-provenance finding",
          [items(mutate('sources:\n  - "[[Doe_X_2025.pdf#page=2]]"\n', replacement))
           for replacement in ("sources:\n", "sources: []\n")],
          [["2-field-order"], ["2-field-order"]])
    check("plain placeholder provenance fails the ordinary source rule",
          items(mutate("[[Doe_X_2025.pdf#page=2]]", "placeholder")),
          ["4-sources"])
    check("invalid provenance does not waive the normal footer and card requirements",
          items(mutate("[[Doe_X_2025.pdf#page=2]]", "placeholder")
                .split("\n**Related:**", 1)[0] + "\n"),
          ["11-related-footer", "19-flashcards", "4-sources"])
    check("numeric inline math is not mistaken for currency",
          [_literal_dollar_count(value) for value in (
              r"The rank satisfies $1 \le k \le m$.",
              r"The probability obeys $0 < p < 1$.",
              r"The fraction approaches $1-e^{-1}$.")],
          [0, 0, 0])
    check("two currency amounts remain two literal dollars",
          _literal_dollar_count("The price ranges from $20 to $30."), 2)
    raw_description = mutate(
        'description: "A ROC curve plots true positive rate against false '
        'positive rate."',
        'description: "A ROC curve compares outcomes under an ℓ1 distance."')
    check("raw ell notation in a YAML description gets a plain-word remedy",
          [(f["item"], "ell-one" in f["message"])
           for f in lint_text(raw_description, "roc-curve.md")["findings"]],
          [("12-equation-typography", True)])
    raw_card = mutate(
        "The plot tracing the trade-off between two error rates as a decision "
        "threshold moves.",
        "A plot measured under an ℓ1 distance.")
    check("raw ell notation in a card prompt gets an inline-LaTeX remedy",
          [(f["item"], "$\\ell_1$" in f["message"])
           for f in lint_text(raw_card, "roc-curve.md")["findings"]],
          [("12-equation-typography", True)])
    raw_prose = mutate(
        "decision threshold moves.\n",
        "decision threshold moves. It uses an ℓ2 distance.\n")
    check("raw ell notation in prose gets an inline-LaTeX remedy",
          items(raw_prose), ["12-equation-typography"])
    raw_micro_card = mutate(
        "The plot tracing the trade-off between two error rates as a decision "
        "threshold moves.",
        "A specimen is 10 µm wide.")
    check("raw micro-sign units in a card get an inline-LaTeX remedy",
          [(f["item"], "$\\mu\\mathrm{m}$" in f["message"])
           for f in lint_text(raw_micro_card, "roc-curve.md")["findings"]],
          [("12-equation-typography", True)])
    raw_micro_prose = mutate(
        "decision threshold moves.\n",
        "decision threshold moves. A specimen is 10 μm wide.\n")
    check("raw Greek-mu units in prose get an inline-LaTeX remedy",
          items(raw_micro_prose), ["12-equation-typography"])
    unicode_micro_description = mutate(
        'description: "A ROC curve plots true positive rate against false '
        'positive rate."',
        'description: "A ROC curve depicts features at a 10 μm scale."')
    check("a description keeps its documented plain-Unicode allowance",
          items(unicode_micro_description), [])
    numeric_math = mutate(
        "decision threshold moves.\n",
        r"decision threshold moves. Its rank satisfies $1 \le k \le m$." + "\n")
    check("a complete entry accepts numeric inline math",
          items(numeric_math), [])
    currency_pair = mutate(
        "decision threshold moves.\n",
        "decision threshold moves. It costs $20 to $30.\n")
    check("a complete entry reports both literal currency signs",
          [(f["item"], f["message"].startswith("2 unescaped"))
           for f in lint_text(currency_pair, "roc-curve.md")["findings"]],
          [("12-literal-dollar", True)])
    writing_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "references", "writing.md")
    with open(writing_path, encoding="utf-8") as writing_handle:
        writing_text = writing_handle.read()
    complete_example = re.search(
        r'```markdown\n(---\ntitle: "LambdaRank".*?\n)```',
        writing_text, re.DOTALL)
    check("writing.md exposes the complete LambdaRank example",
          complete_example is not None, True)
    if complete_example is not None:
        check("the documented complete entry passes the actual linter",
              items(complete_example.group(1), "lambdarank.md"), [])
        two_card_example = re.sub(
            r"## Flashcards\n\n.*\Z",
            "## Flashcards\n\n"
            "The learning-to-rank method that multiplies each item pair's "
            "RankNet gradient by the NDCG change their swap would cause.\n"
            "??\nLambdaRank\n\n"
            "Why do pairs near the top of a LambdaRank ranking get larger "
            "updates?\n?\nSwapping top positions changes NDCG the most.\n",
            complete_example.group(1), flags=re.DOTALL)
        check("the complete entry with a primary and an understanding card "
              "passes the actual linter",
              items(two_card_example, "lambdarank.md"), [])
    commented = good.replace('title: "ROC curve"', 'title: "ROC curve" # user annotation')
    commented = commented.replace('"auroc"', '"aur\\u006fc" # an escaped alias')
    commented = commented.replace('sources:\n', 'sources: # reference\n# provenance annotation\n')
    commented = commented.replace('read: false', 'read: true # already read')
    check("valid YAML escapes and comments do not cause metadata or body repairs",
          items(commented), [])
    for raw in ('"Malformed "yaml""', '"bad\\q"'):
        bad = lint_text(mutate('title: "ROC curve"', 'title: ' + raw), 'roc-curve.md')
        check("malformed YAML produces a validity finding rather than a fabricated title",
              "1-valid-yaml" in _st_items(bad), True)
    check("flow lists with leading, middle, or trailing empty elements are invalid YAML",
          ["1-valid-yaml" in items(mutate(
              'aliases:\n  - "auroc"\n', 'aliases: [' + raw + ']\n'))
           for raw in (',"auroc"', '"auroc",,"roc"', '"auroc",,')],
          [True] * 3)
    check("a key without a space after its colon is invalid YAML",
          "1-valid-yaml" in items(mutate('title: "ROC curve"',
                                         'title:"ROC curve"')), True)
    for raw in ('null', '~'):
        bad = lint_text(mutate('title: "ROC curve"', 'title: ' + raw), 'roc-curve.md')
        check("a null title never creates a rename target",
              (bad['title'], any((f.get('evidence') or {}).get('expected_filename')
                                for f in bad['findings'])), (None, False))
    pair = lint_text(mutate('  - "[[Doe_X_2025.pdf#page=2]]"\n',
                            '  - "[[Doe_X_2025.pdf#page=2]]"\n  - "[[Doe_X_2025.md]]"\n'),
                     'roc-curve.md')
    pair_findings = [f for f in pair['findings'] if f['item'] == '4-duplicate-source']
    check("same-stem provenance has no deletion instruction or deletion payload",
          [(f['severity'], f['evidence'].get('review_only'), 'delete' in f['evidence'])
           for f in pair_findings], [('warning', True, False)])

    review_base = good.replace('read: false', 'read: true').replace(
        '\n??\n', '\n!!\n')
    review_cards = (
        ("next-line",
         review_base.rstrip('\n') + '\n'
         + '<!--SR:!2026-09-20,30,250!2026-09-21,31,250-->\n'
           '<!--SR:preserved-state-->\n'),
        ("multiline next-line",
         review_base.rstrip('\n') + '\n'
         + '<!--SR:\n!2026-09-20,30,250\n\n!2026-09-21,31,250\n-->\n'),
        ("same-line plus block ID",
         review_base.replace(
             '\nROC curve\n',
             '\nROC curve <!--SR:!2026-09-20,30,250--> ^roc-card\n')),
        ("next-line plus term block ID",
         review_base.replace('\nROC curve\n', '\nROC curve ^roc-card\n')
         .rstrip('\n') + '\n<!--SR:!2026-09-20,30,250-->\n'),
        ("metadata callout plus block ID",
         review_base.rstrip('\n') + '\n'
         + '> [!sr|card-metadata] \n'
           '>  <!--SR:!2026-09-20,30,250--> ^roc-card\n'),
    )
    for storage_form, studied in review_cards:
        before_bytes = studied.encode('utf-8')
        studied_result = lint_text(studied, 'roc-curve.md')
        check("protected %s state is not extra card content" % storage_form,
              _st_items(studied_result), [])
        check("checking %s state preserves every source byte" % storage_form,
              studied.encode('utf-8'), before_bytes)
        extra = studied + '\nA different main claim.\n??\nAnother term\n'
        check("%s state does not hide a genuine extra card" % storage_form,
              any(f.get('evidence', {}).get('cards') == 2
                  for f in lint_text(extra, 'roc-curve.md')['findings']
                  if isinstance(f.get('evidence'), dict)), True)
    why_card = ("Why does raising the decision threshold lower recall?\n?\n"
                "Fewer instances are predicted positive, so more actual "
                "positives are missed.\n")
    why_answer = ("\nFewer instances are predicted positive, so more actual "
                  "positives are missed.")
    review_why = review_base.rstrip('\n') + '\n\n' + why_card
    for storage_form, studied in (
            ("next-line",
             review_why + '<!--SR:!2026-09-20,30,250!2026-09-21,31,250-->\n'
                          '<!--SR:preserved-state-->\n'),
            ("multiline next-line",
             review_why + '<!--SR:\n!2026-09-20,30,250\n\n'
                          '!2026-09-21,31,250\n-->\n'),
            ("same-line plus block ID",
             review_why.replace(why_answer, why_answer
                                + ' <!--SR:!2026-09-20,30,250--> ^why-card')),
            ("next-line plus answer block ID",
             review_why.replace(why_answer, why_answer + ' ^why-card')
             + '<!--SR:!2026-09-20,30,250-->\n'),
            ("metadata callout plus block ID",
             review_why + '> [!sr|card-metadata] \n'
                          '>  <!--SR:!2026-09-20,30,250--> ^why-card\n')):
        before_bytes = studied.encode('utf-8')
        check("protected %s state on an understanding card is not extra "
              "card content" % storage_form,
              _st_items(lint_text(studied, 'roc-curve.md')), [])
        check("checking %s state on an understanding card preserves every "
              "source byte" % storage_form,
              studied.encode('utf-8'), before_bytes)
    check("a blank detaches next-line state from an understanding card too",
          _st_items(lint_text(review_why + '\n<!--SR:detached-after-blank-->\n',
                              'roc-curve.md')), ["19-flashcards"])
    detached = review_base + '\n<!--SR:detached-after-blank-->\n'
    check("a blank detaches next-line state so item 19 can report it",
          "19-flashcards" in _st_items(
              lint_text(detached, 'roc-curve.md')), True)
    unterminated = (review_base.rstrip('\n')
                    + '\n<!--SR:unterminated-state\n')
    check("an unterminated attached SR comment remains reportable content",
          "19-flashcards" in _st_items(
              lint_text(unterminated, 'roc-curve.md')), True)
    for fence in ('```', '~~~'):
        example = good.replace('\n**Related:**',
                               '\n' + fence + 'text\n' + fence + 'not-a-close\n'
                               '[[precision]]\n' + fence + '\n\n[[precision]]\n\n**Related:**')
        check("a closing code fence may not carry trailing text: %s" % fence,
              [f for f in lint_text(example, 'roc-curve.md')['findings']
               if f['item'] in ('10-duplicate-wikilink', '19-flashcards')], [])

    for alias, surface in (("covariate", "covariates"), ("hypothesis", "hypotheses")):
        alias_text = mutate('"auroc"', json.dumps(alias)).replace(
            "\n**Related:**", "\nIt is also called *%s*.\n\n**Related:**" % surface)
        check("a plural of an existing alias is not a missing alias: %s" % surface,
              items(alias_text), [])
    check("a genuinely different introduced name is still flagged",
          items(good.replace("\n**Related:**", "\nIt is also called *operating curve*.\n\n**Related:**")),
          ["17-alias-completeness"])

    # Invalid provenance and review state used to pass the creation gate.
    for source in ("[[Doe_X_2025.pdf]]", "[[Doe_X_2025.pdf#page=0]]",
                   "[[Doe_X_2025.pdf#page=01]]",
                   "[[Doe_X_2025.pdf#page=1garbage]]",
                   "https://example.test/Doe_X_2025.pdf#page=1",
                   "Doe_X_2025.pdf#page=1", "[[Note.md#Heading]]"):
        check("reject malformed source %s" % source,
              items(mutate("[[Doe_X_2025.pdf#page=2]]", source)), ["4-sources"])
    check("a valid markdown source has no page anchor",
          items(mutate("[[Doe_X_2025.pdf#page=2]]", "[[Note.md]]")), [])
    check("a source scalar is not a sources list",
          items(mutate('sources:\n  - "[[Doe_X_2025.pdf#page=2]]"',
                       'sources: "[[Doe_X_2025.pdf#page=2]]"')), ["4-sources"])
    for raw in ("null", "~", "", "banana", "[]", "[true, false]", '"banana"'):
        result = lint_text(mutate("read: false", "read: " + raw), "roc-curve.md")
        check("unknown read state is report-only: %r" % raw,
              [(f["item"], f["evidence"].get("report_only")) for f in result["findings"]],
              [("2-read-state", True)])
    for raw in ("yes", "no", "0", "1"):
        result = lint_text(mutate("read: false", "read: " + raw), "roc-curve.md")
        check("known read answer may be re-spelled: %s" % raw,
              [(f["item"], f["evidence"].get("report_only")) for f in result["findings"]],
              [("2-read-state", False)])

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
    check("a missing read key is report-only user state",
          [(f["item"], f["severity"], f["evidence"].get("report_only"))
           for f in lint_text(mutate("read: false\n", ""),
                              "roc-curve.md")["findings"]],
          [("2-read-state", "info", True)])
    check("an off-schema key is a WARNING, not an error",
          [(f["item"], f["severity"])
           for f in lint_text(mutate("read: false\n", "mood: bright\nread: false\n"),
                              "roc-curve.md")["findings"]],
          [("2-field-order", "warning")])
    obsidian_fields = (
        "cssclasses: wide\ncssclass: legacy\npublish: true\n"
        "permalink: /roc\ncover: cover.png\nimage: image.png\n"
        "banner: banner.png\nicon: chart\n")
    obsidian_findings = lint_text(
        mutate("read: false\n", obsidian_fields + "read: false\n"),
        "roc-curve.md")["findings"]
    check("all Obsidian-owned appearance/publish keys are report-only and "
          "never schema-cleanup findings",
          [(f["item"], f["severity"], f["evidence"].get("report_only"))
           for f in obsidian_findings],
          [("2-obsidian-key", "info", True)] * len(OBSIDIAN_KEYS))
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
    check("an exact duplicate source citation is rejected",
          items(mutate(
              'sources:\n  - "[[Doe_X_2025.pdf#page=2]]"\n',
              'sources:\n  - "[[Doe_X_2025.pdf#page=2]]"\n'
              '  - "[[Doe_X_2025.pdf#page=2]]"\n')),
          ["4-sources"])
    check("type: off the 15-value enum",
          items(mutate("type: Concept", "type: Widget")), ["2-type-enum"])
    # `type:` present-but-blank is a 2-type-enum finding only: the KEY is
    # there, so the mandatory-key check has nothing to say about it.
    check("type: blank", items(mutate("type: Concept", "type:")), ["2-type-enum"])
    check("a lossless plain title is accepted after an Obsidian Properties edit",
          items(mutate('title: "ROC curve"', "title: ROC curve")), [])
    check("typed, numeric, and timestamp-like plain titles still require quotes",
          ["2-quoting" in items(mutate(
              'title: "ROC curve"', "title: " + value))
           for value in ("true", "0x10", "0o10", "0b10", "0123", ".5",
                         "12:34:56", "2026-09-03T10:00:00Z")],
          [True] * 8)
    check("a lossless plain alias is accepted after a Properties edit",
          items(mutate('  - "auroc"', "  - auroc")), [])
    check("type: quoted (it is a bare enum value)",
          items(mutate("type: Concept", 'type: "Concept"')), ["2-quoting"])
    check("read: quoted -- the string Obsidian renders as permanently checked",
          items(mutate("read: false", 'read: "false"')), ["2-quoting"])
    check("a single-quoted list item",
          items(mutate('  - "auroc"', "  - 'auroc'")), ["2-quoting"])
    check("a scalar aliases field is rejected even when its value is a valid slug",
          items(mutate('aliases:\n  - "auroc"\n', 'aliases: "auroc"\n')),
          ["18-alias-form"])
    check("a bare aliases key is not an empty list",
          items(mutate('aliases:\n  - "auroc"\n', 'aliases:\n')),
          ["18-alias-form"])
    check("an explicitly empty flow aliases list has list shape",
          items(mutate('aliases:\n  - "auroc"\n', 'aliases: []\n')), [])
    check("an UNQUOTED #tag, which YAML reads as a comment",
          items(mutate('  - "#statistics"', "  - #statistics")),
          ["1-valid-yaml", "2-quoting", "8-tags"])

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
          [source_stem(s) for s in ('"placeholder"', "[[Sources/PDFs/Doe_X_2025.pdf#page=2]]",
                                    "[[doe_x_2025.md|label]]")],
          [("", ""), ("doe_x_2025", "pdf"), ("doe_x_2025", "md")])

    # -- item 5: slug ------------------------------------------------------
    check("the filename does not match slug(title:)",
          items(good, "roc-curves.md"), ["5-slug"])
    check("a title that cannot be slugged at all",
          sorted(set(items(mutate('title: "ROC curve"', 'title: "機械学習"'),
                           "roc-curve.md"))),
          # 19-flashcards is real fallout: only the title was mutated, so card
          # line 3 ("ROC curve") and the description subject genuinely no
          # longer match it
          ["16-bold-opener", "19-flashcards", "5-slug", "7-description"])

    # -- item 7: description ----------------------------------------------
    check("a blank description",
          items(mutate('description: "A ROC curve plots true positive rate '
                       'against false positive rate."', 'description: ""')),
          ["7-description"])
    check("a description over the 110-character cap",
          items(mutate("false positive rate.", "false positive rate, written "
                       "out at rather more length than the hundred and ten "
                       "characters the rule allows.")),
          ["7-description"])
    check("markup in a description",
          items(mutate("plots true", "plots `true`")), ["7-description"])
    check("Markdown links, underscore emphasis, HTML, strikethrough, "
          "footnotes, tags, highlights, and comments are non-plain "
          "description markup",
          [items(mutate("plots true", replacement)) for replacement in (
              "plots [true](https://example.test)",
              "plots [true][target]",
              "plots _true_",
              "plots <em>true</em>",
              "plots ~~true~~",
              "plots true[^1]",
              "plots #true",
              "plots ==true==",
              "plots %%true%%",
          )],
          [["7-description"]] * 9)
    check("a description with no closing period is an error in both linters",
          [(f["item"], f["severity"])
           for f in lint_text(mutate("false positive rate.", "false positive rate"),
                              "roc-curve.md")["findings"]],
          [("7-description", "error")])
    check("two declarative or question-ended description sentences are rejected",
          (items(mutate(
              'description: "A ROC curve plots true positive rate against '
              'false positive rate."',
              'description: "A ROC curve plots rates. It compares errors."')),
           items(mutate(
              'description: "A ROC curve plots true positive rate against '
              'false positive rate."',
              'description: "A ROC curve asks why? It compares errors."'))),
          (["7-description"], ["7-description"]))
    check("decimals, versions, initials, abbreviations, and taxonomic ranks do not create phantom description sentences",
          [items(mutate(
              'description: "A ROC curve plots true positive rate against '
              'false positive rate."', replacement))
           for replacement in (
               'description: "A ROC curve reports 3.5 percent error."',
               'description: "A ROC curve covers GPT-4.5 behavior."',
               'description: "A ROC curve follows work by B. F. Skinner."',
               'description: "A ROC curve operates in the U.S."',
               'description: "A ROC curve compares Brassica var. capitata."')],
          [[]] * 5)
    check("a lowercase-initial description is exempt when the TITLE is one",
          items(mutate('title: "ROC curve"\n', 'title: "k-nearest neighbors"\n')
                .replace("A **ROC curve** plots", "**k-nearest neighbors** plots")
                .replace('description: "A ROC curve plots',
                         'description: "k-nearest neighbors plots')
                .replace("ROC curve\n", "k-nearest neighbors\n"),
                "k-nearest-neighbors.md"),
          [])
    check("a mathematical title's plain form is its description subject",
          items(mutate('title: "ROC curve"\n', 'title: "$k$-fold"\n')
                .replace("A **ROC curve** plots", "A **k-fold** plots")
                .replace('description: "A ROC curve plots',
                         'description: "k-fold plots')
                .replace("ROC curve\n", "k-fold\n"), "k-fold.md"),
          [])
    check("a first-letter case difference still names the canonical subject",
          _description_has_entity_subject("ArXiv stores preprints.", "arXiv"), True)
    check("a parenthetical title accepts its base term after a leading article",
          _description_has_entity_subject(
              "A feature supplies a model input.", "Feature (machine learning)"),
          True)
    check("a parenthetical title does not use its qualifier in running prose",
          _description_has_entity_subject(
              "Feature (machine learning) supplies a model input.",
              "Feature (machine learning)"), False)
    check("a placeholder subject is not the entry entity",
          _description_has_entity_subject("This method compares groups.", "Fairness"),
          False)
    check("a different prefixed noun phrase cannot hide the title later in it",
          _description_has_entity_subject(
              "Machine learning fairness compares group outcomes.", "Fairness"),
          False)
    check("a title prefix must end at a subject boundary",
          _description_has_entity_subject(
              "Fairness-aware learning compares group outcomes.", "Fairness"),
          False)
    check("the clear placeholder mismatch is emitted as item 7",
          items(mutate(
              'description: "A ROC curve plots true positive rate against '
              'false positive rate."',
              'description: "This method plots true positive rate."')),
          ["7-description"])

    # -- item 8: tags ------------------------------------------------------
    check("a tag with no # prefix",
          items(mutate('  - "#statistics"', '  - "statistics"')), ["8-tags"])
    check("a tag outside the discipline enum",
          items(mutate('  - "#statistics"', '  - "#astrology"')), ["8-tags"])
    check("a flow-form tags list is rejected even when its value is valid",
          items(mutate('tags:\n  - "#statistics"\n',
                       'tags: ["#statistics"]\n')), ["8-tags"])
    check("a scalar tags value is rejected even when its value is valid",
          items(mutate('tags:\n  - "#statistics"\n',
                       'tags: "#statistics"\n')), ["8-tags"])
    check("blank and empty-list tags require a discipline or fallback",
          [items(mutate('tags:\n  - "#statistics"\n', replacement))
           for replacement in ("tags:\n", "tags: []\n")],
          [["8-tags"], ["8-tags"]])
    check("the sole misc fallback is a valid discipline tag",
          items(mutate('  - "#statistics"', '  - "#misc"')), [])
    check("misc cannot coexist with a specific discipline or duplicate itself",
          [items(mutate('  - "#statistics"', replacement))
           for replacement in ('  - "#misc"\n  - "#statistics"',
                               '  - "#statistics"\n  - "#misc"',
                               '  - "#misc"\n  - "#misc"')],
          [["8-tags"]] * 3)
    check("multiple specific disciplines violate the single-home rule",
          items(mutate('  - "#statistics"',
                       '  - "#statistics"\n  - "#mathematics"')), ["8-tags"])
    check("missing tags remain a mandatory-field error",
          items(mutate('tags:\n  - "#statistics"\n', "")),
          ["2-field-order"])
    check("null and scalar tag values remain tag errors",
          ["8-tags" in items(mutate('tags:\n  - "#statistics"\n', replacement))
           for replacement in ("tags: null\n", 'tags: ""\n',
                               'tags: "#misc"\n', "tags:\n  - null\n")],
          [True] * 4)

    # -- item 10: duplicate wikilinks --------------------------------------
    check("the same target linked twice in prose, under two labels",
          items(mutate("decision threshold moves.\n",
                       "decision threshold moves, per [[precision]] "
                       "and [[precision|the positive predictive value]].\n")),
          ["10-duplicate-wikilink"])
    check("...counted by TARGET, so one link plus the Related footer is fine",
          items(mutate("decision threshold moves.\n",
                       "decision threshold moves, per [[precision]].\n")),
          [])
    check("an exact body display alias is redundant",
          items(mutate("decision threshold moves.\n",
                       "decision threshold moves, per "
                       "[[precision|precision]].\n")),
          ["10-redundant-pipe"])
    check("the mandatory piped Related form is outside the body-only check",
          items(mutate("[[precision|Precision]]", "[[precision|precision]]")),
          [])
    check("an unpiped Related link is an error even in single-file mode",
          items(mutate("[[precision|Precision]]", "[[precision]]")),
          ["11-related-display"])
    check("a ^block anchor is stripped, so the same target twice is still a dup",
          items(mutate("decision threshold moves.\n",
                       "decision threshold moves, per [[precision|p]] and "
                       "[[precision^init|q]].\n")),
          ["10-duplicate-wikilink"])
    check("repeated explicit MOC navigation is not a duplicate entry link",
          items(mutate("decision threshold moves.\n",
                       "decision threshold moves; navigation uses "
                       "[[MOCs/statistics]] and [[mocs/STATISTICS.md#Methods]].\n")),
          [])

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
    check("a whitespace-only blank line ends the opener paragraph",
          items(mutate(
              "A **ROC curve** plots the trade-off between two error rates "
              "as a decision threshold moves.",
              "A ROC curve plots a trade-off.\n   \n"
              "Later prose names **ROC curve** explicitly.")),
          ["16-bold-opener", "16-unenumerated-bold"])
    check("the parenthetical base-term carve-out",
          items(mutate('title: "ROC curve"', 'title: "ROC curve (statistics)"')
                .replace("ROC curve\n??", "ROC curve\n??"),
                "roc-curve-statistics.md"), [])
    check("the full parenthetical title is invalid in the body opener",
          items(mutate('title: "ROC curve"', 'title: "ROC curve (statistics)"')
                .replace("A **ROC curve** plots",
                         "A **ROC curve (statistics)** plots"),
                "roc-curve-statistics.md"), ["16-bold-opener"])
    check("the math-title plain-form carve-out",
          items(mutate('title: "ROC curve"', 'title: "$k$-fold"')
                .replace("A **ROC curve** plots", "A **k-fold** plots")
                .replace("A ROC curve plots", "k-fold plots")
                .replace("ROC curve\n", "k-fold\n"), "k-fold.md"), [])

    work_title = retitled(
        "Hamlet", "tragedy-of-hamlet", "Hamlet is a tragedy by Shakespeare.",
        "***Hamlet*** is a tragedy by Shakespeare.", "Hamlet", type_="Work")
    check("a Work title combines bold and italics on first appearance",
          items(work_title, "hamlet.md"), [])
    check("a Work title in bold alone is rejected",
          items(work_title.replace("***Hamlet***", "**Hamlet**"), "hamlet.md"),
          ["16-bold-opener"])
    check("an over-emphasized Work title is rejected rather than substring-matched",
          items(work_title.replace("***Hamlet***", "****Hamlet****"), "hamlet.md"),
          ["16-bold-opener"])
    binomial_title = retitled(
        "Mus musculus", "m-musculus",
        "Mus musculus is the laboratory mouse.",
        "***Mus musculus*** is the laboratory mouse.", "Mus musculus",
        type_="Organism")
    check("a Latin-binomial Organism title combines bold and italics",
          items(binomial_title, "mus-musculus.md"), [])
    check("a Latin-binomial Organism title in bold alone is rejected",
          items(binomial_title.replace("***Mus musculus***", "**Mus musculus**"),
                "mus-musculus.md"), ["16-bold-opener"])
    qualified_binomial = retitled(
        "Mus musculus (biology)", "m-musculus",
        "Mus musculus is the laboratory mouse.",
        "***Mus musculus*** is the laboratory mouse.", "Mus musculus",
        type_="Organism")
    check("an Organism disambiguation qualifier stays outside running prose styling",
          items(qualified_binomial, "mus-musculus-biology.md"), [])
    common_title = retitled(
        "House mouse", "laboratory-mouse", "House mouse is a small rodent.",
        "**House mouse** is a small rodent.", "House mouse", type_="Organism")
    check("a common-name Organism title remains bold-only",
          items(common_title, "house-mouse.md"), [])
    african_elephant = retitled(
        "African elephant", "savanna-elephant",
        "African elephant is a large land mammal.",
        "**African elephant** is a large land mammal.", "African elephant",
        type_="Organism")
    check("a two-word common-name Organism is not guessed to be a binomial",
          items(african_elephant, "african-elephant.md"), [])
    ambiguous_taxon = retitled(
        "Pan troglodytes", "chimpanzee",
        "Pan troglodytes is a great ape.",
        "**Pan troglodytes** is a great ape.", "Pan troglodytes",
        type_="Organism")
    check("an evidence-poor taxon-shaped Organism is silent at the mechanical floor",
          items(ambiguous_taxon, "pan-troglodytes.md"), [])
    check("either plausible style stays mechanically quiet for a source-aware decision",
          items(ambiguous_taxon.replace("**Pan troglodytes**",
                                        "***Pan troglodytes***"),
                "pan-troglodytes.md"), [])
    rank_marked = retitled(
        "Brassica oleracea var. capitata", "cabbage",
        "Brassica oleracea var. capitata is a cultivated taxon.",
        "***Brassica oleracea* var. *capitata*** is a cultivated taxon.",
        "Brassica oleracea var. capitata", type_="Organism")
    check("a rank-marked title can use discontiguous italics without a false title mismatch",
          items(rank_marked, "brassica-oleracea-var-capitata.md"), [])
    genus_title = retitled(
        "Didinium", "predatory-ciliate",
        "Didinium is a predatory ciliate.",
        "***Didinium*** is a predatory ciliate.", "Didinium",
        type_="Organism")
    check("a genus-only title remains a silent source-aware typography judgment",
          items(genus_title, "didinium.md"), [])
    trinomial_title = retitled(
        "Canis lupus familiaris", "c-lupus-familiaris",
        "Canis lupus familiaris is the domestic dog.",
        "***Canis lupus familiaris*** is the domestic dog.",
        "Canis lupus familiaris", type_="Organism")
    check("a lowercase infraspecific epithet stays inside the italic taxon",
          items(trinomial_title, "canis-lupus-familiaris.md"), [])
    check("treating an infraspecific epithet as a plain strain suffix fails",
          items(trinomial_title.replace("***Canis lupus familiaris***",
                                       "***Canis lupus* familiaris**"),
                "canis-lupus-familiaris.md"), ["16-bold-opener"])
    mixed_title = retitled(
        "E. coli K-12", "k-12", "E. coli K-12 is a laboratory strain.",
        "***E. coli* K-12** is a laboratory strain.", "E. coli K-12",
        type_="Organism")
    check("a strain-bearing Organism title italicizes only the taxon",
          items(mixed_title, "e-coli-k-12.md"), [])
    check("italicizing the strain designator is rejected",
          items(mixed_title.replace("***E. coli* K-12**", "***E. coli K-12***"),
                "e-coli-k-12.md"), ["16-bold-opener"])
    symbol_star = retitled(
        "$A^{*}$ search", "astar", "A-star search is a graph algorithm.",
        "**$\\boldsymbol{A}^{*}$ search** is a graph algorithm.",
        "A-star search")
    check("a LaTeX star remains semantic in the description, opener, and card",
          items(symbol_star, "a-star-search.md"), [])
    check("the former lossy A-search card spelling is rejected",
          items(symbol_star.replace("??\nA-star search\n", "??\nA search\n"),
                "a-star-search.md"),
          ["19-flashcards"])
    check("LaTeX A-star notation cannot hide a flashcard answer leak",
          items(symbol_star.replace(
              "The plot tracing",
              "An $A^{*}$ search algorithm tracing"),
              "a-star-search.md"),
          ["19-flashcard-leak"])
    chi_squared = retitled(
        "$\\\\chi^2$ test", "chi-square-test",
        "chi-squared test compares observed and expected categorical counts.",
        "**$\\chi^2$ test** compares observed and expected categorical counts.",
        "chi-squared test")
    check("the documented LaTeX chi-squared title has one readable plain form",
          items(chi_squared, "chi-2-test.md"), [])
    check("a non-mathematical Greek title answers verbatim",
          items(retitled("TNF-α", "tnf", "TNF-α is a worked example.",
                         "**TNF-α** is a worked example.", "TNF-α"),
                "tnf-alpha.md"), [])
    ell_one = retitled(
        "$\\\\ell_1$ norm", "l1-norm",
        "ell-one norm measures vector magnitude using absolute values.",
        "**$\\ell_1$ norm** measures vector magnitude using absolute values.",
        "ell-one norm")
    check("an ell-one subscript stays semantic across title fields",
          items(ell_one, "ell-1-norm.md"), [])
    inverse_title = retitled(
        "$L^{-1}$ regularization", "inverse-regularization",
        "L-inverse regularization is a worked mathematical example.",
        "**$L^{-1}$ regularization** is a worked mathematical example.",
        "L-inverse regularization")
    check("an inverse exponent stays semantic across title fields",
          items(inverse_title, "l-1-regularization.md"), [])
    half_power = retitled(
        "$x^{1/2}$ transform", "half-power-transform",
        "x-to-the-one-half transform is a worked mathematical example.",
        "**$x^{1/2}$ transform** is a worked mathematical example.",
        "x-to-the-one-half transform")
    check("a one-half exponent stays semantic across title fields",
          items(half_power, "x-1-2-transform.md"), [])
    positive_superscript = retitled(
        "$R^{+}$", "positive-r",
        "R-plus is a worked mathematical example.",
        "**$R^{+}$** is a worked mathematical example.",
        "R-plus")
    check("a positive superscript stays semantic across title fields",
          items(positive_superscript, "r-plus.md"), [])
    check("bare known special tokens and literal extensions require backticks",
          (items(mutate("decision threshold moves.\n",
                        "decision threshold moves using [CLS].\n")),
           items(mutate("decision threshold moves.\n",
                        "decision threshold moves in a .csv file.\n"))),
          (["16-code-typography"], ["16-code-typography"]))
    check("backticked special tokens and literal extensions are canonical",
          items(mutate("decision threshold moves.\n",
                       "decision threshold moves using `[CLS]` in a `.csv` "
                       "file.\n")), [])
    check("decimals, domains, and extensions attached to filenames are near misses",
          items(mutate("decision threshold moves.\n",
                       "decision threshold moves by 3.5 at example.com and "
                       "writes results.csv.\n")), [])
    check("wikilink and Markdown-link labels are not literal special tokens",
          items(mutate("decision threshold moves.\n",
                       "decision threshold moves with [[CLS]] and the "
                       "[MASK](https://example.test/token.md) reference.\n")), [])
    check("tables, headings, captions, and listings keep their own typography rules",
          items(mutate("decision threshold moves.\n",
                       "decision threshold moves.\n\n"
                       "## Files named .csv\n\n"
                       "Format | Token\n--- | ---\n.csv | [CLS]\n"
                       "*A .csv lookup table.*\n\n"
                       "```text\n[CLS] .csv\n```\n")),
          # The fence itself is item 6's finding in a non-Software entry.
          ["6-api-surface"])

    # -- item 19: presence, then the answer leak ---------------------------
    check("a entry with NO ## Flashcards section",
          items(mutate("\n---\n\n## Flashcards\n\nThe plot tracing the "
                       "trade-off between two error rates as a decision "
                       "threshold moves.\n??\nROC curve\n", "")),
          ["19-flashcards"])
    check("a ## Flashcards section with no card",
          items(mutate("The plot tracing the trade-off between two error rates "
                       "as a decision threshold moves.\n??\nROC curve\n", "")),
          ["19-flashcards"])
    second_card = mutate(
        "??\nROC curve\n",
        "??\nROC curve\n\nAnother notion, stated briefly.\n??\nSecond idea\n")
    check("a ## Flashcards section with a SECOND card",
          (items(second_card),
           [(f["evidence"]["cards"], f["evidence"].get("report_only"))
            for f in lint_text(second_card, "roc-curve.md")["findings"]]),
          (["19-flashcards"], [(2, True)]))
    check("a ## Flashcards heading with no --- separator above it",
          items(mutate("\n---\n\n## Flashcards", "\n## Flashcards")),
          ["19-flashcards"])
    check("the separator and Flashcards heading each require a following blank line",
          (items(mutate("\n---\n\n## Flashcards", "\n---\n## Flashcards")),
           items(mutate("## Flashcards\n\nThe plot", "## Flashcards\nThe plot"))),
          (["19-flashcards"], ["19-flashcards"]))
    simplified = [f["message"] for f in lint_text(
        mutate("??\nROC curve\n", "?\nROC curve\n"),
        "roc-curve.md")["findings"]]
    check("the only card simplified to `?` is a statement without its "
          "question mark and a set without its `??` primary, never a line-3 "
          "contract finding",
          (len(simplified),
           any("does not end with a question mark" in m for m in simplified),
           any("no `??` primary" in m for m in simplified),
           any("line 3" in m for m in simplified)),
          (2, True, True, False))
    triple = lint_text(mutate("??\nROC curve\n", "???\nROC curve\n"),
                       "roc-curve.md")["findings"]
    check("a line 2 that is no separator names all three",
          [(f["item"], all(sep in f["message"]
                           for sep in ("`??`", "`?`", "`!!`")))
           for f in triple], [("19-flashcards", True)])
    check("a user-disabled `!!` card is preserved, not a line-2 finding",
          items(mutate("??\nROC curve\n", "!!\nROC curve\n")), [])
    check("card line 1 must be one sentence",
          items(mutate(
              "The plot tracing the trade-off between two error rates as a "
              "decision threshold moves.",
              "One identifying statement. Another statement.")),
          ["19-flashcards"])
    check("card line 1 must start with a capitalized word",
          items(mutate(
              "The plot tracing the trade-off between two error rates as a "
              "decision threshold moves.",
              "an identifying statement about two error rates.")),
          ["19-flashcards"])
    check("card line 1 must end with a period",
          items(mutate(
              "The plot tracing the trade-off between two error rates as a "
              "decision threshold moves.",
              "An identifying statement about two error rates")),
          ["19-flashcards"])
    check("a period inside closing quotation marks terminates a card sentence",
          items(mutate(
              "The plot tracing the trade-off between two error rates as a "
              "decision threshold moves.",
              'The plot Hooke might have called "a curve."')),
          [])
    check("punctuation inside inline LaTeX does not split a card sentence",
          items(mutate(
              "The plot tracing the trade-off between two error rates as a "
              "decision threshold moves.",
              r"The value $f(t)=\text{e.g. A or B}$ identifies an operating "
              "point.")),
          [])
    check("Markdown links, emphasis, display math, and HTML are "
          "forbidden on card line 1",
          [items(mutate(
              "The plot tracing the trade-off between two error rates as a "
              "decision threshold moves.", replacement))
           for replacement in (
               "A [linked](target) definition.",
               "A [linked][target] definition.",
               "An _italic_ definition.",
               "A ~~deleted~~ definition.",
               "An <span>HTML</span> definition.",
               "An <!-- hidden --> definition.",
               "An %%hidden%% definition.",
               "[Source]: https://example.com.",
               "A [Source]: https://example.com.",
               "<!--SR:misplaced-->\nA complete definition.",
               "A $$x=1$$ definition.",
               "# A heading definition.",
               "    An indented definition.",
               "A quantity uses $x.",
           )],
          [["19-flashcards"]] * 14)
    check("card line 3 that is not the canonical title",
          items(mutate("??\nROC curve\n", "??\nThe ROC\n")), ["19-flashcards"])
    bound_card = mutate('  - "auroc"', '  - "rc"')
    bound_card = bound_card.replace("A **ROC curve** plots", "A **ROC curve** (RC) plots")
    check("...but the exact title plus its established acronym counterpart is fine",
          items(bound_card.replace("??\nROC curve\n", "??\nROC curve (RC)\n")), [])
    check("compound-derived and shared-tail acronyms remain valid counterparts",
          [_acronym_counterpart(short, long) for short, long in (
              ("ATP", "adenosine triphosphate"),
              ("DNA", "deoxyribonucleic acid"),
              ("RNA", "ribonucleic acid"),
              ("MLOps", "ML operations"),
              ("OOB evaluation", "out-of-bag evaluation"),
          )], [True, True, True, True, True])
    check("an established counterpart is required on line 3",
          items(bound_card), ["19-flashcards"])
    check("an arbitrary line-3 parenthetical is not a counterpart",
          items(mutate("??\nROC curve\n", "??\nROC curve (RC)\n")),
          ["19-flashcards"])
    scalar_bound_card = bound_card.replace(
        'aliases:\n  - "rc"\n', 'aliases: "rc"\n').replace(
        "??\nROC curve\n", "??\nROC curve (RC)\n")
    check("a malformed scalar alias cannot establish a card counterpart",
          items(scalar_bound_card), ["18-alias-form", "19-flashcards"])
    check("line 3 preserves the canonical title's casing",
          items(mutate("??\nROC curve\n", "??\nroc curve\n")),
          ["19-flashcards"])
    singular_alias = good.replace('title: "ROC curve"', 'title: "Archaea"')
    singular_alias = singular_alias.replace('  - "auroc"', '  - "archaeon"')
    singular_alias = singular_alias.replace(
        'description: "A ROC curve plots true positive rate against false positive rate."',
        'description: "Archaea is a domain of single-celled organisms."')
    singular_alias = singular_alias.replace(
        'A **ROC curve** plots the trade-off between two error rates as a decision threshold moves.',
        '**Archaea** (singular, *archaeon*) is a domain of single-celled organisms.')
    singular_alias = singular_alias.replace('\nROC curve\n', '\nArchaea\n')
    check("a singular synonym in an annotated opener parenthetical is not a card counterpart",
          items(singular_alias, "archaea.md"), ["18-alias-form"])
    check("appending that singular synonym to line 3 is rejected",
          items(singular_alias.replace("??\nArchaea\n",
                                       "??\nArchaea (archaeon)\n"),
                "archaea.md"), ["18-alias-form", "19-flashcards"])
    short_for_card = retitled(
        "AdaBoost", "adaptive-boosting",
        "AdaBoost reweights mistakes before fitting each new predictor.",
        "**AdaBoost** (short for *adaptive boosting*) reweights mistakes "
        "before fitting each new predictor.",
        "AdaBoost (adaptive boosting)")
    check("a short-for expansion in the opener establishes the alias-bound "
          "flashcard counterpart",
          items(short_for_card, "adaboost.md"), [])
    originally_called = retitled(
        "Boosting", "hypothesis-boosting",
        "Boosting combines weak learners into a strong learner.",
        "**Boosting** (originally called *hypothesis boosting*) combines weak "
        "learners into a strong learner.", "Boosting")
    check("an originally-called synonym is an alias but not a required card "
          "counterpart",
          items(originally_called, "boosting.md"), [])
    check("an originally-called synonym cannot be appended to card line 3 as "
          "an opener-established counterpart",
          items(originally_called.replace(
              "??\nBoosting\n", "??\nBoosting (hypothesis boosting)\n"),
              "boosting.md"), ["19-flashcards"])
    scientific_card = retitled(
        "Saccharomyces cerevisiae", "s-cerevisiae",
        "Saccharomyces cerevisiae is a model budding yeast.",
        "***Saccharomyces cerevisiae*** (*S. cerevisiae*) is a model budding "
        "yeast.", "Saccharomyces cerevisiae (S. cerevisiae)",
        type_="Organism")
    check("a canonical triple-emphasis Organism opener establishes its direct "
          "italic scientific-abbreviation counterpart",
          items(scientific_card, "saccharomyces-cerevisiae.md"), [])
    knn_card = retitled(
        "k-nearest neighbors", "knn",
        "k-nearest neighbors predicts from nearby observations.",
        "The **k-nearest neighbors** algorithm (KNN) predicts from nearby "
        "observations.", "k-nearest neighbors (KNN)")
    check("the documented intervening algorithm noun preserves an opener "
          "acronym binding",
          items(knn_card, "k-nearest-neighbors.md"), [])
    pseudonym_card = retitled(
        "Mark Twain", "samuel-clemens", "Mark Twain was an American author.",
        "**Mark Twain** (Samuel Clemens) was an American author.", "Mark Twain")
    check("a pseudonym parenthetical is an alias but not an acronym counterpart",
          items(pseudonym_card, "mark-twain.md"), [])
    later_bold_card = retitled(
        "Counterpart scope", "pca",
        "Counterpart scope limits opener-bound flashcard answers.",
        "**Counterpart scope** uses **Principal component analysis** (PCA).",
        "Counterpart scope")
    check("a later bold term cannot donate its parenthetical to the title card",
          [f["item"] for f in lint_text(
              later_bold_card, "counterpart-scope.md")["findings"]
           if f["item"] == "19-flashcards"], [])
    counterpart_after_opener = bound_card.replace(
        "A **ROC curve** (RC) plots the trade-off between two error rates as "
        "a decision threshold moves.",
        "A **ROC curve** plots the trade-off between two error rates as a "
        "decision threshold moves.\n   \nLater, **ROC curve** (RC) is used "
        "as an abbreviation example.")
    check("a counterpart introduced after a whitespace-only paragraph break "
          "does not alter the title card",
          [f["item"] for f in lint_text(
              counterpart_after_opener, "roc-curve.md")["findings"]
           if f["item"] == "19-flashcards"], [])
    check("an unrelated noun phrase and later parenthetical do not bind to "
          "the bolded title",
          bool(_BOLD_PAREN_RE.search(
              "**ROC curve** compares a classifier (RC) across thresholds.")),
          False)
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
    check("slash and Unicode-dash variants cannot hide an alias leak",
          items(mutate('  - "auroc"',
                       '  - "bias-variance-trade-off"')
                .replace("The plot tracing",
                         "The bias/variance trade–off curve tracing")),
          ["19-flashcard-leak"])
    check("a leak inside $...$ is still a leak",
          items(mutate("The plot tracing", "The $\\text{ROC curve}$ tracing")),
          ["19-flashcard-leak"])
    math_answer_card = retitled(
        "$k$-nearest neighbors", "nearest-neighbor-rule",
        "k-nearest neighbors predicts from nearby observations.",
        "**$\\boldsymbol{k}$-nearest neighbors** predicts from nearby "
        "observations.", "k-nearest neighbors")
    check("a math-title answer leaks through its plain line-3 skeleton",
          items(math_answer_card.replace(
              "The plot tracing", "A k-nearest neighbors method tracing"),
              "k-nearest-neighbors.md"), ["19-flashcard-leak"])
    check("math delimiters cannot hide a math-title answer leak",
          [items(math_answer_card.replace("The plot tracing", replacement),
                 "k-nearest-neighbors.md")
           for replacement in (
               "A $k$-nearest neighbors method tracing",
               "A $\\boldsymbol{k}$-nearest neighbors method tracing")],
          [["19-flashcard-leak"]] * 2)
    math_alias_card = math_answer_card.replace(
        '  - "nearest-neighbor-rule"', '  - "knn"')
    check("a math-title primary card still gets the entry aliases",
          items(math_alias_card.replace(
              "The plot tracing", "A KNN method tracing"),
              "k-nearest-neighbors.md"), ["19-flashcard-leak"])
    secondary_names_primary = mutate(
        "??\nROC curve\n",
        "??\nROC curve\n\nA ROC curve can illustrate this separate notion.\n"
        "??\nSecond idea\n")
    check("a legacy secondary card may name the primary while its own answer "
          "remains leak-free",
          items(secondary_names_primary), ["19-flashcards"])

    def card_findings(text):
        """Item-19 findings other than the report-only extra-card count."""
        return [f for f in lint_text(text, "roc-curve.md")["findings"]
                if f["item"] == "19-flashcards"
                and not (f.get("evidence") or {}).get("report_only")]

    extra_card = "\n\nAnother idea stated.\n??\nGamma\n"
    check("an extra card keeps its own line-3 answer beside the primary card",
          card_findings(mutate("??\nROC curve\n", "??\nROC curve\n" + extra_card)),
          [])
    check("with no primary card, one finding asks for it without naming an "
          "extra card's answer as wrong",
          [f["message"].startswith("no card carries the primary answer "
                                   '"ROC curve"')
           for f in card_findings(mutate("??\nROC curve\n",
                                         "??\nAlpha\n" + extra_card))],
          [True])
    check("a punctuation-variant primary card is the scanner's near miss",
          [f["evidence"]["card"] for f in card_findings(
              mutate('title: "ROC curve"', 'title: "ROC-curve"')
              .replace("\nROC curve\n", "\nROC–curve\n" + extra_card, 1))],
          [1])
    check("a near-miss primary card gets its own line-3 fault",
          [(f["evidence"]["card"], "canonical casing" in f["message"])
           for f in card_findings(mutate("??\nROC curve\n",
                                         "??\nroc curve\n" + extra_card))],
          [(1, True)])
    check("a short title is not leaked by a mid-word substring",
          items(mutate('title: "ROC curve"', 'title: "C"')
                .replace("A **ROC curve** plots", "A **C** creates")
                .replace("A ROC curve plots", "C creates")
                .replace("ROC curve\n??", "C\n??").replace("\nROC curve\n", "\nC\n"),
                "c.md"), [])
    check("a long title is not leaked inside a different word",
          items(mutate('title: "ROC curve"', 'title: "Variance"')
                .replace("A **ROC curve** plots", "**Variance** describes")
                .replace("A ROC curve plots", "Variance describes")
                .replace("The plot tracing", "A covariance plot tracing")
                .replace("ROC curve\n??", "Variance\n??")
                .replace("\nROC curve\n", "\nVariance\n"),
                "variance.md"), [])

    # -- item 19: the card set and understanding cards --------------------
    why = ("Why does raising the decision threshold lower recall?\n?\n"
           "Fewer instances are predicted positive, so more actual positives "
           "are missed.\n")
    differ = ("How does a ROC curve differ from a precision-recall curve?\n"
              "?\nIt plots the false positive rate against recall.\n")

    def with_cards(*extra):
        return mutate("??\nROC curve\n",
                      "??\nROC curve\n" + "".join("\n" + c for c in extra))

    check("a primary card plus two understanding cards is a complete set",
          items(with_cards(why, differ)), [])
    third = lint_text(with_cards(why, differ, why.replace("recall", "TPR")),
                      "roc-curve.md")["findings"]
    check("a third understanding card is a report-only legacy extra",
          [(f["item"], f["evidence"].get("report_only"),
            f["evidence"].get("cards")) for f in third],
          [("19-flashcards", True, 4)])
    check("an understanding question needs its question mark",
          [(f["item"], "question mark" in f["message"])
           for f in lint_text(with_cards(why.replace("recall?", "recall.")),
                              "roc-curve.md")["findings"]],
          [("19-flashcards", True)])
    check("an understanding answer takes inline LaTeX only",
          ([(f["item"], "answer has forbidden bold" in f["message"])
            for f in lint_text(with_cards(
                "Why?\n?\nIt is **bold**.\n"), "roc-curve.md")["findings"]],
           items(with_cards("What is the rate?\n?\n$\\sqrt{x}$\n"))),
          ([("19-flashcards", True)], []))
    check("an understanding question may name the title and an alias",
          items(with_cards(
              "Why does a ROC curve (AUROC) ignore class balance?\n?\n"
              "Both of its rates are conditioned on the true class.\n")), [])
    check("an understanding question may not contain its own answer",
          items(with_cards(
              "Which rate falls, recall or precision?\n?\nRecall\n")),
          ["19-flashcard-leak"])
    check("a user-disabled understanding card keeps its kind",
          items(with_cards(why.replace("\n?\n", "\n!!\n"))), [])
    long_cue = ("The plot tracing the trade-off between two error rates as a "
                "decision threshold moves across every possible score value, "
                "drawn for a binary classifier evaluated on a held-out test "
                "set.")
    check("a long definition cue is an advisory brevity candidate",
          [(f["item"], f["severity"]) for f in lint_text(mutate(
              "The plot tracing the trade-off between two error rates as a "
              "decision threshold moves.", long_cue),
              "roc-curve.md")["findings"]],
          [("19-brevity-candidate", "warning")])
    check("a long understanding answer is an advisory brevity candidate",
          items(with_cards("Why does the curve bend?\n?\n"
                           + " ".join(["word"] * 25) + "\n")),
          ["19-brevity-candidate"])

    # -- item 19: a discipline root needs no card --------------------------
    stats_root = (
        '---\n'
        'title: "Statistics"\n'
        'type: Concept\n'
        'sources:\n'
        '  - "[[Doe_X_2025.pdf#page=2]]"\n'
        'created: 2026-01-01\n'
        'updated: 2026-01-02\n'
        'description: "Statistics is the study of collecting and interpreting '
        'data."\n'
        'tags:\n'
        '  - "#statistics"\n'
        'parents: []\n'
        'read: false\n'
        '---\n'
        '**Statistics** is the study of collecting, analyzing and '
        'interpreting data.\n'
        '\n'
        '**Related:** [[standard-deviation|Standard deviation]]\n')
    check("a discipline root needs no Flashcards section",
          items(stats_root, "statistics.md"), [])
    check("the same text under another filename needs its card",
          "19-flashcards" in items(stats_root, "stats-overview.md"), True)
    check("a root whose tag names another discipline is not exempt",
          "19-flashcards" in items(
              stats_root.replace('"#statistics"', '"#mathematics"'),
              "statistics.md"), True)
    check("a scalar tag does not make a root, as in the scanner",
          items(stats_root.replace('tags:\n  - "#statistics"',
                                   'tags: "#statistics"'), "statistics.md"),
          ["19-flashcards", "8-tags"])
    check("a layout fault elsewhere keeps the root, as in the scanner",
          [items(stats_root.replace("read: false\n", "read: false\nread: false\n"),
                 "statistics.md"),
           items(stats_root.replace('  - "#statistics"', '    - "#statistics"'),
                 "statistics.md")],
          [["1-valid-yaml"], ["1-valid-yaml"]])
    check("an unreadable frontmatter line voids the root, as in the scanner",
          "19-flashcards" in items(
              stats_root.replace("read: false\n", "read: false\nstray prose\n"),
              "statistics.md"), True)
    check("a root with an empty Flashcards section has no card-count finding",
          items(stats_root + "\n---\n\n## Flashcards\n", "statistics.md"),
          [])
    check("a root whose card set lacks a `??` primary has no missing-primary "
          "finding",
          items(stats_root + "\n---\n\n## Flashcards\n\n"
                "Why do statisticians sample?\n?\n"
                "A sample costs less than a census.\n", "statistics.md"), [])
    check("a root's card is checked as usual",
          [f["message"].startswith("flashcard 1 line 3")
           for f in lint_text(
               stats_root + "\n---\n\n## Flashcards\n\n"
               "The study of collecting and interpreting data.\n??\nStats\n",
               "statistics.md")["findings"]], [True])
    check("the misc root needs no card",
          items(stats_root.replace('"Statistics"', '"Misc"')
                .replace('"#statistics"', '"#misc"')
                .replace("Statistics is the study of collecting and "
                         "interpreting data.",
                         "Misc holds entries outside every discipline.")
                .replace("**Statistics** is the study of collecting, "
                         "analyzing and interpreting data.",
                         "**Misc** holds entries outside every discipline."),
                "misc.md"), [])
    root_tmp = tempfile.mkdtemp(prefix="lint_entry-root-")
    try:
        with open(os.path.join(root_tmp, "statistics.md"), "w",
                  encoding="utf-8") as handle:
            handle.write(stats_root)
        with open(os.path.join(root_tmp, "standard-deviation.md"), "w",
                  encoding="utf-8") as handle:
            handle.write(
                good.replace('title: "ROC curve"', 'title: "Standard deviation"')
                .replace('aliases:\n  - "auroc"\n', '')
                .replace('description: "A ROC curve plots true positive rate '
                         'against false positive rate."',
                         'description: "Standard deviation measures spread '
                         'around the mean."')
                .replace("A **ROC curve** plots the trade-off between two "
                         "error rates as a decision threshold moves.",
                         "**Standard deviation** measures spread around the "
                         "mean.")
                .replace("[[precision|Precision]]", "[[statistics|Statistics]]")
                .replace("The plot tracing the trade-off between two error "
                         "rates as a decision threshold moves.",
                         "The square root of the variance.")
                .replace("\nROC curve\n", "\nStandard deviation\n"))
        root_report = lint_path(root_tmp)
        check("folder mode keeps the root exemption and its Related labels",
              (root_report["summary"]["files"],
               sorted((os.path.basename(entry["file"]), finding["item"])
                      for entry in root_report["entries"]
                      for finding in entry["findings"])), (2, []))
    finally:
        shutil.rmtree(root_tmp, ignore_errors=True)

    # -- item 9: structure plus semantic body review -----------------------
    check("the body starts immediately after frontmatter",
          items(mutate("read: false\n---\nA **ROC curve**",
                       "read: false\n---\n\nA **ROC curve**")),
          ["9-body-structure"])
    opener_sentence = ("A **ROC curve** plots the trade-off between two error "
                       "rates as a decision threshold moves.\n\n")
    check("the body cannot start with an empty or Markdown-block opener",
          ["9-body-structure" in items(mutate(opener_sentence, replacement))
           for replacement in (
               "", "+ item\n\n", "1. item\n\n", "1) item\n\n",
               ">quoted\n\n", "```text\nlisting\n```\n\n",
               "~~~text\nlisting\n~~~\n\n", "    listing\n\n",
               "\tlisting\n\n")],
          [True] * 9)
    check("body headings use exactly plain-text ## ATX form",
          (items(mutate("\n**Related:**",
                        "\n\n### Details\n\nA narrower claim.\n\n**Related:**")),
           items(mutate("\n**Related:**",
                        "\n\n## *Details*\n\nA narrower claim.\n\n**Related:**")),
           items(mutate("\n**Related:**",
                        "\n\n## [Details](target)\n\nA narrower claim.\n\n**Related:**")),
           items(mutate("\n**Related:**",
                        "\n\n## <em>Details</em>\n\nA narrower claim.\n\n**Related:**")),
           items(mutate("\n**Related:**",
                        "\n\n## `Details`\n\nA narrower claim.\n\n**Related:**"))),
          (["9-body-structure"], ["9-body-structure"],
           ["9-body-structure"], ["9-body-structure"],
           ["6-api-surface", "9-body-structure"]))
    check("a Setext body heading cannot evade the exactly-## rule",
          items(mutate("\n**Related:**",
                       "\n\nDetails\n-------\n\nA narrower claim.\n\n**Related:**")),
          ["9-body-structure"])
    check("a canonical plain-text ## body heading remains valid",
          items(mutate("\n**Related:**",
                       "\n\n## Details\n\nA narrower claim.\n\n**Related:**")),
          [])
    dated_person = retitled(
        "Ada Lovelace", "augusta-ada-king",
        "Ada Lovelace was an English mathematician.",
        "**Ada Lovelace** (1815–1852) was an English mathematician.",
        "Ada Lovelace", type_="Person")
    dated_event = retitled(
        "Trinity test", "trinity-nuclear-test",
        "The Trinity test was the first nuclear detonation.",
        "The **Trinity test** (1945-07-16) was the first nuclear detonation.",
        "Trinity test", type_="Event")
    check("valid Person and Event opener dates pass builder lint",
          (items(dated_person, "ada-lovelace.md"),
           items(dated_event, "trinity-test.md")), ([], []))
    check("a date before an acronym expansion keeps the card counterpart",
          items(retitled(
              "ILSVRC", "imagenet-large-scale-visual-recognition-challenge",
              "ILSVRC was an annual image-classification competition.",
              "**ILSVRC** (2010–2017) (ImageNet Large Scale Visual "
              "Recognition Challenge) was an annual competition.",
              "ILSVRC (ImageNet Large Scale Visual Recognition Challenge)",
              type_="Event"), "ilsvrc.md"), [])
    check("missing or misplaced Person/Event years fail builder item 9",
          (items(dated_person.replace(" (1815–1852)", ""),
                 "ada-lovelace.md"),
           items(dated_event.replace(" (1945-07-16) was",
                                     " was first proposed in 1942 and"),
                 "trinity-test.md")),
          (["9-person-event-date"], ["9-person-event-date"]))
    check("a noncanonical or impossible Person/Event date form fails item 9",
          (items(dated_person.replace("(1815–1852)", "(1815 to 1852)"),
                 "ada-lovelace.md"),
           items(dated_person.replace(" (1815–1852)", "(1815–1852)"),
                 "ada-lovelace.md"),
           items(dated_event.replace("(1945-07-16)", "(1945/07/16)"),
                 "trinity-test.md"),
           items(dated_event.replace("(1945-07-16)", "(1945-02-31)"),
                 "trinity-test.md")),
          (["9-person-event-date"], ["9-person-event-date"],
           ["9-person-event-date"],
           ["9-person-event-date"]))
    check("a long, well-scoped entry sentence has no length finding",
          items(mutate("A **ROC curve** plots the trade-off between two error "
                       "rates as a decision threshold moves.\n",
                       "A **ROC curve** plots the trade-off between false "
                       "positive and true positive rates as a decision "
                       "threshold moves through every operating point, while "
                       "preserving the relationship between threshold choice, "
                       "ranking behaviour, and the classifier's error profile "
                       "in one clear scoped statement.\n")),
          [])
    # Descriptions and flashcard definitions still require one sentence.
    # A possessive must end a sentence; an initial must not.
    check("a possessive before the period separates two sentences",
          count_sentences("One belongs to the predictor's. Another follows."), 2)
    check("...and a genuine initial still does not split (B. F. Skinner)",
          count_sentences("It was described by B. F. Skinner in 1948."), 1)
    check("display math beside long prose creates no body-length finding",
          items(mutate("A **ROC curve** plots the trade-off between two error "
                       "rates as a decision threshold moves.\n",
                       "A **ROC curve** plots one error-rate pair per threshold "
                       "and can be summarized by the area under the curve:\n\n"
                       "$$\nA = \\int_0^1 f(x)\\,dx\n$$\n\n"
                       "The integral aggregates ranking behaviour across all "
                       "operating points while the curve preserves the "
                       "threshold-specific trade-off.\n")),
          [])
    equationless = mutate(
        "A **ROC curve** plots the trade-off between two error "
        "rates as a decision threshold moves.\n",
        "A **ROC curve** plots the trade-off between two error rates as a "
        "decision threshold moves. Its spread is the square root of the "
        "variance.\n")
    check("an explicit square-root-of-variance definition without display math "
          "is an equation-coverage candidate",
          items(equationless), ["12-equation-coverage-candidate"])
    check("a nearby canonical display block clears the prose equation candidate",
          items(equationless.replace(
              "variance.\n", "variance:\n\n$$\n"
              "\\sigma = \\sqrt{\\operatorname{Var}(X)}\n$$\n", 1)), [])
    one_line_display = equationless.replace(
        "variance.\n", "variance:\n\n"
        "$$\\sigma = \\sqrt{\\operatorname{Var}(X)}$$\n", 1)
    check("a one-line display is a form finding, not a missing-equation finding",
          items(one_line_display), ["12-equation-format"])
    one_line_finding = next(
        finding for finding in lint_text(
            one_line_display, "roc-curve.md")["findings"]
        if finding["item"] == "12-equation-format")
    check("an equation form finding uses the physical file line",
          one_line_finding["evidence"]["matches"][0]["line"],
          one_line_display.splitlines().index(
              "$$\\sigma = \\sqrt{\\operatorname{Var}(X)}$$") + 1)
    check("an expanded squared-deviation average clears the prose equation candidate",
          items(equationless.replace(
              "variance.\n", "variance:\n\n$$\n"
              "\\sigma = \\sqrt{\\frac{1}{N}"
              "\\sum_i (x_i - \\mu)^2}\n$$\n", 1)), [])
    check("unrelated square-root and variance terms in one display do not clear "
          "the prose equation candidate",
          items(equationless.replace(
              "variance.\n", "variance:\n\n$$\n"
              "f(x) = \\sqrt{x} + \\operatorname{Var}(Y)\n$$\n", 1)),
          ["12-equation-coverage-candidate"])
    inline_definition = mutate(
        "A **ROC curve** plots the trade-off between two error "
        "rates as a decision threshold moves.\n",
        "A **ROC curve** plots one similarity score. For input $x$ and "
        "center $c$, the similarity is $\\exp(-\\gamma (x-c)^2)$.\n")
    check("a defining expression left inline is an equation-form candidate",
          items(inline_definition), ["12-equation-coverage-candidate"])
    check("an unrelated display elsewhere does not clear an inline defining formula",
          items(inline_definition.replace(
              "plots one similarity score.",
              "plots one similarity score.\n\n$$\nq = 1\n$$\n\n")),
          ["12-equation-coverage-candidate"])
    check("a square-root-of-variance phrase in a table is not body-equation "
          "evidence",
          items(mutate(
              "A **ROC curve** plots the trade-off between two error rates as "
              "a decision threshold moves.\n",
              "A **ROC curve** plots the trade-off between two error rates as "
              "a decision threshold moves.\n\nClaim | Value\n--- | ---\n"
              "Spread | It is the square root of variance.\n"
              "*Values by measure.*\n")), [])
    check("Flashcards are outside the equation-coverage prose region",
          "12-equation-coverage-candidate" in items(
              mutate("The plot tracing the trade-off between two error rates "
                     "as a decision threshold moves.",
                     "It is the square root of variance.")), False)
    check("equation wording shown in inline or fenced code is not asserted prose",
          "12-equation-coverage-candidate" in items(mutate(
              "A **ROC curve** plots the trade-off between two error rates as "
              "a decision threshold moves.\n",
              "A **ROC curve** shows `it is the square root of variance` as "
              "literal text.\n\n```text\nIt is the square root of variance.\n```\n")),
          False)
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
          ["6-api-surface"]),
    check("a navigation-only cue pointing straight at a wikilink is item 9",
          items(mutate("decision threshold moves.\n",
                       "decision threshold moves (see [[precision]]).\n")),
          ["9-link-integration"])
    check("ordinary 'to see how' prose is not a navigation-only link cue",
          items(mutate("decision threshold moves.\n",
                       "decision threshold moves; to see how it changes, vary the cutoff.\n")),
          [])
    check("semantic 'see X as Y' prose is not a navigation-only cue",
          items(mutate("decision threshold moves.\n",
                       "decision threshold moves. Researchers see "
                       "[[precision]] as context-dependent.\n")), [])
    check("a navigation cue shown in a fenced listing is ignored",
          items(mutate("\n**Related:**",
                       "\n\n```markdown\nsee [[precision]]\n```\n\n**Related:**")),
          ["6-api-surface"])
    images = mutate(
        "\n**Related:**",
        "\n\n![[figure.png]]\n"
        "*A local figure with $x^*$ shown in its caption.*\n\n"
        "![Remote figure](https://example.test/figure.png)\n"
        "*A remote figure with a plain caption.*\n\n**Related:**")
    check("Obsidian and Markdown image embeds with immediate captions pass",
          items(images), [])
    complex_images = mutate(
        "\n**Related:**",
        "\n\n![Balanced](https://example.test/plot_(x).png)\n"
        "*A destination containing balanced parentheses.*\n\n"
        "![Angle](<https://example.test/plot_(y).png>)\n"
        "*A CommonMark angle-bracket destination.*\n\n"
        "![Plot [panel A]](https://example.test/panel.png)\n"
        "*A nested-bracket alt label.*\n\n"
        r"\![Literal](https://example.test/not-an-image.png)" "\n\n**Related:**")
    check("balanced destinations, nested alt text, and escaped image syntax pass",
          items(complex_images), [])
    check("a blank line between an image and caption is an item-12 error",
          items(images.replace(
              "![[figure.png]]\n*A local", "![[figure.png]]\n\n*A local")),
          ["12-image-caption"])
    missing_caption = mutate(
        "\n**Related:**", "\n\n![[uncaptioned.png]]\n\n**Related:**")
    caption_finding = next(
        finding for finding in lint_text(
            missing_caption, "roc-curve.md")["findings"]
        if finding["item"] == "12-image-caption")
    check("body evidence uses a physical file line, not a body-relative line",
          caption_finding["evidence"]["line"],
          missing_caption.splitlines().index("![[uncaptioned.png]]") + 1)
    for label, markup, fault in (("nested italic", "*extra detail*", "italic"),
                                 ("wikilink", "[[precision|linked detail]]", "wikilink"),
                                 ("Markdown link", "[source](https://example.test)", "Markdown link"),
                                 ("HTML", "<span>detail</span>", "HTML"),
                                 ("strikethrough", "~~extra detail~~", "strikethrough"),
                                 ("bold", "**extra detail**", "bold"),
                                 ("backtick", "`extra detail`", "backtick")):
        result = lint_text(
            images.replace("a plain caption", "a plain caption with " + markup),
            "roc-curve.md")
        check("an image caption rejects %s markup" % label,
              [(f["item"], fault in f["message"])
               for f in result["findings"]],
              [("12-image-caption", True)]
              # A backticked caption word is also an item-6 identifier.
              + ([("6-api-surface", True)] if label == "backtick" else []))
    check("an empty italic caption is rejected",
          items(images.replace("*A remote figure with a plain caption.*", "* *")),
          ["12-image-caption"])
    listing_images = mutate(
        "\n**Related:**",
        "\n\n```\n![[fenced.png]]\n```\n\n"
        "    ![Indented](indented.png)\n\n**Related:**")
    check("image syntax in fenced and indented listings needs no caption",
          items(listing_images), ["6-api-surface"])
    table = mutate(
        "\n**Related:**",
        "\n\n| Method | Score |\n| --- | --- |\n| A | 0.8 |\n"
        "*Scores on the held-out set.*\n\n**Related:**")
    check("a Markdown table with an immediate italic plain-text caption passes",
          items(table), [])
    check("a table caption containing permitted LaTeX bars remains a caption",
          items(table.replace("Scores on the held-out set.",
                              "Error is $|x-y|$ on the held-out set.")), [])
    one_column_table = mutate(
        "\n**Related:**",
        "\n\n| Metric |\n| --- |\n| Recall |\n"
        "*The reported metric.*\n\n**Related:**")
    check("a one-column GFM table with an immediate caption is detected and passes",
          items(one_column_table), [])
    one_column_no_pipe_row = one_column_table.replace("| Recall |", "Recall")
    check("a one-column GFM body row does not require a pipe",
          items(one_column_no_pipe_row), [])
    check("a bare wikilink in a pipe-less one-column table row is rejected",
          items(one_column_no_pipe_row.replace("Recall", "[[precision]]")),
          ["10-table-cell-wikilink"])
    check("a one-column GFM table without a caption is detected",
          items(one_column_table.replace("\n*The reported metric.*", "")),
          ["12-table-caption"])
    pipe_less_link_table = mutate(
        "\n**Related:**",
        "\n\nMetric | Value\n--- | ---\n"
        "[[precision|Precision]] | 0.8\n"
        "*The reported metric.*\n\n**Related:**")
    check("a wikilink in a pipe-less GFM table cell is rejected",
          items(pipe_less_link_table), ["10-table-cell-wikilink"])
    check("wikilink syntax in inline code inside a table cell stays literal",
          items(pipe_less_link_table.replace(
              "[[precision|Precision]]", "`[[precision|Precision]]`", 1)), [])
    emphasized_row = table.replace("| A | 0.8 |",
                                   "| A | 0.8 |\n*Recall* | *0.8*")
    check("an emphasized table row is not mistaken for the caption",
          items(emphasized_row), [])
    check("a blank line between a table and its caption is an item-12 error",
          items(table.replace("| A | 0.8 |\n*Scores", "| A | 0.8 |\n\n*Scores")),
          ["12-table-caption"])
    check("caption code markup is rejected even though table detection masks listings",
          items(table.replace("held-out", "`held-out`")),
          ["12-table-caption", "6-api-surface"])
    check("...same for an inline code span",
          items(mutate("**Related:** [[precision|Precision]]",
                       "It links [[precision|Precision]] once in prose, and "
                       "shows `[[precision]]` as syntax.\n\n"
                       "**Related:** [[precision|Precision]]")),
          [])
    check("path, explicit .md, case, and Unicode-normalization variants count "
          "as one body-link target",
          items(mutate("A **ROC curve** plots the trade-off between two error "
                       "rates as a decision threshold moves.",
                       "A **ROC curve** compares [[Wiki/precision.md|Precision]] "
                       "with [[WIKI/PRECISION|precision]] as two spellings of one "
                       "destination.")),
          ["10-duplicate-wikilink"])
    # A 1- or 2-line card is malformed, not silently clean.
    check("a card missing its term line is a malformed-card error",
          items(mutate("threshold moves.\n??\nROC curve\n",
                       "threshold moves.\n??\n")),
          ["19-flashcards"])
    joined_cards = mutate(
        "threshold moves.\n??\nROC curve\n",
        "One identifying statement.\n??\nROC curve\n"
        "A second definition.\n??\nSecond term\n")
    check("a second card joined without a blank line is malformed visible content",
          "visible lines" in " ".join(
              finding["message"] for finding in
              lint_text(joined_cards, "roc-curve.md")["findings"]
              if finding["item"] == "19-flashcards"),
          True)
    ordinary_line4_comment = mutate(
        "threshold moves.\n??\nROC curve\n",
        "threshold moves.\n??\nROC curve\n<!--ordinary comment-->\n")
    check("a non-SR line-four HTML comment is malformed visible content",
          "visible lines" in " ".join(
              finding["message"] for finding in
              lint_text(ordinary_line4_comment, "roc-curve.md")["findings"]
              if finding["item"] == "19-flashcards"),
          True)
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
          ["16-bold-opener", "16-unenumerated-bold"])
    # Case/normalization-variant aliases within one entry are one name twice.
    check("two alias spellings folding to one name are 18-alias-duplicate "
          "(the non-slug-form spelling is real fallout, reported too)",
          items(mutate('  - "auroc"', '  - "auroc"\n  - "AUROC"')),
          ["18-alias-duplicate", "18-alias-form"])
    # A comma-delimited empty element is invalid YAML, not an empty list.
    check("a degenerate flow list is a YAML validity finding",
          items(mutate('aliases:\n  - "auroc"\n', "aliases: [,]\n")),
          ["1-valid-yaml"])

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
          items(mutate('title: "Precision"', 'title: "A. M. Turing"', base=precision)
                .replace("type: Concept", "type: Person")
                .replace("**Precision** is the share of predicted positives "
                         "that are correct.",
                         "**A. M. Turing** (1912–1954) was a "
                         "mathematician, e.g. of computability.")
                .replace('description: "Precision is the share of predicted '
                         'positives that are correct."',
                         'description: "A. M. Turing was a mathematician."')
                .replace("\nPrecision\n", "\nA. M. Turing\n"),
                "a-m-turing.md"), [])
    check("the cue catches 'which many people call *X*'",
          [c for c, _w in _alias_candidates(split_sections(
              "**Min-max scaling** — which many people call *normalization* "
              "— rescales features to a fixed range."))],
          ["normalization"])
    check("a short-for marker is stripped from the opener alias candidate",
          [c for c, _w in _alias_candidates(split_sections(
              "**AdaBoost** (short for *adaptive boosting*) reweights "
              "mistakes."))],
          ["adaptive boosting"])
    check("an originally-called marker is stripped without changing the "
          "synonym itself",
          [c for c, _w in _alias_candidates(split_sections(
              "**Boosting** (originally called *hypothesis boosting*) "
              "combines weak learners."))],
          ["hypothesis boosting"])
    check("a synonym cue takes only its immediately following italic candidate",
          [c for c, _w in _alias_candidates(
              split_sections("**ROC curve**, also called *receiver plot*, "
                             "contrasts *false positives*."),
              ["ROC curve"])],
          ["receiver plot"])
    check("a component's also-called phrase is not an alias candidate for the "
          "entry subject",
          [c for c, _w in _alias_candidates(
              split_sections("A **ROC curve** compares rates. The false "
                             "positive rate, also called the *fall-out*, is "
                             "one axis."), ["ROC curve"])],
          [])
    check("an explicit subject pronoun still introduces a genuine alias",
          [c for c, _w in _alias_candidates(
              split_sections("**MNIST** is widely studied. It is often called "
                             "the *hello world* of machine learning."),
              ["MNIST"])],
          ["hello world"])
    check("a plural canonical subject is recognized with each chained candidate",
          [c for c, _w in _alias_candidates(
              split_sections("A **feature** is an input. Features are also "
                             "called *predictors* or *attributes*."),
              ["Feature (machine learning)"])],
          ["predictors", "attributes"])
    check("an opener parenthetical's lead-in marker and italics are stripped",
          [c for c, _w in _alias_candidates(split_sections(
              "**Archaea** (singular, *archaeon*) are single-celled "
              "prokaryotes."))],
          ["archaeon"])
    check("synonym cues shown in inline, fenced, and indented code are not aliases",
          [c for c, _w in _alias_candidates(split_sections(
              "**ROC curve** is a worked example.\n\n"
              "`ROC curve is also called *inline fake*.`\n\n"
              "```text\nROC curve is also called *fenced fake*.\n```\n\n"
              "    ROC curve is also called *indented fake*."),
              ["ROC curve"])],
          [])

    # -- item 18: alias form, and alias collisions in FOLDER scope ----------
    check("an alias that is not itself in slug form is a WARNING",
          [(f["item"], f["severity"])
           for f in lint_text(mutate('  - "auroc"',
                                     '  - "receiver operating characteristic"'),
                              "roc-curve.md")["findings"]],
          [("18-alias-form", "warning")])
    check("an empty alias item is rejected",
          items(mutate('  - "auroc"', '  - ""')),
          ["18-alias-form"])
    check("an alias equal to the entry's own slug is rejected",
          items(mutate('  - "auroc"', '  - "roc-curve"')),
          ["18-alias-form"])
    check("a singular/plural-only alias of the canonical slug is rejected",
          items(mutate('  - "auroc"', '  - "roc-curves"')),
          ["18-alias-form"])

    # -- checks shared with wiki-lint's scanner (shared/entry_checks.py) ----
    def with_paragraph(paragraph, base=None):
        """The clean fixture with one body paragraph after its opener."""
        return mutate("decision threshold moves.\n",
                      "decision threshold moves.\n\n" + paragraph + "\n", base)

    def found(text, prefix, filename="roc-curve.md"):
        return [(f["item"], f["severity"])
                for f in lint_text(text, filename)["findings"]
                if f["item"].startswith(prefix)]

    shared_tmp = tempfile.mkdtemp(prefix="lint_entry-shared-")
    try:
        with open(os.path.join(shared_tmp, "precision.md"), "w",
                  encoding="utf-8") as fh:
            fh.write(precision)
        with open(os.path.join(shared_tmp, "decision-threshold.md"), "w",
                  encoding="utf-8") as fh:
            fh.write(_st_decision_threshold())
        # The same rows run through scan_vault's self-test: each moved
        # mutation must be flagged by both tools.
        for name, paragraph, _scan_key, lint_id, needs_folder in SHARED_MUTATIONS:
            mutated = with_paragraph(paragraph.replace("{self}", "roc-curve"))
            with open(os.path.join(shared_tmp, "roc-curve.md"), "w",
                      encoding="utf-8") as fh:
                fh.write(mutated)
            folder_items = sorted({
                f["item"] for entry in lint_path(shared_tmp)["entries"]
                if os.path.basename(entry["file"]) == "roc-curve.md"
                for f in entry["findings"]})
            check("scanner parity, %s: %s" % (name, lint_id),
                  (lint_id in items(mutated), lint_id in folder_items),
                  (not needs_folder, True))
        with open(os.path.join(shared_tmp, "roc-curve.md"), "w",
                  encoding="utf-8") as fh:
            fh.write(with_paragraph(
                "It is the [[Wiki/roc-curve|curve]] shown beside "
                "[[precision|precision values]]."))
        check("folder mode resolves a path-qualified self-link; a label "
              "sharing its target's surface passes",
              sorted({f["item"] for entry in lint_path(shared_tmp)["entries"]
                      for f in entry["findings"]}), ["10-self-link"])
        # The rows neither tool may flag (scan_vault runs them too).
        for name, text in (
                ("mus-musculus.md", retitled(
                    "Mus musculus", "m-musculus",
                    "Mus musculus is the mouse, a small rodent.",
                    "***Mus musculus*** is the mouse, a small rodent.",
                    "Mus musculus", type_="Organism")),
                ("l-2-norm.md", retitled(
                    "$L^2$ norm", "l2-norm",
                    "The L-squared norm measures a vector's length.",
                    "The **$L^2$ norm** measures a vector's length.",
                    "L-squared norm")),
                ("label-machine-learning.md", _st_label())):
            with open(os.path.join(shared_tmp, name), "w",
                      encoding="utf-8") as fh:
                fh.write(text)
        for name, paragraph, _scan_key, lint_id in SHARED_QUIET:
            quiet = with_paragraph(paragraph)
            with open(os.path.join(shared_tmp, "roc-curve.md"), "w",
                      encoding="utf-8") as fh:
                fh.write(quiet)
            folder_items = sorted({
                f["item"] for entry in lint_path(shared_tmp)["entries"]
                if os.path.basename(entry["file"]) == "roc-curve.md"
                for f in entry["findings"]})
            check("scanner parity, quiet %s: %s" % (name, lint_id),
                  (lint_id in items(quiet), lint_id in folder_items),
                  (False, False))
    finally:
        shutil.rmtree(shared_tmp, ignore_errors=True)

    entropy = retitled(
        "Entropy", "shannon-entropy",
        "Entropy measures the uncertainty of a distribution.",
        "**Entropy** measures the uncertainty of a distribution.", "Entropy")
    check("a bare cross-domain common-noun slug is item 5's error; a "
          "qualified one is not",
          (found(entropy, "5-", "entropy.md"),
           found(entropy.replace('title: "Entropy"',
                                 'title: "Entropy (information theory)"'),
                 "5-", "entropy-information-theory.md")),
          ([("5-bare-common-noun", "error")], []))
    check("the bare common-noun error is report-only, so a merge into an "
          "existing bare-slug entry reports the rename it may not apply",
          [(f["severity"], f["evidence"]) for f in lint_text(
              entropy, "entropy.md")["findings"]
           if f["item"] == "5-bare-common-noun"],
          [("error", {"slug": "entropy", "report_only": True})])
    check("item 6: identifiers and fences are errors, framing is a warning",
          sorted((f["evidence"]["check"], f["severity"])
                 for f in lint_text(with_paragraph(
                     "In NumPy the curve is kept as `roc_points`.\n\n"
                     "```python\nx = 1\n```"), "roc-curve.md")["findings"]
                 if f["item"] == "6-api-surface"),
          [("api-string", "warning"), ("backticked-identifiers", "error"),
           ("fenced-code", "error")])
    check("item 6: a code-identifier title is a warning; Software keeps its API",
          ([(f["evidence"]["check"], f["severity"]) for f in lint_text(
              mutate('title: "ROC curve"', 'title: "numpy.linalg"'),
              "numpy-linalg.md")["findings"] if f["item"] == "6-api-surface"],
           found(with_paragraph("In NumPy use `np.dot` to multiply.",
                                mutate("type: Concept", "type: Software")),
                 "6-")),
          ([("code-identifier-title", "warning")], []))
    scarred = with_paragraph("importance: high")
    check("item 13: a merge scar is an error reported at its file line",
          [(f["severity"], f["evidence"]["line"])
           for f in lint_text(scarred, "roc-curve.md")["findings"]
           if f["item"] == "13-merge-scar"],
          [("error", scarred.split("\n").index("importance: high") + 1)])
    check("item 14 is a warning; the authors of a linked work pass this gate",
          (found(with_paragraph("As shown in the paper, the curve bends."),
                 "14-"),
           found(with_paragraph("The authors of [[precision|Precision]] "
                                "argue that the curve bends."), "14-")),
          ([("14-source-meta", "warning")], []))
    check("item 16: unenumerated bold and emphasis around a span are errors",
          sorted(found(with_paragraph("The **area** under it is *$A$*."),
                       "16-")),
          [("16-emphasis-markup", "error"), ("16-unenumerated-bold", "error")])
    check("item 16: only the pure-math title's opener bold is exempt",
          (found(positive_superscript, "16-", "r-plus.md"),
           found(mutate("worked mathematical example.\n",
                        "worked mathematical example.\n\n"
                        "Later **$R^{+}$** returns.\n", positive_superscript),
                 "16-", "r-plus.md")),
          ([], [("16-emphasis-markup", "error")]))
    check("a preserved comment before the opener leaves the title's bold "
          "in the opener; a missing opener bold is still found",
          ([items(text, filename) for text, filename in (
              (mutate("---\nA **ROC curve**",
                      "---\n%% user note %%\n\nA **ROC curve**"),
               "roc-curve.md"),
              (mutate("---\nA **ROC curve**",
                      "---\n<!-- reviewed 2026-01 -->\nA **ROC curve**"),
               "roc-curve.md"),
              (mutate("---\n**$R^{+}$**", "---\n%% user note %%\n\n**$R^{+}$**",
                      positive_superscript), "r-plus.md"))],
           found(mutate("---\nA **ROC curve**", "---\n%% note %%\n\nA ROC curve"),
                 "16-")),
          ([[], [], []], [("16-bold-opener", "error")]))
    check("item 18: label markup is an error",
          found(with_paragraph(
              "It trades against [[precision|*exact* precision]]."), "18-"),
          [("18-display-label", "error")])
    check("item 10: a link to the entry itself by slug, case, anchor, alias "
          "or in the footer",
          [found(text, "10-") for text in (
              with_paragraph("It is the [[roc-curve|curve]] itself."),
              with_paragraph("It is the [[ROC-Curve.md#Uses|curve]] itself."),
              with_paragraph("It is the [[auroc]] itself."),
              mutate("[[precision|Precision]]",
                     "[[precision|Precision]] · [[roc-curve|ROC curve]]"))],
          [[("10-self-link", "error")]] * 4)
    check("a single file leaves path-qualified self-links to folder mode; "
          "MOC navigation and table cells are not self-links",
          [found(text, "10-self") for text in (
              with_paragraph("It is the [[Wiki/roc-curve|curve]] itself."),
              with_paragraph("It is listed in [[MOCs/roc-curve]]."),
              with_paragraph("Curve | Value\n--- | ---\n[[roc-curve]] | 1\n"
                             "*Values by curve.*"))],
          [[], [], []])
    recall = retitled(
        "Recall (machine learning)", "true-positive-rate",
        "Recall is the share of actual positives that a classifier finds.",
        "**Recall**, also called *completeness*, is the share of actual "
        "positives that a classifier finds.", "Recall")
    check("a designated cross-domain synonym is never an alias candidate",
          [f["item"] for f in lint_text(
              recall.replace("*completeness*", "*sensitivity*"),
              "recall-machine-learning.md")["findings"]
           if f["item"] == "17-alias-completeness"],
          [])
    check("a single-word synonym of a qualified subject carries the scanner's "
          "cross-domain hint; an ordinary candidate does not",
          ([BARE_WORD_ALIAS_HINT in f["message"] for f in lint_text(
              recall, "recall-machine-learning.md")["findings"]
            if f["item"] == "17-alias-completeness"],
           [BARE_WORD_ALIAS_HINT in f["message"] for f in lint_text(
               good.replace("\n**Related:**", "\nIt is also called "
                            "*operating curve*.\n\n**Related:**"),
               "roc-curve.md")["findings"]
            if f["item"] == "17-alias-completeness"]),
          ([True], [False]))
    check("an acronym alias candidate carries no cross-domain hint",
          [BARE_WORD_ALIAS_HINT in f["message"] for f in lint_text(
              recall.replace("**Recall**, also called *completeness*,",
                             "**Recall** (**TPR**)"),
              "recall-machine-learning.md")["findings"]
           if f["item"] == "17-alias-completeness"],
          [False])
    su2 = retitled(
        "SU(2)", "special-unitary-group-of-degree-two",
        "SU(2) is the group of two-by-two unitary matrices with determinant one.",
        "**SU(2)** is the group of two-by-two unitary matrices with "
        "determinant one.", "SU(2)")
    check("a notation parenthesis is part of the name: an SU(2) entry lints "
          "clean",
          items(su2, slug_stem("SU(2)") + ".md"), [])

    tmp = tempfile.mkdtemp(prefix="lint_entry-selftest-")
    try:
        wiki = os.path.join(tmp, "Wiki")
        os.makedirs(os.path.join(wiki, "sub"))

        def put(rel, text, encoding="utf-8"):
            path = os.path.join(wiki, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            mode, kw = (("wb", {}) if isinstance(text, bytes)
                        else ("w", {"encoding": encoding}))
            with open(path, mode, **kw) as fh:
                fh.write(text)
            return path

        def named_good(title, alias, description, body):
            return (good.replace('title: "ROC curve"', 'title: "%s"' % title)
                        .replace('  - "auroc"', '  - "%s"' % alias)
                        .replace(
                            'description: "A ROC curve plots true positive rate '
                            'against false positive rate."',
                            'description: "%s"' % description)
                        .replace(
                            "A **ROC curve** plots the trade-off between two error "
                            "rates as a decision threshold moves.", body)
                        .replace("\nROC curve\n", "\n%s\n" % title))

        put("roc-curve.md", good)
        put("precision.md", precision)
        # a second entry claiming the same alias, in a different CASE
        put("sub/sensitivity.md",
            good.replace('title: "ROC curve"', 'title: "Sensitivity"')
                .replace('  - "auroc"',
                         '  - "AUROC"\n  - "unique-sensitivity"')
                .replace("A ROC curve plots", "Sensitivity measures")
                .replace("A **ROC curve** plots", "**Sensitivity** plots")
                .replace("\nROC curve\n", "\nSensitivity\n"))
        # an entry listing the SAME alias twice: its own per-entry fault,
        # never a folder-scope collision with itself
        put("sub/dupalias.md",
            good.replace('title: "ROC curve"', 'title: "Dupalias"')
                .replace('  - "auroc"', '  - "dupme"\n  - "dupme"')
                .replace("A ROC curve plots", "Dupalias names")
                .replace("A **ROC curve** plots", "**Dupalias** plots")
                .replace("\nROC curve\n", "\nDupalias\n"))
        put("sub/reader.md",
            good.replace('title: "ROC curve"', 'title: "Reader"')
                .replace('  - "auroc"', '  - "reader-alias"')
                .replace("A ROC curve plots", "Reader compares")
                .replace(
                    "A **ROC curve** plots the trade-off between two error "
                    "rates as a decision threshold moves.",
                    "**Reader** compares [[sub/sensitivity.md|Sensitivity]] "
                    "with [[unique-sensitivity|Sensitivity]] as two spellings "
                    "of one destination.")
                .replace("\nROC curve\n", "\nReader\n"))
        put("foo.md", named_good(
            "Foo", "foo-root", "Foo is the root ambiguous basename fixture.",
            "**Foo** is the root ambiguous basename fixture."))
        put("a/foo.md", named_good(
            "Foo", "foo-a", "Foo is the first ambiguous basename fixture.",
            "**Foo** is the first ambiguous basename fixture."))
        put("b/foo.md", named_good(
            "Foo", "foo-b", "Foo is the second ambiguous basename fixture.",
            "**Foo** is the second ambiguous basename fixture."))
        put("sub/path-reader.md", named_good(
            "Path reader", "path-reader-alias",
            "Path reader compares two path-qualified destinations.",
            "**Path reader** compares [[a/foo|one Foo]] with "
            "[[b/foo|another Foo]], while repeated ambiguous bare links "
            "[[foo]] and [[FOO.md|Foo]] remain unresolved."))
        put("sub/alias-reader.md", named_good(
            "Alias reader", "alias-reader-name",
            "Alias reader exercises an ambiguous alias.",
            "**Alias reader** compares [[auroc|one claimant]] with "
            "[[AUROC|another claimant]]."))
        put("sub/exact-path-reader.md", named_good(
            "Exact path reader", "exact-path-reader-name",
            "Exact path reader repeats one qualified destination.",
            "**Exact path reader** repeats [[a/foo|one Foo]] and "
            "[[A/FOO.md|the same Foo]]."))
        put("sub/footer-reader.md", named_good(
            "Footer reader", "footer-reader-name",
            "Footer reader has a deliberately noncanonical footer label.",
            "**Footer reader** exercises the canonical Related display check.")
            .replace("**Related:** [[precision|Precision]]",
                     "**Related:** [[Wiki/precision.md#Details|Positive predictive value]]"))
        report = lint_path(wiki)
        check("lint_path walks the folder recursively",
              report["summary"]["files"], 12)
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
        check("folder lint resolves an unambiguous alias before enforcing the "
              "one-body-link-per-entry rule",
              [sorted({f["item"] for f in e["findings"]})
               for e in report["entries"]
               if os.path.basename(e["file"]) == "reader.md"],
              [["10-duplicate-wikilink"]])
        check("folder lint keeps path-qualified duplicate basenames distinct",
              [f["item"] for e in report["entries"]
               if os.path.basename(e["file"]) == "path-reader.md"
               for f in e["findings"]
               if f["item"] == "10-duplicate-wikilink"],
              [])
        check("folder lint does not prescribe removal for a repeated ambiguous alias",
              [f["item"] for e in report["entries"]
               if os.path.basename(e["file"]) == "alias-reader.md"
               for f in e["findings"]
               if f["item"] == "10-duplicate-wikilink"],
              [])
        check("folder lint still catches a repeated exact qualified path",
              [f["item"] for e in report["entries"]
               if os.path.basename(e["file"]) == "exact-path-reader.md"
               for f in e["findings"]
               if f["item"] == "10-duplicate-wikilink"],
              ["10-duplicate-wikilink"])
        check("folder lint requires a Related target's canonical title",
              [f["item"] for e in report["entries"]
               if os.path.basename(e["file"]) == "footer-reader.md"
               for f in e["findings"]],
              ["11-related-display"])
        for newline in ("\r\n", "\r"):
            for relative in ("sub/reader.md", "sub/footer-reader.md"):
                with open(os.path.join(wiki, relative), encoding="utf-8") as handle:
                    original = handle.read()
                put(relative, original.replace("\n", newline).encode("utf-8"))
            newline_report = lint_path(wiki)
            check("folder snapshot checks preserve universal-newline semantics for %r" % newline,
                  {os.path.basename(e["file"]): [f["item"] for f in e["findings"]]
                   for e in newline_report["entries"]
                   if os.path.basename(e["file"]) in {"reader.md", "footer-reader.md"}},
                  {"reader.md": ["10-duplicate-wikilink"],
                   "footer-reader.md": ["11-related-display"]})
        put("sub/moc-reader.md", named_good(
            "MOC reader", "moc-reader-alias",
            "MOC reader exercises preserved map navigation.",
            "**MOC reader** keeps [[MOCs/statistics]] and "
            "[[MOCs/statistics#Methods|its methods map]]."))
        check("folder lint preserves repeated explicit MOC navigation too",
              [f["item"] for e in lint_path(wiki)["entries"]
               if os.path.basename(e["file"]) == "moc-reader.md"
               for f in e["findings"]
               if f["item"] == "10-duplicate-wikilink"], [])

        # A private review tree need not be named Wiki; `Wiki/`-qualified
        # links must still resolve there.
        review = os.path.join(tmp, "review-tree")
        review_entries = {
            "precision.md": precision,
            "wrong-footer.md": named_good(
                "Wrong footer", "wrong-footer-alias",
                "Wrong footer exercises a root-qualified footer link.",
                "**Wrong footer** exercises a root-qualified footer link.")
            .replace("[[precision|Precision]]",
                     "[[Wiki/precision|Positive predictive value]]"),
            "bare-footer.md": named_good(
                "Bare footer", "bare-footer-alias",
                "Bare footer exercises an unpiped footer link.",
                "**Bare footer** exercises an unpiped footer link.")
            .replace("[[precision|Precision]]", "[[precision]]"),
            "qualified-reader.md": named_good(
                "Qualified reader", "qualified-reader-alias",
                "Qualified reader repeats one root-qualified destination.",
                "**Qualified reader** compares [[Wiki/precision|Precision]] "
                "with [[precision|the positive predictive value]]."),
        }
        os.makedirs(review)
        for name, text in review_entries.items():
            with open(os.path.join(review, name), "w", encoding="utf-8") as fh:
                fh.write(text)
        review_report = lint_path(review)
        check("a review tree with another name resolves `Wiki/`-qualified links, "
              "and an unpiped footer link is reported once with its title",
              {os.path.basename(e["file"]): [
                  (f["item"], (f.get("evidence") or {}).get("expected_display"))
                  for f in e["findings"]]
               for e in review_report["entries"]},
              {"precision.md": [],
               "wrong-footer.md": [("11-related-display", "Precision")],
               "bare-footer.md": [("11-related-display", "Precision")],
               # A label sharing no surface with its target is item 18's
               # folder warning, as in wiki-lint's scanner.
               "qualified-reader.md": [("10-duplicate-wikilink", None),
                                       ("18-label-target", None)]})

        bom = put("bom.md", "﻿" + good.replace('title: "ROC curve"',
                                                    'title: "Bom"')
                  .replace("A ROC curve plots", "Bom records")
                  .replace("A **ROC curve** plots", "**Bom** plots")
                  .replace("\nROC curve\n", "\nBom\n"))
        check("a BOM does not defeat the parser (and skip all 13 checks)",
              _st_items(lint_file(bom)), [])
        binary = put("binary.md", b'---\ntitle: "Caf\xe9"\n---\nbody\n')
        check("a file that is not UTF-8 is reported and still linted",
              "0-encoding" in _st_items(lint_file(binary)), True)
        check("a missing path is a problem, not a traceback",
              lint_path(os.path.join(tmp, "nope"))["problems"] != [], True)
        from unittest.mock import patch
        race_wiki = os.path.join(tmp, "race-wiki")
        os.makedirs(race_wiki)
        race_note = os.path.join(race_wiki, "roc-curve.md")
        with open(race_note, "w", encoding="utf-8") as handle:
            handle.write(good)
        with open(os.path.join(race_wiki, "precision.md"), "w", encoding="utf-8") as handle:
            handle.write(precision)
        foreign_note = os.path.join(tmp, "foreign.md")
        foreign_text = good.replace(
            "decision threshold moves.",
            "decision threshold moves. Other bytes contain [[precision]] "
            "and [[precision]].").replace(
                "[[precision|Precision]]", "[[precision|Wrong title]]")
        with open(foreign_note, "w", encoding="utf-8") as handle:
            handle.write(foreign_text)
        original_alias_check = _check_alias_collisions

        def swap_after_guarded_reads(results):
            collisions = original_alias_check(results)
            os.unlink(race_note)
            try:
                os.symlink(foreign_note, race_note)
            except (OSError, NotImplementedError):
                with open(race_note, "w", encoding="utf-8") as handle:
                    handle.write(foreign_text)
            return collisions

        with patch.dict(globals(), {"_check_alias_collisions": swap_after_guarded_reads}):
            race_report = lint_path(race_wiki)
        check("folder checks never reread a changed path or later symlink after the guarded snapshot",
              [(os.path.basename(entry["file"]), entry["findings"])
               for entry in race_report["entries"]],
              [("precision.md", []), ("roc-curve.md", [])])
        check("folder lint leaves the later path and its foreign target untouched",
              open(race_note, encoding="utf-8").read(), foreign_text)
        def unreadable_walk(root, followlinks=False, onerror=None):
            if onerror:
                onerror(PermissionError(13, "permission denied", os.path.join(root, "private")))
            return iter(())
        with patch.object(os, "walk", unreadable_walk):
            inaccessible = lint_path(wiki)
        check("unreadable directories cannot certify the folder's alias audit clean",
              (inaccessible["summary"]["clean"], bool(inaccessible["problems"])), (False, True))

        floor = lint_path(wiki, severity_floor="error")
        check("--severity error drops warnings and info",
              sorted({f["severity"] for e in floor["entries"]
                      for f in e["findings"]}), ["error"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main([wiki, "-o", os.path.join(tmp, "out.json")])
        check("a delivered lint report exits 0 even when it contains findings",
              (rc, os.path.isfile(os.path.join(tmp, "out.json"))), (0, True))

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main([wiki, "-o", tmp])
        check("a requested report that cannot be written exits nonzero",
              (rc, '"ok": false' in buf.getvalue().lower()), (1, True))

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main([os.path.join(tmp, "missing")])
        check("an unreadable lint scope exits nonzero with its problem report",
              (rc, "no such file or folder" in buf.getvalue()), (1, True))
        check("a missing lint target reports summary.clean false",
              lint_path(os.path.join(tmp, "missing"))["summary"].get("clean"),
              False)

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
        description="Mechanical Quality Checklist checks for wiki-build "
                    "entries (stdlib only). Findings do not set the exit "
                    "status; an incomplete scope, a report-write failure or "
                    "a usage error does.",
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
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, OSError):
            pass
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
    report_complete = not report["problems"]
    dumped = json.dumps(report, ensure_ascii=False,
                        **({} if args.compact else {"indent": 2}))
    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(dumped + "\n")
            status = {"ok": report_complete,
                      "output": os.path.abspath(args.output),
                      "summary": report["summary"]}
            if not report_complete:
                status["error"] = "lint scope could not be read completely"
                status["problems"] = report["problems"]
            print(json.dumps(status, indent=2))
        except Exception as exc:
            print(json.dumps({"ok": False, "error": str(exc),
                              "summary": report["summary"]}, indent=2))
            return 1
    else:
        print(dumped)
    # Entry findings are a delivered report and therefore exit 0. Scope-level
    # read problems make the inventory incomplete, so callers must not treat
    # the report as a clean lint result.
    return 0 if report_complete else 1


if __name__ == "__main__":
    sys.exit(main())
