#!/usr/bin/env python3
"""Whole-vault scanner for the wiki-lint skill — Step 0, "Inventory the vault".

Parses every `Wiki/**/*.md` entry once (recursively, like wiki-build's
vault_index.py) and emits a single JSON object: the vault inventory, the
deterministic QC violations ("problems"), and the worklists the executing agent must
judge — the user's flagged issues (`user_issues`, the run's first worklist),
collision candidates (item-5 probes), rename candidates, backfill
candidates and hub footer items (Task 2), and card rivals (item 19) — plus the
Task 3 hierarchy diagnostic. Outside `Wiki/` it reads the MOCs, for the
advisory `spaced_repetition` report the Spaced Repetition plugin's settings
file, and with `--settled` wiki-lint's settled-decisions ledger; it never
writes any of them.

A file that cannot be read (not UTF-8, dangling symlink, permission error) is
reported as an `item0` problem and skipped; it never aborts the scan. Unknown
alias ownership suppresses alias-dependent link worklists until a clean rescan.

The scanner mechanizes every deterministic check. The executing agent handles
the remaining semantic judgments automatically during the wiki-lint run; no user or other human review is required. Nothing here is applied to the vault:
the candidate lists are worklists, not auto-fixes. See
references/scanner.md for the field-by-field output contract and for what the
scanner deliberately does not check.

Stdlib only, Python 3.10+ (the plugin runtime floor).

    python3 scripts/scan_vault.py /path/to/vault/Wiki \
        --vault /path/to/vault \
        --images /path/to/vault/Sources/Images \
        --out '<scratch>/wiki-scan-1.json'

`--images` is optional. It checks that every local image embed names a file in
`Sources/Images/` and emits report-only `image_folder_findings` for nested
paths, recognizable temporary/staging residue, unreadable scope, and grouped
portable-basename collisions. CONVENTIONS.md §§1 and 8 make this skill the
folder's read-only validator; no folder finding authorizes moving, renaming or
deleting a file.
"""

import argparse
import datetime
import hashlib
import json
import os
import posixpath
import re
import stat
import sys
import unicodedata
from collections import Counter, defaultdict


# Disciplines are the fixed tag enum (VALID_TAGS below).

# ===========================================================================
# NO SLUG IMPLEMENTATION LIVES HERE.  There is exactly one copy of the
# algorithm -- shared/scripts/slugify.py -- reached through the canonical
# bootstrap below (shared/CONVENTIONS.md §5).  A vendored copy used to sit in
# this spot, kept in sync by hand.
#
# Do NOT paste one back.  Drift is destructive, not cosmetic: the scanner
# proposes vault-wide renames from slug(), so a slug computed differently here
# from the one that named the file turns every correctly-named entry into a
# false rename candidate -- and two titles that collapse to one slug here (C++
# and C# both to "c") propose two renames onto the same destination, the second
# silently clobbering the first.
# `python3 shared/scripts/slugify.py --test` is the conformance suite.
# ===========================================================================

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

from slugify import (  # noqa: E402
    SlugError as _SlugError,
    base_term,
    has_parenthetical,
    slug_stem as _slug_stem,
)
from yaml_scalars import parse_scalar, split_flow, strip_comment  # noqa: E402
from note_provenance import split_provenance  # noqa: E402
from portable_names import portable_identity  # noqa: E402


def fold_name(s):
    """Portable case/Unicode identity for a slug or link target.

    The plugin treats case and normalization variants as one ownership class,
    then canonicalizes references to the exact on-disk spelling. This yields
    the same collision decision on filesystems that alias those spellings and
    ones that can store both; raw strings would make safety host-dependent.
    """
    return portable_identity(s or "")


# ===========================================================================
# NO SINGULARIZER LIVES HERE EITHER, and for the same reason.  The item-5
# `plural` and `word-order-singular` probes turn on which two word forms are
# the same word; wiki-build's find_collisions.py probes (c) and (e) turn on
# the same fact.  This file used to carry a three-rule regular-plural stripper
# of its own, which answered "hypotheses" with "hypothes" where wiki-build
# answered "hypothesis" -- so `hypothesis-testing` / `testing-hypotheses` was
# caught when wiki-build probed a NEW candidate against the vault and missed
# by the sweep here.  CONVENTIONS.md §9 gives whole-vault dedup detection to
# this skill alone, so a pair already sitting in the vault was reported by
# nobody at all.  `python3 shared/scripts/plurals.py --test` is the
# conformance suite.  Do NOT paste a copy back.
# ===========================================================================
from plurals import (  # noqa: E402
    real_permutation, singular_forms, singular_keys,
    stem_key, wordorder_key_singular,
)
from organism_names import (  # noqa: E402
    first_sentence,
    organism_title_classification,
)
from code_typography import find_bare_code_shapes  # noqa: E402
from equation_coverage import (  # noqa: E402
    find_boilerplate_candidates,
    find_display_spans,
    find_missing_display_equation_candidates,
    find_multi_relation_display_candidates,
    find_noncanonical_display_equation_candidates,
)
from entry_structure import (  # noqa: E402
    CARD_SEPARATORS,
    FLASH_HEAD_CANON_RE,
    FLASH_HEAD_LINE_RE,
    RELATED_HEAD_LINE_RE,
    markdown_image_spans,
    source_stem,
    strip_code,
    strip_fenced,
    strip_indented,
    answer_surface_match,
    body_opens_with_prose,
    count_sentences,
    ends_with_sentence_period,
    flashcard_brevity_hints,
    flashcard_hedge_hints,
    flashcard_line1_markup,
    flashcard_line1_faults,
    first_prose_paragraph,
    heading_repeats_title,
    is_review_metadata_block,
    math_title_plain_text,
    mask_body_comments,
    normalized_answer_surface,
    opener_subject_date_status,
    parse_flashcard_blocks,
    split_sentences,
    title_display_form,
    without_leading_title_heading,
)
from introduced_aliases import missing_introduced_aliases  # noqa: E402
from markdown_tables import (  # noqa: E402
    caption_faults,
    markdown_block_start,
    markdown_table_spans,
    mask_line_spans,
)
# Per-entry checks shared with wiki-build's lint_entry.py (one copy).
from entry_checks import (  # noqa: E402
    BARE_WORD_ALIAS_HINT,
    BOLD_OUTER_RE as _BOLD_OUTER_RE,
    BOLD_PAREN_RE,
    COMMON_NOUNS,
    CROSS_DOMAIN_PHRASES,
    EXTRA_CARD_PREFIX,
    PAREN_LEADIN_RE,
    SHARED_MUTATIONS,
    SHARED_QUIET,
    SOURCE_REFERENCE_FORMS,
    acronym_counterpart,
    acronym_expansion_missing,
    api_surface_findings,
    bare_common_noun_slug,
    bare_word_alias_candidate,
    bold_parts as _bold_parts,
    cross_domain_alias_findings,
    cross_domain_synonym_label,
    cross_domain_word,
    description_has_entity_subject,
    description_subject_findings,
    display_label_links,
    emphasis_span_findings,
    flashcard_line3_fault,
    flashcard_primary_answer,
    flashcard_set_faults,
    is_discipline_root,
    kept_card_label,
    label_drops_head,
    label_shares_surface,
    list_indent_findings,
    merge_scar_findings,
    organism_common_name_bound as _organism_common_name_bound,
    organism_common_name_surfaces as _organism_common_name_surfaces,
    plural_surface,
    primary_line3_faults,
    pure_math_opener_markup,
    source_meta_findings,
    source_reference_kind,
    sr_card_marker_faults,
    sr_marker_findings,
    unenumerated_bold_findings,
)
from vault_artifacts import looks_staging  # noqa: E402


def slug(title):
    """Slug stem for ``title``; "" when the title reduces to the empty slug.

    A thin wrapper over the canonical ``slugify.slug_stem``, which raises
    ``SlugError`` where this file's callers expect "".  An empty return means
    the title cannot be slugged automatically (a CJK/all-symbol title).
    Callers must NOT treat "" as a filename: renaming an entry to "" produces
    a file literally called ".md".
    """
    if not title:
        return ""
    try:
        return _slug_stem(str(title))
    except _SlugError:
        return ""


def _organism_fields(entry):
    """A record's ``(type, title, description, prose)`` for entry_checks."""
    entry = entry or {}
    return (entry.get("type"), entry.get("title"), entry.get("desc"),
            entry.get("prose"))


def organism_common_name_surfaces(entry):
    """Locally bound common names; link surfaces, never global aliases."""
    return _organism_common_name_surfaces(*_organism_fields(entry))


def organism_common_name_bound(entry, display):
    """Item 18's Organism common-name carve-out (shared with lint_entry)."""
    return _organism_common_name_bound(*_organism_fields(entry), display)


def leftover_dollars(body):
    # `strip_fenced`, not a backtick-only regex: markdown fences a block with
    # ``` OR ~~~, `strip_fenced` has always understood both, and this scan
    # understood only the first — so a `~~~` shell listing containing `$HOME`
    # was counted, and item 12's class-1 remediation writes `\$` into the
    # middle of the listing, corrupting the command it shows.
    s = strip_code(body)                              # every Markdown listing
    s = s.replace(r"\$", " ")                          # escaped \$
    s = re.sub(r"\$\$.*?\$\$", " ", s, flags=re.S)    # display math
    # A closing inline-math delimiter cannot be immediately followed by a
    # digit. Keeping that dollar visible distinguishes two currency amounts
    # (``$20 ... $30``) without misclassifying numeric math such as
    # ``$1 \\le k \\le m$`` or ``$1-e^{-1}$`` as currency.
    s = re.sub(r"(?<!\\)\$(?!\$)[^$\n]*\$(?!\d)", " ", s)
    return s.count("$")                              # literal dollars

# A standalone image-embed line (Obsidian ![[…png]] or Markdown ![](url))
# for the caption check. Detection runs against listing-masked text below;
# evidence and captions still come from the original lines.
EMB = re.compile(
    r"^\s*!\[\[[^\]\n]*\.(?:png|jpe?g|gif|svg|webp|tiff?|bmp|avif|ico)"
    r"(?:\|[^\]\n]*)?\]\]\s*$", re.IGNORECASE)


def markdown_link_spans(text):
    """Yield valid one-line inline/reference Markdown-link spans.

    The image parser already handles balanced labels, destinations, and
    optional titles. Prefixing a candidate ordinary link with ``!`` lets that
    same parser establish the full inline-link boundary without maintaining a
    second destination grammar. Full and collapsed reference links have no
    destination grammar; their second bracket is scanned directly. Shortcut
    references are deliberately left alone because ``[term]`` is ordinary
    prose unless a matching definition is resolved elsewhere.
    """
    value = text or ""
    consumed_to = 0
    for opener in re.finditer(r"\[", value):
        start = opener.start()
        if start < consumed_to:
            continue
        backslashes, index = 0, start - 1
        while index >= 0 and value[index] == "\\":
            backslashes += 1
            index -= 1
        if backslashes % 2:
            continue
        span_start = start
        if start > 0 and value[start - 1] == "!":
            bangs_backslashes, before_bang = 0, start - 2
            while before_bang >= 0 and value[before_bang] == "\\":
                bangs_backslashes += 1
                before_bang -= 1
            if bangs_backslashes % 2:
                continue
            span_start = start - 1

        depth, index, escaped = 1, start + 1, False
        while index < len(value) and value[index] != "\n":
            char = value[index]
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    break
            index += 1
        if depth:
            continue
        after_label = index + 1

        if after_label < len(value) and value[after_label] == "(":
            synthetic = "!" + value[start:]
            span = next(markdown_image_spans(synthetic), None)
            if span is not None and span[0] == 0:
                end = start + span[1] - 1
                consumed_to = end
                yield span_start, end
            continue

        if after_label < len(value) and value[after_label] == "[":
            index, escaped = after_label + 1, False
            while index < len(value) and value[index] != "\n":
                char = value[index]
                if char == "]" and not escaped:
                    end = index + 1
                    consumed_to = end
                    yield span_start, end
                    break
                escaped = char == "\\" and not escaped
                if char != "\\":
                    escaped = False
                index += 1


_MARKDOWN_REFERENCE_DEFINITION_LINE_RE = re.compile(
    r"^ {0,3}\[([^\]\n]+)\]:", re.MULTILINE)


def _reference_label_key(label):
    """CommonMark-like case/space identity for a reference-link label."""
    return " ".join(unicodedata.normalize("NFC", label or "").split()).casefold()


def markdown_reference_definition_labels(text):
    """Labels declared by link-reference-definition-shaped body lines."""
    return {
        _reference_label_key(match.group(1))
        for match in _MARKDOWN_REFERENCE_DEFINITION_LINE_RE.finditer(text or "")
        if _reference_label_key(match.group(1))
    }


def markdown_shortcut_reference_spans(text, labels):
    """Yield shortcut-reference link/image spans resolved in this document.

    A bare ``[term]`` is ordinary prose until the same document declares a
    matching ``[term]: destination``. Once resolved, neither its label nor an
    image alt label is a writable wiki-backfill surface.
    """
    value = text or ""
    if not labels:
        return
    consumed_to = 0
    for opener in re.finditer(r"\[", value):
        start = opener.start()
        if start < consumed_to or (start > 0 and value[start - 1] == "["):
            continue
        backslashes, before = 0, start - 1
        while before >= 0 and value[before] == "\\":
            backslashes += 1
            before -= 1
        if backslashes % 2:
            continue
        span_start = start
        if start > 0 and value[start - 1] == "!":
            bangs_backslashes, before_bang = 0, start - 2
            while before_bang >= 0 and value[before_bang] == "\\":
                bangs_backslashes += 1
                before_bang -= 1
            if bangs_backslashes % 2:
                continue
            span_start = start - 1

        depth, index, escaped = 1, start + 1, False
        while index < len(value) and value[index] != "\n":
            char = value[index]
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    break
            index += 1
        if depth:
            continue
        end = index + 1
        if end < len(value) and value[end] in "[(":
            continue
        label = value[start + 1:index]
        if _reference_label_key(label) in labels:
            consumed_to = end
            yield span_start, end


_MARKDOWN_URL_RE = re.compile(
    r"<https?://[^>\s]+>|(?<![A-Za-z0-9_])https?://[^\s<>]+",
    re.IGNORECASE)


def markdown_url_spans(text):
    """Yield bare URL/autolink spans that cannot contain a wikilink."""
    for match in _MARKDOWN_URL_RE.finditer(text or ""):
        yield match.span()


def mask_character_spans(text, spans, fill=" "):
    """Blank character spans while preserving offsets and line breaks."""
    chars = list(text or "")
    for start, end in spans:
        for index in range(max(0, start), min(end, len(chars))):
            if chars[index] != "\n":
                chars[index] = fill
    return "".join(chars)


def markdown_image_line(line):
    stripped = (line or "").strip()
    matches = list(markdown_image_spans(stripped))
    return bool(matches and matches[0][0] == 0 and matches[0][1] == len(stripped))
#: An Obsidian image EMBED and the filename it names, anywhere on a line:
#: `![[Doe_X_2025_fig_3.png]]`, with an optional `|width` display pipe. This is
#: the `--images` existence check's reader. Markdown `![](…)` embeds are
#: deliberately NOT here: a remote one is `item12/remote-image` (report-only,
#: and the form wiki-build mandates for a URL), and a local one is not a form
#: wiki-build writes.
IMG_EMBED = re.compile(
    r"!\[\[([^\]|\n]+\.(?:png|jpe?g|gif|svg|webp|tiff?|bmp|avif|ico))(?:\|[^\]\n]*)?\]\]", re.I)

_FIGURE_EXHIBIT_RE = re.compile(
    r"^(?P<prefix>.*?_(?i:fig)_?)(?P<label>(?i:S)?\d+(?:-\d+)*)"
    r"(?P<panel>[a-z]?)$")


def figure_exhibit_parts(filename):
    """Return ``(composite identity, panel letter)`` for a figure filename.

    The extension and vault path do not change exhibit identity. A lowercase
    terminal letter is the legacy panel marker; an empty marker is the
    composite. Unrelated image names return ``None``.
    """
    bare = (filename or "").strip().replace("\\", "/").rsplit("/", 1)[-1]
    stem, ext = os.path.splitext(bare)
    if not ext:
        return None
    match = _FIGURE_EXHIBIT_RE.match(stem)
    if not match:
        return None
    composite = fold_name(match.group("prefix") + match.group("label"))
    return composite, match.group("panel")


def local_image_destinations(body):
    """Local image filenames embedded in rendered body text."""
    masked = strip_code(body or "")
    names = [match.group(1) for match in IMG_EMBED.finditer(masked)]
    for _start, _end, destination in markdown_image_spans(masked):
        if re.match(r"(?:https?|data):", destination, re.IGNORECASE):
            continue
        names.append(destination.split("#", 1)[0].split("?", 1)[0])
    return names

def image_embed_lines(body):
    """Return original lines and real standalone embed indexes.

    ``strip_code`` preserves line positions while blanking fenced, indented and
    inline-code listings. A syntax sample therefore cannot create a caption
    repair finding, while caption markup remains visible in the original text.
    """
    original = body.split("\n")
    masked = strip_code(body).split("\n")
    return original, [i for i, line in enumerate(masked)
                      if EMB.match(line) or markdown_image_line(line)]


def markdown_tables(body):
    """Return ``(original_lines, [(header_index, last_row_index), ...])``.

    This is the deterministic CommonMark/GFM floor needed for caption checks,
    not a table renderer.  A body row may contain fewer cells than the header,
    including no pipe at all; the table ends at a blank, a new block, or this
    vault's whole-line italic caption.  The caption has to be immediate. Table
    positions come from fenced/indented-code masking. Inline code remains
    visible because GFM identifies pipe-separated cells before parsing inline
    spans; an unescaped pipe inside code is still a table separator. Caption
    text comes from the original lines so real backticks remain visible to
    ``caption_faults``.
    """
    original_lines = body.split("\n")
    return original_lines, markdown_table_spans(
        strip_indented(strip_fenced(body)))


# A cue may open a line, a list item's text or its indented continuation.
_NAVIGATION_ONLY_LINK_RE = re.compile(
    r"(?:^[ \t]*(?:(?:[-*+]|\d{1,9}[.)])[ \t]+)?|"
    r"[.!?,;:]\s+|\(\s*|[—–-]\s+)"
    r"(?:see(?:\s+also)?|refer\s+to|consult|"
    r"for\s+(?:more\s+)?details,?\s+see)\s+\[\[", re.IGNORECASE)


def navigation_only_link_lines(body):
    """Return prose lines whose directive cue points straight at a wikilink.

    This is a deterministic floor for item 9, not a flow classifier.  Code,
    figure/table material, and captions are excluded before matching.
    """
    raw_lines = (body or "").split("\n")
    masked_lines = strip_code(body or "").split("\n")
    skip = set()
    _raw, tables = markdown_tables(body or "")
    for header_i, end_i in tables:
        skip.update(range(header_i, min(len(raw_lines), end_i + 2)))
    _raw, embeds = image_embed_lines(body or "")
    for embed_i in embeds:
        skip.add(embed_i)
        skip.add(embed_i + 1)
    return [
        (i + 1, raw_lines[i].strip())
        for i, line in enumerate(masked_lines)
        if i not in skip
        and not re.match(r"^\s*\*.*\*\s*$", line)
        and _NAVIGATION_ONLY_LINK_RE.search(line)
    ]

def split_frontmatter(text, bad=None):
    # BOM only -- never whitespace: Obsidian reads properties only when the
    # opening fence is the very first line of the file, so a leading blank
    # line means the "frontmatter" renders as literal text.  The lenient
    # lstrip() here scanned such an entry as clean while a single-file
    # lint_entry run (and Obsidian itself) called it no-frontmatter.
    text = text.lstrip("\ufeff")
    if not text.startswith("---\n"): return None, text, False
    # The CLOSING fence is a line that is exactly `---`.  `find("\n---")`
    # accepted any line merely STARTING with three dashes -- `----`,
    # `--- text` -- swallowing the junk (and, for `----`, leaking the leftover
    # `-` into the body), so an entry whose broken fence Obsidian refuses to
    # parse scanned completely clean while lint_entry (whose parser requires
    # the exact line) reported item 1 on the same file.
    m = re.compile(r"(?m)^---[ \t]*$").search(text, 4)
    if m is None: return None, text, False
    if m.group(0) != "---" and bad is not None:
        bad.append("closing frontmatter fence has trailing whitespace; write exactly '---'")
    after = text[m.end():]                        # starts at the fence line's own "\n" (or EOF)
    body = after.lstrip("\n")
    # The blank lines between the fence and the body. Body line numbers add
    # them back, so line 1 is the line after the closing fence.
    blank_after = max(0, len(after) - len(body) - 1)
    return text[4:m.start()].strip("\n"), body, blank_after

# Key regex shared by parse_fm, the key_order scan and the item-2 quoting scan, so
# all three see the same keys, as vault_index's _KEY_RE does.  It admits digits,
# hyphens, spaces and non-ASCII letters ("f1-score:", "date modified:"); the old
# ^([A-Za-z_]+): silently dropped such keys, so an off-schema key with a digit in it
# was never reported and never counted as a duplicate.  As YAML requires, the
# colon must be followed by whitespace or end of line: `title:"x"` is not a key.
FM_KEY = re.compile(r"^([^\W\d][\w -]*?)\s*:(?=\s|$)(.*)$")
FM_ITEM = re.compile(r"^\s*-(?:\s+(.*)|\s*)$")

def unquote(raw):
    """Decode a validated YAML scalar; malformed input raises ValueError."""
    return parse_scalar(raw)[0]

def raw_scalar(fm_raw, key):
    """The literal text after `key:` in the frontmatter, or None if absent.

    `parse_fm` deliberately collapses a bare `parents:` and a flow-form
    `parents: []` to the same `[]` — for every consumer that wants the VALUE
    they are the same empty list.  Two item-2 checks want the SPELLING instead:
    a bare key is YAML null, which Obsidian renders as an empty text field
    rather than an empty list under the vault's `multitext` type, and a quoted
    `read: "false"` is a string that renders as a checked box.  Both are
    invisible to the parsed value and visible only here.
    """
    for line in fm_raw.split("\n"):
        m = FM_KEY.match(line)
        if m and m.group(1) == key:
            return strip_comment(m.group(2)).strip()
    return None


def has_block_items(fm_raw, key):
    """True when `key:` is followed by at least one `- item` line."""
    seen = False
    for line in fm_raw.split("\n"):
        m = FM_KEY.match(line)
        if m:
            seen = (m.group(1) == key)
            continue
        if seen and FM_ITEM.match(line):
            return True
    return False


#: A ``|`` or ``>`` block-scalar header with its optional indicators.
_ISSUES_BLOCK = re.compile(r"[|>](?:[1-9][+-]?|[+-][1-9]?)?")
#: An indented ``key:`` line, which starts a mapping under ``issues:``.
_ISSUES_KEY_LINE = re.compile(r"^\s+[^\s#\"'][^:]*:(?:\s|$)")
#: Malformed ``issues:`` shapes that are not YAML at all.
ISSUES_NOT_YAML = ("an unreadable value", "an unreadable flow list",
                   "a value followed by list items")
#: An unquoted ``#`` that YAML reads as a comment cuts the user's text off,
#: even to blank, so the value is malformed rather than read short.
ISSUES_COMMENT = "a YAML comment (an unquoted '#') that cuts its text off"


def _cuts_comment(raw):
    """Whether YAML reads part of one ``issues:`` value or item as a comment."""
    return strip_comment(raw).strip() != raw.strip()


class _IssuesShape(ValueError):
    """A malformed ``issues:`` value; ``str(exc)`` names its shape."""


def issues_spans(fm_raw):
    """``(start, end)`` frontmatter line spans owned by each ``issues:`` key.

    A span runs from the key line to the line before the next key, so it
    holds every continuation, list item, comment or stray line the value
    could own.  These lines are the user's text: the scanner keeps them out of
    the generic item-1 checks and reports a bad value only as
    `item2/issues-malformed`.
    """
    lines = fm_raw.split("\n")
    keys = [i for i, line in enumerate(lines) if FM_KEY.match(line)]
    return [(i, (keys[k + 1:] or [len(lines)])[0])
            for k, i in enumerate(keys)
            if FM_KEY.match(lines[i]).group(1) == "issues"]


#: The item-1 message for a frontmatter that only the Flashcards separator
#: closes; lint_entry reports the same defect as 1-valid-yaml.
FLASHCARDS_CLOSE_MESSAGE = (
    "frontmatter is not closed before the body: the '---' above "
    "'## Flashcards' closes it; restore an exact '---' after the last property")


def flashcards_close_frontmatter(fm_raw, body):
    """Whether only the separator above ``## Flashcards`` closes the frontmatter.

    With the closing fence lost, or spelled ``----`` or ``--- text``, the
    first exact ``---`` is that separator, and ``issues:``, the last key,
    owns the whole body. Two signs show it together: the body opens with the
    Flashcards heading, and an ``issues:`` span holds a column-0 line that is
    no key, list item or comment. The span stays the user's text either way;
    this only reports the lost fence as item 1.
    """
    first = next((line for line in body.split("\n") if line.strip()), "")
    if not FLASH_HEAD_LINE_RE.match(first):
        return False
    lines = fm_raw.split("\n")
    return any(line.strip() and not line[0].isspace()
               and not line.startswith("#")
               and not FM_KEY.match(line) and not FM_ITEM.match(line)
               for start, end in issues_spans(fm_raw)
               for line in lines[start + 1:end])


def _issues_text(raw, more):
    """One string written on one line as ``raw``; ``more`` holds the lines under it.

    Obsidian's Text property is one line (CONVENTIONS.md §2d): a ``|`` or
    ``>`` block scalar, a value that starts on the line after its key or
    dash, and a string continued on another line are malformed, as in
    wiki-build's draft linter.  Returns the value (``None`` for null);
    raises ValueError for a collection or text that is not one-line YAML.
    """
    rest = [line for line in more
            if line.strip() and not line.lstrip().startswith("#")]
    if any(not line[:1].isspace() for line in rest):
        raise ValueError("unindented text under issues:")
    if _ISSUES_BLOCK.fullmatch(raw):
        raise _IssuesShape("a block scalar")
    if rest:
        raise _IssuesShape("a string continued on another line" if raw
                           else "a value on the line after its key")
    if raw[:1] in ("[", "{"):
        raise ValueError("a collection")
    return parse_scalar(raw)[0]


def _issues_list(more):
    """The values of a block list under ``issues:``, one per item."""
    entries, dash = [], None
    for line in more:
        indent = len(line) - len(line.lstrip())
        if line.strip() and (dash is None or indent <= dash):
            if line.lstrip().startswith("#"):
                continue
            match = FM_ITEM.match(line)
            if not match or dash not in (None, indent):
                raise _IssuesShape("an unreadable value")
            if _cuts_comment(match.group(1) or ""):
                raise _IssuesShape(ISSUES_COMMENT)
            dash = indent
            entries.append((strip_comment(match.group(1) or "").strip(), []))
        elif entries:
            entries[-1][1].append(line)
    values = []
    for raw, lines in entries:
        rest = [line for line in lines
                if line.strip() and not line.lstrip().startswith("#")]
        if not raw and rest and FM_ITEM.match(rest[0]):
            raise _IssuesShape("a nested list")
        try:
            values.append(_issues_text(raw, lines))
        except ValueError:
            raise _IssuesShape("a list item that is not one string") from None
    return values


def issues_value(fm_raw):
    """Classify the user's `issues:` inbox (CONVENTIONS.md §2d).

    Returns ``(state, form, items, detail)``.  ``state`` is ``missing``,
    ``blank`` (bare, null, ``~``, a blank quoted string, ``[]``, or a list
    whose items are all blank or null), ``issues`` or ``malformed``.  For
    ``issues``, ``form`` is ``string`` (one plain or quoted line) or ``list``
    (block or one-line flow form) and ``items`` holds the decoded texts: the
    whole string, or one per non-blank list item.  A block scalar, a value
    continued on another line and a value or item that an unquoted ``#``
    comment cuts off are ``malformed``, as in wiki-build's draft linter.  For
    ``malformed``,
    ``detail`` names the shape; ``ISSUES_NOT_YAML`` lists those that are not
    YAML at all.  Nothing here rewrites a value.
    """
    spans = issues_spans(fm_raw)
    if not spans:
        return "missing", None, [], ""
    if len(spans) > 1:
        return "malformed", None, [], "a duplicate issues: key"
    lines = fm_raw.split("\n")
    start, end = spans[0]
    full = FM_KEY.match(lines[start]).group(2)
    if _cuts_comment(full):
        return "malformed", None, [], ISSUES_COMMENT
    raw = strip_comment(full).strip()
    more = lines[start + 1:end]

    def _body():
        return [line for line in more
                if line.strip() and not line.lstrip().startswith("#")]
    body, form = _body(), "list"
    try:
        if not raw and body and FM_ITEM.match(body[0]):
            values = _issues_list(more)
        elif not raw and body and _ISSUES_KEY_LINE.match(body[0]):
            raise _IssuesShape("a mapping")
        elif _ISSUES_BLOCK.fullmatch(raw):
            raise _IssuesShape("a block scalar")
        elif raw.startswith("{"):
            raise _IssuesShape("a mapping")
        elif raw and any(FM_ITEM.match(line) for line in body):
            raise _IssuesShape("a value followed by list items")
        else:
            if raw.startswith("["):
                if body:
                    raise _IssuesShape("a flow list continued on another line")
                try:
                    if not raw.endswith("]"):
                        raise ValueError("an unclosed flow list")
                    texts = split_flow(raw[1:-1])
                except ValueError:
                    raise _IssuesShape("an unreadable flow list") from None
                try:
                    values = [parse_scalar(text)[0] for text in texts]
                except ValueError:
                    raise _IssuesShape(
                        "a list item that is not one string") from None
            else:
                form, values = "string", [_issues_text(raw, more)]
    except _IssuesShape as exc:
        return "malformed", None, [], str(exc)
    except ValueError:
        return "malformed", None, [], (
            "a value followed by list items"
            if any(FM_ITEM.match(line) for line in body)
            else "an unreadable value")
    items = [value for value in values
             if isinstance(value, str) and value.strip()]
    return ("issues", form, items, "") if items else ("blank", None, [], "")


def parse_fm(fm, bad=None):
    """Frontmatter -> {key: str | [str]}.

    Handles block-form lists, flow-form lists, and blank fields. A flow list
    must remain a list so its values participate in validation, alias
    resolution, and backfill.

    `bad`, when given, collects every non-blank line that is neither a key nor
    a list item under a list key — an indented/nested key, stray prose, an
    orphan `- item`.  Silently dropping one hid an invalid frontmatter line
    from the whole scan (no item1, no anything) while a single-file lint_entry
    run reported it.
    """
    d, key = {}, None
    for line in fm.split("\n"):
        if not line.strip() or line.lstrip().startswith("#"): continue
        mi = FM_ITEM.match(line)
        if mi and key is not None and isinstance(d.get(key), list):
            val = (mi.group(1) or "").strip()
            try:
                d[key].append(unquote(val))
            except ValueError:
                if bad is not None: bad.append(line)
                d[key].append(None)
            continue
        m = FM_KEY.match(line)
        if not m:
            if bad is not None: bad.append(line)
            continue
        key, raw = m.group(1), strip_comment(m.group(2)).strip()
        if raw == "":
            d[key] = []                                  # blank, or a block list to follow
        elif raw.startswith("[") and raw.endswith("]"):
            values = []
            try:
                flow_items = split_flow(raw[1:-1])
            except ValueError:
                if bad is not None: bad.append(line)
                flow_items = []
            for item in flow_items:
                try:
                    values.append(unquote(item))
                except ValueError:
                    if bad is not None: bad.append(line)
                    values.append(None)
            d[key] = values
            key = None                                   # a flow list ends on its own line
        else:
            try:
                d[key] = unquote(raw)
            except ValueError:
                if bad is not None: bad.append(line)
                d[key] = None
            key = None
    return d


WIKILINK = re.compile(
    r"(?<!\!)\[\[([^\]\|]+?)(?:\\?\|([^\]]+))?\]\]")  # (?<!!) excludes ![[embeds]]
ANYLINK  = re.compile(r"!?\[\[[^\]]*\]\]")                          # links + embeds, for masking
REDUNDANT_PIPE = re.compile(
    r"(?<!!)\[\[(?P<target>[^\[\]\n|#^/\\]+)\|(?P=target)\]\]")


def entry_link_path_key(raw):
    """Fold a body/Related target while retaining its vault path.

    An explicit ``.md`` suffix, anchors, case and Unicode normalization do not
    create different Obsidian destinations.  Path qualification is retained
    because two files in different folders may share a basename.
    """
    target = raw.split("#", 1)[0].split("^", 1)[0].strip()
    target = target.replace("\\", "/").strip().strip("/")
    prefix, separator, bare = target.rpartition("/")
    if bare.lower().endswith(".md"):
        bare = bare[:-3]
    return fold_name(prefix + separator + bare)


def entry_link_key(raw):
    """Fold a body/Related target to the entry basename it addresses."""
    return entry_link_path_key(raw).rsplit("/", 1)[-1]


def section_marker_indexes(body):
    """Return raw lines plus rendered Related/Flashcards marker indexes.

    Fenced samples are blanked with line count preserved. A slightly
    noncanonical marker is still treated as present so the repair normalizes
    that marker instead of adding a duplicate section beside it.
    """
    lines = body.split("\n")
    masked = strip_fenced(body).split("\n")
    related = [i for i, line in enumerate(masked)
               if RELATED_HEAD_LINE_RE.match(line)]
    flashcards = [i for i, line in enumerate(masked)
                  if FLASH_HEAD_LINE_RE.match(line)]
    return lines, related, flashcards

def regions(body):
    """``(prose, related_line, flashcards_section, flash_off, flash_head)``.

    The Related line and the Flashcards heading are located on the
    FENCED-STRIPPED text (line count preserved, so raw offsets line up): a
    ``**Related:**`` or ``## Flashcards`` shown inside a listing is a sample,
    not a section, and reading it as one truncated the entry's prose there —
    the sample was parsed as the real footer/section (phantom findings whose
    fix edits the listing) while the text past the fence, real findings
    included, vanished from every prose scan.  ``flash_off`` is the heading's
    character offset in the RAW body (−1 when absent); ``flash_head`` is the
    heading line as spelled.
    """
    lines, related_indexes, flashcard_indexes = section_marker_indexes(body)
    rel_i = related_indexes[0] if related_indexes else None
    flash_i = flashcard_indexes[0] if flashcard_indexes else None
    offs, pos = [], 0
    for ln in lines:
        offs.append(pos); pos += len(ln) + 1
    visible_body = mask_body_comments(body)
    rel = visible_body.split("\n")[rel_i].rstrip() if rel_i is not None else ""
    cut = len(body)
    if rel_i is not None: cut = offs[rel_i]
    fc = offs[flash_i] if flash_i is not None else -1
    if fc != -1 and fc < cut: cut = fc
    flash_head = lines[flash_i] if flash_i is not None else ""
    return visible_body[:cut], rel, (body[fc:] if fc != -1 else ""), fc, flash_head

# `importance` is a LEGACY key — removed from wiki-build's schema, never written on a new entry,
# but still present (populated) on every entry generated before the removal. Nothing strips it and
# nothing flags it. It stays in CANON so a legacy entry carrying it in its historical slot is not
# reported as an "unexpected frontmatter key" or as out of schema order; it is deliberately absent
# from the required-key checks and from the never-quoted list below.
CANON = ["title","type","aliases","sources","created","updated","description","tags","importance","parents","read","issues"]

#: The keys that must be PRESENT on every entry — CANON minus
#: the one optional key (`aliases`) and the retired one (`importance`).  This
#: is wiki-build's `lint_entry.MANDATORY_KEYS`, in the same order and with
#: the same members; the two lists say the same thing about the same schema and
#: a vault-wide run must not report fewer missing keys than a single-file lint.
#: Only four of the nine used to be checked here, so an entry with no `title:`
#: produced ZERO findings from this whole scan — item 5 and item 16 are both
#: gated on a title, and it also drops out of `surf_map`, `title_forms` and
#: `rename_candidates`, so nothing backfills toward it and every
#: `[[slug|label]]` aimed at it passes the item-18 label test unconditionally.
MANDATORY_KEYS = [k for k in CANON if k not in ("aliases", "importance")]

#: The bare YAML booleans `read:` may carry.  A quoted "false" is a STRING, and
#: Obsidian's checkbox property renders any non-empty string as checked — so a
#: note the user has not read displays as read, silently, which is the one
#: failure this field cannot afford.  CONVENTIONS.md §2c.
READ_BOOLEANS = {"true", "false"}

#: The spellings of YAML null a `read:` key can carry: a bare key, `null` in any
#: case, and `~`.  These are NOT a type error — there is no value in them to
#: retype — so they route with the missing key, not with `read: yes`.  See the
#: `read:` block in `scan()`.
READ_NULLS = {"", "null", "~"}

#: The two cases that do write a missing, null or unknown `read:` (CONVENTIONS
#: §2c), appended to each report-only `read:` message; `%s` names the write.
READ_EXCEPTIONS = ("The exceptions (CONVENTIONS §2c): resolving one of the "
                   "entry's user_issues, or keeping it as a merge's survivor, %s")
_YAML_TYPED_PLAIN_RE = re.compile(
    r"^(?:null|~|true|false|yes|no|on|off|\.nan|[+-]?\.inf|"
    r"[+-]?(?:0|[1-9][0-9_]*)(?:\.[0-9_]*)?(?:e[+-]?[0-9]+)?|"
    r"[0-9]{4}-[0-9]{2}-[0-9]{2})$", re.IGNORECASE)
VALID_TYPES = [
    "Concept", "Person", "Organization", "Dataset", "Software", "Device",
    "Event", "Standard", "Gene/Protein", "Organism", "Chemical", "Reaction",
    "Place", "Work", "Quote",
]
VALID_TAGS = {"mathematics","statistics","physics","chemistry","biology","earth-science",
 "medicine","engineering","computer-science","psychology","sociology","anthropology",
 "economics","finance","political-science","linguistics","history","philosophy","literature","law",
 "business","entrepreneurship","education","architecture","art","music","machine-learning",
 "misc"}  # discipline enum, including the sole-tag fallback
TAG_ALIASES = {"ml":"machine-learning","ai":"machine-learning","artificial-intelligence":"machine-learning",
 "cs":"computer-science","comp-sci":"computer-science","poli-sci":"political-science",
 "econ":"economics","bio":"biology","chem":"chemistry","phys":"physics",
 "stats":"statistics","math":"mathematics","maths":"mathematics","lit":"literature",
 "investing":"finance","trading":"finance",
 "startup":"entrepreneurship","startups":"entrepreneurship"}  # safe auto-expansions

#: A generated MOC is `MOCs/<discipline>-moc.md`. The suffix keeps its basename
#: apart from the discipline's Wiki root (`Wiki/biology.md`), so a link to the
#: root is an ordinary bare `[[biology]]`. A previous-layout MOC is
#: `MOCs/<discipline>.md`; that layout is inventoried as legacy.
MOC_SUFFIX = "-moc"


def moc_stem(discipline):
    """Basename, without `.md`, of a discipline's generated MOC."""
    return discipline + MOC_SUFFIX


def moc_discipline(stem):
    """The discipline a canonical MOC basename names, else None."""
    folded = fold_name(stem)
    if folded.endswith(MOC_SUFFIX) and folded[:-len(MOC_SUFFIX)] in VALID_TAGS:
        return folded[:-len(MOC_SUFFIX)]
    return None


#: Task 3 appends a parent's missing children to its Related footer up to this
#: many links (hierarchy.md, *Populate parents*).
FOOTER_CHILD_CAP = 12
HUB_FOOTER_MIN = 15
HUB_FOOTER_DIVISOR = 20


def hub_footer_min(entry_count):
    """Footer count at which a target is listed in ``hub_footer``."""
    return max(HUB_FOOTER_MIN, entry_count // HUB_FOOTER_DIVISOR)


def _record_is_discipline_root(slug_value, record):
    """Apply the shared root predicate to one parsed scan record.

    Tags count only when the frontmatter held one readable tag key with a
    single enum value, so a malformed or duplicated key never makes a root.
    """
    return is_discipline_root(
        slug_value,
        record.get("tags_raw") if record.get("tags_valid_single") else None,
        VALID_TAGS)

#: Frontmatter keys that are Obsidian's own, not this schema's. They are NOT
#: `item2` "unexpected key" findings: item 2 is a class-1 fix-in-place, and the
#: only determinate reading of "fix an unexpected key in place" is to delete it
#: — which throws away app/publish configuration the USER set, in a field this
#: plugin never writes and cannot reconstruct. They route report-only through
#: `item2/obsidian-key` instead. A genuinely off-schema key (`mood:`, a
#: stacked-merge scar) is still a plain `item2`.
OBSIDIAN_KEYS = {"cssclasses", "cssclass", "publish", "permalink", "cover",
                 "image", "banner", "icon"}


def _plain_item_allowed(key, value):
    """List items that may stay plain: aliases, and a web source's URL.

    Obsidian's Properties editor strips the quotes from both on every save,
    while a vault link under sources, a tag or a parent keeps them (they are
    load-bearing there), so re-quoting the URL would churn on every review.
    """
    return key == "aliases" or (
        key == "sources" and isinstance(value, str)
        and re.match(r"https?://", value) is not None)


def plain_string_allowed(value, style):
    """Whether a conservative letter-led plain scalar stays a YAML string."""
    return (style == "bare" and isinstance(value, str) and bool(value)
            and value[:1].isalpha()
            and not _YAML_TYPED_PLAIN_RE.fullmatch(value.strip())
            and not re.search(r":(?:\s|$)|\s#", value))


def tag_canonical(tag_slug):
    """The enum slug a raw tag slug denotes: alias expanded, case folded.

    The duplicate-tag check has to run on THIS, not on the raw slug. `#ml` and
    `#machine-learning` are two raw slugs and one discipline: the raw check saw
    no duplicate, while item 8's own mandated fix ('rewrite as
    "#machine-learning"') then produced the duplicate it had just certified
    absent. Same for a case variant — `#Machine-Learning` folds onto
    `#machine-learning`.  Returns the raw slug lowercased when it denotes
    nothing in the enum, so an off-enum tag still groups with itself.
    """
    low = (tag_slug or "").lower()
    if low in VALID_TAGS:
        return low
    return TAG_ALIASES.get(low, low)


WORD = re.compile(r"[A-Za-z0-9]+")

def _index_surfaces(surf_map):
    """Group surface forms by their token sequence: "roc curve" -> [surface, ...].

    Each entry keeps the surface's leading offset (the count of non-alphanumeric
    characters before its first token) so the literal text can still be verified
    against the document -- a surface is only a hit when it appears VERBATIM,
    exactly as the old alternation required.
    """
    by_tokens, maxwords = {}, 0
    for s in surf_map:
        # Plurals and aliases cannot make a forbidden bare destination safe:
        # excluding only "entropy" still proposed [[entropy|entropies]]. A
        # cross-domain phrase ("tree of life") is excluded like a set word,
        # and so is a floor word's plural surface ("targets").
        if (bare_common_noun_slug(s)
                or bare_common_noun_slug(fold_name(surf_map[s]))):
            continue
        m = list(WORD.finditer(s))
        if not m: continue
        key = " ".join(t.group(0) for t in m)
        if key in CROSS_DOMAIN_PHRASES: continue
        by_tokens.setdefault(key, []).append((s, m[0].start()))
        maxwords = max(maxwords, len(m))
    for cands in by_tokens.values():       # longest surface first, as the alternation was
        cands.sort(key=lambda sc: -len(sc[0]))
    return by_tokens, maxwords


def _boundary_ok(low, start, end):
    """Both edges must sit on a non-[A-Za-z0-9] boundary (the old lookarounds)."""
    if start > 0 and low[start-1].isascii() and low[start-1].isalnum(): return False
    if end < len(low) and low[end].isascii() and low[end].isalnum(): return False
    return True


def _scan_surface_spans(text, by_tokens, maxwords):
    """Yield ``(start, end, surface, matched_text)`` for every surface hit.

    Replaces a single regex alternation over EVERY surface form, which was
    re-run against every entry: that is O(entries x surfaces), measured at 84s
    for 2000 entries and extrapolating to ~40 min at 10000.  This tokenizes the
    text once and looks n-grams up in a dict, i.e. O(total tokens) with the
    surface count entering only through `maxwords`.

    Semantics are identical to the alternation it replaces, which is why the
    matches are collected and then resolved rather than taken greedily: an
    alternation sorted longest-first picks the LEFTMOST match, breaks ties by
    length, and never overlaps a previous match.  Anchoring on tokens alone got
    that wrong when one surface starts with punctuation and another starts one
    character later ("(cross)" vs "cross) foo").
    """
    toks = [(m.group(0).lower(), m.start(), m.end()) for m in WORD.finditer(text)]
    low = text.lower()
    if len(low) != len(text):
        # `İ` (U+0130) lowercases to two code points, which would shift every
        # later offset off the token positions taken from `text`.
        low = "".join(c.lower() if len(c.lower()) == 1 else c for c in text)
    n = len(toks)
    hits = []
    for i in range(n):
        for k in range(1, min(maxwords, n - i) + 1):
            cands = by_tokens.get(" ".join(t[0] for t in toks[i:i + k]))
            if not cands: continue
            for surface, lead in cands:
                start = toks[i][1] - lead
                end = start + len(surface)
                if start < 0 or low[start:end] != surface: continue
                if not _boundary_ok(low, start, end): continue
                hits.append((start, -len(surface), surface, end))
    last_end = 0
    for start, _neg, surface, end in sorted(hits):   # leftmost, then longest
        if start < last_end: continue                # non-overlapping, as re.finditer is
        last_end = end
        yield start, end, surface, text[start:end]


#: Words that introduce a field name without forming a compound with it:
#: "in machine learning", "the biology of", "and statistics".
_NON_MODIFIER_WORDS = frozenset("""
    a an the of in on for to with by from as at into onto over under about
    across between within without and or nor but than then so its it their our
    your his her this that these those which who whose what where when while
    if whether is are was were be been being each every any all some no not
    both either neither such other another same via per like unlike
""".split())


def _compound_modifier_before(text, start):
    """Whether the word right before ``start`` forms a compound with it.

    A discipline-root title directly after a modifier ("cell biology",
    "summary statistics", "molecular biology's") names a subfield or a
    different sense, so it fails surface identity with the root itself.
    """
    match = re.search(r"([A-Za-z][A-Za-z-]*)[ \t]*\n?[ \t]*$", text[:start])
    if not match or match.end() != start:
        return False
    return match.group(1).lower() not in _NON_MODIFIER_WORDS


def _root_named_as_setting_or_genus(text, start, end):
    """'In machine learning, …', 'for biology', 'a machine learning system'.

    A discipline root named only as the setting or genus of something else
    fails the closeness bar. "Of" and "to" stay out: "a branch of biology"
    places the subject within the field.
    """
    before = text[:start]
    if re.search(r"\b(?:in|for|within|across)\s+(?:the\s+)?$", before, re.I):
        return True
    return bool(re.search(r"\b(?:a|an|the)\s+$", before, re.I)
                and re.match(r"\s+[a-z]", text[end:]))


# Italic spans (`*term*`, `_term_`), for the late-link exclusions below.
_ITALIC_SPAN_RE = re.compile(
    r"(?<![*\w])\*(?![*\s])([^*\n]+?)(?<![\s*])\*(?![*\w])"
    r"|(?<![_\w])_(?![_\s])([^_\n]+?)(?<![\s_])_(?![_\w])")


def _italic_inner_spans(text):
    """``(start, end)`` of the text inside each italic span of ``text``."""
    spans = []
    for match in _ITALIC_SPAN_RE.finditer(text):
        group = 1 if match.group(1) is not None else 2
        spans.append((match.start(group), match.end(group)))
    return spans


# Bold spans (`**term**`): the title slot or a `- **Term** —` bullet anchor.
_BOLD_SPAN_RE = re.compile(
    r"(?<!\*)\*\*(?![*\s])([^*\n]+?)(?<![\s*])\*\*(?!\*)")


def _bold_inner_spans(text):
    """``(start, end)`` of the text inside each bold span of ``text``."""
    return [match.span(1) for match in _BOLD_SPAN_RE.finditer(text)]


#: Hyphen, Unicode hyphen, non-breaking hyphen and en dash: joined directly to
#: a surface, each makes it part of a compound (`protein-coding`,
#: `multioutput–multiclass`) rather than a separate mention.
_COMPOUND_DASHES = "-\u2010\u2011\u2013"


def _late_link_index(displays):
    """Token index for first-link display surfaces (common nouns included).

    Unlike the backfill index, a common-noun display such as ``model`` stays:
    the entry itself has already bound that word to the linked target.
    """
    by_tokens, maxwords = {}, 0
    for surface in displays:
        m = list(WORD.finditer(surface))
        if not m or len(surface) < 3:
            continue
        key = " ".join(t.group(0) for t in m)
        by_tokens.setdefault(key, []).append((surface, m[0].start()))
        maxwords = max(maxwords, len(m))
    for cands in by_tokens.values():
        cands.sort(key=lambda sc: -len(sc[0]))
    return by_tokens, maxwords


#: A line that starts its own block: a list item, quote, heading or table row.
_BLOCK_START_RE = re.compile(r"[ \t]*(?:[-*+][ \t]|\d+[.)][ \t]|>|#|\|)")


def settle_context(text):
    """SHA-1 hex digest of ``text`` with its whitespace collapsed."""
    return hashlib.sha1(" ".join((text or "").split()).encode("utf-8")).hexdigest()


def _sentence_at(text, offset):
    """The whitespace-collapsed sentence of ``text`` that holds ``offset``.

    The sentence is split from its block: the run of non-blank lines around
    ``offset``, cut where a list item, quote, heading or table row starts.
    """
    lines = text.split("\n")
    line_i = text.count("\n", 0, offset)
    first = last = line_i
    while (first > 0 and lines[first - 1].strip()
           and not _BLOCK_START_RE.match(lines[first])):
        first -= 1
    while (last + 1 < len(lines) and lines[last + 1].strip()
           and not _BLOCK_START_RE.match(lines[last + 1])):
        last += 1
    block_start = sum(len(line) + 1 for line in lines[:first])
    block = "\n".join(lines[first:last + 1])
    before = block[:offset - block_start]
    position = len(" ".join(before.split()))
    if position and before[-1:].isspace():
        position += 1
    compact = " ".join(block.split())
    cursor = 0
    for sentence in split_sentences(block):
        found = compact.find(sentence, cursor)
        if found < 0:
            break
        cursor = found + len(sentence)
        if position < cursor:
            return sentence
    return compact


def build_backfill(entries, surf_map, non_entry_bare_targets=(), resolve_target=None,
                   root_targets=frozenset(), late_links=None,
                   quiet_surfaces=frozenset(), base_only_surfaces=frozenset()):
    """Task 2 worklist: bare-text mentions of another entry's surface forms.

    ``root_targets`` are discipline-root slugs: a root surface directly after a
    modifier word ("cell biology") is a compound, so it is neither proposed nor
    counted as an earlier mention. When ``late_links`` is a list, it receives
    ``(slug, target, matched, surface)`` for each linked target whose first
    body link follows an earlier plain mention of the target's title, alias or
    first-link display label; ``quiet_surfaces`` (alias-only bare nouns of
    qualified destinations) never count as such a mention, and neither does
    the word of a first-link label that is a cross-domain synonym its target
    introduces. ``base_only_surfaces``, the quiet surfaces reached only
    through a parenthetical title's base term, still count as a mention of a
    first-link label they spell.

    Returns ``(slug, target, matched, surface, line, context)`` rows, one per
    target and sentence, in text order: the first eligible occurrence in that
    sentence, its 1-based body line, and the :func:`settle_context` of the
    sentence. :func:`apply_settled` keeps the first unsettled one per target.
    """
    by_tokens, maxwords = _index_surfaces(surf_map)
    backfill = []
    if not by_tokens:
        return backfill
    files = {fold_name(sl): sl for sl in entries}
    alias_owners = {}
    for sl, e in entries.items():
        for alias in e.get("aliases", []):
            alias_owners.setdefault(fold_name(alias), set()).add(sl)
    for sl, e in entries.items():
        # Table links are prohibited and will be reduced to plain text by item
        # 10, so they cannot prove that the entry already has a durable prose
        # link. Mask the shared spans before both the existing-link inventory
        # and the bare-surface scan; otherwise a bad cell link suppresses a
        # legitimate proposal for a later prose mention.
        prose = mask_line_spans(
            strip_code(e["prose"]), e.get("table_spans", ()))
        # The settle context hashes the sentence as written, each wikilink
        # reduced to its visible text, so linking another candidate in the
        # same sentence keeps the key.
        sentence_text = (e["prose"] if len(e["prose"]) == len(prose)
                         else prose)
        linked = set()
        first_link = {}                   # owner -> (offset, display) of its first link
        for link in WIKILINK.finditer(prose):
            target = link.group(1).split("#", 1)[0].split("^", 1)[0].strip()
            owner = None
            if resolve_target is not None:
                owner = resolve_target(target, e)
            else:
                path_key = entry_link_path_key(target)
                if (path_key.startswith("mocs/")
                        or ("/" not in path_key
                            and path_key in non_entry_bare_targets)):
                    continue
                target = target.replace("\\", "/").rsplit("/", 1)[-1]
                if target.lower().endswith(".md"):
                    target = target[:-3]
                key = fold_name(target)
                owner = files.get(key)
                if owner is None and len(alias_owners.get(key, ())) == 1:
                    owner = next(iter(alias_owners[key]))
            if owner is not None:
                linked.add(owner)
                first_link.setdefault(
                    owner, (link.start(), (link.group(2) or "").strip()))
        masked = ANYLINK.sub(lambda m: " "*len(m.group(0)), prose)
        # A target name used as an image's alt text or as an existing
        # Markdown-link label is already presentation/navigation syntax. A
        # proposed wikilink cannot be nested there, so mask the complete spans
        # before looking for the first writable occurrence.
        masked = mask_character_spans(
            masked,
            [(start, end) for start, end, _destination
             in markdown_image_spans(masked)])
        masked = mask_character_spans(masked, markdown_link_spans(masked))
        reference_labels = markdown_reference_definition_labels(prose)
        masked = mask_character_spans(
            masked, markdown_shortcut_reference_spans(masked, reference_labels))
        masked = mask_character_spans(masked, markdown_url_spans(masked))
        # A wikilink cannot be written inside LaTeX math, display or inline,
        # but a surface that holds a whole math span (a LaTeX title) can be.
        math_spans = [m.span() for m in re.finditer(r"\$\$.*?\$\$", masked, re.S)]
        math_spans += [m.span() for m in _DUPLICATE_INLINE_MATH_RE.finditer(
            mask_character_spans(masked, math_spans))]

        def _in_math(start, end):
            return any(ms < end and start < me and not (start <= ms and me <= end)
                       for ms, me in math_spans)

        reference_definition_lines = {
            line_i for line_i, line in enumerate(prose.split("\n"))
            if _MARKDOWN_REFERENCE_DEFINITION_LINE_RE.match(line)
        }
        # Blank every line a link may not be written on, for the same reason in
        # each case: the backfill worklist proposes linking the FIRST occurrence,
        # so a first occurrence sitting somewhere unlinkable is an un-actionable
        # item that also HIDES the linkable occurrence further down.
        #   * whole-line italic captions — item 12 forbids wikilinks in captions;
        #   * markdown TABLE ROWS — item 10 forbids wikilinks in table cells;
        #   * body headings — headings are plain text by item 9;
        #   * Setext heading text — the underline is itself an item-9 defect;
        #   * fenced code blocks — a listing is shown, not asserted, and a link
        #     written inside one renders as literal `[[...]]` text.
        # Blanked lines keep their length so offsets still line up with
        # `prose`, where the first-link positions below were taken.
        masked_lines = masked.split("\n")
        for line_i, line in enumerate(masked_lines):
            if (re.match(r"^\s*\*(?!\*).*\*\s*$", line)
                    or re.match(r"^ {0,3}#{1,6}(?:[ \t]+|$)", line)
                    # A link-reference definition is Markdown metadata. Its
                    # label is not writable body prose, so it must not become
                    # an un-actionable backfill target.
                    or line_i in reference_definition_lines):
                masked_lines[line_i] = " " * len(line)
            if (line_i > 0 and masked_lines[line_i - 1].strip()
                    and re.fullmatch(r" {0,3}(?:=+|-+)[ \t]*", line)):
                masked_lines[line_i - 1] = " " * len(masked_lines[line_i - 1])
                masked_lines[line_i] = " " * len(line)
        masked = "\n".join(masked_lines)
        proposed = {}                     # target -> contexts already proposed
        late = set()
        global_hits = []
        # A `_` or `*` inside LaTeX (`$\hat{y}_{i}$`, `$\theta^*$`) is not an
        # emphasis delimiter. Fill math with a word character, not a space,
        # so an italic that starts with math (`*$k$-fold ...*`) still opens.
        emphasis_text = mask_character_spans(masked, math_spans, fill="x")
        italic_spans = _italic_inner_spans(emphasis_text)
        bold_spans = _bold_inner_spans(emphasis_text)

        def _inside_longer_term(start, end):
            """Whether a hit is part of a longer term, so no link can carry it.

            A word inside a hyphen or dash compound (`batch GD` in
            `mini-batch GD`, `protein` in `protein-coding`) or inside a longer
            italic or bold term (`*blending training set*`, a bolded title
            opener, `- **Blending training set** —`). Both the backfill
            proposal and the late-link check skip such a hit.
            """
            if ((start > 0 and masked[start - 1] in _COMPOUND_DASHES)
                    or (end < len(masked) and masked[end] in _COMPOUND_DASHES)):
                return True
            return any(inner_start <= start and end <= inner_end
                       and inner_end - inner_start > end - start
                       for inner_start, inner_end in italic_spans + bold_spans)

        title_words = set()
        for token in WORD.findall(e.get("title") or ""):
            title_words |= singular_forms(token.lower())
        own_terms = []
        for inner_start, inner_end in italic_spans:
            words = [w.lower() for w in WORD.findall(masked[inner_start:inner_end])]
            if words and all(singular_forms(w) & title_words for w in words):
                own_terms.append([singular_forms(w) for w in words])

        def _own_title_term(start, end):
            """Whether a hit names a facet this entry defines from its title.

            An entry that sets words of its own title in italics (a
            Bias/variance trade-off bullet's `*Variance*`) defines them as its
            own facet, which other entries may use as a label for this entry
            (`[[bias-variance-trade-off|variance]]`). Throughout the entry the
            words then name that facet ("high variance"), so neither the
            backfill proposal nor the late-link check counts them as a
            mention of another target.
            """
            words = [w.lower() for w in WORD.findall(masked[start:end])]
            return any(len(term) == len(words)
                       and all(forms & singular_forms(word)
                               for forms, word in zip(term, words))
                       for term in own_terms)

        def _earlier_mention(owner, start, end, surface, quiet=quiet_surfaces):
            """A plain mention before the first link that could carry it.

            Alias-only bare nouns of qualified destinations (`covariate`), a
            part of a longer term (see `_inside_longer_term`), a facet word the
            entry defines in italics from its own title (see
            `_own_title_term`), a discipline root inside a compound (`cell
            biology`), a descriptor immediately followed by the link itself
            (`fission yeast
            [[schizosaccharomyces-pombe|…]]`), and an italic gene symbol
            before a link to its Gene/Protein entry (`*cdc2*` before the Cdc2
            kinase) are not separate first mentions.
            """
            link_start = first_link[owner][0]
            if start >= link_start or surface in quiet:
                return False
            if _inside_longer_term(start, end) or _own_title_term(start, end):
                return False
            if owner in root_targets and _compound_modifier_before(masked, start):
                return False
            if (entries.get(owner) or {}).get("type") == "Gene/Protein" and any(
                    inner_start <= start and end <= inner_end
                    for inner_start, inner_end in italic_spans):
                return False
            return link_start - end > 3

        for start, end, surface, matched in _scan_surface_spans(
                masked, by_tokens, maxwords):
            if _in_math(start, end):
                continue
            global_hits.append((start, end))
            tgt = surf_map.get(surface)
            if not tgt or tgt == sl: continue
            if tgt in linked:
                # A linked target mentioned in plain text before its first
                # link: item 10 wants the link on the first eligible mention.
                if (late_links is not None and tgt not in late
                        and _earlier_mention(tgt, start, end, surface)):
                    late.add(tgt)
                    late_links.append((sl, tgt, matched, surface))
                continue
            if tgt in root_targets and _compound_modifier_before(masked, start):
                continue
            if tgt in root_targets and _root_named_as_setting_or_genus(
                    masked, start, end):
                continue   # a later occurrence may still be proposed
            # A later standalone mention may still carry the link.
            if _inside_longer_term(start, end) or _own_title_term(start, end):
                continue
            # One row per sentence: when the ledger settles a rejected
            # occurrence, the target's next sentence is offered instead.
            context = settle_context(WIKILINK.sub(
                lambda m: (m.group(2) or m.group(1)).strip(),
                _sentence_at(sentence_text, start)))
            if context in proposed.setdefault(tgt, set()):
                continue
            proposed[tgt].add(context)
            backfill.append((sl, tgt, matched, surface,
                             prose.count("\n", 0, start) + 1
                             + e.get("body_line_offset", 0), context))
        if late_links is None:
            continue
        # The first link's own label can be a word the surface index leaves
        # out (a common noun such as `model`, or an inflection): look for that
        # label, too, unless the hit sits inside a longer indexed surface.
        displays = {}
        for owner, (offset, display) in first_link.items():
            if owner in late or owner == sl or not display:
                continue
            # A cross-domain synonym label resolves its sense only at the link,
            # so, like an alias-only bare noun, its word is not a mention.
            record = entries.get(owner) or {}
            if cross_domain_synonym_label(
                    display,
                    [record.get("title") or ""] + list(record.get("aliases", [])),
                    record.get("prose", "")):
                continue
            for form in {display.lower(), plural_surface(display).lower()}:
                displays.setdefault(form, owner)
        if not displays:
            continue
        display_tokens, display_words = _late_link_index(displays)
        label_quiet = quiet_surfaces - base_only_surfaces
        for start, end, surface, matched in _scan_surface_spans(
                masked, display_tokens, display_words):
            owner = displays[surface]
            if (owner in late or _in_math(start, end)
                    or not _earlier_mention(owner, start, end, surface,
                                            label_quiet)):
                continue
            if any(g_start <= start and end <= g_end
                   and (g_end - g_start) > (end - start)
                   for g_start, g_end in global_hits):
                continue
            late.add(owner)
            late_links.append((sl, owner, matched, surface))
    return backfill


def iter_entry_files(wiki, on_error=None):
    """Every `.md` under `wiki`, RECURSIVELY and sorted (dot-dirs skipped).

    `os.listdir` was flat, so an entry filed in `Wiki/sub/` was invisible to the
    whole scan — and every wikilink pointing at it was reported as dangling.
    wiki-build's vault_index.py has always walked recursively; this matches it.
    A symlinked folder that points back into the Wiki tree is not walked:
    Obsidian does not support a symlink to a folder inside its own vault, and
    the real folder already covers its files.
    """
    out = []
    seen_dirs = set()
    real_wiki = os.path.realpath(wiki)
    inside_wiki = real_wiki.rstrip(os.sep) + os.sep

    def links_back(dirpath, name):
        path = os.path.join(dirpath, name)
        if not os.path.islink(path):
            return False
        real = os.path.realpath(path)
        return real == real_wiki or real.startswith(inside_wiki)

    for dirpath, dirnames, filenames in os.walk(wiki, followlinks=True, onerror=on_error):
        # followlinks, because a synced or shared subfolder under Wiki/ is a
        # symlink in plenty of real vaults, and skipping it made every link
        # into it read as dangling -- whose repair would unlink a working
        # reference. `seen_dirs` keeps a symlink loop through an outside
        # folder from walking forever. A link back into the Wiki tree is
        # pruned by name, so a link that sorts first never hides the real path.
        try:
            directory_stat = os.stat(dirpath)
            key = directory_stat.st_ino, directory_stat.st_dev
        except OSError as exc:
            if on_error is not None:
                on_error(exc)
            dirnames[:] = []
            continue
        if key in seen_dirs:
            dirnames[:] = []
            continue
        seen_dirs.add(key)
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".")
                             and not links_back(dirpath, d))
        for name in filenames:
            if name.lower().endswith(".md") and not name.startswith("."):
                out.append(os.path.join(dirpath, name))
    return sorted(out)


#: Extensions a wikilink may legitimately name that are not wiki entries: the
#: document forms CONVENTIONS 6/7 blesses in a `sources:` list. A link to one
#: is not an entry dangler and must never be unlinked as one. `.md` is absent
#: on purpose: in body prose and the Related footer, `[[x.md]]` is only another
#: spelling of the link `[[x]]`, so it resolves when that Wiki file exists, is
#: `item10/non-entry` when a vault note outside Wiki/ owns the name, and is a
#: dangler when neither does.
_DOC_EXTS = {".pdf", ".epub", ".docx", ".html", ".txt"}


_IMAGE_ALLOWED_HIDDEN = {".figure-manifest.tsv", ".figure-review.txt", ".DS_Store"}


def image_index(images):
    """Return folded image basenames and report-only folder-layout findings.

    Folded, not a literal `os.path.isfile` probe, for the reason `fold_name`
    gives: a case/normalization variant belongs to the same portable ownership
    class. A literal probe would make missing-image results depend on the host
    filesystem; producers and references still use the exact stored spelling.

    Walked recursively although CONVENTIONS §1 makes `Sources/Images/` flat:
    Obsidian resolves an embed by basename wherever the file sits, so a user
    who has nested a subfolder gets no false "missing" findings out of it.
    A symlinked subfolder is not walked, but its direct files are indexed
    once unless it points back into the image folder, whose walk already
    covers them; a directory inside it is reported as `nested-directory`
    and not descended. Paths that reach one underlying file (two links to a
    target, or a hard link) are one owner, not a basename collision.
    Those nested paths, and recognizable temporary/staging artifacts, are
    returned separately for the run report.  They never authorize deletion.
    The two PDF ownership sidecars are intentional; `.DS_Store` is ignored OS
    metadata rather than a plugin artifact.
    """
    if images is None:
        return None, []
    names, findings = set(), []
    paths_by_name = {}
    identity_by_path = {}
    root = os.path.abspath(images)
    real_root = os.path.realpath(root)
    walk_failed = False

    def record_walk_error(exc):
        nonlocal walk_failed
        walk_failed = True
        error_path = getattr(exc, "filename", None) or root
        try:
            relative = os.path.relpath(error_path, root)
        except (TypeError, ValueError):
            relative = str(error_path)
        relative = relative.replace(os.sep, "/")
        findings.append({
            "path": relative,
            "kind": "unreadable",
            "message": (
                "image folder could not be read completely: %s: %s; report "
                "only — missing-image checks are suppressed because a "
                "partial inventory cannot prove absence"
                % (type(exc).__name__, exc)),
        })

    def record_directory(relative_dir, linked):
        """Append the report-only directory finding; return whether it is staging."""
        temporary = looks_staging(relative_dir)
        findings.append({
            "path": relative_dir,
            "kind": "temporary-artifact" if temporary else "nested-directory",
            "message": (
                "temporary/staging directory under Sources/Images; report only — "
                "do not delete without user approval and provenance"
                if temporary else
                "nested %sdirectory under the flat Sources/Images folder; "
                "report only — do not move or delete without user approval "
                "and provenance" % ("symlinked " if linked else "")),
        })
        return temporary

    def index_file(dirpath, rel_dir, name):
        relative = (name if rel_dir == "." else os.path.join(rel_dir, name))
        relative = relative.replace(os.sep, "/")
        path = os.path.join(dirpath, name)
        usable = os.path.isfile(path)
        # Keep recursively discovered visible, resolvable files in the
        # resolver so the layout finding never creates a false missing-
        # image result. A dangling symlink, FIFO or other non-file
        # directory entry does not render merely because os.walk listed it.
        if usable and not name.startswith("."):
            folded = fold_name(name)
            names.add(folded)
            paths_by_name.setdefault(folded, []).append(relative)
            try:
                info = os.stat(path)
                identity_by_path[relative] = (info.st_dev, info.st_ino)
            except OSError:
                identity_by_path[relative] = os.path.realpath(path)
        # Finder writes `.DS_Store` into any folder it opens; the PDF
        # sidecars belong at the image-folder root only.
        if name == ".DS_Store" or (rel_dir == "." and name in _IMAGE_ALLOWED_HIDDEN):
            return
        temporary = looks_staging(relative)
        if temporary:
            kind = "temporary-artifact"
            message = ("temporary/staging artifact under Sources/Images; report only — "
                       "do not delete without user approval and provenance")
        elif rel_dir != ".":
            kind = "nested-file"
            message = ("file is nested under the flat Sources/Images folder; report only — "
                       "do not move or delete without user approval and provenance")
        elif not usable and os.path.lexists(path):
            kind = "unusable-file"
            message = ("image name is a dangling symlink or non-regular file and cannot "
                       "resolve as an embed; report only — do not replace or delete it "
                       "without user approval and provenance")
        else:
            return
        findings.append({"path": relative, "kind": kind, "message": message})

    for dirpath, dirnames, filenames in os.walk(root, onerror=record_walk_error):
        dirnames.sort()
        filenames.sort()
        rel_dir = os.path.relpath(dirpath, root)
        # Record directories when their parent exposes them, including a
        # symlinked directory that os.walk (correctly) does not follow.
        for dirname in dirnames:
            relative_dir = (dirname if rel_dir == "."
                            else os.path.join(rel_dir, dirname))
            linked_dir = os.path.join(dirpath, dirname)
            linked = os.path.islink(linked_dir)
            relative_dir = relative_dir.replace(os.sep, "/")
            temporary = record_directory(relative_dir, linked)
            if not linked or temporary:
                continue
            # A link back into the image folder repeats files the walk
            # already indexed; only an outside target is listed, one level.
            real_target = os.path.realpath(linked_dir)
            if (real_target == real_root
                    or real_target.startswith(real_root.rstrip(os.sep) + os.sep)):
                continue
            try:
                with os.scandir(linked_dir) as linked_scan:
                    linked_names = sorted(entry.name for entry in linked_scan)
            except OSError as exc:
                record_walk_error(exc)
                continue
            for name in linked_names:
                # Only direct files are indexed. A subdirectory here is a
                # directory finding, never a file one, and is not descended.
                child = os.path.join(linked_dir, name)
                if os.path.isdir(child):
                    record_directory(relative_dir + "/" + name,
                                     os.path.islink(child))
                    continue
                index_file(linked_dir, relative_dir, name)
        for name in filenames:
            index_file(dirpath, rel_dir, name)
    # One folded set member is enough for missing-image semantics, but not for
    # namespace safety: two actual paths with a case/NFC-equivalent basename
    # make a bare embed ambiguous. Preserve every path in a report-only group
    # while keeping the name present, so this finding does not manufacture a
    # contradictory item12/missing-image result.
    for paths in paths_by_name.values():
        paths = sorted(set(paths), key=lambda value: (fold_name(value), value))
        if len({identity_by_path.get(path, path) for path in paths}) < 2:
            continue
        findings.append({
            "path": paths[0],
            "paths": paths,
            "kind": "portable-name-collision",
            "message": (
                "case/normalization-equivalent image basenames resolve from "
                "multiple paths: %s; report only — do not rename or delete "
                "without user approval and provenance" % ", ".join(paths)),
        })
    findings.sort(key=lambda finding: (finding["path"], finding["kind"]))
    # One inaccessible subtree makes the inventory incomplete. Returning the
    # names found so far would turn every embed in that subtree into a false
    # missing-image repair cue; None has the same established meaning as an
    # intentionally omitted --images inventory and suppresses those findings.
    return (None if walk_failed else names), findings


#: An image filename that `IMG_EMBED` accepts.
_IMAGE_FILE_RE = re.compile(
    r"\.(?:png|jpe?g|gif|svg|webp|tiff?|bmp|avif|ico)$", re.I)


def _folder_identity(path):
    """``(st_dev, st_ino)`` of the folder at ``path``, or None."""
    try:
        info = os.stat(path)
    except OSError:
        return None
    return info.st_dev, info.st_ino


def _is_folder(path, identity):
    """Whether ``path`` is the folder whose identity is ``identity``.

    Identity, unlike a path string, matches a case-folding host's other
    spelling of the folder (``wiki`` for ``Wiki``) and a symlink to it.
    """
    return identity is not None and _folder_identity(path) == identity


def vault_image_index(vault_root, images):
    """Index the vault's image files outside the `--images` folder.

    Returns a dict from each folded basename to the sorted vault-relative
    paths that hold it. Obsidian resolves an embed by basename anywhere in
    the vault, so an image outside `Sources/Images/` still renders.
    Dot-folders, which Obsidian does not index, and the image folder, which
    `image_index` already covers, are skipped. Folder symlinks are not
    followed, and a folder that cannot be read is skipped.
    """
    paths = {}
    root = os.path.abspath(vault_root)
    images_identity = _folder_identity(images)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            name for name in dirnames
            if not name.startswith(".")
            and not _is_folder(os.path.join(dirpath, name), images_identity))
        for name in sorted(filenames):
            if name.startswith(".") or not _IMAGE_FILE_RE.search(name):
                continue
            if not os.path.isfile(os.path.join(dirpath, name)):
                continue
            relative = os.path.relpath(
                os.path.join(dirpath, name), root).replace(os.sep, "/")
            paths.setdefault(fold_name(name), []).append(relative)
    return paths


def moc_file_state(path, *, _directory_fd=None, _texts=None):
    """Read one complete generated MOC through a stable regular-file snapshot.

    Content has no separately owned regions: canonical MOCs are wholly
    generated documents. File safety is separate from tree formatting, and
    no content shape can make an unsafe pathname writable.
    """
    result = {
        "path": os.path.abspath(path),
        "state": "missing",
    }
    # When inventorying MOCs/, address the leaf through an already verified
    # directory descriptor. A swapped directory cannot redirect the read.
    read_path = os.path.basename(path) if _directory_fd is not None else path
    options = ({"dir_fd": _directory_fd} if _directory_fd is not None else {})
    try:
        before = os.stat(read_path, follow_symlinks=False, **options)
    except FileNotFoundError:
        return result
    except OSError as exc:
        result["state"] = "unreadable"
        result["error"] = "%s: %s" % (type(exc).__name__, exc)
        return result
    if stat.S_ISLNK(before.st_mode):
        result["state"] = "unreadable"
        result["error"] = (
            "SymlinkError: MOC pathname is a symlink occupant; do not follow "
            "it for initialization or generated-file replacement")
        return result
    if not stat.S_ISREG(before.st_mode):
        result["state"] = "unreadable"
        result["error"] = (
            "FileTypeError: MOC pathname is occupied by a non-regular file")
        return result
    descriptor = None
    try:
        descriptor = os.open(
            read_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0), **options)
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise OSError("MOC pathname changed while it was opened")
        with os.fdopen(descriptor, "r", encoding="utf-8-sig") as fh:
            descriptor = None
            text = fh.read()
            opened_after = os.fstat(fh.fileno())
        after = os.stat(read_path, follow_symlinks=False, **options)
        stable = lambda item: (
            item.st_dev, item.st_ino, item.st_size,
            getattr(item, "st_mtime_ns", int(item.st_mtime * 1e9)),
            getattr(item, "st_ctime_ns", int(item.st_ctime * 1e9)),
            stat.S_IFMT(item.st_mode),
        )
        if not (stable(before) == stable(opened)
                == stable(opened_after) == stable(after)):
            raise OSError("MOC pathname changed while it was read")
    except (OSError, UnicodeDecodeError) as exc:
        result["state"] = "unreadable"
        result["error"] = "%s: %s" % (type(exc).__name__, exc)
        return result
    finally:
        if descriptor is not None:
            os.close(descriptor)

    if _texts is not None:
        _texts[result["path"]] = text
    try:
        outline, _provenance = split_provenance(text)
    except ValueError:
        outline = text  # Keep malformed metadata visible to tree diagnostics.
    result["state"] = "readable" if outline.strip() else "empty"
    return result


def inventory_mocs(vault_root, entry_counts):
    """Inventory known MOC names, preserving ambiguous and legacy ownership.

    Only the flat canonical MOCs/ directory and known old names are in scope:
    vault-root `<discipline>-moc.md` notes and the previous
    `MOCs/<discipline>.md` layout. Missing directories permit later
    initialization; occupied, aliased or unreadable directories never
    masquerade as an empty inventory.
    """
    directory = os.path.join(vault_root, "MOCs")
    states, legacy, findings, texts = [], [], [], {}
    root_names, names, folder_error = [], [], None
    descriptor = None

    def finding(kind, path, message, **fields):
        findings.append(dict(kind=kind, path=os.path.abspath(path),
                             message=message, **fields))

    try:
        root_names = sorted(os.listdir(vault_root))
        folders = [name for name in root_names if fold_name(name) == "mocs"]
        if len(folders) > 1:
            folder_error = "MOCs/ has multiple portable directory owners"
            finding("ambiguous-directory", directory, folder_error,
                    paths=[os.path.join(vault_root, name) for name in folders])
        elif folders and folders[0] != "MOCs":
            folder_error = "MOCs/ exists with noncanonical directory spelling"
            finding("noncanonical-directory", directory, folder_error,
                    paths=[os.path.join(vault_root, folders[0])])
        elif folders:
            before = os.stat(directory, follow_symlinks=False)
            if not stat.S_ISDIR(before.st_mode):
                raise OSError("MOCs pathname is a symlink or non-directory occupant")
            descriptor = os.open(directory, os.O_RDONLY
                                 | getattr(os, "O_DIRECTORY", 0)
                                 | getattr(os, "O_NOFOLLOW", 0))
            opened = os.fstat(descriptor)
            if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                raise OSError("MOCs directory changed while it was opened")
            names = sorted(os.listdir(descriptor))
            for name in names:
                if (name.lower().endswith(".md")
                        and moc_discipline(name[:-3]) is None
                        and fold_name(name[:-3]) not in VALID_TAGS):
                    finding("unexpected-moc", os.path.join(directory, name),
                            "MOC filename is not a canonical discipline MOC name; preserve it for explicit review")
    except OSError as exc:
        folder_error = "%s: %s" % (type(exc).__name__, exc)
        finding("unsafe-directory", directory, folder_error)

    try:
        for discipline in sorted(VALID_TAGS):
            canonical_name = moc_stem(discipline) + ".md"
            path = os.path.join(directory, canonical_name)
            owners = [name for name in names
                      if fold_name(name) == canonical_name]
            old_names = [name for name in root_names
                         if discipline != "misc"
                         and fold_name(name) == discipline + "-moc.md"]
            previous_names = [name for name in names
                              if fold_name(name) == discipline + ".md"]
            for old_name in old_names:
                old_path = os.path.join(vault_root, old_name)
                old_state = moc_file_state(old_path)
                old_state.update(discipline=discipline,
                                 target="MOCs/" + moc_stem(discipline),
                                 canonical_path=os.path.abspath(path),
                                 entries=entry_counts.get(discipline, 0))
                legacy.append(old_state)
                finding("legacy-location", old_path,
                        "unexpected old root MOC is outside generated ownership; preserve it and resolve ownership before creating a canonical MOC",
                        discipline=discipline, canonical_path=os.path.abspath(path))
            for previous_name in previous_names:
                previous_path = os.path.join(directory, previous_name)
                previous_state = (
                    moc_file_state(previous_path, _directory_fd=descriptor)
                    if descriptor is not None and not folder_error else
                    dict(path=os.path.abspath(previous_path),
                         state="unreadable", error=folder_error))
                previous_state.update(discipline=discipline,
                                      target="MOCs/" + moc_stem(discipline),
                                      canonical_path=os.path.abspath(path),
                                      entries=entry_counts.get(discipline, 0))
                legacy.append(previous_state)
                finding("previous-layout", previous_path,
                        "MOC has the previous name, which its Wiki root shares; migrate it to the canonical name before regenerating it",
                        discipline=discipline, canonical_path=os.path.abspath(path))
            if not (entry_counts.get(discipline) or owners or old_names
                    or previous_names):
                continue
            error = folder_error
            if len(owners) > 1:
                error = "discipline MOC has multiple portable pathname owners"
                finding("ambiguous-moc", path, error, discipline=discipline,
                        paths=[os.path.join(directory, name) for name in owners])
            elif owners and owners[0] != canonical_name:
                error = "discipline MOC exists with noncanonical filename spelling"
                finding("noncanonical-moc", path, error, discipline=discipline,
                        paths=[os.path.join(directory, owners[0])])
            if error:
                state = dict(path=os.path.abspath(path), state="unreadable",
                             error=error)
            elif descriptor is not None:
                state = moc_file_state(path, _directory_fd=descriptor,
                                         _texts=texts)
            else:
                state = dict(path=os.path.abspath(path), state="missing")
            state.update(discipline=discipline,
                         target="MOCs/" + moc_stem(discipline),
                         entries=entry_counts.get(discipline, 0))
            states.append(state)
            if owners and not entry_counts.get(discipline) and discipline != "misc":
                finding("stale-moc", path,
                        "existing MOC has no entries; preserve it and report its inactive discipline",
                        discipline=discipline)
        if descriptor is not None:
            after = os.stat(directory, follow_symlinks=False)
            current_names = sorted(os.listdir(descriptor))
            if ((after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino)
                    or not stat.S_ISDIR(after.st_mode) or current_names != names):
                raise OSError("MOCs directory changed during inventory")
    except OSError as exc:
        error = "%s: %s" % (type(exc).__name__, exc)
        finding("unsafe-directory", directory, error)
        for state in states:
            state.update(state="unreadable", error=error)
        texts.clear()
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return states, legacy, findings, texts


# Listings are masked first, so indentation here is a list item's.
_DUPLICATE_DISPLAY_RE = re.compile(
    r"(?ms)^[ \t]*\$\$[ \t]*\n.*?\n[ \t]*\$\$[ \t]*$")
_DUPLICATE_MARKDOWN_LINK_RE = re.compile(
    r"!?\[([^\]\n]*)\]\([^\n)]*\)")
_DUPLICATE_MARKDOWN_IMAGE_RE = re.compile(
    r"!\[[^\]\n]*\]\([^\n)]*\)")
_DUPLICATE_INLINE_MATH_RE = re.compile(
    r"(?<![\\$])\$(?!\$)((?:\\.|[^$\n])+?)(?<!\\)\$(?!\$)")
#: An inline code span for duplicate_sentence_surfaces: a run of N backticks,
#: content, and a closing run of the SAME length, whose payload is protected
#: from punctuation normalization.  Not `` `[^`]*` ``, which reads
#: ``` ``[[x]]`` ``` as two empty spans around a bare `[[x]]` and renders that
#: sample of link syntax as its label.  Line-bounded on purpose: a code span
#: may legally span a line break, but honouring that lets one stray backtick
#: swallow the rest of an entry.
_INLINE_CODE = re.compile(r"(`+)[^\n]*?\1(?!`)")
def duplicate_sentence_surfaces(prose, table_spans=()):
    """Return long normalized prose sentences eligible for ownership review.

    Exact copied prose is a useful cross-entry signal only after presentation
    syntax is removed. Listings, displays, tables, images, and captions are not
    assertions to deduplicate, so they are blanked. Wikilinks normalize to
    their rendered label, making a linked and an unlinked copy comparable.
    Short sentences stay out: ordinary connective or definitional phrases are
    expected to recur and offer no ownership evidence.
    """
    visible = strip_indented(strip_fenced(prose or ""))
    visible = _DUPLICATE_DISPLAY_RE.sub(
        lambda match: "".join(
            "\n" if char == "\n" else " " for char in match.group(0)),
        visible)
    visible = mask_line_spans(visible, table_spans)
    kept_lines = []
    for line in visible.split("\n"):
        stripped = line.strip()
        if (not stripped or stripped.startswith("#")
                or re.match(r"^!\[\[.*\]\]$", stripped)
                or re.match(r"^!\[[^\]]*\]\([^)]*\)$", stripped)
                or re.match(r"^\*(?!\*)\S(?:.*\S)?\*$", stripped)):
            kept_lines.append("")
        else:
            kept_lines.append(line)
    visible = "\n".join(kept_lines)

    def render_wikilink(match):
        target = match.group(1).split("#", 1)[0].split("^", 1)[0]
        target = target.replace("\\", "/").rsplit("/", 1)[-1]
        if target.lower().endswith(".md"):
            target = target[:-3]
        return match.group(2) or target.replace("-", " ")

    def protected_payload(prefix, payload):
        """Keep code/math semantics through punctuation normalization."""
        parts = [prefix]
        for char in unicodedata.normalize("NFKC", payload or ""):
            if char.isalnum():
                parts.append(char.casefold())
            elif char.isspace():
                parts.append(" ")
            else:
                parts.append(" u%04x " % ord(char))
        return "".join(parts)

    payloads = []

    def protect(match, prefix, payload):
        token = "dupsentinel%06dtoken" % len(payloads)
        payloads.append((token, protected_payload(prefix, payload),
                         match.group(0)))
        return token

    # Inline code and inline math carry semantic payload. Protect them while
    # presentation syntax is normalized, then expand each placeholder in two
    # ways: an operator-preserving comparison key and the original readable
    # evidence shown in the finding.
    visible = _INLINE_CODE.sub(
        lambda match: protect(
            match, " dupcode ",
            match.group(0)[len(match.group(1)):-len(match.group(1))]),
        visible)
    visible = _DUPLICATE_INLINE_MATH_RE.sub(
        lambda match: protect(match, " dupmath ", match.group(1)),
        visible)
    visible = re.sub(r"!\[\[[^\]\n]+\]\]", "", visible)
    visible = _DUPLICATE_MARKDOWN_IMAGE_RE.sub("", visible)
    visible = WIKILINK.sub(render_wikilink, visible)
    visible = _DUPLICATE_MARKDOWN_LINK_RE.sub(r"\1", visible)
    visible = re.sub(r"[*_~]+", "", visible)
    compact = " ".join(visible.split())

    out = []
    for sentence in split_sentences(compact):
        comparison = sentence.strip()
        surface = comparison
        for token, comparison_payload, evidence_payload in payloads:
            comparison = comparison.replace(token, comparison_payload)
            surface = surface.replace(token, evidence_payload)
        normalized = unicodedata.normalize("NFKC", comparison).casefold()
        normalized = re.sub(r"[^\w]+", " ", normalized)
        normalized = " ".join(normalized.split())
        if len(normalized) < 80 or len(normalized.split()) < 12:
            continue
        out.append((normalized, surface))
    return out


def build_card_rivals(cues, parent_slugs, related_slugs, root_slugs):
    """Item-19 review input: each entry's primary cue beside its closest rivals.

    ``cues`` maps slug -> primary line 1; ``parent_slugs`` and
    ``related_slugs`` map slug -> resolved entry slugs. Rivals are the
    entry's Related-footer targets plus every entry that shares a resolved
    parent other than a discipline root. Only entries with a cue count,
    and an entry never rivals itself. Read-only; authorizes no edit.
    """
    children = {}
    for slug_value, parents in parent_slugs.items():
        for parent in parents:
            if parent not in root_slugs:
                children.setdefault(parent, set()).add(slug_value)
    rows = []
    for slug_value in sorted(cues):
        rivals = set(related_slugs.get(slug_value, ()))
        for parent in parent_slugs.get(slug_value, ()):
            if parent not in root_slugs:
                rivals |= children.get(parent, set())
        rivals = sorted(r for r in rivals if r != slug_value and r in cues)
        if rivals:
            rows.append({"slug": slug_value, "cue": cues[slug_value],
                         "rivals": rivals})
    return rows


SR_SETTINGS_PARTS = (".obsidian", "plugins", "obsidian-spaced-repetition",
                     "data.json")

#: The plugin's built-in cloze conversions: (toggle, pattern, entry text it
#: would turn into cards). Without a ``clozePatterns`` list the plugin derives
#: its patterns from these toggles.
SR_CLOZE_CONVERSIONS = (
    ("convertHighlightsToClozes", "==[123;;]answer[;;hint]==",
     "any ==highlight=="),
    ("convertBoldTextToClozes", "**[123;;]answer[;;hint]**",
     "every bold opener and bullet anchor"),
    ("convertCurlyBracketsToClozes", "{{[123;;]answer[;;hint]}}",
     "any {{...}} span, such as doubled LaTeX braces"),
)


def spaced_repetition_report(vault_root, discipline_counts):
    """Advisory, read-only view of the Spaced Repetition plugin's settings.

    ``discipline_counts`` is the scan's ``discipline_tags`` census. Never
    writes, never follows a symlinked settings file, never raises.
    """
    report = {"settings": "absent", "uncovered_tags": {},
              "separator_findings": []}
    path = os.path.join(vault_root, *SR_SETTINGS_PARTS)
    if not os.path.lexists(path):
        return report
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                             | getattr(os, "O_NONBLOCK", 0))
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError("not a regular file")
        with os.fdopen(descriptor, encoding="utf-8") as handle:
            descriptor = None
            data = json.load(handle)
    except (OSError, ValueError, UnicodeDecodeError, RecursionError):
        report["settings"] = "unreadable"
        return report
    finally:
        if descriptor is not None:
            os.close(descriptor)
    settings = data.get("settings") if isinstance(data, dict) else None
    if not isinstance(settings, dict):
        report["settings"] = "unreadable"
        return report
    report["settings"] = "read"
    tags = settings.get("flashcardTags", ["#flashcards"])
    listed = {tag.strip().lstrip("#").casefold()
              for tag in (tags if isinstance(tags, list) else [])
              if isinstance(tag, str)}
    if settings.get("convertFoldersToDecks") is not True:
        report["uncovered_tags"] = {
            slug_value: count
            for slug_value, count in sorted(discipline_counts.items())
            if count and slug_value.casefold() not in listed}
    value = settings.get("multilineReversedCardSeparator", "??")
    if value != "??":
        report["separator_findings"].append(
            "multilineReversedCardSeparator is %r; wiki cards use '??'"
            % (value,))
    value = settings.get("multilineCardSeparator", "?")
    if value != "?":
        report["separator_findings"].append(
            "multilineCardSeparator is %r; a body line that is only it "
            "becomes an extra card, and the entry check guards only '?'"
            % (value,))
    marker = settings.get("multilineCardEndMarker", "")
    if marker:
        report["separator_findings"].append(
            "multilineCardEndMarker is %r; wiki cards end at a blank line"
            % marker)
    # The item19/sr-marker floor guards the default single-line separators;
    # an empty one turns single-line cards off.
    for key, default in (("singleLineCardSeparator", "::"),
                         ("singleLineReversedCardSeparator", ":::")):
        value = settings.get(key, default)
        if value not in (default, ""):
            report["separator_findings"].append(
                "%s is %r; entry text containing it becomes an extra card, "
                "and the entry check guards only %r" % (key, value, default))
    # Every active cloze conversion turns ordinary entry text into cards.
    patterns = settings.get("clozePatterns")
    if patterns is None:
        patterns = [pattern for key, pattern, _text in SR_CLOZE_CONVERSIONS
                    if settings.get(key)]
    for pattern in (patterns if isinstance(patterns, list) else []):
        if not isinstance(pattern, str) or not pattern:
            continue
        known = next((row for row in SR_CLOZE_CONVERSIONS
                      if row[1] == pattern), None)
        report["separator_findings"].append(
            "clozePatterns converts %r%s: %s in an entry becomes an extra "
            "cloze card; keep cloze conversion off"
            % (pattern, " (%s)" % known[0] if known else "",
               known[2] if known else "matching text"))
    return report


def _vault_root_for(wiki, images=None, vault=None):
    """Use an explicit vault root, otherwise retain legacy path inference.

    Returns ``(root, known)``. ``known`` is false only for the last fallback,
    the Wiki folder's parent, which may be any directory rather than a vault.
    """
    if vault is not None:
        if not os.path.isdir(vault):
            raise ValueError("vault is not a directory: %s" % vault)
        return os.path.abspath(vault), True
    if images:
        image_path = os.path.abspath(images)
        if (fold_name(os.path.basename(image_path)) == "images"
                and fold_name(os.path.basename(os.path.dirname(image_path)))
                == "sources"):
            return os.path.dirname(os.path.dirname(image_path)), True
    current = os.path.abspath(wiki)
    while True:
        if os.path.isdir(os.path.join(current, ".obsidian")):
            return current, True
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return os.path.dirname(os.path.abspath(wiki)), False


def vault_note_index(vault_root, wiki):
    """Index the vault's real Markdown notes outside the Wiki tree.

    Returns ``(paths, basenames, complete)``. ``paths`` maps each folded,
    extensionless vault-relative path to the exact vault-relative paths
    (with ``.md``) that own it, and ``basenames`` maps each folded basename
    the same way. ``complete`` is false when a folder could not be read.
    Dot-folders, the scanned Wiki tree and the vault-root ``MOCs/`` folder,
    which the MOC inventory owns, are skipped. Folder symlinks are followed,
    as Obsidian indexes them, with a loop guard; one that points back into
    the vault is not walked, because the real folder already covers its
    files.
    """
    paths, basenames = {}, {}
    complete = True
    root = os.path.abspath(vault_root)
    wiki_identity = _folder_identity(wiki)
    inside_root = os.path.realpath(root).rstrip(os.sep) + os.sep
    seen = set()

    def failed(_exc):
        nonlocal complete
        complete = False

    def links_back(path):
        return (os.path.islink(path)
                and (os.path.realpath(path) + os.sep).startswith(inside_root))

    for dirpath, dirnames, filenames in os.walk(
            root, followlinks=True, onerror=failed):
        identity = _folder_identity(dirpath)
        if identity is None:
            complete = False
        if identity is None or identity in seen:
            dirnames[:] = []
            continue
        seen.add(identity)
        top = dirpath == root
        dirnames[:] = sorted(
            name for name in dirnames
            if not name.startswith(".")
            and not (top and fold_name(name) == "mocs")
            and not _is_folder(os.path.join(dirpath, name), wiki_identity)
            and not links_back(os.path.join(dirpath, name)))
        for name in sorted(filenames):
            if name.startswith(".") or not name.lower().endswith(".md"):
                continue
            if not os.path.isfile(os.path.join(dirpath, name)):
                continue
            relative = os.path.relpath(
                os.path.join(dirpath, name), root).replace(os.sep, "/")
            key = fold_name(relative[:-3])
            paths.setdefault(key, []).append(relative)
            basenames.setdefault(key.rsplit("/", 1)[-1], []).append(relative)
    return paths, basenames, complete


class _ProblemList(list):
    """Internal problem rows with optional physical-path identity.

    Public reports have historically keyed ordinary findings by ``slug``.
    Keep that stable, but retain the Wiki-relative path while checking a
    basename collision: two physical files then share one slug and the path is
    the only safe way to identify which body produced a local finding.
    """
    current_path = ""

    def append(self, row):
        slug_value, item, message = row
        super().append((slug_value, item, message, self.current_path))


class IncompleteWikiInventoryError(OSError):
    """The entry inventory cannot establish identity or absence safely."""


def _entry_physical_key(wiki, path):
    """Exact Wiki-relative filename used only for physical-record identity."""
    return os.path.relpath(path, wiki).replace("\\", "/")


#: The settled-decisions ledger's record fields, per row kind
#: (link-hygiene.md, Settled decisions).
SETTLED_FIELDS = {"backfill": ("entry", "target", "surface", "context"),
                  "hub_footer": ("entry", "target", "context")}


def read_settled(path):
    """``({kind: set of record tuples}, version, error)`` from a settled ledger.

    A missing file is an empty version-2 ledger. An unreadable or malformed
    one yields no records and an error message, so it suppresses nothing.
    """
    empty = {kind: set() for kind in SETTLED_FIELDS}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return empty, 2, None
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return empty, 2, "cannot read the ledger: %s" % exc
    if (not isinstance(data, dict) or type(data.get("version")) is not int
            or data["version"] not in (1, 2)):
        return empty, 2, 'the ledger is not a {"version": 2, ...} object'
    unknown = sorted(set(data) - {"version"} - set(SETTLED_FIELDS))
    if unknown:
        return empty, 2, "the ledger has unknown keys: %s" % ", ".join(unknown)
    records = {}
    for kind, fields in SETTLED_FIELDS.items():
        rows = data.get(kind, [])
        if not isinstance(rows, list):
            return empty, 2, "the ledger's %s is not a list" % kind
        records[kind] = set()
        for row in rows:
            if (not isinstance(row, dict) or set(row) != set(fields)
                    or not all(isinstance(row[f], str) and row[f]
                               for f in fields)
                    or not re.fullmatch(r"[0-9a-f]{40}", row["context"])):
                return empty, 2, (
                    "the ledger's %s holds a malformed record: %s"
                    % (kind, json.dumps(row, ensure_ascii=False)))
            records[kind].add(tuple(row[f] for f in fields))
    return records, data["version"], None


def apply_settled(backfill_rows, hub_footer, path, complete=True):
    """Omit the rows a settled ledger records; return them and ``settled``.

    A ``backfill_candidates`` row or a ``hub_footer`` item is omitted when
    its ``settle_key`` equals a ledger record, and a hub target left with no
    item goes too. ``backfill_rows`` holds one row per target and sentence,
    each target's in text order; the first unsettled one per entry and
    target is kept, with ``settle_keys``: its own key and those of the
    target's later unsettled sentences, which a rejection records together.
    In a version-1 ledger, a record that matches the target's first sentence
    settles all of that entry's sentences of the target, and ``upgrade``
    lists the records of the others, so a version-2 rewrite keeps them
    settled. ``stale`` lists the records that matched no current row, in
    the ledger's own shape. Both stay empty when ``complete`` is false,
    since the rows themselves were then not computed, and ``upgrade`` is
    then None for a version-1 ledger.
    """
    settled = {"path": path, "backfill_suppressed": 0,
               "hub_footer_suppressed": 0,
               "stale": {kind: [] for kind in SETTLED_FIELDS}, "upgrade": [],
               "error": None}
    if path is None:
        records, version = {kind: set() for kind in SETTLED_FIELDS}, 2
    else:
        records, version, settled["error"] = read_settled(path)
    matched = {kind: set() for kind in SETTLED_FIELDS}

    def _is_settled(kind, key):
        record = tuple(key[f] for f in SETTLED_FIELDS[kind])
        if record in records[kind]:
            matched[kind].add(record)
            return True
        return False

    pairs = {}
    for row in backfill_rows:
        pairs.setdefault((row["slug"], row["target"]), []).append(row)
    kept = []
    for rows in pairs.values():
        # Every row is checked, so a record that still matches is not stale.
        done = [_is_settled("backfill", row["settle_key"]) for row in rows]
        if version == 1 and done[0]:
            settled["upgrade"] += [row["settle_key"]
                                   for row, row_done in zip(rows, done)
                                   if not row_done]
            done = [True] * len(rows)
        settled["backfill_suppressed"] += sum(done)
        open_rows = [row for row, row_done in zip(rows, done) if not row_done]
        if open_rows:
            kept.append(dict(open_rows[0], settle_keys=[
                row["settle_key"] for row in open_rows]))
    hubs = []
    for row in hub_footer:
        items = [(entry, key)
                 for entry, key in zip(row["entries"], row["settle_keys"])
                 if not _is_settled("hub_footer", key)]
        settled["hub_footer_suppressed"] += len(row["entries"]) - len(items)
        if items:
            hubs.append(dict(row, entries=[entry for entry, _key in items],
                             settle_keys=[key for _entry, key in items]))
    if complete:
        settled["stale"] = {
            kind: [dict(zip(fields, record)) for record
                   in sorted(records[kind] - matched[kind])]
            for kind, fields in SETTLED_FIELDS.items()}
    elif version == 1:
        settled["upgrade"] = None
    return kept, hubs, settled


def scan(wiki, images=None, vault=None, settled=None):
    """Parse every entry in the `wiki` folder; return the Step 0 model as a dict.

    `vault` explicitly selects the root used for qualified entry links, parent
    resolution, backfill targets, and MOC diagnostics. When omitted, infer it
    from `images`, a .obsidian ancestor, or the Wiki folder's parent.

    `images` is the vault's `Sources/Images/` folder, or None. CONVENTIONS §1
    names this skill the validator of the embeds pointing there, and until
    `--images` existed nothing in the skill had a path to that folder at all:
    an entry embedding a figure that is not on disk produced an empty problem
    list here while paper-summarize's `note_lint.py --images` reported the
    same embed on an `Articles/` note. It is also the detector CONVENTIONS §1a
    relies on for `Wiki/` — a source rename renames every figure with it, and
    the embeds left pointing at the old stem are silent otherwise.

    `settled` is the settled-decisions ledger's path, or None; the rows it
    records are omitted (see `apply_settled`).
    """
    vault_root, vault_root_known = _vault_root_for(wiki, images, vault)
    img_fold, image_folder_findings = image_index(images)
    # Images elsewhere in a known vault, built on the first embed that the
    # image folder does not hold.
    vault_images = None
    entries, problems = {}, _ProblemList()
    # Every slug whose FILE is on disk, whether or not it parsed as an entry.
    # A link to an unparseable file resolves in Obsidian, so it is not dangling
    # -- creating a replacement would write over that real file.
    on_disk = set()
    seen_paths = {}
    paths_by_basename = {}
    # Exact Wiki-relative filename -> parsed record or None. Keep the extension
    # spelling too: on a case-sensitive filesystem `foo.md` and `foo.MD` are two
    # physical files even though both resolve through one portable link
    # identity. Resolution derives that normalized, extensionless identity only
    # while comparing; physical records must never collapse first.
    path_records = {}
    alias_inventory_gaps = set()
    alias_gap_note = (
        " Alias inventory is incomplete: dangling-link, alias-dependent "
        "canonicalization/duplicate-removal, alias-addition and backfill "
        "inferences are suppressed for this scan. Preserve unresolved links; "
        "safely repair the affected metadata/readability and rescan to resume.")
    walk_errors = []
    def walk_error(exc):
        walk_errors.append(str(exc))

    physical_paths = iter_entry_files(wiki, on_error=walk_error)
    if walk_errors:
        # An unseen subtree can own any missing filename or alias. No derived
        # linking or hierarchy worklist is sound from that partial inventory.
        # Leaf-read failures below are different: their occupied paths remain
        # inventoried and receive the ordinary report-only item0 finding.
        raise IncompleteWikiInventoryError(
            "incomplete Wiki directory inventory; no scan worklists produced: "
            + "; ".join(walk_errors))
    for path in physical_paths:
        fn = os.path.basename(path)
        sl = fn[:-3]
        rel = _entry_physical_key(wiki, path)
        path_key = rel
        paths_by_basename.setdefault(fold_name(sl), set()).add(path_key)
    ambiguous_files = {
        basename for basename, owners in paths_by_basename.items()
        if len(owners) > 1
    }

    for path in physical_paths:
        fn = os.path.basename(path)
        sl = fn[:-3]
        rel = _entry_physical_key(wiki, path)
        path_key = rel
        problems.current_path = rel if fold_name(sl) in ambiguous_files else ""
        path_records[path_key] = None
        # Bare links use basename ownership. Two equal basenames in different
        # folders, including case/normalization variants under the plugin's
        # portable identity, create one ambiguous slug with two bodies.
        keep_entry = fold_name(sl) not in seen_paths
        if not keep_entry:
            ambiguous_files.add(fold_name(sl))
            prev_sl, prev_rel = seen_paths[fold_name(sl)]
            problems.append((sl,"item5",f'slug "{sl}" occurs in two files ({prev_rel} and {rel}'
                                        f'{"" if prev_sl == sl else ", stems differing only in case/normalization"}) — '
                                        f'the portable link identity has multiple owners; rename or merge'))
        else:
            seen_paths[fold_name(sl)] = (sl, rel)
        # Leaf symlinks are not editable Wiki entries. Directory symlinks are
        # supported by the cycle-safe walker, but following a leaf can read and
        # later write a target outside the selected vault. Read one stable
        # regular inode through O_NOFOLLOW where available.
        descriptor = None
        try:
            before = os.stat(path, follow_symlinks=False)
            if stat.S_ISLNK(before.st_mode):
                raise OSError("leaf Markdown path is a symlink; its target is "
                              "outside this scan's editable ownership")
            if not stat.S_ISREG(before.st_mode):
                raise OSError("leaf Markdown path is not a regular file")
            descriptor = os.open(
                path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0))
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise OSError("leaf Markdown path changed while it was opened")
            # utf-8-SIG strips a BOM, which would otherwise sit in front of
            # the opening `---` and report a valid entry as having no
            # frontmatter.  Universal newlines are load-bearing too and are why
            # nothing here re-spells CRLF: text mode translates \r\n to \n on
            # read, so every line-oriented check below sees one line ending.
            # Reading with `newline=""` would leave a \r on every parsed value
            # AND blind the blank-line-after-frontmatter probe, which counts
            # leading "\n" and would see "\r\n\r\n".
            with os.fdopen(descriptor, "r", encoding="utf-8-sig") as fh:
                descriptor = None
                text = fh.read()
                opened_after = os.fstat(fh.fileno())
            after = os.stat(path, follow_symlinks=False)
            stable = lambda item: (
                item.st_dev, item.st_ino, item.st_size,
                getattr(item, "st_mtime_ns", int(item.st_mtime * 1e9)),
                getattr(item, "st_ctime_ns", int(item.st_ctime * 1e9)),
                stat.S_IFMT(item.st_mode),
            )
            if not (stable(before) == stable(opened)
                    == stable(opened_after) == stable(after)):
                raise OSError("leaf Markdown path changed while it was read")
        except (OSError, UnicodeDecodeError) as exc:
            problems.append((sl,"item0",f"unreadable: {type(exc).__name__}: {exc}"))
            alias_inventory_gaps.add((sl, problems.current_path))
            on_disk.add(sl)
            continue
        finally:
            if descriptor is not None:
                os.close(descriptor)
        try:
            text, _provenance = split_provenance(text)
        except ValueError as exc:
            problems.append((sl, "item2/provenance",
                             "invalid skill provenance: %s" % exc))
        _frontmatter_boundary_bad = []
        fm_raw, body, blank_after = split_frontmatter(
            text, _frontmatter_boundary_bad)
        if fm_raw is None:
            problems.append((sl,"item1","no YAML frontmatter"))
            # A readable plain note has no Obsidian properties. A possible
            # but unsupported/unclosed fence cannot establish alias absence.
            if text.lstrip("\ufeff").startswith("---"):
                alias_inventory_gaps.add((sl, problems.current_path))
            on_disk.add(sl)
            continue
        if flashcards_close_frontmatter(fm_raw, body):
            _frontmatter_boundary_bad.append(FLASHCARDS_CLOSE_MESSAGE)
        for _message in _frontmatter_boundary_bad:
            problems.append((sl, "item1", _message))
        _fm_bad = []
        # The issues: lines are the user's text: item2/issues-malformed is
        # their only finding, so they never become fixable item-1 rows or an
        # alias-inventory gap.
        _issues_owned = {i for _start, _end in issues_spans(fm_raw)
                         for i in range(_start, _end)}
        fm = parse_fm("\n".join("" if i in _issues_owned else line
                                for i, line in enumerate(fm_raw.split("\n"))),
                      _fm_bad)
        for _ln in _fm_bad:
            problems.append((sl,"item1",
                             f"unparseable frontmatter line: {_ln.strip()[:60]!r}"))
        for _line_no, _line in enumerate(fm_raw.split("\n"), 2):
            if _line_no - 2 in _issues_owned:
                continue
            _list_match = re.match(r"^([ \t]*)-", _line)
            if _list_match and _list_match.group(1) != "  ":
                problems.append((
                    sl, "item1",
                    "frontmatter line %d: block-list items use exactly two "
                    "spaces before '-'" % _line_no))
            if re.match(r"^  -[ \t]+#", _line):
                problems.append((
                    sl, "item1",
                    "frontmatter line %d: an unquoted hash list item is a "
                    "YAML comment, not a value" % _line_no))
        def _scalar(k):                    # a key written as a list is not a scalar
            v = fm.get(k, "")
            return v if isinstance(v, str) else ""
        sources = fm.get("sources") or []
        if isinstance(sources, str): sources = [sources]
        title = _scalar("title")
        aliases_present = "aliases" in fm
        aliases_spelling = raw_scalar(fm_raw, "aliases")
        aliases_is_list = (
            isinstance(fm.get("aliases"), list)
            and (bool(aliases_spelling and aliases_spelling.startswith("[")
                      and aliases_spelling.endswith("]"))
                 or has_block_items(fm_raw, "aliases")))
        aliases_all = (list(fm["aliases"])
                       if aliases_is_list else [])
        aliases = [a for a in aliases_all if isinstance(a, str) and a]
        alias_key_count = sum(
            bool((match := FM_KEY.match(line)) and match.group(1) == "aliases")
            for line in fm_raw.split("\n"))
        aliases_complete = (
            not _fm_bad and not _frontmatter_boundary_bad
            and alias_key_count <= 1
            and (not aliases_present
                 or (isinstance(fm.get("aliases"), list)
                     and all(isinstance(a, str) for a in fm["aliases"]))))
        if not aliases_complete:
            alias_inventory_gaps.add((sl, problems.current_path))
        tags_raw = fm.get("tags", []) if isinstance(fm.get("tags"), list) else ([fm["tags"]] if fm.get("tags") else [])
        tags_raw = [t.strip() for t in tags_raw if isinstance(t, str) and t.strip()]  # decoded, non-null tags
        tag_slugs = [t.lstrip("#").strip() for t in tags_raw]          # discipline slugs without the # prefix, for MOC/hierarchy use
        # The lightweight YAML parser can recover values from malformed input
        # or ignore an earlier quoted/escaped tag key. Require a structurally
        # readable document and unique tag key before classifying a genuine
        # blank for repair or an explicit sole #misc for hierarchy membership.
        _fm_lines = fm_raw.split("\n")
        _tag_lines = [i for i, line in enumerate(_fm_lines)
                      if (match := FM_KEY.match(line)) and match.group(1) == "tags"]
        tags_valid_misc = (not _fm_bad and len(_tag_lines) == 1
                           and fm.get("tags") == ["#misc"])
        tags_valid_single = (not _fm_bad and len(_tag_lines) == 1
                             and isinstance(fm.get("tags"), list)
                             and len(fm["tags"]) == 1
                             and fm["tags"][0] in {"#" + d for d in VALID_TAGS})
        tags_valid_empty = False
        if not _fm_bad and len(_tag_lines) == 1 and fm.get("tags") == []:
            _tag_i = _tag_lines[0]
            _tag_end = next((i for i in range(_tag_i + 1, len(_fm_lines))
                             if FM_KEY.match(_fm_lines[i])), len(_fm_lines))
            _tag_spelling = FM_KEY.match(_fm_lines[_tag_i]).group(2).strip()
            tags_valid_empty = (
                (_tag_spelling == "" or _tag_spelling.startswith("["))
                and all(not line.strip() or line.lstrip().startswith("#")
                        for line in _fm_lines[_tag_i + 1:_tag_end]))
        desc = _scalar("description")
        created = _scalar("created"); updated = _scalar("updated")
        key_order = [m.group(1) for line in fm_raw.split("\n") if (m:=FM_KEY.match(line))]
        prose, rel, fcsec, flash_off, flash_head = regions(body)
        body_lines, related_indexes, flashcard_indexes = \
            section_marker_indexes(body)
        _table_lines, table_spans = markdown_tables(body)
        parents_present = "parents" in fm
        parents_spelling = raw_scalar(fm_raw, "parents")
        parents_is_list = isinstance(fm.get("parents"), list)
        parents_all = list(fm.get("parents", [])) if parents_is_list else []
        issues_state = issues_value(fm_raw)
        record = dict(slug=sl, title=title, aliases=aliases,
                      aliases_complete=aliases_complete,
                      aliases_all=aliases_all,
                      aliases_present=aliases_present,
                      aliases_is_list=aliases_is_list, type=_scalar("type"),
                      tags_raw=tags_raw, tag_slugs=tag_slugs,
                      tags_valid_empty=tags_valid_empty,
                      tags_valid_misc=tags_valid_misc,
                      tags_valid_single=tags_valid_single,
                      tags_value_count=len(fm["tags"]) if isinstance(fm.get("tags"), list) else 0,
                      sources=sources, sources_is_list=isinstance(fm.get("sources"), list),
                      body=body, prose=prose, rel=rel, fcsec=fcsec, desc=desc,
                      created=created, updated=updated,
                      blank_after=bool(blank_after),
                      body_line_offset=blank_after,
                      parents=parents_all,
                      parents_present=parents_present,
                      parents_is_list=parents_is_list,
                      parents_spelling=parents_spelling,
                      issues_state=issues_state,
                      key_order=key_order, fm_raw=fm_raw,
                      flash_off=flash_off, flash_head=flash_head,
                      has_flashcards=(flash_off != -1),
                      has_related=bool(rel), path_key=path_key,
                      table_spans=table_spans, body_lines=body_lines,
                      related_indexes=related_indexes,
                      flashcard_indexes=flashcard_indexes)
        path_records[path_key] = record
        if keep_entry:
            entries[sl] = record
    problems.current_path = ""

    # Every parsed physical file receives source-independent local QC. The
    # slug-keyed ``entries`` map deliberately remains the unique-owner model
    # used by resolution, collision planning, backfill, renames, and hierarchy.
    diagnostic_records = sorted(
        (record for record in path_records.values() if record is not None),
        key=lambda record: (fold_name(record["path_key"]), record["path_key"]),
    )

    # fold_name(slug) -> exact on-disk slug. A unique case/normalization match
    # is an existing owner needing canonical spelling, not a missing target;
    # this decision stays the same across supported filesystems.
    fold_of = {}
    for _sl in entries:
        fold_of.setdefault(fold_name(_sl), _sl)
    # Files on disk that did NOT parse into `entries`: a link to one of these
    # resolves in Obsidian, so it is not a dangler and must never be unlinked.
    on_disk_fold = {fold_name(_sl) for _sl in on_disk} - set(fold_of)
    # fold_name(alias) -> (owning slug, the alias as spelled). Obsidian
    # resolves [[tpr]] to the entry whose `aliases:` carries "tpr" when no FILE
    # answers to that name -- shared/CONVENTIONS.md §4b calls an alias an
    # alternative slug, and wiki-build's find_collisions.build_targets probes
    # aliases for exactly that reason. A file always wins over an alias, so
    # this is consulted only after the slug and on-disk lookups, and it is not
    # a fallback for them. Keep ambiguous owners separate: item 18 reports
    # the collision, but item 10 must not choose a rewrite target for it.
    alias_of = {}
    ambiguous_aliases = set()
    alias_inventory_complete = not alias_inventory_gaps
    # A skipped file may own any alias, including one otherwise claimed by a
    # single parsed note. Keep local QC/collision evidence, but do not expose
    # a partial alias map to link, label, or parent canonicalization.
    # The second file sharing a portable basename may carry aliases absent
    # from the first. Inventory all physical records, but keep those aliases
    # report-only: the slug-keyed repair model cannot choose one such file.
    for _e in (diagnostic_records if alias_inventory_complete else ()):
        _sl = _e["slug"]
        for _a in _e["aliases"]:
            _k = fold_name(_a)
            if _k:
                if (fold_name(_sl) in ambiguous_files
                        or (_k in alias_of and alias_of[_k][0] != _sl)):
                    ambiguous_aliases.add(_k)
                alias_of.setdefault(_k, (_sl, _a))

    _wiki_prefixes = {
        fold_name(os.path.basename(os.path.abspath(wiki))) + "/",
        "wiki/",
        fold_name(os.path.relpath(os.path.abspath(wiki), vault_root).replace("\\", "/")) + "/",
    }
    def _entry_moc_roots(entry):
        return {d.lower() for d in entry["tag_slugs"]
                if d.lower() in VALID_TAGS
                and (d.lower() != "misc" or entry["tags_valid_misc"])}

    _moc_entry_counts = {}
    for _entry in entries.values():
        for _discipline in _entry_moc_roots(_entry):
            _moc_entry_counts[_discipline] = _moc_entry_counts.get(_discipline, 0) + 1
    moc_states, legacy_moc_states, moc_inventory_findings, _moc_texts = \
        inventory_mocs(vault_root, _moc_entry_counts)
    _moc_state_by_discipline = {row["discipline"]: row for row in moc_states}
    _moc_canonical_by_fold = {fold_name("MOCs/" + moc_stem(d)): "MOCs/" + moc_stem(d)
                              for d in VALID_TAGS}
    # Non-enum Markdown notes are outside discipline-root ownership, but their
    # real filenames still outrank aliases and collide with Wiki basenames.
    _moc_unknown_basenames = {
        fold_name(os.path.basename(row["path"])[:-3])
        for row in moc_inventory_findings if row["kind"] == "unexpected-moc"}
    _moc_basename_owners = {
        moc_stem(row["discipline"]) for row in moc_states
        if row["state"] != "missing"
    } | _moc_unknown_basenames
    # Legacy names include a previous-layout `MOCs/<discipline>.md`: while it
    # exists, a bare link to the same-named Wiki root stays ambiguous.
    _legacy_moc_names = {fold_name(os.path.basename(row["path"])[:-3])
                         for row in legacy_moc_states}
    # Any vault-root note named like a canonical MOC (`misc-moc.md` included,
    # though misc has no legacy root MOC) makes a bare `[[<name>]]` ambiguous.
    try:
        _root_moc_basenames = {
            fold_name(name[:-3]) for name in os.listdir(vault_root)
            if name.lower().endswith(".md") and moc_discipline(name[:-3])}
    except OSError:
        _root_moc_basenames = set()
    # Real notes outside Wiki/ and MOCs/, such as an Articles/ reading note:
    # Obsidian resolves a link to one by path or basename, so it is neither
    # an entry dangler nor an alias, and it is another owner of a same-named
    # entry's bare name. Only a known vault root is walked; the parent-folder
    # fallback may be any directory, so it proves nothing about the vault.
    if vault_root_known:
        _outside_paths, _outside_basenames, _outside_complete = \
            vault_note_index(vault_root, wiki)
    else:
        _outside_paths, _outside_basenames, _outside_complete = {}, {}, False

    def _origin_target_key(raw_target, note_path=None):
        target = entry_link_path_key(raw_target)
        if target.startswith(("./", "../")):
            if note_path is None:
                return None
            target = fold_name(posixpath.normpath(posixpath.join(
                posixpath.dirname(note_path), target)))
            if target == ".." or target.startswith("../"):
                return None
        return target

    def _resolve_entry_file(raw_target, note_path=None):
        """Resolve a Wiki file target without discarding path qualification.

        Returns ``(record, status, path_key)``. ``record`` is a parsed path
        record when available; ``status`` is ``parsed``, ``unparsed``,
        ``ambiguous``, ``missing``, or ``moc`` for the separate MOCs/ namespace.
        A bare basename with multiple owners is
        ambiguous even if one owner is at the Wiki root. A qualified target may
        use a vault-root prefix (``Wiki/a/foo``) or a unique suffix
        (``a/foo``), and therefore remains resolvable under a basename clash.
        """
        target_key = _origin_target_key(raw_target, note_path)
        if target_key is None:
            return None, "missing", None
        note_relative = entry_link_path_key(raw_target).startswith(("./", "../"))
        # MOCs/ is a reserved vault-root namespace, never a unique Wiki path
        # suffix. The explicit Wiki/MOCs/foo path still addresses a Wiki entry.
        if target_key.startswith("mocs/"):
            return None, "moc", None
        if note_relative:
            public_wiki_prefix = fold_name(os.path.relpath(
                os.path.abspath(wiki), vault_root).replace("\\", "/")) + "/"
            if not target_key.startswith(public_wiki_prefix):
                return None, "missing", None
        basename_key = target_key.rsplit("/", 1)[-1]
        owners = paths_by_basename.get(basename_key, set())
        if "/" not in target_key and basename_key in _moc_basename_owners:
            # A real MOC file outranks any entry alias with its basename. Only
            # an actual same-named Wiki file makes the bare target ambiguous.
            return None, ("ambiguous" if owners else "moc"), None
        if "/" not in target_key and basename_key in _legacy_moc_names:
            return None, ("ambiguous" if owners else "moc"), None
        if not owners:
            return None, "missing", None
        lookup = target_key
        for prefix in sorted(_wiki_prefixes, key=lambda value: (-len(value), value)):
            if lookup.startswith(prefix):
                lookup = lookup[len(prefix):]
                break
        if "/" not in target_key:
            if len(owners) != 1:
                return None, "ambiguous", None
            owner = next(iter(owners))
        else:
            exact = {candidate for candidate in owners
                     if entry_link_path_key(candidate) == lookup}
            if len(exact) == 1:
                owner = next(iter(exact))
            elif len(exact) > 1:
                return None, "ambiguous", None
            elif note_relative:
                return None, "missing", None
            else:
                candidates = {
                    candidate for candidate in owners
                    if entry_link_path_key(candidate).endswith("/" + lookup)
                }
                if len(candidates) != 1:
                    return None, ("ambiguous" if candidates or len(owners) > 1
                                  else "missing"), None
                owner = next(iter(candidates))

        record = path_records.get(owner)
        return record, ("parsed" if record is not None else "unparsed"), owner

    def _outside_owners(raw_target, note_path=None):
        """Vault notes outside Wiki/ and MOCs/ that a link target names.

        Uses `_resolve_entry_file`'s rules: a `./` or `../` path from the
        note's folder, an exact vault path, a path suffix or a bare basename.
        Several owners are still a real note that Obsidian opens, so any
        match means the target is not a dangler. Returns exact paths.
        """
        if not _outside_paths:
            return []
        key = _origin_target_key(raw_target, note_path)
        if not key:
            return []
        if entry_link_path_key(raw_target).startswith(("./", "../")):
            return _outside_paths.get(key, [])
        if "/" not in key:
            return _outside_basenames.get(key, [])
        if key in _outside_paths:
            return _outside_paths[key]
        return sorted(path for owner_key, owned in _outside_paths.items()
                      if owner_key.endswith("/" + key) for path in owned)

    _vault_targets = {}

    def _entry_vault_target(record):
        # Memoized: link resolution asks once per link, and each relpath
        # costs two getcwd calls (a sixth of a 2,000-entry scan).
        path_key = record["path_key"]
        if path_key not in _vault_targets:
            path = os.path.join(wiki, path_key)
            _vault_targets[path_key] = os.path.relpath(
                path, vault_root).replace("\\", "/")[:-3]
        return _vault_targets[path_key]

    def _entry_parent_target(record):
        """Bare slug, or the Wiki path when another file shares the basename.

        A discipline root is no exception: its MOC is `<discipline>-moc`, so
        only a previous-layout MOC or another same-named file qualifies it.
        """
        if (fold_name(record["slug"]) in _moc_basename_owners
                or fold_name(record["slug"]) in _legacy_moc_names
                or fold_name(record["slug"]) in ambiguous_files):
            return _entry_vault_target(record)
        return record["slug"]

    def _entry_link_target(record):
        """Body and Related form: also qualified beside a note outside Wiki/.

        CONVENTIONS §6 qualifies a body or Related link when any other real
        vault file owns the bare name; a `parents:` value counts only Wiki
        and MOC owners (`_entry_parent_target`).
        """
        if fold_name(record["slug"]) in _outside_basenames:
            return _entry_vault_target(record)
        return _entry_parent_target(record)

    def _final_link_target(raw_target, record, qualified_target):
        """The canonical spelling of a body or Related link to one entry.

        Drops an explicit `.md` suffix, which never changes the destination.
        Drops a path as well when the complete vault inventory proves that no
        other file owns the bare name. Otherwise keeps the on-disk spelling of
        the path the link uses. A bare link is qualified only when its `.md`
        is respelled anyway and another vault file owns the bare name, so it
        takes the form `_entry_link_target` supplies.
        """
        written = raw_target.replace("\\", "/").strip().strip("/")
        if qualified_target is None:
            if written.lower().endswith(".md"):
                return _entry_link_target(record)
            return record["slug"]
        if (_outside_complete
                and _entry_link_target(record) == record["slug"]):
            return record["slug"]
        if written.lower().endswith(".md") and \
                qualified_target.lower().endswith(".md"):
            return qualified_target[:-3]
        return qualified_target

    def _resolve_parent_target(target, note_path=None):
        """Resolve paths before basenames; legacy MOCs never supply a new root."""
        key = _origin_target_key(target, note_path)
        if key is None:
            return None, "missing"
        if key.startswith("mocs/"):
            stem = key[len("mocs/"):]
            discipline = moc_discipline(stem)
            if discipline is None:
                if stem in _legacy_moc_names:
                    return None, "legacy-moc"
                return None, ("unexpected-moc" if stem in _moc_unknown_basenames
                              else "missing")
            state = _moc_state_by_discipline.get(discipline, {})
            if state.get("state", "missing") in {"missing", "unreadable"}:
                return None, state.get("state", "missing")
            return "@moc:" + discipline, None
        record, status, owner_path = _resolve_entry_file(target, note_path)
        if "/" not in key and key in _moc_basename_owners:
            if status not in {"missing", "moc"}:
                return None, "ambiguous"
            if key in _root_moc_basenames:
                # A vault-root `<discipline>-moc.md` shares the canonical
                # MOC's basename, so the bare target has two owners.
                return None, "ambiguous"
            if key in _moc_unknown_basenames:
                return None, "unexpected-moc"
            discipline = moc_discipline(key)
            state = _moc_state_by_discipline[discipline]
            if state["state"] == "unreadable":
                return None, "unreadable"
            return "@moc:" + discipline, None
        if "/" not in key and key in _legacy_moc_names:
            return None, ("legacy-moc" if status in {"missing", "moc"}
                          else "ambiguous")
        if status == "parsed" and record is not None:
            if fold_name(record["slug"]) in ambiguous_files:
                # The global hierarchy census cannot safely merge two physical
                # entries that share one slug, even if this edge is qualified.
                return None, "ambiguous"
            return record["slug"], None
        if status != "missing":
            return None, status
        if "/" in key:
            return None, "missing"
        if not alias_inventory_complete:
            return None, "unparsed"
        if key in ambiguous_aliases:
            return None, "ambiguous"
        if key in alias_of:
            owner = alias_of[key][0]
            return owner, None
        return None, "missing"

    def _canonical_qualified_target(raw_target, owner_path, note_path=None):
        """Exact spelling of the qualified path form that resolved ``owner``.

        Resolution deliberately folds case and Unicode so it behaves the same
        across filesystems. Repair diagnostics need the opposite view: retain
        every directory component as it exists on disk, while preserving a
        caller's valid unique-suffix qualification and optional ``Wiki/``
        prefix and ``.md`` suffix.
        """
        target = raw_target.split("#", 1)[0].split("^", 1)[0].strip()
        target = target.replace("\\", "/").strip().strip("/")
        if "/" not in target:
            return None

        if target.startswith(("./", "../")):
            if note_path is None:
                return None
            actual = os.path.relpath(os.path.join(wiki, owner_path), vault_root).replace("\\", "/")
            if not target.lower().endswith(".md"):
                actual = actual[:-3]
            relative = posixpath.relpath(actual, posixpath.dirname(note_path))
            return ("./" + relative if target.startswith("./")
                    and not relative.startswith(".") else relative)

        parts = target.split("/")
        canonical_prefix = []
        wiki_name = os.path.basename(os.path.abspath(wiki))
        vault_wiki_parts = os.path.relpath(os.path.abspath(wiki), vault_root).replace("\\", "/").split("/")
        if (len(parts) > len(vault_wiki_parts)
                and list(map(fold_name, parts[:len(vault_wiki_parts)]))
                == list(map(fold_name, vault_wiki_parts))):
            canonical_prefix = vault_wiki_parts
            parts = parts[len(vault_wiki_parts):]
        elif parts and fold_name(parts[0]) == fold_name(wiki_name):
            canonical_prefix = [wiki_name]
            parts = parts[1:]
        elif parts and fold_name(parts[0]) == "wiki":
            # Test fixtures and callers may pass the Wiki folder itself under
            # another temporary basename; ``Wiki/`` is the documented
            # vault-root qualifier in either case.
            canonical_prefix = ["Wiki"]
            parts = parts[1:]
        if not parts:
            return None

        explicit_md = parts[-1].lower().endswith(".md")
        owner = owner_path.replace("\\", "/").strip("/")
        owner_no_ext = owner[:-3] if owner.lower().endswith(".md") else owner
        owner_parts = owner_no_ext.split("/")

        # `_resolve_entry_file` accepts an exact path or a unique suffix. Keep
        # that useful amount of qualification rather than needlessly widening
        # a link, but take the spelling of every retained component from disk.
        count = len(parts)
        selected = (owner_parts[-count:] if count <= len(owner_parts)
                    else owner_parts)
        if explicit_md and selected:
            extension = owner[-3:] if owner.lower().endswith(".md") else ".md"
            selected[-1] += extension
        return "/".join(canonical_prefix + selected)

    # Any existing entry is a named referent: a Work, or a named method such
    # as SGDR (writing.md's "the authors of SGDR"). A lowercase match counts
    # only when it spells a title exactly, so "the authors of machine
    # learning textbooks" stays source-meta.
    _named_surfaces = set()
    _title_surfaces = set()
    for _entry in entries.values():
        _title = _entry.get("title") or ""
        _titles = {" ".join(_title.split()),
                   " ".join(base_term(_title).split())}
        for _surface in list(_titles) + list(_entry.get("aliases", [])):
            _surface = " ".join((_surface or "").split()).strip()
            if not _surface:
                continue
            _variants = {_surface, _surface.replace("-", " ")}
            _named_surfaces |= _variants
            if _surface in _titles:
                _title_surfaces |= _variants
    _named_surfaces = sorted(_named_surfaces,
                             key=lambda value: (-len(value), value))

    def _authors_phrase_names_entry(remainder, note_path=None):
        """Whether the text after ``the author(s) of`` names an entry."""
        linked = WIKILINK.match(remainder)
        if linked is not None and linked.start() == 0:
            target = linked.group(1)
            record, status, _path = _resolve_entry_file(target, note_path)
            key = entry_link_key(target)
            if (record is None and status == "missing"
                    and key not in ambiguous_aliases and key in alias_of):
                record = entries.get(alias_of[key][0])
            return record is not None

        # Work titles are often italicized in prose. Strip only a leading
        # emphasis delimiter; the boundary after the matched surface may be
        # the closing delimiter itself.
        visible = re.sub(r"^[*_]{1,3}", "", remainder)
        for surface in _named_surfaces:
            found = re.match(re.escape(surface) + r"(?![A-Za-z0-9])",
                             visible, re.IGNORECASE)
            if found and (found.group(0) in _title_surfaces
                          or found.group(0) != found.group(0).lower()):
                return True
        return False

    # Read-only inputs for Task 2 (`hub_footer`), Task 3 (`unlinked_children`)
    # and item 19 (`card_rivals`, `spaced_repetition`), collected once in the
    # per-entry loop. Only uniquely owned slugs take part: a basename shared by
    # two files names no single entry to link, place or compare.
    _linked_owners = defaultdict(set)   # slug -> entries its prose or footer links
    _footer_owners = defaultdict(set)   # slug -> entries its Related footer links
    _footer_links = {}                  # slug -> wikilinks in its Related footer
    _primary_cues = {}                  # slug -> line 1 of its primary card
    user_issues = []                    # entries whose issues: is non-blank

    def _unique_slug(slug_value):
        return slug_value in entries and fold_name(slug_value) not in ambiguous_files

    for e in diagnostic_records:
        sl = e["slug"]
        _unique_owner = _unique_slug(sl)
        problems.current_path = (
            e["path_key"]
            if fold_name(sl) in ambiguous_files else "")
        fm_raw, title = e["fm_raw"], e["title"]
        # ---- item 5: slug == filename; bare-slug cross-domain term ----
        _newslug = slug(title) if title else ""
        if title and not _newslug:
            problems.append((sl,"item5",f'title "{title[:60]}" cannot be slugged automatically (it reduces to '
                                        f'the empty slug, or its slug exceeds the filename budget) — ask the '
                                        f'user for an ASCII-representable, shorter title; DO NOT rename the file'))
        elif title and _newslug != sl:
            problems.append((sl,"item5",f'title "{title}" slugs to "{_newslug}" ≠ filename'))
        if bare_common_noun_slug(sl):
            problems.append((sl,"item5",f'bare-slug cross-domain term "{sl}" — retitle it through '
                                        f'the entry-retitle protocol when special-titles.md determines '
                                        f'its qualified title and that slug is free; the bare slug never '
                                        f'stays an alias'))
        # ---- item 2: field order, required keys, duplicate keys, quoting ----
        known = [k for k in e["key_order"] if k in CANON]
        if [CANON.index(k) for k in known] != sorted(CANON.index(k) for k in known):
            problems.append((sl,"item2","fields out of schema order: "+", ".join(e["key_order"])))
        for k in e["key_order"]:
            if k in CANON:
                continue
            if k.lower() in OBSIDIAN_KEYS:
                # REPORT ONLY. See OBSIDIAN_KEYS: this is Obsidian's own
                # property, not a schema violation, and the only determinate
                # reading of an item-2 "fix in place" is deletion — which
                # silently destroys appearance/publish configuration the user
                # set and this plugin can never reconstruct.
                problems.append((sl,"item2/obsidian-key",
                                 f'frontmatter key "{k}" is an Obsidian built-in property, not part of '
                                 f'the entry schema — REPORT ONLY, DO NOT DELETE OR REORDER. It is the '
                                 f"user's own appearance/publish configuration; deleting it is the only "
                                 f'thing "fix in place" could mean here, and nothing can restore it. '
                                 f'Preserve it and report it as optional user-owned configuration; '
                                 f'the lint run still completes'))
                continue
            problems.append((sl,"item2",f'unexpected frontmatter key "{k}" — preserve this user metadata; do not delete or repurpose it from a schema mismatch alone'))
        # A duplicate issues: key is the report-only issues-malformed below.
        _other_keys = [k for k in e["key_order"] if k != "issues"]
        if len(_other_keys) != len(set(_other_keys)):
            problems.append((sl,"item2","duplicate frontmatter key (stacked-body artifact?)"))
        # Every MANDATORY key must be PRESENT, whatever its value — a missing
        # KEY and a missing VALUE are two findings and both are real (item 7
        # reports an absent description, item 3 an absent date; item 2 reports
        # that the key itself is gone). This used to name four keys by hand,
        # and the five it omitted included `title:`, whose absence silently
        # switched off item 5, item 16, the rename candidate and the entry's
        # whole contribution to the surface and display-label maps — so the
        # entry came back from a whole-vault QC pass with nothing at all
        # against it, while a single-file lint_entry run on it reported two.
        # `tags`, `read` and `issues` keep their own messages below; a
        # missing `read:` is report-only.
        for _k in MANDATORY_KEYS:
            if _k in e["key_order"] or _k in ("tags", "read", "title", "issues"):
                continue
            problems.append((sl,"item2",f"missing {_k}: key"))
        # A `title:` KEY with no scalar value (bare, null, or a list) is the
        # same silent no-op as a missing key: `title` is "" either way, and
        # everything below gates on the value, not the key — so only the
        # key-absence half of this used to be checked, and a valueless
        # `title:` came back from a whole-vault pass with no findings while a
        # single-file lint reported two.
        if "title" not in e["key_order"] or not title:
            problems.append((sl,"item2",
                             ("missing title: key" if "title" not in e["key_order"]
                              else "title: key carries no value")
                             + " — the entry has no canonical name, so every "
                             "check that starts from one is a silent no-op on it: the item-5 "
                             "slug↔filename comparison, the item-16 opener check, its rename "
                             "candidate, its surface forms for backfill, and the item-18 "
                             "display-label test on every link pointing at it. Recover a title "
                             "only from one unambiguous canonical name evidenced by the entry; "
                             "otherwise preserve and report it without blocking the run. DO NOT "
                             "invent one from the filename"))
        # read: — the user's review checkbox (CONVENTIONS.md §2c).  Four
        # distinct states, and they route three different ways, which is why
        # they are three messages rather than one:
        #   absent      -> REPORT ONLY.  The linter writes no value here outside
        #                  READ_EXCEPTIONS (a resolved user issue or a merge's
        #                  survivor), and the only value it could supply is
        #                  `false`, which would mark an entry the user has
        #                  already read as unread —
        #                  destroying the one piece of state the field exists to
        #                  hold. Same class as item3/report-only.
        #   present, no -> REPORT ONLY, same class and for the same reason: a
        #   value         bare `read:`, `read: null` and `read: ~` are all YAML
        #                 null, so there is no value here to retype and no sense
        #                 to preserve.  Writing `false` would INVENT one and
        #                 clear a tick the user set — which is precisely the harm
        #                 read-missing is report-only to prevent, so the two
        #                 cannot route differently.  (Contrast item2/parents-null,
        #                 which IS fixed in place: `[]` re-spells an empty value
        #                 that is already empty, and changes nothing.)
        #   wrong type  -> ordinary fix in place.  The meaning is unambiguous;
        #                  only the spelling is wrong, and the value is preserved.
        #   out of order-> already caught by the schema-order check above.
        _read_raw = raw_scalar(fm_raw, "read") or ""
        try:
            _read_value, _read_style = parse_scalar(_read_raw)
        except ValueError:
            _read_value, _read_style = None, "invalid"
        if "read" not in e["key_order"]:
            problems.append((sl,"item2/read-missing",
                             "missing read: key — the user's review checkbox. Report it "
                             "and write no value, since `false` would mark an entry they "
                             "have already read as unread. " + READ_EXCEPTIONS
                             % "inserts `read: false` directly before issues:"))
        elif _read_raw.strip().lower() in READ_NULLS and not has_block_items(fm_raw, "read"):
            problems.append((sl,"item2/read-null",
                             'read: is present but carries no value (%s) — YAML null, not a '
                             'boolean, so Obsidian shows the checkbox unticked while the entry '
                             'records no answer at all. Report it; DO NOT FIX. There is no '
                             'value here to preserve, so writing `false` would invent one and '
                             'clear a tick the user may have set — the same harm, and the same '
                             'report-only class, as a missing read: key. '
                             % ("bare `read:`" if not _read_raw.strip()
                                else "`read: %s`" % _read_raw.strip())
                             + READ_EXCEPTIONS % "sets `read: false`"))
        elif not isinstance(_read_value, str) or _read_value.lower() not in {"true", "false", "yes", "no", "0", "1"}:
            problems.append((sl,"item2/read-unknown",
                             'read: has no recognizable boolean answer (%r) -- REPORT ONLY, '
                             'DO NOT FIX. Neither true nor false can be inferred safely; '
                             'leave this user-owned state unresolved and continue the run. '
                             % _read_raw + READ_EXCEPTIONS % "sets `read: false`"))
        elif _read_style != "bare" or _read_value.lower() not in READ_BOOLEANS:
            problems.append((sl,"item2/read-type",
                             'read: must be a bare boolean (`true` / `false`), not %r — a '
                             'quoted "false" is a string, and Obsidian renders any non-empty '
                             'string in a checkbox property as permanently checked; `yes`/`no` '
                             'and `0`/`1` are the same field written in the wrong spelling. '
                             'Fix the spelling, keep the value' % _read_raw))
        # issues: — the user's issue inbox (CONVENTIONS.md §2d).  A missing
        # key is a format repair; a malformed value is the user's own text,
        # so it is reported and never rewritten.  Every blank spelling
        # conforms, and a non-blank value is a `user_issues` worklist row.
        _issues_state, _issues_form, _issues_items, _issues_detail = \
            e["issues_state"]
        if _issues_state == "missing":
            problems.append((sl,"item2/issues-missing",
                             "missing issues: key — the user's issue inbox. Insert "
                             '`issues: ""` directly after read: (after the last schema key '
                             "before it when read: is absent too), keeping dates and read:"))
        elif _issues_state == "malformed":
            problems.append((sl,"item2/issues-malformed",
                             "issues: holds %s, not a string or a list of strings — "
                             "REPORT ONLY, DO NOT FIX. It is the user's own text: preserve "
                             "it byte-for-byte and report it so the user can rewrite it%s"
                             % (_issues_detail,
                                ". Obsidian cannot read this note's properties until "
                                "the user rewrites it"
                                if _issues_detail in ISSUES_NOT_YAML else "")))
        elif _issues_state == "issues":
            _user_issue = {"slug": sl, "form": _issues_form,
                           "issues": list(_issues_items)}
            if fold_name(sl) in ambiguous_files:
                _user_issue["path"] = e["path_key"]
            user_issues.append(_user_issue)
        # parents: — a bare key is YAML null, not an empty list.  The vault pins
        # the property as `multitext` (.obsidian/types.json), so null renders as
        # an empty TEXT field: the declared type and the value on disk disagree.
        # `[]` is the only spelling that is both a valid empty list and visibly
        # one.  An ordinary fix in place — nothing about the entry changes but
        # the spelling of an empty value.  CONVENTIONS.md §2a.
        if "parents" in e["key_order"] \
                and raw_scalar(fm_raw, "parents") == "" \
                and not has_block_items(fm_raw, "parents"):
            problems.append((sl,"item2/parents-null",
                             "empty parents: is written `parents: []` — a bare key is YAML "
                             "null, which renders as an empty text field rather than an "
                             "empty list under the vault's multitext type"))
        elif e["parents_present"] and not e["parents_is_list"]:
            problems.append((sl, "item2/parents-form",
                             "parents: must be a list — use `parents: []` when empty, or "
                             "a block-form list of double-quoted canonical wikilinks"))
        elif (e["parents_present"] and e["parents_is_list"]
              and not e["parents"]
              and (e["parents_spelling"] or "").startswith("[")
              and e["parents_spelling"] != "[]"):
            problems.append((sl, "item2/parents-form",
                             "an empty parents: list must be spelled exactly "
                             "`parents: []`"))
        elif e["parents_present"] and e["parents"]:
            if (e["parents_spelling"] or "").startswith("["):
                problems.append((sl, "item2/parents-form",
                                 "a populated parents: value must use block form, one "
                                 "double-quoted canonical wikilink per line"))
            _parent_seen = {}
            for _parent in e["parents"]:
                if not isinstance(_parent, str):
                    # The frontmatter parser already reports the invalid YAML
                    # scalar under item1; do not prescribe a second repair.
                    continue
                _parent_match = re.fullmatch(
                    r"\[\[([^\\\[\]\|#^]+)\]\]", _parent.strip())
                if not _parent_match:
                    problems.append((sl, "item2/parents-form",
                                     f'parents: item "{_parent}" must be one '
                                     "canonical wikilink with no display label, "
                                     "heading, block anchor, or `.md` suffix"))
                    continue
                _parent_target = _parent_match.group(1)
                _parent_key = entry_link_path_key(_parent_target)
                _parent_canonical = None
                _parent_owner, _parent_reason = _resolve_parent_target(
                    _parent_target, _entry_vault_target(e))
                if _parent_owner is not None:
                    if _parent_owner.startswith("@moc:"):
                        _parent_canonical = "MOCs/" + moc_stem(
                            _parent_owner[len("@moc:"):])
                    else:
                        _parent_canonical = _entry_parent_target(entries[_parent_owner])
                elif _parent_key in _moc_canonical_by_fold:
                    # Canonical naming is deterministic even before creation;
                    # existence remains the hierarchy diagnostic's finding.
                    _parent_canonical = _moc_canonical_by_fold[_parent_key]
                _parent_is_moc = (
                    (_parent_owner or "").startswith("@moc:")
                    or (_parent_owner is None
                        and _parent_key in _moc_canonical_by_fold))
                if (_parent_canonical is not None
                        and _parent_target != _parent_canonical):
                    if _parent_is_moc:
                        # A MOC is never a parent: respelling it would cement
                        # the invalid edge that Task 3 replaces (moc-parent).
                        problems.append((
                            sl, "item2/parents-form",
                            f'parents: item "{_parent_target}" names the navigation '
                            f'note "{_parent_canonical}"; a MOC is never a parent. '
                            "Report only; do not respell it. Task 3 replaces it with "
                            "the discipline root or nearest Wiki ancestor "
                            "(hierarchy_diagnostic moc-parent)"))
                    else:
                        problems.append((
                            sl, "item2/parents-form",
                            f'parent target "{_parent_target}" resolves to '
                            f'"{_parent_canonical}" — use this canonical target'))
                elif _parent_target.lower().endswith(".md"):
                    problems.append((sl, "item2/parents-form",
                                     "parent targets omit the `.md` suffix"))
                _parent_identity = fold_name(
                    _parent_canonical if _parent_canonical is not None
                    else _parent_target)
                if _parent_identity in _parent_seen:
                    problems.append((sl, "item2/parents-form",
                                     f'parent "{_parent}" is listed more than once'))
                else:
                    _parent_seen[_parent_identity] = _parent
        # No missing-importance: check — the field left the schema (see CANON above).
        if "tags" not in e["key_order"]:
            problems.append((sl,"item2","missing tags: key (mandatory — requires exactly one discipline tag)"))
        if not e["type"]:
            problems.append((sl,"item2/type-enum",
                             "type: is blank or non-scalar — it must be one of the 15 canonical type values"))
        elif e["type"] not in VALID_TYPES:
            problems.append((sl,"item2/type-enum",
                             f'type: "{e["type"]}" is not one of the 15 canonical type values'))
        cur = None
        for line in fm_raw.split("\n"):
            mt = FM_KEY.match(line)
            if mt:
                k, val = mt.group(1), strip_comment(mt.group(2)).strip(); cur = None
                try:
                    _value, _style = parse_scalar(val)
                except ValueError:
                    _value, _style = None, "invalid"
                if (k in ("title", "description") and val
                        and _style != "double"
                        and not plain_string_allowed(_value, _style)):
                    problems.append((
                        sl, "item2",
                        f'{k} must be double-quoted unless its plain YAML '
                        'spelling round-trips as a string'))
                if k in ("type","created","updated") and (val.startswith('"') or val.startswith("'")):
                    problems.append((sl,"item2",f'{k} must not be quoted'))
                if k in ("aliases","sources","tags","parents"):
                    if val.startswith("[") and val.endswith("]"):    # flow list, complete on this line
                        try:
                            flow_items = split_flow(val[1:-1])
                        except ValueError:
                            flow_items = []  # parse_fm already emitted item 1
                        for iv in flow_items:
                            try:
                                _iv_style = parse_scalar(iv)[1]
                            except ValueError:
                                _iv_style = "invalid"
                            try:
                                _iv_value = parse_scalar(iv)[0]
                            except ValueError:
                                _iv_value = None
                            if (_iv_style != "double"
                                    and not (_plain_item_allowed(k, _iv_value)
                                             and plain_string_allowed(
                                                 _iv_value, _iv_style))):
                                problems.append((sl,"item2",f'{k} item not double-quoted: {iv[:30]}'))
                    else:
                        cur = k
            else:
                mi = re.match(r"^\s*-\s*(.*)$", line)
                if mi and cur:
                    iv = mi.group(1).strip()
                    try:
                        _iv_style = parse_scalar(iv)[1]
                    except ValueError:
                        _iv_style = "invalid"
                    try:
                        _iv_value = parse_scalar(iv)[0]
                    except ValueError:
                        _iv_value = None
                    if (iv and _iv_style != "double"
                            and not (_plain_item_allowed(cur, _iv_value)
                                     and plain_string_allowed(
                                         _iv_value, _iv_style))):
                        problems.append((sl,"item2",f'{cur} item not double-quoted: {iv[:30]}'))
        # ---- item 3: dates ----
        for f in ("created","updated"):
            v = e[f]
            if isinstance(v,str) and v:
                if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
                    problems.append((sl,"item3",f'{f} "{v}" not YYYY-MM-DD'))
                else:
                    try: datetime.datetime.strptime(v, "%Y-%m-%d")
                    except ValueError: problems.append((sl,"item3",f'{f} "{v}" is not a valid date'))
            else:
                problems.append((sl,"item3",f'{f} missing'))
        def _valid(d):
            """The `date` this field denotes, or None when it denotes none.

            **The format finding and the ordering finding are separate, and
            this is the ordering one.** Item 3's `^\\d{4}-\\d{2}-\\d{2}$` check
            one block above already reports an unpadded `2026-1-1` on its own
            line; this parse is deliberately as permissive as `strptime` is,
            because `2026-2-05` names one day and nothing else. Refusing to
            ORDER a date that is merely spelled badly throws away a real
            finding to avoid a formatting question that is already reported —
            while both findings remain reportable without blocking the run.

            What must not happen is comparing the raw STRINGS, which is the
            bug this replaced: lexically "2026-1-1" sorts after "2026-01-02"
            (a correctly ordered entry routed to the report-only bucket) and
            "2026-12-01" sorts before "2026-2-05" (a
            genuinely reversed pair reported by nobody). Parse first, then
            compare the `date` objects; every unpadded spelling then orders
            exactly as the day it names.
            """
            if not isinstance(d, str) or not d:
                return None
            try:
                return datetime.datetime.strptime(d, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                return None
        # created > updated is REPORT-ONLY, not a fixable violation: wiki-lint never repairs a date or its
        # ordering (qc-items item 3; dates it writes follow SKILL.md#dates), so filing it as a lint problem would re-report the same entries forever with nothing the
        # linter can do. Its own item key routes it to the nonblocking report-only bucket instead.
        # Compared as DATES, never as strings — the strings are only interchangeable
        # with the dates once both are known to be zero-padded, which is what _valid checks.
        _created_d, _updated_d = _valid(e["created"]), _valid(e["updated"])
        if _created_d is not None and _updated_d is not None and _created_d > _updated_d:
            problems.append((sl,"item3/report-only",f'created {e["created"]} > updated {e["updated"]} — impossible ordering (updated is the last merge date, so it cannot precede creation); DO NOT FIX, leave unresolved and report without blocking the run'))
        # ---- item 4: sources format ----
        # Every entry, a discipline root included, cites at least one source.
        if not e["sources"]:
            problems.append((sl,"item4","sources: is empty; every entry needs at least one source"))
        elif not e["sources_is_list"]:
            problems.append((sl,"item4","sources: must be a list, not a scalar"))
        for i,src in enumerate(e["sources"]):
            if src is None:
                problems.append((sl,"item4","sources: contains a null or invalid item"))
                continue
            if source_reference_kind(src):
                continue
            problems.append((sl,"item4",f'source must be {SOURCE_REFERENCE_FORMS}; '
                             f'display labels, Markdown links and incomplete wikilinks '
                             f'are invalid: {src}'))
        _source_values = [src for src in e["sources"] if src is not None]
        for _duplicate_source in sorted({
                src for src in _source_values if _source_values.count(src) > 1}):
            problems.append((
                sl, "item4",
                f'source "{_duplicate_source}" is listed '
                f'{_source_values.count(_duplicate_source)} times — keep one '
                "exact citation"))
        # No two sources: items may name the same DOCUMENT. paper-summarize writes a note into
        # Articles/ for every PDF it summarises, so one document sits in the vault under two
        # names — Sources/PDFs/X.pdf and Articles/X.md — and both are legal sources:
        # values. A same-stem clipping may instead be an independent source, so the match
        # needs the markdown note's provenance before any source may be removed.
        # Only a stem collision ACROSS the two extensions counts — an entry may
        # legitimately cite several distinct PDFs and several distinct clippings —
        # and stems use the portable case/NFC identity from fold_name.
        pdf_by_stem, md_items = {}, []
        for src in e["sources"]:
            stem, ext = source_stem(src)
            if not stem: continue
            if ext == "pdf": pdf_by_stem.setdefault(stem, src)   # keep the first spelling
            elif ext == "md": md_items.append((stem, src))
        for stem, md_src in md_items:
            if stem not in pdf_by_stem: continue
            problems.append((sl,"item4/source-identity",
                             f'{md_src} and {pdf_by_stem[stem]} share a filename stem; review the '
                             f'markdown note\'s decoded sources: (or legacy source:) to establish '
                             f'whether it summarizes that PDF. A URL-origin clipping can be '
                             f'independent. Preserve both sources until their identity is confirmed'))
        # ---- item 6: type / API surface (non-Software entries) ----
        # Shared with lint_entry (entry_checks.api_surface_findings).
        for _api_finding in api_surface_findings(
                e["type"], title, e["prose"], e["body"]):
            problems.append((sl, "item6", _api_finding["message"]))
        # ---- item 7: description length + presence ----
        if not e["desc"]: problems.append((sl,"item7","missing description"))
        elif len(e["desc"]) > 110: problems.append((sl,"item7",f'description {len(e["desc"])} chars > 110'))
        marks = []
        if "$" in e["desc"]:
            marks.append("$ (LaTeX/currency)")
        # Description values are stricter than flashcard definitions: they
        # permit no presentation markup at all, while card line 1 permits
        # inline LaTeX. Reuse the shared Markdown/HTML classifier so the two
        # wiki validators do not silently disagree about links, underscore
        # emphasis, HTML, comments, highlights, footnotes, or block markup.
        marks.extend(flashcard_line1_markup(e["desc"]))
        if marks:
            problems.append((sl,"item7",f'description has non-plain-text markup ({", ".join(marks)}) — renders literally in Obsidian Properties'))
        if re.search(r"ℓ(?:[0-9₀-₉])", e["desc"]):
            problems.append((
                sl, "item12/equation-typography",
                "raw ℓ-norm notation in description must use plain words "
                "such as `ell-one` or `ell-two`; YAML descriptions do not "
                "render LaTeX"))
        if e["desc"]:
            sentence_count = count_sentences(e["desc"])
            if sentence_count > 1:
                problems.append((
                    sl, "item7",
                    f"description must be one sentence; found roughly "
                    f"{sentence_count}"))
            for _subject in (description_subject_findings(e["desc"], title)
                             if title else ()):
                problems.append((sl, "item7", _subject["message"]))
            if e["desc"][0].isalpha() and not e["desc"][0].isupper():
                subjects = []
                for subject in (title, base_term(title) if title else None):
                    for form in (
                            subject,
                            math_title_plain_text(subject)
                            if subject else None):
                        if form and form not in subjects:
                            subjects.append(form)
                lowercase_title_subject = any(
                    s[0].islower() and e["desc"].startswith(s) for s in subjects)
                if not lowercase_title_subject:
                    problems.append((sl,"item7",
                                     "description does not start with a capitalized word"))
            if not ends_with_sentence_period(e["desc"]):
                problems.append((sl,"item7","description does not end with a period"))
            # The caveat review covers the description as well as the card;
            # the card's frequency-hedge words apply unchanged (lint_entry's
            # 7-hedge-candidate). A review candidate, never a fault.
            _desc_hedges = flashcard_hedge_hints(e["desc"])
            if _desc_hedges:
                problems.append((
                    sl, "item7/hedge-candidate",
                    "description hedges with "
                    + ", ".join(f'"{word}"' for word in _desc_hedges)
                    + " — state the ordinary case plainly when the note "
                    "establishes it; a candidate is never an order"))
        # ---- item 8: exactly one discipline tag; misc is the sole fallback ----
        e_tags_raw, e_tag_slugs = e["tags_raw"], e["tag_slugs"]
        if e["tags_value_count"] > 1:
            problems.append((sl, "item8", "tags: must contain exactly one discipline home; "
                             "choose from the entry's meaning, not the first listed tag"))
        raw_tags = raw_scalar(fm_raw, "tags")
        if e["tags_valid_empty"]:
            problems.append((sl, "item8", "tags: must contain exactly one discipline tag; "
                             "use only #misc when no specific discipline fits"))
        elif "tags" in e["key_order"] and not e_tags_raw:
            problems.append((sl, "item8", "tags: has no valid discipline values; "
                             "repair the malformed, scalar, null, or duplicate field "
                             "before assigning hierarchy membership"))
        if any(d.lower() == "misc" for d in e_tag_slugs) and not e["tags_valid_misc"]:
            problems.append((sl, "item8", "#misc must be the sole tag in one valid tags: list, "
                             "reserved for entries where no specific discipline fits"))
        if raw_tags not in (None, ""):
            spelling = "flow-list" if raw_tags.startswith("[") else "scalar"
            problems.append((sl,"item8",f'tags: uses {spelling} syntax — write a block-form '
                             'list with one double-quoted tag per `-` line; use only '
                             '"#misc" when no specific discipline fits'))
        for t in e_tags_raw:
            inner = t.strip()
            is_wikilink = inner.startswith("[[") or inner.endswith("]]")
            slugpart = inner.lstrip("#").strip().strip("[]").strip()     # core slug: drop #, [[ ]]
            low = slugpart.lower()
            target = low if low in VALID_TAGS else TAG_ALIASES.get(low)  # the corrected enum slug, if one exists
            faults = []
            if is_wikilink:
                faults.append("written as a wikilink (tags are #-prefixed slugs, not links)")
            elif not inner.startswith("#"):
                faults.append("missing the # prefix (an unquoted # is a YAML comment, silently dropping the discipline)")
            if low not in VALID_TAGS:
                faults.append(f'"{low}" is a known abbreviation/synonym, not an enum slug' if target
                              else f'"{low}" is not one of the {len(VALID_TAGS)} discipline slugs')
            elif slugpart != low:
                # The enum slugs are lowercase. A case variant folds onto the
                # right discipline for the census and for Obsidian's search, so
                # nothing downstream broke and nothing reported it either — the
                # entry simply carried a spelling the enum does not contain.
                faults.append(f'"{slugpart}" is a case variant of the enum slug "{low}" '
                              '(enum slugs are lowercase)')
            if faults:
                fix = f'rewrite as "#{target}"' if target else "fix to a valid #-prefixed enum slug"
                problems.append((sl,"item8",f'tag "{t}": ' + "; ".join(faults) + f" — {fix}"))
        # Duplicates are counted on the CANONICAL slug — alias expanded, case
        # folded — not on the raw one. `#ml` beside `#machine-learning` is one
        # discipline written twice, and the raw check reported no duplicate
        # while item 8's own mandated fix above ("rewrite as
        # #machine-learning") went on to create one. Same for `#Machine-Learning`.
        _canon_by_tag = [(t, tag_canonical(s)) for t, s in zip(e_tags_raw, e_tag_slugs)]
        _dup_counts = [c for _t, c in _canon_by_tag]
        for d in sorted({c for c in _dup_counts if _dup_counts.count(c) > 1}):
            spellings = ", ".join(f'"{t}"' for t, c in _canon_by_tag if c == d)
            problems.append((sl,"item8",f'discipline "#{d}" tagged more than once (as {spellings}) — keep one'))
        # ---- item 9: body structure ----
        # Body line numbers in messages count from the line after the
        # closing fence, so blank lines dropped before the body add back.
        _line_off = e["body_line_offset"]
        if e["blank_after"]:
            problems.append((sl,"item9","blank line immediately after frontmatter"))
        # A leading heading that repeats the title gets its own delete
        # finding below; the body then opens at the line after it.
        if not body_opens_with_prose(
                without_leading_title_heading(e["prose"], title)):
            problems.append((sl,"item9","body does not open with a prose sentence"))
        if e["type"] in ("Person","Event"):
            opener = first_prose_paragraph(e["prose"])
            date_status = opener_subject_date_status(opener, e["type"])
            if date_status == "missing":
                problems.append((sl,"item9",f'{e["type"]} opener needs a date '
                                             f'parenthetical immediately after the bolded subject'))
            elif date_status == "malformed":
                problems.append((sl,"item9",f'{e["type"]} opener date parenthetical '
                                             f'is not one of the exact forms in '
                                             f'wiki-build/references/rare-types.md '
                                             f'(including qualifier punctuation and '
                                             f'en-dash spacing)'))
        # An all-capital acronym title (MNIST, not ROC curve or MLOps) opens
        # with its full form: the shared floor lint_entry also runs. An
        # all-capital name that is no acronym (ELIZA) still matches the shape,
        # so the message names that exit rather than demanding an expansion.
        if acronym_expansion_missing(title, first_prose_paragraph(e["prose"])):
            problems.append((
                sl, "item9/acronym-expansion",
                f'acronym title "{base_term(title)}" has no full-form '
                f'parenthetical directly after its bolded opener title — add '
                f'the expansion there (wiki-build writing.md principle 5(f)) '
                f'from the cited source or accurate background; then apply '
                f"item 17's alias gates and, when the alias is added, item "
                f"19's line-3 counterpart. A title whose letters stand for no "
                f'established full form keeps its opener'))
        for line_no, cue_line in navigation_only_link_lines(e["prose"]):
            problems.append((
                sl, "item9/imperative-link",
                f'navigation-only cross-reference on prose line '
                f'{line_no + _line_off}: '
                f'"{cue_line[:100]}" — integrate it where adjacent prose already '
                f'states the relationship without adding a claim; otherwise '
                f'Task 1b states the relationship from the entry\'s or the '
                f'linked entry\'s cited source, or accurate background, and '
                f'integrates the link'))
        # Listings are presentation samples and must not be parsed as
        # headings, but inline code is itself forbidden heading markup.
        heading_lines = strip_indented(strip_fenced(e["prose"])).split("\n")
        heading_table_rows = {
            line_i
            for header_i, end_i in e.get("table_spans", ())
            for line_i in range(header_i, end_i + 1)
        }
        for line_i, heading_line in enumerate(heading_lines):
            if line_i in heading_table_rows:
                continue
            line_no = line_i + 1 + _line_off
            heading = re.match(r"^ {0,3}(#{1,6})[ \t]+(.+?)\s*$", heading_line)
            if heading and heading_repeats_title(heading.group(2), title):
                problems.append((
                    sl, "item9",
                    "body heading on prose line %d repeats the entry title: "
                    "%s — delete it, never demote it; Obsidian shows the "
                    "filename as the inline title"
                    % (line_no, heading_line.strip()[:80])))
            elif heading:
                faults = []
                if heading.group(1) != "##":
                    faults.append("level must be exactly ##")
                heading_text = heading.group(2).rstrip("#").rstrip()
                heading_markup = []
                if "$" in heading_text: heading_markup.append("LaTeX")
                heading_markup.extend(flashcard_line1_markup(heading_text))
                if heading_markup:
                    faults.append("plain text only (found %s)"
                                  % ", ".join(heading_markup))
                if faults:
                    problems.append((
                        sl, "item9",
                        "body heading on prose line %d is noncanonical: %s — %s"
                        % (line_no, heading_line.strip()[:80], "; ".join(faults))))

            previous_heading_line = (
                heading_lines[line_i - 1] if line_i > 0 else "")
            if (line_i > 0 and previous_heading_line.strip()
                    and not markdown_block_start(previous_heading_line)
                    and re.fullmatch(r" {0,3}(?:=+|-+)[ \t]*", heading_line)):
                problems.append((
                    sl, "item9",
                    "Setext body heading ending on prose line %d is "
                    "noncanonical; use a plain-text `##` heading"
                    % line_no))
        # A display or paragraph that a list item owns but that is indented
        # short of the item's text column ends the list in Obsidian. Shared
        # with lint_entry's 9-list-indent.
        _list_tables = markdown_tables(e["prose"])[1]
        for _indent in list_indent_findings(
                e["prose"], find_display_spans(strip_code(e["prose"]),
                                               _list_tables), _list_tables):
            problems.append((
                sl, "item9/list-indent",
                "prose line %d (list item on prose line %d): %s"
                % (_indent["line"] + _line_off,
                   _indent["item_line"] + _line_off, _indent["message"])))
        # ---- item 12 (format): unescaped literal $ and remote image embeds ----
        _pure_math_opener_markup = None
        nd = leftover_dollars(e["prose"])
        if nd:
            problems.append((sl,"item12",f'{nd} unescaped literal "$" in body — escape as \\$ (a lone $ renders as math; a $ in a URL needs the image localized)'))
        for _line_no, _line in enumerate(
                strip_code(e["prose"]).split("\n"), 1 + _line_off):
            if re.search(r"ℓ(?:[0-9₀-₉])", _line):
                problems.append((
                    sl, "item12/equation-typography",
                    "raw ℓ-norm notation on prose line %d must use inline "
                    "LaTeX, such as `$\\ell_1$` or `$\\ell_2$`"
                    % _line_no))
            if re.search(r"(?<!\w)(?:μ|µ)m\b", _line):
                problems.append((
                    sl, "item12/equation-typography",
                    "raw micrometre notation on prose line %d must use "
                    "inline LaTeX, such as `$\\mu\\mathrm{m}$`"
                    % _line_no))
        _equation_prose = strip_code(e["prose"])
        _equation_tables = markdown_tables(e["prose"])[1]
        _equation_candidates = find_missing_display_equation_candidates(
            _equation_prose, _equation_tables)
        if _equation_candidates:
            _lines = ", ".join(str(line + _line_off) for line in sorted(
                {candidate["line"] for candidate in _equation_candidates}))
            _details = "; ".join(
                f'{candidate["kind"]} "{candidate["phrase"]}" '
                f'(line {candidate["line"] + _line_off})'
                for candidate in _equation_candidates)
            problems.append((
                sl, "item12/equation-coverage-candidate",
                "prose or inline math appears to define a calculation "
                "without a nearby display equation "
                f"({_details}; prose line(s) {_lines}) — executing "
                "agent: first judge explanatory value under "
                "wiki-build/references/equations.md. Keep simple verbal "
                "rules in prose when notation adds no understanding; "
                "otherwise verify the relationship and define its symbols."
                + (" A square-root-of-variance cue never authorizes "
                   "inferring a population or sample denominator"
                   if any(candidate["kind"] == "square-root-of-variance"
                          for candidate in _equation_candidates) else "")))
        _equation_form_candidates = \
            find_noncanonical_display_equation_candidates(
                _equation_prose, _equation_tables)
        if _equation_form_candidates:
            _lines = ", ".join(str(line + _line_off) for line in sorted(
                {candidate["line"] for candidate in _equation_form_candidates}))
            _form_kinds = {candidate["kind"]
                           for candidate in _equation_form_candidates}
            _repairs = []
            if _form_kinds - {"bare-alignment"}:
                _repairs.append(
                    "display math is not in canonical block form (a `$$` "
                    "shares a line with the equation or with prose, or a "
                    "blank line is missing above or below); put each `$$` "
                    "alone on its line with a blank line above and below")
            if "bare-alignment" in _form_kinds:
                _repairs.append(
                    "display math uses `&` or `\\\\` outside an aligned or "
                    "gathered environment, which fails to render; wrap its "
                    "rows in `\\begin{aligned}...\\end{aligned}`, or "
                    "`gathered` when nothing aligns")
            problems.append((
                sl, "item12/equation-format",
                "; ".join(_repairs) + f" (prose line(s) {_lines}) — keep the "
                "existing equation and do not add a second display"))
        _equation_split_candidates = \
            find_multi_relation_display_candidates(
                _equation_prose, _equation_tables)
        if _equation_split_candidates:
            _lines = ", ".join(str(line + _line_off) for line in sorted(
                {candidate["line"]
                 for candidate in _equation_split_candidates}))
            problems.append((
                sl, "item12/equation-split-candidate",
                "a display line holds more than one equation "
                f"(prose line(s) {_lines}) — executing agent: give each "
                "equation its own line (a separate display beside the prose "
                "that introduces it, or a row of an aligned or gathered "
                "display), keeping the math unchanged"))
        # Well-definedness boilerplate is removed by ordinary lint (QC item
        # 12), but only the agent pass found it: a corpus run removed about 60
        # guards such as "for a nonempty dataset", `$m \ge 1$` and
        # `$\alpha \ge 0$` from entries this scan reported clean.
        _boilerplate = find_boilerplate_candidates(
            _equation_prose, _equation_tables)
        if _boilerplate:
            problems.append((
                sl, "item12/boilerplate-candidate",
                "possible well-definedness boilerplate in body prose — "
                + "; ".join(f'line {candidate["line"] + _line_off}: '
                            f'{candidate["kind"]} '
                            f'"{candidate["phrase"][:60]}"'
                            for candidate in _boilerplate)
                + " — executing agent: remove a condition the formula "
                "already presupposes, keep a range the definition needs "
                "(wiki-build/references/equations.md §1)"))
        # Remote ![](http…) embeds are REPORT-ONLY, not a violation. wiki-build MANDATES this exact
        # form for an external URL coming from a markdown source's clipping ("use standard markdown
        # image syntax ![alt](https://...) since wikilinks don't handle remote URLs" —
        # wiki-build references/media.md), because an Obsidian wikilink cannot address a remote URL.
        # Filing it as an ordinary itemN problem made the linter "fix in place" a working image into
        # ![[Sources/Images/…]] — a path form wiki-build does not use either (it embeds a BARE basename,
        # ![[Name_fig_3.png]]) — which resolves to nothing and throws the URL away. Its own item key
        # routes it to the run report instead. DO NOT re-file this as item12.
        for _start, _end, url in markdown_image_spans(strip_code(e["body"])):
            if not re.match(r"https?://", url, re.IGNORECASE):
                continue
            problems.append((sl,"item12/remote-image",f'remote image embed ![]({url[:50]}…) — VALID, DO NOT REWRITE (wiki-build mandates markdown syntax for remote URLs); report only, as a candidate for localizing by re-running clipping-clean on the source clipping'))
        # Image embeds need an italic *caption* on the very next line. Read
        # embed positions from listing-masked text so syntax samples in
        # fenced/indented code do not prescribe a caption edit; read the
        # caption from the original text so forbidden markup remains visible.
        blines, image_lines = image_embed_lines(e["body"])
        for i in image_lines:
            ln = blines[i]
            cap = blines[i+1].strip() if i+1 < len(blines) else ""
            cap_faults = caption_faults(cap)
            if cap_faults == ["missing italic caption"]:
                problems.append((sl,"item12",f'image embed without an italic *caption* on the next line: {ln.strip()[:48]}'))
            elif cap_faults:
                problems.append((sl,"item12",f'caption has {", ".join(cap_faults)} — captions are plain text (only LaTeX $…$ allowed): {cap[:48]}'))
        _exhibits = {}
        for _destination in local_image_destinations(e["body"]):
            _parts = figure_exhibit_parts(_destination)
            if _parts is None:
                continue
            _identity, _panel = _parts
            _exhibits.setdefault(_identity, {"composites": [], "panels": []})[
                "panels" if _panel else "composites"].append(
                    _destination.replace("\\", "/").rsplit("/", 1)[-1])
        for _group in _exhibits.values():
            if not _group["composites"] or not _group["panels"]:
                continue
            problems.append((
                sl, "item12/panel-composite",
                "entry embeds both a composite figure (%s) and one of its "
                "panels (%s) — they are one exhibit; preserve both until a "
                "source-backed review chooses the composite or the "
                "subject-specific panel"
                % (", ".join(sorted(set(_group["composites"]))),
                   ", ".join(sorted(set(_group["panels"]))))))
        table_lines = e["body"].split("\n")
        for header_i, end_i in e["table_spans"]:
            cap = table_lines[end_i + 1].strip() if end_i + 1 < len(table_lines) else ""
            cap_faults = caption_faults(cap)
            table_head = table_lines[header_i].strip()[:48]
            if cap_faults == ["missing italic caption"]:
                problems.append((sl,"item12",f'Markdown table without an italic *caption* '
                                 f'on the immediately following line: {table_head}'))
            elif cap_faults:
                problems.append((sl,"item12",f'table caption has {", ".join(cap_faults)} — '
                                 f'captions are plain text (only LaTeX $…$ allowed): {cap[:48]}'))
        # ---- item 12 (embeds): every ![[…]] image names a file that is there ----
        # Only with --images: without the folder there is nothing to compare
        # against, and guessing would report every embed in the vault as broken.
        # Read listing-stripped: an embed shown in fenced, indented, or inline
        # code is a syntax sample, not an embed Obsidian resolves.
        if img_fold is not None:
            for _m in IMG_EMBED.finditer(strip_code(e["body"])):
                # Obsidian resolves an embed by BASENAME vault-wide, so a
                # path-qualified `![[Sources/Images/X.png]]` names the same file
                # as a bare `![[X.png]]` and must not read as missing.
                _img = _m.group(1).strip().replace("\\", "/").rsplit("/", 1)[-1]
                if fold_name(_img) in img_fold:
                    continue
                # The same basename rule finds a file elsewhere in a known
                # vault, such as a pasted image in Attachments/. It renders,
                # so it is not missing; it only sits outside the image folder.
                if vault_root_known and vault_images is None:
                    vault_images = vault_image_index(vault_root, images)
                _elsewhere = (vault_images or {}).get(fold_name(_img))
                if _elsewhere:
                    problems.append((sl, "item12/image-outside-folder",
                                     f'embed resolves to {", ".join(_elsewhere)} '
                                     f'outside the image folder (Obsidian renders '
                                     f'it); CONVENTIONS §1 keeps every image in the '
                                     f'flat Sources/Images/ folder — REPORT ONLY, do '
                                     f'not move, rename or delete the file or the '
                                     f'embed'))
                    continue
                problems.append((sl,"item12/missing-image",
                                 f'embed names a file that is not in the image folder: {_img} '
                                 f'(Obsidian renders this as plain text, silently) — REPORT '
                                 f'ONLY, DO NOT DELETE THE EMBED OR ITS CAPTION. Neither cause '
                                 f'is the linter\'s to repair: the figure was never '
                                 f'extracted (run figure-extract on the source), or the '
                                 f'image file was renamed or moved without its references. '
                                 f'pdf-organize\'s source rename rewrites embeds in the same '
                                 f'run (CONVENTIONS §1a), so this is not a pending step of '
                                 f'it; do not hand-patch the embed. Deleting the embed throws '
                                 f'away the one record of which figure belongs here'))
        # ---- item 16: opener title text plus type-specific emphasis ----------
        # The opener is the first prose paragraph: a masked leading comment
        # is blank, and a leading heading or display block is skipped.
        opener = first_prose_paragraph(e["prose"])
        mo = _BOLD_OUTER_RE.search(
            " ".join(line.strip() for line in opener.splitlines()))
        # The PRESENCE half: an opener with no bold span at all used to be
        # silent (the coherence check below is gated on a bold to compare),
        # so the one entry that skipped the bold entirely was the one
        # entry item 16 never flagged.
        if not mo and opener.strip():
            problems.append((sl,"item16","body opener has no bold span — "
                                         "the opener bolds the entry title "
                                         "on first appearance"))
        if mo and title:
            b, bold_style, italic_prefix = _bold_parts(mo)
            b = b.strip()
            t_norm = base_term(title)   # drop a trailing disambiguation parenthetical
            taxon_status, taxon = (
                organism_title_classification(
                    t_norm, e["aliases"], first_sentence(opener))
                if e["type"] == "Organism" else ("common", None))
            compared_b = (b.replace("*", "").replace("_", "")
                          if taxon_status == "ambiguous" else b)
            bb = math_title_plain_text(compared_b)
            tt = math_title_plain_text(t_norm)
            if bb and tt and (bb[:1].lower()+bb[1:] != tt[:1].lower()+tt[1:]):
                problems.append((
                    sl, "item16",
                    f'body opener "**{b}**" ≠ title "{title}" '
                    "(after applying the shared mathematical-title "
                    "plain form and dropping a disambiguation "
                    "parenthetical)"))
            else:
                # A title made entirely from one inline-math span has no
                # surrounding prose text to carry the required first-title
                # bold. Its exact opener span is the one narrow exception to
                # the general ban on wrapping LaTeX itself in emphasis.
                _pure_math_opener_markup = pure_math_opener_markup(
                    t_norm, opener)
                if taxon_status == "ambiguous":
                    # The semantic item-16 pass still checks the source, but
                    # there is no stored resolution bit with which a scanner
                    # warning could ever close.  Once the visible title is
                    # correct, accept either style at the mechanical floor.
                    pass
                else:
                    expected_style = "full-italic" if e["type"] == "Work" else "plain"
                    if taxon_status == "scientific":
                        expected_style = "mixed" if taxon[1] else "full-italic"
                    style_ok = bold_style == expected_style
                    if expected_style == "mixed":
                        style_ok = (style_ok and italic_prefix == taxon[0]
                                    and b == taxon[0] + taxon[1])
                    if not style_ok:
                        if expected_style == "plain":
                            expected_markup = "**%s**" % t_norm
                        elif expected_style == "full-italic":
                            expected_markup = "***%s***" % t_norm
                        else:
                            expected_markup = "***%s*%s**" % taxon
                        problems.append((
                            sl, "item16",
                            f'body opener title has the wrong emphasis for {e["type"]}; '
                            f'use "{expected_markup}"'))
        # ---- item 16b: unenumerated bold — only title-first-mention, `- **Term** —` anchor, **Related:** ----
        # Shared with lint_entry. Markup inside a wikilink display label is
        # item 18's violation, and bold around a single link/math/code span is
        # the emphasis check's below.
        for _bold_finding in unenumerated_bold_findings(
                e["prose"], e.get("table_spans", ())):
            problems.append((sl, "item16", _bold_finding["message"]))
        # ---- item 16: emphasis (bold/italic) around a wikilink/math/code span — the markup itself is the styling ----
        for _emphasis_finding in emphasis_span_findings(
                e["prose"], e["rel"], e.get("table_spans", ()),
                opener_markup=_pure_math_opener_markup):
            problems.append((sl, "item16", _emphasis_finding["message"]))
        # ---- item 16: two literal prose shapes that require backticks ----
        # The shared helper is intentionally conservative for extensions and
        # excludes headings, captions, tables, math, link/embed syntax, and
        # URLs. `strip_code` makes an already-canonical `[CLS]` or `.csv`
        # invisible here.
        _code_typography_prose = strip_code(e["prose"])
        for occurrence in find_bare_code_shapes(
                _code_typography_prose, e.get("table_spans", ())):
            problems.append((
                sl, "item16",
                'bare %(kind)s %(token)r on prose line %(line)d — wrap the '
                'literal shape in backticks'
                % dict(occurrence, line=occurrence["line"] + _line_off)))
        # ---- item 13: stray frontmatter key, `---` or digit line mid-body (stacked-merge scars) ----
        # Shared with lint_entry; listings are masked (shown, not asserted).
        # If Related is missing, regions() reaches the legitimate separator
        # before Flashcards: item 11's finding, not an item-13 scar.
        _structural_separator_i = None
        if e.get("flashcard_indexes"):
            _flash_i = e["flashcard_indexes"][0]
            _structural_separator_i = next(
                (i for i in range(_flash_i - 1, -1, -1)
                 if e["body_lines"][i].strip()), None)
            if (_structural_separator_i is not None
                    and e["body_lines"][_structural_separator_i].strip() != "---"):
                _structural_separator_i = None
        for _scar in merge_scar_findings(e["prose"], _structural_separator_i):
            problems.append((sl, "item13", _scar["message"]))
        # ---- item 19: Flashcards presence/absence + card-set shape + per-card structure / markup / answer-leak ----
        # A discipline root needs no card (hierarchy.md, *Establish discipline
        # roots*): it skips the missing-section, no-card and no-primary
        # findings. A card it keeps gets every per-card check.
        _root_entry = _record_is_discipline_root(sl, e)
        if not e["has_flashcards"] and not _root_entry:
            problems.append((sl,"item19","entry missing ## Flashcards section"))
        # The Spaced Repetition plugin parses the whole note, so a single-line
        # separator before the Flashcards section adds a card (lint_entry
        # shares this floor). It reads the raw text under its own comment
        # rule, so the floor gets the unmasked body.
        for _sr_hit in sr_marker_findings(
                e["body"][:e["flash_off"]] if e["has_flashcards"]
                else e["body"], multiline=e["has_flashcards"]):
            problems.append((sl, "item19/sr-marker", _sr_hit["message"]))
        if e["has_flashcards"]:
            # A tolerated heading spelling (### level, extra/leading spaces) is a
            # PRESENT section with a heading to fix — never a missing section,
            # whose remedy would add a second one beside the section Obsidian
            # already renders.
            if not FLASH_HEAD_CANON_RE.match(e["flash_head"]):
                problems.append((sl,"item19",f'Flashcards heading spelled "{e["flash_head"].strip()[:30]}" — '
                                             f'the canonical heading is exactly "## Flashcards"; fix the '
                                             f'heading in place, do NOT add a second section'))
            # the ## Flashcards heading must sit under a '---' separator line on its own
            _visible = mask_body_comments(e["body"])
            pre = _visible[:e["flash_off"]].rstrip()
            pre_nb = [l for l in pre.split("\n") if l.strip()]
            if not pre_nb or pre_nb[-1].strip() != "---":
                problems.append((sl,"item19","## Flashcards not preceded by a '---' separator line on its own (Body Structure → Flashcards)"))
            else:
                _flash_i = e["flashcard_indexes"][0]
                _lines = e["body_lines"]
                _visible_lines = _visible.split("\n")
                _separator_i = next(
                    (i for i in range(_flash_i - 1, -1, -1)
                     if _visible_lines[i].strip()), None)
                if (_separator_i is not None
                        and (_separator_i + 1 >= len(_lines)
                             or _lines[_separator_i + 1].strip())):
                    problems.append((
                        sl, "item19",
                        "the `---` separator must be followed by a blank line "
                        "before `## Flashcards`"))
                if (_flash_i + 1 >= len(_lines)
                        or _lines[_flash_i + 1].strip()):
                    problems.append((
                        sl, "item19",
                        "`## Flashcards` must be followed by a blank line "
                        "before card line 1"))
            # split the section (after the heading) into card blocks on blank-line boundaries
            after_head = e["fcsec"].split("\n",1)[1] if "\n" in e["fcsec"] else ""
            # Inline, next-line, and callout scheduling state plus block IDs
            # belong to the review plugin/user. None is another card to
            # remove. Mask it only in this read-only check.
            cards = parse_flashcard_blocks(after_head)
            # A block of only schedule state, which a blank line separates
            # from its card, is neither a card nor an attachment (lint_entry
            # reports the same); block numbers stay as parsed.
            _schedules = {ci for ci, cl in enumerate(cards, 1)
                          if is_review_metadata_block(cl)}
            if len(cards) == len(_schedules) and not _root_entry:
                problems.append((sl,"item19","## Flashcards section has no card"))
            for _message in flashcard_set_faults(
                    sum(1 for ci, cl in enumerate(cards, 1)
                        if len(cl) >= 3 and ci not in _schedules)):
                problems.append((sl, "item19", "## Flashcards holds " + _message))
            alias_forms = list(e["aliases"])
            _expected_term, _expected_counterpart = flashcard_primary_answer(
                title, e["aliases"], opener, e["type"])
            _line3_faults = []
            _definition_cues = []
            # With 2+ complete cards, the kept card is the primary card the
            # answer contract identifies, else the first card, which the run
            # rewrites into the definition card. Every other complete card is
            # an extra card to remove, and its per-card problems say that its
            # removal is the only repair (lint_entry marks the same).
            _complete_rows = [
                (f"card {ci}" if len(cards) > 1 else "flashcard", cl[2],
                 flashcard_line3_fault(cl[2], title, e["aliases"], opener,
                                       e["type"]))
                for ci, cl in enumerate(cards, 1)
                if len(cl) >= 3 and ci not in _schedules]
            _primary_tag = (kept_card_label(
                _complete_rows, _expected_term, _expected_counterpart)
                if len(_complete_rows) > 1 and title else None)
            for ci, cl in enumerate(cards, 1):
                tag = (f"card {ci}" if len(cards) > 1 else "flashcard")
                if ci in _schedules:
                    problems.append((
                        sl, "item19",
                        f"block {ci} is a Spaced Repetition schedule that a "
                        "blank line separates from the card — it is neither "
                        "a card nor an attachment; preserve it byte-for-byte, "
                        "never delete, move or reattach it, and report it"))
                    continue
                if len(cl) < 3:
                    problems.append((sl,"item19",f'{tag} malformed — needs 3 contiguous lines (cue / separator / answer), found {len(cl)} (a blank line between lines 1–3 breaks the card)'))
                    continue
                _extra = _primary_tag is not None and tag != _primary_tag
                _lead = EXTRA_CARD_PREFIX % ci if _extra else ""
                if len(cl) > 3:
                    # Removing an extra card never takes the content after its
                    # line 3 that is not a recognized attachment.
                    problems.append((
                        sl, "item19",
                        f'{_lead}{tag} has {len(cl)} visible lines — removing '
                        'it removes lines 1–3 and their recognized attachments '
                        'only; the content after line 3 stays and is reported'
                        if _extra else
                        f'{_lead}{tag} has {len(cl)} visible lines — only the '
                        'first three may be card content; recognized Spaced '
                        'Repetition state may be attached to line 3, follow it '
                        'as `<!--SR:` metadata, or use the exact '
                        '`sr|card-metadata` callout, so other content '
                        'after the term is malformed'))
                line1, line2, line3 = cl[0], cl[1].strip(), cl[2]
                _card_boilerplate = find_boilerplate_candidates(
                    strip_code(line1), card_line=True)
                if _card_boilerplate:
                    problems.append((
                        sl, "item12/boilerplate-candidate",
                        f"{_lead}possible well-definedness boilerplate in "
                        f"{tag} line 1 — "
                        + "; ".join(f'{candidate["kind"]} '
                                    f'"{candidate["phrase"][:60]}"'
                                    for candidate in _card_boilerplate)
                        + ("" if _extra else
                           " — shorten the math to its compact equivalent "
                           "only when the tested claim is unchanged; keep the "
                           "cue, answer line and every attachment "
                           "(flashcards.md)")))
                if re.search(r"ℓ(?:[0-9₀-₉])", line1):
                    problems.append((
                        sl, "item12/equation-typography",
                        f"{_lead}raw ℓ-norm notation in {tag} line 1 must use "
                        "inline LaTeX, such as `$\\ell_1$` or `$\\ell_2$`"))
                if re.search(r"(?<!\w)(?:μ|µ)m\b", line1):
                    problems.append((
                        sl, "item12/equation-typography",
                        f"{_lead}raw micrometre notation in {tag} line 1 must "
                        "use inline LaTeX, such as `$\\mu\\mathrm{m}$`"))
                if line2 not in CARD_SEPARATORS:
                    problems.append((
                        sl, "item19",
                        f'{_lead}{tag} line 2 is "{line2[:20]}"' if _extra else
                        f'{tag} line 2 is "{line2[:20]}", must be exactly ?? '
                        "(or !! if the user disabled the card)"))
                _sentence_faults = flashcard_line1_faults(line1)
                if _sentence_faults:
                    problems.append((
                        sl, "item19",
                        f'{_lead}{tag} line 1 {" and ".join(_sentence_faults)} '
                        "— the definition must be one capitalized, "
                        "period-terminated sentence and takes inline LaTeX "
                        "only (no Markdown or HTML)"))
                # The plugin reads a separator on line 1 or 3 as a card of
                # its own (lint_entry reports the same).
                for _line_no, _marker, _fault in sr_card_marker_faults(cl):
                    problems.append((
                        sl, "item19", f"{_lead}{tag} line {_line_no} {_fault}"))
                # leak check: line 1 must not contain THIS card's answer — its own line-3 term (+ parenthetical
                # expansion); add the entry's aliases only when this card's term is the entry title (the primary
                # card). An extra card may name the primary entity, so don't test it against the title.
                mt = re.match(r"^(.*?)(?:\s+\(([^)]*)\))?\s*$", line3.strip())
                term_main = (mt.group(1) if mt else line3).strip()
                paren = mt.group(2).strip() if (mt and mt.group(2)) else ""
                # the parenthetical is a leak candidate only when it is a real acronym/expansion of the term; a
                # discipline-disambiguation parenthetical ("Model (machine learning)") is just a domain tag, not part
                # of the recall answer, so its appearance in line 1 ("a machine learning system") is context, not a leak.
                cands = [term_main] + ([paren] if (paren and slug(paren) not in VALID_TAGS) else [])
                # The primary-card test compares against the title with a trailing
                # discipline-disambiguation parenthetical stripped: the primary
                # card's line 3 is the BASE term for a disambiguated title
                # ("Feature", not "Feature (machine learning)"), so an exact
                # compare skipped the alias needles for exactly the entries that
                # carry them — every disambiguated entry sat in the blind spot.
                if _expected_term and term_main == _expected_term:
                    cands += alias_forms
                # Unicode punctuation, slash/dash variants, and whitespace are
                # normalized by the shared leak matcher. lint_entry uses the
                # same matcher, so the two tools agree.
                _seen_surfaces = set()
                _deduped_cands = []
                for _candidate in cands:
                    _surface = normalized_answer_surface(_candidate)
                    if not _surface or _surface in _seen_surfaces:
                        continue
                    _seen_surfaces.add(_surface)
                    _deduped_cands.append(_candidate)
                cands = _deduped_cands
                hit = None
                for c in cands:
                    if answer_surface_match(line1, c):
                        hit = c
                        break
                if hit:
                    problems.append((sl,"item19",f'{_lead}{tag} line 1 leaks the answer ("{hit}")'))
                l3 = []                              # line 3 (term) is plain text — no markup at all, including LaTeX
                if "[[" in line3: l3.append("wikilink")
                if "`" in line3: l3.append("backtick")
                if "$" in line3: l3.append("$ (LaTeX)")
                if "**" in line3: l3.append("bold")
                elif re.search(r"\*\w[^*]*\*", line3): l3.append("italic")
                if l3:
                    problems.append((
                        sl, "item19",
                        f'{_lead}{tag} line 3 (term) has {", ".join(l3)} — '
                        "line 3 must be plain text (no markup, including "
                        "LaTeX)" + ("" if _extra else "; remove only the markup")))
                _line3_fault = flashcard_line3_fault(
                    line3, title, e["aliases"], opener, e["type"])
                _line3_faults.append((tag, line3, _line3_fault))
                _definition_cues.append((tag, line1.strip()))
                _hints = flashcard_brevity_hints(line1)
                if _hints:
                    problems.append((
                        sl, "item19/brevity-candidate",
                        f'{_lead}{tag}: {"; ".join(_hints)} — review under '
                        "flashcard maintenance; a candidate is never an order"))
                _hedges = flashcard_hedge_hints(line1)
                if _hedges:
                    problems.append((
                        sl, "item19/hedge-candidate",
                        f'{_lead}{tag} line 1 hedges with '
                        + ", ".join(f'"{word}"' for word in _hedges)
                        + " — state the ordinary case plainly when the note "
                        "establishes it; a candidate is never an order"))
            # The line-3 term contract binds the primary card only: an extra
            # card is removed, never repointed to the entry's answer.
            # lint_entry makes the same choice.
            _report_line3, _no_primary = primary_line3_faults(
                len(_line3_faults), _line3_faults, _expected_term,
                _expected_counterpart)
            # `card_rivals` input: the primary card's cue, else the first
            # complete card's.
            if _unique_owner and _definition_cues:
                _primary_cues[sl] = dict(_definition_cues).get(
                    _primary_tag, _definition_cues[0][1])
            if _no_primary and not _root_entry:
                problems.append((sl, "item19", _no_primary))
            for tag, line3, line3_fault in _report_line3:
                problems.append((sl, "item19",
                                 f'{tag} line 3 is "{line3[:40]}" — '
                                 f'{line3_fault}'))
        # ---- item 11: exactly one terminal Related footer on entries ----
        # ``regions`` intentionally stops prose at the first rendered marker.
        # Without this topology check, a second footer or ordinary prose after
        # that marker disappears from every body/link scan and can conceal a
        # self-link or any other violation indefinitely.
        _visible_body_lines = mask_body_comments(e["body"]).split("\n")
        _related_indexes = e.get("related_indexes", [])
        _flash_indexes = e.get("flashcard_indexes", [])
        if not _related_indexes:
            problems.append((
                sl, "item11",
                "entry has no `**Related:**` footer — add one terminal "
                "footer line before the Flashcards separator"))
        elif len(_related_indexes) > 1:
            problems.append((
                sl, "item11",
                f"entry has {len(_related_indexes)} rendered `**Related:**` "
                "footer lines — consolidate them into exactly one terminal line"))
        else:
            _related_i = _related_indexes[0]
            _related_line = _visible_body_lines[_related_i].rstrip()
            _related_form_bad = not _related_line.startswith("**Related:**")
            if not _related_form_bad:
                _related_tail = _related_line[len("**Related:**"):]
                if _related_tail:
                    if not _related_tail.startswith(" "):
                        _related_form_bad = True
                    else:
                        _related_parts = _related_tail[1:].split(" · ")
                        _related_form_bad = (
                            not _related_parts
                            or any(WIKILINK.fullmatch(part) is None
                                   for part in _related_parts))
            if _related_form_bad:
                problems.append((
                    sl, "item11",
                    "Related footer must be exactly `**Related:**` followed "
                    "by whole-line wikilinks separated with ` · `"))

            if _flash_indexes:
                _flash_i = _flash_indexes[0]
                if _related_i >= _flash_i:
                    problems.append((
                        sl, "item11",
                        "Related footer must precede the Flashcards separator "
                        "and heading"))
                else:
                    _separator_i = None
                    for _i in range(_flash_i - 1, _related_i, -1):
                        if _visible_body_lines[_i].strip():
                            if _visible_body_lines[_i].strip() == "---":
                                _separator_i = _i
                            break
                    _tail_end = (_separator_i if _separator_i is not None
                                 else _flash_i)
                    _stray = [
                        _i for _i in range(_related_i + 1, _tail_end)
                        if _visible_body_lines[_i].strip()]
                    if _stray:
                        problems.append((
                            sl, "item11",
                            "body content appears after the Related footer "
                            "before Flashcards — move it back into prose or "
                            "remove it; the footer must be terminal"))
                    if (_separator_i is not None
                            and _separator_i == _related_i + 1):
                        problems.append((
                            sl, "item11",
                            "leave a blank line after the Related footer; "
                            "an immediate `---` renders it as a Setext heading"))
            elif any(line.strip()
                     for line in _visible_body_lines[_related_i + 1:]):
                problems.append((
                    sl, "item11",
                    "body content appears after the Related footer — the "
                    "footer must be the terminal prose line"))

        if len(_flash_indexes) > 1:
            problems.append((
                sl, "item19",
                f"entry has {len(_flash_indexes)} rendered Flashcards "
                "headings — consolidate them into exactly one section"))


        # ---- item 14: source-meta phrasings (prose only) ----
        # Shared with lint_entry. Named `the author(s) of …` passes only when
        # it names an existing entry, which this scan can resolve.
        for _meta_finding in source_meta_findings(
                e["prose"], e.get("type"),
                names_work=lambda named: _authors_phrase_names_entry(
                    named, _entry_vault_target(e))):
            problems.append((sl, "item14", _meta_finding["message"]))
        # ---- item 17: names introduced for this subject but absent in aliases ----
        # The shared detector is exactly the one wiki-build runs on a new or
        # merged entry. It supplies a deterministic candidate; same-entity,
        # cross-domain, and Organism common-name safety remain executing-agent judgments.
        for _candidate, _where, _candidate_slug in (missing_introduced_aliases(
            strip_code(e["prose"]).split("\n"), title, e["aliases"], sl)
                if alias_inventory_complete else ()):
            problems.append((
                sl, "item17/alias-candidate",
                f'the body introduces "{_candidate}" ({_where}) as a name for '
                f'the subject, but aliases: does not contain '
                f'"{_candidate_slug}" — review same-entity and cross-domain '
                f'safety before adding it'
                + ("; " + BARE_WORD_ALIAS_HINT
                   if bare_word_alias_candidate(
                       _candidate_slug, title, _candidate)
                   else "")))
        # ---- item 10: dangling targets; first-occurrence dup within PROSE ----
        # A target that misses every entry exactly but has one portable
        # case/normalization owner is not a genuine missing target. It gets its
        # own key because the repairs are opposites: a genuine dangler is
        # dropped to display text, while this variant is canonicalized in place.
        # Read the entry with its LISTINGS removed -- fenced blocks and inline
        # code spans -- for the reason item 13's own comment gives about the
        # sibling scar check: a fenced block is shown, not asserted. A
        # `[[target-note]]` inside one renders as literal text and links
        # nothing, so calling it dangling prescribes CREATING a file for
        # something the entry only ever displayed as an example of link
        # syntax. The dup scan reads the same masked text: a target shown in a
        # listing and linked once in prose is linked ONCE, and "keep first
        # only" applied to that pair edits the listing or drops the real link.
        # Table cells are a separate deterministic violation: the writing
        # contract forbids wikilinks there.  Report each rendered link, then
        # mask the parsed table spans so it cannot also look dangling, duplicate,
        # or otherwise become input to a second item-10 repair.
        _table_link_lines = strip_code(e["body"]).split("\n")
        for _table_start, _table_end in e.get("table_spans", ()):
            for _line_i in range(_table_start,
                                 min(len(_table_link_lines), _table_end + 1)):
                for _table_link in WIKILINK.finditer(_table_link_lines[_line_i]):
                    _shown = _table_link.group(0)
                    problems.append((
                        sl, "item10/table",
                        f'wikilink {_shown} appears in a Markdown table cell on '
                        f'body line {_line_i + 1 + _line_off} — replace the '
                        f'link markup with '
                        f'its rendered plain text; table cells do not take wikilinks'))
        _p10 = mask_line_spans(
            strip_code(e["prose"]), e.get("table_spans", ()))
        _r10 = strip_code(e["rel"])
        _p10_and_related = _p10 + "\n" + _r10
        for m in WIKILINK.finditer(_p10_and_related):
            tgt = m.group(1).split("#")[0].split("^")[0].strip()
            if not tgt:
                continue
            _link_region = ("Related footer" if m.start() > len(_p10)
                            else "body prose")
            # Forms Obsidian resolves that a bare `tgt in entries` test calls
            # dangling. A path-qualified link (`sub/delta`) and an explicit
            # `.md` suffix resolve like the bare entry link; when they name an
            # entry, item10/case respells them to the §6 form. With no Wiki
            # file they fall through to the vault-note, alias and dangling
            # branches. A link to a document rather than an entry
            # (`Doe_Foo_2025.pdf`, the form CONVENTIONS 6/7 blesses in a
            # `sources:` list) is skipped.
            bare = tgt.replace("\\", "/").rsplit("/", 1)[-1]
            lookup_key = entry_link_key(tgt)
            file_record, file_status, _file_path = _resolve_entry_file(tgt, _entry_vault_target(e))
            if file_status == "moc":
                _moc_owner, _moc_reason = _resolve_parent_target(tgt, _entry_vault_target(e))
                if _moc_reason is not None:
                    problems.append((sl, "item10/moc",
                                     f'MOC navigation target "{tgt}" is {_moc_reason}; '
                                     "preserve its MOCs/ destination and resolve it through "
                                     "Task 3, never redirect it to a same-named Wiki entry"))
                else:
                    _canonical_moc = "MOCs/" + moc_stem(_moc_owner[len("@moc:"):])
                    if tgt != _canonical_moc:
                        problems.append((sl, "item10/case",
                                         f'MOC navigation target "{tgt}" resolves to '
                                         f'"{_canonical_moc}"; normalize the target while '
                                         "preserving its anchor and display label"))
                continue
            if file_status == "ambiguous":
                problems.append((sl, "item10/ambiguous",
                                 f'wikilink target "{tgt}" does not identify one file among '
                                 f'multiple same-basename paths; preserve the link, its path, '
                                 f'anchor and display text until the destination is resolved. '
                                 f'Report only; never choose a file by walk order'))
                continue
            actual = file_record["slug"] if file_record is not None else None
            if (file_record is not None
                    and file_record.get("path_key") == e.get("path_key")):
                problems.append((
                    sl, "item10/self",
                    f'wikilink target "{m.group(1)}" in {_link_region} resolves '
                    "to this entry itself — remove the redundant footer link or "
                    "render a subject mention as plain text; if an anchored body "
                    "link is deliberate navigation, use a local anchor"))
                continue
            # A path, case variant or exact link to an entry counts as linked
            # for `unlinked_children`, even when a repair below respells it.
            if (file_record is not None and _unique_owner
                    and _unique_slug(file_record["slug"])):
                _linked_owners[sl].add(file_record["slug"])
            canonical_target = (
                _canonical_qualified_target(tgt, _file_path, _entry_vault_target(e))
                if file_record is not None and _file_path is not None else None
            )
            normalized_target = tgt.replace("\\", "/").strip().strip("/")
            final_target = (_final_link_target(tgt, file_record, canonical_target)
                            if file_record is not None else None)
            if final_target is not None and normalized_target == final_target:
                continue
            if (final_target is not None
                    and fold_name(normalized_target) != fold_name(final_target)):
                # An explicit `.md` or a path no other owner needs: CONVENTIONS
                # §6 spells the link bare and extensionless.
                _extra = []
                if normalized_target.lower().endswith(".md"):
                    _extra.append("an explicit `.md` suffix")
                if "/" in normalized_target and "/" not in final_target:
                    _extra.append("a path that no other vault file with "
                                  "this basename needs")
                problems.append((
                    sl, "item10/case",
                    f'wikilink target "{tgt}" names the entry "{actual}" with '
                    f'{" and ".join(_extra) or "a noncanonical path"} — this is a '
                    f'FIX IN PLACE (rewrite the target to "{final_target}", '
                    "preserving its anchor and display label)"))
                continue
            if canonical_target is not None:
                problems.append((
                    sl, "item10/case",
                    f'wikilink target "{tgt}" matches the on-disk path '
                    f'"{final_target}" only under the portable '
                    "case/normalization identity — this is a FIX IN PLACE "
                    f'(rewrite the target to "{final_target}", preserving '
                    "its anchor and display label), without creating a replacement note"))
                continue
            if actual:
                problems.append((sl,"item10/case",
                                 f'wikilink target "{tgt}" matches the entry "{actual}" only under '
                                 f'the portable case/normalization identity — this is a FIX IN PLACE '
                                 f'(correct the basename spelling to "{actual}", preserving any path, '
                                 f'anchor and display label), never create a variant file that may overwrite '
                                 f'"{actual}.md" on an insensitive filesystem or create a competing owner '
                                 f'on a sensitive one'))
            elif file_status == "unparsed":
                # The file EXISTS but did not parse (item0/item1). Reporting it
                # as a dangler is wrong twice over: the link resolves in
                # Obsidian, and writing a replacement would overwrite that real
                # file.
                problems.append((sl,"item10/unparsed",
                                 f'wikilink target "{tgt}" names a file that is '
                                 f'on disk but could not be parsed as an entry. '
                                 f'The link resolves; fix that file. NEVER overwrite '
                                 f'this target with a replacement note'))
            elif _outside_owners(tgt, _entry_vault_target(e)):
                # A real note outside Wiki/ outranks an entry alias, as any
                # file does, and is not an entry the link could be missing.
                _outside = _outside_owners(tgt, _entry_vault_target(e))
                problems.append((
                    sl, "item10/non-entry",
                    f'wikilink target "{tgt}" resolves to the vault note '
                    f'"{_outside[0]}"'
                    + (f" (and {len(_outside) - 1} more)" if len(_outside) > 1 else "")
                    + " outside Wiki/, not to an entry; preserve the link, its "
                    "path, anchor and display text. Report only: never unlink "
                    "it as a dangler, retarget it to an entry or alias, or "
                    "create an entry for it"))
            elif os.path.splitext(bare)[1].lower() in _DOC_EXTS:
                continue
            elif lookup_key in alias_of:
                # An alias resolves to its existing entry. A new same-named
                # file would take precedence and steal that identity.
                if lookup_key in ambiguous_aliases:
                    ownership = (
                        "belongs to an entry whose filename has multiple physical owners"
                        if fold_name(alias_of[lookup_key][0]) in ambiguous_files
                        else "is claimed as an alias by multiple entries")
                    problems.append((sl, "item10/ambiguous",
                                     f'wikilink target "{tgt}" {ownership}; '
                                     f'preserve the link, anchor and display text until its '
                                     f'owner is resolved. Report only; never choose the first alias owner'))
                    continue
                _own_sl, _own_raw = alias_of[lookup_key]
                if _own_sl == sl:
                    problems.append((
                        sl, "item10/self",
                        f'wikilink target "{m.group(1)}" in {_link_region} is '
                        f'this entry\'s own alias "{_own_raw}" — render the '
                        "subject mention as plain text, or remove it from the "
                        "Related footer"))
                    continue
                if _unique_owner and _unique_slug(_own_sl):
                    _linked_owners[sl].add(_own_sl)
                _anchor_match = re.search(r"[#^].*", m.group(1))
                _anchor = _anchor_match.group(0) if _anchor_match else ""
                _label = m.group(2) if m.group(2) is not None else tgt
                _own_target = _entry_link_target(entries[_own_sl])
                _replacement = f'[[{_own_target}{_anchor}|{_label}]]'
                problems.append((sl,"item10/alias",
                                 f'wikilink target "{tgt}" is an alias of the entry '
                                 f'"{_own_sl}" (aliases: "{_own_raw}"), not an entry of its '
                                 f'own — the link RESOLVES in Obsidian. Fix in place: '
                                 f'rewrite to "{_replacement}". A new same-named note '
                                 f'creates a file that outranks the alias and steals every '
                                 f'"[[{tgt}]]" in the vault away from "{_own_sl}"'))
            elif alias_inventory_complete:
                problems.append((sl,"item10/dangling",f'wikilink target "{tgt}" does not resolve'))
        # Duplicate means one resolved entry, regardless of how the link was
        # spelled.  Paths, ``.md``, case/Unicode variants, and an unambiguous
        # alias all collapse to the same owner.  A file continues to outrank an
        # alias, exactly as in the resolution branch above.
        seen = {}
        spellings = {}
        for m in WIKILINK.finditer(_p10):
            raw_target = m.group(1).strip()
            key = entry_link_key(raw_target)
            if not key:
                continue
            record, status, owner_path = _resolve_entry_file(raw_target, _entry_vault_target(e))
            if (record is not None
                    and record.get("path_key") == e.get("path_key")):
                continue
            if status in ("parsed", "unparsed"):
                owners = paths_by_basename.get(entry_link_key(raw_target), set())
                key = ("file-path:" + owner_path if len(owners) > 1
                       else fold_name(record["slug"] if record
                                      else entry_link_key(raw_target)))
            elif status in {"ambiguous", "moc"}:
                # No safe duplicate-removal action exists until the bare or
                # partially qualified target identifies one file.
                continue
            elif _outside_owners(raw_target, _entry_vault_target(e)):
                # A note outside Wiki/ is not an entry: item10/non-entry
                # reports it, and no removal is inferred.
                continue
            elif not alias_inventory_complete:
                # A repeated unresolved spelling can belong to a skipped
                # note or conflict with a known alias; do not infer removal.
                continue
            elif key in ambiguous_aliases:
                # Preserve repeated ambiguous aliases until their owner is
                # resolved. Counting the raw spelling would still choose an
                # owner implicitly.
                continue
            elif key in alias_of:
                owner_slug = alias_of[key][0]
                if owner_slug == sl:
                    continue
                key = fold_name(owner_slug)
            seen[key] = seen.get(key, 0) + 1
            spellings.setdefault(key, []).append(raw_target)
        for key, count in seen.items():
            if count > 1:
                forms = ", ".join(repr(x) for x in spellings[key])
                problems.append((sl, "item10/dup",
                                 f'entry target "{key}" is wikilinked {count}× in prose '
                                 f'({forms}) — keep first only'))
        # ---- item 11: every Related footer link is piped to its canonical title ----
        if _unique_owner:
            # Every footer wikilink counts toward the child-link cap.
            _footer_links[sl] = len(WIKILINK.findall(strip_code(e["rel"])))
        for m in WIKILINK.finditer(e["rel"]):
            tgt, disp = m.group(1).strip(), m.group(2)
            # The link target may carry an anchor and/or a vault path while
            # still resolving to an entry.  Resolve the underlying basename
            # before deciding whether item 11 applies; a direct dict lookup on
            # the rendered target let [[Wiki/term#Heading]] escape the rule.
            lookup_key = entry_link_key(tgt)
            record, status, _owner_path = _resolve_entry_file(tgt, _entry_vault_target(e))
            if status == "ambiguous" or lookup_key in ambiguous_aliases:
                continue
            if (record is None and status == "missing" and lookup_key in alias_of
                    and not _outside_owners(tgt, _entry_vault_target(e))):
                record = entries.get(alias_of[lookup_key][0])
            if (record is not None
                    and record.get("path_key") == e.get("path_key")):
                continue
            if (record is not None and _unique_owner
                    and _unique_slug(record["slug"])):
                _footer_owners[sl].add(record["slug"])
            raw_title = record.get("title", "") if record else ""
            tt = title_display_form(raw_title) if raw_title else ""
            if not tt:
                continue
            if disp is None:
                problems.append((sl,"item11",f'Related footer bare link [[{tgt}]] should be piped to "{tt}"'))
            elif disp != tt:
                problems.append((sl, "item11",
                                 f'Related footer link [[{tgt}|{disp}]] must use '
                                 f'the canonical title "{tt}" as its display label'))

    problems.current_path = ""

    # ---- item 18: alias collisions + within-entry dup + display-label sanity ----
    alias_owner = {}
    for e in diagnostic_records:
        sl = e["slug"]
        problems.current_path = (
            e["path_key"]
            if fold_name(sl) in ambiguous_files else "")
        al = e["aliases"]
        if e["aliases_present"] and not e["aliases_is_list"]:
            if raw_scalar(e["fm_raw"], "aliases") == "":
                message = ("aliases: must be a list; a bare key is YAML null — "
                           "remove this optional key when there are no aliases, "
                           "or write aliases: [] for an explicit empty list")
            else:
                message = ("aliases: must be a list, not a scalar — wrap the "
                           "existing value as one quoted list item without changing it")
            problems.append((sl, "item18", message))
        _empty_aliases = sum(1 for a in e.get("aliases_all", ()) if a == "")
        if _empty_aliases:
            problems.append((sl, "item18",
                             f'aliases: contains {_empty_aliases} empty item'
                             f'{"s" if _empty_aliases != 1 else ""} — remove '
                             "empty strings; they are not alternate names"))
        for a in sorted({x for x in al if al.count(x) > 1}):
            problems.append((sl,"item18",f'alias "{a}" listed {al.count(a)}× within this entry'))
        # Case/normalization-variant duplicates WITHIN one entry: by the
        # fold_name doctrine both tools apply cross-entry, "TPR" beside "tpr"
        # is ONE name to Obsidian listed twice — but the raw count above sees
        # two strings and the cross-entry map skips same-entry pairs, so the
        # pair was reported by nobody.  lint_entry counts the same way; the two
        # tools must agree.
        _fold_first = {}
        for a in al:
            _k = fold_name(a)
            if not _k: continue
            if _k in _fold_first and _fold_first[_k] != a:
                problems.append((sl,"item18",
                                 f'aliases "{_fold_first[_k]}" and "{a}" differ only in '
                                 f'case/normalization — one name to Obsidian; keep one'))
            _fold_first.setdefault(_k, a)
        _own_family = singular_keys(fold_name(sl))
        _alias_families = []
        for a in al:
            try:
                expected = _slug_stem(a)
            except _SlugError:
                problems.append((sl,"item18",f'alias "{a}" cannot be converted to a slug'))
                continue
            if fold_name(expected) == fold_name(sl):
                problems.append((sl, "item18",
                                 f'alias "{a}" resolves to this entry\'s own '
                                 "filename — remove the redundant self-alias"))
            elif singular_keys(fold_name(expected)) & _own_family:
                problems.append((
                    sl, "item18",
                    f'alias "{a}" differs from this entry\'s filename only '
                    "by singular/plural normalization — remove the redundant "
                    "alias"))
            elif a != expected:
                problems.append((sl,"item18",
                                 f'alias "{a}" is not in slug form (expected "{expected}")'))
            _family = singular_keys(fold_name(expected))
            for _other, _other_expected, _other_family in _alias_families:
                if (fold_name(expected) != fold_name(_other_expected)
                        and _family & _other_family):
                    problems.append((
                        sl, "item18",
                        f'aliases "{_other}" and "{a}" differ only by '
                        "singular/plural normalization — keep one surface family"))
                    break
            _alias_families.append((a, expected, _family))
        # The never-an-alias rule's floor: the surface index hides such an
        # alias, so no recurring backfill row would ever expose it.
        for a in dict.fromkeys(cross_domain_alias_findings(al)):
            problems.append((
                sl, "item18/cross-domain-alias",
                f'alias "{a}" is a bare cross-domain term, which is never an '
                "alias — remove it under the alias-removal protocol"))
        # Keyed on fold_name, like every other "is this the same name?"
        # comparison in this file (see fold_name's docstring). Two aliases that
        # differ only in case or Unicode normalization share one portable owner
        # identity, making lookup ambiguous across supported hosts. Comparing raw strings reported nothing, and
        # CONVENTIONS §9 gives whole-vault dedup to this skill alone, so on a
        # vault-wide run the pair was seen by nobody. The raw spelling is kept
        # for the message: the fix is to change one of the two spellings, and
        # the user has to be told which two they are.
        for a in al:
            k = fold_name(a)
            if (k in alias_owner
                    and alias_owner[k][2] != e["path_key"]):
                own_sl, own_raw, own_path = alias_owner[k]
                problems.append((sl,"item18",
                                 f'alias "{a}" also on "{own_sl}"'
                                 + ("" if own_raw == a else
                                    f' (spelled "{own_raw}" there — the two differ only in '
                                    f'case/normalization and share one portable alias identity)')
                                 + (f' at "{own_path}"'
                                    if own_sl == sl else "")))
            elif k not in alias_owner:
                alias_owner[k] = (sl, a, e["path_key"])
    _body_label_owners = {}               # body-link display label -> its targets
    for e in diagnostic_records:
        sl = e["slug"]
        problems.current_path = (
            e["path_key"]
            if fold_name(sl) in ambiguous_files else "")
        _display_label_prose = mask_line_spans(
            strip_code(e["prose"]), e.get("table_spans", ()))
        for _match in REDUNDANT_PIPE.finditer(_display_label_prose):
            _target = _match.group("target")
            if (fold_name(_target) in _moc_basename_owners
                    or fold_name(_target) in _legacy_moc_names):
                continue
            problems.append((
                sl, "item10/redundant-pipe",
                f'wikilink [[{_target}|{_target}]] in body prose has a '
                f'display label identical to its slug — use [[{_target}]]'))
        _display_label_text = _display_label_prose + "\n" + strip_code(e["rel"])
        _display_label_prose_lines = _display_label_prose.count("\n") + 1
        # Label markup and the label/target surface floor are shared with
        # lint_entry (its folder mode resolves targets for the surface test).
        for _link in display_label_links(_display_label_text):
            tgt, disp = _link["target"], _link["display"]
            if _link["marks"]:
                problems.append((sl, "item18", _link["message"]))
                continue
            # A Related-footer label's wording is item 11's canonical-title
            # check, as in lint_entry; only its markup is item 18.
            if _link["line"] > _display_label_prose_lines:
                continue
            # A label passes when its tokens are a subset or a superset of
            # the target's title or an alias (entry_checks.label_shares_surface
            # explains why the test must stay that loose).
            target_key = entry_link_key(tgt)
            target_record, target_status, _target_path = _resolve_entry_file(tgt, _entry_vault_target(e))
            if (target_record is None and target_status == "missing"
                    and target_key not in ambiguous_aliases
                    and target_key in alias_of
                    and not _outside_owners(tgt, _entry_vault_target(e))):
                target_record = entries.get(alias_of[target_key][0])
            if target_record is not None and disp:
                _body_label_owners.setdefault(
                    " ".join(disp.split()).lower(), set()).add(
                        target_record["slug"])
            if (target_record is not None and disp
                    and target_record.get("aliases_complete", False)):
                target_slug = target_record["slug"]
                # The deliberately loose token floor below must accept
                # qualified bare terms and inflections, but that same looseness
                # can hide a concrete ownership conflict: `yeast` is a token
                # subset of the aliases on Saccharomyces cerevisiae even when a
                # real `yeast.md` entry owns the exact display.  Resolve the
                # display as a slug first (real file before alias, just like
                # item 10).  A unique different owner is a review finding, never
                # authority to auto-retarget; ambiguous ownership stays silent.
                display_slug = slug(disp)
                display_record = None
                display_path = None
                display_claim = None
                if display_slug:
                    display_record, display_status, display_path = \
                        _resolve_entry_file(display_slug)
                    display_key = fold_name(display_slug)
                    if display_record is not None and display_status == "parsed":
                        display_claim = "canonical entry"
                    elif (display_record is None and display_status == "missing"
                          and display_key not in ambiguous_aliases
                          and display_key in alias_of):
                        display_record = entries.get(alias_of[display_key][0])
                        if (display_record is not None
                                and fold_name(display_record["slug"])
                                not in ambiguous_files):
                            display_path = display_record.get("path_key")
                            display_claim = "unique alias"
                        else:
                            display_record = None
                if (display_record is not None and display_claim is not None
                        and display_record.get("path_key")
                        != target_record.get("path_key")):
                    display_title = (display_record.get("title")
                                     or display_record.get("slug"))
                    chosen_title = target_record.get("title") or target_slug
                    problems.append((
                        sl, "item18",
                        f'wikilink [[{tgt}|{disp}]] uses display label "{disp}" '
                        f'that exactly names a different {display_claim}, '
                        f'"{display_title}" at "{display_path or display_record["slug"]}", '
                        f'rather than the chosen target "{chosen_title}" — review '
                        f'the target or label; do not auto-retarget'))
                    continue
                _surfaces = [target_record["title"]] + target_record["aliases"]
                ok = label_shares_surface(disp, _surfaces)
                if not ok and organism_common_name_bound(target_record, disp):
                    ok = True
                # A body label may be a cross-domain synonym the target itself
                # introduces in italics (wiki-build writing.md's first
                # display-label carve-out).
                if not ok and cross_domain_synonym_label(
                        disp, _surfaces, target_record.get("prose", "")):
                    ok = True
                if not ok:
                    target_title = target_record.get("title") or target_slug
                    location = _target_path or target_slug
                    problems.append((sl,"item18",f'wikilink [[{tgt}|{disp}]] — "{disp}" shares no surface form with the canonical target "{target_title}" at "{location}" (its title/aliases), and no explicit Organism common-name binding applies; likely wrong target or invented label'))
                    continue
                # The loose floor above also passes a label built only from
                # the title's modifiers (`greedy` for Greedy algorithm).
                _head = label_drops_head(disp, target_record["title"],
                                         target_record["aliases"],
                                         target_record.get("prose", ""))
                if _head and not organism_common_name_bound(target_record, disp):
                    target_title = target_record.get("title") or target_slug
                    problems.append((
                        sl, "item18/partial-label",
                        f'wikilink [[{tgt}|{disp}]] — "{disp}" keeps only '
                        f'modifiers of the target title "{target_title}" and '
                        f'omits its head word "{_head}"; reword so the label '
                        "names the target (its title, an alias, an inflection "
                        "or a derived form), or review whether the label names "
                        "a different entity; do not auto-retarget"))

    problems.current_path = ""

    # ---- item 5: collision probes across entries (candidates for Task 1b's merge check; a match never merges) ----
    collisions = []
    ident_owners = {}                     # exact identifier (slug or alias) -> its owners, in scan order
    for sl,e in entries.items():
        for ident in [sl] + e["aliases"]:
            owners = ident_owners.setdefault(ident, [])
            if sl not in owners:
                collisions.extend((sl, other, "exact", ident) for other in owners)
                owners.append(sl)
    def group_probe(keyfn, name, pair_ok=None, skip_pairs=None):
        # `pair_ok(ident_a, ident_b)` is an optional last-word filter on a grouped pair —
        # for a probe whose key deliberately over-groups (see word-order-singular below).
        # `keyfn` may return one key or a SET of them: English singularization is
        # ambiguous ("bases" = base | basis), so an identifier has to be filed under
        # every plausible reading or the probe only fires when the plural happens to
        # be the side that guessed right.
        groups = {}
        for sl,e in entries.items():
            for ident in [sl] + e["aliases"]:
                k = keyfn(ident)
                for key in ((k,) if isinstance(k, str) else k):
                    groups.setdefault(key, set()).add((sl, ident))
        for key,members in groups.items():
            slugs = {m[0] for m in members}
            if len(slugs) > 1:
                ms = sorted(members)
                for i in range(len(ms)):
                    for j in range(i+1,len(ms)):
                        pair = frozenset((ms[i][0], ms[j][0]))
                        # A shared identifier is the `exact` probe's alone;
                        # its hyphen-free, sorted and singular keys match too.
                        if (ms[i][0] != ms[j][0]
                                and ms[i][1] != ms[j][1]
                                and (pair_ok is None or pair_ok(ms[i][1], ms[j][1]))
                                and (skip_pairs is None or pair not in skip_pairs)):
                            collisions.append((ms[i][0], ms[j][0], name, f"{ms[i][1]}~{ms[j][1]}"))
    # `singular_keys` is shared/scripts/plurals.py's probe-(c) key SET — every plausible
    # singular of the identifier's head token, the identifier itself included — so an
    # ambiguous `-es` ("bases" = base + basis) files under both readings in one pass.
    group_probe(singular_keys, "plural")
    group_probe(lambda s: s.replace("-",""), "hyphenation")
    group_probe(lambda s: "-".join(sorted(s.split("-"))), "word-order")
    # The sort above is a PURE token sort, so it cannot see `weight-tying` ~ `tying-weights`:
    # `weights` does not sort to `weight`. wiki-build/references/merge.md describes the
    # singularized comparison, and wiki-build's find_collisions.py runs probe
    # (e) twice for it (`wordorder_key` AND `wordorder_key_singular`). CONVENTIONS §9 gives
    # whole-vault duplicate detection to wiki-lint alone — wiki-build only probes the
    # candidates of the source in front of it — so a pair already sitting in the vault is seen
    # by NOBODY unless this scanner runs the singularized half too. The key function is
    # shared/scripts/plurals.py's, the same one wiki-build calls, so there is nothing left
    # here to drift from it.
    #
    # `real_permutation` is that module's guard, not a copy of it. Equal raw sorts are the
    # `word-order` hit above, and a plural on the head token is a pair `plural` already
    # reports — either would put the same pair in the worklist a second time.
    group_probe(wordorder_key_singular, "word-order-singular", real_permutation)
    # µ-variant probe via titles
    for sl,e in entries.items():
        t = e["title"]
        if "µ" in t or "μ" in t:
            alt = slug(t.replace("µ","\u03bc")) if "µ" in t else slug(t.replace("\u03bc","µ"))
            if alt != sl and alt in entries:
                collisions.append((sl, alt, "µ-variant", f"{sl}~{alt}"))
    # Probe (f), light stem morphology, is the last whole-key probe in
    # wiki-build.  It only adds a signal when none of the earlier probes
    # already covered the pair, so a plural such as roc-curve/roc-curves keeps
    # the more precise `plural` label instead of acquiring a second finding.
    # The key itself lives in shared/scripts/plurals.py and is therefore
    # byte-for-byte the builder's create-time key rather than a local copy.
    covered_pairs = {frozenset((a, b)) for a, b, _p, _d in collisions}
    group_probe(stem_key, "stem-morphology", skip_pairs=covered_pairs)
    # A bare entry or alias equal to a qualified title's base term (`outlier`
    # beside `outlier-statistics`) is a duplicate or naming candidate. This is
    # not the omitted token-superset probe, which would flood on qualifier-
    # versus-other-base pairs (`feature-machine-learning`, `machine-learning`).
    covered_pairs = {frozenset((a, b)) for a, b, _p, _d in collisions}
    _ident_keys = {}
    for sl, e in entries.items():
        for ident in [sl] + e["aliases"]:
            for key in singular_keys(ident):
                _ident_keys.setdefault(key, []).append((sl, ident))
    for sl, e in sorted(entries.items()):
        t = e.get("title") or ""
        if not has_parenthetical(t):
            continue
        _base_slug = slug(base_term(t))
        if not _base_slug:
            continue
        _matched = {}
        for key in sorted(singular_keys(_base_slug)):
            for other, ident in _ident_keys.get(key, ()):
                if other != sl:
                    _matched.setdefault(other, ident)
        for other, ident in sorted(_matched.items()):
            if frozenset((other, sl)) not in covered_pairs:
                collisions.append((other, sl, "base-term", f"{ident}~{sl}"))
    # dedup collisions (unordered pair + probe)
    seen_c = set(); collisions2 = []
    for a,b,p,d in collisions:
        key = (frozenset((a,b)), p)
        if key in seen_c: continue
        seen_c.add(key); collisions2.append((a,b,p,d))

    # ---- Surface map + backfill candidates (Task 2 worklist; the executing agent judges closeness) ----
    surface_owners = {}                   # lowercased surface form -> all owners
    _title_surf, _alias_surf, _organism_common_surf = set(), set(), set()
    _base_surf, _real_alias_surf = set(), set()
    for e in diagnostic_records:
        sl = e["slug"]
        forms = ([("title", e["title"])]
                 + [("alias", a.replace("-", " ")) for a in e["aliases"]]
                 + [("organism-common", name)
                    for name in organism_common_name_surfaces(e)])
        # A parenthetical title's base term is its running-prose form
        # ("outlier" for Outlier (statistics)). The base term itself is
        # tested, so a floor word's plural ("features") never enters, and a
        # base another target already owns as a body-link label ("variance"
        # for Bias/variance trade-off) names that sense instead.
        if has_parenthetical(e["title"]):
            _base = base_term(e["title"])
            if (_base and not cross_domain_word(_base)
                    and not any(_body_label_owners.get(v.lower(), set()) - {sl}
                                for v in (_base, plural_surface(_base)))):
                forms.append(("base", _base))
        for kind, f in forms:
            if not f or len(f) < 3: continue
            # `plural_surface`, not `pluralize`: the latter takes ONE token, and
            # a whole title matches no irregular in its table (see plural_surface).
            for variant in (f, plural_surface(f)):
                surface_owners.setdefault(variant.lower(), set()).add(sl)
                if kind == "title":
                    _title_surf.add(variant.lower())
                elif kind in ("alias", "base"):
                    _alias_surf.add(variant.lower())
                    if kind == "base":
                        _base_surf.add(variant.lower())
                    else:
                        _real_alias_surf.add(variant.lower())
                else:
                    _organism_common_surf.add(variant.lower())
    # A shared title/alias (or plural) supplies no unique link destination.
    # Choosing the first owner can link an entry's own opener to another
    # entity; duplicate basenames are ambiguous even with one parsed record.
    surf_map = {surface: next(iter(owners))
                for surface, owners in surface_owners.items()
                if len(owners) == 1
                and fold_name(next(iter(owners))) not in ambiguous_files}
    # Alias-mediated bare-noun surfaces: a single all-lowercase word reached
    # only through a qualified entry's alias ("covariate"); a COMMON_NOUNS word
    # never becomes a surface at all (_index_surfaces).  These match
    # everywhere, nearly always fail the closeness bar, and — candidates
    # carrying no memory — resurfaced for identical re-judgment every run.
    # The candidate is still emitted (the closeness call stays with the executing agent;
    # a qualified-target link to a bare term is legal in principle) but is
    # TAGGED `bare_noun_alias` so the report can batch them.  The same
    # single-word shape reached through a TITLE is already suppressed or
    # surfaced by COMMON_NOUNS and item 5's bare-slug check.
    _qualified = {e["slug"] for e in diagnostic_records
                  if has_parenthetical(e["title"])}
    bare_noun_alias = {s for s in _alias_surf - _title_surf
                       if re.fullmatch(r"[a-z]+", s)
                       and surface_owners[s] <= _qualified}
    def _backfill_owner(target, entry):
        record, status, _path = _resolve_entry_file(target, _entry_vault_target(entry))
        if record is not None and status == "parsed":
            return (None if fold_name(record["slug"]) in ambiguous_files
                    else record["slug"])
        key = entry_link_path_key(target)
        if (status == "missing" and "/" not in key
                and key not in ambiguous_aliases and key in alias_of):
            return alias_of[key][0]
        return None

    # Discipline roots: backfill tags their candidates `discipline_root` for
    # batch review and drops compound mentions ("cell biology").
    _root_slugs = {s for s, r in entries.items()
                   if _record_is_discipline_root(s, r)}
    _late_links = []
    backfill = (build_backfill(entries, surf_map, _moc_basename_owners, _backfill_owner,
                               root_targets=_root_slugs, late_links=_late_links,
                               quiet_surfaces=bare_noun_alias,
                               base_only_surfaces=_base_surf - _real_alias_surf)
                if alias_inventory_complete else [])
    for _sl, _target, _matched, _surface in sorted(_late_links):
        _target_title = entries[_target].get("title") or _target
        problems.current_path = (entries[_sl]["path_key"]
                                 if fold_name(_sl) in ambiguous_files else "")
        problems.append((
            _sl, "item10/late-link",
            f'the first body link to "{_target_title}" follows an earlier '
            f'plain mention "{_matched}" — move the link there when that '
            "mention names the same entity; a different sense, or a "
            "discipline root named only as a setting, stays plain"))
    problems.current_path = ""

    # Exact normalized sentence overlap is a cross-entry ownership candidate,
    # not proof that either copy is wrong: each entry is clean in isolation,
    # while only one is the explanation's owner. Task 1b keeps the owner's
    # copy and trims the others to a one-clause consequence linked to it;
    # refactors.md, not this message, chooses the owner (a family-wide
    # property goes to the family's entry, not to the most specific one).
    sentence_owners = {}
    for _slug, _entry in sorted(entries.items()):
        for _normalized, _surface in duplicate_sentence_surfaces(
                _entry.get("prose", ""), _entry.get("table_spans", ())):
            sentence_owners.setdefault(_normalized, {}) \
                .setdefault(_slug, _surface)
    for _normalized, _owners in sorted(sentence_owners.items()):
        if len(_owners) < 2:
            continue
        _all_slugs = sorted(_owners)
        for _slug in _all_slugs:
            _peers = [peer for peer in _all_slugs if peer != _slug]
            _snippet = _owners[_slug]
            if len(_snippet) > 180:
                _snippet = _snippet[:177].rstrip() + "..."
            problems.append((
                _slug, "item9/duplicate-sentence",
                "a long prose sentence has the same normalized word sequence "
                "in %s: %r — Task 1b consolidates it in its owner under the "
                "refactors.md consolidation rule and trims every other copy "
                "to its consequence in one clause linked to the owner; "
                "normalized similarity alone never chooses the owner"
                % (", ".join(_peers), _snippet)))

    # ---- discipline-tag census (VALID enum slugs vs off-enum/malformed) ----
    tag_counts = {}                       # VALID discipline slug -> entry count
    off_enum = {}                         # malformed/off-enum slug -> [entries using it]
    for sl,e in entries.items():
        for d in {d.lower() for d in e["tag_slugs"] if d.lower() in VALID_TAGS}:
            tag_counts[d] = tag_counts.get(d, 0) + 1
        for d in set(e["tag_slugs"]):
            if d.lower() not in VALID_TAGS:
                off_enum.setdefault(d, []).append(sl)
    untagged_entries = [sl for sl, e in entries.items() if e["tags_valid_empty"]]

    # ---- problem tally by checklist item ----
    # Explain the conservative gate on each affected path's existing QC row,
    # without introducing a public schema flag or a second repair worklist.
    unexplained_alias_gaps = set(alias_inventory_gaps)
    for i, (sl, item, message, path) in enumerate(problems):
        if ((sl, path) in unexplained_alias_gaps
                and item in {"item0", "item1", "item2", "item18"}):
            problems[i] = (sl, item, message + alias_gap_note, path)
            unexplained_alias_gaps.remove((sl, path))
    for sl, path in sorted(unexplained_alias_gaps):
        problems.current_path = path
        problems.append((sl, "item18", "aliases: could not be fully inventoried."
                         + alias_gap_note))
    problems.current_path = ""

    # The share of entries affected supports evidenced skill suggestions.
    tally = {}                                   # item -> [issue_count, set_of_entries]
    for sl,item,_message,_path in problems:
        t = tally.setdefault(item, [0, set()])
        t[0] += 1; t[1].add(sl)
    nentries = len(entries) or 1
    entry_set = set(entries)
    # `entries` also counts unreadable item0 paths; `pct_of_entries` is the
    # one-decimal share of parsed entries.
    tally_out = [dict(item=item, entries=len(ents),
                      pct_of_entries=round(100 * len(ents & entry_set) / nentries, 1),
                      issues=cnt)
                 for item,(cnt,ents) in sorted(tally.items(),
                                               key=lambda kv: (-len(kv[1][1]), -kv[1][0], kv[0]))]

    # ---- Rename candidates (item 5): filename != slug(title). Task 1b applies one through the entry-retitle protocol when its slug is free (a rename rewrites links vault-wide). ----
    inbound = {}
    for _e in entries.values():
        # Count actual entry links against the path record they resolve to.
        # Basename-only folding loses qualified paths and explicit `.md`
        # suffixes; raw-string counting also assigns an ambiguous bare basename
        # to whichever duplicate happened to be walked first.  The item-10
        # resolver already answers this safely, so reuse it here and decline to
        # count anything ambiguous or unparsed.
        _inbound_text = strip_code(_e["prose"]) + "\n" + strip_code(_e["rel"] or "")
        for _m in WIKILINK.finditer(_inbound_text):
            _record, _status, _owner_path = _resolve_entry_file(_m.group(1), _entry_vault_target(_e))
            if _status != "parsed" or _record is None or _owner_path is None:
                continue
            inbound[_owner_path] = inbound.get(_owner_path, 0) + 1
    renames = []
    _rename_targets = {}                  # folded new_slug -> [paths proposing it]
    # Every physical file, not only the first owner of a shared basename:
    # each twin may need its own rename, and each proposal competes for its
    # destination.
    for _e in diagnostic_records:
        _sl = _e["slug"]
        _new = slug(_e["title"]) if _e["title"] else ""
        # An unsluggable title (CJK, all-symbol) yields "" — renaming to it produces a
        # file literally called ".md".  Never propose it; item 5 already reports the title.
        if not _new or _new == _sl: continue
        _rename_targets.setdefault(fold_name(_new), []).append(_e["path_key"])
        renames.append([_sl, _new, inbound.get(_e["path_key"], 0), _e["path_key"]])
    # Alias owners from every parsed record, even when the alias inventory
    # has gaps: an incomplete inventory must not hide a known owner here.
    _any_alias_owners = {}
    for _e in diagnostic_records:
        for _a in _e["aliases"]:
            _any_alias_owners.setdefault(fold_name(_a), set()).add(_e["path_key"])
    for _r in renames:
        # target_exists ⇒ likely duplicate/disambiguation; do NOT rename into it, flag both.
        # Compared folded because a destination is taken whenever a file shares
        # its portable case/normalization identity. Only the file being
        # renamed is excluded, by its path: a twin sharing its basename still
        # occupies the destination, and a case-only rename still changes that
        # same file's spelling. Two candidates aiming at one destination
        # counts too: applying both in sequence would have the second silently
        # overwrite the first.
        #
        # Occupancy comes from every physical path, not from `entries`, for
        # the same reason the item10/unparsed carve-out above consults
        # `on_disk_fold`: a file that is ON DISK but did not parse (no
        # frontmatter, unreadable) is absent from `entries`, yet it is a real
        # file. The approved rename is `mv wrong-name.md broken.md`, which
        # destroys it.
        #
        # Another entry's alias is taken too: the renamed file would outrank
        # that alias and capture every link that now resolves through it.
        # The file's own alias is not a collision.
        _fold_new = fold_name(_r[1])
        _r.append(bool(paths_by_basename.get(_fold_new, set()) - {_r[3]})
                  or _fold_new in on_disk_fold
                  or len(_rename_targets[_fold_new]) > 1
                  or _fold_new in ambiguous_aliases
                  or bool(_any_alias_owners.get(_fold_new, set()) - {_r[3]}))

    # ---- Hierarchy diagnostic (Task 3): existing parent/MOC state ----------
    # Reflect existing parents. Generated trees root at their discipline entry,
    # so a self-parent is always a relationship to recompute in Task 3.
    def _parent_rows(e):
        """``(raw, target)`` per wikilink parent; an empty target is kept.

        A malformed non-wikilink item is left to the frontmatter form checks;
        ``placement_gaps`` still exposes the missing hierarchy edge.
        """
        out = []
        for p in e.get("parents", []):
            m = re.match(r"\s*\[\[([^\]|#]+)", str(p))
            if not m:
                continue
            target = m.group(1).split("^", 1)[0].strip()
            target = target.replace("\\", "/")
            if target.lower().endswith(".md"):
                target = target[:-3]
            out.append((str(p), target))
        return out

    def _parent_targets(e):
        return [target for _raw, target in _parent_rows(e) if target]
    # Each parent resolves once: `canonical_parents` drives the hierarchy,
    # and every unresolved row (an empty target reads as missing) becomes an
    # `unresolved_parents` diagnostic below.
    _resolved_parent_rows = {
        sl: [(_raw, _target,
              *_resolve_parent_target(_target, _entry_vault_target(e)))
             for _raw, _target in _parent_rows(e)]
        for sl, e in entries.items()
    }
    canonical_parents = {
        sl: [(_target, _owner, _reason)
             for _raw, _target, _owner, _reason in rows if _target]
        for sl, rows in _resolved_parent_rows.items()
    }

    # ---- Task 3: parents link down; Task 2: hub footer items ----
    # Both lists are report-only and empty while alias ownership is incomplete.
    _parent_owners = {s: {o for _t, o, _r in rows if o in entries and o != s}
                      for s, rows in canonical_parents.items()}
    _children = defaultdict(set)
    for _c, _owners in _parent_owners.items():
        if not _unique_slug(_c):
            continue
        for _p in _owners:
            _children[_p].add(_c)

    unlinked_children = []
    if alias_inventory_complete:
        for _p in sorted(_children):
            if _p == "misc" or _footer_links.get(_p, 0) >= FOOTER_CHILD_CAP:
                continue
            _missing = sorted(_children[_p] - _linked_owners.get(_p, set()))
            if not _missing:
                continue
            unlinked_children.append({
                "slug": _p,
                "children": len(_children[_p]),
                "footer_links": _footer_links.get(_p, 0),
                "unlinked": [_entry_link_target(entries[c]) for c in _missing],
                "branch_heads": [_entry_link_target(entries[c])
                                 for c in _missing if _children.get(c)],
            })

    hub_footer = []
    if alias_inventory_complete:
        _hub_min = hub_footer_min(len(entries))
        _counts = Counter(t for owners in _footer_owners.values() for t in owners)
        for _t, _n in sorted(_counts.items()):
            if _n < _hub_min or _t in _root_slugs or _t not in entries:
                continue
            _pt = _parent_owners.get(_t, set()) - _root_slugs
            _listed = []
            for _s in sorted(_footer_owners):
                if _t not in _footer_owners[_s]:
                    continue
                _ps = _parent_owners.get(_s, set()) - _root_slugs
                # A parent, child, sibling, or an entry the target's own
                # footer lists back is a neighbor the prune rule keeps.
                if (_t in _parent_owners.get(_s, ())
                        or _s in _parent_owners.get(_t, ()) or _ps & _pt
                        or _s in _footer_owners.get(_t, ())):
                    continue
                _listed.append(_s)
            if _listed:
                _hub_target = _entry_link_target(entries[_t])
                hub_footer.append({
                    "target": _hub_target, "footers": _n, "entries": _listed,
                    # One per `entries` item: its footer line's settled record.
                    "settle_keys": [
                        {"entry": _s, "target": _hub_target,
                         "context": settle_context(entries[_s]["rel"])}
                        for _s in _listed]})

    # Item 19's forward check: each primary cue beside its closest rivals.
    card_rivals = build_card_rivals(
        _primary_cues, {s: sorted(o) for s, o in _parent_owners.items()},
        {s: sorted(o) for s, o in _footer_owners.items()}, _root_slugs)

    # ``moc_consistency_findings`` is a report-only worklist for complete
    # generated MOC documents. Every MOC-local record has
    # ``kind``, ``discipline``, absolute ``path`` and ``message``; line-local
    # records also carry a 1-based ``line`` and link findings carry the
    # relevant ``slug``/``target`` where one is known. A cross-MOC
    # ``parent-union-mismatch`` instead carries ``slug``, ``disciplines``, and
    # the sorted targets in ``expected_parents``/``actual_parents`` (MOC
    # roots and colliding entry names retain their vault-relative paths).
    # Nothing in this list grants write authority.
    moc_consistency_findings = []
    _moc_parse = {}

    def _moc_expected_label(entry, discipline):
        """Canonical visible label for an entry in one discipline MOC."""
        title = title_display_form(entry.get("title") or "")
        match = re.search(r"\s+\(([^()]*)\)\s*$", title)
        if discipline != "misc" and match and slug(match.group(1)) == discipline:
            return title[:match.start()].rstrip()
        return title

    def _moc_add(state, kind, message, **fields):
        finding = {
            "kind": kind,
            "discipline": state["discipline"],
            "path": state["path"],
            "message": message,
        }
        finding.update(fields)
        moc_consistency_findings.append(finding)

    _bullet_line = re.compile(r"^(?P<indent>[ \t]*)- (?P<content>\S.*)$")
    for _moc_state in moc_states:
        _discipline = _moc_state["discipline"]
        if _moc_state["state"] not in {"readable", "empty"}:
            continue
        _tree = {
            "structurally_parseable": True,
            "present": set(),
            "placements": {},
            "blocked_placements": set(),
            "top_level": [],
        }
        _moc_parse[_discipline] = _tree
        # File safety and whole-document tree structure use the same guarded read.
        # Reopening the pathname here could follow a later symlink swap.
        _moc_text = _moc_texts[_moc_state["path"]]
        try:
            _moc_text, _provenance = split_provenance(_moc_text)
        except ValueError as exc:
            _tree["structurally_parseable"] = False
            _moc_add(_moc_state, "invalid-provenance",
                     "invalid skill provenance: %s" % exc)
        _moc_lines = _moc_text.splitlines()
        _stack = []                 # one parsed node at each active bullet level
        _previous_level = 0
        _seen_placement = {}        # (slug, nearest parent) -> first line
        for _idx in range(len(_moc_lines)):
            _line = _moc_lines[_idx]
            _line_no = _idx + 1
            if not _line.strip():
                continue
            _bullet = _bullet_line.match(_line)
            if not _bullet:
                _tree["structurally_parseable"] = False
                _moc_add(
                    _moc_state, "malformed-line",
                    "generated MOC line is not a nested '- ' bullet",
                    line=_line_no)
                # A missing/malformed bullet may have been an ancestor; do not
                # infer a parent through it for later indented lines.
                _stack = []
                _previous_level = 0
                continue

            _indent = _bullet.group("indent")
            _content = _bullet.group("content").strip()
            if "\t" in _indent or len(_indent) % 2:
                _tree["structurally_parseable"] = False
                _moc_add(
                    _moc_state, "malformed-indentation",
                    "tree indentation uses tabs or is not a multiple of two spaces",
                    line=_line_no)
                _stack = []
                _previous_level = 0
                continue

            _level = len(_indent) // 2 + 1
            _indent_ok = (
                _level <= _previous_level + 1
                and (_level == 1 or len(_stack) >= _level - 1))
            if not _indent_ok:
                _tree["structurally_parseable"] = False
                _moc_add(
                    _moc_state, "malformed-indentation",
                    "tree indentation jumps over a bullet level or has no parent bullet",
                    line=_line_no, depth=_level)

            _stack = _stack[:max(0, _level - 1)]
            _ancestor_safe = (_level == 1 or (
                len(_stack) >= _level - 1 and _stack[_level - 2]["safe"]))
            _node_safe = _indent_ok and _ancestor_safe
            _link = WIKILINK.fullmatch(_content)
            _linked_slug = None
            if _discipline == "misc" and (_level not in {1, 2} or _link is None):
                _tree["structurally_parseable"] = False
                _node_safe = False
                _moc_add(
                    _moc_state, "misc-format",
                    "misc must contain its Wiki root and one level of member links without categories",
                    line=_line_no)
            if _link is None and ("[[" in _content or "]]" in _content):
                _tree["structurally_parseable"] = False
                _node_safe = False
                _moc_add(
                    _moc_state, "malformed-line",
                    "linked tree bullets must contain exactly one whole-line wikilink",
                    line=_line_no)
            elif _link is None and (
                    re.match(r"(?:`{3,}|~{3,})", _content)
                    or any(token in _content for token in ("<!--", "-->", "%%"))):
                # A list bullet can open a fenced block or comment too. It is
                # not a visible category, and its children cannot establish a
                # navigation placement through text that renders as code or is
                # hidden from the reader.
                _tree["structurally_parseable"] = False
                _node_safe = False
                _moc_add(
                    _moc_state, "malformed-line",
                    "unlinked category bullets cannot contain code fences or comment delimiters",
                    line=_line_no)
            elif _link is not None:
                _raw_target = _link.group(1)
                _target = _raw_target.strip()
                _label = _link.group(2)
                _record, _status, _owner_path = _resolve_entry_file(
                    _target, os.path.relpath(_moc_state["path"], vault_root).replace("\\", "/"))
                _alias_key = entry_link_key(_target)
                if _status == "missing" and "/" not in entry_link_path_key(_target):
                    if _alias_key in ambiguous_aliases:
                        _status = "ambiguous"
                    elif _alias_key in alias_of:
                        _record = entries[alias_of[_alias_key][0]]
                        _status = "parsed"
                if (_status == "parsed" and _record is not None
                        and fold_name(_record["slug"]) in ambiguous_files):
                    _status = "ambiguous"
                if _status != "parsed" or _record is None:
                    # This line is visibly a link, not a plain category term,
                    # but its hierarchy identity is unknown. Descendants may
                    # not skip through it to a higher ancestor and thereby
                    # manufacture a parent union.
                    _node_safe = False
                    _moc_add(
                        _moc_state, "unresolved-link",
                        "MOC link does not resolve to one parsed Wiki entry",
                        line=_line_no, target=_target, reason=_status)
                else:
                    _entry_slug = _record["slug"]
                    _canonical_target = _entry_vault_target(_record)
                    if _raw_target != _canonical_target:
                        _moc_add(
                            _moc_state, "noncanonical-target",
                            "MOC link resolves, but its target is not the canonical vault-relative Wiki path",
                            line=_line_no, slug=_entry_slug, target=_raw_target,
                            expected_target=_canonical_target)
                    _expected_label = _moc_expected_label(_record, _discipline)
                    if _label != _expected_label:
                        _moc_add(
                            _moc_state, "noncanonical-label",
                            "MOC link label does not match the canonical discipline-scoped title",
                            line=_line_no, slug=_entry_slug,
                            label=_label, expected_label=_expected_label)
                    if _discipline not in _entry_moc_roots(_record):
                        _node_safe = False
                        _moc_add(
                            _moc_state, "wrong-discipline-link",
                            ("linked entry does not carry one valid sole #misc tag"
                             if _discipline == "misc" else
                             "linked entry does not carry this MOC's discipline tag"),
                            line=_line_no, slug=_entry_slug, target=_target)
                    else:
                        # A uniquely resolvable alias, path, case variant, or
                        # wrong label is still this placement. Report its form
                        # without cascading into a false missing-entry finding.
                        _tree["present"].add(_entry_slug)
                        if _node_safe:
                            _linked_slug = _entry_slug
                            # The top-level discipline entry is the actual
                            # root, with no parent. A MOC is never an ancestor.
                            _parent = None
                            for _ancestor in reversed(_stack):
                                if _ancestor["linked_slug"] is not None:
                                    _parent = _entry_parent_target(entries[_ancestor["linked_slug"]])
                                    break
                            _tree["placements"].setdefault(_entry_slug, []).append(
                                (_parent, _line_no))
                            _placement_key = (_entry_slug, _parent)
                            if _placement_key in _seen_placement:
                                _moc_add(
                                    _moc_state, "duplicate-placement",
                                    "entry appears more than once under the same nearest linked parent",
                                    line=_line_no, slug=_entry_slug, parent=_parent,
                                    first_line=_seen_placement[_placement_key])
                            else:
                                _seen_placement[_placement_key] = _line_no
                        else:
                            _tree["blocked_placements"].add(_entry_slug)

            if _level == 1:
                _tree["top_level"].append({
                    "slug": _linked_slug,
                    "line": _line_no,
                    "content": _content,
                })
            _stack.append({"linked_slug": _linked_slug, "safe": _node_safe})
            _previous_level = _level

        # A duplicated basename is item5's finding; its MOC link stays unresolved.
        _required = {sl for sl, e in entries.items()
                     if _discipline in _entry_moc_roots(e)
                     and fold_name(sl) not in ambiguous_files}
        for _missing_slug in sorted(_required - _tree["present"]):
            _moc_add(
                _moc_state, "missing-entry",
                "entry assigned to this MOC is absent from its generated tree",
                slug=_missing_slug)

        _eponymous = entries.get(_discipline)
        if (_tree["structurally_parseable"] and _eponymous is not None
                and _discipline in {
                    d.lower() for d in _eponymous["tag_slugs"]
                    if d.lower() in VALID_TAGS}):
            _top_slugs = [node["slug"] for node in _tree["top_level"]]
            if (_top_slugs != [_discipline]
                    or len(_tree["placements"].get(_discipline, [])) != 1
                    or _discipline in _tree["blocked_placements"]):
                _moc_add(
                    _moc_state, "eponymous-root",
                    "the eponymous discipline entry must be the single "
                    "top-level bullet and appear nowhere else, with every "
                    "other branch nested below it",
                    slug=_discipline,
                    top_level_slugs=_top_slugs)
        if _discipline == "misc" and _tree["structurally_parseable"]:
            _member_slugs = [sl for sl, placements in _tree["placements"].items()
                             if sl != "misc"]
            if all(sl is not None for sl in _member_slugs):
                _ordered = sorted(_member_slugs, key=lambda sl: (
                    fold_name(_moc_expected_label(entries[sl], "misc")),
                    _entry_vault_target(entries[sl])))
                if _member_slugs != _ordered:
                    _moc_add(_moc_state, "misc-order",
                             "misc entries must be sorted by canonical display title, then vault-relative path")

    # Compare the exact complete parents union only when every valid tagged
    # discipline has a readable, structurally parseable tree and the entry has a
    # usable placement in each. This prevents a missing/unreadable/broken MOC from
    # turning an incomplete observation into a false union mismatch.
    for _entry_slug, _entry in sorted(entries.items()):
        _tagged_disciplines = sorted(_entry_moc_roots(_entry))
        if not _tagged_disciplines:
            continue
        if (_entry_slug in VALID_TAGS and _entry["tags_valid_single"]
                and _tagged_disciplines == [_entry_slug]):
            continue  # eponymous-root and root-parent-mismatch govern a root
        if any(
                d not in _moc_parse
                or not _moc_parse[d]["structurally_parseable"]
                or not _moc_parse[d]["placements"].get(_entry_slug)
                or _entry_slug in _moc_parse[d]["blocked_placements"]
                for d in _tagged_disciplines):
            continue
        _expected_parents = sorted({
            parent
            for d in _tagged_disciplines
            for parent, _line in _moc_parse[d]["placements"][_entry_slug]
            if parent is not None})
        _actual_parents = sorted(set(_parent_targets(_entry)))
        if _actual_parents != _expected_parents:
            moc_consistency_findings.append({
                "kind": "parent-union-mismatch",
                "slug": _entry_slug,
                "disciplines": _tagged_disciplines,
                "expected_parents": _expected_parents,
                "actual_parents": _actual_parents,
                "message": (
                    "parents: does not equal the union of nearest linked ancestors "
                    "across all assigned generated MOCs"),
            })

    moc_consistency_findings.sort(key=lambda finding: (
        finding.get("discipline", ""),
        finding.get("line", 0),
        finding["kind"],
        finding.get("slug", ""),
        finding.get("target", ""),
    ))
    parent_state_findings = []
    for _discipline in sorted(_moc_entry_counts):
        _root = entries.get(_discipline)
        if (_root is None or not _root["tags_valid_single"]
                or _entry_moc_roots(_root) != {_discipline}):
            parent_state_findings.append({
                "slug": _discipline,
                "kind": "missing-discipline-root",
                "message": "active discipline needs a uniquely owned Wiki root with its matching sole tag",
            })
    for _entry_slug, _entry in sorted(entries.items()):
        _is_root = (_entry_slug in VALID_TAGS
                    and _entry["tags_valid_single"]
                    and _entry_moc_roots(_entry) == {_entry_slug})
        if _is_root and _entry.get("parents"):
            parent_state_findings.append({
                "slug": _entry_slug,
                "kind": "root-parent-mismatch",
                "parents": list(_entry["parents"]),
                "message": "a discipline Wiki root must have parents: []",
            })
        for _target, _owner, _reason in canonical_parents[_entry_slug]:
            if (_target.lower().startswith("mocs/")
                    or (_owner and _owner.startswith("@moc:"))):
                parent_state_findings.append({
                    "slug": _entry_slug,
                    "kind": "moc-parent",
                    "parent": _target,
                    "message": "MOCs are navigation notes and cannot be parents; derive a Wiki ancestor",
                })
        if not _entry.get("parents"):
            continue
        _misc_root = entries.get("misc")
        _misc_parent = _entry_parent_target(_misc_root) if _misc_root else None
        if (_entry["tags_valid_misc"] and not _is_root
                and _parent_targets(_entry) != [_misc_parent]):
            parent_state_findings.append({
                "slug": _entry_slug,
                "kind": "misc-parent-mismatch",
                "parents": list(_entry["parents"]),
                "message": "a misc member must have only [[%s]] as its parent"
                           % (_misc_parent or "misc"),
            })
    selfp = sorted(
        sl for sl, e in entries.items()
        if any(owner == sl for _target, owner, _reason in canonical_parents[sl]))

    # Retain legacy tag memberships for migration diagnostics, even though
    # multiple tags now fail QC. Only Wiki ancestors can establish placement;
    # MOC links cannot hide a missing concept relationship.
    placement_gaps = []
    for sl, e in sorted(entries.items()):
        required = _entry_moc_roots(e)
        if not required:
            continue
        if sl in VALID_TAGS and e["tags_valid_single"] and required == {sl}:
            continue  # A discipline root is correctly placed with empty parents.
        represented = set()
        for _target, owner, _reason in canonical_parents[sl]:
            if owner is None or owner == sl:
                continue
            if owner.startswith("@moc:"):
                continue
            elif owner in entries:
                represented.update(
                    d.lower() for d in entries[owner]["tag_slugs"]
                    if d.lower() in required)
        missing = sorted(required - represented)
        if missing:
            placement_gaps.append({
                "slug": sl,
                "missing_disciplines": missing,
                "represented_disciplines": sorted(represented),
            })
    unresolved_parents = [
        {"slug": _sl, "parent": _raw, "target": _target, "reason": _reason}
        for _sl, rows in sorted(_resolved_parent_rows.items())
        for _raw, _target, _owner, _reason in rows
        if _reason is not None
    ]
    # ---- parent CYCLES of length >= 2 (Task 3) ----
    # A self-parent is the 1-cycle and is reported above.  The 2-cycle — A
    # parents B and B parents A — is the one a hand-edit or an interrupted run
    # actually leaves behind, and it was invisible: nothing self-parented, the
    # diagnostic read clean, and every walk up the tree from either entry runs
    # forever.  Longer cycles come out of the same search for free.
    _parent_of = {}
    for _sl, _e in entries.items():
        _parent_of[_sl] = [
            owner for _target, owner, _reason in canonical_parents[_sl]
            if owner in entries
        ]
    # One depth-first walk with three-colour marking, so every EDGE is looked at
    # once and the pass is O(entries + parent links). Enumerating every simple
    # cycle instead is exponential on a densely mis-parented vault, and this is
    # a diagnostic: one cycle per back edge is what Task 3 needs to break it.
    _state = {}                       # slug -> 1 on the current path, 2 finished
    _cycles, _seen_cyc = [], set()
    for _start in sorted(entries):
        if _state.get(_start):
            continue
        _state[_start] = 1
        _path = [_start]
        _stack = [(_start, iter(sorted(_parent_of.get(_start, []))))]
        while _stack:
            _node, _it = _stack[-1]
            _nxt = next(_it, None)
            if _nxt is None:
                _state[_node] = 2
                _stack.pop(); _path.pop()
                continue
            if _nxt not in entries:            # roots/missing targets cannot participate in an entry cycle
                continue
            if _state.get(_nxt) == 1:          # a back edge, i.e. a cycle
                _cyc = _path[_path.index(_nxt):]
                if len(_cyc) < 2: continue     # the 1-cycle is `self_parented`
                _i = _cyc.index(min(_cyc))     # rotate to a canonical spelling
                _rot = tuple(_cyc[_i:] + _cyc[:_i])
                if _rot not in _seen_cyc:
                    _seen_cyc.add(_rot); _cycles.append(list(_rot))
                continue
            if _state.get(_nxt) == 2:
                continue
            _state[_nxt] = 1
            _path.append(_nxt)
            _stack.append((_nxt, iter(sorted(_parent_of.get(_nxt, [])))))
    _cycles.sort()
    _backfill_rows = []
    # Sorting on entry and target alone keeps each target's sentences in
    # text order, so apply_settled offers the first unsettled one.
    for s, t, f, key, line, context in sorted(backfill,
                                              key=lambda row: row[:2]):
        _target = _entry_link_target(entries[t])
        _backfill_rows.append({
            "slug": s, "target": _target, "surface": f,
            "bare_noun_alias": key in bare_noun_alias,
            "organism_common_name": key in _organism_common_surf,
            "discipline_root": t in _root_slugs,
            "base_term": key in _base_surf,
            "line": line,
            "settle_key": {"entry": s, "target": _target, "surface": f,
                           "context": context}})
    _backfill_rows, hub_footer, _settled = apply_settled(
        _backfill_rows, hub_footer, settled, alias_inventory_complete)
    def _public_problem(row):
        slug_value, item, message, path = row
        result = {"slug": slug_value, "item": item, "message": message}
        if path:
            result["path"] = path
        return result

    return {
        # stamp suggestion-item observations with this; rescans are the same run
        "run_timestamp": f"{datetime.datetime.now():%Y-%m-%d %H:%M}",
        "wiki_path": os.path.abspath(wiki),
        "vault_root": vault_root,
        "inventory": {
            "entries": len(entries),
            "slugs": sorted(entries),
        },
        "discipline_tags": dict(sorted(tag_counts.items())),
        "off_enum_tags": {d: sorted(set(v)) for d,v in sorted(off_enum.items())},
        "untagged_entries": sorted(untagged_entries),
        "problems": [_public_problem(row) for row in sorted(
            problems, key=lambda row: (row[0], row[1], row[3], row[2]))],
        "problem_tally": tally_out,
        # Step 0's user-issue worklist: each entry whose issues: is non-blank,
        # its form ("string" or "list") and its decoded issue texts.
        "user_issues": sorted(user_issues,
                              key=lambda row: (row["slug"], row.get("path", ""))),
        "collision_candidates": [{"a": a, "b": b, "probe": p, "detail": d}
                                 for a,b,p,d in sorted(collisions2)],
        # A basename that several files share adds the file's path, as in
        # `problems`, so each twin's row names the file to rename.
        "rename_candidates": [
            dict({"slug": s, "new_slug": n, "inbound_links": c, "target_exists": x},
                 **({"path": p} if fold_name(s) in ambiguous_files else {}))
            for s, n, c, p, x in sorted(renames, key=lambda r: (r[0], r[3]))],
        # `bare_noun_alias`: the matched surface is a single all-lowercase word
        # reached only through an alias — batch these in the report; the
        # closeness judgment itself stays with the executing agent (see build_backfill).
        # A target is a writable link destination, so a real MOC basename
        # owner requires the same Wiki qualification as an entry parent.
        # `discipline_root`: the target is a Wiki discipline root, which the
        # closeness bar accepts only where the passage discusses the field
        # itself — batch-review these like `bare_noun_alias`.
        # `base_term`: the surface is a parenthetical title's base term.
        # `settle_key`: the settled-ledger record of the offered sentence;
        # `settle_keys`: it and the target's later unsettled sentences, the
        # records a rejection stores.
        "backfill_candidates": _backfill_rows,
        # Report-only; Task 2 judges each listed footer item; no write authority.
        "hub_footer": hub_footer,
        # The --settled ledger's effect; it never suppresses `problems`.
        "settled": _settled,
        # Item 19's forward-check input: a floor, not an exhaustive rival set.
        "card_rivals": card_rivals,
        # Folder-level, report-only findings.  These are deliberately outside
        # `problems`: they are not entry checklist violations and must not
        # inflate per-entry problem tallies or imply deletion authority.
        "image_folder_findings": image_folder_findings,
        # Advisory; the plugin's settings file is read, never written.
        "spaced_repetition": spaced_repetition_report(
            vault_root, tag_counts),
        "hierarchy_diagnostic": {
            "entries": len(entries),
            "self_parented": selfp,
            # Report-only state from the hierarchy last written (or not yet
            # written). These worklists do not authorize Task 3 or its
            # transitive scope expansion.
            "placement_gaps": placement_gaps,
            "unresolved_parents": unresolved_parents,
            "parent_state_findings": parent_state_findings,
            # Parents whose body and footer leave direct children unlinked
            # while the footer has room; Task 3 appends them.
            "unlinked_children": unlinked_children,
            "moc_file_states": moc_states,
            "legacy_moc_states": legacy_moc_states,
            "moc_inventory_findings": moc_inventory_findings,
            "moc_consistency_findings": moc_consistency_findings,
            # Cycles of length >= 2 in `parents:` (the 1-cycle is `self_parented`).
            # Each is listed once, rotated to start at its alphabetically first
            # slug. Any entry named here has no path to a MOC root, so Task 3
            # must break the cycle before it can place either end.
            "parent_cycles": _cycles,
        },
    }


# ===========================================================================
# self-test
# ===========================================================================
#
# This scanner drives IN-PLACE EDITS to a whole vault.  Every case below is
# one where a wrong finding can destroy or misdirect user content -- a working
# link mis-classified as dangling and unlinked, a duplicate destination whose
# second link survives, or a backfill proposal aimed at a line no link may be
# written on.  Fixtures are built under `tempfile` and deleted; nothing here
# reads or writes anything outside the temp directory.
#
#     python3 scan_vault.py --test

def _st_entry(title, prose, tags=('"#statistics"',), type_="Concept",
              sources=('"[[Doe_X_2025.pdf#page=2]]"',), aliases=(),
              parents=(), extra_keys="", card=None, related=None,
              description=None):
    """A schema-clean entry, so a case only carries the fault it names.

    Anything left at its default produces NO finding -- the `clean entry`
    case below asserts exactly that -- so a case that adds one fault gets one
    finding, and a check that fires on the scaffolding is caught immediately.
    """
    def _block(key, items):
        if not items:
            return "%s: []\n" % key
        return "%s:\n" % key + "".join("  - %s\n" % i for i in items)
    fm = ['title: "%s"' % title, "type: %s" % type_]
    text = fm[0] + "\n" + fm[1] + "\n"
    if aliases:
        text += _block("aliases", aliases)
    text += _block("sources", sources)
    text += "created: 2026-01-01\nupdated: 2026-01-02\n"
    if description is None:
        subject = (math_title_plain_text(base_term(title))
                   or math_title_plain_text(title) or title)
        description = "%s is a worked example used by the self-test." % subject
    text += "description: %s\n" % json.dumps(description)
    text += _block("tags", tags)
    text += extra_keys
    text += _block("parents", parents)
    text += 'read: false\nissues: ""\n'
    body = prose
    # A clean entry fixture carries the required terminal footer even
    # when it has no related links. Pass ``related=False`` only when a test
    # deliberately exercises the missing-footer defect.
    has_related_marker = any(
        RELATED_HEAD_LINE_RE.match(line)
        for line in strip_fenced(body).split("\n"))
    if related is not False and not has_related_marker:
        body += "\n\n**Related:**" + ((" " + related) if related else "")
    if card is not False:
        term = card or title
        body += ("\n\n---\n\n## Flashcards\n\n"
                 "The idea this entry is about, stated once.\n??\n%s\n" % term)
    return "---\n" + text + "---\n" + body + "\n"


def _st_write(root, relpath, text, encoding="utf-8"):
    path = os.path.join(root, *relpath.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Keep fixture line endings verbatim, including explicit CRLF test cases.
    mode, kw = (("wb", {}) if isinstance(text, bytes)
                else ("w", {"encoding": encoding, "newline": ""}))
    with open(path, mode, **kw) as fh:
        fh.write(text)
    return path


def _st_items(res, slug=None):
    """The (slug, item) pairs reported, optionally for one entry."""
    return sorted((p["slug"], p["item"]) for p in res["problems"]
                  if slug is None or p["slug"] == slug)


def _st_keys(res, slug):
    return sorted(p["item"] for p in res["problems"] if p["slug"] == slug)


def _st_msg(res, slug, item):
    return " | ".join(p["message"] for p in res["problems"]
                      if p["slug"] == slug and p["item"] == item)


def run_self_test():
    import contextlib
    import io
    from pathlib import Path
    import shutil
    import tempfile
    cases = []

    def check(label, got, want):
        cases.append((label, got == want, got, want))

    check("numeric inline math is not mistaken for currency",
          [leftover_dollars(value) for value in (
              r"The rank satisfies $1 \le k \le m$.",
              r"The probability obeys $0 < p < 1$.",
              r"The fraction approaches $1-e^{-1}$.")],
          [0, 0, 0])
    check("two currency amounts remain two literal dollars",
          leftover_dollars("The price ranges from $20 to $30."), 2)
    check("dollars inside code spans and blocks remain literal examples",
          [leftover_dollars(value) for value in (
              "    echo $HOME", "``$HOME``", "```sh\necho $HOME\n```")],
          [0, 0, 0])

    tmp = tempfile.mkdtemp(prefix="scan_vault-selftest-")
    try:
        comments_vault = os.path.join(tmp, "hidden-comments")
        _st_write(comments_vault, "linked.md", _st_entry("Linked", "**Linked** describes a relation."))
        _st_write(comments_vault, "escaped.md", _st_entry("Escaped", "**Escaped** describes a link."))
        _st_write(comments_vault, "visible.md", _st_entry("Visible", "**Visible** describes a topic."))
        for kind, opening, closing in (("html", "<!--", "-->"), ("obsidian", "%%", "%%")):
            body = ("**Probe " + kind + "** introduces a topic.\n\n" + opening +
                    "\n## Flashcards\n**Related:** [[hidden]]\n```\n"
                    "[[linked]]\n" + closing + "\n\n"
                    "Linked explains a mechanism. Visible supplies a contrast.\n"
                    r"Literal \[[ghost]] and live \![[escaped]] syntax." + "\n")
            _st_write(comments_vault, "probe-" + kind + ".md",
                      _st_entry("Probe " + kind, body).replace(
                          "\n---\n\n## Flashcards",
                          "\n---\n\n" + opening + " note " + closing + "\n\n## Flashcards"))
        result = scan(comments_vault)
        # The HTML comment is left open on its first line, and the %% comment
        # holds a column-0 fence no column-0 line closes; each hides the rest
        # of the note from the Spaced Repetition plugin, and only that is
        # reported.
        check("commented templates and escaped syntax create no repair findings",
              [(p["slug"], p["item"]) for p in result["problems"]
               if p["slug"].startswith("probe-")],
              [("probe-html", "item19/sr-marker"),
               ("probe-obsidian", "item19/sr-marker")])
        check("hidden links do not suppress a later eligible backfill",
              sorted((c["slug"], c["target"]) for c in result["backfill_candidates"]
                     if c["slug"].startswith("probe-")),
              [("probe-html", "linked"), ("probe-html", "visible"),
               ("probe-obsidian", "linked"), ("probe-obsidian", "visible")])
        # ------------------------------------------------------------------
        # 1. parsing: what becomes an entry, and what becomes a report
        # ------------------------------------------------------------------
        v = os.path.join(tmp, "v1")
        _st_write(v, "anchor.md", _st_entry("Anchor", "**Anchor** is a worked example."))
        _st_write(v, "no-fm.md", "no frontmatter at all, just prose\n")
        _st_write(v, "unterminated.md",
                  '---\ntitle: "Unterminated"\ntype: Concept\nnever closed\n')
        # a byte that is not valid UTF-8: read() raises, and one bad file must
        # not take the scan down with it
        _st_write(v, "binary.md", b'---\ntitle: "Caf\xe9"\n---\nbody\n')
        _st_write(v, "bom.md", "\ufeff" + _st_entry("Bom", "**Bom** is a worked example."))
        _st_write(v, "crlf.md",
                  _st_entry("Crlf", "**Crlf** is a worked example.").replace("\n", "\r\n"))
        _st_write(v, "crlf-blank.md",
                  _st_entry("Crlf blank", "**Crlf blank** is a worked example.")
                  .replace("---\n**Crlf blank**", "---\n\n**Crlf blank**")
                  .replace("\n", "\r\n"))
        _st_write(v, "invalid-source.md", _st_entry(
            "Invalid source", "**Invalid source** is a worked example.",
            sources=('"unresolved-source"',), card=False, related=False))
        _st_write(v, "sub/nested.md",
                  _st_entry("Nested", "**Nested** is a worked example."))
        # a leading blank line: Obsidian reads properties only at line 1
        _st_write(v, "leading-blank.md", "\n" + _st_entry(
            "Leading blank", "**Leading blank** is a worked example."))
        # a frontmatter line that is neither a key nor a list item
        _st_write(v, "stray-line.md",
                  _st_entry("Stray line", "**Stray line** is a worked example.")
                  .replace("type: Concept\n",
                           "type: Concept\nnot a key or a list item\n"))
        _st_write(v, "unspaced-key.md",
                  _st_entry("Unspaced key", "**Unspaced key** is a worked example.")
                  .replace("type: Concept\n", "type:Concept\n"))
        for _name, _raw in (("flow-leading", ',"alias"'),
                            ("flow-middle", '"alias",,"other"'),
                            ("flow-trailing", '"alias",,'),
                            ("flow-one-trailing-comma", '"alias",')):
            _st_write(v, _name + ".md", _st_entry(
                _name.replace("-", " ").capitalize(),
                "**%s** is a worked example."
                % _name.replace("-", " ").capitalize()).replace(
                    "sources:\n", "aliases: [%s]\nsources:\n" % _raw, 1))
        linked = os.path.join(tmp, "linked-target")
        os.makedirs(linked)
        _st_write(linked, "symlinked.md",
                  _st_entry("Symlinked", "**Symlinked** is a worked example."))
        have_symlink = True
        try:
            os.symlink(linked, os.path.join(v, "linkdir"))
        except (OSError, NotImplementedError, AttributeError):
            have_symlink = False
        outside_leaf = os.path.join(tmp, "outside-leaf.md")
        _st_write(tmp, "outside-leaf.md",
                  _st_entry("Outside leaf", "**Outside leaf** is external."))
        have_leaf_symlink = True
        try:
            os.symlink(outside_leaf, os.path.join(v, "leaf-link.md"))
        except (OSError, NotImplementedError, AttributeError):
            have_leaf_symlink = False
        res = scan(v)
        check("flow lists with leading, middle, or trailing empty elements are item 1",
              ["item1" in _st_keys(res, slug_) for slug_ in
               ("flow-leading", "flow-middle", "flow-trailing")],
              [True] * 3)
        check("one trailing comma after an item is valid YAML, not item 1",
              "item1" in _st_keys(res, "flow-one-trailing-comma"), False)

        check("a schema-clean entry produces no finding at all",
              _st_keys(res, "anchor"), [])
        check("...and is parsed into the inventory",
              res["inventory"]["entries"] >= 1 and "anchor" in res["inventory"]["slugs"],
              True)
        check("no frontmatter -> item1", _st_keys(res, "no-fm"), ["item1"])
        check("an unterminated --- fence is not frontmatter -> item1",
              _st_keys(res, "unterminated"), ["item1"])
        check("a file that is not UTF-8 -> item0, and the scan continues",
              _st_keys(res, "binary"), ["item0"])
        check("a BOM does not hide the frontmatter", _st_keys(res, "bom"), [])
        check("a LEADING BLANK LINE before the fence is no frontmatter -> "
              "item1 (Obsidian reads properties only at line 1)",
              _st_keys(res, "leading-blank"), ["item1"])
        check("a frontmatter line that is neither key nor item is item1, "
              "never silently dropped",
              (_st_keys(res, "stray-line"),
               "not a key or a list item" in _st_msg(res, "stray-line", "item1")),
              (["item1"], True))
        check("a key with no space after its colon is an unparseable item1 line",
              "unparseable frontmatter line: 'type:Concept'"
              in _st_msg(res, "unspaced-key", "item1"), True)
        check("CRLF line endings parse", _st_keys(res, "crlf"), [])
        check("...and a CRLF blank line after the frontmatter is still item9",
              _st_keys(res, "crlf-blank"), ["item9"])
        check("an invalid source value never exempts an entry from normal source, footer, or card QC",
              [key in _st_keys(res, "invalid-source") for key in ("item4", "item11", "item19")],
              [True, True, True])
        check("an entry in a subfolder is scanned", "nested" in res["inventory"]["slugs"], True)
        if have_symlink:
            check("an entry in a SYMLINKED subfolder is scanned",
                  "symlinked" in res["inventory"]["slugs"], True)
        check("a leaf Markdown symlink is item0 and never an editable entry "
              "(skipped where symlink creation is unavailable)",
              (not have_leaf_symlink or
               (_st_keys(res, "leaf-link") == ["item0"]
                and "leaf-link" not in res["inventory"]["slugs"])),
              True)
        check("valid-frontmatter records remain inventoried while the four "
              "unreadable or non-frontmatter files are excluded",
              res["inventory"]["entries"], 12 + (1 if have_symlink else 0))

        v = os.path.join(tmp, "v1-symlink-loop")
        _st_write(v, "looped.md", _st_entry(
            "Looped", "**Looped** is a worked example."))
        _have_loop = True
        try:
            os.symlink(v, os.path.join(v, "loop"))
        except (OSError, NotImplementedError, AttributeError):
            _have_loop = False
        try:
            _loop_res = scan(v)
            _loop_seen = (_loop_res["inventory"]["entries"], _st_items(_loop_res))
        except IncompleteWikiInventoryError as exc:
            _loop_seen = str(exc)
        check("a symlink loop under Wiki/ scans each entry once "
              "(skipped where symlink creation is unavailable)",
              not _have_loop or _loop_seen == (1, []), True)
        # A symlinked folder back into the Wiki tree is pruned by name, so a
        # link that sorts before the real folder never hides its paths.
        v_back = os.path.join(tmp, "v1-symlink-back")
        _st_write(v_back, "topics/mean.md", _st_entry(
            "Mean", "**Mean** is a worked example."))
        _st_write(v_back, "topics/sample-mean.md", _st_entry(
            "Sample mean", "**Sample mean** is a worked example.",
            parents=('"[[Wiki/topics/mean]]"',)))
        _st_write(v_back, "median.md", _st_entry(
            "Median", "**Median** is compared with the "
            "[[Wiki/topics/mean|mean]].",
            related="[[Wiki/topics/mean|Mean]]"))
        _back_want = (["median.md", "topics/mean.md", "topics/sample-mean.md"],
                      False, [])
        try:
            os.symlink("topics", os.path.join(v_back, "alias-dir"))
        except (OSError, NotImplementedError, AttributeError):
            _back_seen = _back_want
        else:
            _back_res = scan(v_back)
            _back_seen = (
                [os.path.relpath(path, v_back).replace(os.sep, "/")
                 for path in iter_entry_files(v_back)],
                "item10/dangling" in _st_keys(_back_res, "median"),
                _back_res["hierarchy_diagnostic"]["unresolved_parents"])
        check("a symlinked folder back into Wiki/ is not walked, and its "
              "real paths still resolve (skipped where symlink creation is "
              "unavailable)", _back_seen, _back_want)

        # zero entries, and one entry
        empty = os.path.join(tmp, "empty")
        os.makedirs(empty)
        res0 = scan(empty)
        check("an empty vault scans to zero entries and zero problems",
              (res0["inventory"]["entries"], res0["problems"],
               res0["backfill_candidates"], res0["collision_candidates"]),
              (0, [], [], []))
        one = os.path.join(tmp, "one")
        _st_write(one, "solo.md", _st_entry("Solo", "**Solo** is a worked example."))
        res1 = scan(one)
        check("a one-entry vault scans clean",
              (res1["inventory"], res1["problems"]),
              ({"entries": 1, "slugs": ["solo"]}, []))

        metadata_vault = os.path.join(tmp, "unexpected-metadata")
        for name, drop_tags in (("tagged", False), ("missing-tags", True)):
            content = _st_entry(
                name.title(), "**%s** is a worked example." % name.title(),
                extra_keys='roots:\n  - "[[physics]]"\n')
            if drop_tags:
                content = content.replace('tags:\n  - "#statistics"\n', '')
            _st_write(metadata_vault, name + ".md", content)
        metadata_res = scan(metadata_vault)
        check("an unexpected property is reported and preserved without a metadata migration",
              [('unexpected frontmatter key "roots"' in _st_msg(metadata_res, name, "item2"),
                "preserve this user metadata" in _st_msg(metadata_res, name, "item2"),
                "migrate" in _st_msg(metadata_res, name, "item2"))
               for name in ("tagged", "missing-tags")],
              [(True, True, False)] * 2)
        check("unexpected metadata supplies neither missing tags nor inferred discipline membership",
              (metadata_res["discipline_tags"],
               "missing tags: key" in _st_msg(metadata_res, "missing-tags", "item2")),
              ({"statistics": 1}, True))

        # ------------------------------------------------------------------
        # 2. item 10 -- the destructive one.  A target mis-called `dangling`
        #    gets unlinked even though it resolves, so every carve-out below
        #    is a real file or alias whose working link must survive.
        # ------------------------------------------------------------------
        v = os.path.join(tmp, "v2")
        _st_write(v, "sub/delta.md", _st_entry(
            "Delta", "**Delta** is a worked example.", aliases=('"delta-alias"',)))
        _st_write(v, "ROC-curve.md", _st_entry("ROC-curve", "**ROC-curve** is a worked example."))
        _st_write(v, "broken.md", "no frontmatter here either\n")
        _st_write(v, "foo.md", _st_entry(
            "Root Foo", "**Root Foo** is the root ambiguous basename fixture."))
        _st_write(v, "a/foo.md", _st_entry(
            "Alpha", "**Alpha** is the first ambiguous basename fixture."))
        _st_write(v, "b/foo.md", _st_entry(
            "Beta", "**Beta** is the second ambiguous basename fixture."))
        _st_write(v, "path-reader.md", _st_entry(
            "Path reader", "**Path reader** compares [[a/foo|Alpha]] with "
            "[[b/foo|Beta]], while repeated ambiguous bare links "
            "[[foo]] and [[FOO.md|Foo]] remain unresolved. A qualified path "
            "that matches no owner, [[c/foo|Unknown path]], remains ambiguous "
            "while those basename owners coexist."))
        _st_write(v, "exact-path-reader.md", _st_entry(
            "Exact path reader", "**Exact path reader** repeats "
            "[[a/foo|Alpha]] and [[A/FOO.md|Alpha]]."))
        _st_write(v, "qualified-related-reader.md", _st_entry(
            "Qualified related reader",
            "**Qualified related reader** points to one colliding path.\n\n"
            "**Related:** [[b/foo|Beta]]"))
        _st_write(v, "wrong-qualified-reader.md", _st_entry(
            "Wrong qualified reader",
            "**Wrong qualified reader** points to [[b/foo|Alpha]].\n\n"
            "**Related:** [[b/foo|Alpha]]"))
        _st_write(v, "alias-a.md", _st_entry(
            "Alias A", "**Alias A** is one ambiguous alias owner.",
            aliases=('"shared-alias"',)))
        _st_write(v, "alias-b.md", _st_entry(
            "Alias B", "**Alias B** is another ambiguous alias owner.",
            aliases=('"shared-alias"',)))
        _st_write(v, "alias-reader.md", _st_entry(
            "Alias reader", "**Alias reader** compares [[shared-alias|one owner]] "
            "with [[SHARED-ALIAS|another owner]]."))
        _st_write(v, "md-ghost-reader.md", _st_entry(
            "Md ghost reader",
            "**Md ghost reader** links to [[ghost-note.md]] and "
            "[[Sub/ghost-three.md]].",
            related="[[ghost-footer.md|Ghost]]"))
        _st_write(v, "hub.md", _st_entry(
            "Hub",
            "**Hub** is a worked example that links to [[nowhere]], to "
            "[[roc-curve]], to [[broken]], to [[sub/delta]], to [[delta.md]], "
            "to [[DELTA|Delta]], to [[delta-alias|Delta]], to "
            "[[Doe_Foo_2025.pdf]] and embeds "
            "![[figure.png]].\n\n"
            "It also links [[sub/delta]] a second time."))
        res = scan(v)
        got = sorted(set(k for k in _st_keys(res, "hub")))
        check("a genuine dangler is item10/dangling", "item10/dangling" in got, True)
        check("...and only the genuine one",
              _st_msg(res, "hub", "item10/dangling").count("does not resolve"), 1)
        check("a case-only mismatch is item10/case, never a dangler",
              "nowhere" in _st_msg(res, "hub", "item10/dangling")
              and "roc-curve" in _st_msg(res, "hub", "item10/case"), True)
        check("a target on disk that did NOT parse is item10/unparsed, not dangling",
              "broken" in _st_msg(res, "hub", "item10/unparsed"), True)
        check("...and item10/unparsed says never to overwrite it",
              "NEVER overwrite" in _st_msg(res, "hub", "item10/unparsed"), True)
        check("a path-qualified target resolves",
              "sub/delta" in _st_msg(res, "hub", "item10/dangling"), False)
        check("an explicit .md suffix resolves",
              "delta.md" in _st_msg(res, "hub", "item10/dangling"), False)
        check("without a known vault root an explicit .md suffix is still "
              "respelled, but a path is kept",
              ('wikilink target "delta.md" names the entry "delta" with an '
               "explicit `.md` suffix" in _st_msg(res, "hub", "item10/case"),
               '"sub/delta"' in _st_msg(res, "hub", "item10/case")),
              (True, False))
        check("a document link (.pdf) is not an entry link",
              "Doe_Foo_2025.pdf" in _st_msg(res, "hub", "item10/dangling"), False)
        check("an explicit .md suffix naming no Wiki file is item10/dangling "
              "in body prose and the Related footer",
              [name in _st_msg(res, "md-ghost-reader", "item10/dangling")
               for name in ('"ghost-note.md"', '"Sub/ghost-three.md"',
                            '"ghost-footer.md"')], [True, True, True])
        check("an ![[image.png]] embed is excluded from item 10 entirely",
              "figure.png" in " ".join(p["message"] for p in res["problems"]), False)
        check("path, explicit .md, and case variants of the same resolved "
              "entry collapse into one item10/dup target",
              ('entry target "delta" is wikilinked 5×'
               in _st_msg(res, "hub", "item10/dup")), True)
        check("two path-qualified links with one ambiguous basename are not "
              "collapsed into item10/dup",
              "item10/dup" in _st_keys(res, "path-reader"), False)
        check("the ambiguous destinations remain report-only instead",
              _st_msg(res, "path-reader", "item10/ambiguous").count(
                  "multiple same-basename paths"), 3)
        check("an exact repeated qualified path still gets item10/dup",
              "item10/dup" in _st_keys(res, "exact-path-reader"), True)
        check("a qualified Related target under a basename collision uses that path's title",
              [k for k in _st_keys(res, "qualified-related-reader")
               if k in ("item10/ambiguous", "item11", "item18")], [])
        check("item 11 and item 18 diagnose against the qualified path's owner",
              ("Beta" in _st_msg(res, "wrong-qualified-reader", "item11"),
               'canonical target "Beta" at "b/foo.md"'
               in _st_msg(res, "wrong-qualified-reader", "item18")),
              (True, True))
        check("a repeated ambiguous alias gets no duplicate-removal finding",
              "item10/dup" in _st_keys(res, "alias-reader"), False)
        check("the ambiguous alias remains report-only instead",
              _st_msg(res, "alias-reader", "item10/ambiguous").count(
                  "claimed as an alias by multiple entries"), 2)

        # A known pathname does not establish an unreadable file's aliases.
        # The same uncertainty applies to valid YAML keys this small parser
        # does not support; neither case may turn a working alias into a prune.
        from unittest.mock import patch
        v_gap = os.path.join(tmp, "v2-alias-inventory-gap")
        hidden_text = _st_entry(
            "Hidden owner", "**Hidden owner** is a worked example.",
            aliases=('"hidden-alias"', '"shared-alias"'))
        hidden_path = _st_write(v_gap, "hidden-owner.md", hidden_text)
        _st_write(v_gap, "known-owner.md", _st_entry(
            "Known owner", "**Known owner** is a worked example.",
            aliases=('"known-alias"', '"shared-alias"'), type_="Invalid"))
        _st_write(v_gap, "alias-reader.md", _st_entry(
            "Alias reader", "**Alias reader** uses [[hidden-alias|Hidden owner]], "
            "[[known-alias|Known owner]], [[shared-alias|Shared]], "
            "[[shared-alias|Shared]], [[reader-alias|Alias reader]] and [[ghost]].",
            aliases=('"reader-alias"',), related="[[known-alias]]",
            parents=('"[[known-alias]]"',)))
        _st_write(v_gap, "file-reader.md", _st_entry(
            "File reader", "**File reader** uses [[KNOWN-OWNER|Known owner]] "
            "and [[known-owner|Known owner]].", related="[[known-owner]]"))
        _st_write(v_gap, "bare-reader.md", _st_entry(
            "Bare reader", "**Bare reader** uses Known owner in a comparison."))
        real_open = os.open
        def deny_alias_owner(path, *args, **kwargs):
            if os.fspath(path) == hidden_path:
                raise PermissionError(13, "synthetic denied read", hidden_path)
            return real_open(path, *args, **kwargs)
        with patch.object(os, "open", deny_alias_owner):
            unreadable_alias_res = scan(v_gap)
        _st_write(v_gap, "hidden-owner.md", hidden_text.replace('aliases:', '"aliases":'))
        quoted_alias_res = scan(v_gap)
        for label, gap_res, gap_item in (
                ("unreadable owner", unreadable_alias_res, "item0"),
                ("quoted alias key", quoted_alias_res, "item1")):
            check(label + " explains suppressed alias actions without aborting local QC",
                  ("Alias inventory is incomplete" in _st_msg(
                      gap_res, "hidden-owner", gap_item),
                   "item2/type-enum" in _st_keys(gap_res, "known-owner")),
                  (True, True))
            check(label + " cannot imply a dangling, canonical, self, duplicate or Related alias repair",
                  [key for key in _st_keys(gap_res, "alias-reader")
                   if key.startswith("item10/") or key == "item11"], [])
            check(label + " retains direct filename case, duplicate and Related checks",
                  [key for key in _st_keys(gap_res, "file-reader")
                   if key.startswith("item10/") or key == "item11"],
                  ["item10/case", "item10/dup", "item11"])
            check(label + " suppresses backfill and alias-parent canonicalization",
                  (gap_res["backfill_candidates"],
                   "resolves to" in _st_msg(gap_res, "alias-reader", "item2/parents-form"),
                   [(row["target"], row["reason"])
                    for row in gap_res["hierarchy_diagnostic"]["unresolved_parents"]
                    if row["slug"] == "alias-reader"]),
                  ([], False, [("known-alias", "unparsed")]))
            check(label + " suppresses unlinked_children and hub_footer",
                  (gap_res["hierarchy_diagnostic"]["unlinked_children"],
                   gap_res["hub_footer"]), ([], []))
        _st_write(v_gap, "hidden-owner.md", hidden_text)
        repaired_alias_res = scan(v_gap)
        check("repair and rescan restore unlinked_children through an alias parent",
              [row["slug"] for row in
               repaired_alias_res["hierarchy_diagnostic"]["unlinked_children"]],
              ["known-owner"])
        check("repair and rescan restore ordinary alias resolution, including real ambiguity",
              {"item10/alias", "item10/ambiguous", "item10/self", "item10/dangling", "item11"}
              <= set(_st_keys(repaired_alias_res, "alias-reader")), True)
        check("repair and rescan restore backfill despite unrelated field-value QC",
              any(row["slug"] == "bare-reader" and row["target"] == "known-owner"
                  for row in repaired_alias_res["backfill_candidates"]), True)

        # A duplicate portable basename is one resolution identity, but each
        # physical file still has its own body and must receive local QC. The
        # optional path is the only backward-compatible way to distinguish
        # those findings while retaining the public slug field.
        v_path = os.path.join(tmp, "v2-path-diagnostics")
        duplicate_clean = _st_entry(
            "Duplicate", "**Duplicate** is the clean physical owner.")
        _st_write(v_path, "a/duplicate.md", duplicate_clean)
        _st_write(v_path, "b/duplicate.md", duplicate_clean.replace(
            "type: Concept\n", "type: Model\n", 1))
        path_res = scan(v_path)
        path_type_rows = [
            (p["slug"], p.get("path"), p["message"])
            for p in path_res["problems"]
            if p["item"] == "item2/type-enum"
        ]
        check("duplicate basenames preserve the legacy slug-keyed inventory",
              path_res["inventory"], {"entries": 1, "slugs": ["duplicate"]})
        check("the second same-basename file receives its own local type lint",
              [(slug_value, path) for slug_value, path, _message
               in path_type_rows],
              [("duplicate", "b/duplicate.md")])
        check("that path-keyed type finding retains the enum diagnosis",
              len(path_type_rows) == 1
              and 'not one of the 15 canonical type values'
              in path_type_rows[0][2], True)
        check("ordinary findings keep the historical three-field shape",
              any("path" in p for p in res["problems"]
                  if p["slug"] == "hub"), False)

        # Alias inventory must retain every physical file, including the
        # second owner of a duplicate basename. Its aliases are real, but
        # slug-keyed repair plans cannot safely choose their destination.
        v_alias_path = os.path.join(tmp, "v2-duplicate-path-aliases")
        _st_write(v_alias_path, "a/duplicate.md", _st_entry(
            "First owner", "**First owner** describes the first file."))
        _st_write(v_alias_path, "b/duplicate.md", _st_entry(
            "Second owner", "**Second owner** describes the second file.",
            aliases=('"second-alias"', '"shared-surface"')))
        _st_write(v_alias_path, "unique-owner.md", _st_entry(
            "Unique owner", "**Unique owner** describes a separate file.",
            aliases=('"shared-surface"', '"unique-alias"')))
        _st_write(v_alias_path, "alias-reader.md", _st_entry(
            "Alias reader", "**Alias reader** uses [[second-alias]], "
            "[[second-alias]] and [[shared-surface]].",
            related="[[second-alias]]", parents=('"[[second-alias]]"',)))
        _st_write(v_alias_path, "bare-reader.md", _st_entry(
            "Bare reader", "**Bare reader** mentions shared surface here."))
        _st_write(v_alias_path, "qualified-reader.md", _st_entry(
            "Qualified reader", "**Qualified reader** uses "
            "[[b/duplicate|Second owner]] and [[unique-alias|Unique owner]].",
            related="[[b/duplicate|Second owner]]"))
        alias_path_res = scan(v_alias_path)
        check("secondary duplicate-file aliases cannot imply removal or rewriting",
              sorted({key for key in _st_keys(alias_path_res, "alias-reader")
                      if key.startswith("item10/") or key == "item11"}),
              ["item10/ambiguous"])
        check("every use of a duplicate-file alias remains report-only",
              _st_msg(alias_path_res, "alias-reader", "item10/ambiguous").count(
                  "preserve the link"), 4)
        check("duplicate-file alias parents keep uncertain ownership",
              [(row["target"], row["reason"])
               for row in alias_path_res["hierarchy_diagnostic"]["unresolved_parents"]
               if row["slug"] == "alias-reader"],
              [("second-alias", "ambiguous")])
        check("secondary duplicate-file aliases prevent arbitrary surface backfill",
              [row for row in alias_path_res["backfill_candidates"]
               if row["slug"] == "bare-reader"], [])
        check("duplicate-file aliases leave qualified paths and unrelated aliases usable",
              [key for key in _st_keys(alias_path_res, "qualified-reader")
               if key.startswith("item10/") or key in ("item11", "item18")],
              ["item10/alias"])
        # A qualified link or MOC bullet can open the second file of a
        # case-variant pair, whose slug is not the kept inventory key.
        v_case_root = os.path.join(tmp, "v2-case-variant-path")
        v_case = os.path.join(v_case_root, "Wiki")
        for rel in ("Kernel-density.md", "methods/kernel-density.md"):
            _st_write(v_case, rel, _st_entry(
                "Kernel density", "**Kernel density** smooths a histogram."))
        _st_write(v_case, "histogram.md", _st_entry(
            "Histogram", "**Histogram** bins data; a density estimate is "
            "smoother, as a [[methods/kernel-density|density estimate]] shows."))
        _st_write(v_case_root, "MOCs/statistics-moc.md",
                  "- [[Wiki/methods/kernel-density|Kernel density]]\n"
                  "  - [[Wiki/histogram|Histogram]]\n")
        check("a qualified link or MOC bullet to a case-variant duplicate "
              "stays ambiguous instead of aborting the scan",
              "item5" in _st_keys(scan(v_case), "kernel-density"), True)

        # A case-sensitive filesystem can hold two entries whose only pathname
        # difference is the Markdown extension's case. Link identity correctly
        # folds that suffix, but physical QC must still retain both files.
        v_ext = os.path.join(tmp, "v2-extension-case")
        os.makedirs(v_ext)
        ext_body = _st_entry(
            "Extension", "**Extension** is the extension-case fixture.")
        lower_ext = os.path.join(v_ext, "extension.md")
        upper_ext = os.path.join(v_ext, "extension.MD")
        with open(lower_ext, "w", encoding="utf-8") as fh:
            fh.write(ext_body)
        upper_body = ext_body.replace("type: Concept\n", "type: Model\n", 1)
        try:
            descriptor = os.open(
                upper_ext, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            descriptor = None
        if descriptor is not None:
            with os.fdopen(descriptor, "w", encoding="utf-8") as fh:
                fh.write(upper_body)
            ext_res = scan(v_ext)
        else:
            # A case-folding host cannot hold the twin. Keep its body outside
            # the Wiki folder and add the second spelling to walk, stat and
            # open, so the scan still reads two physical files.
            twin_real = os.path.join(tmp, "v2-extension-case-twin")
            with open(twin_real, "w", encoding="utf-8") as fh:
                fh.write(upper_body)
            real_walk, real_stat, real_open = os.walk, os.stat, os.open

            def twin_path(path):
                return twin_real if path == upper_ext else path

            def twin_walk(root, *args, **kwargs):
                for dirpath, dirnames, filenames in real_walk(
                        root, *args, **kwargs):
                    if os.path.normpath(dirpath) == os.path.normpath(v_ext):
                        filenames = sorted(set(filenames) | {"extension.MD"})
                    yield dirpath, dirnames, filenames

            with patch.object(os, "walk", twin_walk), \
                    patch.object(os, "stat", lambda path, *args, **kwargs:
                                 real_stat(twin_path(path), *args, **kwargs)), \
                    patch.object(os, "open", lambda path, *args, **kwargs:
                                 real_open(twin_path(path), *args, **kwargs)):
                ext_res = scan(v_ext)
        extension_case_observed = [
            p.get("path") for p in ext_res["problems"]
            if p["item"] == "item2/type-enum"
        ]
        check("extension-case twins retain separate physical QC records "
              "(simulated where the filesystem folds case)",
              (len({_entry_physical_key(v_ext, lower_ext),
                    _entry_physical_key(v_ext, upper_ext)}),
               extension_case_observed),
              (2, ["extension.MD"]))

        # Resolution folds the whole path for portability, but the repair must
        # restore directory spelling as well as the basename. Looking only at
        # file_record["slug"] let [[a/foo]] silently survive beside A/foo.md.
        v_dir_case = os.path.join(tmp, "v2-qualified-directory-case")
        _st_write(v_dir_case, "A/foo.md", _st_entry(
            "Foo", "**Foo** is the qualified-directory fixture."))
        _st_write(v_dir_case, "wrong-path-case.md", _st_entry(
            "Wrong path case", "**Wrong path case** links "
            "[[a/foo|Foo]] through the wrong directory case."))
        _st_write(v_dir_case, "exact-path-case.md", _st_entry(
            "Exact path case", "**Exact path case** links "
            "[[A/foo|Foo]] through the on-disk path."))
        dir_case_res = scan(v_dir_case)
        check("qualified link case checks every on-disk path component",
              ("item10/case" in _st_keys(dir_case_res, "wrong-path-case"),
               '"A/foo"' in _st_msg(
                   dir_case_res, "wrong-path-case", "item10/case"),
               "item10/case" in _st_keys(
                   dir_case_res, "exact-path-case")),
              (True, True, False))

        # Different directories let this fixture run even on a case-insensitive
        # filesystem. Their basenames still share the plugin's portable case /
        # Unicode identity, so bare resolution is ambiguous while each fully
        # qualified path remains usable.
        v_case = os.path.join(tmp, "v2-portable-paths")
        _st_write(v_case, "a/Case-Twin.md", _st_entry(
            "Case twin", "**Case twin** is the first portable owner."))
        _st_write(v_case, "b/case-twin.md", _st_entry(
            "Case twin", "**Case twin** is the second portable owner."))
        _st_write(v_case, "portable-reader.md", _st_entry(
            "Portable reader", "**Portable reader** distinguishes "
            "[[a/Case-Twin|Case twin]] from [[b/case-twin|Case twin]], while "
            "[[case-twin|Case twin]] has no unique path."))
        case_res = scan(v_case)
        check("case-equivalent basenames retain distinct qualified owners",
              ("item10/dangling" in _st_keys(case_res, "portable-reader"),
               "item10/case" in _st_keys(case_res, "portable-reader"),
               _st_msg(case_res, "portable-reader", "item10/ambiguous").count(
                   "multiple same-basename paths")),
              (False, False, 1))
        check("portable-owner diagnostics carry their exact physical paths",
              sorted({p.get("path") for p in case_res["problems"]
                      if p["slug"] in ("Case-Twin", "case-twin")}),
              ["a/Case-Twin.md", "b/case-twin.md"])

        # An NFD filename (as Finder often writes it) and an NFC link share
        # one portable identity: the link resolves and is only respelled.
        v_nfd = os.path.join(tmp, "v2-unicode-forms")
        _st_write(v_nfd, "poincaré-conjecture.md", _st_entry(
            "Poincaré conjecture",
            "**Poincaré conjecture** is a worked example."))
        _st_write(v_nfd, "nfc-reader.md", _st_entry(
            "Nfc reader", "**Nfc reader** links "
            "[[poincaré-conjecture|Poincaré conjecture]]."))
        nfd_res = scan(v_nfd)
        check("an NFC link to an NFD filename is item10/case, never a dangler",
              ("item10/dangling" in _st_keys(nfd_res, "nfc-reader"),
               "item10/case" in _st_keys(nfd_res, "nfc-reader")),
              (False, True))

        # A real note outside Wiki/ and MOCs/ resolves in Obsidian by path or
        # basename. It is reported as a non-entry and never unlinked as a
        # dangler, retargeted to an alias or counted as a duplicate entry.
        v_notes = os.path.join(tmp, "v2-vault-notes")
        os.makedirs(os.path.join(v_notes, ".obsidian"))
        for _note in ("Articles/Doe_X_2025.md", "People/Ada Lovelace.md",
                      "People/turing-note.md", "Articles/variance.md"):
            _st_write(v_notes, _note, "A note outside the Wiki.\n")
        w_notes = os.path.join(v_notes, "Wiki")
        _st_write(w_notes, "turing-machine.md", _st_entry(
            "Turing machine", "**Turing machine** is a worked example.",
            aliases=('"turing-note"',)))
        _st_write(w_notes, "note-reader.md", _st_entry(
            "Note reader", "**Note reader** cites "
            "[[Articles/Doe_X_2025|Doe 2025]], [[People/Ada Lovelace|Ada]], "
            "[[Ada Lovelace]], [[Doe_X_2025.md|the note]], "
            "[[turing-note|Turing]] and [[nowhere]]. It names "
            "[[Ada Lovelace]] again."))
        # A body or Related link drops an explicit .md suffix, and a path
        # that no other vault file with the basename needs.
        _st_write(w_notes, "mean.md", _st_entry(
            "Mean", "**Mean** is a worked example."))
        _st_write(w_notes, "variance.md", _st_entry(
            "Variance", "**Variance** is a worked example."))
        for _slug, _link, _footer in (
                ("md-reader", "[[mean.md|mean]]", None),
                ("path-reader", "[[Wiki/mean|mean]]", None),
                ("footer-reader", "the mean", "[[Wiki/mean.md|Mean]]"),
                ("shared-reader", "[[Wiki/variance|variance]]", None),
                ("shared-md-reader", "[[Wiki/variance.md|variance]]", None)):
            _title = _slug.replace("-", " ").capitalize()
            _st_write(w_notes, _slug + ".md", _st_entry(
                _title, "**%s** uses %s." % (_title, _link),
                related=_footer))
        notes_res = scan(w_notes)
        check("links to vault notes outside Wiki/ are item10/non-entry, "
              "never dangling, alias or dup",
              (_st_msg(notes_res, "note-reader", "item10/non-entry").count(
                  "outside Wiki/, not to an entry"),
               [_name in _st_msg(notes_res, "note-reader", "item10/non-entry")
                for _name in ('"Articles/Doe_X_2025.md"',
                              '"People/Ada Lovelace.md"',
                              '"People/turing-note.md"')],
               [k for k in _st_keys(notes_res, "note-reader")
                if k in ("item10/dangling", "item10/alias", "item10/dup")],
               _st_msg(notes_res, "note-reader", "item10/dangling")),
              (6, [True, True, True], ["item10/dangling"],
               'wikilink target "nowhere" does not resolve'))
        check("an unneeded .md suffix or Wiki/ path is item10/case naming "
              "the bare slug; a path a same-named vault note needs is kept",
              [_st_msg(notes_res, _slug, "item10/case").split(
                  "rewrite the target to ")[-1].split(",")[0]
               for _slug in ("md-reader", "path-reader", "footer-reader",
                             "shared-reader", "shared-md-reader")],
              ['"mean"', '"mean"', '"mean"', "", '"Wiki/variance"'])
        # Beside a same-named note outside Wiki/, every body or Related target
        # the scan supplies is the qualified path (CONVENTIONS §6).
        v_outside = os.path.join(tmp, "v2-outside-twin")
        os.makedirs(os.path.join(v_outside, ".obsidian"))
        _st_write(v_outside, "Articles/variance.md", "An outside note.\n")
        w_outside = os.path.join(v_outside, "Wiki")
        _st_write(w_outside, "mean.md", _st_entry(
            "Mean", "**Mean** is a worked example."))
        _st_write(w_outside, "variance.md", _st_entry(
            "Variance", "**Variance** is a worked example.",
            aliases=('"var-alias"',), parents=('"[[mean]]"',)))
        for _slug, _prose in (
                ("twin-mention", "depends on the variance of the data"),
                ("twin-alias", "uses [[var-alias|variance]]"),
                ("twin-md", "uses [[variance.md|variance]]")):
            _title = _slug.replace("-", " ").capitalize()
            _st_write(w_outside, _slug + ".md", _st_entry(
                _title, "**%s** %s." % (_title, _prose)))
        res = scan(w_outside)
        check("beside an outside same-named note, backfill, alias, .md and "
              "unlinked-child targets are all the qualified path",
              ([row["target"] for row in res["backfill_candidates"]
                if row["slug"] == "twin-mention"],
               '"[[Wiki/variance|variance]]"' in _st_msg(
                   res, "twin-alias", "item10/alias"),
               _st_msg(res, "twin-md", "item10/case").split(
                   "rewrite the target to ")[-1].split(",")[0],
               [row["unlinked"] for row in
                res["hierarchy_diagnostic"]["unlinked_children"]
                if row["slug"] == "mean"]),
              (["Wiki/variance"], True, '"Wiki/variance"',
               [["Wiki/variance"]]))
        # Obsidian indexes a symlinked folder, so its same-named note keeps a
        # needed Wiki/ path. A loop and a link back into the vault add nothing.
        v_linked = os.path.join(tmp, "v2-symlinked-outside")
        os.makedirs(os.path.join(v_linked, ".obsidian"))
        _st_write(os.path.join(tmp, "v2-shared"), "mean.md", "A shared note.\n")
        _st_write(v_linked, "Articles/doe.md", "An outside note.\n")
        w_linked = os.path.join(v_linked, "Wiki")
        _st_write(w_linked, "mean.md", _st_entry(
            "Mean", "**Mean** is a worked example."))
        _st_write(w_linked, "median.md", _st_entry(
            "Median", "**Median** is unlike the [[Wiki/mean|mean]]."))
        _linked_want = ({"articles/doe": ["Articles/doe.md"],
                         "shared/mean": ["Shared/mean.md"]}, True, [])
        try:
            os.symlink(os.path.join(tmp, "v2-shared"),
                       os.path.join(v_linked, "Shared"))
            os.symlink(os.path.join(tmp, "v2-shared"),
                       os.path.join(tmp, "v2-shared", "loop"))
            os.symlink("Articles", os.path.join(v_linked, "Aa-alias"))
        except (OSError, NotImplementedError, AttributeError):
            _linked_seen = _linked_want
        else:
            _linked_paths, _, _linked_complete = vault_note_index(
                v_linked, w_linked)
            _linked_seen = (_linked_paths, _linked_complete,
                            _st_keys(scan(w_linked), "median"))
        check("a note in a symlinked outside folder owns its basename and "
              "keeps the Wiki/ path (skipped where symlink creation is "
              "unavailable)", _linked_seen, _linked_want)

        # ------------------------------------------------------------------
        # 3. item 8 -- tag aliases, case variants, and the duplicate check
        # ------------------------------------------------------------------
        v = os.path.join(tmp, "v3")
        _st_write(v, "aliased.md", _st_entry(
            "Aliased", "**Aliased** is a worked example.",
            tags=('"#ml"', '"#machine-learning"')))
        _st_write(v, "abbrev.md", _st_entry(
            "Abbrev", "**Abbrev** is a worked example.", tags=('"#ml"',)))
        _st_write(v, "cased.md", _st_entry(
            "Cased", "**Cased** is a worked example.", tags=('"#Machine-Learning"',)))
        _st_write(v, "twice.md", _st_entry(
            "Twice", "**Twice** is a worked example.",
            tags=('"#statistics"', '"#statistics"')))
        _st_write(v, "offenum.md", _st_entry(
            "Offenum", "**Offenum** is a worked example.", tags=('"#astrology"',)))
        _st_write(v, "flow-tags.md", _st_entry(
            "Flow tags", "**Flow tags** is a worked example.").replace(
            'tags:\n  - "#statistics"\n', 'tags: ["#statistics"]\n'))
        _st_write(v, "scalar-tags.md", _st_entry(
            "Scalar tags", "**Scalar tags** is a worked example.").replace(
            'tags:\n  - "#statistics"\n', 'tags: "#statistics"\n'))
        _st_write(v, "blank-tags.md", _st_entry(
            "Blank tags", "**Blank tags** is a worked example.").replace(
            'tags:\n  - "#statistics"\n', 'tags:\n'))
        _st_write(v, "twocards.md", _st_entry(
            "Twocards", "**Twocards** is a worked example.",
            tags=('"#physics"',)).replace(
            "??\nTwocards\n",
            "??\nTwocards\n\nA Twocards example illustrates another notion.\n"
            "??\nSecond idea\n"))
        _st_write(v, "no-primary-card.md", _st_entry(
            "No primary card", "**No primary card** is a worked example.",
            tags=('"#physics"',)).replace(
            "??\nNo primary card\n",
            "??\nFirst other idea\n\nAnother notion is stated here.\n"
            "??\nSecond other idea\n"))
        _st_write(v, "near-primary-card.md", _st_entry(
            "Near primary card", "**Near primary card** is a worked example.",
            tags=('"#physics"',)).replace(
            "??\nNear primary card\n",
            "??\nnear primary card\n\nAnother notion is stated here.\n"
            "??\nOther idea\n"))
        _st_write(v, "joined-cards.md", _st_entry(
            "Joined cards", "**Joined cards** is a worked example.",
            tags=()).replace(
            "??\nJoined cards\n",
            "??\nJoined cards\nA second definition.\n??\nSecond term\n"))
        _st_write(v, "ordinary-line4-comment.md", _st_entry(
            "Ordinary line4 comment",
            "**Ordinary line4 comment** is a worked example.",
            tags=()).replace(
            "??\nOrdinary line4 comment\n",
            "??\nOrdinary line4 comment\n<!--ordinary comment-->\n"))
        _st_write(v, "space-padded-card.md", _st_entry(
            "Space padded card", "**Space padded card** is a worked example.",
            tags=()).replace("## Flashcards\n\n", "## Flashcards\n   \n"))
        _st_write(v, "two-sentence-card.md", _st_entry(
            "Two sentence card", "**Two sentence card** is a worked example.",
            tags=())
            .replace("The idea this entry is about, stated once.",
                     "One identifying statement. Another statement."))
        _st_write(v, "quoted-period-card.md", _st_entry(
            "Quoted period card", "**Quoted period card** is a worked example.",
            tags=()).replace(
                "The idea this entry is about, stated once.",
                'The label Hooke called "cells."'))
        _st_write(v, "inline-math-period-card.md", _st_entry(
            "Inline math period card",
            "**Inline math period card** is a worked example.",
            tags=()).replace(
                "The idea this entry is about, stated once.",
                r"The value $f(t)=\text{e.g. A or B}$ applies under a stated "
                "condition."))
        _st_write(v, "markdown-card.md", _st_entry(
            "Markdown card", "**Markdown card** is a worked example.",
            tags=()).replace(
                "The idea this entry is about, stated once.",
                "A [linked](target) definition."))
        _st_write(v, "reference-card.md", _st_entry(
            "Reference card", "**Reference card** is a worked example.",
            tags=()).replace(
                "The idea this entry is about, stated once.",
                "A [linked][target] definition."))
        _st_write(v, "comment-card.md", _st_entry(
            "Comment card", "**Comment card** is a worked example.",
            tags=()).replace(
                "The idea this entry is about, stated once.",
                "An <!-- hidden --> definition."))
        _st_write(v, "obsidian-comment-card.md", _st_entry(
            "Obsidian comment card",
            "**Obsidian comment card** is a worked example.", tags=()).replace(
                "The idea this entry is about, stated once.",
                "An %%50% hidden%% definition."))
        _st_write(v, "reference-definition-card.md", _st_entry(
            "Reference definition card",
            "**Reference definition card** is a worked example.", tags=()).replace(
                "The idea this entry is about, stated once.",
                "[Source]:https://example.com."))
        _st_write(v, "leading-comment-card.md", _st_entry(
            "Leading comment card",
            "**Leading comment card** is a worked example.", tags=()).replace(
                "The idea this entry is about, stated once.",
                "<!--SR:misplaced-->\nA complete definition."))
        _st_write(v, "display-math-card.md", _st_entry(
            "Display math card", "**Display math card** is a worked example.",
            tags=()).replace(
                "The idea this entry is about, stated once.",
                "A $$x=1$$ definition."))
        _st_write(v, "block-markdown-card.md", _st_entry(
            "Block Markdown card",
            "**Block Markdown card** is a worked example.", tags=()).replace(
                "The idea this entry is about, stated once.",
                "# A heading definition."))
        _st_write(v, "unmatched-math-card.md", _st_entry(
            "Unmatched math card",
            "**Unmatched math card** is a worked example.", tags=()).replace(
                "The idea this entry is about, stated once.",
                "A quantity uses $x."))
        res = scan(v)
        check("#ml is reported as an abbreviation with its expansion named",
              'rewrite as "#machine-learning"' in _st_msg(res, "abbrev", "item8"), True)
        check("...and on its own it is NOT a duplicate",
              "tagged more than once" in _st_msg(res, "abbrev", "item8"), False)
        check("#ml beside #machine-learning IS a duplicate (item 8's own fix "
              "creates it otherwise)",
              "tagged more than once" in _st_msg(res, "aliased", "item8"), True)
        check("...and the duplicate message names both spellings",
              '"#ml"' in _st_msg(res, "aliased", "item8")
              and '"#machine-learning"' in _st_msg(res, "aliased", "item8"), True)
        check("a case variant of an enum slug is reported",
              "case variant" in _st_msg(res, "cased", "item8"), True)
        check("...with the lowercase enum slug as the fix",
              'rewrite as "#machine-learning"' in _st_msg(res, "cased", "item8"), True)
        check("an exact duplicate tag is still a duplicate",
              "tagged more than once" in _st_msg(res, "twice", "item8"), True)
        check("...and every duplicate names the CANONICAL discipline, not the "
              "raw spelling",
              (('discipline "#machine-learning" tagged more than once'
                in _st_msg(res, "aliased", "item8")),
               ('discipline "#statistics" tagged more than once'
                in _st_msg(res, "twice", "item8"))), (True, True))
        check("tag_canonical expands an alias and folds case, and leaves an "
              "off-enum slug alone",
              [tag_canonical(t) for t in ("ml", "Machine-Learning",
                                          "machine-learning", "astrology")],
              ["machine-learning", "machine-learning", "machine-learning",
               "astrology"])
        check("an off-enum tag is reported and lands in off_enum_tags",
              ("not one of the 28" in _st_msg(res, "offenum", "item8"),
               sorted(res["off_enum_tags"])), (True, ["astrology", "ml"]))
        check("flow-form tags are rejected even when every value is valid",
              "flow-list syntax" in _st_msg(res, "flow-tags", "item8"), True)
        check("scalar tags are rejected even when the value is valid",
              "scalar syntax" in _st_msg(res, "scalar-tags", "item8"), True)
        check("a blank block-form tags key requires an explicit discipline or sole misc tag",
              _st_keys(res, "blank-tags"), ["item8"])
        check("the tag census counts the enum tags",
              res["discipline_tags"].get("statistics"), 3)
        _twocards = _st_msg(res, "twocards", "item19")
        check("a second flashcard is a fixable finding: remove it and quote "
              "it in the report",
              ("holds 2 cards: " in _twocards,
               "remove every other card" in _twocards,
               "verbatim, attachments included, in the report" in _twocards),
              (True, True, True))
        check("a second flashcard is never report-only or preserved",
              [word in _twocards for word in ("report-only", "legacy",
                                              "preserve every card")],
              [False] * 3)
        check("an extra card draws no line-3 term finding: it is removed, "
              "never repointed",
              "line 3 is" in _twocards, False)
        _no_primary = _st_msg(res, "no-primary-card", "item19").split(" | ")
        check("several cards with no primary answer get one finding, not one per card",
              ([msg for msg in _no_primary if " line 3 is" in msg],
               sum("no card carries the primary answer" in msg
                   for msg in _no_primary)),
              ([], 1))
        check("with no definition card, the first card is rewritten into it "
              "and the rest removed",
              sum(msg.endswith("rewrite the first card into the definition "
                               "card, keeping its attachments, and remove "
                               "every other card") for msg in _no_primary), 1)
        check("a near-miss primary card gets its own line-3 fault; the extra card none",
              [msg[:msg.index(" line 3")] for msg in
               _st_msg(res, "near-primary-card", "item19").split(" | ")
               if " line 3 is" in msg],
              ["card 1"])
        # A notation parenthetical such as SU(2) is part of the name unless the
        # shared slugify rule calls it a disambiguator; no private regex here.
        _v_notation = os.path.join(tmp, "v-notation-title")
        _st_write(_v_notation, "su2.md", _st_entry(
            "SU(2)", "**SU(2)** is a worked example.", card="SU(2)"))
        _notation_res = scan(_v_notation)
        _notation_split = has_parenthetical("SU(2)")
        check("opener and card-term checks follow the shared disambiguator rule",
              ("item16" in _st_keys(_notation_res, "su2"),
               "line 3 is" in _st_msg(_notation_res, "su2", "item19")),
              (_notation_split, _notation_split))
        check("a second card joined without a blank line is malformed visible content",
              "visible lines" in _st_msg(res, "joined-cards", "item19"), True)
        check("a non-SR line-four HTML comment is malformed visible content",
              "visible lines" in _st_msg(
                  res, "ordinary-line4-comment", "item19"), True)
        check("whitespace-only padding after the heading parses like a blank line",
              "item19" in _st_keys(res, "space-padded-card"), False)
        check("an extra card may name the primary without an answer leak",
              "leaks the answer" in _st_msg(res, "twocards", "item19"), False)
        check("flashcard line 1 must be one sentence",
              "roughly 2 sentences" in _st_msg(
                  res, "two-sentence-card", "item19"), True)
        check("a period inside closing quotation marks terminates a card sentence",
              _st_msg(res, "quoted-period-card", "item19"), "")
        check("punctuation inside inline LaTeX does not split a card sentence",
              _st_msg(res, "inline-math-period-card", "item19"), "")
        check("Markdown link syntax is rejected on card line 1",
              "Markdown link/image" in _st_msg(
                  res, "markdown-card", "item19"), True)
        check("Markdown reference-link syntax is rejected on card line 1",
              "Markdown reference link/image" in _st_msg(
                  res, "reference-card", "item19"), True)
        check("an inline HTML comment is rejected on card line 1",
              "HTML" in _st_msg(res, "comment-card", "item19"), True)
        check("an Obsidian comment is rejected on card line 1",
              "Obsidian comment" in _st_msg(
                  res, "obsidian-comment-card", "item19"), True)
        check("a Markdown reference definition is rejected on card line 1",
              "Markdown reference definition" in _st_msg(
                  res, "reference-definition-card", "item19"), True)
        check("a review comment before card line 1 remains visible and invalid",
              "item19" in _st_keys(res, "leading-comment-card"), True)
        check("display LaTeX is rejected on card line 1",
              "display LaTeX" in _st_msg(
                  res, "display-math-card", "item19"), True)
        check("block Markdown is rejected on card line 1",
              "block Markdown" in _st_msg(
                  res, "block-markdown-card", "item19"), True)
        check("unmatched inline LaTeX is rejected on card line 1",
              "unmatched LaTeX delimiter" in _st_msg(
                  res, "unmatched-math-card", "item19"), True)

        # ------------------------------------------------------------------
        # 4. near-duplicate surfaces + the backfill worklist
        # ------------------------------------------------------------------
        check("plural_surface inflects the HEAD token, not the whole title",
              [plural_surface(t) for t in
               ("Confusion matrix", "Hypothesis", "ROC curve", "Analysis")],
              ["Confusion matrices", "Hypotheses", "ROC curves", "Analyses"])
        _dotted_index, _dotted_words = _index_surfaces({
            "e. coli": "escherichia-coli"})
        check("dotted scientific abbreviations remain backfill surfaces",
              [hit[2:] for hit in _scan_surface_spans(
                  "The *E. coli* strain grows.",
                  _dotted_index, _dotted_words)],
              [("e. coli", "E. coli")])
        _span_index, _span_words = _index_surfaces({
            "machine learning": "machine-learning",
            "gradient descent": "gradient-descent"})
        check("a dotted capital I before a surface keeps later offsets aligned",
              [hit[:3] for hit in _scan_surface_spans(
                  "İzmir hosts a machine learning lab using gradient descent.",
                  _span_index, _span_words)],
              [(14, 30, "machine learning"), (41, 57, "gradient descent")])
        v = os.path.join(tmp, "v4")
        _st_write(v, "confusion-matrix.md",
                  _st_entry("Confusion matrix", "**Confusion matrix** is a worked example.",
                            card="Confusion matrix"))
        _st_write(v, "hypothesis.md",
                  _st_entry("Hypothesis", "**Hypothesis** is a worked example.",
                            card="Hypothesis"))
        _st_write(v, "mentions.md", _st_entry(
            "Mentions",
            "**Mentions** is a worked example. Several confusion matrices are "
            "compared, and competing hypotheses are listed."))
        _st_write(v, "unlinkable.md", _st_entry(
            "Unlinkable",
            "**Unlinkable** is a worked example with nothing linkable in prose.\n\n"
            "| Metric | Note |\n|---|---|\n| Confusion matrix | inside a table cell |\n\n"
            "```\nConfusion matrix inside a fenced listing\n```\n\n"
            "![[figure.png]]\n*A confusion matrix, in a caption.*"))
        _st_write(v, "already.md", _st_entry(
            "Already",
            "**Already** is a worked example that already links "
            "[[confusion-matrix|Confusion matrix]] once, and names confusion "
            "matrices again in bare text afterwards."))
        _st_write(v, "presentation-only.md", _st_entry(
            "Presentation only",
            "**Presentation only** is a worked example with no prose mention.\n\n"
            "## Confusion matrix\n\n"
            "![Confusion matrix](https://example.test/plot.png)\n"
            "*A diagnostic plot.*\n\n"
            "[Confusion matrix](https://example.test/definition) and "
            "[Confusion matrix][cm] are existing Markdown links.\n\n"
            "[cm]: https://example.test/reference"))
        _st_write(v, "presentation-before-prose.md", _st_entry(
            "Presentation before prose",
            "**Presentation before prose** introduces an exhibit.\n\n"
            "![Confusion matrix](https://example.test/plot.png)\n"
            "*A diagnostic plot.*\n\n"
            "A confusion matrix then supports the prose claim."))
        res = scan(v)
        pairs = sorted((b["slug"], b["target"]) for b in res["backfill_candidates"])
        check("an irregular plural in prose is a backfill candidate",
              ("mentions", "confusion-matrix") in pairs
              and ("mentions", "hypothesis") in pairs, True)
        check("...and the surface recorded is the plural actually found",
              sorted(b["surface"] for b in res["backfill_candidates"]
                     if b["slug"] == "mentions"),
              ["confusion matrices", "hypotheses"])
        check("a mention only inside a TABLE ROW is not proposed",
              ("unlinkable", "confusion-matrix") in pairs, False)
        check("a mention only inside a FENCED BLOCK is not proposed",
              [b for b in res["backfill_candidates"] if b["slug"] == "unlinkable"], [])
        check("an entry that already links the target is not proposed",
              ("already", "confusion-matrix") in pairs, False)
        check("headings, image alt text, and existing Markdown-link labels "
              "are not new wikilink surfaces",
              [b for b in res["backfill_candidates"]
               if b["slug"] == "presentation-only"], [])
        check("an unlinkable image-alt occurrence cannot hide a later prose "
              "backfill candidate",
              [(b["target"], b["surface"])
               for b in res["backfill_candidates"]
               if b["slug"] == "presentation-before-prose"],
              [("confusion-matrix", "confusion matrix")])
        check("nothing in this vault is a collision candidate",
              res["collision_candidates"], [])
        # ...but a real plural pair sitting in the vault still fires probe (c),
        # which is the half CONVENTIONS.md 9 gives to this scanner alone.
        v = os.path.join(tmp, "v4b")
        _st_write(v, "roc-curve.md",
                  _st_entry("ROC curve", "**ROC curve** is a worked example.",
                            card="ROC curve"))
        _st_write(v, "roc-curves.md",
                  _st_entry("ROC curves", "**ROC curves** is a worked example.",
                            card="ROC curves"))
        res4b = scan(v)
        check("a plural pair already in the vault is a collision candidate",
              [(c["a"], c["b"], c["probe"]) for c in res4b["collision_candidates"]],
              [("roc-curve", "roc-curves", "plural")])

        # Probe (f) uses the exact same shared stem key as wiki-build, and it
        # runs only after the more specific probes have had first claim.
        v = os.path.join(tmp, "v4c")
        for name, title in (("masked-language-model", "Masked language model"),
                            ("masked-language-modeling", "Masked language modeling")):
            _st_write(v, name + ".md", _st_entry(
                title, "**%s** is a worked example." % title, card=title))
        res4c = scan(v)
        check("a noun/gerund pair already in the vault fires shared probe (f)",
              [(c["a"], c["b"], c["probe"])
               for c in res4c["collision_candidates"]],
              [("masked-language-model", "masked-language-modeling",
                "stem-morphology")])

        # A shared exact identifier is one `exact` row per owner pair, never
        # also a plural, hyphenation or word-order row.
        v = os.path.join(tmp, "v4d")
        _st_write(v, "recall.md", _st_entry(
            "Recall", "**Recall** is a worked example."))
        _st_write(v, "true-positive-rate.md", _st_entry(
            "True positive rate", "**True positive rate** is a worked example.",
            aliases=('"tpr"', '"recall"')))
        check("an alias equal to another entry's slug is one exact collision "
              "whose detail is the shared identifier",
              [(c["a"], c["b"], c["probe"], c["detail"])
               for c in scan(v)["collision_candidates"]],
              [("true-positive-rate", "recall", "exact", "recall")])
        v = os.path.join(tmp, "v4e")
        for name in ("alpha-term", "beta-term", "gamma-term"):
            title = name.replace("-", " ").capitalize()
            _st_write(v, name + ".md", _st_entry(
                title, "**%s** is a worked example." % title,
                aliases=('"shared-name"',)))
        check("three entries sharing one alias are three exact rows and "
              "nothing else",
              sorted((c["a"], c["b"], c["probe"])
                     for c in scan(v)["collision_candidates"]),
              [("beta-term", "alpha-term", "exact"),
               ("gamma-term", "alpha-term", "exact"),
               ("gamma-term", "beta-term", "exact")])

        v = os.path.join(tmp, "v4-duplicate-sentence")
        repeated = ("With a suitable learning rate, gradient descent approaches "
                    "the minimum cost whenever a finite minimizer exists.")
        _st_write(v, "optimization-a.md", _st_entry(
            "Optimization A", "**Optimization A** is a worked example. " + repeated,
            card="Optimization A"))
        _st_write(v, "optimization-b.md", _st_entry(
            "Optimization B", "**Optimization B** is another worked example. "
            + repeated.replace("minimum cost", "*minimum cost*"),
            card="Optimization B"))
        abbreviated = (
            "B. F. Skinner described a long U.S. laboratory procedure, e.g. "
            "presenting a signal before reinforcement, to compare behavior "
            "across carefully controlled experimental sessions.")
        _st_write(v, "abbreviation-a.md", _st_entry(
            "Abbreviation A", "**Abbreviation A** is a worked example. "
            + abbreviated, card="Abbreviation A"))
        _st_write(v, "abbreviation-b.md", _st_entry(
            "Abbreviation B", "**Abbreviation B** is another worked example. "
            + abbreviated, card="Abbreviation B"))
        res4d = scan(v)
        check("a long exact sentence copied across entries is an ownership candidate",
              [(slug, "item9/duplicate-sentence" in _st_keys(res4d, slug))
               for slug in ("optimization-a", "optimization-b")],
              [("optimization-a", True), ("optimization-b", True)])
        check("presentation markup is ignored by duplicate-sentence normalization",
              "optimization-b" in _st_msg(
                  res4d, "optimization-a", "item9/duplicate-sentence"), True)
        check("abbreviations and initials do not break duplicate sentences",
              [(slug, "item9/duplicate-sentence" in _st_keys(res4d, slug))
               for slug in ("abbreviation-a", "abbreviation-b")],
              [("abbreviation-a", True), ("abbreviation-b", True)])
        table_after_display = (
            "A short introduction.\n\n$$\nx = 1\ny = 2\n$$\n\n"
            "Claim | Explanation\n--- | ---\nvalue | This deliberately long table "
            "sentence has more than twelve words and must remain excluded from "
            "duplicate prose ownership review.\n*Values in the fixture.*")
        check("display masking preserves table-span line offsets",
              duplicate_sentence_surfaces(
                  table_after_display, markdown_tables(table_after_display)[1]),
              [])
        code_a = ("This deliberately long sentence explains that the pipeline "
                  "calls `fit()` before it records the resulting model for "
                  "later evaluation and comparison.")
        code_b = code_a.replace("`fit()`", "`transform()`")
        check("different inline-code payloads do not collapse",
              [surface for surface, _ in duplicate_sentence_surfaces(code_a)]
              == [surface for surface, _ in duplicate_sentence_surfaces(code_b)],
              False)
        check("duplicate evidence keeps readable inline code",
              duplicate_sentence_surfaces(code_a)[0][1].find("`fit()`") >= 0,
              True)
        math_a = ("This deliberately long sentence says the resulting score is "
                  "$x+y$ before the system records it for later evaluation "
                  "and comparison.")
        math_b = math_a.replace("$x+y$", "$x-y$")
        check("different inline-math operators do not collapse",
              [surface for surface, _ in duplicate_sentence_surfaces(math_a)]
              == [surface for surface, _ in duplicate_sentence_surfaces(math_b)],
              False)
        check("duplicate evidence keeps readable inline math",
              duplicate_sentence_surfaces(math_a)[0][1].find("$x+y$") >= 0,
              True)
        step_sentence = (
            "This deliberately long sentence explains how the weighted error "
            "counts the weight that sits on misclassified examples.")
        check("a display indented under 10. is masked like a top-level one, "
              "so the step's sentence matches its top-level copy",
              [surface for _normalized, surface in duplicate_sentence_surfaces(
                  "10. Compute it.\n\n    $$\n    e = 1\n    $$\n\n    "
                  + step_sentence)],
              [surface for _normalized, surface in duplicate_sentence_surfaces(
                  "Compute it.\n\n$$\ne = 1\n$$\n\n" + step_sentence)])

        # special-titles.md's cross-domain corpus, its words and its phrases,
        # is the scanner's mechanical minimum.  A single fixture over every
        # term prevents additions to one copied list from silently escaping
        # both the filename and backfill gates.
        v = os.path.join(tmp, "v4d")
        _phrase_slugs = {phrase.replace(" ", "-") for phrase in CROSS_DOMAIN_PHRASES}
        _corpus = sorted(COMMON_NOUNS | CROSS_DOMAIN_PHRASES)
        for term in _corpus:
            title = term.capitalize()
            _st_write(v, term.replace(" ", "-") + ".md", _st_entry(
                title, "**%s** is a worked example." % title, card=title))
        _st_write(v, "reader.md", _st_entry(
            "Reader", "**Reader** compares " + ", ".join(_corpus) + "."))
        res4d = scan(v)
        _bare = {p["slug"] for p in res4d["problems"]
                 if p["item"] == "item5"
                 and "bare-slug cross-domain term" in p["message"]}
        check("every explicitly named common noun is rejected as a bare slug",
              _bare - _phrase_slugs, COMMON_NOUNS)
        check("every cross-domain phrase is rejected as a bare hyphenated slug",
              _bare & _phrase_slugs, _phrase_slugs)
        check("none of the common-noun corpus becomes an automatic backfill target",
              [b for b in res4d["backfill_candidates"]
               if b["slug"] == "reader" and b["target"] in COMMON_NOUNS], [])
        check("no cross-domain phrase becomes an automatic backfill target either",
              [b for b in res4d["backfill_candidates"]
               if b["slug"] == "reader" and b["target"] in _phrase_slugs], [])
        check("a bare cross-domain slug is retitled, never kept as an alias",
              ("entry-retitle protocol" in _st_msg(res4d, "tree-of-life", "item5"),
               "never stays an alias" in _st_msg(res4d, "tree-of-life", "item5")),
              (True, True))
        # The same corpus as aliases of QUALIFIED destinations: the surface
        # test, not the destination test, keeps them out of backfill, and
        # each alias is itself an item18/cross-domain-alias finding.
        v = os.path.join(tmp, "v4d-qualified")
        _st_write(v, "entropy-information-theory.md", _st_entry(
            "Entropy (information theory)", "**Entropy** is a worked example.",
            aliases=('"entropy"',), card="Entropy"))
        _st_write(v, "online-machine-learning.md", _st_entry(
            "Online machine learning", "**Online machine learning** is a "
            "worked example.", aliases=('"online-learning"',)))
        _st_write(v, "tree-of-life-biology.md", _st_entry(
            "Tree of life (biology)", "**Tree of life** is a worked example.",
            aliases=('"tree-of-life"',), card="Tree of life"))
        _st_write(v, "random-forest.md", _st_entry(
            "Random forest", "**Random forest** is a worked example.",
            aliases=('"random-decision-forest"',)))
        _st_write(v, "label-machine-learning.md", _st_entry(
            "Label (machine learning)", "**Label** is a worked example.",
            aliases=('"targets"',), card="Label"))
        _st_write(v, "reader2.md", _st_entry(
            "Reader two", "**Reader two** mentions entropy, entropies, "
            "online learning, targets and the tree of life."))
        res = scan(v)
        check("a cross-domain alias of a qualified destination is not a "
              "backfill surface, nor is its plural",
              [row for row in res["backfill_candidates"]
               if row["slug"] == "reader2" and row["target"] in (
                   "entropy-information-theory", "online-machine-learning",
                   "tree-of-life-biology", "label-machine-learning")], [])
        check("an alias that is a cross-domain floor term or its plural is an "
              "item18/cross-domain-alias finding; an ordinary alias is not",
              sorted(p["slug"] for p in res["problems"]
                     if p["item"] == "item18/cross-domain-alias"),
              ["entropy-information-theory", "label-machine-learning",
               "online-machine-learning", "tree-of-life-biology"])
        # A parenthetical title's base term is a backfill surface unless it
        # is a cross-domain floor term (or its plural) or another target's
        # body-link label; a bare entry equal to it is a collision.
        def _base_vault(name, labeler):
            wiki = os.path.join(tmp, name)
            _st_write(wiki, "outlier-statistics.md", _st_entry(
                "Outlier (statistics)", "An **outlier** is an observation far "
                "from the rest.", card="Outlier"))
            _st_write(wiki, "feature-machine-learning.md", _st_entry(
                "Feature (machine learning)", "A **feature** is a measured "
                "input.", card="Feature"))
            _st_write(wiki, "machine-learning.md", _st_entry(
                "Machine learning", "**Machine learning** is a worked "
                "example."))
            _st_write(wiki, "variance-statistics.md", _st_entry(
                "Variance (statistics)", "**Variance** measures spread.",
                card="Variance"))
            _st_write(wiki, "bias-variance-trade-off.md", _st_entry(
                "Bias-variance trade-off", "The **bias-variance trade-off** "
                "balances two errors."))
            _st_write(wiki, "reader.md", _st_entry(
                "Reader", "**Reader** removes outliers, scales the features "
                "and reports the variance."))
            if labeler:
                _st_write(wiki, "labeler.md", _st_entry(
                    "Labeler", "**Labeler** has high "
                    "[[bias-variance-trade-off|variance]]."))
            return wiki
        res = scan(_base_vault("base-term", labeler=True))
        check("a base term ('outliers') is a base_term backfill surface; a "
              "floor term's plural ('features') and a base another target "
              "owns as a body-link label ('variance') are not",
              [(row["target"], row["surface"], row["base_term"],
                row["bare_noun_alias"])
               for row in res["backfill_candidates"]
               if row["slug"] == "reader"],
              [("outlier-statistics", "outliers", True, True)])
        check("without that label the base term 'variance' is proposed",
              [row["target"] for row in scan(_base_vault(
                  "base-term-unlabeled", labeler=False))["backfill_candidates"]
               if row["slug"] == "reader" and row["base_term"]],
              ["outlier-statistics", "variance-statistics"])
        _st_write(_base_vault("base-term-collision", labeler=False),
                  "outlier.md", _st_entry(
                      "Outlier", "An **outlier** is a worked example."))
        res = scan(os.path.join(tmp, "base-term-collision"))
        check("a bare entry equal to a qualified title's base term is a "
              "base-term collision; a qualifier equal to another entry is not",
              [(c["a"], c["b"], c["probe"], c["detail"])
               for c in res["collision_candidates"]],
              [("outlier", "outlier-statistics", "base-term",
                "outlier~outlier-statistics")])
        _base_late = _base_vault("base-term-late", labeler=False)
        _st_write(_base_late, "reader.md", _st_entry(
            "Reader", "**Reader** removes outliers first.\n\nLater, "
            "[[outlier-statistics|outliers]] are trimmed."))
        _st_write(_base_late, "quiet-reader.md", _st_entry(
            "Quiet reader", "**Quiet reader** removes outliers first.\n\n"
            "Later, [[outlier-statistics|Outlier (statistics)]] applies."))
        res = scan(_base_late)
        check("a base surface before a link with that label is a late link; "
              "before a link with another label it is not",
              ["item10/late-link" in _st_keys(res, slug_)
               for slug_ in ("reader", "quiet-reader")], [True, False])

        # wiki-build writing.md principle 5(f): an all-capital acronym title
        # opens with its full form; ROC curve and MLOps are outside the floor.
        v = os.path.join(tmp, "v4e-acronym")
        _st_write(v, "mnist.md", _st_entry(
            "MNIST", "**MNIST** is a dataset of handwritten digits."))
        _st_write(v, "atp.md", _st_entry(
            "ATP", "**ATP** (adenosine triphosphate) is a cell's chemical fuel.",
            aliases=('"adenosine-triphosphate"',),
            card="ATP (adenosine triphosphate)"))
        _st_write(v, "ilsvrc.md", _st_entry(
            "ILSVRC", "**ILSVRC** (2010–2017) was an annual competition.",
            type_="Event"))
        _st_write(v, "roc-curve.md", _st_entry(
            "ROC curve", "A **ROC curve** plots two error rates."))
        _st_write(v, "mlops.md", _st_entry(
            "MLOps", "**MLOps** applies DevOps practice to models."))
        res4e = scan(v)
        check("an acronym title without its opener expansion is item9's "
              "acronym finding, also after a date alone",
              [(slug, "item9/acronym-expansion" in _st_keys(res4e, slug))
               for slug in ("mnist", "ilsvrc", "atp", "roc-curve", "mlops")],
              [("mnist", True), ("ilsvrc", True), ("atp", False),
               ("roc-curve", False), ("mlops", False)])
        check("the acronym finding names the title, the principle and the "
              "no-full-form exit",
              ('"MNIST"' in _st_msg(res4e, "mnist", "item9/acronym-expansion"),
               "5(f)" in _st_msg(res4e, "mnist", "item9/acronym-expansion"),
               "no established full form" in _st_msg(
                   res4e, "mnist", "item9/acronym-expansion")),
              (True, True, True))

        # ------------------------------------------------------------------
        # 5. item 13 (stray key) and item 2 (unexpected key)
        # ------------------------------------------------------------------
        v = os.path.join(tmp, "v5")
        _st_write(v, "sw.md", _st_entry(
            "Sw", "**Sw** is a worked example.\n\n"
            "```yaml\ntype: Software\ntags:\n  - \"#computer-science\"\n```",
            type_="Software"))
        _st_write(v, "scarred.md", _st_entry(
            "Scarred", "**Scarred** is a worked example.\n\ntags:\n  - \"#statistics\""))
        _st_write(v, "obsidian.md", _st_entry(
            "Obsidian", "**Obsidian** is a worked example.",
            extra_keys="cssclasses: wide\npublish: true\n"))
        _st_write(v, "junk.md", _st_entry(
            "Junk", "**Junk** is a worked example.", extra_keys="mood: bright\n"))
        # item 12's literal-$ scan, item 2's bare-`parents:` scan, and item 4's
        # one-document-twice scan: each is a distinct reader over the same file.
        _st_write(v, "dollars.md", _st_entry(
            "Dollars", "**Dollars** is a worked example costing 5$ to run."))
        _st_write(v, "bare-parents.md", _st_entry(
            "Bare parents", "**Bare parents** is a worked example.")
            .replace("parents: []", "parents:"))
        _st_write(v, "block-parents.md", _st_entry(
            "Block parents", "**Block parents** is a worked example.",
            parents=('"[[junk]]"',)))
        _st_write(v, "twice-cited.md", _st_entry(
            "Twice cited", "**Twice cited** is a worked example.",
            sources=('"[[Doe_X_2025.pdf#page=2]]"',
                     '"[[Sources/Notes/doe_x_2025.md]]"')))
        res = scan(v)
        check("a literal $ in the body is item12",
              "item12" in _st_keys(res, "dollars"), True)
        check("a bare `parents:` is YAML null, not an empty list",
              "item2/parents-null" in _st_keys(res, "bare-parents"), True)
        check("...but a bare `parents:` WITH block items under it is not",
              "item2/parents-null" in _st_keys(res, "block-parents"), False)
        check("a .md source naming the same document as a .pdf source is item4 "
              "(stems folded for case and folder, as CONVENTIONS 7 requires of "
              "the shared source_stem helper)",
              "Preserve both sources" in _st_msg(res, "twice-cited", "item4/source-identity"), True)
        check("a frontmatter key shown inside a FENCE is not a merge scar",
              "item13" in _st_keys(res, "sw"), False)
        check("a real stray frontmatter key in the body still is",
              "item13" in _st_keys(res, "scarred"), True)
        check("an Obsidian built-in key routes to item2/obsidian-key, not item2",
              (sorted(set(_st_keys(res, "obsidian"))), ), (["item2/obsidian-key"], ))
        check("...and says not to delete it",
              "DO NOT DELETE" in _st_msg(res, "obsidian", "item2/obsidian-key"), True)
        check("...for every such key",
              _st_msg(res, "obsidian", "item2/obsidian-key").count("Obsidian built-in"), 2)
        check("a genuinely off-schema key is still a plain item2",
              (sorted(set(_st_keys(res, "junk"))),
               "mood" in _st_msg(res, "junk", "item2")), (["item2"], True))

        # ------------------------------------------------------------------
        # 6. the hierarchy diagnostic
        # ------------------------------------------------------------------
        v = os.path.join(tmp, "v6")
        _st_write(v, "selfy.md", _st_entry(
            "Selfy", "**Selfy** is a worked example.", parents=('"[[selfy]]"',)))
        _st_write(v, "ping.md", _st_entry(
            "Ping", "**Ping** is a worked example.", parents=('"[[pong]]"',)))
        _st_write(v, "pong.md", _st_entry(
            "Pong", "**Pong** is a worked example.", parents=('"[[ping]]"',)))
        _st_write(v, "leaf.md", _st_entry(
            "Leaf", "**Leaf** is a worked example.", parents=('"[[root]]"',)))
        _st_write(v, "root.md", _st_entry("Root", "**Root** is a worked example."))
        _st_write(v, "alias-self.md", _st_entry(
            "Alias self", "**Alias self** is a worked example.",
            aliases=('"self-handle"',), parents=('"[[self-handle]]"',)))
        _st_write(v, "alias-left.md", _st_entry(
            "Alias left", "**Alias left** is a worked example.",
            aliases=('"left-handle"',), parents=('"[[right-handle]]"',)))
        _st_write(v, "alias-right.md", _st_entry(
            "Alias right", "**Alias right** is a worked example.",
            aliases=('"right-handle"',), parents=('"[[left-handle]]"',)))
        _st_write(v, "unparsed-owner.md", "A user note without frontmatter.\n")
        _st_write(v, "alias-shadow.md", _st_entry(
            "Alias shadow", "**Alias shadow** is a worked example.",
            aliases=('"unparsed-owner"',)))
        _st_write(v, "unparsed-child.md", _st_entry(
            "Unparsed child", "**Unparsed child** is a worked example.",
            parents=('"[[unparsed-owner]]"',)))
        for _a, _b in (("tri-a", "tri-b"), ("tri-b", "tri-c"), ("tri-c", "tri-a")):
            _st_write(v, _a + ".md", _st_entry(
                _a, "**%s** is a worked example." % _a, parents=('"[[%s]]"' % _b,)))
        res = scan(v)
        h = res["hierarchy_diagnostic"]
        check("exact and unambiguous-alias self-parents are reported",
              h["self_parented"], ["alias-self", "selfy"])
        check("a 2-CYCLE is reported", ["ping", "pong"] in h["parent_cycles"], True)
        check("a longer cycle is reported too, rotated to its first slug",
              ["tri-a", "tri-b", "tri-c"] in h["parent_cycles"], True)
        check("an alias-mediated two-cycle is canonicalized and reported",
              ["alias-left", "alias-right"] in h["parent_cycles"], True)
        check("...each once, not once per member", len(h["parent_cycles"]), 3)
        check("an ordinary parent edge is not a cycle",
              any("leaf" in c or "root" in c for c in h["parent_cycles"]), False)
        check("an unparsed Wiki file cannot serve as a hierarchy parent",
              [(x["slug"], x["target"], x["reason"])
               for x in h["unresolved_parents"]],
              [("unparsed-child", "unparsed-owner", "unparsed")])

        # Discipline Wiki roots, one-home tags, and deep conceptual trees.
        v = os.path.join(tmp, "v6-concept-roots", "Wiki")
        vr = os.path.dirname(v)
        _st_write(v, "machine-learning.md", _st_entry(
            "Machine learning", "**Machine learning** is a field.",
            tags=('"#machine-learning"',)))
        _tree_lines = ["- [[Wiki/machine-learning|Machine learning]]"]
        _previous = "machine-learning"
        for _depth, _name in enumerate(("Models", "Trees", "Decision tree", "Leaf node"), 1):
            _child = slug(_name)
            _st_write(v, _child + ".md", _st_entry(
                _name, "**%s** is a concept." % _name,
                tags=('"#machine-learning"',),
                parents=(json.dumps("[[%s]]" % _previous),)))
            _tree_lines.append("  " * _depth + "- [[Wiki/%s|%s]]" % (_child, _name))
            _previous = _child
        _st_write(vr, "MOCs/machine-learning-moc.md", "\n".join(_tree_lines) + "\n")
        _root_report = scan(v)
        check("a five-level Wiki-rooted tree has no hierarchy defects",
              {key: value for key, value in _root_report["hierarchy_diagnostic"].items()
               if key in {"placement_gaps", "unresolved_parents", "parent_state_findings",
                          "moc_consistency_findings", "self_parented", "parent_cycles"}},
              {key: [] for key in ("placement_gaps", "unresolved_parents", "parent_state_findings",
                                   "moc_consistency_findings", "self_parented", "parent_cycles")})
        _st_write(v, "leaf-node.md", _st_entry(
            "Leaf node", "**Leaf node** is a concept.",
            tags=('"#machine-learning"', '"#computer-science"'),
            parents=('"[[MOCs/machine-learning-moc]]"',)))
        _root_report = scan(v)
        check("multiple valid specific tags still violate one-home classification",
              "exactly one discipline home" in _st_msg(_root_report, "leaf-node", "item8"), True)
        check("an existing readable MOC cannot pass as a parent",
              any(row["slug"] == "leaf-node" and row["kind"] == "moc-parent"
                  for row in _root_report["hierarchy_diagnostic"]["parent_state_findings"]), True)
        check("an active discipline without a Wiki root is diagnosed",
              any(row["slug"] == "computer-science" and row["kind"] == "missing-discipline-root"
                  for row in _root_report["hierarchy_diagnostic"]["parent_state_findings"]), True)
        _st_write(v, "machine-learning.md", _st_entry(
            "Machine learning", "**Machine learning** is a field.",
            tags=('"#machine-learning"',), parents=('"[[models]]"',)))
        _root_report = scan(v)
        check("a root cannot acquire a parent even when it resolves to a Wiki entry",
              any(row["slug"] == "machine-learning" and row["kind"] == "root-parent-mismatch"
                  for row in _root_report["hierarchy_diagnostic"]["parent_state_findings"]), True)

        # A link to a missing root waits for Task 3 (link-hygiene.md). That
        # rule pairs each spelling's item10/dangling finding with the
        # missing-discipline-root row for the same folded slug, so the scan
        # must report both and must not call either spelling a case or alias
        # match.
        v = os.path.join(tmp, "v6-missing-root", "Wiki")
        _st_write(v, "mitochondrion.md", _st_entry(
            "Mitochondrion", "**Mitochondrion** is an organelle studied in "
            "[[biology]], which [[Biology|life science]] also names.",
            tags=('"#biology"',)))
        _root_report = scan(v)
        _dangling = _st_msg(_root_report, "mitochondrion", "item10/dangling")
        check("each spelling of a link to a missing root is reported as dangling",
              ('"biology"' in _dangling, '"Biology"' in _dangling), (True, True))
        check("a missing root that entries link is diagnosed for the same slug",
              [(row["slug"], row["kind"])
               for row in _root_report["hierarchy_diagnostic"]["parent_state_findings"]],
              [("biology", "missing-discipline-root")])
        check("a link to a missing root is no case or alias match",
              [key for key in _st_keys(_root_report, "mitochondrion")
               if key in ("item10/case", "item10/alias")], [])

        # Parent resolution and MOC ownership live outside the entry-only
        # inventory: the vault root is the parent of Wiki/, and a valid root
        # MOC must resolve without being mistaken for a missing Wiki entry.
        v = os.path.join(tmp, "v6b", "Wiki")
        vr = os.path.dirname(v)
        _st_write(v, "placed-empty.md", _st_entry(
            "Placed empty", "**Placed empty** is a worked example.",
            tags=('"#machine-learning"',)))
        _st_write(v, "rooted.md", _st_entry(
            "Rooted", "**Rooted** is a worked example.",
            tags=('"#machine-learning"',),
            parents=('"[[MOCs/machine-learning-moc]]"',)))
        _st_write(v, "exact-file-child.md", _st_entry(
            "Exact file child", "**Exact file child** is a worked example.",
            tags=('"#machine-learning"',), parents=('"[[rooted]]"',)))
        _st_write(v, "ml-parent.md", _st_entry(
            "ML parent", "**ML parent** is a worked example.",
            tags=('"#machine-learning"',),
            parents=('"[[MOCs/machine-learning-moc]]"',)))
        _st_write(v, "partial-multitag.md", _st_entry(
            "Partial multitag", "**Partial multitag** is a worked example.",
            tags=('"#machine-learning"', '"#statistics"'),
            parents=('"[[MOCs/machine-learning-moc]]"',)))
        _st_write(v, "partial-via-entry.md", _st_entry(
            "Partial via entry", "**Partial via entry** is a worked example.",
            tags=('"#machine-learning"', '"#statistics"'),
            parents=('"[[ml-parent]]"',)))
        _st_write(v, "complete-multitag.md", _st_entry(
            "Complete multitag", "**Complete multitag** is a worked example.",
            tags=('"#machine-learning"', '"#statistics"'),
            parents=('"[[ml-parent]]"', '"[[MOCs/statistics-moc]]"')))
        _st_write(v, "wrong-discipline-root.md", _st_entry(
            "Wrong discipline root",
            "**Wrong discipline root** is a worked example.",
            tags=('"#biology"',), parents=('"[[MOCs/machine-learning-moc]]"',)))
        _st_write(v, "missing-entry-parent.md", _st_entry(
            "Missing entry parent", "**Missing entry parent** is a worked example.",
            tags=('"#machine-learning"',),
            parents=('"[[definitely-missing-parent]]"',)))
        _st_write(v, "alias-owner-a.md", _st_entry(
            "Alias owner A", "**Alias owner A** is a worked example.",
            tags=('"#machine-learning"',), aliases=('"rooted"',),
            parents=('"[[MOCs/machine-learning-moc]]"',)))
        _st_write(v, "alias-owner-b.md", _st_entry(
            "Alias owner B", "**Alias owner B** is a worked example.",
            tags=('"#machine-learning"',), aliases=('"rooted"',),
            parents=('"[[MOCs/machine-learning-moc]]"',)))
        for _discipline in ("statistics", "mathematics", "biology", "physics"):
            _title = _discipline.title() + " rooted"
            _st_write(v, _discipline + "-rooted.md", _st_entry(
                _title, "**%s** is a worked example." % _title,
                tags=(json.dumps("#" + _discipline),),
                parents=(json.dumps("[[MOCs/%s-moc]]" % _discipline),)))
        _st_write(v, "chemistry-rooted.md", _st_entry(
            "Chemistry rooted", "**Chemistry rooted** is a worked example.",
            tags=('"#chemistry"',), parents=('"[[MOCs/chemistry-moc]]"',)))
        _st_write(vr, "MOCs/machine-learning-moc.md", "- [[Wiki/rooted|Rooted]]\n")
        _st_write(vr, "MOCs/statistics-moc.md", "- [[Wiki/statistics-rooted|Statistics rooted]]\n")
        _st_write(vr, "MOCs/mathematics-moc.md", "")
        _st_write(vr, "MOCs/biology-moc.md",
                  "  <!-- annotation -->\n- [[Wiki/biology-rooted|Biology rooted]]\n")
        _st_write(vr, "MOCs/chemistry-moc.md", b"\xff\xfe")
        res = scan(v)
        h = res["hierarchy_diagnostic"]
        check("the vault root is derived from the scanned Wiki directory",
              res["vault_root"], os.path.abspath(vr))
        check("a tagged entry with no usable parent is report-only hierarchy backlog",
              [gap["slug"] for gap in h["placement_gaps"]],
              ["alias-owner-a", "alias-owner-b", "biology-rooted", "chemistry-rooted",
               "complete-multitag", "mathematics-rooted", "missing-entry-parent", "ml-parent",
               "partial-multitag", "partial-via-entry", "physics-rooted", "placed-empty",
               "rooted", "statistics-rooted", "wrong-discipline-root"])
        check("placement gaps retain the missing discipline for partial unions and wrong roots",
              [(x["slug"], x["missing_disciplines"],
                x["represented_disciplines"])
               for x in h["placement_gaps"]
               if x["slug"] in ("partial-multitag", "partial-via-entry",
                                "wrong-discipline-root")],
              [("partial-multitag", ["machine-learning", "statistics"], []),
               ("partial-via-entry", ["statistics"], ["machine-learning"]),
               ("wrong-discipline-root", ["biology"], [])])
        check("a legacy multi-discipline union cannot use an MOC as its second ancestor",
              any(x["slug"] == "complete-multitag" for x in h["placement_gaps"]), True)
        check("missing entry and root-MOC parents are reported, while an existing root MOC resolves",
              [(x["slug"], x["target"], x["reason"])
               for x in h["unresolved_parents"]],
              [("chemistry-rooted", "MOCs/chemistry-moc", "unreadable"),
               ("missing-entry-parent", "definitely-missing-parent", "missing"),
               ("physics-rooted", "MOCs/physics-moc", "missing")])
        check("an exact parent file wins over entries that ambiguously claim the same alias",
              any(x["slug"] == "exact-file-child" for x in h["unresolved_parents"]), False)
        check("every discipline MOC has an explicit safe-file state",
              {x["discipline"]: x["state"] for x in h["moc_file_states"]},
              {"biology": "readable", "machine-learning": "readable",
               "chemistry": "unreadable", "mathematics": "empty", "physics": "missing",
               "statistics": "readable"})
        check("an unreadable MOC carries its read error through the scan",
              [(x["state"], x.get("error", "").split(":", 1)[0])
               for x in h["moc_file_states"]
               if x["discipline"] == "chemistry"],
              [("unreadable", "UnicodeDecodeError")])
        check("an indented comment is malformed generated outline content",
              [x["line"] for x in h["moc_consistency_findings"]
               if x.get("discipline") == "biology" and x["kind"] == "malformed-line"],
              [1])
        check("an empty active MOC reports every missing tagged entry",
              [x["slug"] for x in h["moc_consistency_findings"]
               if x.get("discipline") == "mathematics" and x["kind"] == "missing-entry"],
              ["mathematics-rooted"])

        _fake_moc = os.path.join(vr, "dangling-moc.md")
        try:
            os.symlink(os.path.join(vr, "missing-moc-target.md"), _fake_moc)
            _have_moc_symlink = True
            _symlink_state = moc_file_state(_fake_moc)
        except (OSError, NotImplementedError):
            _have_moc_symlink = False
            _symlink_state = {"state": "unreadable", "error": "symlink"}
        check("a dangling or live MOC symlink is occupied and never `missing`",
              (_symlink_state["state"], "symlink" in _symlink_state["error"].lower()),
              ("unreadable", True))

        # A regular file can be swapped to a link between the initial lstat
        # and open. The no-follow/opened-inode guard must classify that race as
        # unreadable instead of importing an outside generated tree.
        _race_moc = os.path.join(vr, "race-moc.md")
        _race_target = os.path.join(vr, "race-target.md")
        _st_write(vr, "race-moc.md", "- original\n")
        _st_write(vr, "race-target.md", "- outside\n")
        if _have_moc_symlink:
            _real_open = os.open
            _swapped = []

            def _swap_moc_before_open(path, flags, *args, **kwargs):
                if os.path.abspath(path) == os.path.abspath(_race_moc) and not _swapped:
                    os.unlink(_race_moc)
                    os.symlink(_race_target, _race_moc)
                    _swapped.append(True)
                return _real_open(path, flags, *args, **kwargs)

            from unittest import mock
            with mock.patch.object(os, "open", side_effect=_swap_moc_before_open):
                _race_state = moc_file_state(_race_moc)
            check("a MOC swapped to a leaf symlink before open is unreadable",
                  _race_state["state"], "unreadable")
        else:
            check("MOC open-race regression skipped without symlinks", True, True)

        malformed = os.path.join(vr, "outline-shapes")
        for name, content in (("prose", "A personal introduction.\n"),
                              ("heading", "# A heading\n"),
                              ("comment", "<!-- annotation -->\n")):
            _st_write(malformed, name + ".md", content)
        check("file readability does not imply valid generated outline content",
              [moc_file_state(os.path.join(malformed, name + ".md"))["state"]
               for name in ("prose", "heading", "comment")],
              ["readable"] * 3)

        # The complete generated tree supplies coverage and nearest linked
        # ancestors without any region markers. Resolvable noncanonical
        # links remain placements, while broken structure blocks exact-union
        # comparison rather than manufacturing a partial answer.
        v = os.path.join(tmp, "v6c", "Wiki")
        vr = os.path.dirname(v)
        _st_write(v, "broad.md", _st_entry(
            "Broad", "**Broad** is a worked example.",
            tags=('"#machine-learning"',),
            parents=('"[[MOCs/machine-learning-moc]]"',)))
        _st_write(v, "machine-learning.md", _st_entry(
            "Machine learning", "**Machine learning** is a worked example.",
            tags=('"#machine-learning"',),
            parents=('"[[MOCs/machine-learning-moc]]"',)))
        for _name in ("Leaf", "Duplicate", "Deep"):
            _st_write(v, slug(_name) + ".md", _st_entry(
                _name, "**%s** is a worked example." % _name,
                tags=('"#machine-learning"',), parents=('"[[broad]]"',)))
        _st_write(v, "qualified-machine-learning.md", _st_entry(
            "Qualified (machine learning)",
            "**Qualified (machine learning)** is a worked example.",
            tags=('"#machine-learning"',), aliases=('"qualified-handle"',),
            parents=('"[[MOCs/machine-learning-moc]]"',)))
        _st_write(v, "mismatch.md", _st_entry(
            "Mismatch", "**Mismatch** is a worked example.",
            tags=('"#machine-learning"',),
            parents=('"[[MOCs/machine-learning-moc]]"',)))
        _st_write(v, "absent.md", _st_entry(
            "Absent", "**Absent** is a worked example.",
            tags=('"#machine-learning"',), parents=('"[[broad]]"',)))
        _st_write(v, "blocked-child.md", _st_entry(
            "Blocked child", "**Blocked child** is a worked example.",
            tags=('"#machine-learning"',), parents=('"[[broad]]"',)))
        _st_write(v, "partially-blocked.md", _st_entry(
            "Partially blocked", "**Partially blocked** is a worked example.",
            tags=('"#machine-learning"',),
            parents=('"[[broad]]"', '"[[does-not-exist]]"')))
        _st_write(v, "multi-group-union.md", _st_entry(
            "Multi-group union", "**Multi-group union** is a worked example.",
            tags=('"#machine-learning"', '"#physics"'),
            parents=('"[[MOCs/machine-learning-moc]]"',)))
        _st_write(v, "suppressed.md", _st_entry(
            "Suppressed", "**Suppressed** is a worked example.",
            tags=('"#statistics"',), parents=('"[[wrong-parent]]"',)))
        _st_write(v, "biology-only.md", _st_entry(
            "Biology only", "**Biology only** is a worked example.",
            tags=('"#biology"',), parents=('"[[MOCs/biology-moc]]"',)))
        _st_write(
            vr, "MOCs/machine-learning-moc.md",
            "- [[Wiki/broad|Broad]]\n"
            "  - [[Wiki/leaf|Leaf]]\n"
            "  - [[Wiki/duplicate|Duplicate]]\n"
            "  - [[Wiki/duplicate|Duplicate]]\n"
            "  - Theme\n"
            "    - Subtheme\n"
            "      - [[Wiki/deep|Deep]]\n"
            "  - [[Wiki/mismatch|Mismatch]]\n"
            "  - [[Wiki/partially-blocked|Partially blocked]]\n"
            "- [[qualified-handle|Qualified (machine learning)]]\n"
            "- [[Wiki/multi-group-union|Multi-group union]]\n"
            "- [[Wiki/biology-only|Biology only]]\n"
            "- [[Wiki/does-not-exist|Does not exist]]\n"
            "  - [[Wiki/blocked-child|Blocked child]]\n"
            "  - [[Wiki/partially-blocked|Partially blocked]]\n"
)
        _st_write(
            vr, "MOCs/statistics-moc.md",
            "  - [[Wiki/suppressed|Suppressed]]\n"
            "not a bullet\n"
            "- [[Wiki/suppressed|Suppressed]]\n"
)
        _st_write(vr, "MOCs/physics-moc.md", "- [[Wiki/multi-group-union|Multi-group union]]\n")
        res = scan(v)
        findings = res["hierarchy_diagnostic"]["moc_consistency_findings"]
        check("whole-file MOC consistency reports every deterministic issue class",
              {x["kind"] for x in findings},
              {"malformed-line", "malformed-indentation",
               "unresolved-link", "noncanonical-target", "noncanonical-label",
               "wrong-discipline-link", "missing-entry",
               "duplicate-placement", "parent-union-mismatch",
               "eponymous-root"})
        check("a resolvable alias stays a placement while both canonical forms are reported",
              ([(x.get("slug"), x.get("target")) for x in findings
                if x["kind"] == "noncanonical-target"],
               [(x.get("slug"), x.get("label"), x.get("expected_label"))
                for x in findings if x["kind"] == "noncanonical-label"],
               any(x["kind"] == "missing-entry"
                   and x.get("slug") == "qualified-machine-learning"
                   for x in findings)),
              ([('qualified-machine-learning', 'qualified-handle')],
               [('qualified-machine-learning', 'Qualified (machine learning)',
                 'Qualified')], False))
        check("wrong-discipline and unresolved links remain distinct",
              ([(x["kind"], x.get("slug"), x.get("target")) for x in findings
                if x["kind"] == "wrong-discipline-link"],
               [(x.get("target"), x.get("reason")) for x in findings
                if x["kind"] == "unresolved-link"]),
              ([('wrong-discipline-link', 'biology-only', 'Wiki/biology-only')],
               [('Wiki/does-not-exist', 'missing')]))
        check("duplicate placements use the same nearest linked parent",
              [(x.get("slug"), x.get("parent")) for x in findings
               if x["kind"] == "duplicate-placement"],
              [("duplicate", "broad")])
        check("valid conceptual depth has no arbitrary three-level ceiling",
              [(x.get("slug"), x.get("depth")) for x in findings
               if x["kind"] == "excessive-depth"], [])
        check("tagged entries absent from a generated MOC are reported",
              [x["slug"] for x in findings if x["kind"] == "missing-entry"
               and x["discipline"] == "machine-learning"],
              ["absent", "machine-learning"])
        check("the exact parent union is derived from the nearest linked ancestor",
              [(x["slug"], x["expected_parents"], x["actual_parents"])
               for x in findings if x["kind"] == "parent-union-mismatch"],
              [("broad", [], ["MOCs/machine-learning-moc"]),
               ("mismatch", ["broad"], ["MOCs/machine-learning-moc"]),
               ("multi-group-union", [], ["MOCs/machine-learning-moc"]),
               ("qualified-machine-learning", [], ["MOCs/machine-learning-moc"])])
        check("malformed and missing-placement MOCs suppress union comparison",
              any(x["kind"] == "parent-union-mismatch"
                  and x.get("slug") in {"suppressed", "absent",
                                        "blocked-child"}
                  for x in findings), False)
        check("an unresolved linked ancestor blocks descendant parent inference",
              any(x["kind"] == "missing-entry"
                  and x.get("slug") == "blocked-child" for x in findings), False)
        check("one safe placement cannot hide another occurrence under an unresolved ancestor",
              any(x["kind"] == "parent-union-mismatch"
                  and x.get("slug") == "partially-blocked" for x in findings), False)
        check("an eponymous discipline entry must be the single top-level branch",
              [(x.get("slug"), x.get("top_level_slugs")) for x in findings
               if x["kind"] == "eponymous-root"],
              [("machine-learning",
                ["broad", "qualified-machine-learning", "multi-group-union",
                 None, None])])
        check("complete generated trees supply the multi-discipline parent union",
              [x["slug"] for x in findings if x["kind"] == "parent-union-mismatch"
               and "physics" in x.get("disciplines", [])], ["multi-group-union"])

        # A discipline root placed a second time, below its own descendant or
        # below a category under itself, is a MOC-shape error. The parent
        # union never asks the root for a parent.
        v = os.path.join(tmp, "v6-root-twice", "Wiki")
        vr = os.path.dirname(v)
        _st_write(v, "statistics.md", _st_entry(
            "Statistics", "**Statistics** is a field.", card=False))
        _st_write(v, "mean.md", _st_entry(
            "Mean", "**Mean** is a worked example.",
            parents=('"[[statistics]]"',)))
        _root_twice = []
        for _tree_text in (
                "- [[Wiki/statistics|Statistics]]\n"
                "  - [[Wiki/mean|Mean]]\n"
                "    - [[Wiki/statistics|Statistics]]\n",
                "- [[Wiki/statistics|Statistics]]\n"
                "  - Theme\n"
                "    - [[Wiki/statistics|Statistics]]\n"
                "  - [[Wiki/mean|Mean]]\n"):
            _st_write(vr, "MOCs/statistics-moc.md", _tree_text)
            _root_twice.append(
                [(x["kind"], x.get("slug")) for x in
                 scan(v)["hierarchy_diagnostic"]["moc_consistency_findings"]])
        check("a root repeated below its descendant or itself is an "
              "eponymous-root finding, never a parent-union mismatch",
              _root_twice, [[("eponymous-root", "statistics")]] * 2)

        # Canonical MOCs live outside Wiki under `<discipline>-moc` names, so
        # their eponymous roots take ordinary bare links; the two destinations
        # stay distinct even when both appear in the same entry or tree.
        v = os.path.join(tmp, "v6d", "Wiki")
        vr = os.path.dirname(v)
        _st_write(v, "statistics.md", _st_entry(
            "Statistics", "**Statistics** is a worked example.",
            aliases=('"physics"',)))
        _st_write(v, "leaf.md", _st_entry(
            "Leaf", "**Leaf** is a worked example.",
            parents=('"[[statistics]]"',)))
        _st_write(v, "navigation.md", _st_entry(
            "Navigation", "**Navigation** is a worked example. "
            "[[MOCs/statistics-moc|Field index]] and [[statistics|Statistics]] "
            "are distinct destinations. [[MOCs/physics-moc|A different index]] "
            "is not an alias for the concept.", tags=('"#misc"',),
            parents=('"[[misc]]"',),
            related="[[MOCs/statistics-moc|Field index]]"))
        _canonical_tree = ("- [[Wiki/statistics|Statistics]]\n"
                           "  - [[Wiki/leaf|Leaf]]\n")
        _st_write(vr, "MOCs/statistics-moc.md", _canonical_tree)
        _st_write(v, "misc.md", _st_entry("Misc", "**Misc** is a category.", tags=('"#misc"',)))
        _st_write(vr, "MOCs/misc-moc.md", "- [[Wiki/misc|Misc]]\n  - [[Wiki/navigation|Navigation]]\n")
        res = scan(v)
        h = res["hierarchy_diagnostic"]
        check("canonical MOC and same-named Wiki entry form a complete consistent tree",
              [h[key] for key in ("placement_gaps", "unresolved_parents",
                                  "self_parented", "parent_cycles",
                                  "moc_consistency_findings", "moc_inventory_findings")],
              [[]] * 6)
        check("eponymous root parents are bare once the MOC has its own name",
              "item2/parents-form" in _st_keys(res, "leaf"), False)
        check("MOC navigation is neither an entry duplicate nor a wrong entry title",
              [key for key in _st_keys(res, "navigation")
               if key in {"item10/dup", "item10/dangling", "item10/alias",
                          "item11", "item18"}], [])
        check("a missing explicit MOC cannot resolve through a same-named Wiki alias",
              "MOCs/physics-moc" in _st_msg(res, "navigation", "item10/moc"), True)
        check("only active or existing discipline MOCs are inventoried",
              [(row["target"], row["entries"]) for row in h["moc_file_states"]],
              [("MOCs/misc-moc", 2), ("MOCs/statistics-moc", 2)])
        check("an unchanged canonical hierarchy scan is deterministic and read-only",
              (scan(v) == res,
               open(os.path.join(vr, "MOCs/statistics-moc.md"), encoding="utf-8").read()),
              (True, _canonical_tree))
        _st_write(v, "alias-navigation.md", _st_entry(
            "Alias navigation", "**Alias navigation** is a worked example. "
            "[[physics|Field concept]] is an entry alias.", tags=()))
        _st_write(v, "moc-only-navigation.md", _st_entry(
            "MOC only navigation", "**MOC only navigation** is a worked example. "
            "[[MOCs/statistics-moc|Index]] and [[MOCs/statistics-moc|Index]] are navigation. "
            "Statistics also names the distinct concept.", tags=()))
        res = scan(v)
        check("entry alias repair uses the bare root slug once the MOC has its own name",
              "[[statistics|Field concept]]" in
              _st_msg(res, "alias-navigation", "item10/alias"), True)
        check("MOC links do not suppress a real entry backfill or become entry duplicates",
              (any(row["slug"] == "moc-only-navigation" and row["target"] == "statistics"
                   for row in res["backfill_candidates"]),
               "item10/dup" in _st_keys(res, "moc-only-navigation")),
              (True, False))
        _st_write(v, "leaf.md", _st_entry(
            "Leaf", "**Leaf** is a worked example.",
            parents=('"[[Wiki/statistics]]"',)))
        res = scan(v)
        check("a qualified root parent is respelled bare once the MOC has its own name",
              'resolves to "statistics"' in _st_msg(res, "leaf", "item2/parents-form"),
              True)

        # A previous-layout MOC is `MOCs/<discipline>.md`. While that
        # previous-layout file exists it is a legacy owner of the root's
        # basename: a qualified root link stays canonical and a bare one is
        # ambiguous rather than resolved to either file.
        _st_write(vr, "MOCs/statistics.md", _canonical_tree)
        _st_write(v, "ambiguous-child.md", _st_entry(
            "Ambiguous child", "**Ambiguous child** is a worked example. "
            "[[statistics|statistics]] has an unresolved destination.",
            parents=('"[[statistics]]"',)))
        _st_write(vr, "MOCs/statistics-moc.md",
                  _canonical_tree.replace("[[Wiki/statistics|", "[[statistics|"))
        res = scan(v)
        h = res["hierarchy_diagnostic"]
        check("a previous-layout MOC is a legacy owner reported for migration",
              ([(row["kind"], row.get("discipline"))
                for row in h["moc_inventory_findings"]],
               [(os.path.basename(row["path"]), row["state"], row["target"])
                for row in h["legacy_moc_states"]]),
              ([("previous-layout", "statistics")],
               [("statistics.md", "readable", "MOCs/statistics-moc")]))
        check("while it exists, a qualified root parent stays canonical",
              "item2/parents-form" in _st_keys(res, "leaf"), False)
        check("a bare eponymous parent is ambiguous instead of selecting entry or MOC",
              [(row["slug"], row["reason"]) for row in h["unresolved_parents"]],
              [("ambiguous-child", "ambiguous")])
        check("ambiguous bare navigation is preserved without a redundant-pipe rewrite",
              ("item10/ambiguous" in _st_keys(res, "ambiguous-child"),
               "item10/redundant-pipe" in _st_keys(res, "ambiguous-child")),
              (True, False))
        check("a bare eponymous MOC bullet cannot become a self-link or inferred entry",
              [(row["target"], row["reason"])
               for row in h["moc_consistency_findings"]
               if row["kind"] == "unresolved-link"],
              [("statistics", "ambiguous")])
        check("backfill qualifies the root while its previous-layout MOC exists",
              [row["target"] for row in res["backfill_candidates"]
               if row["slug"] == "moc-only-navigation"
               and row["target"].endswith("statistics")],
              ["Wiki/statistics"])
        os.unlink(os.path.join(vr, "MOCs/statistics.md"))

        v = os.path.join(tmp, "v6d-backfill", "Wiki")
        vr = os.path.dirname(v)
        for _slug, _title in (("misc", "Misc"), ("statistics", "Statistics"),
                              ("leaf", "Leaf")):
            _st_write(v, _slug + ".md", _st_entry(
                _title, "**%s** is a worked example." % _title))
        _st_write(vr, "MOCs/misc-moc.md", "")
        _st_write(vr, "MOCs/statistics-moc.md", "")
        _reader_body = "**Reader** uses Misc, Statistics, and Leaf for worked examples."
        _st_write(v, "reader.md", _st_entry("Reader", _reader_body))
        res = scan(v)
        _backfill_rows = [row for row in res["backfill_candidates"]
                          if row["slug"] == "reader"]
        check("backfill destinations to misc and discipline roots are bare beside their -moc MOCs",
              sorted(row["target"] for row in _backfill_rows),
              ["leaf", "misc", "statistics"])
        for _row in _backfill_rows:
            _reader_body = _reader_body.replace(
                _row["surface"], "[[%s|%s]]" % (_row["target"], _row["surface"]), 1)
        _st_write(v, "reader.md", _st_entry("Reader", _reader_body))
        res = scan(v)
        check("applying proposed backfill destinations resolves to entries and is idempotent on rescan",
              ([key for key in _st_keys(res, "reader") if key.startswith("item10/")],
               [row for row in res["backfill_candidates"] if row["slug"] == "reader"]),
              ([], []))

        # MOCs are real basename owners even when there is no same-named Wiki
        # entry. Their files outrank entry aliases in every link consumer.
        v = os.path.join(tmp, "v6d-bare", "Wiki")
        vr = os.path.dirname(v)
        _st_write(v, "leaf.md", _st_entry(
            "Leaf", "**Leaf** is a worked example.",
            tags=('"#biology"',), parents=('"[[biology-moc]]"',)))
        _st_write(vr, "MOCs/biology-moc.md",
                  "- [[Wiki/leaf|Leaf]]\n")
        _st_write(v, "reader.md", _st_entry(
            "Reader", "**Reader** is a worked example. [[biology-moc|Biology index]] "
            "and [[MOCs/biology-moc|Biology index]] are navigation. "
            "Alias owner is a separate concept.", tags=('"#misc"',),
            parents=('"[[MOCs/misc-moc]]"',),
            related="[[biology-moc|Biology index]]"))
        _st_write(vr, "MOCs/misc-moc.md", "- [[Wiki/reader|Reader]]\n")
        res = scan(v)
        check("a unique bare MOC target is normalized as navigation, never dangling",
              ("MOCs/biology-moc" in _st_msg(res, "reader", "item10/case"),
               [key for key in _st_keys(res, "reader")
                if key in {"item10/dangling", "item10/alias", "item10/dup", "item11"}]),
              (True, []))
        check("a resolvable bare MOC remains invalid as a conceptual parent",
              (res["hierarchy_diagnostic"]["unresolved_parents"],
               [row["slug"] for row in res["hierarchy_diagnostic"]["parent_state_findings"]
                if row["kind"] == "moc-parent"],
               "MOCs/biology-moc" in _st_msg(res, "leaf", "item2/parents-form")),
              ([], ["leaf", "reader"], True))
        check("a MOC-resolving parent is report-only, never respelled to its MOC",
              ("use this canonical target" in _st_msg(res, "leaf", "item2/parents-form"),
               "Report only" in _st_msg(res, "leaf", "item2/parents-form"),
               "item2/parents-form" in _st_keys(res, "reader")),
              (False, True, False))
        _st_write(v, "alias-owner.md", _st_entry(
            "Alias owner", "**Alias owner** is a worked example.",
            tags=(), aliases=('"biology-moc"',)))
        _st_write(v, "qualified-reader.md", _st_entry(
            "Qualified reader", "**Qualified reader** is a worked example. "
            "[[Wiki/alias-owner|Alias owner]] is the actual concept. "
            "Alias owner remains linked.", tags=()))
        res = scan(v)
        check("a real MOC file outranks a Wiki alias without redirecting or relabeling navigation",
              [key for key in _st_keys(res, "reader")
               if key in {"item10/dangling", "item10/alias", "item10/dup", "item11", "item18"}], [])
        check("bare MOC navigation cannot suppress backfill to a same-named entry alias owner",
              [row["slug"] for row in res["backfill_candidates"]
               if row["target"] == "alias-owner"], ["reader"])
        _st_write(v, "biology-moc.md", _st_entry(
            "Biology moc", "**Biology moc** is a worked example.",
            tags=('"#biology"',)))
        _st_write(v, "qualified-reader.md", _st_entry(
            "Qualified reader", "**Qualified reader** is a worked example. "
            "[[Wiki/biology-moc|Biology moc]] is distinct from [[MOCs/biology-moc|Biology index]].",
            tags=()))
        res = scan(v)
        check("adding a real Wiki basename makes bare links ambiguous while qualified links stay distinct",
              ("item10/ambiguous" in _st_keys(res, "reader"),
               [key for key in _st_keys(res, "qualified-reader")
                if key.startswith("item10/") or key in {"item11", "item18"}]),
              (True, []))

        v = os.path.join(tmp, "v6d-unexpected", "Wiki")
        vr = os.path.dirname(v)
        _st_write(v, "leaf.md", _st_entry(
            "Leaf", "**Leaf** is a worked example. [[leaf|Leaf map]] is navigation.",
            parents=('"[[MOCs/statistics-moc]]"',)))
        _st_write(vr, "MOCs/statistics-moc.md",
                  "- [[Wiki/leaf|Leaf]]\n")
        for _map in ("leaf", "other-map", "orphan-map"):
            _st_write(vr, "MOCs/" + _map + ".md", "A user-owned non-enum map.\n")
        _st_write(v, "alias-owner.md", _st_entry(
            "Alias owner", "**Alias owner** is a worked example.",
            tags=(), aliases=('"other-map"',)))
        _st_write(v, "reader.md", _st_entry(
            "Reader", "**Reader** is a worked example. [[other-map|Index]] "
            "and [[orphan-map|Other index]] and [[MOCs/leaf|Leaf index]] are navigation. "
            "Alias owner is a distinct concept. [[Wiki/leaf|Leaf]] is an entry.",
            tags=(), related="[[other-map|Index]]"))
        _st_write(v, "unknown-parent.md", _st_entry(
            "Unknown parent", "**Unknown parent** is a worked example.",
            parents=('"[[other-map]]"',)))
        res = scan(v)
        check("an unexpected MOC basename makes a same-named Wiki link ambiguous, never self-linked",
              ("item10/ambiguous" in _st_keys(res, "leaf"),
               "item10/self" in _st_keys(res, "leaf")), (True, False))
        check("unknown bare or explicit MOC navigation outranks aliases but is preserved without qualification",
              (len([row for row in res["problems"] if row["slug"] == "reader"
                    and row["item"] == "item10/moc"]),
               [key for key in _st_keys(res, "reader")
                if key in {"item10/alias", "item10/dangling", "item10/case",
                           "item10/dup", "item11", "item18"}]),
              (4, []))
        check("an unexpected MOC cannot act as a hierarchy root or suppress alias-owner backfill",
              ([(row["slug"], row["reason"])
                for row in res["hierarchy_diagnostic"]["unresolved_parents"]],
               any(row["slug"] == "reader" and row["target"] == "alias-owner"
                   for row in res["backfill_candidates"])),
              ([("unknown-parent", "unexpected-moc")], True))

        # Nested Wiki overrides use actual vault-relative targets, including
        # parent links to the eponymous entry, rather than just folder basename.
        vr = os.path.join(tmp, "v6d-override")
        os.makedirs(os.path.join(vr, ".obsidian"))
        v = os.path.join(vr, "Knowledge", "Concepts")
        _st_write(v, "statistics.md", _st_entry(
            "Statistics", "**Statistics** is a worked example."))
        _st_write(v, "leaf.md", _st_entry(
            "Leaf", "**Leaf** is a worked example.",
            parents=('"[[statistics]]"',)))
        _st_write(vr, "MOCs/statistics-moc.md",
                  _canonical_tree.replace("Wiki/", "Knowledge/Concepts/"))
        res = scan(v)
        check("MOC and parent links honor the full path of a nested Wiki override",
              (res["vault_root"], res["hierarchy_diagnostic"]["moc_consistency_findings"],
               res["hierarchy_diagnostic"]["unresolved_parents"],
               "item2/parents-form" in _st_keys(res, "leaf")),
              (vr, [], [], False))

        v = os.path.join(tmp, "v6e", "Wiki")
        vr = os.path.dirname(v)
        _st_write(v, "legacy-rooted.md", _st_entry(
            "Legacy rooted", "**Legacy rooted** is a worked example.",
            parents=('"[[statistics-moc]]"',)))
        _st_write(v, "new-rooted.md", _st_entry(
            "New rooted", "**New rooted** is a worked example.",
            parents=('"[[MOCs/statistics-moc]]"',)))
        _st_write(vr, "statistics-moc.md", _canonical_tree)
        res = scan(v)
        h = res["hierarchy_diagnostic"]
        check("a legacy root MOC never supplies a missing canonical root",
              ([(row["target"], row["state"]) for row in h["moc_file_states"]],
               [(row["slug"], row["reason"]) for row in h["unresolved_parents"]]),
              ([("MOCs/statistics-moc", "missing")],
               [("legacy-rooted", "legacy-moc"), ("new-rooted", "missing")]))
        check("unexpected old root bytes retain their safe-file state and conflicting canonical path",
              [(row["discipline"], row["state"], row["canonical_path"])
               for row in h["legacy_moc_states"]],
              [("statistics", "readable", os.path.join(vr, "MOCs/statistics-moc.md"))])
        _empty_tree = ""
        _st_write(vr, "MOCs/statistics-moc.md", _empty_tree)
        _st_write(vr, "MOCs/physics-moc.md", _empty_tree)
        _st_write(vr, "economics-moc.md", "Personal legacy note.\n")
        _st_write(vr, "MOCs/physics-map.md", "Unexpected spelling.\n")
        _st_write(vr, "MOCs/biology-moc.md", _empty_tree)
        res = scan(v)
        h = res["hierarchy_diagnostic"]
        check("inactive disciplines remain visible without creating every enum MOC",
              [(row["discipline"], row["entries"], row["state"])
               for row in h["moc_file_states"]],
              [("biology", 0, "empty"), ("economics", 0, "missing"),
               ("physics", 0, "empty"), ("statistics", 2, "empty")])
        check("stale canonical and legacy MOCs are distinct preservation worklists",
              [(row["kind"], row.get("discipline")) for row in h["moc_inventory_findings"]],
              [("unexpected-moc", None), ("stale-moc", "biology"),
               ("legacy-location", "economics"), ("stale-moc", "physics"),
               ("legacy-location", "statistics")])
        check("canonical and old root copies remain visible as separate owners",
              [row["discipline"] for row in h["legacy_moc_states"]],
              ["economics", "statistics"])

        _st_write(v, "old-map-reader.md", _st_entry(
            "Old map reader", "**Old map reader** uses [[statistics-moc|Map]] "
            "and [[statistics-moc|Map]] for navigation.",
            related="[[statistics-moc|Map]]"))
        old_map_res = scan(v)
        check("an unexpected old root note stays a known body/footer owner without migration",
              [key for key in _st_keys(old_map_res, "old-map-reader")
               if key.startswith("item10/") or key == "item11"],
              ["item10/moc"] * 3)
        _st_write(v, "statistics-moc.md", _st_entry(
            "Statistics moc", "**Statistics moc** is a worked example.",
            aliases=('"specific-map"',)))
        _st_write(v, "qualified-map-reader.md", _st_entry(
            "Qualified map reader", "**Qualified map reader** uses "
            "[[Wiki/statistics-moc|Statistics moc]] and [[specific-map|Map]]."))  # Wiki entry, not a MOC.
        old_map_res = scan(v)
        check("a Wiki file beside an old root owner requires qualified resolution",
              ("item10/ambiguous" in _st_keys(old_map_res, "old-map-reader"),
               "[[Wiki/statistics-moc|Map]]" in _st_msg(  # Wiki entry, not a MOC.
                   old_map_res, "qualified-map-reader", "item10/alias"),
               "item10/dangling" in _st_keys(old_map_res, "qualified-map-reader")),
              (True, True, False))

        # Every line of a canonical MOC must belong to its generated outline.
        v = os.path.join(tmp, "v6-whole-file", "Wiki")
        vr = os.path.dirname(v)
        _st_write(v, "statistics.md", _st_entry("Statistics", "**Statistics** is a field."))
        for _name in ("First", "Middle", "Last"):
            _st_write(v, _name.lower() + ".md", _st_entry(
                _name, "**%s** is a worked example." % _name,
                parents=('"[[statistics]]"',)))
        _plain_tree = ("- [[Wiki/statistics|Statistics]]\n"
                       "  - [[Wiki/first|First]]\n"
                       "  - [[Wiki/middle|Middle]]\n"
                       "  - [[Wiki/last|Last]]\n")
        _st_write(vr, "MOCs/statistics-moc.md", "Personal introduction.\n" + _plain_tree
                  + "Personal conclusion.\n")
        res = scan(v)
        check("prose before and after the outline is malformed generated content",
              [(x["kind"], x.get("line"))
               for x in res["hierarchy_diagnostic"]["moc_consistency_findings"]],
              [("malformed-line", 1), ("malformed-line", 6)])
        for _name, _wrapped in (
                ("fenced", "```markdown\n" + _plain_tree + "```\n"),
                ("frontmatter", "---\ntitle: A map\n---\n" + _plain_tree),
                ("commented", "<!-- annotation\n" + _plain_tree + "-->\n")):
            _st_write(vr, "MOCs/statistics-moc.md", _wrapped)
            res = scan(v)
            _findings = res["hierarchy_diagnostic"]["moc_consistency_findings"]
            check("%s wrappers are validated as malformed whole-file content" % _name,
                  (res["hierarchy_diagnostic"]["moc_file_states"][0]["state"],
                   {x["kind"] for x in _findings}),
                  ("readable", {"malformed-line"}))
        _st_write(vr, "MOCs/statistics-moc.md", _plain_tree)
        res = scan(v)
        check("a complete generated MOC is clean and repeated scans leave its bytes unchanged",
              (res["hierarchy_diagnostic"]["moc_consistency_findings"], scan(v) == res,
               open(os.path.join(vr, "MOCs/statistics-moc.md"), encoding="utf-8").read()),
              ([], True, _plain_tree))

        for _name, _opening, _closing in (
                ("backtick fence", "```markdown", "```"),
                ("tilde fence", "~~~", "~~~"),
                ("HTML comment", "<!--", "-->"),
                ("Obsidian comment", "%%", "%%")):
            _hidden_tree = ("- " + _opening + "\n"
                            + "".join("  " + line + "\n"
                                      for line in _plain_tree.splitlines())
                            + "- " + _closing + "\n")
            _st_write(vr, "MOCs/statistics-moc.md", _hidden_tree)
            res = scan(v)
            check("a %s inside category bullets cannot appear to be a clean MOC" % _name,
                  [(x["kind"], x.get("line"))
                   for x in res["hierarchy_diagnostic"]["moc_consistency_findings"]],
                  [("malformed-line", 1), ("malformed-line", 6)])
        _st_write(vr, "MOCs/statistics-moc.md", "- [[Wiki/statistics|Statistics]]\n  - Visible category\n"
                  + "".join("  " + line + "\n" for line in _plain_tree.splitlines()[1:]))
        check("ordinary unlinked categories still support complete MOC placement",
              scan(v)["hierarchy_diagnostic"]["moc_consistency_findings"], [])

        # Fail closed without walking a linked directory or arbitrarily
        # choosing a portable directory/leaf collision. Injected listings make
        # the collision cases testable on case-insensitive filesystems too.
        vr = os.path.join(tmp, "v6f")
        os.makedirs(vr)
        _outside = os.path.join(tmp, "v6f-outside")
        _st_write(_outside, "statistics.md", _empty_tree)
        if _have_moc_symlink:
            os.symlink(_outside, os.path.join(vr, "MOCs"))
            _states, _legacy, _issues, _texts = inventory_mocs(vr, {"statistics": 1})
            check("a symlinked MOCs directory is blocked without importing its tree",
                  (_states[0]["state"], [row["kind"] for row in _issues], _texts),
                  ("unreadable", ["unsafe-directory"], {}))
            os.unlink(os.path.join(vr, "MOCs"))
        _st_write(vr, "MOCs", "occupied by a file")
        _states, _legacy, _issues, _texts = inventory_mocs(vr, {"statistics": 1})
        check("a regular file occupying MOCs is never an absent directory",
              (_states[0]["state"], [row["kind"] for row in _issues]),
              ("unreadable", ["unsafe-directory"]))
        os.unlink(os.path.join(vr, "MOCs"))
        from unittest import mock
        for _folder_names, _expected_kind in ((["mocs"], "noncanonical-directory"),
                                              (["MOCs", "mocs"], "ambiguous-directory")):
            with mock.patch.object(os, "listdir", return_value=_folder_names):
                _states, _legacy, _issues, _texts = inventory_mocs(vr, {"statistics": 1})
            check("portable MOCs folder ownership: " + _expected_kind,
                  (_states[0]["state"], [row["kind"] for row in _issues]),
                  ("unreadable", [_expected_kind]))
        _st_write(vr, "MOCs/statistics-moc.md", _empty_tree)
        _real_listdir = os.listdir
        for _leaf_names, _expected_kind in ((["Statistics-moc.md"], "noncanonical-moc"),
                                           (["statistics-moc.md", "Statistics-MOC.md"], "ambiguous-moc")):
            def _collision_listing(path):
                return _leaf_names if isinstance(path, int) else _real_listdir(path)
            with mock.patch.object(os, "listdir", side_effect=_collision_listing):
                _states, _legacy, _issues, _texts = inventory_mocs(vr, {"statistics": 1})
            check("portable MOC leaf ownership: " + _expected_kind,
                  (_states[0]["state"], [row["kind"] for row in _issues], _texts),
                  ("unreadable", [_expected_kind], {}))
        if _have_moc_symlink:
            _real_open = os.open
            _swapped = []
            def _swap_moc_directory_before_leaf(path, flags, *args, **kwargs):
                if kwargs.get("dir_fd") is not None and not _swapped:
                    os.rename(os.path.join(vr, "MOCs"), os.path.join(vr, "MOCs-original"))
                    os.symlink(_outside, os.path.join(vr, "MOCs"))
                    _swapped.append(True)
                return _real_open(path, flags, *args, **kwargs)
            with mock.patch.object(os, "open", side_effect=_swap_moc_directory_before_leaf):
                _states, _legacy, _issues, _texts = inventory_mocs(vr, {"statistics": 1})
            check("a MOCs directory swapped during reading invalidates the full snapshot",
                  (_states[0]["state"], [row["kind"] for row in _issues], _texts),
                  ("unreadable", ["unsafe-directory"], {}))

        # Misc is an explicit sole-tag discipline fallback. Blank tags remain
        # repair work, and never silently assign an entry to its MOC.
        v = os.path.join(tmp, "v6-misc", "Wiki")
        vr = os.path.dirname(v)
        for _slug, _title in (("alpha", "Alpha"), ("misc", "Misc"),
                              ("zeta-misc", "Zeta (misc)")):
            _text = _st_entry(_title, "**%s** is a worked example." % _title,
                              tags=('"#misc"',), parents=(() if _slug == "misc" else ('"[[misc]]"',)))
            _st_write(v, _slug + ".md", _text)
        _st_write(v, "topic.md", _st_entry(
            "Topic", "**Topic** is a worked example.",
            parents=('"[[statistics]]"',)))
        _st_write(v, "statistics.md", _st_entry("Statistics", "**Statistics** is a field."))
        _misc_tree = ("- [[Wiki/misc|Misc]]\n  - [[Wiki/alpha|Alpha]]\n"
                      "  - [[Wiki/zeta-misc|Zeta (misc)]]\n")
        _st_write(vr, "MOCs/misc-moc.md", _misc_tree)
        _st_write(vr, "MOCs/statistics-moc.md", "- [[Wiki/statistics|Statistics]]\n  - [[Wiki/topic|Topic]]\n")
        res = scan(v)
        h = res["hierarchy_diagnostic"]
        check("all parsed entries use one inventory and discipline counts include explicit misc",
              (res["inventory"], res["discipline_tags"], res["untagged_entries"]),
              ({"entries": 5, "slugs": ["alpha", "misc", "statistics", "topic", "zeta-misc"]},
               {"misc": 3, "statistics": 2}, []))
        check("a misc root and title-ordered members form a consistent concept hierarchy",
              [h[key] for key in ("moc_consistency_findings", "placement_gaps",
                                  "parent_state_findings", "unresolved_parents", "self_parented")],
              [[]] * 5)
        check("misc has ordinary file-state entry counts and belongs to the tag enum",
              ([(row["target"], row["entries"]) for row in h["moc_file_states"]],
               "misc" in VALID_TAGS),
              ([("MOCs/misc-moc", 3), ("MOCs/statistics-moc", 2)], True))
        _st_write(vr, "MOCs/misc-moc.md", "")
        res = scan(v)
        check("an empty active misc reports all missing members without an inactive-discipline finding",
              ([row["slug"] for row in res["hierarchy_diagnostic"]["moc_consistency_findings"]
                if row["kind"] == "missing-entry" and row.get("discipline") == "misc"],
               res["hierarchy_diagnostic"]["moc_inventory_findings"]),
              (["alpha", "misc", "zeta-misc"], []))
        os.unlink(os.path.join(vr, "MOCs/misc-moc.md"))
        res = scan(v)
        check("a missing misc MOC does not invalidate real Wiki parent links",
              [(row["slug"], row["target"], row["reason"])
               for row in res["hierarchy_diagnostic"]["unresolved_parents"]],
              [])
        _st_write(vr, "MOCs/misc-moc.md", _misc_tree.splitlines()[0] + "\n" + "\n".join(reversed(_misc_tree.splitlines()[1:])) + "\n")
        res = scan(v)
        check("misc order is deterministic by canonical title rather than prior insertion order",
              [row["kind"] for row in res["hierarchy_diagnostic"]["moc_consistency_findings"]],
              ["misc-order"])
        _st_write(vr, "MOCs/misc-moc.md", "- [[Wiki/misc|Misc]]\n  - Group\n    - [[Wiki/alpha|Alpha]]\n"
                  "  - [[Wiki/zeta-misc|Zeta (misc)]]\n")
        res = scan(v)
        check("misc categories and nested members are rejected as non-flat generated content",
              [(row["kind"], row.get("line"))
               for row in res["hierarchy_diagnostic"]["moc_consistency_findings"]],
              [("misc-format", 2), ("misc-format", 3)])
        _st_write(vr, "MOCs/misc-moc.md", _misc_tree)
        _st_write(v, "alpha.md", _st_entry(
            "Alpha", "**Alpha** is a worked example.", tags=('"#misc"',),
            parents=('"[[misc]]"',)))
        res = scan(v)
        check("a misc member points to its Wiki root without a placement gap",
              ([(row["slug"], row["kind"])
                for row in res["hierarchy_diagnostic"]["parent_state_findings"]],
               res["hierarchy_diagnostic"]["placement_gaps"]),
              ([], []))
        _st_write(v, "alpha.md", _st_entry(
            "Alpha", "**Alpha** is a worked example.", tags=('"#misc"',),
            parents=('"[[Wiki/misc]]"',)))
        res = scan(v)
        check("a qualified misc parent is respelled bare once the MOC name differs",
              ('resolves to "misc"' in _st_msg(res, "alpha", "item2/parents-form"),
               [row["kind"] for row in res["hierarchy_diagnostic"]["parent_state_findings"]
                if row["slug"] == "alpha"]),
              (True, ["misc-parent-mismatch"]))
        _st_write(vr, "MOCs/misc.md", _misc_tree)
        _st_write(v, "alpha.md", _st_entry(
            "Alpha", "**Alpha** is a worked example.", tags=('"#misc"',),
            parents=('"[[misc]]"',)))
        res = scan(v)
        check("a previous-layout misc MOC keeps a bare misc parent ambiguous",
              [(row["slug"], row["reason"])
               for row in res["hierarchy_diagnostic"]["unresolved_parents"]
               if row["slug"] == "alpha"],
              [("alpha", "ambiguous")])
        os.unlink(os.path.join(vr, "MOCs/misc.md"))
        _st_write(v, "alpha.md", _st_entry(
            "Alpha", "**Alpha** is a worked example.",
            parents=('"[[MOCs/misc-moc]]"',)))
        res = scan(v)
        _findings = res["hierarchy_diagnostic"]["moc_consistency_findings"]
        check("retagging out of misc exposes both its stale misc listing and absent discipline listing",
              ([(row["kind"], row["discipline"])
                for row in _findings if row.get("slug") == "alpha"],
               res["hierarchy_diagnostic"]["placement_gaps"]),
              ([("wrong-discipline-link", "misc"), ("missing-entry", "statistics")],
               [{"slug": "alpha", "missing_disciplines": ["statistics"], "represented_disciplines": []}]))
        _st_write(v, "topic.md", _st_entry(
            "Topic", "**Topic** is a worked example.", tags=('"#misc"',),
            parents=('"[[MOCs/statistics-moc]]"',)))
        res = scan(v)
        check("retagging into misc exposes missing misc membership and the stale discipline placement",
              [(row["kind"], row["discipline"])
               for row in res["hierarchy_diagnostic"]["moc_consistency_findings"]
               if row.get("slug") == "topic"],
              [("missing-entry", "misc"), ("wrong-discipline-link", "statistics")])

        v = os.path.join(tmp, "v6-misc-invalid-tags", "Wiki")
        vr = os.path.dirname(v)
        _bad_tags = {
            "missing": "", "null": "tags: null\n", "scalar": 'tags: ""\n',
            "commas": "tags: [,]\n", "null-item": "tags:\n  - null\n",
            "empty-item": 'tags:\n  - ""\n', "unquoted-item": "tags:\n  - #statistics\n",
            "unquoted-scalar": "tags: #statistics\n", "bad-block": "tags:\n  not-a-list\n",
            "duplicate": "tags:\ntags:\n", "off-enum": 'tags:\n  - "#unknown"\n',
        }
        _ambiguous_tag_keys = {
            "double-quoted-key": '"tags": ["#statistics"]\ntags: []\n',
            "single-quoted-key": "'tags': ['#statistics']\ntags:\n",
            "escaped-key": '"\\u0074ags": ["#statistics"]\ntags: []\n',
            "explicit-key": '? tags\n: ["#statistics"]\ntags:\n',
            "malformed-key": '"tags: ["#statistics"]\ntags:\n',
        }
        _bad_tags.update(_ambiguous_tag_keys)
        for _name, _tags in _bad_tags.items():
            _title = _name.replace("-", " ").title()
            _st_write(v, _name + ".md", _st_entry(
                _title, "**%s** is a worked example." % _title, tags=(),
                parents=('"[[MOCs/misc-moc]]"',)).replace("tags: []\n", _tags))
        _st_write(vr, "MOCs/misc-moc.md", "".join(
            "- [[Wiki/%s|%s]]\n" % (name, name.replace("-", " ").title())
            for name in sorted(_bad_tags)))
        res = scan(v)
        check("missing, scalar, malformed, and invalid tag data never becomes valid misc membership",
              (res["untagged_entries"],
               all(any(key.startswith(("item1", "item2", "item8"))
                       for key in _st_keys(res, name)) for name in _bad_tags)),
              ([], True))
        check("misc rejects every listed entry whose tags were malformed or off-enum",
              sorted(row["slug"] for row in res["hierarchy_diagnostic"]["moc_consistency_findings"]
                     if row["kind"] == "wrong-discipline-link"), sorted(_bad_tags))
        check("ignored quoted, escaped, explicit, or malformed tag keys cannot turn a later empty field into misc",
              [(name, name in res["untagged_entries"],
                {"item1", "item8"}.issubset(_st_keys(res, name)))
               for name in sorted(_ambiguous_tag_keys)],
              [(name, False, True) for name in sorted(_ambiguous_tag_keys)])
        _st_write(vr, "MOCs/misc-moc.md", "")
        res = scan(v)
        check("an authorized zero-member misc refresh leaves a clean empty file without deleting its identity",
              ([(row["target"], row["entries"], row["state"])
                for row in res["hierarchy_diagnostic"]["moc_file_states"]],
               res["hierarchy_diagnostic"]["moc_consistency_findings"],
               res["hierarchy_diagnostic"]["moc_inventory_findings"]),
              ([("MOCs/misc-moc", 0, "empty")], [], []))
        _st_write(v, "field-qc.md", _st_entry(
            "Field QC", "**Field QC** is a worked example.", tags=(),
            parents=('"[[MOCs/misc-moc]]"',), sources=('"invalid-source"',)).replace(
                "type: Concept\n", "type: Invalid\n"))
        res = scan(v)
        check("ordinary field-value QC does not erase the proven empty-tag repair worklist",
              (res["untagged_entries"],
               {"item2/type-enum", "item4"}.issubset(_st_keys(res, "field-qc"))),
              (["field-qc"], True))

        v = os.path.join(tmp, "v6-misc-tag-rules", "Wiki")
        vr = os.path.dirname(v)
        _tag_forms = {
            "valid-block": 'tags:\n  - "#misc"\n',
            "valid-flow": 'tags: ["#misc"]\n',
            "blank-block": 'tags:\n',
            "blank-flow": 'tags: []\n',
            "mixed": 'tags:\n  - "#misc"\n  - "#statistics"\n',
            "twice": 'tags:\n  - "#misc"\n  - "#misc"\n',
            "null-companion": 'tags: ["#misc", null]\n',
            "empty-companion": 'tags: ["#misc", ""]\n',
            "scalar-misc": 'tags: "#misc"\n',
            "unprefixed-misc": 'tags:\n  - "misc"\n',
            "cased-misc": 'tags:\n  - "#Misc"\n',
            "duplicate-key": 'tags: ["#misc"]\ntags: ["#misc"]\n',
            "quoted-key": '"tags": ["#statistics"]\ntags: ["#misc"]\n',
        }
        for _name, _tags in _tag_forms.items():
            _title = _name.replace("-", " ").title()
            _st_write(v, _name + ".md", _st_entry(
                _title, "**%s** is a worked example." % _title, tags=(),
                parents=('"[[MOCs/misc-moc]]"',)).replace("tags: []\n", _tags))
        _st_write(vr, "MOCs/misc-moc.md", "".join(
            "- [[Wiki/%s|%s]]\n" % (name, name.replace("-", " ").title())
            for name in sorted(_tag_forms)))
        res = scan(v)
        h = res["hierarchy_diagnostic"]
        check("only an explicit valid sole misc tag supplies Misc membership, while observed tag counts retain invalid claims",
              ([(row["discipline"], row["entries"]) for row in h["moc_file_states"]],
               res["discipline_tags"], res["untagged_entries"]),
              ([("misc", 2), ("statistics", 1)],
               {"misc": 11, "statistics": 1}, ["blank-block", "blank-flow"]))
        check("blank tags and malformed, mixed, duplicate, or noncanonical misc values cannot enter the Misc tree",
              sorted(row["slug"] for row in h["moc_consistency_findings"]
                     if row["kind"] == "wrong-discipline-link"),
              sorted(set(_tag_forms) - {"valid-block", "valid-flow"}))
        check("blank tags require repair and duplicate canonical misc values retain duplicate QC",
              (all("exactly one discipline tag" in _st_msg(res, name, "item8")
                   for name in ("blank-block", "blank-flow")),
               "#misc must be the sole tag" in _st_msg(res, "mixed", "item8"),
               'discipline "#misc" tagged more than once' in _st_msg(res, "twice", "item8")),
              (True, True, True))
        check("a mixed misc entry retains its specific-discipline placement diagnostics",
              h["placement_gaps"],
              [{"slug": "mixed", "missing_disciplines": ["statistics"], "represented_disciplines": []},
               {"slug": "valid-block", "missing_disciplines": ["misc"], "represented_disciplines": []},
               {"slug": "valid-flow", "missing_disciplines": ["misc"], "represented_disciplines": []}])
        check("a valid misc block is clean and a valid flow list has only its normal layout QC",
              ("item8" in _st_keys(res, "valid-block"),
               "flow-list syntax" in _st_msg(res, "valid-flow", "item8"),
               "#misc must be the sole tag" in _st_msg(res, "valid-flow", "item8")),
              (False, True, False))
        _st_write(v, "blank-block.md", _st_entry(
            "Blank Block", "**Blank Block** is a worked example.",
            tags=('"#misc"',), parents=('"[[MOCs/misc-moc]]"',)))
        res = scan(v)
        check("repairing blank tags to explicit misc establishes membership and removes the stale-listing diagnostic",
              (res["untagged_entries"],
               next(row["entries"] for row in res["hierarchy_diagnostic"]["moc_file_states"]
                    if row["discipline"] == "misc"),
               [row["kind"] for row in res["hierarchy_diagnostic"]["moc_consistency_findings"]
                if row.get("slug") == "blank-block"]),
              (["blank-flow"], 3, ["parent-union-mismatch"]))
        _st_write(vr, "misc-moc.md", "An unrelated root note.\n")
        _st_write(v, "valid-block.md", _st_entry(
            "Valid Block", "**Valid Block** is a worked example.",
            tags=('"#misc"',), parents=('"[[misc-moc]]"',)))
        res = scan(v)
        check("a root note named like the misc MOC is not legacy, and a bare link to that name is ambiguous",
              (res["hierarchy_diagnostic"]["legacy_moc_states"],
               [(row["target"], row["reason"])
                for row in res["hierarchy_diagnostic"]["unresolved_parents"]
                if row["slug"] == "valid-block"]),
              ([], [("misc-moc", "ambiguous")]))

        # ------------------------------------------------------------------
        # 7. rename candidates -- `target_exists` is the ONLY thing standing
        #    between an approved rename and `mv wrong-name.md broken.md` over
        #    a file the user still has.  Every destination that a file already
        #    answers to must read True, whether or not that file PARSED.
        # ------------------------------------------------------------------
        v = os.path.join(tmp, "v7")
        _st_write(v, "broken.md", "no frontmatter at all, so this never parses\n")
        _st_write(v, "wrong-name.md", _st_entry(
            "Broken", "**Broken** is a worked example."))
        _st_write(v, "free-name.md", _st_entry(
            "Unoccupied", "**Unoccupied** is a worked example."))
        _st_write(v, "taken-name.md", _st_entry(
            "Occupied", "**Occupied** is a worked example."))
        _st_write(v, "occupied.md", _st_entry(
            "Occupied elsewhere", "**Occupied elsewhere** is a worked example."))
        _st_write(v, "recall-owner.md", _st_entry(
            "Recall owner", "**Recall owner** is a worked example.",
            aliases=('"tpr"',)))
        _st_write(v, "true-pos.md", _st_entry(
            "TPR", "**TPR** is a worked example."))
        _st_write(v, "own-alias-old.md", _st_entry(
            "Own alias", "**Own alias** is a worked example.",
            aliases=('"own-alias"',)))
        _st_write(v, "a/path-old.md", _st_entry(
            "Alpha renamed", "**Alpha renamed** is a worked example."))
        _st_write(v, "b/path-old.md", _st_entry(
            "Beta renamed", "**Beta renamed** is a worked example."))
        for _name in ("shared-old-a", "shared-old-b"):
            _st_write(v, _name + ".md", _st_entry(
                "Shared destination",
                "**Shared destination** is a worked example."))
        _st_write(v, "rename-reader.md", _st_entry(
            "Rename reader", "**Rename reader** links "
            "[[a/path-old|Alpha renamed]] and "
            "[[Wiki/a/path-old.md#Details|Alpha renamed]] to one owner, "
            "[[b/path-old|Beta renamed]] to the other, and leaves the bare "
            "[[path-old]] ambiguous."))
        res = scan(v)
        _tx = {r["slug"]: r["target_exists"] for r in res["rename_candidates"]}
        check("a rename onto a file that is ON DISK but did not parse is "
              "target_exists (the approved `mv` would destroy it)",
              _tx.get("wrong-name"), True)
        check("...and the unparsed file is still reported in its own right",
              ("broken", "item1") in _st_items(res), True)
        check("NEAR MISS: a rename onto a genuinely free destination stays "
              "target_exists: false",
              _tx.get("free-name"), False)
        check("a rename onto a destination held by a PARSED entry is still "
              "target_exists",
              _tx.get("taken-name"), True)
        check("a rename onto another entry's alias is target_exists; onto "
              "the entry's own alias it is not",
              (_tx.get("true-pos"), _tx.get("own-alias-old")), (True, False))
        check("two renames onto one free destination are both target_exists, "
              "so the second can never overwrite the first",
              (_tx.get("shared-old-a"), _tx.get("shared-old-b")), (True, True))
        _st_write(v, "typo.md", _st_entry(
            "Typo", "**Typo** is a worked example.").replace(
                "read: false", "read:false"))
        _gap_res = scan(v)
        check("an alias-inventory gap elsewhere does not hide a known alias "
              "owner from target_exists",
              (("typo", "item1") in _st_items(_gap_res),
               {r["slug"]: r["target_exists"]
                for r in _gap_res["rename_candidates"]}.get("true-pos")),
              (True, True))
        os.remove(os.path.join(v, "typo.md"))
        _path_rename = next(r for r in res["rename_candidates"]
                            if r["slug"] == "path-old")
        check("rename inbound counts resolve path-qualified and explicit-.md links "
              "without assigning ambiguous or other-path links to the candidate",
              _path_rename["inbound_links"], 2)

        # ------------------------------------------------------------------
        # 8. item 10 again -- the two ways a RESOLVING link was called
        #    dangling.  Both remedies write a file; both are destructive.
        # ------------------------------------------------------------------
        v = os.path.join(tmp, "v8")
        _st_write(v, "recall.md", _st_entry(
            "Recall", "**Recall** is a worked example.", aliases=('"tpr"',),
            card="Recall"))
        _st_write(v, "linker.md", _st_entry(
            "Linker", "**Linker** is a worked example that links [[tpr]] and "
                      "[[genuinely-absent]]."))
        _st_write(v, "listing.md", _st_entry(
            "Listing",
            "**Listing** is a worked example.\n\n"
            "```\nSee [[target-note]] for the syntax\n```\n\n"
            "It links [[sub-note]] once in prose, and shows the same link in "
            "`[[sub-note]]` form inline.",
            type_="Software"))
        _st_write(v, "sub-note.md", _st_entry(
            "Sub note", "**Sub note** is a worked example."))
        res = scan(v)
        check("a link to another entry's ALIAS is item10/alias, never a dangler",
              ("item10/alias" in _st_keys(res, "linker"),
               "tpr" in _st_msg(res, "linker", "item10/dangling")),
              (True, False))
        check("...and it names the owning entry and the piped rewrite",
              ('[[recall|tpr]]' in _st_msg(res, "linker", "item10/alias"),
               "new same-named note" in _st_msg(res, "linker", "item10/alias")),
              (True, True))
        check("NEAR MISS: a target that is neither entry nor alias is still "
              "item10/dangling",
              "genuinely-absent" in _st_msg(res, "linker", "item10/dangling"), True)
        check("a wikilink inside a FENCED block is not a dangling target "
              "(the remedy would create a file for a listing)",
              "target-note" in " ".join(p["message"] for p in res["problems"]), False)
        check("a wikilink inside an INLINE code span is not one either",
              _st_keys(res, "listing"), [])
        check("...so a target shown in a code span and linked once in prose is "
              "linked ONCE, not twice",
              "item10/dup" in _st_keys(res, "listing"), False)
        # An alias must not shadow item10/case: a FILE outranks an alias in
        # Obsidian, and the two findings have opposite fixes (rewrite the
        # target's spelling vs. pipe the link through the owner).
        v = os.path.join(tmp, "v8b")
        _st_write(v, "recall.md", _st_entry(
            "Recall", "**Recall** is a worked example.", aliases=('"tpr"',),
            card="Recall"))
        _st_write(v, "TPR.md", _st_entry("TPR", "**TPR** is a worked example."))
        _st_write(v, "caselink.md", _st_entry(
            "Caselink", "**Caselink** is a worked example linking [[tpr]]."))
        res = scan(v)
        check("NEAR MISS: a case-variant FILE outranks an alias of the same "
              "name — item10/case, not item10/alias",
              (_st_keys(res, "caselink"), "TPR" in _st_msg(res, "caselink", "item10/case")),
              (["item10/case"], True))

        # All THREE markdown spellings of a listing, and the look-alikes that
        # are not listings at all.  A check that knows only fenced blocks is a
        # rule about backticks, not about listings, and the entry written the
        # other way gets the finding whose remedy creates a file.
        v = os.path.join(tmp, "v8c")
        _listings = [
            # slug,     body after the opener,                          dangling?
            ("dbl",     "showing ``[[double-target]]`` inline.",         False),
            ("ind",     "\n\nLike this:\n\n    [[indented-target]]\n\nDone.", False),
            ("tabbed",  "\n\nLike this:\n\n\t[[tab-target]]\n\nDone.",   False),
            # ...and the three that are NOT code and must still be checked:
            # a list item's continuation content is indented for its own
            # reason, at one level and at two,
            ("lst",     "\n\n- a bullet\n\n    a continuation naming "
                        "[[list-target]].\n\nDone.",                     True),
            ("nested",  "\n\n- outer\n  - inner\n\n      a continuation "
                        "naming [[deep-target]].\n\nDone.",              True),
            # and an indented line with no blank line above it does not start
            # a code block at all -- it cannot interrupt a paragraph.
            ("interrupt", "\n    still the same paragraph, [[para-target]].", True),
        ]
        for _slug, _tail, _dangles in _listings:
            _st_write(v, _slug + ".md", _st_entry(
                _slug.title(), "**%s** is a worked example %s" % (_slug.title(), _tail),
                card=_slug.title()))
        # a 4-backtick fence WRAPPING a 3-backtick sample: CommonMark closes a
        # fence only on a >= run of the same character, so the whole thing is
        # one listing -- a blind toggle read the inner ``` as the close and the
        # [[link]] came back dangling (Software type, so item 6 stays quiet)
        _st_write(v, "quadfence.md", _st_entry(
            "Quadfence",
            "**Quadfence** is a worked example.\n\n"
            "````\n```\nSee [[quad-target]] for the syntax\n```\n````",
            type_="Software", card="Quadfence"))
        res = scan(v)
        check("a 4-backtick fence wrapping a 3-backtick sample is ONE listing, "
              "so its [[link]] is not a dangling target",
              _st_keys(res, "quadfence"), [])
        for _slug, _tail, _dangles in _listings:
            check("a wikilink in %s %s a dangling target"
                  % ({"dbl": "a DOUBLE-BACKTICK code span",
                      "ind": "a 4-SPACE INDENTED code block",
                      "tabbed": "a TAB-INDENTED code block",
                      "lst": "NEAR MISS: a list item's continuation",
                      "nested": "NEAR MISS: a nested list item's continuation",
                      "interrupt": "NEAR MISS: an indented line continuing a "
                                   "paragraph (no blank line above it)"}[_slug],
                     "is" if _dangles else "is NOT"),
                  "item10/dangling" in _st_keys(res, _slug), _dangles)
        check("...and none of the six produces any OTHER finding",
              sorted({k for _s, _t, _d in _listings for k in _st_keys(res, _s)}),
              ["item10/dangling"])

        # ------------------------------------------------------------------
        # 9. item 18 alias collisions, item 6 / item 12 fence spellings,
        #    the mandatory-key floor, and the date ordering compare
        # ------------------------------------------------------------------
        v = os.path.join(tmp, "v9")
        _st_write(v, "cased-a.md", _st_entry(
            "Cased a", "**Cased a** is a worked example.", aliases=('"lambda-rank"',)))
        _st_write(v, "cased-b.md", _st_entry(
            "Cased b", "**Cased b** is a worked example.", aliases=('"Lambda-Rank"',)))
        _st_write(v, "distinct.md", _st_entry(
            "Distinct", "**Distinct** is a worked example.", aliases=('"lambdarank"',)))
        res = scan(v)
        check("two aliases differing only in CASE are an item-18 collision "
              "(they are one name to Obsidian, and nobody else reports it)",
              ("item18" in _st_keys(res, "cased-b"),
               '"cased-a"' in _st_msg(res, "cased-b", "item18")), (True, True))
        check("...and the message keeps both raw spellings",
              ('"Lambda-Rank"' in _st_msg(res, "cased-b", "item18")
               and '"lambda-rank"' in _st_msg(res, "cased-b", "item18")), True)
        check("NEAR MISS: a genuinely different alias is not a collision",
              "item18" in _st_keys(res, "distinct"), False)

        v = os.path.join(tmp, "v10")
        _st_write(v, "tilde.md", _st_entry(
            "Tilde", "**Tilde** is a worked example.\n\n~~~\nmake install\n~~~"))
        _st_write(v, "backtick.md", _st_entry(
            "Backtick", "**Backtick** is a worked example.\n\n```\nmake install\n```"))
        _st_write(v, "tilde-sw.md", _st_entry(
            "Tilde sw", "**Tilde sw** is a worked example.\n\n~~~\necho $HOME\n~~~",
            type_="Software"))
        _st_write(v, "tilde-dollar.md", _st_entry(
            "Tilde dollar",
            "**Tilde dollar** is a worked example costing 5$ to run.\n\n"
            "~~~\necho $HOME $PATH\n~~~", type_="Software"))
        _st_write(v, "capzero.md", _st_entry(
            "Capzero", "**Capzero** is a worked example (`SomeClass` names it)."))
        _st_write(v, "capzero-sw.md", _st_entry(
            "Capzero sw", "**Capzero sw** is a worked example (`SomeClass` names it).",
            type_="Software"))
        _st_write(v, "extonly.md", _st_entry(
            "Extonly", "**Extonly** is a worked example saving `.csv` files."))
        _st_write(v, "tokenonly.md", _st_entry(
            "Tokenonly", "**Tokenonly** is a worked example using `[CLS]`."))
        _st_write(v, "bare-ext.md", _st_entry(
            "Bare ext", "**Bare ext** is a worked example saving .csv files."))
        _st_write(v, "bare-token.md", _st_entry(
            "Bare token", "**Bare token** is a worked example using [CLS]."))
        _st_write(v, "dot-near-misses.md", _st_entry(
            "Dot near misses",
            "**Dot near misses** reports 3.5 at example.com in results.csv."))
        _st_write(v, "linked-token.md", _st_entry(
            "Linked token",
            "**Linked token** uses [CLS](https://example.test/token.md).\n\n"
            "![[MASK]]\n*An image whose basename resembles a special token.*"))
        _st_write(v, "typography-zones.md", _st_entry(
            "Typography zones", "**Typography zones** is a worked example.\n\n"
            "## Files named .csv\n\n"
            "Format | Token\n--- | ---\n.csv | [CLS]\n"
            "*A .csv lookup table.*\n\n"
            "```text\n[CLS] .csv\n```", type_="Software"))
        res = scan(v)
        check("a ~~~ fence is a fenced code block for item 6, exactly as ``` is",
              (_st_keys(res, "tilde"), _st_keys(res, "backtick")),
              (["item6"], ["item6"]))
        check("a $ inside a ~~~ listing is not an unescaped literal $ "
              "(item 12's fix would write \\$ into the command)",
              _st_keys(res, "tilde-sw"), [])
        check("NEAR MISS: a literal $ in PROSE is still item12, and counted once",
              ("item12" in _st_keys(res, "tilde-dollar"),
               _st_msg(res, "tilde-dollar", "item12").startswith("1 unescaped")),
              (True, True))
        check("one backticked identifier in a non-Software entry exceeds the zero cap",
              ("item6" in _st_keys(res, "capzero"),
               "cap is 0" in _st_msg(res, "capzero", "item6")), (True, True))
        check("...the same identifier in Software is mechanically exempt; "
              "the executing agent selects semantically",
              _st_keys(res, "capzero-sw"), [])
        check("NEAR MISS: a bare backticked file extension is not an identifier",
              _st_keys(res, "extonly"), [])
        check("NEAR MISS: a backticked bracket special token is not an identifier",
              _st_keys(res, "tokenonly"), [])
        check("bare literal extensions and known bracket tokens are item 16",
              (_st_keys(res, "bare-ext"), _st_keys(res, "bare-token")),
              (["item16"], ["item16"]))
        check("decimals, domains, and extensions attached to filenames stay quiet",
              _st_keys(res, "dot-near-misses"), [])
        check("Markdown-link and Obsidian-embed syntax is not a bare special token",
              _st_keys(res, "linked-token"), [])
        check("tables, headings, captions, and listings keep their own typography rules",
              _st_keys(res, "typography-zones"), [])

        v = os.path.join(tmp, "v11")
        _clean = _st_entry("Whole", "**Whole** is a worked example.")
        _st_write(v, "no-title.md", _clean.replace('title: "Whole"\n', ""))
        _st_write(v, "no-type.md", _clean.replace("type: Concept\n", ""))
        _st_write(v, "no-sources.md",
                  _clean.replace('sources:\n  - "[[Doe_X_2025.pdf#page=2]]"\n', ""))
        _st_write(v, "blank-title.md", _clean.replace('title: "Whole"', "title:"))
        _st_write(v, "unbolded.md", _st_entry(
            "Unbolded", "Unbolded is a worked example with no bold opener.",
            card="Unbolded"))
        _st_write(v, "unbolded-whitespace.md", _st_entry(
            "Unbolded whitespace",
            "Unbolded whitespace starts without emphasis.\n   \n"
            "Later, **Unbolded whitespace** is named in another paragraph.",
            card="Unbolded whitespace"))
        _st_write(v, "counterpart-whitespace.md", _st_entry(
            "Principal component analysis",
            "**Principal component analysis** reduces dimensionality.\n   \n"
            "Later, **Principal component analysis** (PCA) appears as an "
            "abbreviation example.",
            aliases=('"pca"',), card="Principal component analysis"))
        _st_write(v, "wrapped-meeting.md", _st_entry(
            "Wrapped meeting", "The **Wrapped\nmeeting** (1975) was a worked example.",
            type_="Event"))
        _st_write(v, "whole.md", _clean)
        res = scan(v)
        check("a missing title: key is an item2 — without it item 5, item 16 "
              "and the rename candidate are all silent no-ops",
              ("item2" in _st_keys(res, "no-title"),
               "missing title" in _st_msg(res, "no-title", "item2")), (True, True))
        check("a title: key with NO VALUE is the same item2 (every gated check "
              "reads the value, not the key)",
              (_st_keys(res, "blank-title"),
               "carries no value" in _st_msg(res, "blank-title", "item2")),
              (["item2"], True))
        check("a entry whose opener has NO bold span at all is item16",
              (_st_keys(res, "unbolded"),
               "no bold span" in _st_msg(res, "unbolded", "item16")),
              (["item16"], True))
        check("a whitespace-only blank line ends the opener for item 16",
              "no bold span" in _st_msg(
                  res, "unbolded-whitespace", "item16"), True)
        check("a bold title hard-wrapped inside the opener is found with its date",
              _st_keys(res, "wrapped-meeting"), [])
        check("a later paragraph cannot establish the flashcard counterpart",
              "item19" in _st_keys(res, "counterpart-whitespace"), False)
        check("a missing type: key is an item2 too",
              "missing type: key" in _st_msg(res, "no-type", "item2"), True)
        check("...and a missing sources: key",
              "missing sources: key" in _st_msg(res, "no-sources", "item2"), True)
        check("NEAR MISS: an entry carrying all nine mandatory keys reports none",
              _st_keys(res, "whole"), [])

        # The item-3 date pair, in the four combinations that separate a
        # FORMAT finding from an ORDERING one.  The two must not be conflated
        # in either direction: a raw-string compare invents an ordering
        # violation on a correctly ordered entry (row 1) and misses a real one
        # (row 3), while regex-gating the ORDERING check on the format rule
        # (rather than only the format finding) silently drops rows 3 and 4 —
        # trading the false positive for a false negative.  `2026-2-05` names
        # one day and nothing else, so it is ordered; that it is also badly
        # spelled is a separate finding on a separate line.
        v = os.path.join(tmp, "v12")
        _dates = [
            # slug,       created,        updated,      ordering?, format?
            ("ok-unpad",  "2026-1-1",     "2026-01-02",  False, True),
            ("rev-pad",   "2026-12-01",   "2026-02-05",  True,  False),
            ("rev-unpad", "2026-12-01",   "2026-2-05",   True,  True),
            ("rev-both",  "2026-3-01",    "2026-1-02",   True,  True),
        ]
        for _slug, _c, _u, _ord, _fmt in _dates:
            _st_write(v, _slug + ".md",
                      _st_entry(_slug, "**%s** is a worked example." % _slug)
                      .replace("created: 2026-01-01", "created: " + _c)
                      .replace("updated: 2026-01-02", "updated: " + _u))
        res = scan(v)
        for _slug, _c, _u, _ord, _fmt in _dates:
            check("created %s / updated %s -> ordering finding: %s"
                  % (_c, _u, _ord),
                  "item3/report-only" in _st_keys(res, _slug), _ord)
            check("...and its FORMAT finding is independent of that: %s" % _fmt,
                  "not YYYY-MM-DD" in _st_msg(res, _slug, "item3"), _fmt)
        check("a well-formed, correctly ordered pair produces neither finding",
              [k for k in _st_keys(res, "ok-unpad") if k == "item3/report-only"], [])

        # ------------------------------------------------------------------
        # 10. --images: the Sources/Images/ embed check CONVENTIONS §1 makes
        #     this skill's, and which had no path to the folder at all.
        # ------------------------------------------------------------------
        v = os.path.join(tmp, "v13")
        _imgdir = os.path.join(tmp, "v13-images")
        os.makedirs(_imgdir)
        for _f in ("Doe_X_2025_fig_2.png", "doe_x_2025_fig_3.png",
                   "Doe_X_2025_fig_4.ico", "Garci\u0301a_X_2025_fig_5.png"):
            open(os.path.join(_imgdir, _f), "w", encoding="utf-8").close()
        # Valid sidecars/OS metadata stay quiet.  Nested and staging residue is
        # reported without making a nested-but-resolving embed look missing.
        for _f in (".figure-manifest.tsv", ".figure-review.txt", ".DS_Store"):
            open(os.path.join(_imgdir, _f), "w", encoding="utf-8").close()
        os.makedirs(os.path.join(_imgdir, "nested"))
        open(os.path.join(_imgdir, "nested", ".DS_Store"), "w",
             encoding="utf-8").close()
        open(os.path.join(_imgdir, "nested", "nested-only.png"), "w",
             encoding="utf-8").close()
        open(os.path.join(_imgdir, "Collision.png"), "w",
             encoding="utf-8").close()
        open(os.path.join(_imgdir, "nested", "collision.PNG"), "w",
             encoding="utf-8").close()
        os.makedirs(os.path.join(_imgdir, ".tmp"))
        open(os.path.join(_imgdir, ".tmp", "dl_1"), "w",
             encoding="utf-8").close()
        open(os.path.join(_imgdir, ".trash_run.dltmp_1"), "w",
             encoding="utf-8").close()
        _figbody = (
            "**Figured** is a worked example.\n\n"
            "![[Doe_X_2025_fig_99.png]]\n*A figure that is not on disk.*\n\n"
            "![[Doe_X_2025_fig_2.png]]\n*A figure that is.*\n\n"
            "![[Sources/Images/Doe_X_2025_fig_2.png]]\n*The same file, path-qualified.*\n\n"
            "![[Doe_X_2025_FIG_3.png]]\n*The same file in another case.*\n\n"
            "![[Garc\u00eda_X_2025_fig_5.png]]\n*The same file in another Unicode normalization.*\n\n"
            "![[nested-only.png]]\n*A nested file that still resolves.*\n\n"
            "![[COLLISION.PNG]]\n*A portable-colliding basename that remains present.*\n\n"
            "![[Doe_X_2025_fig_4.ico]]\n*An ICO that resolves.*\n\n"
            "![[Doe_X_2025_fig_100.ico]]\n*An ICO that is not on disk.*\n\n"
            "```\n![[Doe_X_2025_fig_98.png]]\n```")
        _st_write(v, "figured.md", _st_entry("Figured", _figbody))
        res_noimg = scan(v)
        res = scan(v, _imgdir)
        check("without --images nothing checks the embeds (the old behaviour, "
              "and the whole bug)",
              "item12/missing-image" in _st_keys(res_noimg, "figured"), False)
        check("an embed naming a file that is NOT in the image folder is "
              "item12/missing-image",
              ("item12/missing-image" in _st_keys(res, "figured"),
               "fig_99" in _st_msg(res, "figured", "item12/missing-image")),
              (True, True))
        _missing_msg = _st_msg(res, "figured", "item12/missing-image")
        check("...and it says not to delete or hand-patch the embed, since "
              "pdf-organize's rename rewrites embeds in its own run",
              ("DO NOT DELETE" in _missing_msg,
               "rewrites embeds in the same run" in _missing_msg,
               "embed is rewritten" in _missing_msg), (True, True, False))
        check("an .ico emitted by clipping-clean uses the same existence "
              "check as every other supported image extension",
              "fig_100.ico" in _st_msg(res, "figured", "item12/missing-image"), True)
        check("an NFC embed of an NFD-named image file is not missing",
              "fig_5" in _st_msg(res, "figured", "item12/missing-image"), False)
        check("NEAR MISS: an embed present under the portable identity — bare, "
              "path-qualified, in another case, or from a "
              "nested legacy folder — is clean, and a fenced sample of embed "
              "syntax is not an embed; the existing ICO is clean",
              _st_msg(res, "figured", "item12/missing-image").count(
                  "not in the image folder"), 2)
        _folder_findings = {
            (finding["path"], finding["kind"])
            for finding in res["image_folder_findings"]
        }
        check("nested directories/files and recognizable staging residue are "
              "reported outside per-entry problems",
              _folder_findings,
              {(".tmp", "temporary-artifact"),
               (".tmp/dl_1", "temporary-artifact"),
               (".trash_run.dltmp_1", "temporary-artifact"),
               ("Collision.png", "portable-name-collision"),
               ("nested", "nested-directory"),
               ("nested/collision.PNG", "nested-file"),
               ("nested/nested-only.png", "nested-file")})
        _portable_collision = [
            finding for finding in res["image_folder_findings"]
            if finding["kind"] == "portable-name-collision"]
        check("portable image collision preserves every resolving path",
              [finding.get("paths") for finding in _portable_collision],
              [["Collision.png", "nested/collision.PNG"]])
        check("a portable image collision stays present for missing-image checks",
              "COLLISION.PNG" in _st_msg(
                  res, "figured", "item12/missing-image"), False)
        check("intentional PDF sidecars and .DS_Store stay out of image-folder "
              "findings",
              any(finding["path"].rsplit("/", 1)[-1] in _IMAGE_ALLOWED_HIDDEN
                  for finding in res["image_folder_findings"]), False)
        check("image-folder findings are explicitly report-only",
              all("report only" in finding["message"]
                  and "do not" in finding["message"]
                  for finding in res["image_folder_findings"]), True)

        # Obsidian resolves an embed by basename anywhere in the vault. An
        # image elsewhere in a known vault renders, so it is not missing; one
        # found only under a dot-folder, which Obsidian does not index, is.
        _iv = os.path.join(tmp, "v13b-vault-images")
        os.makedirs(os.path.join(_iv, ".obsidian"))
        _iv_images = os.path.join(_iv, "Sources", "Images")
        os.makedirs(_iv_images)
        for _rel in ("Attachments/Pasted image 20260101.png",
                     ".trash/Trashed.png"):
            os.makedirs(os.path.join(_iv, os.path.dirname(_rel)))
            open(os.path.join(_iv, _rel), "w", encoding="utf-8").close()
        _st_write(_iv, "Wiki/pasted.md", _st_entry(
            "Pasted", "**Pasted** is a worked example.\n\n"
            "![[Pasted image 20260101.png]]\n*A pasted image.*\n\n"
            "![[Trashed.png]]\n*An image found only in the trash.*"))
        _iv_res = scan(os.path.join(_iv, "Wiki"), _iv_images, vault=_iv)
        check("an embed found elsewhere in the vault is outside the image "
              "folder, not missing; one only under a dot-folder is missing",
              ("Attachments/Pasted image 20260101.png" in _st_msg(
                  _iv_res, "pasted", "item12/image-outside-folder"),
               "REPORT ONLY" in _st_msg(
                   _iv_res, "pasted", "item12/image-outside-folder"),
               [p["message"].split(": ", 1)[1].split(" (", 1)[0]
                for p in _iv_res["problems"]
                if p["slug"] == "pasted"
                and p["item"] == "item12/missing-image"]),
              (True, True, ["Trashed.png"]))
        check("a `.dltmp` download staging name is temporary on its own",
              [looks_staging(name) for name in (
                  "Doe_X_2025_fig_1.png.dltmp", "Doe_X_2025_fig_1.png")],
              [True, False])

        # An unreadable subtree is not evidence that its files are absent.
        # Simulate os.walk's documented onerror callback so this remains
        # deterministic even when the self-test runs as a privileged user.
        def _failed_image_walk(root, onerror=None):
            if onerror is not None:
                onerror(PermissionError(
                    13, "Permission denied", os.path.join(root, "closed")))
            yield root, [], ["visible.png"]

        with mock.patch.object(os, "walk", _failed_image_walk):
            _partial_names, _partial_findings = image_index(_imgdir)
        check("an unreadable image subtree suppresses missing-image evidence",
              _partial_names, None)
        check("an unreadable image subtree remains visible as a report-only "
              "folder finding",
              [(finding["path"], finding["kind"])
               for finding in _partial_findings],
              [("closed", "unreadable")])

        _unusable_dir = os.path.join(tmp, "unusable-images")
        os.makedirs(_unusable_dir)
        _unusable_path = os.path.join(_unusable_dir, "dangling.png")
        open(_unusable_path, "w", encoding="utf-8").close()
        _real_isfile = os.path.isfile

        def _unusable_file(path):
            if os.path.abspath(path) == os.path.abspath(_unusable_path):
                return False
            return _real_isfile(path)

        with mock.patch.object(os.path, "isfile", side_effect=_unusable_file):
            _unusable_names, _unusable_findings = image_index(_unusable_dir)
        check("a dangling symlink or non-regular image name cannot satisfy an embed",
              _unusable_names, set())
        check("an unusable image occupant is reported without authorizing cleanup",
              [(finding["path"], finding["kind"])
               for finding in _unusable_findings],
              [("dangling.png", "unusable-file")])

        # A symlinked subfolder is not walked, yet Obsidian renders its files:
        # its direct files resolve, a directory inside it is a directory
        # finding that is not descended, a link back into the folder adds no
        # second copy of files the walk already indexed, and a second link to
        # the same target is one owner, not a basename collision.
        _linked_images = os.path.join(tmp, "linked-images")
        _linked_outside = os.path.join(tmp, "linked-outside")
        os.makedirs(_linked_images)
        os.makedirs(os.path.join(_linked_outside, "deeper"))
        os.makedirs(os.path.join(_linked_images, "sub"))
        open(os.path.join(_linked_images, "root.png"), "w",
             encoding="utf-8").close()
        open(os.path.join(_linked_outside, "Doe_X_2025_fig_1.png"), "w",
             encoding="utf-8").close()
        open(os.path.join(_linked_outside, "deeper", "deep.png"), "w",
             encoding="utf-8").close()
        _have_image_link = True
        try:
            os.symlink(_linked_outside, os.path.join(_linked_images, "linked"))
            os.symlink(_linked_images, os.path.join(_linked_images, "loop"))
            os.symlink(_linked_outside,
                       os.path.join(_linked_images, "sub", "again"))
        except (OSError, NotImplementedError, AttributeError):
            _have_image_link = False
        v = os.path.join(tmp, "linked-image-vault")
        _st_write(v, "linked-figure.md", _st_entry(
            "Linked figure", "**Linked figure** is a worked example.\n\n"
            "![[Doe_X_2025_fig_1.png]]\n*A figure in a symlinked subfolder.*"))
        _linked_res = scan(v, _linked_images)
        check("a file in a symlinked image subfolder resolves, the folder is a "
              "symlinked nested-directory finding, a directory inside it is a "
              "nested-directory finding that is not descended, a link back "
              "into the folder repeats nothing, and two links to one target "
              "are no portable-name collision (skipped where symlinks are "
              "unavailable)",
              (not _have_image_link or (
                  "item12/missing-image" not in _st_keys(
                      _linked_res, "linked-figure"),
                  sorted((finding["path"], finding["kind"])
                         for finding in _linked_res["image_folder_findings"]),
                  sorted((finding["path"], finding["message"].startswith(
                              "nested symlinked directory"))
                         for finding in _linked_res["image_folder_findings"]
                         if finding["kind"] == "nested-directory"))
               == (True,
                   [("linked", "nested-directory"),
                    ("linked/Doe_X_2025_fig_1.png", "nested-file"),
                    ("linked/deeper", "nested-directory"),
                    ("loop", "nested-directory"),
                    ("sub", "nested-directory"),
                    ("sub/again", "nested-directory"),
                    ("sub/again/Doe_X_2025_fig_1.png", "nested-file"),
                    ("sub/again/deeper", "nested-directory")],
                   [("linked", True), ("linked/deeper", False),
                    ("loop", True), ("sub", False), ("sub/again", True),
                    ("sub/again/deeper", False)])),
              True)

        # ------------------------------------------------------------------
        # 11. item 19 -- the ## Flashcards heading is a LINE, not a substring
        # ------------------------------------------------------------------
        v = os.path.join(tmp, "v14")
        _st_write(v, "hhh.md",
                  _st_entry("Hhh", "**Hhh** is a worked example.")
                  .replace("## Flashcards", "### Flashcards"))
        _st_write(v, "midline.md", _st_entry(
            "Midline", "**Midline** is a worked example that mentions "
                       "## Flashcards mid-line."))
        res = scan(v)
        check("a ### Flashcards heading is a PRESENT section with a "
              "heading-spelling finding — never 'missing section', whose "
              "remedy adds a second section beside the rendered one",
              (_st_keys(res, "hhh"),
               "missing ## Flashcards" in _st_msg(res, "hhh", "item19"),
               'canonical heading is exactly "## Flashcards"'
               in _st_msg(res, "hhh", "item19")),
              (["item19"], False, True))
        check("a mid-line '## Flashcards' in prose neither starts the section "
              "nor splits the prose at a byte inside a sentence",
              _st_keys(res, "midline"), [])

        # ------------------------------------------------------------------
        # 12b. listings vs sections, fence exactness, and the leak needles —
        #      the 2026-08-24 review's fixes, each pinned by its reproduction.
        # ------------------------------------------------------------------
        v = os.path.join(tmp, "v12b")
        # (a) closing fence must be exactly `---`: `----` and `--- text` are
        #     not frontmatter to Obsidian (or to lint_entry) and must be item1
        #     here too, not a silently clean entry.
        _st_write(v, "four-dash.md",
                  _st_entry("Four dash", "**Four dash** is a worked example.",
                            card=False)
                  .replace('issues: ""\n---\n', 'issues: ""\n----\n', 1))
        _st_write(v, "fence-text.md",
                  _st_entry("Fence text", "**Fence text** is a worked example.",
                            card=False)
                  .replace('issues: ""\n---\n', 'issues: ""\n--- closed\n', 1))
        # (b) a fenced listing SHOWING section markers is not the section: the
        #     Related line and Flashcards heading inside the fence are samples,
        #     and the real prose past the fence is still scanned (the dangling
        #     link below must be found).
        _st_write(v, "sw-listing.md", _st_entry(
            "Sw listing",
            "**Sw listing** is a worked example.\n\n"
            "```\n**Related:** [[phantom-target|P]]\n## Flashcards\n"
            "sample def\n??\nSample term\n```\n\n"
            "After the fence it links [[genuinely-dangling]] in real prose.",
            type_="Software"))
        # (d) tolerated heading spellings are a PRESENT section + a spelling
        #     finding, never "missing section".
        _st_write(v, "two-space.md",
                  _st_entry("Two space", "**Two space** is a worked example.")
                  .replace("## Flashcards", "##  Flashcards"))
        # (e) a stray `read:` line mid-body is an item13 scar like any other
        #     schema key (it is the schema's LAST key — the likeliest one-line scar).
        _st_write(v, "read-scar.md", _st_entry(
            "Read scar", "**Read scar** is a worked example.\n\nread: false"))
        # (f) leak needles: a hyphenated TITLE leaks in its natural spaced
        #     spelling; a disambiguated title's primary card (line 3 = base
        #     term) still gets the entry's alias needles.
        _st_write(v, "fine-tuning.md", _st_entry(
            "Fine-tuning", "**Fine-tuning** is a worked example.", card=False)
            + "\n---\n\n## Flashcards\n\nThe fine tuning of a pretrained model.\n??\nFine-tuning\n")
        _st_write(v, "feature-machine-learning.md", _st_entry(
            "Feature (machine learning)",
            "**Feature (machine learning)** is a worked example.",
            aliases=('"attribute"',), card=False)
            + "\n---\n\n## Flashcards\n\nAn input attribute a model consumes.\n??\nFeature\n")
        _st_write(v, "punctuation-leak.md", _st_entry(
            "Punctuation leak", "**Punctuation leak** is a worked example.",
            aliases=('"bias-variance-trade-off"',), card=False)
            + "\n---\n\n## Flashcards\n\n"
              "The bias/variance trade–off balances two error sources.\n"
              "??\nPunctuation leak\n")
        # (g) two alias spellings that fold to one name are reported within
        #     the entry, not only across entries.
        _st_write(v, "fold-dup.md", _st_entry(
            "Fold dup", "**Fold dup** is a worked example.",
            aliases=('"TPR"', '"tpr"')))
        _st_write(v, "math-primary-alias.md", _st_entry(
            "$k$-nearest neighbors",
            "**$\\boldsymbol{k}$-nearest neighbors** predicts from nearby "
            "observations.", aliases=('"knn"',), card=False)
            + "\n---\n\n## Flashcards\n\nA KNN method using nearby "
              "observations.\n??\nk-nearest neighbors\n")
        for test_slug, rendered in (
                ("math-delimited-answer", "$k$"),
                ("math-command-answer", "$\\boldsymbol{k}$")):
            _st_write(v, test_slug + ".md", _st_entry(
                "$k$-nearest neighbors",
                "**$\\boldsymbol{k}$-nearest neighbors** predicts from nearby "
                "observations.", card=False)
                + "\n---\n\n## Flashcards\n\nA " + rendered
                  + "-nearest neighbors method.\n??\nk-nearest neighbors\n")
        res = scan(v)
        check("a `----` closing fence is item1, not a clean entry",
              _st_keys(res, "four-dash"), ["item1"])
        check("a `--- text` closing fence is item1, not a clean entry",
              _st_keys(res, "fence-text"), ["item1"])
        # (a2) With a card, a lost, `----` or `--- text` closing fence leaves
        #      the separator above `## Flashcards` to close the frontmatter,
        #      and issues: owns the whole body. That is item1 as well. A body
        #      that merely opens with the heading, with no stray line in the
        #      issues: span, is not.
        v_close = os.path.join(tmp, "v12b-flash-close")
        _close_slugs = ("lost-fence", "four-dash-card", "fence-text-card")
        for _name, _fence in zip(_close_slugs, (
                'issues: ""\n', 'issues: ""\n----\n',
                'issues: ""\n--- closed\n')):
            _title = _name.replace("-", " ").capitalize()
            _st_write(v_close, _name + ".md", _st_entry(
                _title, "**%s** is a worked example." % _title)
                .replace('issues: ""\n---\n', _fence, 1))
        _st_write(v_close, "flash-only.md", _st_entry(
            "Flash only", "", related=False, card=False)
            + "## Flashcards\n\nThe idea this entry is about, stated once."
              "\n??\nFlash only\n")
        res_close = scan(v_close)
        check("a frontmatter that only the Flashcards separator closes is item1",
              [FLASHCARDS_CLOSE_MESSAGE in _st_msg(res_close, slug_, "item1")
               for slug_ in _close_slugs], [True] * 3)
        check("...while its issues: span stays issues-malformed, never an "
              "unparseable item-1 line",
              [("item2/issues-malformed" in _st_keys(res_close, slug_),
                "unparseable" in _st_msg(res_close, slug_, "item1"))
               for slug_ in _close_slugs], [(True, False)] * 3)
        check("a body that opens with ## Flashcards after a closed "
              "frontmatter is not a lost fence",
              FLASHCARDS_CLOSE_MESSAGE in _st_msg(res_close, "flash-only",
                                                  "item1"), False)
        # Restore readable metadata before asserting absence/alias-dependent
        # link results; the malformed-fence cases above suppress those results.
        for name in ("four-dash", "fence-text"):
            _st_write(v, name + ".md", _st_entry(
                name.replace("-", " ").capitalize(),
                "**%s** is a worked example." % name.replace("-", " ").capitalize()))
        res = scan(v)
        check("fenced Related/Flashcards samples produce no phantom section "
              "findings, and prose past the fence is still scanned",
              (_st_msg(res, "sw-listing", "item10/dangling""").count("does not resolve"),
               "phantom-target" in " ".join(p["message"] for p in res["problems"]),
               "genuinely-dangling" in _st_msg(res, "sw-listing", "item10/dangling")),
              (1, False, True))
        check("...and the real `## Flashcards` section (outside any fence) is "
              "still recognised on the same entry",
              "item19" in _st_keys(res, "sw-listing"), False)
        check("'##  Flashcards' (double space) is a present section plus a "
              "heading-spelling finding, not a missing section",
              ("missing ## Flashcards" in _st_msg(res, "two-space", "item19"),
               'canonical heading is exactly "## Flashcards"'
               in _st_msg(res, "two-space", "item19")),
              (False, True))
        check("a stray `read:` line in the body is an item13 scar",
              "item13" in _st_keys(res, "read-scar"), True)
        check("a hyphenated title leaking in its spaced spelling is caught",
              'leaks the answer ("Fine-tuning")'
              in _st_msg(res, "fine-tuning", "item19"),
              True)
        check("slash and Unicode-dash variants cannot hide an alias leak",
              'leaks the answer ("bias-variance-trade-off")'
              in _st_msg(res, "punctuation-leak", "item19"), True)
        check("a disambiguated title's primary card (line 3 = base term) "
              "gets the alias needles — the alias leak is caught",
              'leaks the answer ("attribute")'
              in _st_msg(res, "feature-machine-learning", "item19"), True)
        check("two alias spellings folding to one name are an item18 finding "
              "within the entry",
              "differ only in case/normalization"
              in _st_msg(res, "fold-dup", "item18"), True)
        check("a math-title primary card gets alias leak needles",
              'leaks the answer ("knn")'
              in _st_msg(res, "math-primary-alias", "item19"), True)
        check("math markup cannot hide a primary answer leak",
              ['leaks the answer ("k-nearest neighbors")' in _st_msg(
                   res, test_slug, "item19") for test_slug in
               ("math-delimited-answer", "math-command-answer")],
              [True, True])

        # (h) backfill: a candidate reached only through a single lowercase
        #     alias word is tagged bare_noun_alias; a title-surface candidate
        #     is not.
        v = os.path.join(tmp, "v12c")
        _st_write(v, "feature-machine-learning.md", _st_entry(
            "Feature (machine learning)",
            "**Feature (machine learning)** is a worked example.",
            aliases=('"covariate"',)))
        _st_write(v, "gradient-descent.md", _st_entry(
            "Gradient descent", "**Gradient descent** is a worked example."))
        _st_write(v, "principal-component-analysis.md", _st_entry(
            "Principal component analysis",
            "**Principal component analysis** is a worked example.",
            aliases=('"pca"',)))
        _st_write(v, "user.md", _st_entry(
            "User", "**User** is a worked example. Each covariate feeds the "
                    "model, and gradient descent fits it after PCA."))
        res = scan(v)
        _bf = {(b["target"], b["bare_noun_alias"]) for b in res["backfill_candidates"]
               if b["slug"] == "user"}
        check("an alias-mediated bare-noun surface of a qualified entry is "
              "tagged bare_noun_alias; a title or unqualified alias is not",
              (("feature-machine-learning", True) in _bf,
               ("gradient-descent", False) in _bf,
               ("principal-component-analysis", False) in _bf),
              (True, True, True))

        v = os.path.join(tmp, "v13-validation")
        for i, source in enumerate(("[[Doe_X_2025.pdf]]", "[[Doe_X_2025.pdf#page=0]]",
                                  "[[Doe_X_2025.pdf#page=01]]",
                                  "[[Doe_X_2025.pdf#page=1garbage]]",
                                  "[Doe](https://example.test/Doe_X_2025.pdf)",
                                  "Doe_X_2025.pdf#page=1", "[[Note.md#Heading]]")):
            name = "Source %s" % i
            _st_write(v, slug(name) + ".md", _st_entry(
                name, "**%s** is a worked example." % name,
                sources=(json.dumps(source),)))
        for i, raw in enumerate(("banana", "[]", "[true, false]", '"banana"')):
            name = "Unknown %s" % i
            _st_write(v, slug(name) + ".md", _st_entry(
                name, "**%s** is a worked example." % name).replace("read: false", "read: " + raw))
        for i, raw in enumerate(("yes", "no", "0", "1")):
            name = "Known %s" % i
            _st_write(v, slug(name) + ".md", _st_entry(
                name, "**%s** is a worked example." % name).replace("read: false", "read: " + raw))
        _st_write(v, "no-source.md", _st_entry("No source", "**No source** is a worked example.", sources=()))
        _st_write(v, "web-source.md", _st_entry(
            "Web source", "**Web source** is a worked example.",
            sources=('"https://arxiv.org/abs/2305.18290"', '"[[Doe_X_2025.pdf#page=2]]"')))
        _st_write(v, "web-pair.md", _st_entry(
            "Web pair", "**Web pair** is a worked example.",
            sources=('"https://example.org/Doe_X_2025.pdf"', '"[[Doe_X_2025.md]]"')))
        _st_write(v, "web-twice.md", _st_entry(
            "Web twice", "**Web twice** is a worked example.",
            sources=('"https://example.org/a"', '"https://example.org/a"')))
        _st_write(v, "web-pair-md.md", _st_entry(
            "Web pair md", "**Web pair md** is a worked example.",
            sources=('"[[Doe_X_2025.pdf#page=2]]"', '"https://example.org/Doe_X_2025.md"')))
        _st_write(v, "web-http.md", _st_entry(
            "Web http", "**Web http** is a worked example.",
            sources=('"http://example.org/page"',)))
        _st_write(v, "web-query.md", _st_entry(
            "Web query", "**Web query** is a worked example.",
            sources=('"https://example.org/search?q=roc&page=2#results"',)))
        _st_write(v, "web-bare.md", _st_entry(
            "Web bare", "**Web bare** is a worked example.",
            sources=('https://example.org/a',)))
        # Each carries a real address, but only a bare http(s) URL is a source.
        web_rejects = ("ftp://example.org/Doe_X_2025.pdf",
                       "[ROC](https://example.org/roc)",
                       "Label https://example.org/roc",
                       "<https://example.org/roc>",
                       "[[https://example.org/roc]]",
                       "example.org/page", "https://example.org/a b")
        for i, source in enumerate(web_rejects):
            name = "Web reject %s" % i
            _st_write(v, slug(name) + ".md", _st_entry(
                name, "**%s** is a worked example." % name,
                sources=(json.dumps(source),)))
        _st_write(v, "self-case.md", _st_entry("Self case", "**Self case** is a worked example.",
                  parents=('"[[SELF-CASE]]"',)))
        for kind, target in (("md", "self-md.md"), ("path", "Wiki/self-path"),
                             ("block", "self-block^definition"), ("heading", "self-heading#Definition")):
            name = "Self " + kind
            _st_write(v, slug(name) + ".md", _st_entry(name, "**%s** is a worked example." % name,
                      parents=(json.dumps("[[%s]]" % target),)))
        _st_write(v, "cycle-left.md", _st_entry("Cycle left", "**Cycle left** is a worked example.",
                  parents=('"[[Wiki/CYCLE-RIGHT.md#Definition]]"',)))
        _st_write(v, "cycle-right.md", _st_entry("Cycle right", "**Cycle right** is a worked example.",
                  parents=('"[[cycle-left.md]]"',)))
        res = scan(v)
        check("every malformed source is an item4 finding",
              ["item4" in _st_keys(res, "source-%d" % i) for i in range(7)], [True] * 7)
        check("empty provenance is not a clean entry", "item4" in _st_keys(res, "no-source"), True)
        check("an online page cited by URL is a valid source",
              [k for k in _st_keys(res, "web-source") if k.startswith("item4")], [])
        check("a URL ending in .pdf pairs with no local note",
              [k for k in _st_keys(res, "web-pair") if k.startswith("item4")], [])
        check("an exactly repeated URL is flagged once",
              _st_msg(res, "web-twice", "item4"),
              'source "https://example.org/a" is listed 2 times — keep one exact citation')
        check("a URL ending in .md pairs with no local pdf",
              [k for k in _st_keys(res, "web-pair-md") if k.startswith("item4")], [])
        check("a plain http URL is a valid source",
              _st_keys(res, "web-http"), [])
        check("a URL with a query and a fragment is a valid source",
              _st_keys(res, "web-query"), [])
        for i, source in enumerate(web_rejects):
            check("a wrapped, non-http or incomplete address is an item4 "
                  "finding: %s" % source,
                  ([k for k in _st_keys(res, "web-reject-%d" % i)
                    if k.startswith("item4")],
                   _st_msg(res, "web-reject-%d" % i, "item4").endswith(
                       "are invalid: " + source)),
                  (["item4"], True))
        check("an unquoted URL source is conforming: Obsidian strips its quotes",
              _st_keys(res, "web-bare"), [])
        check("unknown review states route report-only, never read-type",
              [sorted(k for k in _st_keys(res, "unknown-%d" % i) if k.startswith("item2/read"))
               for i in range(4)], [["item2/read-unknown"]] * 4)
        check("a read-unknown message names the user-issue and merge-survivor "
              "exceptions",
              [("user_issues" in _st_msg(res, "unknown-%d" % i, "item2/read-unknown"),
                "merge's survivor" in _st_msg(res, "unknown-%d" % i,
                                              "item2/read-unknown"))
               for i in range(4)], [(True, True)] * 4)
        check("known review answers retain the spelling-only fix",
              ["item2/read-type" in _st_keys(res, "known-%d" % i) for i in range(4)], [True] * 4)
        check("resolving self-parent spellings are still self-parents",
              res["hierarchy_diagnostic"]["self_parented"],
              ["self-block", "self-case", "self-heading", "self-md", "self-path"])
        check("a cycle survives parent path, extension, case and anchor variants",
              res["hierarchy_diagnostic"]["parent_cycles"], [["cycle-left", "cycle-right"]])

        v = os.path.join(tmp, "v14-backfill")
        _st_write(v, "recall.md", _st_entry("Recall", "**Recall** measures sensitivity.",
                  aliases=('"true-positive-rate"',)))
        texts = {
            "inline": "**Inline** documents `Recall` as an identifier.",
            "indented": "**Indented** documents a listing.\n\n    Recall",
            "sample": "**Sample** displays `[[recall]]` literally.\n\nRecall measures sensitivity.",
            "anchor": "**Anchor** links [[recall#Definition|Recall]]. Recall measures sensitivity.",
            "qualified": "**Qualified** links [[Wiki/recall.md|Recall]]. Recall measures sensitivity.",
            "misqualified": "**Misqualified** links [[absent/recall.md|Recall]]. Recall measures sensitivity.",
            "case": "**Case** links [[RECALL|Recall]]. Recall measures sensitivity.",
            "alias": "**Alias** links [[true-positive-rate|Sensitivity]]. Recall measures sensitivity.",
            "plain": "**Plain** explains why Recall measures sensitivity.",
            "reference-definition": (
                "**Reference definition** documents a Markdown target.\n\n"
                "[Recall]: https://example.test/recall"),
            "reference-definition-then-prose": (
                "**Reference definition then prose** documents a Markdown target.\n\n"
                "[Recall]: https://example.test/recall\n\n"
                "Recall measures sensitivity."),
            "shortcut-reference": (
                "**Shortcut reference** uses [Recall] as a citation label.\n\n"
                "[recall]: https://example.test/recall"),
            "shortcut-reference-then-prose": (
                "**Shortcut reference then prose** uses [Recall] as a citation label.\n\n"
                "[RECALL]: https://example.test/recall\n\n"
                "Recall measures sensitivity."),
            "shortcut-image": (
                "**Shortcut image** displays ![Recall] as alternative text.\n\n"
                "[Recall]: https://example.test/recall.png"),
            "full-reference-image": (
                "**Full reference image** displays ![Recall][figure] as "
                "alternative text.\n\n[figure]: https://example.test/image.png"),
            "collapsed-reference-image": (
                "**Collapsed reference image** displays ![Recall][] as "
                "alternative text.\n\n[Recall]: https://example.test/image.png"),
            "bare-url": (
                "**Bare URL** records https://example.test/Recall as its source."),
            "autolink": (
                "**Autolink** records <https://example.test/Recall> as its source."),
            "bare-url-then-prose": (
                "**Bare URL then prose** records https://example.test/Recall.\n\n"
                "Recall measures sensitivity."),
        }
        for name, prose in texts.items():
            _st_write(v, name + ".md", _st_entry(name.title(), prose, type_="Software"))
        res = scan(v)
        check("backfill ignores listings and already-linked destinations, but a shown link cannot hide real prose",
              sorted(b["slug"] for b in res["backfill_candidates"] if b["target"] == "recall"),
              ["bare-url-then-prose", "misqualified", "plain",
               "reference-definition-then-prose", "sample",
               "shortcut-reference-then-prose"])

        v = os.path.join(tmp, "v15-preserved-content")
        for name, tail in (
                ('studied', '<!--SR:!2026-09-20,30,250!2026-09-21,31,250-->\n<!--SR:preserved-state-->\n'),
                ('multiline', '<!--SR:\n!2026-09-20,30,250\n\n!2026-09-21,31,250\n-->\n')):
            text = _st_entry(name.title(), '**%s** is a worked example.' % name.title())
            text = text.replace('read: false', 'read: true').replace(
                '\n??\n', '\n!!\n').rstrip('\n') + '\n' + tail
            _st_write(v, name + '.md', text)
        inline = _st_entry('Inline', '**Inline** is a worked example.')
        inline = inline.replace('read: false', 'read: true').replace(
            '\n??\nInline\n',
            '\n!!\nInline <!--SR:!2026-09-20,30,250--> ^inline-card\n')
        _st_write(v, 'inline.md', inline)
        separate_block = _st_entry(
            'Separate block', '**Separate block** is a worked example.')
        separate_block = separate_block.replace(
            '\nSeparate block\n', '\nSeparate block ^separate-card\n')
        separate_block = (separate_block.rstrip('\n')
                          + '\n<!--SR:!2026-09-20,30,250-->\n')
        _st_write(v, 'separate-block.md', separate_block)
        callout = _st_entry('Callout', '**Callout** is a worked example.')
        callout = (callout.rstrip('\n')
                   + '\n> [!sr|card-metadata] \n'
                     '>  <!--SR:!2026-09-20,30,250--> ^callout-card\n')
        _st_write(v, 'callout.md', callout)
        extra = _st_entry('Extra', '**Extra** is a worked example.').rstrip('\n')
        _st_write(v, 'extra.md', extra
                  + '\n> [!sr|card-metadata]\n'
                    '> <!--SR:!2026-09-20,30,250--> ^extra-card\n\n'
                    'A different main claim.\n??\nAnother term\n')
        detached = _st_entry(
            'Detached', '**Detached** is a worked example.')
        _st_write(v, 'detached.md', detached
                  + '\n<!--SR:detached-after-blank-->\n')
        _st_write(v, 'detached-callout.md', _st_entry(
            'Detached callout', '**Detached callout** is a worked example.')
                  + '\n> [!sr|card-metadata]\n>\n'
                    '> <!--SR:!2026-03-01,12,270--> ^detached-card\n')
        for name, trailing in (
                ('schedule-block-id', '^bid3\n'),
                ('schedule-user-lines',
                 'User line a.\nUser line b\nUser line c\n')):
            _st_write(v, name + '.md', _st_entry(
                name.replace('-', ' ').capitalize(),
                '**%s** is a worked example.'
                % name.replace('-', ' ').capitalize()).rstrip('\n')
                + '\n<!--SR:!2026-03-01,12,270-->\n' + trailing)
        unterminated = _st_entry(
            'Unterminated', '**Unterminated** is a worked example.').rstrip('\n')
        _st_write(v, 'unterminated.md', unterminated
                  + '\n<!--SR:unterminated-state\n')
        for name, fence in (('backticks', '```'), ('tildes', '~~~')):
            _st_write(v, name + '.md', _st_entry(
                name.title(), '**%s** is a worked example.\n\n' % name.title()
                + fence + 'text\n' + fence + 'not-a-close\n[[syntax-example]]\n'
                + fence, type_='Software'))
        _st_write(v, 'indented-closer.md', _st_entry('Indented closer',
                  '**Indented closer** displays syntax.\n\n```text\n    ```\n[[literal-syntax]]\n```',
                  type_='Software'))
        _st_write(v, 'nested-fence.md', _st_entry('Nested fence',
                  '**Nested fence** displays syntax.\n\n- An example:\n\n    ```text\n    [[literal-nested]]\n    ```',
                  type_='Software'))
        _st_write(v, 'sub/parsed.md', _st_entry('Parsed', '**Parsed** is a worked example.'))
        _st_write(v, 'sub/unparsed.md', 'A user note without frontmatter.\n')
        _st_write(v, 'linked.md', _st_entry('Linked', '**Linked** cites [[SUB/PARSED]], '
                  '[[sub/UNPARSED]], [[sub/parsed.MD]] and [[sub/unparsed.md]].'))
        before = {p: open(p, 'rb').read() for p in iter_entry_files(v)}
        res = scan(v)
        check("all note-backed scheduling forms and block IDs stay outside card content",
              [k for name in ('studied', 'multiline', 'inline',
                              'separate-block', 'callout')
               for k in _st_keys(res, name)
               if k == 'item19'], [])
        check("callout metadata is not counted, but a genuine second card still is",
              'holds 2 cards' in _st_msg(res, 'extra', 'item19'), True)
        check("detached or unterminated SR comments remain reportable content",
              ['item19' in _st_keys(res, name)
               for name in ('detached', 'unterminated')], [True, True])
        check("a detached schedule is a block to report, never a card",
              [(_st_keys(res, name),
                'Spaced Repetition schedule that a blank line separates'
                in _st_msg(res, name, 'item19'),
                any(word in _st_msg(res, name, 'item19')
                    for word in ('holds 2 cards', 'extra card',
                                 'contiguous lines')))
               for name in ('detached', 'detached-callout')],
              [(['item19'], True, False)] * 2)
        check("content after an attached schedule stays on the card",
              [('visible lines' in _st_msg(res, name, 'item19'),
                any(word in _st_msg(res, name, 'item19')
                    for word in ('holds 2 cards', 'extra card',
                                 'contiguous lines')))
               for name in ('schedule-block-id', 'schedule-user-lines')],
              [(True, False)] * 2)
        check("a fence with trailing text cannot end the listing or hide the real flashcard",
              [k for name in ('backticks', 'tildes', 'indented-closer', 'nested-fence') for k in _st_keys(res, name)
               if k in ('item10/dangling', 'item19')], [])
        check("qualified case and explicit-extension links are never false danglers",
              'item10/dangling' in _st_keys(res, 'linked'), False)
        check("qualified unparsed destinations still route to the file's own repair",
              _st_keys(res, 'linked').count('item10/unparsed'), 2)
        check("the scanner leaves every scheduling form, block ID, and input byte untouched",
              all(open(p, 'rb').read() == content for p, content in before.items()), True)

        v = os.path.join(tmp, "v16-scalar-provenance")
        _st_write(v, 'commented.md', _st_entry('Commented', '**Commented** is a worked example.')
                  .replace('title: "Commented"', 'title: "Comm\\u0065nted" # user annotation')
                  .replace('read: false', 'read: true # already read')
                  .replace('sources:\n', 'sources: # origin\n# preserve this annotation\n'))
        for name, raw in (('null-title', 'null'), ('malformed', '"Malformed "yaml""')):
            _st_write(v, name + '.md', _st_entry(name.title(), '**Example** is a worked example.')
                      .replace('title: "' + name.title() + '"', 'title: ' + raw))
        _st_write(v, 'two-sources.md', _st_entry('Two sources', '**Two sources** is a worked example.',
                  sources=('"[[Study.pdf#page=2]]"', '"[[Study.md]]"')))
        res = scan(v)
        check("comments and decoded YAML title preserve a clean studied entry",
              _st_keys(res, 'commented'), [])
        check("null or malformed titles never produce rename candidates",
              [r for r in res['rename_candidates'] if r['slug'] in ('null-title', 'malformed')], [])
        check("malformed quoted YAML is a validity finding",
              'item1' in _st_keys(res, 'malformed'), True)
        check("same-stem PDF/clipping provenance is a report-only candidate",
              _st_keys(res, 'two-sources'), ['item4/source-identity'])
        for raw, want in (("[O'Reilly, real-alias]", ["O'Reilly", "real-alias"]),
                          ("['tail\\', 'real-alias']", ["tail\\", "real-alias"]),
                          ("['O''Reilly, Inc.', 'real-alias']", ["O'Reilly, Inc.", "real-alias"])):
            check("flow parsing retains every valid scalar in %s" % raw,
                  parse_fm('---\naliases: ' + raw + '\n---\n')['aliases'], want)
        from unittest.mock import patch
        def unreadable_walk(root, followlinks=False, onerror=None):
            if onerror:
                onerror(PermissionError(13, "permission denied", os.path.join(root, "private")))
            return iter(())
        with patch.object(os, "walk", unreadable_walk):
            try:
                scan(v)
                inaccessible_error = ""
            except IncompleteWikiInventoryError as exc:
                inaccessible_error = str(exc)
        check("an unreadable directory blocks the scan rather than yielding partial worklists",
              "incomplete Wiki directory inventory" in inaccessible_error, True)

        _st_write(v, "private/hidden-topic.md", _st_entry(
            "Hidden topic", "**Hidden topic** is a worked example."))
        _st_write(v, "reader-with-hidden-target.md", _st_entry(
            "Reader with hidden target",
            "**Reader with hidden target** uses [[hidden-topic|Hidden topic]]."))

        def partial_walk(root, followlinks=False, onerror=None):
            if onerror:
                onerror(PermissionError(13, "permission denied", os.path.join(root, "private")))
            return iter([(root, [], ["reader-with-hidden-target.md"])])

        import contextlib
        import io
        old_report = os.path.join(tmp, "prior-scan.json")
        with open(old_report, "w", encoding="utf-8") as handle:
            handle.write("prior report must not be replaced")
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(os, "walk", partial_walk), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            incomplete_status = main([v, "--out", old_report])
        check("partial CLI inventory exits nonzero without prescribing removal of a hidden real entry",
              (incomplete_status, stdout.getvalue(),
               "incomplete Wiki directory inventory" in stderr.getvalue(),
               open(old_report, encoding="utf-8").read()),
              (1, "", True, "prior report must not be replaced"))

        real_stat = os.stat
        def missing_directory_identity(path, *args, **kwargs):
            if os.path.abspath(path) == os.path.join(v, "private"):
                raise PermissionError(13, "directory identity unavailable", path)
            return real_stat(path, *args, **kwargs)

        with patch.object(os, "stat", side_effect=missing_directory_identity):
            try:
                scan(v)
                identity_error = ""
            except IncompleteWikiInventoryError as exc:
                identity_error = str(exc)
        check("a missing directory identity cannot fall back to unsafe path-based loop detection",
              "directory identity unavailable" in identity_error, True)

        v = os.path.join(tmp, "v17-ambiguous-links")
        for name in ('first', 'second'):
            aliases = ('"shared-name"', '"single-name"') if name == 'first' else ('"shared-name"',)
            _st_write(v, name + '.md', _st_entry(name.title(), '**%s** is a worked example.' % name.title(),
                      aliases=aliases))
        for rel in ('a/Shared.md', 'b/shared.md'):
            _st_write(v, rel, _st_entry('Shared', '**Shared** is a worked example.'))
        _st_write(v, 'reader.md', _st_entry('Reader', '**Reader** cites '
                  '[[shared-name#Definition|the chosen term]], [[b/shared#Section]], '
                  'and [[single-name#Definition|the precise term]].'))
        res = scan(v)
        check("ambiguous alias owners never produce an automatic rewrite or dangler",
              _st_keys(res, 'reader').count('item10/ambiguous'), 1)
        check("a qualified file target still resolves under a basename collision",
              'b/shared' in _st_msg(res, 'reader', 'item10/ambiguous'), False)
        check("an unambiguous alias rewrite keeps the existing anchor and display label",
              '[[first#Definition|the precise term]]' in _st_msg(res, 'reader', 'item10/alias'), True)
        check("ambiguous resolving links are not classified as dangling",
              'item10/dangling' in _st_keys(res, 'reader'), False)

        v = os.path.join(tmp, "v18-tally")
        _st_write(v, "clean.md", _st_entry("Clean", "**Clean** is a worked example."))
        for name in ("first", "second"):
            _st_write(v, name + ".md", _st_entry(
                name.title(), "**%s** is a worked example." % name.title(),
                sources=('"invalid-source"',)))
        _st_write(v, "no-frontmatter.md", "no frontmatter at all\n")
        res = scan(v)
        check("problem percentages use every parsed entry as the denominator",
              [(p["entries"], p["pct_of_entries"]) for p in res["problem_tally"]
               if p["item"] == "item4"], [(2, 66.7)])
        check("an unparsed path counts in `entries` but not in the parsed-entry "
              "share or its denominator",
              [(p["entries"], p["pct_of_entries"]) for p in res["problem_tally"]
               if p["item"] == "item1"], [(1, 0.0)])

        # issues: — the user's issue inbox.  Every blank spelling conforms;
        # a string or a list of strings is a user_issues row; anything else is
        # report-only; a missing key is a format repair.
        v = os.path.join(tmp, "v18c-issues")
        _issue_values = {
            "issues-canonical": 'issues: ""\n',
            "issues-bare": "issues:\n",
            "issues-null": "issues: null\n",
            "issues-tilde": "issues: ~\n",
            "issues-single": "issues: ''\n",
            "issues-flow": "issues: []\n",
            "issues-string": 'issues: "The opener repeats the title: rewrite it."\n',
            "issues-plain": "issues: Explain variance more simply\n",
            "issues-list": 'issues:\n  - "Add an example."\n  - Wrong parent\n',
            "issues-mapping": "issues:\n  note: fix it\n",
            "issues-flow-mapping": "issues: {note: fix it}\n",
            "issues-nested": "issues:\n  -\n    - Wrong parent\n",
            "issues-collection": "issues:\n  - [Add an example, Wrong parent]\n",
            # An unquoted '#' comment cuts the user's text off; quoted, or
            # with no space before it, the '#' is part of the text.
            "issues-comment-start": "issues: #1 the card is wrong\n",
            "issues-comment-plain": "issues: Fix the card # and add an example\n",
            "issues-comment-item": "issues:\n  - Fix the #2 card\n",
            "issues-quoted-hash": 'issues: "#1 the card is wrong"\n',
            "issues-unspaced-hash": "issues: Fix the card#2\n",
            "issues-missing": "",
        }
        for _name, _value in _issue_values.items():
            _st_write(v, _name + ".md", _st_entry(
                _name.replace("-", " ").capitalize(),
                "**%s** is a worked example." % _name.replace("-", " ").capitalize())
                .replace('issues: ""\n', _value))
        _st_write(v, "sub-a/zeta-issue.md", _st_entry(
            "Zeta issue", "**Zeta issue** is a worked example.")
            .replace('issues: ""\n', 'issues: "Wrong parent"\n'))
        _st_write(v, "sub-b/alpha-issue.md", _st_entry(
            "Alpha issue", "**Alpha issue** is a worked example.")
            .replace('issues: ""\n', 'issues: "Add an example"\n'))
        _st_write(v, "issues-first.md", _st_entry(
            "Issues first", "**Issues first** is a worked example.")
            .replace('read: false\nissues: ""\n', 'issues: ""\nread: false\n'))
        res = scan(v)
        _blank_issue_slugs = ("issues-canonical", "issues-bare", "issues-null",
                              "issues-tilde", "issues-single", "issues-flow")
        check("every blank issues: spelling is a clean entry",
              [_st_keys(res, slug_) for slug_ in _blank_issue_slugs],
              [[]] * len(_blank_issue_slugs))
        check("a string or list issues: value is user text, never an item2 "
              "quoting finding",
              [_st_keys(res, slug_) for slug_ in
               ("issues-string", "issues-plain", "issues-list",
                "issues-quoted-hash", "issues-unspaced-hash")],
              [[]] * 5)
        check("user_issues lists each non-blank entry's form and decoded "
              "issues, sorted by slug",
              res["user_issues"],
              [{"slug": "alpha-issue", "form": "string",
                "issues": ["Add an example"]},
               {"slug": "issues-list", "form": "list",
                "issues": ["Add an example.", "Wrong parent"]},
               {"slug": "issues-plain", "form": "string",
                "issues": ["Explain variance more simply"]},
               {"slug": "issues-quoted-hash", "form": "string",
                "issues": ["#1 the card is wrong"]},
               {"slug": "issues-string", "form": "string",
                "issues": ["The opener repeats the title: rewrite it."]},
               {"slug": "issues-unspaced-hash", "form": "string",
                "issues": ["Fix the card#2"]},
               {"slug": "zeta-issue", "form": "string",
                "issues": ["Wrong parent"]}])
        _malformed_issue_slugs = ("issues-mapping", "issues-flow-mapping",
                                  "issues-nested", "issues-collection")
        check("a mapping, a nested list or a collection item in issues: is "
              "report-only issues-malformed, its only finding, and never a "
              "user_issues row",
              [(_st_keys(res, slug_),
                "REPORT ONLY" in _st_msg(res, slug_, "item2/issues-malformed"),
                slug_ in [row["slug"] for row in res["user_issues"]])
               for slug_ in _malformed_issue_slugs],
              [(["item2/issues-malformed"], True, False)]
              * len(_malformed_issue_slugs))
        check("issues-malformed names the shape it found",
              [_st_msg(res, slug_, "item2/issues-malformed").split(",")[0]
               for slug_ in _malformed_issue_slugs],
              ["issues: holds a mapping",
               "issues: holds a mapping", "issues: holds a nested list",
               "issues: holds a list item that is not one string"])
        check("an unquoted '#' comment that cuts issues: text off, even to "
              "blank, is only the report-only issues-malformed and never a "
              "short user_issues row",
              [(_st_keys(res, slug_),
                _st_msg(res, slug_, "item2/issues-malformed").split(",")[0],
                slug_ in [row["slug"] for row in res["user_issues"]])
               for slug_ in ("issues-comment-start", "issues-comment-plain",
                             "issues-comment-item")],
              [(["item2/issues-malformed"], "issues: holds " + ISSUES_COMMENT,
                False)] * 3)
        check("a missing issues: key is the fixable issues-missing, not a "
              "generic missing-key finding",
              (_st_keys(res, "issues-missing"),
               _st_msg(res, "issues-missing", "item2/issues-missing")),
              (["item2/issues-missing"],
               "missing issues: key — the user's issue inbox. Insert "
               '`issues: ""` directly after read: (after the last schema key '
               "before it when read: is absent too), keeping dates and read:"))
        check("issues: before read: is out of schema order",
              (_st_keys(res, "issues-first"),
               "fields out of schema order" in _st_msg(res, "issues-first", "item2")),
              (["item2"], True))
        # The Text property is one line (CONVENTIONS.md §2d), as wiki-build's
        # draft linter reads it: a block scalar or a value on several lines is
        # report-only, and text that is not YAML stays the user's, with no
        # fixable item-1 row and no alias-inventory gap that would stall link
        # work vault-wide.
        v = os.path.join(tmp, "v18c-issues-yaml")
        _issue_values = {
            "wrapped-quoted": 'issues: "A long issue that\n  wraps."\n',
            "wrapped-plain": "issues: A long issue that\n  wraps.\n",
            "folded-block": "issues: >-\n  A long issue that\n  wraps.\n",
            "literal-block": ("issues: |-\n  - Opener repeats the title.\n"
                              "  - Wrong parent.\n"),
            "next-line": "issues:\n  Wrong parent\n",
            "wrapped-item": "issues:\n  - Wrong parent,\n    not Variance\n",
            "wrapped-flow": "issues: [Wrong parent,\n  Add an example]\n",
            "flow-list": "issues: [Wrong parent, \"Add an example\"]\n",
            "blank-items": "issues:\n  - \"\"\n  -\n  - ' '\n",
            "colon-value": "issues: Wrong parent: should be Variance\n",
            "unclosed-quote": 'issues: "Wrong parent\n',
            "item-after-value": 'issues: ""\n- Wrong parent\n',
            "duplicate-key": 'issues: ""\nissues: "Wrong parent"\n',
        }
        for _name, _value in _issue_values.items():
            _st_write(v, _name + ".md", _st_entry(
                _name.replace("-", " ").capitalize(),
                "**%s** is a worked example." % _name.replace("-", " ").capitalize())
                .replace('issues: ""\n', _value, 1))
        _st_write(v, "linker.md", _st_entry(
            "Linker", "**Linker** is a worked example of [[Nowhere at all]]."))
        res = scan(v)
        check("a one-line flow list is user text, and a list of blank items "
              "is blank",
              ([_st_keys(res, slug_) for slug_ in ("flow-list", "blank-items")],
               res["user_issues"]),
              ([[], []],
               [{"slug": "flow-list", "form": "list",
                 "issues": ["Wrong parent", "Add an example"]}]))
        check("a wrapped string, a block scalar, a value on the next line, a "
              "wrapped list item or flow list is only the report-only "
              "issues-malformed, which names its shape",
              [(_st_keys(res, slug_),
                _st_msg(res, slug_, "item2/issues-malformed").split(",")[0],
                _st_msg(res, slug_, "item2/issues-malformed").endswith(
                    "the user rewrites it"))
               for slug_ in ("wrapped-quoted", "wrapped-plain", "folded-block",
                             "literal-block", "next-line", "wrapped-item",
                             "wrapped-flow")],
              [(["item2/issues-malformed"],
                "issues: holds a string continued on another line", False),
               (["item2/issues-malformed"],
                "issues: holds a string continued on another line", False),
               (["item2/issues-malformed"], "issues: holds a block scalar",
                False),
               (["item2/issues-malformed"], "issues: holds a block scalar",
                False),
               (["item2/issues-malformed"],
                "issues: holds a value on the line after its key", False),
               (["item2/issues-malformed"],
                "issues: holds a list item that is not one string", False),
               (["item2/issues-malformed"],
                "issues: holds a flow list continued on another line", False)])
        check("issues: text that is not YAML, or a duplicate issues: key, is "
              "only the report-only issues-malformed",
              [(_st_keys(res, slug_),
                _st_msg(res, slug_, "item2/issues-malformed").split(",")[0],
                _st_msg(res, slug_, "item2/issues-malformed").endswith(
                    ". Obsidian cannot read this note's properties until the "
                    "user rewrites it"))
               for slug_ in ("colon-value", "unclosed-quote",
                             "item-after-value", "duplicate-key")],
              [(["item2/issues-malformed"], "issues: holds an unreadable value",
                True),
               (["item2/issues-malformed"], "issues: holds an unreadable value",
                True),
               (["item2/issues-malformed"],
                "issues: holds a value followed by list items", True),
               (["item2/issues-malformed"],
                "issues: holds a duplicate issues: key", False)])
        check("a malformed issues: value never switches off another entry's "
              "link findings",
              "item10/dangling" in _st_keys(res, "linker"), True)
        v = os.path.join(tmp, "v18c-issues-twins")
        for _folder in ("one", "two"):
            _st_write(v, _folder + "/twin.md", _st_entry(
                "Twin", "**Twin** is a worked example.")
                .replace('issues: ""\n', 'issues: "Fix %s"\n' % _folder))
        check("a user_issues row for a shared basename carries its path",
              scan(v)["user_issues"],
              [{"slug": "twin", "form": "string", "issues": ["Fix one"],
                "path": "one/twin.md"},
               {"slug": "twin", "form": "string", "issues": ["Fix two"],
                "path": "two/twin.md"}])

        # Every physical file whose title slug differs gets a rename row, and
        # a basename that several files share adds the file's path.
        v = os.path.join(tmp, "v18c-rename-twins")
        for _rel, _title in (("a/x.md", "Mean"), ("b/x.md", "X"),
                             ("c/y.md", "Median"), ("d/Y.md", "Median"),
                             ("solo.md", "Solo entry")):
            _st_write(v, _rel, _st_entry(
                _title, "**%s** is a worked example." % _title))
        check("rename rows for a shared basename carry their paths and "
              "compete for one destination",
              scan(v)["rename_candidates"],
              [{"slug": "Y", "new_slug": "median", "inbound_links": 0,
                "target_exists": True, "path": "d/Y.md"},
               {"slug": "solo", "new_slug": "solo-entry", "inbound_links": 0,
                "target_exists": False},
               {"slug": "x", "new_slug": "mean", "inbound_links": 0,
                "target_exists": False, "path": "a/x.md"},
               {"slug": "y", "new_slug": "median", "inbound_links": 0,
                "target_exists": True, "path": "c/y.md"}])
        v = os.path.join(tmp, "v18c-rename-twins-reversed")
        for _rel, _title in (("a/x.md", "X"), ("b/x.md", "Mean"),
                             ("c/z.md", "Z"), ("d/Z.md", "z")):
            _st_write(v, _rel, _st_entry(
                _title, "**%s** is a worked example." % _title))
        check("the second file of a shared basename gets its rename row, and "
              "a twin occupies its case-only destination",
              [(r["slug"], r["new_slug"], r["target_exists"], r["path"])
               for r in scan(v)["rename_candidates"]],
              [("Z", "z", True, "d/Z.md"), ("x", "mean", False, "b/x.md")])

        # Frontmatter, date, description, title and opener checks that no
        # other case pins, each in an otherwise schema-clean entry.
        v = os.path.join(tmp, "v18c-field-checks")
        for _name, _text in (
                ("read-missing", _st_entry(
                    "Read missing", "**Read missing** is a worked example.")
                 .replace("read: false\n", "")),
                ("read-bare", _st_entry(
                    "Read bare", "**Read bare** is a worked example.")
                 .replace("read: false\n", "read:\n")),
                ("read-tilde", _st_entry(
                    "Read tilde", "**Read tilde** is a worked example.")
                 .replace("read: false\n", "read: ~\n")),
                ("out-of-order", _st_entry(
                    "Out of order", "**Out of order** is a worked example.")
                 .replace('title: "Out of order"\ntype: Concept\n',
                          'type: Concept\ntitle: "Out of order"\n')),
                ("duplicate-key", _st_entry(
                    "Duplicate key", "**Duplicate key** is a worked example.")
                 .replace("type: Concept\n", "type: Concept\ntype: Concept\n")),
                ("1984", _st_entry(
                    "1984", "***1984*** is a worked example.", type_="Work")
                 .replace('title: "1984"', "title: 1984")),
                # Valid YAML that is not double-quoted, so the entry still
                # parses and only the quoting rule fires.
                ("desc-colon", _st_entry(
                    "Desc colon", "**Desc colon** is a worked example.")
                 .replace('description: "Desc colon is a worked example used '
                          'by the self-test."',
                          "description: 'Desc colon is a worked example: "
                          "with a colon.'")),
                ("quoted-type", _st_entry(
                    "Quoted type", "**Quoted type** is a worked example.")
                 .replace("type: Concept\n", 'type: "Concept"\n')),
                ("quoted-date", _st_entry(
                    "Quoted date", "**Quoted date** is a worked example.")
                 .replace("created: 2026-01-01", 'created: "2026-01-01"')),
                ("impossible-date", _st_entry(
                    "Impossible date", "**Impossible date** is a worked example.")
                 .replace("created: 2026-01-01", "created: 2026-02-30")),
                ("no-updated", _st_entry(
                    "No updated", "**No updated** is a worked example.")
                 .replace("updated: 2026-01-02\n", "")),
                ("long-description", _st_entry(
                    "Long description", "**Long description** is a worked "
                    "example.", description="Long description " + "x" * 93
                    + ".")),
                ("cjk-title", _st_entry(
                    "\u6f22\u5b57", "**\u6f22\u5b57** is a worked example.",
                    description="\u6f22\u5b57 is a worked example.")),
                ("list-opener", _st_entry(
                    "List opener", "- **List opener** is a worked example.")),
                ("data-set", _st_entry(
                    "Data set", "**Data set** is a worked example.")),
                ("dataset", _st_entry(
                    "Dataset", "**Dataset** is a worked example.")),
                ("u-law-algorithm", _st_entry(
                    "\u00b5-law algorithm",
                    "**\u00b5-law algorithm** is a worked example.")),
                ("mu-law-algorithm", _st_entry(
                    "\u03bc-law algorithm",
                    "**\u03bc-law algorithm** is a worked example.")),
                ("setext-mention", _st_entry(
                    "Setext mention", "**Setext mention** is a worked "
                    "example.\n\nData set\n===\n\nMore prose.")),
                ("plain-mention", _st_entry(
                    "Plain mention", "**Plain mention** is a worked "
                    "example.\n\nA data set follows."))):
            _st_write(v, _name + ".md", _text)
        res = scan(v)
        check("a missing, bare or `~` read: is report-only read-missing or "
              "read-null",
              [[key for key in _st_keys(res, slug_) if key.startswith("item2/read")]
               for slug_ in ("read-missing", "read-bare", "read-tilde")],
              [["item2/read-missing"], ["item2/read-null"], ["item2/read-null"]])
        check("a report-only read: message names the user-issue and "
              "merge-survivor exceptions",
              [("user_issues" in _st_msg(res, slug_, key_),
                "merge's survivor" in _st_msg(res, slug_, key_))
               for slug_, key_ in (("read-missing", "item2/read-missing"),
                                   ("read-bare", "item2/read-null"),
                                   ("read-tilde", "item2/read-null"))],
              [(True, True)] * 3)
        check("schema order, duplicate keys, an unquoted numeric title, a "
              "single-quoted description and quoted type/date values are "
              "item2",
              [(_st_keys(res, slug_), needle in _st_msg(res, slug_, "item2"))
               for slug_, needle in (
                   ("out-of-order", "fields out of schema order"),
                   ("duplicate-key", "duplicate frontmatter key"),
                   ("1984", "title must be double-quoted"),
                   ("desc-colon", "description must be double-quoted"),
                   ("quoted-type", "type must not be quoted"),
                   ("quoted-date", "created must not be quoted"))],
              [(["item2"], True)] * 6)
        check("an impossible calendar date and a missing updated: are item3",
              ("is not a valid date" in _st_msg(res, "impossible-date", "item3"),
               "updated missing" in _st_msg(res, "no-updated", "item3")),
              (True, True))
        check("a 111-character description is item7",
              "111 chars > 110" in _st_msg(res, "long-description", "item7"), True)
        check("an unsluggable title is item5 and never a rename candidate",
              ("cannot be slugged automatically" in _st_msg(
                  res, "cjk-title", "item5"),
               [row for row in res["rename_candidates"]
                if row["slug"] == "cjk-title"]), (True, []))
        check("a body that opens with a list is item9",
              "does not open with a prose sentence" in _st_msg(
                  res, "list-opener", "item9"), True)
        check("the hyphenation and micro-sign probes report their pairs",
              sorted((c["a"], c["b"], c["probe"])
                     for c in res["collision_candidates"]),
              [("data-set", "dataset", "hyphenation"),
               ("mu-law-algorithm", "u-law-algorithm", "\u00b5-variant")])
        check("Setext heading text is not a backfill surface; the same "
              "mention in prose is",
              [(b["slug"], b["target"]) for b in res["backfill_candidates"]
               if b["target"] in ("data-set", "dataset")],
              [("plain-mention", "data-set")])

        # A heading that repeats the title is deleted, never demoted, and
        # item 16 reads the first prose paragraph as the opener.
        v = os.path.join(tmp, "v19a-title-heading")
        for _name, _prose in (
                ("title-heading", "# Title heading\n\n**Title heading** is a "
                                  "worked example."),
                ("overview-first", "## Overview\n\n**Overview first** is a "
                                   "worked example."),
                ("heading-deleted", "**Heading deleted** is a worked "
                                    "example.")):
            _st_write(v, _name + ".md", _st_entry(
                _name.replace("-", " ").capitalize(), _prose))
        res = scan(v)
        check("a leading title heading is one item9 finding and the real "
              "opener is clean; a leading non-title heading is item9 only",
              [[key for key in _st_keys(res, slug_)
                if key.startswith(("item9", "item16"))]
               for slug_ in ("title-heading", "overview-first",
                             "heading-deleted")],
              [["item9"], ["item9"], []])
        check("a title heading is deleted, never demoted",
              ("delete it, never demote it" in _st_msg(
                  res, "title-heading", "item9"),
               "level must be exactly" in _st_msg(
                   res, "title-heading", "item9"),
               "does not open with a prose sentence" in _st_msg(
                   res, "overview-first", "item9")),
              (True, False, True))

        v = os.path.join(tmp, "v19-backfill-ownership")
        _st_write(v, 'aaa-technique.md', _st_entry('AAA technique',
                  '**AAA technique** is a worked example.', aliases=('"calibration"', '"shared-method"')))
        _st_write(v, 'calibration.md', _st_entry('Calibration',
                  '**Calibration** is a worked example.'))
        _st_write(v, 'second-technique.md', _st_entry('Second technique',
                  '**Second technique** is a worked example.', aliases=('"shared-method"', '"unique-method"')))
        for rel in ('first/duplicate.md', 'second/duplicate.md'):
            _st_write(v, rel, _st_entry('Duplicate', '**Duplicate** is a worked example.'))
        _st_write(v, 'reader.md', _st_entry('Reader',
                  '**Reader** uses calibration, shared methods, duplicates and a unique method.'))
        before = {p: Path(p).read_bytes() for p in iter_entry_files(v)}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main([v])
        res = json.loads(buf.getvalue())
        check("ambiguous backfill surfaces never choose a first owner, but unique aliases remain",
              (rc, [(b['slug'], b['target'], b['surface']) for b in res['backfill_candidates']]),
              (0, [('reader', 'second-technique', 'unique method')]))
        check("the ownership scan leaves every entry byte-for-byte unchanged",
              {p: Path(p).read_bytes() for p in iter_entry_files(v)}, before)

        # The CLI refuses a vault root as WIKI; the scan() API is unguarded.
        _root_vault = os.path.join(tmp, "v19b-vault-root")
        _st_write(_root_vault, "Wiki/entry.md", _st_entry(
            "Entry", "**Entry** is a worked example."))
        _obsidian_only = os.path.join(tmp, "v19b-obsidian-only")
        os.makedirs(os.path.join(_obsidian_only, ".obsidian"))
        _root_codes = []
        for _root_argv in ([_root_vault],
                           [_obsidian_only],
                           [os.path.join(_root_vault, "Wiki"),
                            "--vault", os.path.join(_root_vault, "Wiki")]):
            _root_err = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(_root_err):
                try:
                    _root_codes.append(main(_root_argv))
                except SystemExit as exc:
                    _root_codes.append(
                        (exc.code, "looks like a vault root"
                         in _root_err.getvalue()))
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            _root_codes.append(main([os.path.join(_root_vault, "Wiki"),
                                     "--vault", _root_vault]))
        check("the CLI exits 2 when WIKI holds .obsidian/ or Wiki/ or equals "
              "--vault, and scans <vault>/Wiki",
              _root_codes, [(2, True), (2, True), (2, True), 0])

        # WIKI must lie inside the vault and be the wiki folder itself.
        _other_vault = os.path.join(tmp, "v19c-other-vault")
        os.makedirs(os.path.join(_other_vault, ".obsidian"))
        os.makedirs(os.path.join(_other_vault, "Sources", "Images"))
        _sub_vault = os.path.join(tmp, "v19c-subfolder")
        os.makedirs(os.path.join(_sub_vault, ".obsidian"))
        _st_write(_sub_vault, "Wiki/variance.md", _st_entry(
            "Variance", "**Variance** is a worked example."))
        _st_write(_sub_vault, "Wiki/sub/spread.md", _st_entry(
            "Spread", "**Spread** uses [[variance]]."))
        _sub_wiki = os.path.join(_sub_vault, "Wiki", "sub")
        _place_codes = []
        for _place_argv, _place_text in (
                ([os.path.join(_root_vault, "Wiki"), "--vault", _other_vault],
                 "is not inside the vault"),
                ([os.path.join(_root_vault, "Wiki"), "--images",
                  os.path.join(_other_vault, "Sources", "Images")],
                 "is not inside the vault"),
                ([_sub_wiki], "is a subfolder of the wiki folder"),
                ([_sub_wiki, "--vault", _sub_vault],
                 "is a subfolder of the wiki folder")):
            _place_err = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(_place_err):
                try:
                    _place_codes.append(main(_place_argv))
                except SystemExit as exc:
                    _place_codes.append(
                        (exc.code, _place_text in _place_err.getvalue()))
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            _place_codes.append(main([os.path.join(_root_vault, "Wiki"),
                                      "--vault", _root_vault + os.sep]))
        check("the CLI exits 2 when WIKI is outside the vault or inside its "
              "wiki folder, and accepts a --vault with a trailing separator",
              _place_codes, [(2, True), (2, True), (2, True), (2, True), 0])

        # One vault reached under another spelling, a symlink alias or an
        # NFD name, is read in WIKI's own spelling.
        _spell_parent = os.path.join(tmp, "v19d-spelling")
        _spell_vault = os.path.join(_spell_parent, "Café vault")
        os.makedirs(os.path.join(_spell_vault, ".obsidian"))
        _spell_wiki = os.path.join(_spell_vault, "Wiki")
        _st_write(_spell_wiki, "statistics.md", _st_entry(
            "Statistics", "**Statistics** is a worked example."))
        _st_write(_spell_wiki, "leaf.md", _st_entry(
            "Leaf", "**Leaf** is a worked example.",
            parents=('"[[statistics]]"',)))
        _st_write(_spell_vault, "MOCs/statistics-moc.md",
                  "- [[Wiki/statistics|Statistics]]\n"
                  "  - [[Wiki/leaf|Leaf]]\n")

        def _spell_scan(vault_arg):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), \
                    contextlib.redirect_stderr(io.StringIO()):
                code = main([_spell_wiki, "--vault", vault_arg])
            report = json.loads(out.getvalue())
            return (code, report["vault_root"],
                    report["hierarchy_diagnostic"]["moc_consistency_findings"],
                    [p for p in report["problems"]
                     if p["item"] == "item2/parents-form"])

        _spell_aliases = []
        _spell_link = os.path.join(_spell_parent, "vault-alias")
        try:
            os.symlink(_spell_vault, _spell_link, target_is_directory=True)
            _spell_aliases.append(_spell_link)
        except (OSError, NotImplementedError):
            pass  # no symlinks on this host
        _spell_nfd = unicodedata.normalize("NFD", _spell_vault)
        if os.path.isdir(_spell_nfd):
            _spell_aliases.append(_spell_nfd)
        check("a --vault spelled through a symlink or an NFD name scans as "
              "WIKI's own spelling (where the host supports it)",
              [_spell_scan(alias) for alias in [_spell_vault] + _spell_aliases],
              [(0, _spell_vault, [], [])] * (1 + len(_spell_aliases)))

        # Where the host folds case, `<vault>/wiki` opens `<vault>/Wiki`: the
        # note index still skips that folder, and the CLI spells it `Wiki`.
        _fold_vault = os.path.join(tmp, "v19d-case-variant")
        os.makedirs(os.path.join(_fold_vault, ".obsidian"))
        _fold_wiki = os.path.join(_fold_vault, "Wiki")
        _st_write(_fold_wiki, "mean.md", _st_entry(
            "Mean", "**Mean** is a worked example.",
            aliases=('"average"',)))
        _st_write(_fold_wiki, "variance.md", _st_entry(
            "Variance", "**Variance** is a worked example."))
        _st_write(_fold_vault, "Articles/variance.md", "An outside note.\n")
        _st_write(_fold_wiki, "reader.md", _st_entry(
            "Reader", "**Reader** uses [[Wiki/mean|mean]], the [[average]] "
            "and [[Wiki/variance|variance]]."))
        _fold_variant = os.path.join(_fold_vault, "wiki")
        if os.path.isdir(_fold_variant):
            def _fold_cli(wiki_arg):
                out = io.StringIO()
                with contextlib.redirect_stdout(out), \
                        contextlib.redirect_stderr(io.StringIO()):
                    main([wiki_arg, "--vault", _fold_vault])
                return json.loads(out.getvalue())["problems"]
            check("a case-variant WIKI is skipped by the note index and "
                  "spelled as on disk",
                  ('"[[mean|average]]"' in _st_msg(
                      scan(_fold_variant, vault=_fold_vault), "reader",
                      "item10/alias"),
                   _fold_cli(_fold_variant) == _fold_cli(_fold_wiki)),
                  (True, True))

        # A filename that is not valid UTF-8 (a lone surrogate on Linux)
        # reaches --out as a JSON escape, as it reaches stdout.
        _bad_vault = os.path.join(tmp, "v19e-undecodable-name")
        _st_write(_bad_vault, "anchor.md", _st_entry(
            "Anchor", "**Anchor** is a worked example."))
        _bad_out = os.path.join(tmp, "v19e-scan.json")
        _bad_real_walk = os.walk

        def _surrogate_walk(root, *args, **kwargs):
            for dirpath, dirnames, filenames in _bad_real_walk(
                    root, *args, **kwargs):
                if os.path.normpath(dirpath) == os.path.normpath(_bad_vault):
                    filenames = list(filenames) + ["caf\udce9.md"]
                yield dirpath, dirnames, filenames

        with patch.object(os, "walk", _surrogate_walk), \
                contextlib.redirect_stderr(io.StringIO()):
            _bad_rc = main([_bad_vault, "--out", _bad_out])
        with open(_bad_out, encoding="utf-8") as fh:
            _bad_slugs = [p["slug"] for p in json.load(fh)["problems"]]
        check("--out writes a filename that is not valid UTF-8 as a JSON "
              "escape instead of crashing",
              (_bad_rc, "caf\udce9" in _bad_slugs), (0, True))

        v = os.path.join(tmp, "v20-bare-target-plurals")
        for name, title in (('entropy', 'Entropy'), ('information-entropy', 'Information entropy')):
            _st_write(v, name + '.md', _st_entry(title, '**%s** is a worked example.' % title))
        _st_write(v, 'reader.md', _st_entry('Reader',
                  '**Reader** compares entropies and information entropies.'))
        check("a plural cannot bypass the bare-common-noun destination gate",
              [(b['target'], b['surface']) for b in scan(v)['backfill_candidates']
               if b['slug'] == 'reader'], [('information-entropy', 'information entropies')])

        v = os.path.join(tmp, "v21-public-contract")
        _st_write(v, "invalid-type.md", _st_entry(
            "Invalid type", "**Invalid type** is a worked example.", type_="Model"))
        _st_write(v, "list-type.md", _st_entry(
            "List type", "**List type** is a worked example.").replace(
            "type: Concept", "type: [Concept]"))
        _st_write(v, "lower-description.md", _st_entry(
            "Lower description", "**Lower description** is a worked example.",
            description="lower description is a worked example used by the self-test."))
        _st_write(v, "periodless-description.md", _st_entry(
            "Periodless description", "**Periodless description** is a worked example.",
            description="Periodless description is a worked example used by the self-test"))
        _st_write(v, "raw-ell-description.md", _st_entry(
            "Raw ell description", "**Raw ell description** is a worked example.",
            description="Raw ell description uses an ℓ1 distance."))
        _raw_ell_card = _st_entry(
            "Raw ell card", "**Raw ell card** is a worked example.")
        _raw_ell_card = _raw_ell_card.replace(
            "The idea this entry is about, stated once.",
            "A quantity measured under an ℓ2 distance.")
        _st_write(v, "raw-ell-card.md", _raw_ell_card)
        _st_write(v, "raw-ell-prose.md", _st_entry(
            "Raw ell prose",
            "**Raw ell prose** uses an ℓ1 distance in its definition."))
        _raw_micro_card = _st_entry(
            "Raw micro card", "**Raw micro card** is a worked example.")
        _raw_micro_card = _raw_micro_card.replace(
            "The idea this entry is about, stated once.",
            "A specimen is 10 µm wide.")
        _st_write(v, "raw-micro-card.md", _raw_micro_card)
        _st_write(v, "raw-micro-prose.md", _st_entry(
            "Raw micro prose",
            "**Raw micro prose** describes a specimen that is 10 μm wide."))
        _st_write(v, "unicode-micro-description.md", _st_entry(
            "Unicode micro description",
            "**Unicode micro description** is a worked example.",
            description=(
                "Unicode micro description depicts features at a 10 μm scale.")))
        _st_write(v, "wrong-level-heading.md", _st_entry(
            "Wrong level heading", "**Wrong level heading** is a worked example.\n\n"
            "### A narrower aspect\n\nThe aspect remains part of the entry."))
        _st_write(v, "marked-up-heading.md", _st_entry(
            "Marked up heading", "**Marked up heading** is a worked example.\n\n"
            "## [[canonical-target|A linked aspect]]\n\nThe aspect remains part of the entry."))
        _st_write(v, "markdown-link-heading.md", _st_entry(
            "Markdown link heading",
            "**Markdown link heading** is a worked example.\n\n"
            "## [A linked aspect](target)\n\nThe aspect remains part of the entry."))
        _st_write(v, "html-heading.md", _st_entry(
            "Html heading", "**Html heading** is a worked example.\n\n"
            "## <em>An aspect</em>\n\nThe aspect remains part of the entry."))
        _st_write(v, "code-heading.md", _st_entry(
            "Code heading", "**Code heading** is a worked example.\n\n"
            "## `An aspect`\n\nThe aspect remains part of the entry."))
        _st_write(v, "no-prose-opener.md", _st_entry(
            "No prose opener", ""))
        _st_write(v, "setext-heading.md", _st_entry(
            "Setext heading", "**Setext heading** is a worked example.\n\n"
            "A narrower aspect\n-----------------\n\n"
            "The aspect remains part of the entry."))
        _st_write(v, "two-sentence-description.md", _st_entry(
            "Two sentence description",
            "**Two sentence description** is a worked example.",
            description="Two sentence description states one claim. It adds another."))
        _st_write(v, "question-description.md", _st_entry(
            "Question description", "**Question description** is a worked example.",
            description="Question description asks why? It supplies an answer."))
        for _slug, _suffix in (
                ("markdown-link-description",
                 "contains a [link](https://example.test)."),
                ("reference-link-description", "contains a [link][target]."),
                ("underscore-description", "contains _emphasis_."),
                ("html-description", "contains <em>HTML</em>."),
                ("strikethrough-description", "contains ~~strikethrough~~."),
                ("footnote-description", "contains a footnote[^1]."),
                ("tag-description", "contains an #inline-tag."),
                ("highlight-description", "contains ==highlighting==."),
                ("comment-description", "contains %%hidden text%%.")):
            _title = _slug.replace("-", " ").capitalize()
            _st_write(v, _slug + ".md", _st_entry(
                _title, "**%s** is a worked example." % _title,
                description="%s %s" % (_title, _suffix)))
        for _slug, _description in (
                ("decimal-description", "Decimal description reports 3.5 percent error."),
                ("version-description", "Version description covers GPT-4.5 behavior."),
                ("initial-description", "Initial description follows work by B. F. Skinner."),
                ("us-description", "Us description operates in the U.S."),
                ("rank-description", "Rank description compares Brassica var. capitata.")):
            _title = _slug.replace("-", " ").capitalize()
            _st_write(v, _slug + ".md", _st_entry(
                _title, "**%s** is a worked example." % _title,
                description=_description))
        _st_write(v, "arxiv.md", _st_entry(
            "arxiv", "**arxiv** is a scholarly archive.",
            description="arxiv is a scholarly archive."))
        _st_write(v, "fairness.md", _st_entry(
            "Fairness", "**Fairness** compares group outcomes.",
            description="Machine learning fairness compares group outcomes."))
        _st_write(v, "placeholder-subject.md", _st_entry(
            "Placeholder subject", "**Placeholder subject** compares groups.",
            description="This method compares groups."))
        _st_write(v, "canonical-target.md", _st_entry(
            "Canonical target", "**Canonical target** is a worked example.",
            aliases=('"canonical-name"',)))
        _st_write(v, "redundant-pipe.md", _st_entry(
            "Redundant pipe", "**Redundant pipe** builds on "
            "[[canonical-target|canonical-target]]."))
        _st_write(v, "non-slug-alias.md", _st_entry(
            "Non-slug alias", "**Non-slug alias** is a worked example.",
            aliases=('"True Positive Rate"',)))
        _st_write(v, "scalar-alias.md", _st_entry(
            "Scalar alias", "**Scalar alias** is a worked example.").replace(
            "sources:\n", 'aliases: "scalar-alias-name"\nsources:\n', 1))
        _st_write(v, "scalar-bound-card.md", _st_entry(
            "Scalar bound card", "**Scalar bound card** (SBC) is a worked example.",
            aliases=('"sbc"',), card="Scalar bound card (SBC)").replace(
            'aliases:\n  - "sbc"\n', 'aliases: "sbc"\n'))
        _st_write(v, "blank-alias.md", _st_entry(
            "Blank alias", "**Blank alias** is a worked example.").replace(
            "sources:\n", "aliases:\nsources:\n", 1))
        _st_write(v, "empty-flow-alias.md", _st_entry(
            "Empty flow alias", "**Empty flow alias** is a worked example.").replace(
            "sources:\n", "aliases: []\nsources:\n", 1))
        _st_write(v, "related-reader.md", _st_entry(
            "Related reader", "**Related reader** is a worked example.",
            related="[[arxiv]] · [[canonical-target]]"))
        _st_write(v, "related-anchored.md", _st_entry(
            "Related anchored", "**Related anchored** is a worked example.",
            related="[[canonical-target#Details]] · [[Wiki/canonical-target.md^block]]"))
        _st_write(v, "related-alias.md", _st_entry(
            "Related alias", "**Related alias** is a worked example.",
            related="[[canonical-name#Details]]"))
        _st_write(v, "related-wrong-label.md", _st_entry(
            "Related wrong label", "**Related wrong label** is a worked example.",
            related="[[canonical-target#Details|target]]"))
        _st_write(v, "related-foreign-label.md", _st_entry(
            "Related foreign label",
            "**Related foreign label** is a worked example.",
            related="[[canonical-target|Zebra]]"))
        _st_write(v, "related-marked-label.md", _st_entry(
            "Related marked label",
            "**Related marked label** is a worked example.",
            related="[[canonical-target|*Canonical* target]]"))
        _st_write(v, "related-piped.md", _st_entry(
            "Related piped", "**Related piped** is a worked example.",
            related="[[arxiv|arxiv]] · [[Wiki/canonical-target#Details|Canonical target]]"))
        _st_write(v, "wrong-card.md", _st_entry(
            "Wrong card", "**Wrong card** is a worked example.",
            card="Different term"))
        _st_write(v, "feature-machine-learning.md", _st_entry(
            "Feature (machine learning)", "**Feature** is a worked example.",
            card="Feature", description="A feature is a worked example."))
        _st_write(v, "feature-statistics.md", _st_entry(
            "Feature (statistics)", "**Feature** is a worked example.",
            card="Feature",
            description="Feature (statistics) is a worked example."))
        _st_write(v, "feature-biology.md", _st_entry(
            "Feature (biology)", "**Feature (biology)** is a worked example.",
            card="Feature", description="A feature is a worked example."))
        _st_write(v, "k-nearest-neighbors.md", _st_entry(
            "$k$-nearest neighbors",
            "**$\\boldsymbol{k}$-nearest neighbors** is a worked example.",
            card="k-nearest neighbors",
            description="k-nearest neighbors is a worked example."))
        _st_write(v, "principal-component-analysis.md", _st_entry(
            "Principal component analysis",
            "**Principal component analysis** (PCA) is a worked example.",
            aliases=('"pca"',), card="Principal component analysis (PCA)"))
        _st_write(v, "missing-counterpart.md", _st_entry(
            "Missing counterpart", "**Missing counterpart** (MC) is a worked example.",
            aliases=('"mc"',), card="Missing counterpart"))
        _st_write(v, "wrong-counterpart-case.md", _st_entry(
            "Wrong counterpart case",
            "**Wrong counterpart case** (WCC) is a worked example.",
            aliases=('"wcc"',), card="Wrong counterpart case (wcc)"))
        _st_write(v, "synonym-parenthetical.md", _st_entry(
            "Synonym parenthetical", "**Synonym parenthetical** is a worked example.",
            aliases=('"alternate-name"',),
            card="Synonym parenthetical (alternate-name)"))
        _st_write(v, "wrong-title-case.md", _st_entry(
            "Wrong title case", "**Wrong title case** is a worked example.",
            card="wrong title case"))
        _st_write(v, "archaea.md", _st_entry(
            "Archaea", "**Archaea** (singular, *archaeon*) is a domain of organisms.",
            aliases=('"archaeon"',), card="Archaea"))
        _st_write(v, "singular-parenthetical.md", _st_entry(
            "Bacteria", "**Bacteria** (singular, *bacterium*) is a domain of organisms.",
            aliases=('"bacterium"',), card="Bacteria (bacterium)"))
        _st_write(v, "adaboost.md", _st_entry(
            "AdaBoost",
            "**AdaBoost** (short for *adaptive boosting*) reweights mistakes.",
            aliases=('"adaptive-boosting"',),
            card="AdaBoost (adaptive boosting)"))
        _st_write(v, "boosting.md", _st_entry(
            "Boosting",
            "**Boosting** (originally called *hypothesis boosting*) combines "
            "weak learners.", aliases=('"hypothesis-boosting"',),
            card="Boosting"))
        _st_write(v, "boosting-with-synonym.md", _st_entry(
            "Boosting with synonym",
            "**Boosting with synonym** (originally called *early boosting*) "
            "combines weak learners.", aliases=('"early-boosting"',),
            card="Boosting with synonym (early boosting)"))
        _st_write(v, "saccharomyces-cerevisiae.md", _st_entry(
            "Saccharomyces cerevisiae",
            "***Saccharomyces cerevisiae*** (*S. cerevisiae*) is a model "
            "budding yeast.", type_="Organism", aliases=('"s-cerevisiae"',),
            card="Saccharomyces cerevisiae (S. cerevisiae)"))
        _st_write(v, "mus-musculus.md", _st_entry(
            "Mus musculus", "***Mus musculus*** is the mouse used in laboratories.",
            type_="Organism",
            description="Mus musculus is the mouse used in laboratories."))
        _st_write(v, "mus-musculus-biology.md", _st_entry(
            "Mus musculus (biology)",
            "***Mus musculus*** is a laboratory model species.",
            type_="Organism", aliases=('"m-musculus"',), card="Mus musculus",
            description="Mus musculus is a laboratory model species."))
        _st_write(v, "african-elephant.md", _st_entry(
            "African elephant", "**African elephant** is a large land mammal.",
            type_="Organism"))
        _st_write(v, "canis-lupus-familiaris.md", _st_entry(
            "Canis lupus familiaris",
            "***Canis lupus familiaris*** is the domestic dog.",
            type_="Organism", aliases=('"c-lupus-familiaris"',)))
        _st_write(v, "drosophila-melanogaster.md", _st_entry(
            "Drosophila melanogaster",
            "**Drosophila melanogaster** is a model fruit fly.",
            type_="Organism", aliases=('"d-melanogaster"',)))
        _st_write(v, "e-coli-k-12.md", _st_entry(
            "E. coli K-12", "***E. coli* K-12** is a laboratory strain.",
            type_="Organism"))
        _st_write(v, "e-coli-b-2.md", _st_entry(
            "E. coli B-2", "***E. coli B-2*** is a laboratory strain.",
            type_="Organism"))
        _st_write(v, "hamlet.md", _st_entry(
            "Hamlet", "***Hamlet*** is a tragedy by Shakespeare.", type_="Work"))
        _st_write(v, "macbeth.md", _st_entry(
            "Macbeth", "****Macbeth**** is a tragedy by Shakespeare.", type_="Work"))
        _st_write(v, "pan-troglodytes.md", _st_entry(
            "Pan troglodytes", "****Pan troglodytes**** is a great ape.",
            type_="Organism", aliases=('"p-troglodytes"',)))
        _st_write(v, "king-lear.md", _st_entry(
            "King Lear", "**King Lear** is a tragedy by Shakespeare.", type_="Work"))
        _st_write(v, "asgard-archaea.md", _st_entry(
            "Asgard archaea", "**Asgard archaea** are an archaeal lineage.",
            type_="Organism"))
        _st_write(v, "rattus-norvegicus.md", _st_entry(
            "Rattus norvegicus",
            "***Rattus norvegicus*** is the laboratory rat; a mouse is a "
            "different organism.", type_="Organism",
            description="Rattus norvegicus is the laboratory rat."))
        _st_write(v, "common-name-reader.md", _st_entry(
            "Common name reader",
            "**Common name reader** compares [[mus-musculus|mouse]] with "
            "[[rattus-norvegicus|mouse]]."))
        _st_write(v, "common-name-backfill-reader.md", _st_entry(
            "Common name backfill reader",
            "**Common name backfill reader** studies the mouse in laboratories."))
        _st_write(v, "imperative-link.md", _st_entry(
            "Imperative link", "**Imperative link** adds detail "
            "(see [[canonical-target|Canonical target]])."))
        _st_write(v, "ordinary-see.md", _st_entry(
            "Ordinary see", "**Ordinary see** varies a threshold to see how "
            "the error changes."))
        _st_write(v, "semantic-see.md", _st_entry(
            "Semantic see", "**Semantic see** records how researchers see "
            "[[canonical-target|models]] as approximations."))
        _st_write(v, "listed-imperative.md", _st_entry(
            "Listed imperative", "**Listed imperative** shows syntax.\n\n"
            "```markdown\nsee [[canonical-target]]\n```", type_="Software"))
        _st_write(v, "algorithm-counterpart.md", _st_entry(
            "Algorithm counterpart",
            "The **Algorithm counterpart** algorithm (AC) predicts from nearby "
            "observations.", aliases=('"ac"',),
            card="Algorithm counterpart (AC)"))
        _st_write(v, "ilsvrc.md", _st_entry(
            "ILSVRC",
            "**ILSVRC** (2010–2017) (ImageNet Large Scale Visual Recognition "
            "Challenge) was an annual competition.", type_="Event",
            aliases=('"imagenet-large-scale-visual-recognition-challenge"',),
            card="ILSVRC (ImageNet Large Scale Visual Recognition Challenge)"))
        _st_write(v, "mark-twain.md", _st_entry(
            "Mark Twain", "**Mark Twain** (Samuel Clemens) was an author.",
            aliases=('"samuel-clemens"',), card="Mark Twain"))
        _st_write(v, "counterpart-scope.md", _st_entry(
            "Counterpart scope",
            "**Counterpart scope** uses **Principal component analysis** (PCA).",
            aliases=('"pca"',), card="Counterpart scope"))
        _st_write(v, "a-star-search.md", _st_entry(
            "$A^{*}$ search",
            "**$\\boldsymbol{A}^{*}$ search** explores a graph.",
            card="A-star search"))
        _st_write(v, "b-star-search.md", _st_entry(
            "$B^{*}$ search",
            "**$\\boldsymbol{B}^{*}$ search** explores a graph.",
            card="B search"))
        _st_write(v, "chi-2-test.md", _st_entry(
            "$\\\\chi^2$ test",
            "**$\\chi^2$ test** compares observed and expected counts.",
            card="chi-squared test",
            description=(
                "chi-squared test compares observed and expected counts.")))
        _st_write(v, "ell-1-norm.md", _st_entry(
            "$\\\\ell_1$ norm",
            "**$\\ell_1$ norm** measures vector magnitude using absolute values.",
            card="ell-one norm",
            description=(
                "ell-one norm measures vector magnitude using absolute values.")))
        _st_write(v, "l-1-regularization.md", _st_entry(
            "$L^{-1}$ regularization",
            "**$L^{-1}$ regularization** is a worked mathematical example.",
            card="L-inverse regularization",
            description=(
                "L-inverse regularization is a worked mathematical example.")))
        _st_write(v, "x-1-2-transform.md", _st_entry(
            "$x^{1/2}$ transform",
            "**$x^{1/2}$ transform** is a worked mathematical example.",
            card="x-to-the-one-half transform",
            description=(
                "x-to-the-one-half transform is a worked mathematical example.")))
        _st_write(v, "r-plus.md", _st_entry(
            "$R^{+}$", "**$R^{+}$** is a worked mathematical example.",
            card="R-plus",
            description="R-plus is a worked mathematical example."))
        _st_write(v, "c-star-search.md", _st_entry(
            "$C^{*}$ search",
            "**$\\boldsymbol{C}^{*}$ search** explores a graph.",
            card=False)
            + "\n---\n\n## Flashcards\n\n"
              "A $C^{*}$ search explores a graph.\n??\nC-star search\n")
        res = scan(v)
        check("invalid and list-valued type fields both fail the canonical enum",
              ["item2/type-enum" in _st_keys(res, name)
               for name in ("invalid-type", "list-type")], [True, True])
        check("description capitalization and terminal-period checks are independent",
              ("capitalized" in _st_msg(res, "lower-description", "item7"),
               "period" in _st_msg(res, "periodless-description", "item7")),
              (True, True))
        check("raw ell typography covers descriptions, card prompts, and prose",
              [("item12/equation-typography" in _st_keys(res, slug_),
                remedy in _st_msg(
                    res, slug_, "item12/equation-typography"))
               for slug_, remedy in (
                   ("raw-ell-description", "ell-one"),
                   ("raw-ell-card", "$\\ell_1$"),
                   ("raw-ell-prose", "$\\ell_1$"))],
              [(True, True)] * 3)
        check("raw micro units in card prompts and prose use inline LaTeX",
              [("item12/equation-typography" in _st_keys(res, slug_),
                "$\\mu\\mathrm{m}$" in _st_msg(
                    res, slug_, "item12/equation-typography"))
               for slug_ in ("raw-micro-card", "raw-micro-prose")],
              [(True, True)] * 2)
        check("a description keeps its documented plain-Unicode allowance",
              "item12/equation-typography" in _st_keys(
                  res, "unicode-micro-description"), False)
        check("body headings use exactly ## and plain text",
              ["item9" in _st_keys(res, slug_) for slug_ in
               ("wrong-level-heading", "marked-up-heading",
                "markdown-link-heading", "html-heading", "code-heading")],
              [True] * 5)
        check("a Related footer cannot stand in for the required prose opener",
              "item9" in _st_keys(res, "no-prose-opener"), True)
        check("Setext body headings cannot evade the exactly-## rule",
              "item9" in _st_keys(res, "setext-heading"), True)
        check("the complete Markdown/HTML surface is non-plain description "
              "markup",
              ["non-plain-text markup" in _st_msg(res, slug_, "item7") for slug_ in
               ("markdown-link-description", "reference-link-description",
                "underscore-description", "html-description",
                "strikethrough-description", "footnote-description",
                "tag-description", "highlight-description",
                "comment-description")],
              [True] * 9)
        check("two declarative or question-ended description sentences are item 7",
              ["item7" in _st_keys(res, slug_) for slug_ in
               ("two-sentence-description", "question-description")],
              [True, True])
        check("description sentence counting ignores decimals, versions, initials, abbreviations, and taxonomic ranks",
              ["item7" in _st_keys(res, slug_) for slug_ in
               ("decimal-description", "version-description",
                "initial-description", "us-description", "rank-description")],
              [False] * 5)
        check("a lowercase canonical title may remain the description's subject",
              "item7" in _st_keys(res, "arxiv"), False)
        check("a different prefixed noun phrase is not the canonical subject",
              "canonical title or base term" in _st_msg(res, "fairness", "item7"), True)
        check("a placeholder subject is an item-7 mismatch",
              "canonical title or base term" in _st_msg(
                  res, "placeholder-subject", "item7"), True)
        check("a leading article plus parenthetical title's base term passes",
              "item7" in _st_keys(res, "feature-machine-learning"), False)
        check("the full qualified title is not a running-prose description subject",
              "item7" in _st_keys(res, "feature-statistics"), True)
        check("the full qualified title is not the bold running-prose opener",
              "item16" in _st_keys(res, "feature-biology"), True)
        check("first-letter case is the only case carve-out for a title subject",
              (description_has_entity_subject("ArXiv stores preprints.", "arXiv"),
               description_has_entity_subject("Arxiv stores preprints.", "arXiv")),
              (True, False))
        check("a human-readable alias is rejected in favor of its slug form",
              'expected "true-positive-rate"'
              in _st_msg(res, "non-slug-alias", "item18"), True)
        check("a scalar aliases field is rejected even when its value is a valid slug",
              "must be a list" in _st_msg(res, "scalar-alias", "item18"), True)
        check("a malformed scalar alias cannot establish a card counterpart",
              ("item18" in _st_keys(res, "scalar-bound-card"),
               "item19" in _st_keys(res, "scalar-bound-card")), (True, True))
        check("a bare aliases key is not an empty list",
              "must be a list" in _st_msg(res, "blank-alias", "item18"), True)
        # Keep the scalar-shape diagnostics above, then establish the complete
        # alias inventory needed by the independent link/backfill cases below.
        for name, alias in (("scalar-alias", "scalar-alias-name"),
                            ("scalar-bound-card", "sbc")):
            path = os.path.join(v, name + ".md")
            with open(path, encoding="utf-8") as fh:
                repaired = fh.read().replace(
                    'aliases: "' + alias + '"\n',
                    'aliases:\n  - "' + alias + '"\n')
            _st_write(v, name + ".md", repaired)
        link_res = scan(v)
        check("an explicitly empty flow aliases list has list shape",
              "item18" in _st_keys(res, "empty-flow-alias"), False)
        check("a mathematical title's plain form may be the description subject",
              "item7" in _st_keys(res, "k-nearest-neighbors"), False)
        check("A-star and chi-squared retain their meaning across title fields",
              [_st_keys(res, slug_)
               for slug_ in ("a-star-search", "chi-2-test")],
              [[], []])
        check("subscript, inverse, half-power, and positive titles retain their meaning",
              [_st_keys(res, slug_) for slug_ in (
                  "ell-1-norm", "l-1-regularization",
                  "x-1-2-transform", "r-plus")],
              [[], [], [], []])
        check("the former lossy B-search card spelling is rejected",
              "item19" in _st_keys(res, "b-star-search"), True)
        check("LaTeX star notation cannot hide a flashcard answer leak",
              'leaks the answer ("C-star search")'
              in _st_msg(res, "c-star-search", "item19"), True)
        check("Work, scientific taxon, mixed-strain, and common-name opener styles pass",
              ["item16" in _st_keys(res, name) for name in
               ("hamlet", "mus-musculus", "mus-musculus-biology",
                "e-coli-k-12", "asgard-archaea", "african-elephant",
                "canis-lupus-familiaris", "a-star-search")],
              [False, False, False, False, False, False, False, False])
        check("bad taxon/Work styles and over-emphasis fail",
              ["item16" in _st_keys(res, name) for name in
               ("drosophila-melanogaster", "king-lear", "e-coli-b-2",
                "macbeth", "pan-troglodytes")],
              [True, True, True, True, True])
        check("an explicitly bound Organism common name is a valid display label",
              "mouse" in _st_msg(res, "common-name-reader", "item18"), True)
        check("only the unrelated target common-name display remains an item-18 finding",
              _st_keys(res, "common-name-reader").count("item18"), 1)
        check("a uniquely bound Organism common name enters backfill without becoming an alias",
              [(b["target"], b["surface"], b["organism_common_name"])
               for b in link_res["backfill_candidates"]
               if b["slug"] == "common-name-backfill-reader"],
              [("mus-musculus", "mouse", True)])
        common_name_entry = {
                  "type": "Organism", "title": "Canis lupus familiaris",
                  "aliases": ["c-lupus-familiaris"],
                  "desc": "Canis lupus familiaris is commonly known as the domestic dog.",
                  "prose": "***Canis lupus familiaris*** is a model organism."
              }
        check("a binding covers the complete common-name phrase, not its head noun",
              (organism_common_name_bound(common_name_entry, "domestic dog"),
               organism_common_name_bound(common_name_entry, "dog")),
              (True, False))
        check("a navigation-only cue directly governing a wikilink is item9",
              "item9/imperative-link" in _st_keys(res, "imperative-link"), True)
        check("ordinary semantic uses of 'see' and fenced samples stay quiet",
              ["item9/imperative-link" in _st_keys(res, name)
               for name in ("ordinary-see", "semantic-see", "listed-imperative")],
              [False, False, False])
        check("every bare Related link is item11, including a lowercase title",
              (_st_keys(res, "related-reader").count("item11"),
               "arxiv" in _st_msg(res, "related-reader", "item11"),
               "Canonical target" in _st_msg(res, "related-reader", "item11")),
              (2, True, True))
        check("anchors and vault paths cannot hide bare Related links",
              _st_keys(res, "related-anchored").count("item11"), 2)
        check("a resolving alias target cannot hide a bare Related link",
              "Canonical target" in _st_msg(link_res, "related-alias", "item11"), True)
        check("a Related display label must equal the target's canonical title",
              "canonical title"
              in _st_msg(res, "related-wrong-label", "item11"), True)
        check("a Related label's wording is item 11 alone; its markup is item 18",
              [("item11" in _st_keys(res, name), "item18" in _st_keys(res, name))
               for name in ("related-foreign-label", "related-marked-label")],
              [(True, False), (True, True)])
        check("fully piped Related links are the valid near miss",
              "item11" in _st_keys(res, "related-piped"), False)
        check("an exact body display alias is redundant in the whole-vault linter",
              "item10/redundant-pipe" in _st_keys(res, "redundant-pipe"), True)
        check("the mandatory piped Related form is outside the body-only check",
              "item10/redundant-pipe" in _st_keys(res, "related-piped"), False)
        check("a flashcard term unrelated to the canonical title is rejected",
              "must be exactly"
              in _st_msg(res, "wrong-card", "item19"), True)
        check("parenthetical, math and acronym primary-answer forms stay valid",
              ["item19" in _st_keys(res, name) for name in
               ("feature-machine-learning", "k-nearest-neighbors",
                "principal-component-analysis")], [False, False, False])
        check("compound-derived and shared-tail acronyms remain valid counterparts",
              [acronym_counterpart(short, long) for short, long in (
                  ("ATP", "adenosine triphosphate"),
                  ("DNA", "deoxyribonucleic acid"),
                  ("RNA", "ribonucleic acid"),
                  ("MLOps", "ML operations"),
                  ("OOB evaluation", "out-of-bag evaluation"),
              )], [True, True, True, True, True])
        check("an opener-bound counterpart is mandatory and case-exact",
              ["item19" in _st_keys(res, name) for name in
               ("missing-counterpart", "wrong-counterpart-case")], [True, True])
        check("a synonym alias cannot authorize a line-3 parenthetical",
              "not an opener-established"
              in _st_msg(res, "synonym-parenthetical", "item19"), True)
        check("line 3 preserves the canonical title's casing",
              "same canonical casing"
              in _st_msg(res, "wrong-title-case", "item19"), True)
        check("a singular synonym in an annotated opener parenthetical is not a card counterpart",
              "item19" in _st_keys(res, "archaea"), False)
        check("appending that singular synonym to line 3 is rejected",
              "not an opener-established"
              in _st_msg(res, "singular-parenthetical", "item19"), True)
        check("a short-for expansion in the opener establishes its alias-bound "
              "flashcard counterpart",
              "item19" in _st_keys(res, "adaboost"), False)
        check("an originally-called synonym remains excluded from the required "
              "flashcard answer",
              "item19" in _st_keys(res, "boosting"), False)
        check("an originally-called synonym cannot be appended as an "
              "opener-established counterpart",
              "not an opener-established" in _st_msg(
                  res, "boosting-with-synonym", "item19"), True)
        check("a canonical triple-emphasis Organism opener establishes its "
              "direct italic scientific-abbreviation counterpart",
              "item19" in _st_keys(res, "saccharomyces-cerevisiae"), False)
        check("the documented intervening algorithm noun preserves an opener "
              "acronym binding",
              "item19" in _st_keys(res, "algorithm-counterpart"), False)
        check("a date before an acronym expansion keeps the card counterpart",
              "item19" in _st_keys(res, "ilsvrc"), False)
        check("pseudonyms and a later bold parenthetical are not acronym counterparts",
              ["item19" in _st_keys(res, name)
               for name in ("mark-twain", "counterpart-scope")], [False, False])
        check("an unrelated noun phrase and later parenthetical do not bind to "
              "the bolded title",
              bool(BOLD_PAREN_RE.search(
                  "**Algorithm counterpart** predicts a class (AC) nearby.")),
              False)
        import introduced_aliases as _alias_module
        check("item 17 reads the opener parenthetical and its lead-ins with "
              "the shared item-19 patterns",
              [_alias_module._BOLD_PAREN_RE is BOLD_PAREN_RE,
               _alias_module._PAREN_LEADIN_RE is PAREN_LEADIN_RE],
              [True, True])

        v = os.path.join(tmp, "v22-person-dates")
        _st_write(v, "w-e-b-du-bois.md", _st_entry(
            "W. E. B. Du Bois",
            "**W. E. B. Du Bois** (b. 1868) was an American sociologist.",
            type_="Person"))
        _st_write(v, "dated-person.md", _st_entry(
            "Dated person", "**Dated person** (1901–1980) was a researcher.",
            type_="Person"))
        _st_write(v, "active-person.md", _st_entry(
            "Active person", "**Active person** (fl. since 2020) is a researcher.",
            type_="Person"))
        _st_write(v, "misplaced-person-date.md", _st_entry(
            "Misplaced person date",
            "**Misplaced person date** received a 2020 prize (born 1980).",
            type_="Person"))
        _st_write(v, "dated-event.md", _st_entry(
            "Dated event", "**Dated event** (1990–1992) was a conference series.",
            type_="Event"))
        _st_write(v, "missing-event-date.md", _st_entry(
            "Missing event date", "**Missing event date** was a conference series.",
            type_="Event"))
        _st_write(v, "malformed-person-date.md", _st_entry(
            "Malformed person date",
            "**Malformed person date** (1901 to 1980) was a researcher.",
            type_="Person"))
        _st_write(v, "unspaced-person-date.md", _st_entry(
            "Unspaced person date",
            "**Unspaced person date**(1901–1980) was a researcher.",
            type_="Person"))
        _st_write(v, "malformed-event-date.md", _st_entry(
            "Malformed event date",
            "**Malformed event date** (1990-1992) was a conference series.",
            type_="Event"))
        _st_write(v, "impossible-event-date.md", _st_entry(
            "Impossible event date",
            "**Impossible event date** (1990-02-31) was a conference series.",
            type_="Event"))
        res = scan(v)
        check("Person/Event dates pass only in the parenthetical after the bold subject",
              ["item9" in _st_keys(res, name) for name in
               ("dated-person", "active-person", "misplaced-person-date",
                "dated-event", "missing-event-date",
                "malformed-person-date", "unspaced-person-date",
                "malformed-event-date",
                "impossible-event-date")],
              [False, False, True, False, True, True, True, True, True])
        check("malformed and missing date messages stay distinguishable",
              ("exact forms" in _st_msg(res, "malformed-person-date", "item9"),
               "exact forms" in _st_msg(res, "unspaced-person-date", "item9"),
               "needs a date" in _st_msg(res, "missing-event-date", "item9")),
              (True, True, True))

        v = os.path.join(tmp, "v23-table-captions")
        _st_write(v, "captioned-table.md", _st_entry(
            "Captioned table", "**Captioned table** is a worked example.\n\n"
            "Metric | Value\n--- | ---\nRecall | 0.8\n*Values by group.*"))
        _st_write(v, "math-bar-caption.md", _st_entry(
            "Math bar caption", "**Math bar caption** is a worked example.\n\n"
            "Metric | Value\n--- | ---\nError | 0.2\n*Error is $|x-y|$.*"))
        _st_write(v, "emphasized-row.md", _st_entry(
            "Emphasized row", "**Emphasized row** is a worked example.\n\n"
            "Metric | Value\n--- | ---\n*Recall* | *0.8*\n*Values by group.*"))
        _st_write(v, "missing-table-caption.md", _st_entry(
            "Missing table caption", "**Missing table caption** is a worked example.\n\n"
            "Metric | Value\n--- | ---\nRecall | 0.8"))
        _st_write(v, "gapped-table-caption.md", _st_entry(
            "Gapped table caption", "**Gapped table caption** is a worked example.\n\n"
            "Metric | Value\n--- | ---\nRecall | 0.8\n\n*Values by group.*"))
        _st_write(v, "linked-table-caption.md", _st_entry(
            "Linked table caption", "**Linked table caption** is a worked example.\n\n"
            "Metric | Value\n--- | ---\nRecall | 0.8\n*Values for [[group]].*"))
        _st_write(v, "coded-table-caption.md", _st_entry(
            "Coded table caption", "**Coded table caption** is a worked example.\n\n"
            "Metric | Value\n--- | ---\nRecall | 0.8\n*Values for `group`.*"))
        _st_write(v, "pipe-prose.md", _st_entry(
            "Pipe prose", "**Pipe prose** compares A | B in ordinary prose.\n"
            "The next line is not a delimiter."))
        _st_write(v, "fenced-table.md", _st_entry(
            "Fenced table", "**Fenced table** shows table syntax.\n\n"
            "```markdown\nMetric | Value\n--- | ---\nRecall | 0.8\n```",
            type_="Software"))
        _st_write(v, "indented-table.md", _st_entry(
            "Indented table", "**Indented table** shows table syntax.\n\n"
            "    Metric | Value\n    --- | ---\n    Recall | 0.8",
            type_="Software"))
        _st_write(v, "one-column-table.md", _st_entry(
            "One column table", "**One column table** is a worked example.\n\n"
            "| Metric |\n| --- |\n| Recall |\n*The reported metric.*"))
        _st_write(v, "one-column-missing-caption.md", _st_entry(
            "One column missing caption",
            "**One column missing caption** is a worked example.\n\n"
            "| Metric |\n| --- |\n| Recall |"))
        _st_write(v, "fenced-emphasis.md", _st_entry(
            "Fenced emphasis", "**Fenced emphasis** shows markup syntax.\n\n"
            "```markdown\n**[[missing-target]]**\n*`value`*\n```",
            type_="Software"))
        _st_write(v, "target-term.md", _st_entry(
            "Target term", "**Target term** is a worked example."))
        _st_write(v, "pipe-less-table-row.md", _st_entry(
            "Pipe-less table row",
            "**Pipe-less table row** is a worked example.\n\n"
            "Metric | Note\n--- | ---\n**Target term**\n"
            "*A row with fewer cells than the header.*"))
        _st_write(v, "linked-table-cell.md", _st_entry(
            "Linked table cell",
            "**Linked table cell** is a worked example.\n\n"
            "Metric | Note\n--- | ---\n**[[target-term|Target term]]**\n"
            "*A link inside a pipe-less table row.*"))
        _st_write(v, "table-link-then-prose.md", _st_entry(
            "Table link then prose",
            "**Table link then prose** is a worked example.\n\n"
            "Metric | Note\n--- | ---\n[[target-term|Target term]]\n"
            "*A link inside a pipe-less table row.*\n\n"
            "A later Target term mention belongs in prose."))
        res = scan(v)
        check("an immediate italic plain-text table caption passes item12",
              "item12" in _st_keys(res, "captioned-table"), False)
        check("permitted LaTeX bars in a caption are not consumed as a table row",
              "item12" in _st_keys(res, "math-bar-caption"), False)
        check("one-column GFM tables are detected for both passing and missing captions",
              ["item12" in _st_keys(res, name) for name in
               ("one-column-table", "one-column-missing-caption")],
              [False, True])
        check("an emphasized table row is not mistaken for the caption",
              "item12" in _st_keys(res, "emphasized-row"), False)
        check("a missing caption and an intervening blank are both detected",
              ["item12" in _st_keys(res, name) for name in
               ("missing-table-caption", "gapped-table-caption")], [True, True])
        check("a wikilink makes an otherwise italic table caption non-plain-text",
              "wikilink" in _st_msg(res, "linked-table-caption", "item12"), True)
        check("caption validation reads original text after code-masked table detection",
              "backtick" in _st_msg(res, "coded-table-caption", "item12"), True)
        check("pipe prose and fenced or indented table samples are not tables",
              ["item12" in _st_keys(res, name) for name in
               ("pipe-prose", "fenced-table", "indented-table")],
              [False, False, False])
        check("emphasis-looking markup inside a fence is neither item 16 nor a link",
              [key for key in _st_keys(res, "fenced-emphasis")
               if key in ("item16", "item10/dangling")], [])
        check("a pipe-less GFM body row is masked from item16 and backfill",
              ([key for key in _st_keys(res, "pipe-less-table-row")
                if key == "item16"],
               [(b["slug"], b["target"]) for b in res["backfill_candidates"]
                if b["slug"] == "pipe-less-table-row"]), ([], []))
        check("a wikilink in any parsed table row gets the dedicated item10 finding",
              ("item10/table" in _st_keys(res, "linked-table-cell"),
               "[[target-term|Target term]]" in _st_msg(
                   res, "linked-table-cell", "item10/table")), (True, True))
        check("table spans also mask emphasis wrapped around a cell link from item16",
              "item16" in _st_keys(res, "linked-table-cell"), False)
        check("a table-cell link is masked from the ordinary item10 resolver",
              [key for key in _st_keys(res, "linked-table-cell")
               if key in ("item10/dangling", "item10/dup", "item10/case",
                          "item10/alias", "item10/ambiguous", "item10/unparsed")], [])
        check("a prohibited table-cell link cannot suppress a later prose backfill",
              [(b["slug"], b["target"]) for b in res["backfill_candidates"]
               if b["slug"] == "table-link-then-prose"],
              [("table-link-then-prose", "target-term")])

        v = os.path.join(tmp, "v23b-equation-coverage")
        _st_write(v, "equationless.md", _st_entry(
            "Equationless", "**Equationless** is a measure. It is the square "
            "root of the variance and is denoted $\\sigma$."))
        _st_write(v, "equation-present.md", _st_entry(
            "Equation present", "**Equation present** is a measure. It is the "
            "square root of the variance:\n\n$$\n"
            "\\sigma = \\sqrt{\\operatorname{Var}(X)}\n$$"))
        _st_write(v, "equation-expanded.md", _st_entry(
            "Equation expanded", "**Equation expanded** is a measure. It is the "
            "square root of the variance:\n\n$$\n"
            "\\sigma = \\sqrt{\\frac{1}{N}"
            "\\sum_i (x_i - \\mu)^2}\n$$"))
        _st_write(v, "equation-unrelated.md", _st_entry(
            "Equation unrelated", "**Equation unrelated** is a measure. It is the "
            "square root of the variance:\n\n$$\n"
            "f(x) = \\sqrt{x} + \\operatorname{Var}(Y)\n$$"))
        _st_write(v, "equation-one-line.md", _st_entry(
            "Equation one line", "**Equation one line** is a measure. It is the "
            "square root of the variance:\n\n"
            "$$\\sigma = \\sqrt{\\operatorname{Var}(X)}$$"))
        _st_write(v, "equation-two-relations.md", _st_entry(
            "Equation two relations", "**Equation two relations** is a "
            "measure. It is the square root of the variance:\n\n$$\n"
            "\\sigma = \\sqrt{\\operatorname{Var}(X)}, \\qquad "
            "\\mu = \\operatorname{E}[X]\n$$"))
        _st_write(v, "equation-shared-open.md", _st_entry(
            "Equation shared open", "**Equation shared open** is a measure. It "
            "is the square root of the variance:\n\n"
            "$$\\sigma = \\sqrt{\\operatorname{Var}(X)}\n$$"))
        _st_write(v, "equation-bare-alignment.md", _st_entry(
            "Equation bare alignment", "**Equation bare alignment** is a "
            "measure. It is the square root of the variance:\n\n$$\n"
            "\\sigma &= \\sqrt{\\operatorname{Var}(X)} \\\\\n"
            "&= \\sqrt{\\operatorname{E}[(X - \\mu)^2]}\n$$"))
        _st_write(v, "equation-two-physical.md", _st_entry(
            "Equation two physical", "**Equation two physical** is a measure. "
            "It is the square root of the variance:\n\n$$\n"
            "\\sigma = \\sqrt{\\operatorname{Var}(X)}\n"
            "\\mu = \\operatorname{E}[X]\n$$"))
        _st_write(v, "negated-equation.md", _st_entry(
            "Negated equation", "**Negated equation** is a measure. It is not "
            "the square root of variance."))
        _st_write(v, "table-equation.md", _st_entry(
            "Table equation", "**Table equation** is a worked example.\n\n"
            "Claim | Value\n--- | ---\nSpread | It is the square root of variance.\n"
            "*Values by measure.*"))
        flash_only = _st_entry(
            "Flashcard equation", "**Flashcard equation** is a worked example.")
        flash_only = flash_only.replace(
            "The idea this entry is about, stated once.",
            "It is the square root of variance.")
        _st_write(v, "flashcard-equation.md", flash_only)
        _st_write(v, "listing-equation.md", _st_entry(
            "Listing equation", "**Listing equation** shows `it is the square "
            "root of variance` as literal text.\n\n```text\n"
            "It is the square root of variance.\n```", type_="Software"))
        _st_write(v, "two-cue-line.md", _st_entry(
            "Two cue line", "**Two cue line** is a rule. Its error rate is the "
            "fraction of misclassified instances, found by normalizing each "
            "cell by its row total."))
        res = scan(v)
        check("an explicit square-root-of-variance definition with no display "
              "math becomes an equation-coverage candidate",
              "item12/equation-coverage-candidate" in
              _st_keys(res, "equationless"), True)
        check("a canonical display equation clears the narrow coverage candidate",
              "item12/equation-coverage-candidate" in
              _st_keys(res, "equation-present"), False)
        check("an expanded squared-deviation display clears the coverage candidate",
              "item12/equation-coverage-candidate" in
              _st_keys(res, "equation-expanded"), False)
        check("unrelated root and variance terms in one display do not clear the "
              "coverage candidate",
              "item12/equation-coverage-candidate" in
              _st_keys(res, "equation-unrelated"), True)
        check("a one-line display is a form finding, not a missing-equation finding",
              ("item12/equation-format" in
               _st_keys(res, "equation-one-line"),
               "item12/equation-coverage-candidate" in
               _st_keys(res, "equation-one-line")), (True, False))
        check("two relations in one display are a split candidate, not a "
              "form finding",
              ("item12/equation-split-candidate" in
               _st_keys(res, "equation-two-relations"),
               "item12/equation-split-candidate" in
               _st_keys(res, "equation-present"),
               "item12/equation-format" in
               _st_keys(res, "equation-two-relations")), (True, False, False))
        check("an opening $$ on the equation's line is a form finding, not a "
              "missing-equation finding",
              ("item12/equation-format" in
               _st_keys(res, "equation-shared-open"),
               "item12/equation-coverage-candidate" in
               _st_keys(res, "equation-shared-open")), (True, False))
        check("a bare &= display is a form finding that names aligned",
              ("item12/equation-format" in
               _st_keys(res, "equation-bare-alignment"),
               "aligned" in _st_msg(res, "equation-bare-alignment",
                                    "item12/equation-format")), (True, True))
        check("two equations on separate source lines are a split candidate",
              ("item12/equation-split-candidate" in
               _st_keys(res, "equation-two-physical"),
               "item12/equation-format" in
               _st_keys(res, "equation-two-physical")), (True, False))
        check("negated wording does not become an equation-coverage candidate",
              "item12/equation-coverage-candidate" in
              _st_keys(res, "negated-equation"), False)
        check("table cells stay outside the prose equation candidate floor",
              "item12/equation-coverage-candidate" in
              _st_keys(res, "table-equation"), False)
        check("inline and fenced code stay outside equation coverage",
              "item12/equation-coverage-candidate" in
              _st_keys(res, "listing-equation"), False)
        check("two equation cues on one prose line list that line once",
              "prose line(s) 1)" in _st_msg(
                  res, "two-cue-line", "item12/equation-coverage-candidate"),
              True)
        _two_cue_msg = _st_msg(
            res, "two-cue-line", "item12/equation-coverage-candidate")
        check("a coverage candidate names each matched phrase, and only a "
              "square-root cue carries the denominator caveat",
              ('named-fraction-or-ratio "rate is the fraction" (line 1)'
               in _two_cue_msg, "denominator" in _two_cue_msg,
               "denominator" in _st_msg(
                   res, "equationless", "item12/equation-coverage-candidate")),
              (True, False, True))

        v = os.path.join(tmp, "v24-image-captions")
        _st_write(v, "captioned-images.md", _st_entry(
            "Captioned images", "**Captioned images** is a worked example.\n\n"
            "![[figure.png]]\n*A local figure with $x^*$ in its caption.*\n\n"
            "![Alt](figure-2.png)\n*A Markdown image with a plain caption.*"))
        _st_write(v, "missing-image-caption.md", _st_entry(
            "Missing image caption", "**Missing image caption** is a worked example.\n\n"
            "![[figure.png]]"))
        _st_write(v, "gapped-image-caption.md", _st_entry(
            "Gapped image caption", "**Gapped image caption** is a worked example.\n\n"
            "![Alt](figure.png)\n\n*A caption after a gap.*"))
        _st_write(v, "composite-and-panel.md", _st_entry(
            "Composite and panel", "**Composite and panel** is a worked example.\n\n"
            "![[Study_fig_3.png]]\n*The composite figure.*\n\n"
            "![[Study_fig_3a.png]]\n*One panel of the same figure.*"))
        _st_write(v, "panels-only.md", _st_entry(
            "Panels only", "**Panels only** is a worked example.\n\n"
            "![[Study_fig_S1a.png]]\n*The first selected panel.*\n\n"
            "![[Study_fig_S1b.png]]\n*The second selected panel.*"))
        _st_write(v, "complex-image-destinations.md", _st_entry(
            "Complex image destinations",
            "**Complex image destinations** is a worked example.\n\n"
            "![Balanced](https://example.test/plot_(x).png)\n"
            "*A balanced-parenthesis destination.*\n\n"
            "![Angle](<https://example.test/plot_(y).png>)\n"
            "*An angle-bracket destination.*\n\n"
            "![Plot [panel A]](https://example.test/panel.png)\n"
            "*A nested-bracket alt label.*"))
        _st_write(v, "escaped-image-syntax.md", _st_entry(
            "Escaped image syntax", r"**Escaped image syntax** shows "
            r"\![Alt](https://example.test/literal.png) as literal text."))
        for name, markup in (("italic", "*nested detail*"),
                             ("underscore-italic", "_nested detail_"),
                             ("wikilink", "[[detail]]"),
                             ("markdown-link", "[source](https://example.test)"),
                             ("html", "<span>detail</span>"),
                             ("strikethrough", "~~nested detail~~"),
                             ("bold", "**nested detail**"),
                             ("backtick", "`nested detail`")):
            _st_write(v, name + "-image-caption.md", _st_entry(
                name.title() + " image caption",
                "**%s image caption** is a worked example.\n\n"
                "![[figure.png]]\n*A caption with %s.*"
                % (name.title(), markup)))
        _st_write(v, "empty-image-caption.md", _st_entry(
            "Empty image caption", "**Empty image caption** is a worked example.\n\n"
            "![[figure.png]]\n* *"))
        _st_write(v, "listing-images.md", _st_entry(
            "Listing images", "**Listing images** shows embed syntax.\n\n"
            "```markdown\n![[fenced.png]]\n```\n\n"
            "    ![Indented](indented.png)", type_="Software"))
        res = scan(v)
        check("both image embed forms accept immediate plain captions and LaTeX",
              "item12" in _st_keys(res, "captioned-images"), False)
        check("balanced-parenthesis and angle-bracket destinations retain captions",
              "item12" in _st_keys(res, "complex-image-destinations"), False)
        check("a composite beside its panel is reported, while panels without the composite are not",
              ("item12/panel-composite" in _st_keys(res, "composite-and-panel"),
               "item12/panel-composite" in _st_keys(res, "panels-only")),
              (True, False))
        check("remote-image reports retain the complete complex destinations",
              (_st_keys(res, "complex-image-destinations").count("item12/remote-image"),
               "plot_(x).png" in _st_msg(
                   res, "complex-image-destinations", "item12/remote-image"),
               "plot_(y).png" in _st_msg(
                   res, "complex-image-destinations", "item12/remote-image")),
              (3, True, True))
        check("escaped Markdown image syntax is not an embed or remote image",
              [key for key in _st_keys(res, "escaped-image-syntax")
               if key.startswith("item12")], [])
        check("a missing image caption and an intervening blank are detected",
              ["item12" in _st_keys(res, name) for name in
               ("missing-image-caption", "gapped-image-caption")], [True, True])
        for name, fault in (("italic", "italic"),
                            ("underscore-italic", "italic"),
                            ("wikilink", "wikilink"),
                            ("markdown-link", "Markdown link"),
                            ("html", "HTML"),
                            ("strikethrough", "strikethrough"),
                            ("bold", "bold"),
                            ("backtick", "backtick")):
            check("an image caption rejects %s markup" % name,
                  fault in _st_msg(res, name + "-image-caption", "item12"), True)
        check("an empty italic caption is rejected",
              "empty" in _st_msg(res, "empty-image-caption", "item12"), True)
        check("fenced and indented image syntax samples need no caption",
              "item12" in _st_keys(res, "listing-images"), False)

        v = os.path.join(tmp, "v25-display-owner-conflicts")
        _st_write(v, "yeast.md", _st_entry(
            "Yeast", "**Yeast** is a worked example.",
            aliases=('"budding-yeast"',)))
        _st_write(v, "saccharomyces-cerevisiae.md", _st_entry(
            "Saccharomyces cerevisiae",
            "***Saccharomyces cerevisiae*** is a model organism.",
            type_="Organism", aliases=('"s-cerevisiae"',)))
        _st_write(v, "conflicting-display-reader.md", _st_entry(
            "Conflicting display reader",
            "**Conflicting display reader** compares "
            "[[saccharomyces-cerevisiae|Yeast]] with "
            "[[saccharomyces-cerevisiae|Budding yeast]]."))
        _st_write(v, "same-owner-display-reader.md", _st_entry(
            "Same owner display reader",
            "**Same owner display reader** names [[yeast|Budding yeast]]."))
        _st_write(v, "marked-up-display-reader.md", _st_entry(
            "Marked up display reader",
            "**Marked up display reader** names [[yeast|**Yeast**]]."))
        _st_write(v, "culture-a.md", _st_entry(
            "Culture A", "**Culture A** is a worked example.",
            aliases=('"culture"',)))
        _st_write(v, "culture-b.md", _st_entry(
            "Culture B", "**Culture B** is a worked example.",
            aliases=('"culture"',)))
        _st_write(v, "ambiguous-display-reader.md", _st_entry(
            "Ambiguous display reader",
            "**Ambiguous display reader** names "
            "[[saccharomyces-cerevisiae|Culture]]."))
        res = scan(v)
        check("a display that exactly names a different canonical entry is item18",
              ('different canonical entry' in _st_msg(
                   res, "conflicting-display-reader", "item18"),
               '"Yeast" at "yeast.md"' in _st_msg(
                   res, "conflicting-display-reader", "item18")), (True, True))
        check("a display that exactly names another entry's unique alias is item18",
              ('different unique alias' in _st_msg(
                   res, "conflicting-display-reader", "item18"),
               "do not auto-retarget" in _st_msg(
                   res, "conflicting-display-reader", "item18")), (True, True))
        check("an exact alias display owned by the chosen target remains valid",
              "item18" in _st_keys(res, "same-owner-display-reader"), False)
        check("markup inside a display label is owned only by item18",
              ([key for key in _st_keys(res, "marked-up-display-reader")
                if key in ("item16", "item18")],
               "labels render as plain text" in _st_msg(
                   res, "marked-up-display-reader", "item18")),
              (["item18"], True))
        check("an ambiguously owned display never chooses the first alias owner",
              "different unique alias" in _st_msg(
                  res, "ambiguous-display-reader", "item18"), False)

        # ------------------------------------------------------------------
        # 26. builder/linter parity guards added by the scope review:
        #     introduced aliases, self-links, parent shape/state, and the
        #     complete source-meta blacklist with its named-work/code carve-outs.
        # ------------------------------------------------------------------
        v = os.path.join(tmp, "v26-scope-parity")
        _st_write(v, "self.md", _st_entry(
            "Self", "**Self** names [[Wiki/self.md#Part|Self]] and its "
            "[[self-handle|Self]] alias.", aliases=('"self-handle"',),
            related="[[self|Self]]"))
        _st_write(v, "introduced-alias.md", _st_entry(
            "Introduced alias", "**Introduced alias** — which many people "
            "call *alternate name* — is a worked example."))
        _st_write(v, "feature-machine-learning.md", _st_entry(
            "Feature (machine learning)", "**Feature** — which many people "
            "call *covariate* — is a measurable input to a model."))
        _st_write(v, "label-machine-learning.md", _st_entry(
            "Label (machine learning)", "**Label** — which many people call "
            "*target* — is the answer a model learns to predict."))
        _st_write(v, "component-name.md", _st_entry(
            "Component name", "**Component name** has a part. The part, also "
            "called the *auxiliary unit*, is not the entry subject."))
        _st_write(v, "empty-alias.md", _st_entry(
            "Empty alias", "**Empty alias** is a worked example.",
            aliases=('""',)))
        _st_write(v, "own-alias.md", _st_entry(
            "Own alias", "**Own alias** is a worked example.",
            aliases=('"own-alias"',)))
        _st_write(v, "root.md", _st_entry(
            "Root", "**Root** is a worked example.",
            aliases=('"root-handle"',)))
        _st_write(v, "scalar-parent.md", _st_entry(
            "Scalar parent", "**Scalar parent** is a worked example.").replace(
            "parents: []\n", 'parents: "[[root]]"\n'))
        _st_write(v, "flow-parent.md", _st_entry(
            "Flow parent", "**Flow parent** is a worked example.").replace(
            "parents: []\n", 'parents: ["[[root]]"]\n'))
        _st_write(v, "spaced-empty-parent.md", _st_entry(
            "Spaced empty parent", "**Spaced empty parent** is a worked example.").replace(
            "parents: []\n", 'parents: [ ]\n'))
        _st_write(v, "plain-parent.md", _st_entry(
            "Plain parent", "**Plain parent** is a worked example.",
            parents=('"root"',)))
        _st_write(v, "alias-parent.md", _st_entry(
            "Alias parent", "**Alias parent** is a worked example.",
            parents=('"[[root-handle]]"',)))
        _st_write(v, "case-parent.md", _st_entry(
            "Case parent", "**Case parent** is a worked example.",
            parents=('"[[Root]]"',)))
        _st_write(v, "duplicate-parent.md", _st_entry(
            "Duplicate parent", "**Duplicate parent** is a worked example.",
            parents=('"[[root]]"', '"[[root-handle]]"')))
        _st_write(v, "untagged-parent.md", _st_entry(
            "Untagged parent", "**Untagged parent** is a worked example.",
            tags=(), parents=('"[[root]]"',)))
        for _slug, _sentence in (
                ("meta-source", "This source gives the result."),
                ("meta-source-text", "The source text states the result."),
                ("meta-later", "As discussed later, the result holds."),
                ("meta-section", "In the previous section, the case was introduced."),
                ("meta-bare-section", "The previous section introduced the case."),
                ("meta-saw", "As we saw, the case is representative."),
                ("meta-figure", "The figure above gives the result.")):
            _title = _slug.replace("-", " ").title()
            _st_write(v, _slug + ".md", _st_entry(
                _title, "**%s** is a worked example. %s" % (_title, _sentence)))
        _st_write(v, "sgdr.md", _st_entry(
            "SGDR", "***SGDR*** is a named work used by the self-test.",
            type_="Work"))
        _st_write(v, "meta-near-misses.md", _st_entry(
            "Meta near misses", "**Meta near misses** explains source code, "
            "credits the authors of SGDR, explains this source code, returns "
            "later, and stays above zero. It maps the source domain to a "
            "target domain and routes flow from the source node to the sink."))
        _st_write(v, "meta-unnamed-authors.md", _st_entry(
            "Meta unnamed authors", "**Meta unnamed authors** says the authors "
            "of a study reported the result."))
        _st_write(v, "code-listings.md", _st_entry(
            "Code listings", "**Code listings** shows literal samples: "
            "`This source uses [[root|$Root$]] and is also called *inline fake*.`\n\n"
            "```text\nThe figure below. Code listings is also called "
            "*fenced fake*. [[root|**Root**]]\n```\n\n"
            "    Code listings is also called *indented fake*.",
            type_="Software"))
        _st_write(v, "missing-related.md", _st_entry(
            "Missing related", "**Missing related** is a worked example.",
            related=False))
        _st_write(v, "post-related-content.md", _st_entry(
            "Post related content", "**Post related content** is a worked example.")
            .replace("**Related:**\n\n---",
                     "**Related:**\n\nMore [[post-related-content]].\n\n---"))
        _st_write(v, "duplicate-source.md", _st_entry(
            "Duplicate source", "**Duplicate source** is a worked example.",
            sources=('"[[Doe_X_2025.pdf#page=2]]"',
                     '"[[Doe_X_2025.pdf#page=2]]"')))
        _st_write(v, "plural-alias.md", _st_entry(
            "Plural alias", "**Plural alias** is a worked example.",
            aliases=('"plural-aliases"',)))
        _st_write(v, "merge-scars.md", _st_entry(
            "Merge scars", "**Merge scars** is a worked example.\n\n---\n42"))
        _st_write(v, "card-sentence-form.md", _st_entry(
            "Card sentence form", "**Card sentence form** is a worked example.")
            .replace("The idea this entry is about, stated once.",
                     "the idea this entry is about, stated once"))
        _st_write(v, "separator-spacing.md", _st_entry(
            "Separator spacing", "**Separator spacing** is a worked example.")
            .replace("---\n\n## Flashcards", "---\n## Flashcards"))
        _st_write(v, "heading-spacing.md", _st_entry(
            "Heading spacing", "**Heading spacing** is a worked example.")
            .replace("## Flashcards\n\nThe idea", "## Flashcards\nThe idea"))
        res = scan(v)
        check("canonical, path/.md/anchor, and own-alias self-links share item10/self",
              _st_keys(res, "self").count("item10/self"), 3)
        check("self-links do not cascade into alias/case/duplicate/footer-label findings",
              [key for key in _st_keys(res, "self")
               if key in {"item10/alias", "item10/case", "item10/dup", "item11"}], [])
        check("the linter mirrors builder's introduced-alias candidate detector",
              ("item17/alias-candidate" in _st_keys(res, "introduced-alias"),
               '"alternate-name"' in _st_msg(
                   res, "introduced-alias", "item17/alias-candidate")),
              (True, True))
        check("a single-word synonym of a disambiguated subject defaults to staying out",
              ("stays out" in _st_msg(res, "feature-machine-learning",
                                      "item17/alias-candidate"),
               "stays out" in _st_msg(res, "introduced-alias",
                                      "item17/alias-candidate")),
              (True, False))
        check("a component's synonym is not promoted to the entry's alias",
              "item17/alias-candidate" in _st_keys(res, "component-name"), False)
        check("a designated cross-domain synonym is never an alias candidate",
              "item17/alias-candidate" in _st_keys(res, "label-machine-learning"),
              False)
        check("empty and own-slug aliases are item18 findings",
              ["item18" in _st_keys(res, slug_) for slug_ in
               ("empty-alias", "own-alias")], [True, True])
        check("scalar, flow/empty spelling, plain, alias/case, and resolved-duplicate parents are form findings",
              ["item2/parents-form" in _st_keys(res, slug_) for slug_ in
               ("scalar-parent", "flow-parent", "spaced-empty-parent",
                "plain-parent", "alias-parent", "case-parent",
                "duplicate-parent")],
              [True] * 7)
        check("every previously omitted exact source-meta phrase is item14",
              ["item14" in _st_keys(res, slug_) for slug_ in
               ("meta-source", "meta-source-text", "meta-later", "meta-section",
                "meta-bare-section", "meta-saw", "meta-figure")], [True] * 7)
        check("named-work, technical source compounds, temporal-later, and "
              "geometric-above uses stay clean",
              "item14" in _st_keys(res, "meta-near-misses"), False)
        check("authors of an unnamed study remains source-meta phrasing",
              "item14" in _st_keys(res, "meta-unnamed-authors"), True)
        check("source-meta and marked-up wikilinks inside code stay outside prose checks",
              [key for key in _st_keys(res, "code-listings")
               if key in {"item14", "item17/alias-candidate", "item18"}], [])
        check("missing and nonterminal Related footers are structural item11 findings",
              ["item11" in _st_keys(res, slug_) for slug_ in
               ("missing-related", "post-related-content")], [True, True])
        check("exact source duplication, plural aliases, merge scars, and card sentence form are covered",
              ("item4" in _st_keys(res, "duplicate-source"),
               "item18" in _st_keys(res, "plural-alias"),
               _st_keys(res, "merge-scars").count("item13"),
               "item19" in _st_keys(res, "card-sentence-form")),
              (True, True, 2, True))
        check("Flashcards separator and heading spacing are both enforced",
              ["item19" in _st_keys(res, slug_) for slug_ in
               ("separator-spacing", "heading-spacing")],
              [True, True])

        # A linked target's earlier plain mention (item10/late-link), with
        # the hyphen-compound, apposition and alias-only-noun exclusions.
        v = os.path.join(tmp, "late-links")
        _st_write(v, "training-set.md", _st_entry(
            "Training set", "A **training set** is a worked example."))
        _st_write(v, "schizosaccharomyces-pombe.md", _st_entry(
            "Schizosaccharomyces pombe",
            "***Schizosaccharomyces pombe*** is a worked example.",
            aliases=('"fission-yeast"',)))
        _st_write(v, "model-organism.md", _st_entry(
            "Model organism", "A **model organism** is a worked example."))
        _st_write(v, "feature-x.md", _st_entry(
            "Feature (machine learning)", "A **feature** is a worked example.",
            aliases=('"regressor"',)))
        _st_write(v, "label-x.md", _st_entry(
            "Label (machine learning)", "A **label** is the answer a model "
            "learns. The word *target* is a near-synonym."))
        _st_write(v, "k-nearest-neighbors.md", _st_entry(
            "$k$-nearest neighbors",
            "**$\\boldsymbol{k}$-nearest neighbors** is a worked example."))
        _st_write(v, "cdc2.md", _st_entry(
            "Cdc2", "**Cdc2** is a worked example.", type_="Gene/Protein",
            tags=('"#biology"',)))
        for slug_, prose in (
                ("late", "**Late** fits a model on a training set first. It "
                         "then reuses the [[training-set|training set]]."),
                ("early", "**Early** uses the [[training-set|training set]]. "
                          "A training set is then reused."),
                ("hyphen", "**Hyphen** runs a pre-training set pass before "
                           "the [[training-set|training set]] is used."),
                ("apposition", "**Apposition** was studied in fission yeast "
                               "[[schizosaccharomyces-pombe|Schizosaccharomyces "
                               "pombe]]."),
                ("display", "**Display** is a model in genetics. Later work "
                            "made it a useful [[model-organism|model]]."),
                ("quiet-alias", "**Quiet alias** trains each regressor on a "
                                "sample of [[feature-x|features]]."),
                ("synonym", "**Synonym** fits the noise-free target first. "
                            "It then scores each observed "
                            "[[label-x|target]]."),
                ("math", "**Math** fits $f(\\text{training set})$ and\n\n$$\n"
                         "\\text{training set} = D\n$$\n\nreuses the "
                         "[[training-set|training set]]."),
                ("math-only", "**Math only** minimizes $L(\\text{training set})$."),
                ("latex-title", "**Latex title** votes with $k$-nearest neighbors."),
                ("longer-italic", "**Longer italic** fits a *blending training "
                                  "set* built from the [[training-set|training "
                                  "set]]."),
                ("gene-symbol", "**Gene symbol** names the *cdc2* gene, which "
                                "encodes the [[cdc2|Cdc2]] kinase."),
                ("italic-same", "**Italic same** fits a *training set* first. "
                                "It then reuses the [[training-set|training "
                                "set]]."),
                ("open-compound", "**Open compound** reports the training "
                                  "set size first. It then reuses the "
                                  "[[training-set|training set]]."),
                ("italic-bullet", "**Italic bullet** has two parts.\n\n"
                                  "- *Training set* comes from the fitted "
                                  "split.\n- *Base split* is the rest.\n\n"
                                  "It reuses the [[training-set|training "
                                  "set]]."),
                ("training-set-split", "**Training set split** has two "
                                       "parts.\n\n- *Training set* is the "
                                       "fitted part, and a large training "
                                       "set helps.\n- *Rest* is held out."
                                       "\n\nIt reuses the [[training-set|"
                                       "training set]]."),
                ("math-sub", "**Math sub** predicts $\\hat{y}_{i}$ for each "
                             "training set example $\\mathbf{x}_{i}$. It "
                             "reuses the [[training-set|training set]]."),
                ("math-star", "**Math star** compares $\\theta^*$ from the "
                              "training set with $w^*$. It reuses the "
                              "[[training-set|training set]]."),
                ("math-italic", "**Math italic** fits a *$k$-fold training "
                                "set* built from the [[training-set|training "
                                "set]]."),
                ("longer-bold", "**Longer bold** has two splits.\n\n"
                                "- **Blending training set** — the held-out "
                                "split.\n- **Base split** — the rest.\n\n"
                                "Both come from the [[training-set|training "
                                "set]]."),
                ("bold-same", "**Bold same** has two splits.\n\n"
                              "- **Training set** — the fitted split.\n"
                              "- **Base split** — the rest.\n\nIt reuses "
                              "the [[training-set|training set]]."),
                ("en-dash", "**En dash** runs a pre\u2013training set pass "
                            "before the [[training-set|training set]] is used."),
                ("hyphen-only", "**Hyphen only** runs a pre-training set pass."),
                ("en-dash-only", "**En dash only** runs a pre\u2013training "
                                 "set pass."),
                ("italic-only", "**Italic only** fits a *blending training "
                                "set* once."),
                ("hyphen-then-plain", "**Hyphen then plain** runs a "
                                      "pre-training set pass.\n\nIt then "
                                      "samples a training set."),
                ("bold-then-plain", "**Bold then plain** has two splits.\n\n"
                                    "- **Blending training set** — the "
                                    "held-out split.\n\nA training set "
                                    "remains.")):
            _st_write(v, slug_ + ".md", _st_entry(slug_.replace("-", " ").capitalize(), prose))
        res = scan(v)
        check("a plain mention before the first link is a late link; a later "
              "mention, a hyphen compound, an apposition, an alias-only bare "
              "noun, and a cross-domain synonym label's word are not",
              ["item10/late-link" in _st_keys(res, slug_) for slug_ in
               ("late", "early", "hyphen", "apposition", "display",
                "quiet-alias", "synonym")],
              [True, False, False, False, True, False, False])
        check("a longer italic term and an italic gene symbol before a "
              "Gene/Protein link are not earlier mentions; an italic mention "
              "of the target itself still is",
              ["item10/late-link" in _st_keys(res, slug_) for slug_ in
               ("longer-italic", "gene-symbol", "italic-same")],
              [False, False, True])
        check("a modifier inside an open compound (`training set size`) and "
              "an italic bullet term naming the target are earlier mentions; "
              "words the entry defines in italics from its own title name "
              "its own facet, italic or plain, and are not",
              ["item10/late-link" in _st_keys(res, slug_) for slug_ in
               ("open-compound", "italic-bullet", "training-set-split")],
              [True, True, False])
        check("a `_` or `*` inside LaTeX math opens no italic span, so the "
              "mention between two math spans is still a late link; an "
              "italic term that starts with math still is one term",
              ["item10/late-link" in _st_keys(res, slug_) for slug_ in
               ("math-sub", "math-star", "math-italic")],
              [True, True, False])
        check("a longer bold bullet-anchor term is not an earlier mention; a "
              "bold anchor naming the target itself still is",
              ["item10/late-link" in _st_keys(res, slug_) for slug_ in
               ("longer-bold", "bold-same")],
              [False, True])
        check("an en-dash compound is not an earlier mention",
              "item10/late-link" in _st_keys(res, "en-dash"), False)
        check("a backfill proposal skips hyphen, en-dash and longer italic or "
              "bold occurrences and takes the first eligible one, with its "
              "body line",
              sorted((row["slug"], row["line"])
                     for row in res["backfill_candidates"]
                     if row["target"] == "training-set" and row["slug"] in (
                         "hyphen-only", "en-dash-only", "italic-only",
                         "hyphen-then-plain", "bold-then-plain")),
              [("bold-then-plain", 5), ("hyphen-then-plain", 3)])
        check("LaTeX math is neither an earlier mention nor a backfill surface, "
              "but a LaTeX title's own surface is",
              ("item10/late-link" in _st_keys(res, "math"),
               [(row["slug"], row["target"]) for row in res["backfill_candidates"]
                if row["slug"].startswith(("math", "latex"))]),
              (False, [("latex-title", "k-nearest-neighbors")]))
        # The own-title facet exclusion on the backfill side: an entry that
        # defines `*Training set*` from its own title is not proposed a link
        # for its later plain "training set".
        v = os.path.join(tmp, "own-title-backfill")
        _st_write(v, "training-set.md", _st_entry(
            "Training set", "A **training set** is the data a model learns "
            "from."))
        _st_write(v, "training-set-split.md", _st_entry(
            "Training set split", "A **training set split** divides data in "
            "two.\n\n- *Training set* is the fitted part.\n\nA large training "
            "set helps."))
        _st_write(v, "control-split.md", _st_entry(
            "Control split", "A **control split** divides data in two.\n\nA "
            "large training set helps."))
        check("words an entry defines in italics from its own title are not "
              "a backfill mention of another target",
              sorted((row["slug"], row["target"])
                     for row in scan(v)["backfill_candidates"]),
              [("control-split", "training-set")])
        # Discipline-root backfill: tagged for batch review; a field name
        # inside a compound ("cell biology") is not the root at all.
        v = os.path.join(tmp, "root-backfill")
        _st_write(v, "biology.md", _st_entry(
            "Biology", "**Biology** is the study of life.",
            tags=('"#biology"',)))
        _st_write(v, "setting.md", _st_entry(
            "Setting", "**Setting** is what biology calls a habitat.",
            tags=('"#biology"',)))
        _st_write(v, "in-setting.md", _st_entry(
            "In setting", "**In setting** is a topic in biology.",
            tags=('"#biology"',)))
        _st_write(v, "genus.md", _st_entry(
            "Genus", "**Genus** is a biology lab tool.",
            tags=('"#biology"',)))
        _st_write(v, "setting-then-field.md", _st_entry(
            "Setting then field", "**Setting then field** is a topic in "
            "biology.\n\nIt is what biology calls a niche.",
            tags=('"#biology"',)))
        _st_write(v, "compound.md", _st_entry(
            "Compound", "**Compound** is studied in cell biology.",
            tags=('"#biology"',)))
        _st_write(v, "compound-late.md", _st_entry(
            "Compound late", "**Compound late** is studied in cell biology, "
            "which images single cells. [[biology|Biology]] studies life "
            "more broadly.",
            tags=('"#biology"',)))
        _st_write(v, "root-late.md", _st_entry(
            "Root late", "**Root late** is a topic in biology, and it changed "
            "how [[biology]] is taught.", tags=('"#biology"',)))
        res = scan(v)
        check("a root candidate carries discipline_root; a compound, a "
              "setting ('in biology') and a genus ('a biology lab tool') are "
              "dropped, and a later field mention is still proposed",
              sorted((row["slug"], row["target"].rsplit("/", 1)[-1],
                      row["discipline_root"], row["line"])
                     for row in res["backfill_candidates"]),
              [("setting", "biology", True, 1),
               ("setting-then-field", "biology", True, 3)])
        check("a root named as a setting or genus, never after 'of' or 'to'",
              [_root_named_as_setting_or_genus(text, text.index("biology"),
                                               text.index("biology") + 7)
               for text in ("In biology, cells", "for the biology",
                            "a biology lab", "a branch of biology",
                            "close to biology", "the biology.")],
              [True, True, True, False, False, False])
        check("a root compound is not an earlier mention of a later root link",
              ["item10/late-link" in _st_keys(res, slug_)
               for slug_ in ("compound-late", "root-late")],
              [False, True])
        # A label that keeps only the title's modifiers (item18/partial-label),
        # unless the target defines that word as a term.
        v = os.path.join(tmp, "partial-labels")
        _st_write(v, "greedy-algorithm.md", _st_entry(
            "Greedy algorithm", "A **greedy algorithm** is a worked example."))
        _st_write(v, "ensemble-learning.md", _st_entry(
            "Ensemble learning", "**Ensemble learning** combines a group of "
            "predictors, called an *ensemble*."))
        _st_write(v, "partial.md", _st_entry(
            "Partial", "**Partial** makes [[greedy-algorithm|greedy]] choices."))
        _st_write(v, "defined.md", _st_entry(
            "Defined", "**Defined** builds an [[ensemble-learning|ensemble]]."))
        _st_write(v, "full.md", _st_entry(
            "Full", "**Full** is a [[greedy-algorithm|greedy algorithm]]."))
        res = scan(v)
        check("a modifier-only label is a partial label; a defined term and "
              "the full title are not",
              ["item18/partial-label" in _st_keys(res, slug_)
               for slug_ in ("partial", "defined", "full")],
              [True, False, False])
        # Well-definedness boilerplate on a card's line 1.
        v = os.path.join(tmp, "card-boilerplate")
        _st_write(v, "card-guard.md", _st_entry(
            "Card guard",
            "**Card guard** is a worked example.\n\n**Related:**\n\n---\n\n"
            "## Flashcards\n\nThe mean $m^{-1}\\sum_{i=1}^{m} x_i$ over "
            "$m\\ge1$ values.\n??\nCard guard", card=False))
        res = scan(v)
        check("card line 1 lists a count guard and full-range bounds",
              [p["message"].count('"') >= 4 for p in res["problems"]
               if p["slug"] == "card-guard"
               and p["item"] == "item12/boilerplate-candidate"],
              [True])

        # A numbered procedure: a display or paragraph at its step's text
        # column (3 spaces under 1., 4 under 10.) reads like a top-level one.
        v = os.path.join(tmp, "list-steps")
        procedure = (
            "**Steps** run in order.\n\n"
            "1. Set every weight to one over the count, so all examples "
            "count.\n"
            "2. Fit a weak classifier. Common choices are:\n"
            "   - a decision stump;\n   - a shallow tree.\n\n"
            "   A deeper tree fits the weights too closely.\n"
            "3. Compute the weighted error:\n\n"
            "   $$\n   \\epsilon = \\sum_{i=1}^{n} w_i\n   $$\n\n"
            "   Here $\\epsilon$ is the weight on mistakes.\n"
            + "".join("%d. Record round %d.\n" % (n, n) for n in range(4, 10))
            + "10. Normalize the weights:\n\n"
            "    $$\n    w_i \\leftarrow \\frac{w_i}{Z}\n    $$\n\n"
            "    Here $Z$ is the total weight.\n"
            "11. Repeat from step 2 until every round has run.")
        _st_write(v, "steps.md", _st_entry("Steps", procedure))
        _st_write(v, "loose-steps.md", _st_entry(
            "Loose steps", procedure.replace("**Steps**", "**Loose steps**")
            .replace("   $$\n   \\epsilon = \\sum_{i=1}^{n} w_i\n   $$\n\n"
                     "   Here",
                     "$$\n\\epsilon = \\sum_{i=1}^{n} w_i\n$$\n\nHere")
            .replace("    $$\n    w_i \\leftarrow \\frac{w_i}{Z}\n    $$",
                     "   $$\n   w_i \\leftarrow \\frac{w_i}{Z}\n   $$")))
        res = scan(v)
        check("a numbered procedure with indented displays, a nested bullet "
              "and a two-digit step scans clean",
              _st_keys(res, "steps"), [])
        check("a display and paragraph left outside a step, and a display "
              "short of 10.'s text column, are item9/list-indent",
              [(p["item"], p["message"].split(":", 1)[0])
               for p in res["problems"] if p["slug"] == "loose-steps"],
              [("item9/list-indent",
                "prose line 11 (list item on prose line 9)"),
               ("item9/list-indent",
                "prose line 15 (list item on prose line 9)"),
               ("item9/list-indent",
                "prose line 24 (list item on prose line 22)")])
        # The per-entry checks shared with wiki-build's lint_entry.py: its
        # self-test runs the same rows, so each moved mutation is flagged by
        # both tools.
        v = os.path.join(tmp, "shared-checks")
        _st_write(v, "precision.md", _st_entry(
            "Precision", "**Precision** is a worked example."))
        _st_write(v, "decision-threshold.md", _st_entry(
            "Decision threshold", "A **decision threshold** is a worked example."))
        for number, row in enumerate(SHARED_MUTATIONS, 1):
            slug_ = "mutation-%d" % number
            _st_write(v, slug_ + ".md", _st_entry(
                "Mutation %d" % number,
                "**Mutation %d** describes a rate.\n\n%s"
                % (number, row[1].replace("{self}", slug_))))
        res = scan(v)
        for number, (name, _paragraph, scan_key, _lint_id, _folder) in \
                enumerate(SHARED_MUTATIONS, 1):
            check("lint_entry parity, %s: %s" % (name, scan_key),
                  scan_key in _st_keys(res, "mutation-%d" % number), True)
        check("the shared-check reference entry stays clean",
              _st_keys(res, "precision"), [])
        # ...and each quiet row stays unflagged by both tools.
        v = os.path.join(tmp, "shared-quiet")
        _st_write(v, "mus-musculus.md", _st_entry(
            "Mus musculus",
            "***Mus musculus*** is the mouse, a small rodent.",
            type_="Organism",
            description="Mus musculus is the mouse, a small rodent."))
        _st_write(v, "l-2-norm.md", _st_entry(
            "$L^2$ norm", "The **$L^2$ norm** measures a vector's length."))
        _st_write(v, "decision-threshold.md", _st_entry(
            "Decision threshold", "A **decision threshold** is a worked example."))
        _st_write(v, "label-machine-learning.md", _st_entry(
            "Label (machine learning)", "A **label** is the answer a model "
            "learns to predict. The word *target* is a near-synonym."))
        for number, row in enumerate(SHARED_QUIET, 1):
            _st_write(v, "quiet-%d.md" % number, _st_entry(
                "Quiet %d" % number,
                "**Quiet %d** describes a rate.\n\n%s" % (number, row[1])))
        res = scan(v)
        for number, (name, _paragraph, scan_key, _lint_id) in \
                enumerate(SHARED_QUIET, 1):
            check("lint_entry parity, quiet %s: %s" % (name, scan_key),
                  scan_key in _st_keys(res, "quiet-%d" % number), False)
        # A preserved comment before the opener leaves the title's bold in
        # the opener (lint_entry's self-test runs the same cases).
        v = os.path.join(tmp, "leading-comment")
        _st_write(v, "comment-lead.md", _st_entry(
            "Comment lead",
            "%% user note %%\n\n**Comment lead** is a worked example."))
        _st_write(v, "html-lead.md", _st_entry(
            "Html lead",
            "<!-- reviewed 2026-01 -->\n**Html lead** is a worked example."))
        _st_write(v, "r-plus.md", _st_entry(
            "$R^{+}$", "%% user note %%\n\n**$R^{+}$** is a worked example.",
            card="R-plus"))
        _st_write(v, "unbolded-lead.md", _st_entry(
            "Unbolded lead", "%% note %%\n\nUnbolded lead is a worked example."))
        res = scan(v)
        check("a leading comment keeps the title's bold in the opener; a "
              "missing opener bold after it is still found",
              [_st_keys(res, slug_) for slug_ in
               ("comment-lead", "html-lead", "r-plus", "unbolded-lead")],
              [[], [], [], ["item16"]])
        # `the authors of` any existing entry is named attribution, such as a
        # method named by its paper; an unknown name stays source-meta.
        v = os.path.join(tmp, "authors-named-entry")
        _st_write(v, "sgdr.md", _st_entry(
            "SGDR", "**SGDR** is a learning-rate schedule with warm restarts."))
        _st_write(v, "cosine-annealing.md", _st_entry(
            "Cosine annealing", "**Cosine annealing** lowers the rate along a "
            "cosine. The authors of SGDR recommend restarting it periodically."))
        _st_write(v, "unknown-authors.md", _st_entry(
            "Unknown authors", "**Unknown authors** is a worked example. "
            "The authors of Adam recommend it."))
        _st_write(v, "machine-learning.md", _st_entry(
            "Machine learning", "**Machine learning** fits models to data."))
        _st_write(v, "direct-preference-optimization.md", _st_entry(
            "Direct preference optimization",
            "**Direct preference optimization** tunes a model on preferences.",
            aliases=('"dpo"',)))
        _st_write(v, "generic-authors.md", _st_entry(
            "Generic authors", "**Generic authors** is a worked example. "
            "The authors of machine learning textbooks recommend it."))
        _st_write(v, "acronym-authors.md", _st_entry(
            "Acronym authors", "**Acronym authors** is a worked example. "
            "The authors of DPO recommend it."))
        res = scan(v)
        check("the authors of an existing Concept entry are named attribution; "
              "an unknown name stays source-meta",
              ("item14" in _st_keys(res, "cosine-annealing"),
               "item14" in _st_keys(res, "unknown-authors")),
              (False, True))
        check("a lowercase generic phrase naming no entry exactly stays "
              "source-meta; a capitalized alias names its entry",
              ("item14" in _st_keys(res, "generic-authors"),
               "item14" in _st_keys(res, "acronym-authors")),
              (True, False))
        v = os.path.join(tmp, "alias-hint")
        _st_write(v, "recall-machine-learning.md", _st_entry(
            "Recall (machine learning)",
            "**Recall** (**TPR**), also called *completeness*, is the share "
            "of actual positives that a classifier finds. It is also called "
            "*sensitivity*.",
            aliases=('"true-positive-rate"',), card="Recall"))
        res = scan(v)
        check("the cross-domain alias hint skips an acronym candidate, and a "
              "designated cross-domain word is no candidate at all",
              sorted((p["message"].split('"')[1],
                      BARE_WORD_ALIAS_HINT in p["message"])
                     for p in res["problems"]
                     if p["slug"] == "recall-machine-learning"
                     and p["item"] == "item17/alias-candidate"),
              [("TPR", False), ("completeness", True)])

        # ------------------------------------------------------------------
        # Item 19 card set: one `??` definition card per entry; a further card
        # is an extra card to remove; brevity candidates.
        # ------------------------------------------------------------------
        def _with_cards(title, extra, **kwargs):
            return (_st_entry(title, "**%s** is a worked example." % title,
                              **kwargs).rstrip("\n") + "\n\n" + extra)
        _why = "Why does the example matter?\n?\nIt keeps each claim separate.\n"
        v = os.path.join(tmp, "v-card-set")
        _st_write(v, "extra-question.md", _with_cards("Extra question", _why))
        _st_write(v, "three-cards.md", _with_cards(
            "Three cards", _why + "\n"
            + "A second claim, stated once.\n??\nSecond term\n"))
        _st_write(v, "simplified-primary.md", _st_entry(
            "Simplified primary", "**Simplified primary** is a worked example.")
            .replace("\n??\nSimplified primary\n", "\n?\nSimplified primary\n"))
        _st_write(v, "bad-separator.md", _st_entry(
            "Bad separator", "**Bad separator** is a worked example.")
            .replace("\n??\nBad separator\n", "\n???\nBad separator\n"))
        _long_cue = ("A deliberately verbose definition that keeps adding "
                     "ordinary words well beyond the target length so that the "
                     "advisory brevity hint fires for this long card cue about "
                     "nothing in particular.")   # 30 words
        _st_write(v, "long-cue.md", _st_entry(
            "Long cue", "**Long cue** is a worked example.").replace(
                "The idea this entry is about, stated once.", _long_cue))
        _st_write(v, "glossary-cue.md", _st_entry(
            "Glossary cue", "**Glossary cue** is a worked example.").replace(
                "The idea this entry is about, stated once.",
                "The ratio $a/b$ of two counts, where $a$ counts hits."))
        _st_write(v, "hedge-cue.md", _st_entry(
            "Hedge cue", "**Hedge cue** is a worked example.").replace(
                "The idea this entry is about, stated once.",
                "The idea this entry is usually about, stated once."))
        _st_write(v, "hedge-description.md", _st_entry(
            "Hedge description", "**Hedge description** is a worked example.",
            description="Hedge description is a worked example, often used "
                        "by the self-test."))
        _st_write(v, "measured-description.md", _st_entry(
            "Measured description",
            "**Measured description** is a worked example.",
            description="Measured description counts how often a normally "
                        "distributed value is used."))
        _st_write(v, "simplified-pair.md", _with_cards(
            "Simplified pair", _why).replace(
                "\n??\nSimplified pair\n", "\n?\nSimplified pair\n"))
        _st_write(v, "question-first.md", _st_entry(
            "Question first", "**Question first** is a worked example.")
            .replace("## Flashcards\n\n", "## Flashcards\n\n" + _why + "\n"))
        _st_write(v, "extra-faults.md", _with_cards(
            "Extra faults",
            "The rate at 10 μm for a nonempty set of $m \\ge 1$ instances, "
            "usually stated at length across many more ordinary words than any card "
            "cue should ever need to carry, and one second idea.\n??\n"
            "Second idea (**SI**)\n"))
        _st_write(v, "card-line-marker.md", _st_entry(
            "Card line marker", "**Card line marker** is a worked example.")
            .replace("The idea this entry is about, stated once.",
                     "The idea $a :: b$ this entry is about, stated once."))
        _st_write(v, "extra-card-marker.md", _with_cards(
            "Extra card marker", "Another notion, stated $x ::: y$ briefly."
            "\n??\nSecond::idea\n"))
        _st_write(v, "code-card-marker.md", _st_entry(
            "Code card marker", "**Code card marker** is a worked example.")
            .replace("The idea this entry is about, stated once.",
                     "The idea `a::b` this entry is about, stated once."))
        _st_write(v, "two-q.md", _st_entry(
            "Two q", "**Two q** is a worked example.").replace(
                "The idea this entry is about, stated once.\n??\nTwo q\n",
                _why + "\nWhy is the example short?\n?\nIt states one claim.\n"))
        _st_write(v, "extra-stray.md", _with_cards(
            "Extra stray", "Another notion, stated briefly.\n??\nSecond idea\n"
            "A stray user line.\n"))
        res = scan(v)
        check("a separator on card line 1 or 3 splits the card: an item19 "
              "problem naming the line, asking for an extra card's removal",
              [sorted(p["message"].split(" holds ")[0] for p in res["problems"]
                      if p["slug"] == slug_ and p["item"] == "item19"
                      and " holds `:" in p["message"])
               for slug_ in ("card-line-marker", "extra-card-marker",
                             "code-card-marker")],
              [["flashcard line 1"],
               [EXTRA_CARD_PREFIX % 2 + "card 2 line 1",
                EXTRA_CARD_PREFIX % 2 + "card 2 line 3"], []])
        check("a card-line separator names the math remedy on line 1",
              "\\mathbin{:}\\mathbin{:}" in _st_msg(
                  res, "card-line-marker", "item19"), True)
        _extra_q = _st_msg(res, "extra-question", "item19")
        check("a question card is an extra card to remove whose own line 1 "
              "and line 2 are reported",
              ("holds 2 cards" in _extra_q,
               "remove every other card" in _extra_q,
               "card 2 line 1 does not end with a period" in _extra_q,
               'card 2 line 2 is "?"' in _extra_q, "card 1 " in _extra_q),
              (True, True, True, True, False))
        _extra_q_rows = [p["message"] for p in res["problems"]
                         if p["slug"] == "extra-question"
                         and "card 2" in p["message"]]
        check("per-card problems on an extra card carry the removal prefix, "
              "and none asks for a new line 2",
              ([m.startswith(EXTRA_CARD_PREFIX % 2) for m in _extra_q_rows],
               any("must be exactly" in m for m in _extra_q_rows)),
              ([True, True], False))
        _pair = [p["message"] for p in res["problems"]
                 if p["slug"] == "simplified-pair" and "line 2" in p["message"]]
        check("a primary simplified to ? beside an extra ? card: only the "
              "primary's line 2 must be ?? again",
              sorted((m.startswith("extra card 2 (remove this extra card; "),
                      "must be exactly ??" in m) for m in _pair),
              [(False, True), (True, False)])
        check("a question card placed first is the extra card; the "
              "definition card after it is the primary one",
              sorted(p["message"].split(":")[0] for p in res["problems"]
                     if p["slug"] == "question-first"
                     and p["item"] == "item19"
                     and "holds 2 cards" not in p["message"]),
              ["extra card 1 (remove this extra card; it needs no other "
               "repair)"] * 2)
        _extra_rows = [(p["item"], p["message"].startswith(
                            EXTRA_CARD_PREFIX % 2),
                        "remove only the markup" in p["message"]
                        or "keep the cue" in p["message"])
                       for p in res["problems"]
                       if p["slug"] == "extra-faults" and "card 2" in p["message"]]
        check("markup, leak, typography, boilerplate, brevity and hedge "
              "problems on an extra card ask for its removal, and none orders "
              "another repair",
              sorted(set(_extra_rows)),
              [("item12/boilerplate-candidate", True, False),
               ("item12/equation-typography", True, False),
               ("item19", True, False),
               ("item19/brevity-candidate", True, False),
               ("item19/hedge-candidate", True, False)])
        _two_q = [p["message"] for p in res["problems"] if p["slug"] == "two-q"]
        check("with no definition card, every card after the first is an "
              "extra card to remove; the first keeps its ordinary problems",
              ([m.startswith(EXTRA_CARD_PREFIX % 2)
                for m in _two_q if "card 2" in m],
               any("must be exactly" in m for m in _two_q if "card 2" in m),
               ["must be exactly ??" in m for m in _two_q
                if m.startswith("card 1 line 2")],
               sum(m.startswith('no card carries the primary answer "Two q"')
                   for m in _two_q)),
              ([True, True], False, [True], 1))
        check("an extra card's content after line 3 stays: its removal takes "
              "lines 1–3 and their recognized attachments only",
              [(m.startswith(EXTRA_CARD_PREFIX % 2), m.endswith(
                  "and their recognized attachments only; the content after "
                  "line 3 stays and is reported"))
               for m in (p["message"] for p in res["problems"]
                         if p["slug"] == "extra-stray")
               if "visible lines" in m],
              [(True, True)])
        check("the extra's line-3 markup and leak are both reported",
              [any(word in p["message"] for p in res["problems"]
                   if p["slug"] == "extra-faults")
               for word in ("line 3 (term) has bold", "leaks the answer")],
              [True, True])
        _three = _st_msg(res, "three-cards", "item19")
        check("every further card joins one card-set problem",
              ("holds 3 cards" in _three, "remove every other card" in _three,
               _three.count("holds 3 cards")),
              (True, True, 1))
        _simplified = _st_msg(res, "simplified-primary", "item19")
        check("a card simplified to ? needs its ?? back, and nothing else",
              ('line 2 is "?"' in _simplified,
               "must be exactly ??" in _simplified,
               "does not end with" in _simplified, " line 3 is" in _simplified),
              (True, True, False, False))
        check("an invalid line 2 names both separators",
              "must be exactly ?? (or !! if the user disabled the card)"
              in _st_msg(res, "bad-separator", "item19"), True)
        check("a frequency hedge on the cue is an advisory candidate, never "
              "an item19 error",
              ([k for k in _st_keys(res, "hedge-cue") if k.startswith("item19")],
               '"usually"' in _st_msg(res, "hedge-cue", "item19/hedge-candidate")),
              (["item19/hedge-candidate"], True))
        check("a frequency hedge in the description is an advisory item7 "
              "candidate; a measured frequency and normally distributed are "
              "not",
              ([k for k in _st_keys(res, "hedge-description")
                if k.startswith("item7")],
               '"often"' in _st_msg(res, "hedge-description",
                                    "item7/hedge-candidate"),
               [k for k in _st_keys(res, "measured-description")
                if k.startswith("item7")]),
              (["item7/hedge-candidate"], True, []))
        check("brevity candidates are advisory and never item19 errors",
              ([k for k in _st_keys(res, "long-cue") if k.startswith("item19")],
               "glossary" in _st_msg(res, "glossary-cue",
                                     "item19/brevity-candidate")),
              (["item19/brevity-candidate"], True))

        v = os.path.join(tmp, "v-card-attachments", "Wiki")
        _attached = {
            "inline-state": "It anchors the idea. <!--SR:!2026-09-20,30,250-->\n",
            "next-line-state": "It anchors the idea.\n<!--SR:!2026-09-20,30,250-->\n",
            "callout-state": ("It anchors the idea.\n> [!sr|card-metadata]\n"
                              "> <!--SR:!2026-09-20,30,250--> ^u-card\n"),
            "block-id-state": "It anchors the idea. ^u-card\n",
        }
        for _name, _answer in _attached.items():
            _st_write(v, _name + ".md", _with_cards(
                _name.replace("-", " ").capitalize(),
                "Why does it matter?\n?\n" + _answer))
        before = {p: open(p, "rb").read() for p in iter_entry_files(v)}
        res = scan(v)
        check("recognized attachments on an extra card are not card "
              "content",
              [("holds 2 cards" in _st_msg(res, name, "item19"),
                any(word in _st_msg(res, name, "item19")
                    for word in ("visible lines", "malformed")))
               for name in _attached], [(True, False)] * len(_attached))
        check("the scan leaves every card byte unchanged",
              {p: open(p, "rb").read() for p in iter_entry_files(v)}, before)

        check("an a.k.a. lead-in is stripped from the opener counterpart, as "
              "in lint_entry",
              [flashcard_primary_answer(
                  "PCA", ["principal-component-analysis"],
                  "**PCA** (%s *principal component analysis*) projects data."
                  % lead, "Concept")[1] for lead in ("a.k.a.", "a.k.a")],
              ["principal component analysis"] * 2)
        check("card_rivals pairs siblings under a hub parent and Related targets only",
              build_card_rivals(
                  {"a": "A cue.", "b": "B cue.", "c": "C cue.", "d": "D cue.",
                   "x": "X cue."},
                  {"a": ["hub"], "b": ["hub"], "c": ["root"], "x": ["root"],
                   "hub": ["root"]},
                  {"a": ["a"], "c": ["nocue"], "d": ["b"]}, {"root"}),
              [{"slug": "a", "cue": "A cue.", "rivals": ["b"]},
               {"slug": "b", "cue": "B cue.", "rivals": ["a"]},
               {"slug": "d", "cue": "D cue.", "rivals": ["b"]}])

        # Spaced Repetition settings: advisory, read-only, never raises.
        def _sr_vault(name, data=None, raw=None):
            root = os.path.join(tmp, name)
            path = os.path.join(root, *SR_SETTINGS_PARTS)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(raw if raw is not None else json.dumps(data))
            return root, path
        def _sr_settings(**changes):
            data = {"settings": {
                "flashcardTags": ["#statistics"], "convertFoldersToDecks": False,
                "multilineCardSeparator": "?",
                "multilineReversedCardSeparator": "??",
                "multilineCardEndMarker": "", "dataStore": "NOTES"},
                "scheduleData": {"cardSchedules": {}}}
            data["settings"].update(changes)
            return data
        _counts = {"physics": 1, "statistics": 2}
        _absent = spaced_repetition_report(os.path.join(tmp, "no-vault"), _counts)
        check("absent plugin settings are reported as absent",
              _absent, {"settings": "absent", "uncovered_tags": {},
                        "separator_findings": []})
        _root, _ = _sr_vault("sr-malformed", raw="{not json")
        check("malformed plugin settings are unreadable",
              spaced_repetition_report(_root, _counts)["settings"], "unreadable")
        _real_root, _real_path = _sr_vault("sr-real", _sr_settings())
        _link_root = os.path.join(tmp, "sr-link")
        _link_path = os.path.join(_link_root, *SR_SETTINGS_PARTS)
        os.makedirs(os.path.dirname(_link_path))
        # Only the link creation may fail (unsupported platform); an
        # exception from the reader itself must fail the self-test.
        try:
            os.symlink(_real_path, _link_path)
            _linked = True
        except (OSError, NotImplementedError, AttributeError):
            _linked = False
        if _linked:
            check("a symlinked settings file is never followed",
                  spaced_repetition_report(_link_root, _counts)["settings"],
                  "unreadable")
        _before_stat = os.stat(_real_path)
        _before_bytes = open(_real_path, "rb").read()
        _read = spaced_repetition_report(_real_root, _counts)
        check("readable settings report uncovered tags and no findings",
              (_read["settings"], _read["uncovered_tags"],
               _read["separator_findings"], sorted(_read)),
              ("read", {"physics": 1}, [],
               ["separator_findings", "settings", "uncovered_tags"]))
        check("reading the settings never changes the file",
              (open(_real_path, "rb").read(), os.stat(_real_path).st_mtime_ns),
              (_before_bytes, _before_stat.st_mtime_ns))
        _variants = {}
        for _name, _data in (
                ("folders", _sr_settings(convertFoldersToDecks=True)),
                ("separator", _sr_settings(
                    multilineReversedCardSeparator="::")),
                ("basic-separator", _sr_settings(multilineCardSeparator="::")),
                ("end-marker", _sr_settings(multilineCardEndMarker="+++")),
                ("cloze-bold", _sr_settings(
                    clozePatterns=["**[123;;]answer[;;hint]**"],
                    convertBoldTextToClozes=True)),
                ("cloze-toggles", _sr_settings(
                    convertHighlightsToClozes=True,
                    convertCurlyBracketsToClozes=True)),
                ("cloze-custom", _sr_settings(
                    clozePatterns=["[[123::]answer]"])),
                ("cloze-off", _sr_settings(
                    clozePatterns=[], convertHighlightsToClozes=True)),
                ("single-line", _sr_settings(
                    singleLineCardSeparator=";;",
                    singleLineReversedCardSeparator="")),
                ("single-line-defaults", _sr_settings(
                    singleLineCardSeparator="::",
                    singleLineReversedCardSeparator=":::"))):
            _variants[_name] = spaced_repetition_report(
                _sr_vault("sr-" + _name, _data)[0], _counts)
        check("folders-as-decks covers every tag",
              _variants["folders"]["uncovered_tags"], {})
        check("a changed multi-line separator or end marker is one finding "
              "each",
              (len(_variants["separator"]["separator_findings"]),
               len(_variants["end-marker"]["separator_findings"]),
               len(_variants["basic-separator"]["separator_findings"])),
              (1, 1, 1))
        check("each active cloze conversion is one finding naming its toggle; "
              "an explicit empty pattern list turns the toggles off",
              [[(("convertBoldTextToClozes" in finding),
                 ("convertHighlightsToClozes" in finding),
                 ("convertCurlyBracketsToClozes" in finding),
                 "keep cloze conversion off" in finding)
                for finding in _variants[name]["separator_findings"]]
               for name in ("cloze-bold", "cloze-toggles", "cloze-custom",
                            "cloze-off")],
              [[(True, False, False, True)],
               [(False, True, False, True), (False, False, True, True)],
               [(False, False, False, True)], []])
        check("a changed single-line separator is a finding; an empty or "
              "default one is not",
              ([finding.split(" is ")[0] for finding in
                _variants["single-line"]["separator_findings"]],
               _variants["single-line-defaults"]["separator_findings"]),
              (["singleLineCardSeparator"], []))

        # ------------------------------------------------------------------
        # Discipline roots need no card; parents link down to their children.
        # ------------------------------------------------------------------
        v = os.path.join(tmp, "v-root-cards", "Wiki")
        _st_write(v, "statistics.md", _st_entry(
            "Statistics", "**Statistics** is a field.", card=False))
        _st_write(v, "standard-deviation.md", _st_entry(
            "Standard deviation", "**Standard deviation** is a spread.",
            card=False))
        _st_write(v, "mathematics.md", _st_entry(
            "Mathematics", "**Mathematics** is a field.",
            tags=('"#mathematics"',), card=False) + "\n---\n\n## Flashcards\n")
        _st_write(v, "physics.md", _st_entry(
            "Physics", "**Physics** is a field.", tags=('"#physics"',),
            card="Wrong term"))
        _st_write(v, "biology.md", _st_entry(
            "Biology", "**Biology** is a field.", tags=('"#biology"',))
            .replace("\n??\nBiology\n", "\n?\nBiology\n"))
        _st_write(v, "chemistry.md", _st_entry(
            "Chemistry", "**Chemistry** is a field.", tags=('"#chemistry"',),
            card="Wrong term").rstrip("\n")
            + "\n\nA different main claim.\n??\nOther term\n")
        # lint_entry's _is_root_entry applies the same tags_valid_single gate.
        for _tag, _extra in (("economics", "read: false\n"),
                             ("finance", "stray prose\n")):
            _st_write(v, _tag + ".md", _st_entry(
                _tag.capitalize(), "**%s** is a field." % _tag.capitalize(),
                tags=('"#%s"' % _tag,), card=False)
                .replace("read: false\n", "read: false\n" + _extra))
        res = scan(v)
        check("a discipline root needs no Flashcards section",
              [k for k in _st_keys(res, "statistics")
               if k == "item19" or k == "item11" or k.startswith("item10")], [])
        check("a non-root without a card still needs one",
              "entry missing ## Flashcards section" in _st_msg(
                  res, "standard-deviation", "item19"), True)
        check("a root with an empty section raises no card-count finding",
              ("has no card" in _st_msg(res, "mathematics", "item19"),
               "primary" in _st_msg(res, "mathematics", "item19")),
              (False, False))
        check("a root that keeps its card is checked as usual",
              "line 3 is" in _st_msg(res, "physics", "item19"), True)
        _biology = _st_msg(res, "biology", "item19")
        check("a root's card simplified to ? keeps its per-card checks",
              ("must be exactly ??" in _biology,
               "no card carries the primary answer" in _biology), (True, False))
        _chemistry = _st_msg(res, "chemistry", "item19")
        check("a root with two cards needs no primary card",
              ("holds 2 cards" in _chemistry,
               "no card carries the primary answer" in _chemistry),
              (True, False))
        check("a duplicated non-tag key keeps the root; an unreadable line voids it",
              ["entry missing ## Flashcards section" in _st_msg(res, _tag, "item19")
               for _tag in ("economics", "finance")], [False, True])

        # item 4: a discipline root cites a source like every entry.
        _src_v = os.path.join(tmp, "root-sources", "Wiki")
        _st_write(_src_v, "statistics.md", _st_entry(
            "Statistics", "**Statistics** is a field.", sources=(), card=False))
        _st_write(_src_v, "physics.md", _st_entry(
            "Physics", "**Physics** is a field.", tags=('"#physics"',),
            sources=('"https://en.wikipedia.org/wiki/Physics"',), card=False))
        res = scan(_src_v)
        check("a discipline root needs a source too; a cited page satisfies it",
              (_st_msg(res, "statistics", "item4"), _st_msg(res, "physics", "item4")),
              ("sources: is empty; every entry needs at least one source", ""))

        def _org_vault(name, models_prose=None, trees_aliases=(),
                       models_related=None, extra=()):
            wiki = os.path.join(tmp, name, "Wiki")
            ml = ('"#machine-learning"',)
            _st_write(wiki, "machine-learning.md", _st_entry(
                "Machine learning", "**Machine learning** is a field.",
                tags=ml, card=False, related="[[linear-model|Linear model]]"))
            _st_write(wiki, "models.md", _st_entry(
                "Models", models_prose or
                "**Models** is a worked example that includes [[trees|trees]].",
                tags=ml, parents=('"[[machine-learning]]"',),
                related=models_related))
            _st_write(wiki, "trees.md", _st_entry(
                "Trees", "**Trees** is a worked example.", tags=ml,
                aliases=trees_aliases, parents=('"[[models]]"',)))
            _st_write(wiki, "linear-model.md", _st_entry(
                "Linear model", "**Linear model** is a worked example.",
                tags=ml, parents=('"[[models]]"',)))
            _st_write(wiki, "decision-tree.md", _st_entry(
                "Decision tree", "**Decision tree** is a worked example.",
                tags=ml, parents=('"[[trees]]"',)))
            for _file, _text in extra:
                _st_write(wiki, _file, _text)
            return wiki

        def _rows(result):
            return {row["slug"]: row for row in
                    result["hierarchy_diagnostic"]["unlinked_children"]}
        res = scan(_org_vault("v-org"))
        _unlinked = _rows(res)
        check("unlinked_children lists a parent's unlinked children",
              (_unlinked.get("models", {}).get("unlinked"),
               _unlinked.get("models", {}).get("branch_heads"),
               _unlinked.get("models", {}).get("children")),
              (["linear-model"], [], 2))
        check("a root lists its unlinked branch heads and counts every footer wikilink",
              (_unlinked.get("machine-learning", {}).get("unlinked"),
               _unlinked.get("machine-learning", {}).get("branch_heads"),
               _unlinked.get("machine-learning", {}).get("footer_links")),
              (["models"], ["models"], 1))
        _rivals = {row["slug"]: row["rivals"] for row in res["card_rivals"]}
        check("children of a hub parent are each other's card rivals",
              (_rivals.get("trees"), _rivals.get("linear-model"),
               "machine-learning" in _rivals), (["linear-model"], ["trees"], False))
        _question_first = (_st_entry(
            "Linear model", "**Linear model** is a worked example.",
            tags=('"#machine-learning"',), parents=('"[[models]]"',))
            .replace("## Flashcards\n\n", "## Flashcards\n\nWhy does the "
                     "model fit?\n?\nBecause of thresholds.\n\n", 1)
            .replace("\n??\nLinear model\n", "\n??\nlinear model\n", 1))
        _res_question_first = scan(_org_vault(
            "v-org-question-first",
            extra=(("linear-model.md", _question_first),)))
        check("card_rivals takes the primary card's cue, not an extra card "
              "placed before it",
              [row["cue"] for row in _res_question_first["card_rivals"]
               if row["slug"] == "linear-model"],
              ["The idea this entry is about, stated once."])
        check("scan output keys follow the documented order",
              [key for key in res if key in {
                  "backfill_candidates", "hub_footer", "card_rivals",
                  "image_folder_findings", "spaced_repetition",
                  "hierarchy_diagnostic"}],
              ["backfill_candidates", "hub_footer", "card_rivals",
               "image_folder_findings", "spaced_repetition",
               "hierarchy_diagnostic"])
        res = scan(_org_vault(
            "v-org-alias",
            models_prose="**Models** is a worked example that includes "
                         "[[tree-models|tree models]] and "
                         "[[Linear-Model|linear model]].",
            trees_aliases=('"tree-models"',)))
        check("a child linked through an alias or case variant counts as linked",
              "models" in _rows(res), False)
        _full = " · ".join("[[n%02d|N%02d]]" % (i, i) for i in range(1, 13))
        res = scan(_org_vault(
            "v-org-full", models_related=_full,
            extra=[("n%02d.md" % i, _st_entry(
                "N%02d" % i, "**N%02d** is a worked example." % i,
                tags=('"#machine-learning"',)))
                   for i in range(1, 13)]))
        check("a parent whose footer is full is not listed",
              "models" in _rows(res), False)
        v = os.path.join(tmp, "v-org-misc")
        _st_write(v, "misc.md", _st_entry(
            "Misc", "**Misc** is a holding area.", tags=('"#misc"',), card=False))
        for _name in ("Loose one", "Loose two"):
            _st_write(v, slug(_name) + ".md", _st_entry(
                _name, "**%s** is a worked example." % _name,
                tags=('"#misc"',), parents=('"[[misc]]"',)))
        check("misc is exempt from unlinked_children",
              "misc" in _rows(scan(v)), False)

        def _hub_vault(name, footers=16, hub_parents=('"[[topic]]"',),
                       owner_parents=(), hub_related=None):
            wiki = os.path.join(tmp, name)
            _st_write(wiki, "statistics.md", _st_entry(
                "Statistics", "**Statistics** is a field.", card=False))
            _st_write(wiki, "topic.md", _st_entry(
                "Topic", "**Topic** is a worked example."))
            _st_write(wiki, "hub-term.md", _st_entry(
                "Hub term", "**Hub term** is a worked example.",
                parents=hub_parents, related=hub_related))
            footer = "[[hub-term|Hub term]] · [[statistics|Statistics]]"
            _st_write(wiki, "hub-child.md", _st_entry(
                "Hub child", "**Hub child** is a worked example.",
                parents=('"[[hub-term]]"',), related=footer))
            _st_write(wiki, "hub-sibling.md", _st_entry(
                "Hub sibling", "**Hub sibling** is a worked example.",
                parents=('"[[topic]]"',), related=footer))
            for i in range(1, footers - 1):
                _st_write(wiki, "u%02d.md" % i, _st_entry(
                    "U%02d" % i, "**U%02d** is a worked example." % i,
                    parents=owner_parents if i == 1 else (), related=footer))
            return wiki
        _hub_wiki = _hub_vault("v-hub")
        res = scan(_hub_wiki)
        check("hub_footer lists vocabulary footers at the threshold",
              [(row["target"], row["footers"], row["entries"])
               for row in res["hub_footer"]],
              [("hub-term", 16, ["u%02d" % i for i in range(1, 15)])])
        check("a discipline root is never a hub target",
              [row["target"] for row in res["hub_footer"]
               if row["target"] == "statistics"], [])
        check("the scan is deterministic apart from its run timestamp",
              {k: value for k, value in scan(_hub_wiki).items()
               if k != "run_timestamp"},
              {k: value for k, value in res.items() if k != "run_timestamp"})
        res = scan(_hub_vault("v-hub-recip", hub_related="[[u01|U01]]"))
        check("an entry the hub's own footer lists back is not listed",
              [row["entries"] for row in res["hub_footer"]
               if row["target"] == "hub-term"],
              [["u%02d" % i for i in range(2, 15)]])
        check("below the threshold nothing is listed",
              scan(_hub_vault("v-hub-14", footers=14))["hub_footer"], [])
        res = scan(_hub_vault("v-hub-root", hub_parents=('"[[statistics]]"',),
                              owner_parents=('"[[statistics]]"',)))
        check("siblings under only a discipline root are not exempt",
              any("u01" in row["entries"] for row in res["hub_footer"]
                  if row["target"] == "hub-term"), True)
        check("hub_footer_min grows with the Wiki",
              (hub_footer_min(258), hub_footer_min(400), hub_footer_min(1000)),
              (15, 20, 50))
        # The settled-decisions ledger (--settled): a recorded rejection or
        # kept hub item is omitted until its sentence or footer line changes.
        _text = ("First one. Second\nline here.\n- Item one. Item two.\n\n"
                 "Last.")
        check("a settle context is the sentence within its block",
              [_sentence_at(_text, _text.index(word))
               for word in ("one.", "line", "two", "Last")],
              ["First one.", "Second line here.", "Item two.", "Last."])
        _settle_wiki = _hub_vault("v-hub-settled")
        _st_write(_settle_wiki, "settle-reader.md", _st_entry(
            "Settle reader", "**Settle reader** names a hub term once. It "
            "also names a topic."))
        _ledger = os.path.join(tmp, "settled.json")
        res0 = scan(_settle_wiki, settled=_ledger)
        _bf_key = next(row["settle_key"] for row in res0["backfill_candidates"]
                       if row["target"] == "hub-term")
        _hub_row = next(row for row in res0["hub_footer"]
                        if row["target"] == "hub-term")
        _hub_key = _hub_row["settle_keys"][_hub_row["entries"].index("u01")]
        check("a missing ledger is empty; each row carries its settle key",
              (res0["settled"], _bf_key, _hub_key),
              ({"path": _ledger, "backfill_suppressed": 0,
                "hub_footer_suppressed": 0,
                "stale": {"backfill": [], "hub_footer": []}, "upgrade": [],
                "error": None},
               {"entry": "settle-reader", "target": "hub-term",
                "surface": "hub term",
                "context": settle_context("**Settle reader** names a hub "
                                          "term once.")},
               {"entry": "u01", "target": "hub-term",
                "context": settle_context("**Related:** [[hub-term|Hub term]] "
                                          "· [[statistics|Statistics]]")}))
        _gone = {"entry": "gone", "target": "hub-term", "surface": "hub term",
                 "context": "0" * 40}
        with open(_ledger, "w", encoding="utf-8") as fh:
            json.dump({"version": 2, "backfill": [_bf_key, _gone],
                       "hub_footer": [_hub_key]}, fh)
        res1 = scan(_settle_wiki, settled=_ledger)

        def _settle_view(res):
            hub = [row["entries"] for row in res["hub_footer"]
                   if row["target"] == "hub-term"]
            return (sorted(row["target"] for row in res["backfill_candidates"]
                           if row["slug"] == "settle-reader"),
                    "u01" in (hub[0] if hub else []),
                    res["settled"]["backfill_suppressed"],
                    res["settled"]["hub_footer_suppressed"],
                    [len(res["settled"]["stale"][kind])
                     for kind in ("backfill", "hub_footer")],
                    res["settled"]["error"])
        check("a settled row is suppressed and an unmatched record is stale",
              _settle_view(res1), (["topic"], False, 1, 1, [1, 0], None))
        check("the ledger never suppresses problems",
              res1["problems"] == res0["problems"], True)
        _st_write(_settle_wiki, "settle-reader.md", _st_entry(
            "Settle reader", "**Settle reader** names a hub term twice. It "
            "also names a topic."))
        _st_write(_settle_wiki, "u01.md", _st_entry(
            "U01", "**U01** is a worked example.",
            related="[[statistics|Statistics]] · [[hub-term|Hub term]]"))
        check("an edited sentence or footer line restores the row",
              _settle_view(scan(_settle_wiki, settled=_ledger)),
              (["hub-term", "topic"], True, 0, 0, [2, 1], None))
        _st_write(_settle_wiki, "settle-reader.md", _st_entry(
            "Settle reader", "**Settle reader** names a hub term and a topic."))
        _before = next(row["settle_key"] for row in scan(_settle_wiki)
                       ["backfill_candidates"] if row["target"] == "hub-term")
        _st_write(_settle_wiki, "settle-reader.md", _st_entry(
            "Settle reader", "**Settle reader** names a hub term and a "
            "[[topic]]."))
        check("linking another candidate in the sentence keeps the key",
              [row["settle_key"] for row in scan(_settle_wiki)
               ["backfill_candidates"] if row["target"] == "hub-term"],
              [_before])
        _st_write(_settle_wiki, "settle-reader.md", _st_entry(
            "Settle reader", "**Settle reader** names a hub term twice. It "
            "also names a topic."))
        for _bad in ("{not json", '{"version": 3}', '{"version": 2, '
                     '"backfill": [{"entry": "x"}]}', '{"version": true}',
                     '{"version": 2, "hub_footers": []}'):
            with open(_ledger, "w", encoding="utf-8") as fh:
                fh.write(_bad)
            _view = _settle_view(scan(_settle_wiki, settled=_ledger))
            check("a malformed ledger suppresses nothing and is reported: "
                  + _bad, (_view[:5], bool(_view[5])),
                  ((["hub-term", "topic"], True, 0, 0, [0, 0]), True))
        _all_keys = [key for key in scan(_settle_wiki)["hub_footer"][0]
                     ["settle_keys"]]
        with open(_ledger, "w", encoding="utf-8") as fh:
            json.dump({"version": 2, "hub_footer": _all_keys}, fh)
        res = scan(_settle_wiki, settled=_ledger)
        check("a hub target left with no item is omitted",
              (res["hub_footer"], res["settled"]["hub_footer_suppressed"]),
              ([], len(_all_keys)))
        # A settled occurrence yields to the target's next sentence, so a
        # rejected first mention in another sense never hides a later one.
        # Two mentions in one sentence are one occurrence.
        _later = os.path.join(tmp, "v-settle-later")
        _st_write(_later, "topic.md", _st_entry(
            "Topic", "**Topic** is a worked example."))
        _st_write(_later, "settle-later.md", _st_entry(
            "Settle later", "**Settle later** names a topic and a topic "
            "again.\n\nIt names a topic once more."))
        _later_ledger = os.path.join(tmp, "settled-later.json")
        _later_contexts = [settle_context(sentence) for sentence in (
            "**Settle later** names a topic and a topic again.",
            "It names a topic once more.")]

        def _later_view(res, slug="settle-later"):
            return ([(row["line"], row["settle_key"]["context"],
                      [key["context"] for key in row["settle_keys"]])
                     for row in res["backfill_candidates"]
                     if row["slug"] == slug],
                    res["settled"]["backfill_suppressed"],
                    res["settled"]["stale"]["backfill"])
        _later_views = [_later_view(scan(_later))]
        for _count in range(3):
            with open(_later_ledger, "w", encoding="utf-8") as fh:
                json.dump({"version": 2, "backfill": [
                    {"entry": "settle-later", "target": "topic",
                     "surface": "topic", "context": _context}
                    for _context in _later_contexts[:_count]]}, fh)
            _later_views.append(_later_view(scan(_later,
                                                 settled=_later_ledger)))
        check("a settled occurrence yields to the target's next sentence",
              _later_views,
              [([(1, _later_contexts[0], _later_contexts)], 0, []),
               ([(1, _later_contexts[0], _later_contexts)], 0, []),
               ([(3, _later_contexts[1], _later_contexts[1:])], 1, []),
               ([], 2, [])])
        # A rejection stores the row's settle_keys, so a target the entry
        # mentions in three sentences stays settled on the next scan.
        _st_write(_later, "settle-three.md", _st_entry(
            "Settle three", "**Settle three** names a topic. It names a "
            "topic again. A third sentence names a topic."))
        _three = next(row for row in scan(_later)["backfill_candidates"]
                      if row["slug"] == "settle-three")
        with open(_later_ledger, "w", encoding="utf-8") as fh:
            json.dump({"version": 2, "backfill": _three["settle_keys"]}, fh)
        check("a rejection's settle_keys settle every sentence of its target",
              (len(_three["settle_keys"]),
               _later_view(scan(_later, settled=_later_ledger),
                           "settle-three")),
              (3, ([], 3, [])))
        # A version-1 record settles its entry and target while it matches
        # the target's first sentence; `upgrade` lists the others.
        with open(_later_ledger, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "backfill": [_three["settle_key"]]}, fh)
        res = scan(_later, settled=_later_ledger)
        check("a version-1 record settles its target's later sentences",
              (_later_view(res, "settle-three"), res["settled"]["upgrade"]),
              (([], 3, []), _three["settle_keys"][1:]))
        with open(_later_ledger, "w", encoding="utf-8") as fh:
            json.dump({"version": 2, "backfill": [_three["settle_key"]]
                       + res["settled"]["upgrade"]}, fh)
        res = scan(_later, settled=_later_ledger)
        check("its version-2 rewrite with the upgrade keeps them settled",
              (_later_view(res, "settle-three"), res["settled"]["upgrade"]),
              (([], 3, []), []))
        # Body line numbers count from the line after the closing fence,
        # including blank lines left there (an item-9 defect).
        _gap_lines = os.path.join(tmp, "v-gap-lines")
        _st_write(_gap_lines, "topic.md", _st_entry(
            "Topic", "**Topic** is a worked example."))
        _st_write(_gap_lines, "gap-lines.md", _st_entry(
            "Gap lines", "**Gap lines** is a worked example.\n\n"
            "It names a topic.\n\n| Case | Note |\n| --- | --- |\n"
            "| one | [[topic]] |").replace("\n---\n", "\n---\n\n\n", 1))
        res = scan(_gap_lines)
        check("body line numbers count blank lines after the fence",
              ([row["line"] for row in res["backfill_candidates"]
                if row["slug"] == "gap-lines"],
               "blank line immediately after frontmatter" in _st_msg(
                   res, "gap-lines", "item9"),
               "on body line 9 " in _st_msg(res, "gap-lines", "item10/table")),
              ([5], True, True))
        # A compound that is another entry's title names that entry: its head
        # word is no mention of its own entry for backfill or a late link.
        _compound = os.path.join(tmp, "v-compound-entry")
        _st_write(_compound, "rna.md", _st_entry(
            "RNA", "**RNA** (ribonucleic acid) is a worked example.",
            aliases=('"ribonucleic acid"',)))
        _st_write(_compound, "messenger-rna.md", _st_entry(
            "Messenger RNA", "**Messenger RNA** (mRNA) is a worked example.",
            aliases=('"mRNA"',)))
        _st_write(_compound, "compound-bare.md", _st_entry(
            "Compound bare", "**Compound bare** holds messenger RNAs."))
        _st_write(_compound, "compound-linked.md", _st_entry(
            "Compound linked", "**Compound linked** holds messenger RNAs "
            "([[messenger-rna|mRNAs]]). Later the [[rna|RNA]] decays."))
        _st_write(_compound, "compound-early.md", _st_entry(
            "Compound early", "**Compound early** studies RNA. It holds "
            "messenger RNAs ([[messenger-rna|mRNAs]]). Later the "
            "[[rna|RNA]] decays."))
        res = scan(_compound)
        check("a compound naming an entry is that entry's mention, never its "
              "head word's",
              ([(row["slug"], row["target"]) for row in
                res["backfill_candidates"] if row["slug"].startswith("compound")],
               ["item10/late-link" in _st_keys(res, name)
                for name in ("compound-linked", "compound-early")]),
              ([("compound-bare", "messenger-rna")], [False, True]))
        # One unreadable file hides whatever aliases it holds, so the
        # alias-dependent worklists stay empty until a clean rescan.
        _gap_hub = _hub_vault("v-hub-alias-gap")
        _st_write(_gap_hub, "introduced-name.md", _st_entry(
            "Introduced name", "**Introduced name** — which many people "
            "call *alternate label* — is a worked example."))
        _complete_hub_res = scan(_gap_hub)
        _st_write(_gap_hub, "unreadable.md", b'---\ntitle: "Caf\xe9"\n---\nbody\n')
        _gap_hub_res = scan(_gap_hub)
        check("an alias-inventory gap empties item17 alias candidates, "
              "hub_footer and unlinked_children that a complete inventory "
              "reports",
              [(bool(r["hub_footer"]),
                bool(r["hierarchy_diagnostic"]["unlinked_children"]),
                "item17/alias-candidate" in _st_keys(r, "introduced-name"))
               for r in (_complete_hub_res, _gap_hub_res)],
              [(True, True, True), (False, False, False)])
        check("an alias-inventory gap reports no ledger record as stale",
              [len(scan(_gap_hub, settled=_ledger)["settled"]["stale"][kind])
               for kind in ("backfill", "hub_footer")], [0, 0])
        with open(_later_ledger, "w", encoding="utf-8") as fh:
            json.dump({"version": 1}, fh)
        check("an alias-inventory gap leaves a version-1 upgrade unknown",
              [scan(_gap_hub, settled=path)["settled"]["upgrade"]
               for path in (_ledger, _later_ledger)],
              [[], None])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [c for c in cases if not c[1]]
    for label, ok, got, want in cases:
        if not ok:
            print("FAIL  %s\n        got  %r\n        want %r" % (label, got, want))
    print("%d/%d self-test cases pass" % (len(cases) - len(failed), len(cases)))
    return 1 if failed else 0


def _looks_like_vault_root(wiki, vault=None):
    """Whether the WIKI argument names a vault root instead of its Wiki/."""
    if (os.path.isdir(os.path.join(wiki, ".obsidian"))
            or os.path.isdir(os.path.join(wiki, "Wiki"))):
        return True
    return (vault is not None
            and os.path.realpath(wiki) == os.path.realpath(vault))


def _vault_spelling(wiki, vault):
    """The ancestor of WIKI that is the vault folder, spelled as in WIKI.

    Folders are compared by identity, so a symlink alias, ``/tmp`` beside
    ``/private/tmp``, or an NFC beside an NFD name finds the same folder.
    Returns None when no ancestor of WIKI is the vault.
    """
    current = os.path.dirname(os.path.abspath(wiki))
    while True:
        try:
            if os.path.samefile(current, vault):
                return current
        except OSError:
            pass
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def _wiki_spelling(wiki, base):
    """WIKI with each folder below ``base`` spelled as its directory entry.

    A case-folding host opens ``<vault>/wiki`` for ``<vault>/Wiki``, but the
    scan spells qualified links from WIKI's path, so each folder takes the
    name its parent lists for it: the entry that names the same folder under
    the portable case/Unicode identity.
    """
    current = base
    for part in os.path.relpath(os.path.abspath(wiki), base).split(os.sep):
        if part == os.curdir:
            continue
        try:
            names = sorted(os.listdir(current))
        except OSError:
            names = [part]
        if part not in names:
            for name in names:
                try:
                    if (fold_name(name) == fold_name(part)
                            and os.path.samefile(os.path.join(current, name),
                                                 os.path.join(current, part))):
                        part = name
                        break
                except OSError:
                    pass
        current = os.path.join(current, part)
    return current


def _enclosing_wiki_folder(wiki, vault):
    """A folder named ``Wiki`` between the vault and WIKI, or None."""
    current = os.path.dirname(os.path.abspath(wiki))
    while current != vault and os.path.dirname(current) != current:
        if fold_name(os.path.basename(current)) == "wiki":
            return current
        current = os.path.dirname(current)
    return None


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, OSError):
            pass
    ap = argparse.ArgumentParser(
        prog="scan_vault.py",
        description="Scan a wiki-build vault and emit the wiki-lint Step 0 inventory as JSON.")
    ap.add_argument("wiki", nargs="?",
                    help="path to the vault's Wiki/ folder (walked recursively; "
                         "entries in subfolders are scanned too)")
    ap.add_argument("--vault", metavar="DIR",
                    help="selected vault root for qualified links, parents, "
                         "backfill targets, and MOC diagnostics; WIKI must lie "
                         "inside it; when omitted, "
                         "infer it from --images, a .obsidian ancestor, or "
                         "the Wiki folder's parent")
    ap.add_argument("--images", metavar="DIR",
                    help="the vault's flat Sources/Images/ folder; with it, every "
                         "![[…]] image embed is checked to name a file that exists "
                         "(item12/missing-image), and nested or temporary artifacts "
                         "are reported in image_folder_findings. Omitted, neither "
                         "folder check runs")
    ap.add_argument("--settled", metavar="FILE",
                    help="the settled-decisions ledger "
                         "(<vault>/Reviews/.wiki-lint-settled.json): omit the "
                         "backfill_candidates occurrences and hub_footer "
                         "items it records (a settled occurrence yields to "
                         "the target's next sentence); a missing file is an "
                         "empty ledger, an "
                         "unreadable or malformed one suppresses nothing and "
                         "is reported in settled.error. Never written here")
    ap.add_argument("--out", metavar="FILE",
                    help="write the JSON to FILE instead of stdout")
    ap.add_argument("--indent", type=int, default=2, metavar="N",
                    help="JSON indent; 0 for one compact line (default: 2)")
    ap.add_argument("--test", action="store_true",
                    help="run the built-in self-test and exit")
    args = ap.parse_args(argv)
    if args.test:
        return run_self_test()
    if not args.wiki:
        print("missing required argument: the Wiki/ folder to scan (or --test)",
              file=sys.stderr)
        return 2
    if not os.path.isdir(args.wiki):
        ap.error("not a directory: %s" % args.wiki)
    if args.vault is not None and not os.path.isdir(args.vault):
        ap.error("--vault is not a directory: %s" % args.vault)
    # WIKI and --vault differ only by `/Wiki`. Given the vault root, the scan
    # reads every Articles/, Slides/ or Investments/ note as a broken entry
    # and exits 0 with thousands of false repair cues.
    if _looks_like_vault_root(args.wiki, args.vault):
        ap.error("WIKI looks like a vault root: %s; pass <vault>/Wiki"
                 % args.wiki)
    # A mistyped --images must not read as "the folder is empty": that reports
    # EVERY embed in the vault as naming a missing file, and the executing agent reading
    # that has no way to tell it from a genuinely broken vault. `isdir`, not
    # `exists` — a path that is a file satisfies `exists` and then lists nothing,
    # which is the same silent-empty failure. This script does not create the
    # folder, because a typo would create the typo.
    if args.images is not None and not os.path.isdir(args.images):
        ap.error("--images is not a directory: %s. No embed was checked; this is "
                 "not a vault with no images." % args.images)
    # Every vault-relative target is a path from WIKI to the vault. WIKI must
    # lie inside the vault, be read under WIKI's own spelling of it, and be
    # the wiki folder itself: a subfolder turns working links into danglers.
    vault, vault_known = _vault_root_for(args.wiki, args.images, args.vault)
    if vault_known:
        spelled = _vault_spelling(args.wiki, vault)
        if spelled is None:
            ap.error("WIKI is not inside the vault %s; pass <vault>/Wiki "
                     "with --vault <vault>" % vault)
        enclosing = _enclosing_wiki_folder(args.wiki, spelled)
        if enclosing is not None:
            ap.error("WIKI is a subfolder of the wiki folder %s; pass that "
                     "folder and narrow the run to its entries" % enclosing)
        vault = spelled
    else:
        vault = None
    wiki = _wiki_spelling(args.wiki, vault or os.path.dirname(
        os.path.abspath(args.wiki)))
    try:
        report = scan(wiki, args.images, vault=vault, settled=args.settled)
    except IncompleteWikiInventoryError as exc:
        print("scan blocked: %s" % exc, file=sys.stderr)
        return 1
    text = json.dumps(report, ensure_ascii=False,
                      indent=(args.indent or None))
    if args.out:
        # Write what stdout mode writes: a filename that is not valid UTF-8
        # (a lone surrogate on Linux) becomes a JSON escape, not a crash.
        with open(args.out, "w", encoding="utf-8",
                  errors="backslashreplace") as fh:
            fh.write(text + "\n")
        print("wrote %s" % args.out, file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
