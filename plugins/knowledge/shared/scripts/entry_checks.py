#!/usr/bin/env python3
"""Per-entry Wiki checks shared by wiki-build's gate and wiki-lint's scanner.

wiki-build's ``lint_entry.py`` and wiki-lint's ``scan_vault.py`` read these
source-independent Quality Checklist floors (items 5, 6, 13, 14, 16 and 18,
item 4's source-identity pairs, item 7's description subject, item 9's
acronym-title expansion, list indentation, list mismatches and register
candidates, item 17's single-word alias hint, and item 19's card set,
primary answer on card line 3, primary card and Spaced Repetition markers in
the body and on card lines) and the discipline-root test from this one
copy, so an entry that passes the builder gate does not fail the next scan on
the same mechanical rule. Each check returns dictionaries with a ``check``
name, a ``message`` and evidence, or a fault message; callers choose the
finding key and severity.
``prose`` is an entry's comment-masked explanatory body (up to the Related
footer or the Flashcards section), without the blank lines after the
frontmatter. Stdlib only (plus sibling shared helpers), Python 3.10+.
"""

import argparse
import os
import re
import sys

# Keep sibling imports working when a harness loads this file directly by path
# rather than running it as a script (where Python supplies this path).
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from code_typography import FILE_EXTENSIONS  # noqa: E402
from entry_structure import (  # noqa: E402
    BOLD_TEXT,
    SOURCE_REFERENCE_FORMS,
    _BOLD_OUTER_RE,
    acronym_initial_forms,
    description_subject_forms,
    first_letter_ci_equal,
    first_prose_paragraph_lines,
    mask_body_comments,
    math_title_plain_text,
    normalized_answer_surface,
    register_hints,
    source_reference_kind,
    source_stem,
    split_sentences,
    strip_code,
    strip_fenced,
    strip_indented,
    title_display_form,
)
from markdown_tables import (  # noqa: E402
    markdown_block_start,
    markdown_table_spans,
    mask_line_spans,
)
from organism_names import (  # noqa: E402
    bound_common_names,
    first_sentence,
    organism_title_classification,
    scientific_abbreviation_matches,
)
from naming import chapter_book_stem, core_stem  # noqa: E402
from plurals import pluralize, singular_forms, singular_keys  # noqa: E402
from portable_names import portable_identity  # noqa: E402
from slugify import SlugError, base_term, has_parenthetical, slug_stem  # noqa: E402


__all__ = [
    "BARE_WORD_ALIAS_HINT",
    "BOLD_OUTER_RE",
    "BOLD_PAREN_RE",
    "COMMON_NOUNS",
    "CROSS_DOMAIN_PHRASES",
    "EXTRA_CARD_PREFIX",
    "PAREN_LEADIN_RE",
    "SHARED_MUTATIONS",
    "SHARED_QUIET",
    "SR_INLINE_SEPARATORS",
    "SOURCE_REFERENCE_FORMS",
    "acronym_counterpart",
    "acronym_expansion_missing",
    "api_surface_findings",
    "bare_common_noun_slug",
    "bare_word_alias_candidate",
    "bold_parts",
    "cross_domain_alias_findings",
    "cross_domain_synonym_label",
    "cross_domain_word",
    "description_has_entity_subject",
    "description_subject_findings",
    "display_label_links",
    "emphasis_span_findings",
    "flashcard_line3_fault",
    "flashcard_primary_answer",
    "flashcard_set_faults",
    "is_discipline_root",
    "kept_card_label",
    "label_drops_head",
    "label_shares_surface",
    "line3_parts",
    "list_indent_findings",
    "list_mismatch_findings",
    "merge_scar_findings",
    "organism_common_name_bound",
    "organism_common_name_surfaces",
    "plural_surface",
    "primary_card_label",
    "primary_line3_faults",
    "pure_math_opener_markup",
    "register_findings",
    "source_identity_pairs",
    "source_meta_findings",
    "sr_card_marker_faults",
    "sr_card_syntax_fault",
    "sr_inline_marker",
    "sr_marker_findings",
    "source_reference_kind",
    "unenumerated_bold_findings",
]


# ---------------------------------------------------------------------------
# item 4: one document, one citation
# ---------------------------------------------------------------------------

def _source_filename(value):
    """The unfolded filename a ``sources:`` item names: no ``[[ ]]``, display
    pipe, anchor or folder.  naming.py reads the canonical capitals of its
    ``_src`` rule, which :func:`source_stem` folds away."""
    name = (value or "").strip()
    if name.startswith("[[") and name.endswith("]]"):
        name = name[2:-2]
    name = name.split("|", 1)[0].split("#", 1)[0]
    return name.replace("\\", "/").rsplit("/", 1)[-1].strip()


def source_identity_pairs(values):
    """Item 4: ``(kind, first, second)`` index pairs of ``sources:`` items
    that may name one document.

    ``same-stem`` pairs a Markdown item (``second``) with the first PDF item
    of the same folded stem (``first``): a PDF summary in ``Articles/`` takes
    its PDF's stem, but a web clipping can share it, so the pair is a
    provenance-review candidate.  ``book-and-chapter`` pairs a chapter PDF
    (``second``) with the first PDF whose core stem (``_src`` removed, ``_N``
    kept) is the book the chapter names: a split book is cited in one form.
    URL items and items without an extension never pair.
    """
    pdfs, mds, books, chapters = {}, [], {}, []
    for index, value in enumerate(values):
        stem, ext = source_stem(value)
        if not stem:
            continue
        if ext == "pdf":
            pdfs.setdefault(stem, index)
            name = _source_filename(value)
            books.setdefault(portable_identity(core_stem(name)), index)
            book = chapter_book_stem(name)
            if book:
                chapters.append((portable_identity(book), index))
        elif ext == "md":
            mds.append((stem, index))
    return ([("book-and-chapter", books[book], index)
             for book, index in chapters if book in books]
            + [("same-stem", pdfs[stem], index)
               for stem, index in mds if stem in pdfs])


# ---------------------------------------------------------------------------
# item 5: the cross-domain common-noun floor
# ---------------------------------------------------------------------------

#: The explicit mechanical floor in wiki-build/references/special-titles.md,
#: Cross-domain term disambiguation, test (c).  The prose rule remains broader
#: (dictionary and drafting tests catch terms outside a finite set); every term
#: it names explicitly must at least be guarded, both from a bare filename and
#: from becoming an automatic backfill destination. No such word is proposed as
#: an alias; a target that introduces one in italics accepts it as a label.
COMMON_NOUNS = frozenset({
    "activation", "agent", "attention", "attribute", "bias", "cell",
    "classification", "clustering", "collinearity", "domain", "ensemble",
    "entropy", "feature", "field", "filter", "function", "gradient", "inertia",
    "kernel", "label", "model", "normalization", "policy", "predictor",
    "regression", "return", "sensitivity", "shrinkage", "target",
    "temperature", "tensor", "transformer", "vector",
})

#: The same floor's short common-word phrases, whose other sense is as
#: familiar as the discipline one (``online learning`` also names
#: internet-based education; ``tree of life`` the mythological motif). Like
#: a set word, a phrase is never proposed as an alias and never a bare
#: filename; a target that introduces one in italics accepts it as a label.
CROSS_DOMAIN_PHRASES = frozenset({
    "online learning",
    "tree of life",
})

#: Appended to an item-17 alias-candidate message for a single-word candidate
#: of a disambiguated or cross-domain subject (special-titles.md cross-domain
#: tests).
BARE_WORD_ALIAS_HINT = (
    "a single-word synonym of a disambiguated or cross-domain subject stays "
    "out unless the cross-domain tests show it names only this subject")


def bare_common_noun_slug(slug):
    """Whether a filename stem is a bare term from the cross-domain floor.

    A hyphen-free stem is bare when it is a :data:`COMMON_NOUNS` word; a
    hyphenated one when it spells a :data:`CROSS_DOMAIN_PHRASES` phrase
    (``tree-of-life``). A regular plural of the word, or of the phrase's last
    word, is folded (``kernels``, ``online-learnings``). A qualified stem
    (``tree-of-life-biology``) is not bare.
    """
    slug = (slug or "").replace(" ", "-")
    keys = singular_keys(slug) if slug else set()
    return bool({key for key in keys if "-" not in key} & COMMON_NOUNS
                or {key.replace("-", " ") for key in keys}
                & CROSS_DOMAIN_PHRASES)


def cross_domain_alias_findings(aliases):
    """Aliases that are cross-domain floor terms, which are never aliases."""
    return [a for a in aliases or ()
            if a and bare_common_noun_slug(portable_identity(str(a)))]


def bare_word_alias_candidate(candidate_slug, title, surface=""):
    """Whether a one-word alias candidate needs the cross-domain hint.

    It does when the title carries a disambiguator or the word itself is a
    named cross-domain term. An acronym such as ``TPR`` (a ``surface`` with no
    lowercase letter) is not a bare common word.
    """
    if surface and not re.search(r"[a-z]", surface):
        return False
    return ("-" not in (candidate_slug or "")
            and (has_parenthetical(title or "")
                 or candidate_slug in COMMON_NOUNS))


def cross_domain_word(text):
    """The cross-domain floor term a surface folds to, else "".

    A one-word surface folds to its :data:`COMMON_NOUNS` word, with case and
    a regular plural folded (``Targets`` -> ``target``). A multiword or
    hyphenated surface folds only to a :data:`CROSS_DOMAIN_PHRASES` phrase,
    its last word's plural folded too (``Online-learning`` -> ``online
    learning``). Any other surface folds to "". Such a term never becomes an
    alias; a link may still use it as a context-resolved label
    (:func:`cross_domain_synonym_label`).
    """
    tokens = _label_tokens(text)
    if not tokens:
        return ""
    if len(tokens) == 1:
        words = singular_forms(tokens[0]) & COMMON_NOUNS
        return min(words) if words else ""
    head = " ".join(tokens[:-1])
    phrases = {head + " " + form
               for form in singular_forms(tokens[-1])} & CROSS_DOMAIN_PHRASES
    return min(phrases) if phrases else ""


# ---------------------------------------------------------------------------
# item 6: API surface in a non-Software entry
# ---------------------------------------------------------------------------

#: Libraries named by the API-surface failure strings.
LIBS = ["PyTorch", "TensorFlow", "JAX", "NumPy", "Pandas", "scikit-learn",
        "sklearn", "Keras", "SciPy", "Matplotlib", "Hugging Face", "XGBoost",
        "LightGBM", "CatBoost"]

_LIB_ALT = "|".join(re.escape(lib) for lib in LIBS)
_API_FAILURE_STRINGS = [
    (rf"\bIn ({_LIB_ALT})\b", "In-<library> framing"),
    (rf"\b({_LIB_ALT})\s+(provides|offers|exposes|has)\b",
     "<library> provides/offers framing"),
    (r"\bbuilt with `", "'built with `…`' how-to signpost"),
    (r"\bconstructed (with|via) `",
     "'constructed with/via `…`' how-to signpost"),
    (r"\bcreated (with|by) `", "'created with/by `…`' how-to signpost"),
    (r"\bavailable (through|via|in) `",
     "'available through `…`' how-to signpost"),
    (r"\buse `[^`]+` to\b", "'use `…` to' how-to signpost"),
    (r"\bflag enables\b", "kwarg/flag documentation"),
    (r"`[A-Za-z_][A-Za-z0-9_]*\s*=",
     "backticked kwarg/default-value (`name=`)"),
    (r"`(True|False|None)`", "Python language literal in code form"),
]
_CODE_IDENTIFIER_TITLE_RE = re.compile(r"^[A-Za-z_][\w]*(\.[A-Za-z_][\w]*)+$")
_SPECIAL_TOKEN_LITERAL_RE = re.compile(r"\[[^\]\n]+\]")


def _file_extension_literal(token):
    """A bare file extension such as ``.csv``, or a compound one.

    A compound whose first or last part is a known extension (``.tar.gz``,
    ``.tar.zst``, ``.nii.gz``, ``.d.ts``) passes; a dotted chain such as
    ``.str.lower`` stays an identifier.
    """
    if not re.fullmatch(r"(?:\.[A-Za-z0-9]+)+", token):
        return False
    parts = [part.lower() for part in token.split(".")[1:]]
    return (len(parts) == 1 or parts[0] in FILE_EXTENSIONS
            or parts[-1] in FILE_EXTENSIONS)


def api_surface_findings(entry_type, title, prose, body):
    """Item 6's mechanical API-surface shapes; empty for a Software entry.

    Checks are ``code-identifier-title``, ``api-string`` (the first library
    framing or how-to signpost, else a code-form ``… or …`` alternative),
    ``fenced-code`` (read from the whole comment-masked ``body``: the fence is
    the finding) and ``backticked-identifiers`` (the zero cap; a file
    extension such as ``.csv`` or ``.tar.gz`` and a bracket special token are
    not identifiers).
    """
    if entry_type == "Software":
        return []
    title = title or ""
    prose = prose or ""
    findings = []
    if _CODE_IDENTIFIER_TITLE_RE.match(title) or "()" in title:
        findings.append({
            "check": "code-identifier-title",
            "message": f'title looks like a code identifier: "{title}"'})
    for pattern, label in _API_FAILURE_STRINGS:
        if re.search(pattern, prose):
            findings.append({"check": "api-string", "label": label,
                             "message": f'API-surface failure string — {label}'})
            break
    else:
        for alternatives in re.finditer(
                r"`([^`\n]+)`\s+or\s+`([^`\n]+)`", prose):
            values = [value.strip() for value in alternatives.groups()]
            if not all(_file_extension_literal(value)
                       or _SPECIAL_TOKEN_LITERAL_RE.fullmatch(value)
                       for value in values):
                label = "`…` or `…` alternative signposts"
                findings.append({
                    "check": "api-string", "label": label,
                    "message": "API-surface failure string — " + label})
                break
    # Both fence spellings: markdown opens a block with ``` or ~~~.
    if re.search(r"(?m)^\s*(?:`{3}|~{3,})", mask_body_comments(body or "")):
        findings.append({
            "check": "fenced-code",
            "message": "fenced code block — mechanically allowed only after "
                       "genuine Software classification; reclassification "
                       "does not waive Software's artifact-wide relevance "
                       "gate"})
    inline = re.findall(r"`([^`\n]+)`",
                        re.sub(r"`{3}.*?`{3}", " ", prose, flags=re.S))
    identifiers = [token.strip() for token in inline if token.strip()
                   and not _file_extension_literal(token.strip())
                   and not re.fullmatch(r"\[.+\]", token.strip())]
    if identifiers:
        findings.append({
            "check": "backticked-identifiers", "identifiers": identifiers,
            "message": f'{len(identifiers)} backticked identifier(s) (cap is 0 '
                       "in a non-Software entry; Software may retain only "
                       "artifact-wide design/interface API, never a usage "
                       f'catalog): {", ".join(identifiers[:6])}'})
    return findings


# ---------------------------------------------------------------------------
# item 7: the description's subject
# ---------------------------------------------------------------------------

_LEADING_ARTICLE_RE = re.compile(r"^(?:a|an|the)\s+", re.IGNORECASE)
_SUBJECT_BOUNDARY_RE = re.compile(r"^(?:$|[\s,(:;\u2013\u2014])")


def description_has_entity_subject(description, title):
    """Conservative mechanical floor for the entity-as-subject rule.

    The description must begin with one of ``description_subject_forms``
    (the title, a disambiguated title's base term, a mathematical title's
    plain form), compared case-insensitively on the first letter only and
    ending at a subject boundary. A disambiguated title in full is not a
    running-prose subject. A leading article is optional only when it is not
    already part of the canonical name: "The Iliad" stays valid without
    accepting "The The Iliad". A blank description or title passes, because
    presence and title validity have their own findings.
    """
    if not description or not title:
        return True
    forms = description_subject_forms(title)
    starts = [description.strip()]
    article = _LEADING_ARTICLE_RE.match(starts[0])
    if article and not any(_LEADING_ARTICLE_RE.match(form) for form in forms):
        starts.append(starts[0][article.end():])
    for text in starts:
        if has_parenthetical(title):
            full = text[:len(title)]
            if (first_letter_ci_equal(full, title)
                    and _SUBJECT_BOUNDARY_RE.match(text[len(title):])):
                continue
        for form in forms:
            if (first_letter_ci_equal(text[:len(form)], form)
                    and _SUBJECT_BOUNDARY_RE.match(text[len(form):])):
                return True
    return False


def description_subject_findings(description, title):
    """Item 7: the description-subject finding for one entry, or ``[]``."""
    if description_has_entity_subject(description, title):
        return []
    forms = description_subject_forms(title)
    return [{
        "check": "description-subject",
        "message": ("description subject must begin with the canonical title "
                    "or base term (an optional leading article is allowed); "
                    "expected one of: %s"
                    % ", ".join('"%s"' % form for form in forms)),
        "evidence": {"description": description, "expected_subjects": forms},
    }]


# ---------------------------------------------------------------------------
# item 9: an acronym title's expansion
# ---------------------------------------------------------------------------

#: One token of capital letters and digits, optionally hyphenated (``MNIST``,
#: ``GPT-3``); the caller also requires two capitals.
_ACRONYM_TITLE_RE = re.compile(r"[A-Z0-9]+(?:-[A-Z0-9]+)*")

#: An expansion parenthetical directly after the bold, past the noun
#: ``algorithm`` and a date parenthetical as in :data:`BOLD_PAREN_RE`.
_EXPANSION_AFTER_BOLD_RE = re.compile(
    r"(?:\s+algorithm)?\s*"
    r"(?:\((?:[?0-9]|b\.|c\.|fl\.|annual\b|ongoing\b)[^()\n]*\)\s*)?"
    r"\([A-Za-z*_]", re.IGNORECASE)


def acronym_expansion_missing(title, opener):
    """Item 9: whether an acronym-titled entry's opener omits its full form.

    wiki-build writing.md principle 5(f) opens an acronym-titled entry with
    its expansion in parentheses directly after the bolded title, past a
    Person or Event date: ``**DBSCAN** (Density-Based Spatial Clustering of
    Applications with Noise)``. The floor applies only when the title, or a
    disambiguated title's base term, is one token of capital letters and
    digits, optionally hyphenated, with at least two capitals and no
    lowercase letter (``MNIST``, ``ATP``; not ``ROC curve``, ``MLOps`` or
    ``SARS-CoV-2``). ``opener`` is the opening paragraph, hard wraps allowed.
    It reports only an opener that bolds the title, since a missing or
    different bold is the bold-opener check's finding, and it does not judge
    the parenthetical's wording.
    """
    title = (title or "").strip()
    term = base_term(title) if has_parenthetical(title) else title
    if (not _ACRONYM_TITLE_RE.fullmatch(term)
            or sum(1 for ch in term if ch.isupper()) < 2):
        return False
    opening = " ".join(line.strip() for line in (opener or "").splitlines())
    bolds = [match for match in BOLD_OUTER_RE.finditer(opening)
             if first_letter_ci_equal(
                 math_title_plain_text(bold_parts(match)[0].strip()), term)]
    return bool(bolds) and not any(
        _EXPANSION_AFTER_BOLD_RE.match(opening, match.end()) for match in bolds)


# ---------------------------------------------------------------------------
# item 13: stacked-merge scars
# ---------------------------------------------------------------------------

# `importance` is a legacy key, so a legacy entry's stacked-merge scar can
# still be an `importance:` line stranded in the body. `read:` and `issues:`
# end the schema, so a partial scar plausibly leaves exactly a `read: false`
# or `issues: ""` line. Listings are masked before these run, so leading
# whitespace is a list item's indentation, and a line or display indented
# inside an item is read like a top-level one.
_SCHEMA_KEY_LINE_RE = re.compile(
    r"(?m)^[ \t]*(title|type|aliases|sources|created|updated|description|"
    r"tags|importance|parents|read|issues):")
_DISPLAY_MATH_BLOCK_RE = re.compile(
    r"(?ms)^[ \t]*\$\$[ \t]*(?:\n.*?\n|.*?)[ \t]*\$\$[ \t]*$")
_DIGIT_LINE_RE = re.compile(r"(?m)^[^\S\n]*[0-9]+[^\S\n]*$")


def _line_of(text, offset):
    return text.count("\n", 0, offset) + 1


def merge_scar_findings(prose):
    """Item 13's body scars: a schema key, a stray ``---`` or a digit line.

    Listings are masked first: a Software entry legitimately shows YAML in a
    fence, and deleting a line from the entry's own example is destructive.
    ``prose`` ends before the Related footer, or before the structural
    separator above Flashcards when the footer is missing. Each finding's
    ``line`` is one-based within ``prose``.
    """
    scan = strip_code(prose or "")
    lines = scan.split("\n")
    findings = []
    key = _SCHEMA_KEY_LINE_RE.search(scan)
    if key:
        findings.append({
            "check": "frontmatter-key", "line": _line_of(scan, key.start()),
            "message": "stray frontmatter key in the body — stacked-merge "
                       "scar; remove it"})
    stray = [index for index, line in enumerate(lines)
             if re.fullmatch(r"\s*---\s*", line)
             and not (index > 0 and lines[index - 1].strip()
                      and not markdown_block_start(lines[index - 1]))]
    if stray:
        findings.append({
            "check": "stray-rule", "line": stray[0] + 1,
            "message": "stray `---` fence in explanatory body prose — "
                       "stacked-merge scar; the only body separator belongs "
                       "between Related and Flashcards"})
    kept = _DISPLAY_MATH_BLOCK_RE.sub(
        lambda match: "\n" * match.group(0).count("\n"), scan)
    digit = _DIGIT_LINE_RE.search(kept)
    if digit:
        findings.append({
            "check": "digit-line", "line": _line_of(kept, digit.start()),
            "message": "standalone bare digit line in explanatory body prose "
                       "— stacked-merge scar; remove it or restore the content "
                       "it was detached from"})
    return findings


# ---------------------------------------------------------------------------
# item 9: list-item indentation
# ---------------------------------------------------------------------------

_LIST_MARKER_RE = re.compile(
    r"(?P<indent>[ \t]*)(?P<marker>[-*+]|(?P<number>[0-9]{1,9})[.)])"
    r"(?P<gap>[ \t]+|$)")
_LIST_RULE_RE = re.compile(
    r"[ \t]*(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})")
_LIST_HEADING_RE = re.compile(r"[ \t]*#{1,6}(?:[ \t]|$)")
_LIST_QUOTE_RE = re.compile(r"[ \t]*>")


def _list_width(line):
    """The column of a line's first character, a tab counting four."""
    return len(line[:len(line) - len(line.lstrip(" \t"))].expandtabs(4))


def _list_item(line, open_items, interrupts, resumable=None):
    """The list item ``line`` opens inside ``open_items``, or ``None``.

    Each item is a dict: ``indent`` (the marker's column), ``content`` (its
    text column: the marker plus one to four spaces), ``kind`` (the bullet
    character, or the ordered delimiter) and ``number``. A marker indented
    four or more columns past the open text column is text, as one is at
    the top level. When ``interrupts`` (the line follows paragraph text) and
    the line reaches the innermost open text column, so that it could
    continue that text, an ordered marker other than 1 opens no new list, as
    in CommonMark, unless it continues an open item's list or that of
    ``resumable``, the item a misplaced block closed.
    """
    match = _LIST_MARKER_RE.match(line)
    if not match or _LIST_RULE_RE.fullmatch(line):
        return None
    indent = _list_width(line)
    column = open_items[-1]["content"] if open_items else 0
    if indent >= column + 4:
        return None
    marker, number = match.group("marker"), match.group("number")
    number = int(number) if number is not None else None
    if (interrupts and indent >= column and number not in (None, 1)
            and not any(item["indent"] == indent and item["kind"] == marker[-1]
                        for item in open_items + [resumable] if item)):
        return None
    gap = (len(line[:match.end()].expandtabs(4)) - indent - len(marker))
    if not line[match.end():].strip() or gap > 4:
        gap = 1
    return {"indent": indent, "content": indent + len(marker) + gap,
            "kind": marker[-1], "number": number}


def list_indent_findings(prose, display_spans=(), table_spans=None):
    """Item 9: a list item's display or paragraph left outside its item.

    A display block or a continuation paragraph belongs to the list item
    above it when its ordered list resumes after it with that item's next
    number, or, when the gap opens with a display, the same number again.
    A display also belongs to the item when the item's text before it ends
    with a colon and the display ends the whole list; inside an outer item
    it ends only a nested list, and the numbered list goes on. Indented
    less than the item's text column (3 spaces after ``1.``, 4 after
    ``10.``), the block ends the list in Obsidian, so the remedy is to
    indent it. A nested list belongs to the item when its first marker sits
    past the item's marker but short of its text column, with another
    bullet or delimiter or numbered from 1 again: CommonMark starts a new
    list there, which ends the item's list, or numbers it as the list's
    next items.

    ``display_spans`` are the paired displays of the code-masked prose, as
    ``equation_coverage.find_display_spans`` returns them for the equation
    checks, and ``table_spans`` its parsed tables (computed when ``None``).
    A listing, table or quote in the gap is not reported, and a heading or
    rule there ends the list on purpose, so of the gap before it only a
    display after the item's colon is reported. A list inside a quote or
    callout is not checked. Each finding's ``line`` and ``item_line`` are
    one-based within ``prose``; ``kind`` is ``display``, ``paragraph`` or
    ``list``; ``indent`` is the block's indentation and ``column`` the
    item's text column, both in spaces.
    """
    lines = strip_code(prose or "").split("\n")
    visible = mask_body_comments(prose or "").split("\n")
    displays = {span["open_line"]: span["close_line"]
                for span in display_spans or ()}
    if table_spans is None:
        table_spans = markdown_table_spans(
            strip_indented(strip_fenced(prose or "")))
    tables = dict(table_spans)
    findings = []
    open_items = []
    state = {"pending": None}

    def report(block, item):
        """Record ``block`` as indented short of ``item``'s text column."""
        findings.append({
            "check": "list-indent", "line": block["line"] + 1,
            "kind": block["kind"], "indent": block["indent"],
            "column": item["content"], "item_line": item["line"] + 1,
            "message": (
                "%s belongs to the list item above it but is indented "
                "%d space%s, short of the item's text column at %d, so "
                "Obsidian renders it outside the item — indent it %d spaces"
                % ({"display": "display block", "list": "nested list"}.get(
                       block["kind"], "continuation paragraph"),
                   block["indent"], "" if block["indent"] == 1 else "s",
                   item["content"], item["content"]))})

    def resolve(colon_only):
        """Report the pending gap's blocks, or only a display after a colon."""
        pending = state["pending"]
        state["pending"] = None
        if pending is None or pending["cancelled"]:
            return
        blocks = [block for block in pending["blocks"] if block["reported"]]
        if colon_only:
            # Inside an outer item, the display ends only a nested list.
            first = pending["blocks"][0]
            if not (pending["colon"] and pending["left"]
                    and first["kind"] == "display" and first["reported"]):
                return
            blocks = [first]
        for block in blocks:
            report(block, pending["item"])

    index, count = 0, len(lines)
    previous, last_text = None, ""
    while index < count:
        line = lines[index]
        if not line.strip() and not visible[index].strip():
            previous = None
            index += 1
            continue
        end, kind = index, "paragraph"
        if not line.strip():
            # A listing line: never reported, but it ends what it outdents.
            kind, line = "listing", visible[index]
        else:
            item = _list_item(
                line, open_items, previous == "paragraph",
                state["pending"] and state["pending"]["item"])
            if item is not None:
                item["line"] = index
                pending = state["pending"]
                if pending is not None:
                    last = pending["item"]
                    sibling = (item["indent"] == last["indent"]
                               and item["kind"] == last["kind"])
                    # A resumed bullet list proves nothing: a display
                    # between two bullet lists may belong to neither.
                    resolve(not sibling or last["number"] is None or not (
                        item["number"] == last["number"] + 1
                        or (item["number"] == last["number"]
                            and pending["blocks"][0]["kind"] == "display")))
                owner = open_items[-1] if open_items else None
                if (owner is not None
                        and owner["indent"] < item["indent"] < owner["content"]
                        and (item["kind"] != owner["kind"]
                             or item["number"] == 1)):
                    # A nested list short of its item's text column starts
                    # a new list, which ends the item's list, or with the
                    # same delimiter from 1 joins it as its next items.
                    report({"line": index, "kind": "list",
                            "indent": item["indent"]}, owner)
                while open_items and item["indent"] < open_items[-1]["content"]:
                    open_items.pop()
                open_items.append(item)
                previous, last_text = "paragraph", line
                index += 1
                continue
            if index in displays:
                end = max(index, displays[index])
                if line.lstrip().startswith("$$"):
                    kind = "display"
            elif index in tables:
                end, kind = tables[index], "table"
                if end + 1 < count and _CAPTION_LINE_RE.match(lines[end + 1]):
                    end += 1  # the table's caption goes with it
            elif _LIST_HEADING_RE.match(line) or _LIST_RULE_RE.fullmatch(line):
                kind = "break"
            elif _LIST_QUOTE_RE.match(line):
                kind = "quote"
            elif previous == "paragraph":
                # A lazy continuation line of the paragraph above.
                last_text = line
                index += 1
                continue
        width = _list_width(line)
        closed = []
        while open_items and width < open_items[-1]["content"]:
            closed.append(open_items.pop())
        block = {"line": index, "kind": kind, "indent": width,
                 "reported": kind in ("display", "paragraph")}
        if closed:
            resolve(True)
            state["pending"] = {
                "item": closed[-1], "blocks": [block],
                "cancelled": kind == "break",
                "colon": last_text.rstrip().endswith(":"),
                "left": not open_items}
        elif state["pending"] is not None:
            pending = state["pending"]
            block["reported"] = (block["reported"]
                                 and width < pending["item"]["content"])
            pending["blocks"].append(block)
            if kind == "break":
                resolve(True)
        previous = "paragraph" if kind == "paragraph" else "other"
        if kind != "listing":
            last_text = lines[end]
        index = end + 1
    resolve(True)
    return findings


# ---------------------------------------------------------------------------
# item 9: a list that disagrees with its lead-in or its Repeat step
# ---------------------------------------------------------------------------

_COUNT_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
                "twelve": 12}
#: A count before a plural noun, up to two modifiers apart: "three steps",
#: "4 main stages". "Two-part" is a compound, not a count.
_LEAD_IN_COUNT_RE = re.compile(
    r"(?<![\w$.,/-])(%s|[2-9]|1[0-2])[ \t]+(?:[a-z][\w'-]*[ \t]+){0,2}?"
    r"([a-z][\w-]*s)\b(?!['-])" % "|".join(_COUNT_WORDS), re.IGNORECASE)
#: A count of part of the list ("the first two steps"), a bound or range
#: ("at least two", "two or more steps") and a measure ("three times")
#: count no items.
_PARTIAL_COUNT_RE = re.compile(
    r"\b(?:first|last|next|other|remaining|previous|top|further|"
    r"additional|another|every|least|than|to|up|over|about|around|roughly|"
    r"nearly|almost)[ \t]+$", re.IGNORECASE)
_RANGE_WORD_RE = re.compile(r"[ \t](?:or|to|and)[ \t]", re.IGNORECASE)
_MEASURE_NOUNS = frozenset((
    "times", "seconds", "minutes", "hours", "days", "weeks", "months",
    "years", "decades", "centuries", "orders"))
#: Words ending in s that are no plural noun ("in two as follows:").
_NON_NOUN_WORDS = frozenset((
    "as", "is", "was", "has", "does", "gives", "yields", "follows"))
_REPEAT_STEP_RE = re.compile(r"Repeat\b[^.;:]*?\bsteps?[ \t]+([0-9]{1,9})\b")
_LEAD_IN_MARKUP_RE = re.compile(
    r"\[\[[^\]|\n]*\|([^\]\n]*)\]\]|\[\[([^\]\n]*)\]\]|\$[^$\n]*\$|[*_]+")


def _list_marker(line):
    """A list item's ``indent``, text ``content`` column, ``kind`` (bullet
    or ordered delimiter), ``number`` and ``text``, or ``None``."""
    match = _LIST_MARKER_RE.match(line)
    if (not match or _LIST_RULE_RE.fullmatch(line)
            or not line[match.end():].strip()):
        return None
    indent, marker = _list_width(line), match.group("marker")
    gap = len(line[:match.end()].expandtabs(4)) - indent - len(marker)
    number = match.group("number")
    return {"indent": indent,
            "content": indent + len(marker) + (gap if gap <= 4 else 1),
            "kind": marker[-1], "number": int(number) if number else None,
            "text": line[match.end():].strip()}


def _list_run(lines, start, masked):
    """The top-level items of the list that opens at ``lines[start]``.

    Returns ``(items, ambiguous)``. Each item adds its ``line`` and the
    ``shown`` number Markdown renders. A numbered list that a block short of
    its text column interrupts (``list_indent_findings`` reports the block)
    goes on where it resumes with the next number; a bullet list there
    resumes nothing, so its count is ``ambiguous``.
    """
    head = dict(_list_marker(lines[start]), line=start)
    head["shown"] = head["number"]
    items, content, blank = [head], head["content"], False
    index = start + 1
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            blank, index = True, index + 1
            continue
        width = _list_width(line)
        item = None if index in masked else _list_marker(line)
        if index not in masked and (_LIST_RULE_RE.fullmatch(line) or (
                _LIST_HEADING_RE.match(line) and width < content)):
            break
        if item is not None and item["indent"] <= head["indent"]:
            if not (item["indent"] == head["indent"]
                    and item["kind"] == head["kind"]):
                break
            shown = items[-1]["shown"]
            items.append(dict(item, line=index, shown=(
                item["number"] if shown is None else shown + 1)))
            content, blank, index = item["content"], False, index + 1
            continue
        if blank and item is None and width < content:
            if width < head["indent"]:
                break  # an outer item's text ends a nested list
            resume = None
            for later in range(index, len(lines)):
                text = lines[later]
                if later in masked or not text.strip():
                    continue
                if (_LIST_RULE_RE.fullmatch(text)
                        or _LIST_HEADING_RE.match(text)):
                    break
                marker = _list_marker(text)
                if marker is not None:
                    if (marker["indent"] == head["indent"]
                            and marker["kind"] == head["kind"]):
                        resume = (later, marker)
                    break
            if resume is None:
                break
            later, marker = resume
            if head["number"] is None:
                return items, True
            if marker["number"] != items[-1]["number"] + 1:
                break
            items.append(dict(marker, line=later, shown=marker["number"]))
            content, blank, index = marker["content"], False, later + 1
            continue
        blank, index = False, index + 1
    return items, False


def _lead_in(lines, start, indent, masked):
    """``(line, text)`` of the colon-ended text that opens a list, or
    ``None``: the paragraph or parent item text just above ``start``."""
    above = start - 1
    while above >= 0 and not lines[above].strip() and above not in masked:
        above -= 1
    if (above < 0 or above in masked
            or not lines[above].rstrip().endswith(":")):
        return None
    parts, index = [], above
    while index >= 0 and lines[index].strip() and index not in masked:
        item = _list_marker(lines[index])
        if item is not None:
            if item["indent"] >= indent:
                return None
            parts.append(item["text"])
            break
        if _LIST_HEADING_RE.match(lines[index]):
            break
        parts.append(lines[index].strip())
        index -= 1
    return above, " ".join(reversed(parts))


def _lead_in_count(text):
    """The one count of items in a lead-in's colon sentence, or ``None``."""
    plain = _LEAD_IN_MARKUP_RE.sub(
        lambda match: match.group(1) or match.group(2) or " ", text)
    sentences = split_sentences(plain)
    sentence = sentences[-1] if sentences else ""
    counts = list(_LEAD_IN_COUNT_RE.finditer(sentence))
    if len(counts) != 1:
        return None
    match = counts[0]
    if (_PARTIAL_COUNT_RE.search(sentence[:match.start()])
            or _RANGE_WORD_RE.search(match.group(0))
            or match.group(2).lower() in _MEASURE_NOUNS
            or _NON_NOUN_WORDS & set(match.group(0).lower().split()[1:])):
        return None
    value = match.group(1).lower()
    return _COUNT_WORDS.get(value) or int(value), match.group(0)


def list_mismatch_findings(prose, display_spans=(), table_spans=None):
    """Item 9's review candidates: a list that disagrees with the text that
    refers to it.

    Two checks, each a candidate with a one-based ``line``:

    - ``lead-in-count``: the colon sentence that opens a list states one
      count before a plural noun ("in three steps:"), and the list has a
      different number of top-level items. The noun may count something
      else ("With two classes, it runs as follows:"), so the review keeps
      such a count. The builder's rule counts a final "Repeat from step N"
      item; to avoid misfiring, this check also accepts a count that leaves
      it out. A list in a quote or callout is not checked.
    - ``repeat-step``: a numbered item opening "Repeat from step N" (or
      "Repeat steps N…") names no earlier step of its list.

    ``display_spans`` and ``table_spans`` are as for
    :func:`list_indent_findings`; their lines are never list items.
    """
    lines = strip_code(prose or "").split("\n")
    if table_spans is None:
        table_spans = markdown_table_spans(
            strip_indented(strip_fenced(prose or "")))
    masked = set()
    for span in display_spans or ():
        masked.update(range(span["open_line"], span["close_line"] + 1))
    for first, last in table_spans:
        masked.update(range(first, last + 1))
    findings, seen = [], set()
    for start, line in enumerate(lines):
        head = None if start in seen or start in masked else _list_marker(line)
        if head is None:
            continue
        items, ambiguous = _list_run(lines, start, masked)
        seen.update(item["line"] for item in items)
        lead = _lead_in(lines, start, head["indent"], masked)
        count = _lead_in_count(lead[1]) if lead else None
        repeats = sum(1 for item in items if item["text"].startswith("Repeat"))
        if (count and not ambiguous
                and count[0] not in (len(items), len(items) - repeats)):
            findings.append({
                "check": "lead-in-count", "line": lead[0] + 1,
                "list_line": start + 1, "count": count[0],
                "items": len(items),
                "message": (
                    "the lead-in counts %r but the list below has %d "
                    "top-level items — make a count of the list's items "
                    "match it; keep a count of something else"
                    % (count[1], len(items)))})
        for position, item in enumerate(items):
            match = _REPEAT_STEP_RE.match(item["text"])
            if item["number"] is None or not match:
                continue
            step = int(match.group(1))
            earlier = {number for row in items[:position]
                       for number in (row["number"], row["shown"])}
            if step not in earlier:
                findings.append({
                    "check": "repeat-step", "line": item["line"] + 1,
                    "step": step, "number": item["shown"],
                    "message": (
                        "step %d repeats from step %d, which is not an "
                        "earlier step of its list — point it at the step "
                        "that begins the repeated work"
                        % (item["shown"], step))})
    return findings


#: A prose sentence that opens with a bare imperative and its object.
_IMPERATIVE_OPENER_RE = re.compile(
    r"(?:Train|Run|Fit|Compute|Get|Pick|Choose|Predict|Use)[ \t]+"
    r"(?:a|an|the|each|every|all|this|that|these|those|its|their|some|any|"
    r"another|both|one|%s|[0-9]+)\b" % "|".join(_COUNT_WORDS))
_IMAGE_LINE_RE = re.compile(r"[ \t]*!\[")
#: A wikilink, read as its rendered text: the label, else the target.
_WIKILINK_LABEL_RE = re.compile(r"\[\[(?:([^\]|\n]*)\|)?([^\]\n]*)\]\]")


def register_findings(prose, display_spans=(), table_spans=None, title=None):
    """Item 9's register candidates in the explanatory body.

    ``praise``: a praise word on a body line outside listings and displays
    (``register_hints`` with ``body`` and the entry's ``title``, so a proper
    name or the title is no praise). ``imperative``: a prose sentence
    outside lists, tables, captions and headings that opens with a bare
    imperative from a short list followed by a determiner or number ("Train
    one detector per class"), a definition written as instructions. Each
    finding has a one-based ``line``; a candidate, never a fault.
    """
    lines = strip_code(prose or "").split("\n")
    if table_spans is None:
        table_spans = markdown_table_spans(
            strip_indented(strip_fenced(prose or "")))
    masked = set()
    for span in display_spans or ():
        masked.update(range(span["open_line"], span["close_line"] + 1))
    tables = set()
    for first, last in table_spans:
        tables.update(range(first, last + 1))
    findings = []
    for index, line in enumerate(lines):
        words = [] if index in masked or _IMAGE_LINE_RE.match(line) else (
            register_hints(_WIKILINK_LABEL_RE.sub(r"\2", line), body=True,
                           title=title))
        if words:
            findings.append({
                "check": "praise", "line": index + 1, "words": words,
                "message": (
                    "praise (%s) — state what the subject is or does "
                    "instead" % ", ".join('"%s"' % word for word in words))})
    # A paragraph opens after a blank line or a heading, so a lazy line that
    # continues a list item is never read as prose.
    paragraph, may_open = [], True
    for index, line in enumerate(lines + [""]):
        heading = bool(_LIST_HEADING_RE.match(line))
        prose_line = bool(
            line.strip() and index not in masked and index not in tables
            and not line[:1].isspace() and _list_marker(line) is None
            and not heading and not _LIST_RULE_RE.fullmatch(line)
            and not _LIST_QUOTE_RE.match(line)
            and not _CAPTION_LINE_RE.match(line)
            and not _IMAGE_LINE_RE.match(line))
        if prose_line and (paragraph or may_open):
            paragraph.append((index, " ".join(line.split())))
            continue
        compact = " ".join(text for _row, text in paragraph)
        cursor = 0
        for sentence in split_sentences(compact):
            cursor = max(compact.find(sentence, cursor), cursor)
            match = _IMPERATIVE_OPENER_RE.match(sentence)
            if match:
                offset = 0
                for row, text in paragraph:
                    offset += len(text) + 1
                    if offset > cursor:
                        break
                findings.append({
                    "check": "imperative", "line": row + 1,
                    "words": match.group(0),
                    "message": (
                        "a prose sentence opens with the imperative %r, a "
                        "definition written as instructions — state it as "
                        "a fact; imperatives belong in numbered steps"
                        % match.group(0))})
            cursor += len(sentence)
        paragraph, may_open = [], heading or not line.strip()
    return sorted(findings, key=lambda row: row["line"])


# ---------------------------------------------------------------------------
# item 14: source-meta phrasing
# ---------------------------------------------------------------------------

#: Source-meta patterns for every entry type.
SOURCE_META_PATTERNS = (
    r"\bthis paper\b", r"\bthe chapter\b", r"\bthis (?:chapter|section)\b",
    # “source code” names software material, not the document; the other
    # technical compounds (“the source domain/node/sentence”) name a concept's
    # own source side, and “the source of” names an origin (the source of a
    # river). The carve-out is symmetric for “the” and “this,” including the
    # ordinary hyphenated spelling. Text, file, material and document stay
    # source-meta.
    r"\b(?:the|this) source\b(?!\s+of\b)(?!\s*(?:-| )\s*(?:code|domain"
    r"|language|sentence|sequence|node|vertex|vertices|distribution|task"
    r"|signal|term)s?\b)",
    r"\bas (?:mentioned|discussed|noted|shown|described) "
    r"(?:above|below|earlier|previously|later)\b",
    r"\b(?:in )?the previous section\b", r"\bas we saw\b",
    r"\bthe figure (?:above|below)\b",
)
#: In a Work entry, “the paper”, “the book” or “the article” (also “this book”
#: or “this article”) can name the entry's own subject, so these are
#: source-meta only outside Work entries. Finance's book value and
#: book-to-market ratio are not the document.
NON_WORK_META_PATTERNS = (
    r"\bthe paper\b",
    r"\bthe book\b(?![\s-]+(?:value|values|to-market)\b)",
    r"\bthe article\b",
    r"\bthis book\b(?![\s-]+(?:value|values|to-market)\b)",
    r"\bthis article\b")

_WIKILINK_START_RE = re.compile(r"\[\[[^\[\]\n]+\]\]")
_EMPHASIZED_TITLE_RE = re.compile(r"([*_]{1,3})[^*_\n]+\1")
# A capitalized name or acronym such as SGDR or GPT-3, not a determiner.
_NAME_TOKEN_RE = re.compile(r"(?!(?:The|This|These|That|Those|A|An)\b)[A-Z]\w*")


def _names_linked_or_emphasized_work(named):
    """Single-entry floor: a link, emphasized title, or capitalized name or
    acronym (``the authors of SGDR``) follows ``the author(s) of``."""
    return bool(_WIKILINK_START_RE.match(named)
                or _EMPHASIZED_TITLE_RE.match(named)
                or _NAME_TOKEN_RE.match(named))


def source_meta_findings(prose, entry_type, names_work=None):
    """Item 14: the first source-meta phrase, else a bare ``the author(s)``.

    ``names_work(named)`` decides whether the text after one ``the author(s)
    of`` names an existing entry, such as a Work or a named method. The vault
    scanner resolves the entry; the single-entry default accepts ``the
    author(s) of`` followed by a wikilink, an emphasized title, or a
    capitalized name or acronym, which it cannot verify.
    """
    patterns = list(SOURCE_META_PATTERNS)
    if entry_type != "Work":
        patterns.extend(NON_WORK_META_PATTERNS)
    text = strip_code(prose or "")
    for pattern in patterns:
        found = re.search(pattern, text, re.I)
        if found:
            return [{"check": "phrase", "pattern": pattern,
                     "text": found.group(0),
                     "message": f'source-meta phrasing "{found.group(0)}"'}]
    names_work = names_work or _names_linked_or_emphasized_work
    authors = re.finditer(r"\bthe authors?\b(\s+of\s+)?", text, re.IGNORECASE)
    if any(not (match.group(1) and names_work(text[match.end():]))
           for match in authors):
        return [{"check": "authors",
                 "message": "source-meta phrasing uses bare `the author(s)` "
                            "rather than naming an existing entry"}]
    return []


# ---------------------------------------------------------------------------
# item 16: emphasis
# ---------------------------------------------------------------------------

# One outer-bold reader for all title shapes (entry_structure's).  The inner
# expression admits an italic span, so it reads ordinary ``**Title**``,
# combined ``***Latin binomial***``, and the mixed taxon/strain form
# ``***E. coli* K-12**`` as one bold span instead of starting at the wrong
# pair of asterisks.
BOLD_OUTER_RE = _BOLD_OUTER_RE
_ANYLINK_RE = re.compile(r"!?\[\[[^\]]*\]\]")
_INLINE_CODE_RE = re.compile(r"(`+)[^\n]*?\1(?!`)")
_CAPTION_LINE_RE = re.compile(r"^\s*\*(?!\*).*\*\s*$")
# A bolded bullet anchor may be followed by a short parenthetical or bracketed
# qualifier (optionally italicized) before the delimiter, as in wiki-build's
# `- **True positives** (TP) — positives correctly predicted as positive`.
# The anchor itself is read like the outer bold, so an italic taxon
# (`- ***Mus musculus*** —`) is an anchor too.
_BULLET_ANCHOR_RE = re.compile(
    r"^\s*[-*]\s+\*\*" + BOLD_TEXT + r"\*\*(?!\*)"
    r"(?:\s*[*_]?[\(\[][^)\]\n]{1,60}[\)\]][*_]?)*\s*[—–:\-]")
_SINGLE_SPAN_RE = re.compile(r"\[\[[^\]]*\]\]|\$[^$]+\$|`[^`]+`")
_EMPHASIS_SPAN_RE = re.compile(
    r"(\*\*|\*)(\[\[[^\]\n]*\]\]|\$[^$\n]+\$|`[^`\n]+`)(\*\*|\*)")


def bold_parts(match):
    """Return ``(visible_text, style, italic_prefix)`` for an outer bold.

    ``style`` is ``plain``, ``full-italic``, or ``mixed``.  The mixed form is
    the only legal spelling for a taxon followed by a plain strain designator.
    """
    raw = match.group(1)
    if raw.startswith("*"):
        close = raw.find("*", 1)
        if close > 1:
            italic = raw[1:close]
            suffix = raw[close + 1:]
            return (italic + suffix,
                    "full-italic" if not suffix else "mixed", italic)
    return raw, "plain", None


def unenumerated_bold_findings(prose, table_spans=()):
    """Item 16: bold outside the title, bullet anchors and ``**Related:**``.

    The opener's first bold is the title slot (the opener check owns its
    form). The opener is the first prose paragraph, so a leading comment does
    not end it and a leading heading or display block does not take the
    slot. Whole-line italic captions belong to item 12. Wikilinks are masked
    so markup in a display label stays item 18's finding, and bold around a
    single link, math or code span is left to ``emphasis_span_findings``.
    """
    masked = mask_line_spans(strip_code(prose or ""), table_spans)
    masked = _ANYLINK_RE.sub(lambda match: " " * len(match.group(0)), masked)
    opener = first_prose_paragraph_lines(prose) or (0, 0)
    findings = []
    opener_skipped = False
    for index, line in enumerate(masked.split("\n")):
        in_opener = opener[0] <= index < opener[1]
        if _CAPTION_LINE_RE.match(line) or _BULLET_ANCHOR_RE.match(line):
            continue
        for bold in BOLD_OUTER_RE.finditer(line):
            if in_opener and not opener_skipped:
                opener_skipped = True
                continue
            span = bold_parts(bold)[0].strip()
            if not span or span == "Related:":
                continue
            if _SINGLE_SPAN_RE.fullmatch(span):
                continue
            findings.append({
                "check": "unenumerated-bold", "span": span, "line": index + 1,
                "message": f'unenumerated bold "**{span}**" — bold is only for '
                           "the title, `- **Term** (qualifier) —` bullet "
                           "anchors, and **Related:** (use italics or a "
                           "wikilink)"})
    return findings


def emphasis_span_findings(prose, related="", table_spans=(),
                           opener_markup=None):
    """Item 16: bold or italic wrapped around a wikilink, math or code span.

    The markup itself already styles the span. ``opener_markup`` is the exact
    opener bold of a title made from one inline-math span (see
    ``pure_math_opener_markup``): its first occurrence in the opener, the
    first prose paragraph, is the one allowed exception. Code contents are
    blanked but their delimiters kept, so emphasis shown inside a code sample
    is not rendered emphasis.
    """
    prose = prose or ""
    zones = (mask_line_spans(strip_indented(strip_fenced(prose)), table_spans)
             + "\n" + (related or ""))
    zones = _INLINE_CODE_RE.sub(
        lambda match: (match.group(1)
                       + " " * (len(match.group(0)) - 2 * len(match.group(1)))
                       + match.group(1)),
        zones)
    line_starts = [0] + [match.end() for match in re.finditer(r"\n", zones)]
    opener = first_prose_paragraph_lines(prose) or (0, 0)
    opener_start, opener_limit = (
        line_starts[min(line, len(line_starts) - 1)] for line in opener)
    findings = []
    for match in _EMPHASIS_SPAN_RE.finditer(zones):
        if match.group(1) != match.group(3):
            continue
        inner = match.group(2)
        if inner.startswith("[["):
            kind, fix = "wikilink", "the link"
        elif inner.startswith("$"):
            kind, fix = "math", "LaTeX"
        else:
            kind, fix = "code", "backticks"
        if (opener_markup == match.group(0)
                and opener_start <= match.start() < opener_limit):
            opener_markup = None
            continue
        findings.append({
            "check": "emphasis-around-span", "kind": kind,
            "span": inner[:30], "line": _line_of(zones, match.start()),
            "message": f'{"bold" if match.group(1) == "**" else "italic"} '
                       f'around a {kind} ({inner[:30]}) — remove the emphasis; '
                       f'{fix} already provides the styling'})
    return findings


def pure_math_opener_markup(running_title, opener):
    """The opener bold allowed around a title made of one inline-math span.

    ``running_title`` is the title without a disambiguating parenthetical and
    ``opener`` the opening paragraph. Whether that bold spells the title is
    the bold-opener check's finding.
    """
    if not re.fullmatch(r"\$[^$\n]+\$", running_title or ""):
        return None
    bold = BOLD_OUTER_RE.search(opener or "")
    return bold.group(0) if bold else None


# ---------------------------------------------------------------------------
# item 18: wikilink display labels
# ---------------------------------------------------------------------------

DISPLAY_LINK_RE = re.compile(
    r"\[\[([^\]|#^]+)(?:[#^][^\]|]*)?\|([^\]\n]+)\]\]")


def display_label_markup(display):
    """Markup kinds inside one display label; labels render as plain text."""
    marks = []
    if "$" in display:
        marks.append("$ (LaTeX)")
    if "`" in display:
        marks.append("backtick")
    if "**" in display:
        marks.append("** (bold)")
    elif re.search(r"\*\w[^*]*\*", display):
        marks.append("* (italic)")
    return marks


def display_label_links(text):
    """Every piped wikilink in ``text`` with its label markup.

    ``text`` is the listing- and table-masked body prose plus the
    listing-masked Related footer. Each dictionary has ``target``,
    ``display``, ``marks`` and ``line`` (one-based within ``text``), plus a
    ``message`` when the label carries markup.
    """
    links = []
    for match in DISPLAY_LINK_RE.finditer(text or ""):
        target, display = match.group(1).strip(), match.group(2).strip()
        marks = display_label_markup(display)
        link = {"target": target, "display": display, "marks": marks,
                "line": _line_of(text, match.start())}
        if marks:
            link["message"] = (
                f'wikilink display label "{display[:40]}" has markup '
                f'({", ".join(marks)}) — labels render as plain text; put '
                "math/emphasis in the surrounding prose")
        links.append(link)
    return links


def _label_tokens(text):
    """Lowercased tokens, hyphens as spaces, a parenthetical dropped."""
    text = re.sub(r"\s*\([^)]*\)\s*", " ", (text or "").lower())
    return re.findall(r"[a-z0-9]+", text.replace("-", " "))


def _token_stem(token):
    """Crude inflection stem: tuning/tuned/tunes/tune -> tun."""
    for suffix in ("ing", "ed", "es", "s"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            token = token[: -len(suffix)]
            break
    if token.endswith("e") and len(token) >= 4:
        token = token[:-1]
    return token


def _tokens_match(a, b):
    """Inflection- and truncation-tolerant token equality.

    The four-character common-prefix floor alone misses short e-drop verb
    stems ("tuned" and "tuning" share only "tun"), so equal stems also match;
    a genuinely different word ("tuner", "transfer") still does not.
    Irregular plurals ("taxa", "genera") match through the shared plural
    table.
    """
    if (a in b or b in a or len(os.path.commonprefix([a, b])) >= 4
            or singular_forms(a) & singular_forms(b)):
        return True
    stem_a, stem_b = _token_stem(a), _token_stem(b)
    return len(stem_a) >= 3 and stem_a == stem_b


def label_shares_surface(display, surfaces):
    """Whether a display label shares a surface with a title or alias.

    A label passes when, for some surface, its tokens are a subset of the
    surface (a bare display of a qualified link, an inflection) or a superset
    of it (a more specific display that adds a qualifier). An exact-match
    test false-flags both, and "fixing" a bare display by adding the bare
    alias is the cross-domain collision wiki-build exists to prevent. Do not
    re-tighten it to exact match or add a single-token strict-subset guard,
    which re-flags bare terms. A label with no word tokens passes.
    """
    label = _label_tokens(display)
    if not label:
        return True
    for surface in surfaces:
        # A math title also counts in its plain form ("chi-squared test").
        for variant in {surface, math_title_plain_text(surface)}:
            form = _label_tokens(variant)
            if not form:
                continue
            subset = all(any(_tokens_match(d, t) for t in form) for d in label)
            superset = all(any(_tokens_match(d, t) for d in label)
                           for t in form)
            if subset or superset:
                return True
    return False


def _head_word(term):
    """The head word of a title's base term.

    The last word, or the word before a standalone "of" ("Law of large
    numbers" -> "Law"); a hyphenated compound such as "Out-of-bag evaluation"
    keeps its final word as the head.
    """
    words = [word for word in re.split(r"[\s/]+", term.strip()) if word]
    lowered = [word.lower() for word in words]
    if "of" in lowered[1:]:
        return words[lowered.index("of", 1) - 1]
    return words[-1] if words else ""


_ITALIC_TERM_RE = re.compile(r"(?<![*\w])\*(?!\*)([^*\n]+?)(?<!\s)\*(?![*\w])")


def label_drops_head(display, title, aliases=(), target_prose=""):
    """The title's head word when a label keeps only its modifiers, else "".

    :func:`label_shares_surface` must accept any token subset of a title so
    that cross-domain bare terms (``[[information-entropy|entropy]]``) pass,
    which also lets through a label built only from the title's modifiers:
    ``[[greedy-algorithm|greedy]]``, ``[[bias-variance-trade-off|bias/variance]]``
    or ``[[model-organism|model]]``. Such a label names something other than
    its target. It is reported when every label token belongs to the title's
    base term and none matches the head word. Inflected and derived forms of
    the head count as the head (``eukaryotic`` for Eukaryote, ``binary
    classifier`` for Binary classification). A label that is one of the
    target's aliases, or a term the target's ``target_prose`` defines in
    italics (Ensemble learning's *ensemble*), is never reported.
    """
    label = _label_tokens(display)
    term = base_term(title) if has_parenthetical(title) else (title or "")
    form = _label_tokens(term)
    if not label or len(form) < 2:
        return ""
    if not all(any(_tokens_match(d, t) for t in form) for d in label):
        return ""
    head = _head_word(term)
    head_tokens = _label_tokens(head)
    if any(_tokens_match(d, h) for d in label for h in head_tokens):
        return ""
    defined = [match.group(1) for match in
               _ITALIC_TERM_RE.finditer(target_prose or "")]
    for alias in list(aliases or ()) + defined:
        alias_tokens = _label_tokens(alias)
        if (alias_tokens and len(alias_tokens) == len(label)
                and all(any(_tokens_match(d, a) for a in alias_tokens)
                        for d in label)):
            return ""
    return head


def cross_domain_synonym_label(display, surfaces, target_prose=""):
    """Whether a label is a cross-domain synonym that its target introduces.

    wiki-build writing.md's first display-label carve-out keeps a bare
    cross-domain word as a context-resolved label, never an alias. A bare
    word of the title (``[[information-entropy|entropy]]``) already passes
    :func:`label_shares_surface`; this covers the other form, a one-word
    synonym from :data:`COMMON_NOUNS` that the target's own ``target_prose``
    sets in italics: ``[[label-machine-learning|targets]]`` where Label
    (machine learning) says "The word *target* is a near-synonym". A label
    sharing a surface with the title or an alias in ``surfaces`` is not this
    form, and a set word the target does not introduce stays a finding.
    """
    word = cross_domain_word(display)
    if not word or label_shares_surface(display, surfaces):
        return False
    return any(cross_domain_word(match.group(1)) == word
               for match in _ITALIC_TERM_RE.finditer(target_prose or ""))


def plural_surface(title):
    """The plural surface of a title: only the head (last) token inflects.

    ``pluralize`` takes one token, so a whole title would miss every irregular
    in its table ("Confusion matrix" must become "Confusion matrices").
    """
    match = re.search(r"([A-Za-z]+)([^A-Za-z]*)$", title or "")
    if not match:
        return title
    head = match.group(1)
    plural = pluralize(head.lower())
    if head[:1].isupper():
        plural = plural[:1].upper() + plural[1:]
    return title[:match.start(1)] + plural + match.group(2)


def organism_common_name_surfaces(entry_type, title, description, opener):
    """Common names an Organism's description or opening sentence binds.

    ``opener`` is the entry's prose; its first sentence is read. The names are
    link-label surfaces, never global aliases.
    """
    if entry_type != "Organism":
        return []
    title = title or ""
    running_title = base_term(title) if has_parenthetical(title) else title
    names = bound_common_names(running_title, description or "",
                               first_sentence(opener or ""))
    out = []
    for name in names:
        if name.casefold() not in {x.casefold() for x in out}:
            out.append(name)
    return out


def organism_common_name_bound(entry_type, title, description, opener,
                               display):
    """Item 18's Organism carve-out: the entry binds ``display`` to its title.

    A mention elsewhere in the body or a global alias is not enough: the
    description or opening sentence must equate the title with the complete
    common name (singular or plural).
    """
    label = " ".join((display or "").split())
    if (entry_type != "Organism"
            or not re.fullmatch(r"[^\W\d_](?:[^\W\d_]|['’ -]){0,49}", label)):
        return False
    valid = set()
    for surface in organism_common_name_surfaces(
            entry_type, title, description, opener):
        valid.add(surface.casefold())
        valid.add(plural_surface(surface).casefold())
    return label.casefold() in valid


# ---------------------------------------------------------------------------
# item 19: the card set and the primary flashcard
# ---------------------------------------------------------------------------

def is_discipline_root(slug, tags, disciplines):
    """Whether an entry is a discipline root: ``<discipline>.md`` whose only
    tag is ``#<discipline>``.

    ``slug`` is the filename stem, ``tags`` the entry's tag values exactly as
    parsed (pass none when the tags could not be read reliably) and
    ``disciplines`` the caller's discipline-tag enum. A root needs no
    flashcard (wiki-lint hierarchy.md, *Establish discipline roots*). The
    builder gate and the scanner share this one test, so they agree on roots.
    """
    return (bool(slug) and slug in disciplines
            and list(tags or ()) == ["#" + slug])


def flashcard_set_faults(card_count):
    """Item 19: the card-set finding for a Flashcards section.

    ``card_count`` counts the blocks ``card_block_numbers`` names that have
    three or more lines; any other block keeps its own finding. An entry has
    one ``??`` definition
    card, so every further card is an extra card to remove: a fixable
    finding. Returns the messages lint_entry and the scanner share, so the
    two tools agree. Position is not checked: the primary card is identified
    by its answer (``primary_card_label``), never by its place.
    """
    if card_count <= 1:
        return []
    return [
        "%d cards: an entry has one `??` definition card; keep it, remove "
        "every other card and quote each removed card verbatim, attachments "
        "included, in the report" % card_count]


#: Message prefix for a per-card finding on an extra card, which the card's
#: removal resolves; content after its line 3 that is not a recognized
#: attachment stays and keeps its own finding, unless it holds card syntax
#: (``sr_card_syntax_fault``). Both tools use it.
EXTRA_CARD_PREFIX = ("extra card %d (remove this extra card; it needs no "
                     "other repair): ")


def _near_primary(rows, term, counterpart):
    """The rows whose line-3 term normalizes to the primary answer."""
    keys = {normalized_answer_surface(value)
            for value in (term, counterpart) if value} - {""}
    return [row for row in rows if normalized_answer_surface(
        re.sub(r" \([^()\n]+\)$", "", row[1].strip())) in keys]


def primary_card_label(rows, term, counterpart):
    """Item 19: the label of the entry's primary card, or None.

    ``rows`` have ``primary_line3_faults``' shape. One row is the primary
    card. Otherwise the primary card is the first row that meets the answer
    contract, else the one near miss ``primary_line3_faults`` reports. With
    no such card the result is None: the no-primary finding asks to rewrite
    the first card into the definition card and remove the rest, so
    ``kept_card_label`` keeps the first card and every complete card after
    it is an extra. Every complete card but the kept one is an extra card to
    remove, and its per-card findings carry ``EXTRA_CARD_PREFIX``.
    """
    if len(rows) == 1:
        return rows[0][0]
    passing = next((row[0] for row in rows if not row[2]), None)
    if passing is not None:
        return passing
    near = _near_primary(rows, term, counterpart)
    return near[0][0] if len(near) == 1 else None


def kept_card_label(rows, term, counterpart):
    """Item 19: the card a run keeps: the primary card, else, when the entry
    has a primary answer, the first card, which the run rewrites into the
    definition card."""
    label = primary_card_label(rows, term, counterpart)
    return rows[0][0] if label is None and term and rows else label


def primary_line3_faults(card_count, rows, term, counterpart):
    """Item 19: the line-3 faults to report, plus any missing-primary message.

    ``rows`` are ``(card_label, line3, fault_or_None)`` for each card with a
    line 3; ``term`` and ``counterpart`` are the entry's primary answer. With
    one card every fault is reported. With several cards, a passing card is
    the primary one and the extra cards, which are removed, draw no line-3
    fault; otherwise the one card whose line-3 term normalizes to the primary
    answer is reported, or the message asks to rewrite the first card into
    the definition card and remove the rest.
    """
    faults = [row for row in rows if row[2]]
    if card_count <= 1 or not faults:
        return faults, None
    if len(faults) < len(rows):
        return [], None
    near = _near_primary(faults, term, counterpart)
    if len(near) == 1:
        return near, None
    if not term:
        return [], None
    answer = term + (" (%s)" % counterpart if counterpart else "")
    return [], ('no card carries the primary answer "%s"; rewrite the first '
                "card into the definition card, keeping its attachments, and "
                "remove every other card" % answer)


#: The opener's direct parenthetical after the bold title, past any leading
#: date parenthetical: ``**Principal component analysis** (PCA)``,
#: ``**ILSVRC** (2010–2017) (ImageNet Large Scale ...)``. Only the literal noun
#: ``algorithm`` may intervene; a general word window would attach unrelated
#: later parentheticals to the title. introduced_aliases.py reads the same
#: slot as item-17 alias evidence.
BOLD_PAREN_RE = re.compile(
    r"(?<!\*)\*\*(?P<bold>" + BOLD_TEXT + r")"
    r"\*\*(?!\*)(?:\s+algorithm)?\s*"
    r"(?:\((?:[?0-9]|b\.|c\.|fl\.|annual\b|ongoing\b)"
    r"[^()\n]{0,59}\)\s*)?"
    r"\((?P<paren>[A-Za-z*][^()\n]*)\)",
    re.IGNORECASE)

#: A lexical marker LEADING a parenthetical name -- ``(singular,
#: *archaeon*)``, ``(formerly Facebook)``. Annotation, not part of the name:
#: left in place, the candidate came out polluted ("singular, *archaeon*").
PAREN_LEADIN_RE = re.compile(
    r"^(?:(?:short\s+for|originally\s+called|also\s+called|"
    r"also\s+known\s+as|known\s+as)|singular|plural|abbreviated|"
    r"formerly|n[ée]e|or|a\.k\.a\.?)[\s,:]+", re.IGNORECASE)

_SHORT_FOR_PAREN_RE = re.compile(r"^short\s+for[\s,:]+", re.IGNORECASE)

#: A direct italic scientific abbreviation can be the title's own established
#: counterpart: ``***Saccharomyces cerevisiae*** (*S. cerevisiae*)``. This is
#: deliberately narrower than "any italic parenthetical", so an annotated
#: synonym does not become a card counterpart merely because it is also listed
#: in aliases.
_SCI_ABBREV_RE = re.compile(
    r"^[A-Z]\.\s*[a-z][A-Za-z.-]*(?:\s+[a-z][A-Za-z.-]*)*$")

_LINE3_RE = re.compile(r"(?P<term>.*?)(?: \((?P<paren>[^()\n]+)\))?")


def acronym_counterpart(term, candidate):
    """Whether the pair has an acronym/full-form relationship.

    The check is deliberately structural. It rejects arbitrary alternate
    names such as Mark Twain/Samuel Clemens while admitting canonical shapes
    such as PCA, CART, Lasso, MLOps, OOB and t-SNE.
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
        beside a shared tail (OOB evaluation). Requiring at least two written
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
            for short in cand_compact
            for initials in acronym_initial_forms(term))
        or any(related(short, initials)
               for short in term_compact
               for initials in acronym_initial_forms(candidate))
    )
    if initial_match:
        return True
    term_text, candidate_text = lexical_compact(term), lexical_compact(candidate)
    return (
        any(related(short, candidate_text) for short in acronym_tokens(term))
        or any(related(short, term_text) for short in acronym_tokens(candidate))
    )


def _clean_paren_name(raw):
    """The name inside an opener parenthetical, lead-in and markup stripped."""
    value = " ".join((raw or "").split())
    value = PAREN_LEADIN_RE.sub("", value)
    return value.replace("*", "").replace("_", "").strip()


def _card_counterpart(raw, term, organism_parts):
    """The cleaned parenthetical when it is a direct counterpart, else None.

    Three classes qualify: a ``short for`` expansion, an acronym/full-form
    pair, and, for a title proven scientific (``organism_parts``), its direct
    italic one-letter-genus abbreviation. An annotated parenthetical such as
    ``(singular, *archaeon*)`` or ``(originally called *X*)`` is item-17
    alias evidence, not the title's direct binding, so it never belongs on
    card line 3.
    """
    value = " ".join((raw or "").split())
    cleaned = _clean_paren_name(value)
    short_for = bool(_SHORT_FOR_PAREN_RE.match(value))
    scientific_abbreviation = bool(
        organism_parts
        and scientific_abbreviation_matches(cleaned, organism_parts[0])
        and re.fullmatch(r"\*[^*\n]+\*", value.strip())
        and _SCI_ABBREV_RE.fullmatch(cleaned))
    if short_for or scientific_abbreviation or acronym_counterpart(term, cleaned):
        return cleaned
    return None


def flashcard_primary_answer(title, aliases, opener, entry_type=""):
    """Item 19: the entry's own primary answer, ``(term, counterpart)``.

    The term has one exact plain-text spelling: ``title`` verbatim, its base
    term for a disambiguation parenthetical, or its mathematical plain form
    for a symbol title. An opener parenthetical directly after the bold title
    becomes the required counterpart only when it is a direct counterpart
    (see ``_card_counterpart``) and its slug is in ``aliases``: that separates
    an opener-established binding from a date or explanatory aside without
    inferring counterpart semantics from an alias list that can also hold
    synonyms. An Organism's scientific abbreviation counts only when
    ``organism_title_classification`` proves the title scientific.
    ``aliases`` are the entry's list aliases (a malformed scalar field binds
    nothing); ``opener`` is its opening paragraph, hard wraps allowed.
    """
    title = title or ""
    term = base_term(title) if has_parenthetical(title) else title
    term = title_display_form(term)
    aliases = [alias for alias in aliases or () if alias]
    alias_keys = {portable_identity(alias) for alias in aliases}
    opening = " ".join(line.strip() for line in (opener or "").splitlines())
    organism_parts = None
    if entry_type == "Organism":
        status, parts = organism_title_classification(term, aliases, opening)
        organism_parts = parts if status == "scientific" else None
    for match in BOLD_PAREN_RE.finditer(opening):
        visible, _style, _italic = bold_parts(match)
        # Identity is compared in plain form, so a Greek title bolded as
        # LaTeX or spelled out still binds its counterpart.
        if not first_letter_ci_equal(math_title_plain_text(visible),
                                     math_title_plain_text(term)):
            continue
        candidate = _card_counterpart(match.group("paren"), term,
                                      organism_parts)
        if candidate is None:
            continue
        try:
            candidate_key = portable_identity(slug_stem(candidate))
        except SlugError:
            continue
        if candidate_key in alias_keys:
            return term, candidate
    return term, None


def line3_parts(line3):
    """Split card line 3 into its term and optional final parenthetical."""
    line3 = (line3 or "").strip()
    match = _LINE3_RE.fullmatch(line3)
    return ((match.group("term"), match.group("paren")) if match
            else (line3, None))


def flashcard_line3_fault(line3, title, aliases, opener, entry_type=""):
    """Item 19: why card line 3 breaks the primary-answer contract, or None.

    Line 3 is exactly the primary term plus, when the opener establishes
    one, `` (counterpart)``; any other parenthetical is refused. Arguments
    after ``line3`` are ``flashcard_primary_answer``'s.
    """
    expected_term, required = flashcard_primary_answer(
        title, aliases, opener, entry_type)
    term, counterpart = line3_parts(line3)
    if expected_term and term != expected_term:
        return ('the term must be exactly "%s" (same canonical casing)'
                % expected_term)
    if counterpart is not None and required is None:
        return ('the parenthetical "%s" is not an opener-established, '
                "alias-bound counterpart of the title" % counterpart)
    if required is not None and counterpart != required:
        return ("the established counterpart must appear exactly as (%s)"
                % required)
    return None


#: The Spaced Repetition plugin's default single-line card separators in the
#: order it tries them: reversed ``:::``, then basic ``::``.
SR_INLINE_SEPARATORS = (":::", "::")

#: The callout that carries a card's scheduling state under the card.
SR_METADATA_CALLOUT = "> [!sr|card-metadata]"


def _sr_marker_in_code(line, index, marker):
    """The plugin's own code test: odd backtick counts on both sides."""
    return (line[:index].count("`") % 2 == 1
            and line[index + len(marker):].count("`") % 2 == 1)


def sr_inline_marker(line):
    """The single-line separator the Spaced Repetition plugin finds, or None.

    The plugin tries ``:::`` before ``::`` and tests only each separator's
    first occurrence, which does not count inside a backtick span.
    """
    return next((sep for sep in SR_INLINE_SEPARATORS
                 if sep in line and not _sr_marker_in_code(
                     line, line.find(sep), sep)), None)


#: The whitespace JavaScript's trim() removes, which the plugin uses: it differs
#: from Python's default (U+FEFF counts; U+0085 and U+001C-U+001F do not).
_SR_JS_SPACE = ("\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004"
                "\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f"
                "\u3000\ufeff")


def sr_marker_findings(text, multiline=True):
    """Item 19: lines outside the Flashcards section that become cards.

    ``text`` is the raw body before the Flashcards heading (the whole body
    when there is none). The Spaced Repetition plugin parses the whole note
    with its own rules, copied here as of 1.15.4: a line holding a
    single-line separator becomes a card unless the separator's first
    occurrence sits inside a backtick span, or the line lies inside a fence
    opened at column 0. A line that starts with ``<!--`` (not ``<!--SR:``)
    is skipped with the line after it when it holds ``-->``; otherwise the
    plugin skips the rest of the note, card included, which is reported;
    a fence opened at column 0 that no later line starting with the same
    run closes does the same, which is reported too. A line that is only
    ``?`` or ``??`` (its multi-line separators) starts a card once the
    plugin's running card text is longer than one character, as it always
    is after other text in the same paragraph; with ``multiline`` false (no
    Flashcards section was found, so the entry's own card may lie in
    ``text``) such lines are not reported. Obsidian ``%%`` comments and a
    comment later in a line are ordinary text to it, and the scheduling
    state it attaches under such a card is not parsed. Such a card breaks
    the one-card rule, so every hit is certain. Returns ``{check, line,
    marker, message}`` with 1-based lines of ``text``.
    """
    out = []
    lines = (text or "").split("\n")
    index = 0
    # The length of the plugin's running card text: a blank line or a
    # single-line card empties it, and a skipped comment leaves it alone.
    pending = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("<!--") and not line.startswith("<!--SR:"):
            if "-->" not in line:
                out.append({
                    "check": "sr-marker", "line": index + 1, "marker": "<!--",
                    "message": (
                        '"%s" opens an HTML comment at the start of a line '
                        "without closing it there, so the Spaced Repetition "
                        "plugin skips the rest of the note, the definition "
                        "card included; indent the `<!--` by one space "
                        "(Obsidian still hides the comment) or close it on "
                        "this line" % line.strip()[:60])})
                break
            index += 2
            continue
        if not line.strip(_SR_JS_SPACE):
            pending = 0
            index += 1
            continue
        pending += (1 if pending else 0) + len(line.rstrip(_SR_JS_SPACE))
        marker = sr_inline_marker(line)
        if marker:
            pending = 0
            at = line.find(marker)
            before, after = line[max(0, at - 40):at], line[at:at + 42]
            if at > 40:
                before = before.split(" ", 1)[-1]
            if at + 42 < len(line):
                after = after.rsplit(" ", 1)[0]
            out.append({
                "check": "sr-marker", "line": index + 1, "marker": marker,
                "message": (
                    '"%s" holds `%s`, the Spaced Repetition single-line card '
                    "separator, outside a backtick span, so the plugin reads "
                    "the line as an extra card; reword it, write a math `::` "
                    "as `\\mathbin{:}\\mathbin{:}`, and keep code in a "
                    "backtick span or an unindented fence"
                    % ((before + after).strip(), marker))})
            # The plugin attaches the card's scheduling state unparsed: a
            # next-line `<!--SR:` comment, or a callout through its comment.
            rest = lines[index + 1:]
            if rest and rest[0].startswith("<!--SR:"):
                index += 1
            elif rest and rest[0].startswith(SR_METADATA_CALLOUT):
                index += next((n for n, attached in enumerate(rest, 1)
                               if "<!--SR:" in attached), len(rest))
        elif (multiline and pending > 1
              and line.strip(_SR_JS_SPACE) in ("?", "??")):
            out.append({
                "check": "sr-marker", "line": index + 1,
                "marker": line.strip(_SR_JS_SPACE),
                "message": (
                    '"%s" alone on a line is a Spaced Repetition multi-line '
                    "card separator, so the plugin reads its paragraph as an "
                    "extra card; join it to the line before or reword it"
                    % line.strip(_SR_JS_SPACE))})
        elif line.startswith(("```", "~~~")):
            close = re.match(r"`+|~+", line).group(0)
            opened = index
            index += 1
            while index < len(lines) and not lines[index].startswith(close):
                index += 1
            if index >= len(lines):
                out.append({
                    "check": "sr-marker", "line": opened + 1, "marker": close,
                    "message": (
                        '"%s" opens a fence at the start of a line that no '
                        "later line starting with %s closes, so the Spaced "
                        "Repetition plugin skips the rest of the note, the "
                        "definition card included; indent this line by one "
                        "space (Obsidian renders it the same) or start the "
                        "closing fence at the beginning of its line"
                        % (line.strip()[:60], close))})
                break
        index += 1
    return out


def sr_card_marker_faults(card):
    """Item 19: card lines 1 and 3 that hold a single-line separator.

    The plugin reads such a line 1 as a card of its own and the rest of the
    block as a broken second card; such a line 3 becomes a card in place of
    this one. Returns ``(line_number, marker, fault)`` rows, where ``fault``
    completes "flashcard N line K ...".
    """
    out = []
    for number, remedy in (
            (1, "reads line 1 as a card of its own; write a math `::` as "
                "`\\mathbin{:}\\mathbin{:}`"),
            (3, "reads line 3 as a card in place of this one; the answer "
                "line holds no `::`")):
        if len(card) < number:
            continue
        marker = sr_inline_marker(card[number - 1])
        if marker:
            out.append((number, marker, (
                "holds `%s`, the Spaced Repetition single-line card "
                "separator, outside a backtick span, so the plugin %s"
                % (marker, remedy))))
    return out


def sr_card_syntax_fault(block, after=0):
    """Item 19: Flashcards-section content the plugin reviews as a card.

    ``block`` is one block from ``parse_flashcard_blocks``; its first
    ``after`` lines, a card's three content lines, are context only. Past
    them, a ``::`` or ``:::`` outside a backtick span, or a line that is
    only ``?`` or ``??`` after text in its paragraph (``sr_marker_findings``),
    makes the content an extra card to remove, not text to preserve. Returns
    the fault, which completes "block N ..." or "the content after line 3
    ...", or None. Both tools use it.
    """
    marker = next((row["marker"] for row in sr_marker_findings(
        "\n".join(block or ())) if row["line"] > after
        and row["marker"] in SR_INLINE_SEPARATORS + ("?", "??")), None)
    if marker is None:
        return None
    return ("holds `%s`, Spaced Repetition card syntax, so the plugin reviews "
            "it as a card: remove it as an extra card under the card set and "
            "quote it verbatim in the report" % marker)


# ---------------------------------------------------------------------------
# Differential fixtures
# ---------------------------------------------------------------------------

#: Body paragraphs that both linters must flag, inserted after a clean
#: entry's opener: ``(name, paragraph, scan_vault key, lint_entry id,
#: lint_entry needs a folder)``. ``{self}`` is the entry's own slug,
#: ``precision`` a second entry titled "Precision" and ``decision-threshold``
#: a third titled "Decision threshold". Both self-tests run every row, so a
#: shared rule cannot silently drop out of one tool.
SHARED_MUTATIONS = (
    ("item6 library framing", "In PyTorch the rate is a tensor.",
     "item6", "6-api-surface", False),
    ("item6 backticked identifier", "The rate is stored as `rate_value`.",
     "item6", "6-api-surface", False),
    ("item6 fenced code", "```python\nrate = 1\n```",
     "item6", "6-api-surface", False),
    ("item13 body key", "read: false", "item13", "13-merge-scar", False),
    ("item13 stray rule", "---", "item13", "13-merge-scar", False),
    ("item13 digit line", "3", "item13", "13-merge-scar", False),
    ("item14 source phrase", "As shown in the paper, the rate rises.",
     "item14", "14-source-meta", False),
    ("item14 bare authors", "The authors argue that the rate rises.",
     "item14", "14-source-meta", False),
    ("item16 unenumerated bold", "The rate is **very important** here.",
     "item16", "16-unenumerated-bold", False),
    ("item16 emphasis around a link",
     "The rate follows *[[precision|precision]]*.",
     "item16", "16-emphasis-markup", False),
    ("item16 emphasis around math", "The rate is **$r$** here.",
     "item16", "16-emphasis-markup", False),
    ("item18 label markup", "The rate follows [[precision|*exact* precision]].",
     "item18", "18-display-label", False),
    ("item18 label shares no surface", "The rate follows [[precision|zebra]].",
     "item18", "18-label-target", True),
    ("item18 cross-domain word its target does not introduce",
     "The rate follows each [[precision|target]].",
     "item18", "18-label-target", True),
    ("item18 label drops the title's head word",
     "The rate follows the [[decision-threshold|decision]] rule.",
     "item18/partial-label", "18-partial-label", True),
    ("item12 well-definedness boilerplate",
     "For a nonempty dataset of $m \\ge 1$ instances, the rate is averaged.",
     "item12/boilerplate-candidate", "12-boilerplate-candidate", False),
    ("item10 self-link", "The rate links [[{self}|itself]].",
     "item10/self", "10-self-link", False),
    ("item19 Spaced Repetition separator in body math",
     "The rates compare as $a : b :: c : d$ here.",
     "item19/sr-marker", "19-sr-marker", False),
    ("item19 Spaced Repetition separator in an Obsidian comment",
     "%% The rates compare as a :: b here. %%",
     "item19/sr-marker", "19-sr-marker", False),
    ("item19 Spaced Repetition separator in a mid-line HTML comment",
     "The rates compare <!-- as a::b --> here.",
     "item19/sr-marker", "19-sr-marker", False),
    ("item19 an HTML comment left open at the start of a line",
     "<!-- The rates compare\nas a ratio. -->",
     "item19/sr-marker", "19-sr-marker", False),
    ("item19 a column-0 fence no column-0 line closes",
     "%% The rates compare\n```\n%%",
     "item19/sr-marker", "19-sr-marker", False),
    ("item19 a line holding only the multi-line card separator",
     "Why do the rates compare\n?\nAs a ratio.",
     "item19/sr-marker", "19-sr-marker", False),
    ("item9 a display outside its numbered step",
     "The rate is found in steps.\n\n1. Count the hits:\n\n$$\nh = 1\n"
     "$$\n\n2. Divide the hits by the total.",
     "item9/list-indent", "9-list-indent", False),
    ("item9 an explanation outside its numbered step",
     "The rate is found in steps.\n\n1. Count the hits.\n\nEach hit is a "
     "true positive.\n\n2. Divide the hits by the total.",
     "item9/list-indent", "9-list-indent", False),
    ("item9 a display short of a two-digit step's text column",
     "The rate is found in steps.\n\n10. Count the hits:\n\n   $$\n"
     "   h = 1\n   $$\n\n11. Divide the hits by the total.",
     "item9/list-indent", "9-list-indent", False),
    ("item9 a navigation cue in a step's indented paragraph",
     "The rate is found in steps.\n\n10. Count the hits.\n\n    See "
     "[[precision]] for details.\n11. Divide the hits by the total.",
     "item9/imperative-link", "9-link-integration", False),
    ("item10 a repeated link indented under a two-digit step",
     "The rate is found in steps.\n\n10. Count the [[precision]] hits.\n\n"
     "    The [[precision]] hits are true positives.\n"
     "11. Divide the hits by the total.",
     "item10/dup", "10-duplicate-wikilink", False),
    ("item12 boilerplate in a step's indented paragraph",
     "The rate is found in steps.\n\n10. Count the hits.\n\n    For a "
     "nonempty dataset of $m \\ge 1$ instances, the rate is averaged.\n"
     "11. Divide the hits by the total.",
     "item12/boilerplate-candidate", "12-boilerplate-candidate", False),
    ("item12 a one-line display inside a step",
     "The rate is found in steps.\n\n10. Count the hits:\n\n    $$h = 1$$"
     "\n\n11. Divide the hits by the total.",
     "item12/equation-format", "12-equation-format", False),
    ("item13 a body key inside a step",
     "The rate is found in steps.\n\n1. Count the hits.\n\n   read: false"
     "\n2. Divide the hits by the total.", "item13", "13-merge-scar", False),
    ("item9 a nested list short of a two-digit step's text column",
     "The rate is found in steps.\n\n10. Count the hits. They are:\n"
     "   - the true positives;\n   - the false positives.\n"
     "11. Divide the hits by the total.",
     "item9/list-indent", "9-list-indent", False),
    ("item9 a lead-in count the list contradicts",
     "The rate is found in two steps:\n\n1. Count the hits.\n"
     "2. Count the runs.\n3. Divide the hits by the runs.",
     "item9/list-mismatch-candidate",
     "9-list-mismatch-candidate", False),
    ("item9 a Repeat step that names no earlier step",
     "The rate is found in steps.\n\n1. Count the hits.\n"
     "2. Repeat from step 2 until every run is counted.",
     "item9/list-mismatch-candidate",
     "9-list-mismatch-candidate", False),
    ("item9 a definition written as instructions",
     "Compute the rate from the hits.",
     "item9/register-candidate", "9-register-candidate", False),
    ("item9 praise in body prose", "The rate is a famous measure.",
     "item9/register-candidate", "9-register-candidate", False),
)

#: A numbered procedure whose displays and paragraphs sit at their steps'
#: text columns: 3 spaces under ``1.``, 4 under ``10.``, with a nested bullet.
_QUIET_STEPS = (
    "The rate is found in steps.\n\n"
    "1. Count the hits, which are the true positives:\n\n"
    "   $$\n   h = \\sum_{i=1}^{n} t_i\n   $$\n\n"
    "   Here $t_i$ is one for a true positive and zero otherwise.\n"
    "2. Choose a threshold. Common choices are:\n"
    "   - the median score;\n   - a fixed cut-off.\n\n"
    "   A fixed cut-off keeps runs comparable.\n"
    "10. Divide the hits by the predicted positives:\n\n"
    "    $$\n    r = \\frac{h}{p}\n    $$\n\n"
    "    Here $p$ counts the predicted positives.\n"
    "11. Repeat from step 1 until every threshold is scored.\n\n"
    "After scoring, the best threshold is kept.")

#: Body paragraphs that neither linter may flag under the named keys:
#: ``(name, paragraph, scan_vault key, lint_entry id)``, checked in folder
#: mode. Both self-tests add an Organism ``mus-musculus`` whose description
#: and opener say "Mus musculus is the mouse", an entry ``l-2-norm``
#: titled "$L^2$ norm", ``decision-threshold`` titled "Decision threshold",
#: and ``label-machine-learning`` titled "Label (machine learning)", whose
#: prose says "The word *target* is a near-synonym".
SHARED_QUIET = (
    ("item6 compound file extension", "The rate ships as a `.tar.gz` bundle.",
     "item6", "6-api-surface"),
    ("item6 compound with one known part",
     "Scans ship as `.nii.gz` and `.tar.zst`.", "item6", "6-api-surface"),
    ("item14 the source of an origin",
     "Lake Victoria is the source of the White Nile.",
     "item14", "14-source-meta"),
    ("item14 finance's book value",
     "It divides the share price by the book value per share.",
     "item14", "14-source-meta"),
    ("item16 italic taxon bullet anchor",
     "- ***Mus musculus*** — the house mouse.",
     "item16", "16-unenumerated-bold"),
    ("item18 bound Organism common name",
     "The rate is measured in the [[mus-musculus|mouse]].",
     "item18", "18-label-target"),
    ("item18 plain form of a math title",
     "The rate uses the [[l-2-norm|L-squared norm]].",
     "item18", "18-label-target"),
    ("item18 cross-domain synonym its target introduces",
     "The rate is scored against each [[label-machine-learning|target]].",
     "item18", "18-label-target"),
    ("item18 label keeping the title's head word",
     "The rate crosses the [[decision-threshold|threshold]].",
     "item18/partial-label", "18-partial-label"),
    ("item18 derived form of the head word",
     "The rate controls [[decision-threshold|thresholding]].",
     "item18/partial-label", "18-partial-label"),
    ("item12 ranges a definition needs",
     "For $p \\ge 1$ the rate is a norm, with $0 \\le \\lambda \\le 1$.",
     "item12/boilerplate-candidate", "12-boilerplate-candidate"),
    ("item19 a proportion written with the math remedy",
     "The rates compare as $a : b \\mathbin{:}\\mathbin{:} c : d$ here.",
     "item19/sr-marker", "19-sr-marker"),
    ("item19 single colons are no card separator",
     "The odds are 3:1, and the ratio a:b stays fixed.",
     "item19/sr-marker", "19-sr-marker"),
    ("item19 a line that starts with an HTML comment is skipped",
     "<!-- The rates compare as a::b here. -->",
     "item19/sr-marker", "19-sr-marker"),
    ("item9 displays and paragraphs at their steps' text columns",
     _QUIET_STEPS, "item9/list-indent", "9-list-indent"),
    ("item12 canonical displays at their steps' text columns",
     _QUIET_STEPS, "item12/equation-format", "12-equation-format"),
    ("item13 a digit in a display indented under a two-digit step",
     "The rate is found in steps.\n\n10. Count the hits:\n\n    $$\n    1\n"
     "    $$\n\n11. Divide the hits by the total.",
     "item13", "13-merge-scar"),
    ("item9 a display after a nested item's colon stays in its step",
     "The rate is found in steps.\n\n1. Count the hits.\n"
     "2. Weigh them. The weight combines:\n   - the hit count;\n"
     "   - the run count, scaled by:\n\n   $$\n   s = \\frac{1}{2}\n   $$"
     "\n\n   Here $s$ is the scale.\n"
     "3. Repeat from step 1 until every run is weighed.",
     "item9/list-indent", "9-list-indent"),
    ("item9 a display and its explanation between two bullet lists",
     "The rate has two inputs:\n\n- the hits;\n- the runs.\n\n$$\n"
     "r = \\frac{h}{n}\n$$\n\nHere $h$ counts the hits and $n$ the runs.\n\n"
     "Two uses are common:\n\n- ranking runs;\n- picking a threshold.",
     "item9/list-indent", "9-list-indent"),
    ("item9 a lead-in count that leaves out the final Repeat step",
     "The rate alternates two steps:\n\n1. Count the hits.\n"
     "2. Divide the hits by the total.\n"
     "3. Repeat from step 1 until every run is scored.",
     "item9/list-mismatch-candidate",
     "9-list-mismatch-candidate"),
    ("item9 a numbered procedure's steps and Repeat step",
     _QUIET_STEPS, "item9/list-mismatch-candidate",
     "9-list-mismatch-candidate"),
    ("item9 imperatives in numbered steps",
     _QUIET_STEPS, "item9/register-candidate", "9-register-candidate"),
    ("item9 the classic example in body prose",
     "A ratio is the classic example of the rate.",
     "item9/register-candidate", "9-register-candidate"),
)


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------

def run_self_test(verbose=False):
    cases = []

    def check(label, got, want):
        cases.append((label, got == want, got, want))

    def checks(findings):
        return [finding["check"] for finding in findings]

    # item 4
    check("source forms: a paged PDF, an unanchored note and a full URL",
          [source_reference_kind(value) for value in (
              "[[Doe_X_2025.pdf#page=2]]", "[[Doe_X_2025.md]]",
              "https://arxiv.org/abs/2305.18290",
              "https://en.wikipedia.org/wiki/Online_(disambiguation)",
              "http://example.org:8080/a/b?q=1&r=2#part",
              "https://huggingface.co/docs/trl/sft_trainer")],
          ["pdf", "md", "url", "url", "url", "url"])
    check("not source forms: labels, links, fragments and bad schemes",
          [source_reference_kind(value) for value in (
              "[[Doe_X_2025.pdf]]", "[[Doe_X_2025.pdf#page=0]]",
              "[[Doe_X_2025.md#Intro]]", "[[Doe_X_2025.md|Doe]]",
              "[Paper](https://example.org/p)", "example.org/page",
              "https://example.org/a b", "https://localhost/page",
              "ftp://example.org/file", "HTTPS://example.org/", "https://",
              "https://example.org/<x>", "", None, "Doe 2025",
              "[[https://example.org/roc.md]]",
              "[[https://example.org/Doe_X_2025.pdf#page=2]]",
              "https://example.org/a\x01", "https://example.org/a\u200b",
              "https://example.org/a\u202egnp.exe",
              "https://example.org:99999/", "https://example.org:0/")],
          [None] * 22)
    check("a port inside 1-65535 is a valid URL source",
          [source_reference_kind(value) for value in (
              "https://example.org:1/", "https://example.org:65535/a")],
          ["url", "url"])
    chapter = "[[Prince_UDL_2026_02_SupLearn.pdf#page=3]]"
    check("a chapter beside its book, `_src` aside, is one document; two "
          "chapters, a `_2` book and a URL are not",
          [source_identity_pairs([book, chapter]) for book in (
              "[[Sources/PDFs/Prince_UDL_2026.pdf#page=40]]",
              "[[Prince_UDL_2026_src.pdf#page=40]]",
              "[[Prince_UDL_2026_01_Intro.pdf#page=1]]",
              "[[Prince_UDL_2026_2.pdf#page=4]]",
              "https://example.org/Prince_UDL_2026.pdf")],
          [[("book-and-chapter", 0, 1)]] * 2 + [[]] * 3)
    check("a Markdown item beside a PDF of the same folded stem pairs",
          source_identity_pairs(["[[Doe_X_2025.pdf#page=2]]",
                                 "[[Doe_X_2026.md]]", "[[doe_x_2025.md]]"]),
          [("same-stem", 0, 2)])

    # item 5
    check("a qualified slug and an unnamed bare word pass the floor",
          [bare_common_noun_slug(value) for value in
           ("entropy-information-theory", "precision", "", None)],
          [False, False, False, False])
    check("a corpus word or a hyphenated corpus phrase is a bare slug",
          [bare_common_noun_slug(value) for value in
           ("entropy", "tree-of-life", "online-learning")],
          [True, True, True])
    check("a qualified or longer phrase slug passes the floor",
          [bare_common_noun_slug(value) for value in
           ("tree-of-life-biology", "online-machine-learning",
            "Tree-of-life")],
          [False, False, False])
    check("a cross-domain floor term is never an alias, in any case or form",
          cross_domain_alias_findings(
              ["entropy", "Tree of life", "online-learning",
               "tree-of-life-biology", "shannon-entropy", "", None]),
          ["entropy", "Tree of life", "online-learning"])
    check("a plural of a floor word or phrase is bare too",
          ([bare_common_noun_slug(value) for value in
            ("kernels", "policies", "online-learnings", "precisions")],
           cross_domain_alias_findings(
               ["targets", "Policies", "kernels", "entropy-physics"])),
          ([True, True, True, False], ["targets", "Policies", "kernels"]))
    check("single-word alias candidates of qualified or common subjects",
          [bare_word_alias_candidate(slug, title) for slug, title in (
              ("sensitivity", "Recall (machine learning)"),
              ("kernel", "Filter"),
              ("true-positive-rate", "Recall (machine learning)"),
              ("tpr", "Recall"))],
          [True, True, False, False])
    check("an acronym candidate is not a bare common word",
          [bare_word_alias_candidate(slug, title, surface)
           for slug, title, surface in (
               ("tpr", "Recall (machine learning)", "TPR"),
               ("pca", "Principal component analysis (statistics)", "PCA"),
               ("sensitivity", "Recall (machine learning)", "sensitivity"))],
          [False, False, True])

    # item 6
    check("a Software entry keeps its API surface",
          api_surface_findings("Software", "numpy.linalg",
                               "In NumPy use `np.dot` to multiply.",
                               "```py\nx\n```"), [])
    check("code-identifier titles",
          [checks(api_surface_findings("Concept", title, "", ""))
           for title in ("numpy.linalg", "fit()", "Gradient descent", "SU(2)")],
          [["code-identifier-title"], ["code-identifier-title"], [], []])
    check("library framing reports one API string and stops",
          checks(api_surface_findings(
              "Concept", "Rate", "In PyTorch it is built with `x`.", "")),
          ["api-string", "backticked-identifiers"])
    check("each failure string is recognized",
          [checks(api_surface_findings("Concept", "Rate", prose, ""))[:1]
           for prose in ("SciPy provides a solver.", "The flag enables it.",
                         "The value is available via `x`.")],
          [["api-string"]] * 3)
    check("code-form alternatives are a signpost, presentation literals not",
          [checks(api_surface_findings("Concept", "Rate", prose, ""))
           for prose in ("Pick `mean` or `sum`.", "Save `.csv` or `.tsv`.",
                         "Use `[CLS]` or `[SEP]`.")],
          [["api-string", "backticked-identifiers"], [], []])
    check("compound file extensions are literals; dotted chains are not",
          ([checks(api_surface_findings("Concept", "Rate", prose, ""))
            for prose in ("Ship a `.tar.gz` or `.zip` bundle.",
                          "Read the `.tar.bz2` file.")],
           api_surface_findings("Concept", "Rate",
                                "Call `np.dot` then `.str.lower`.",
                                "")[-1]["identifiers"]),
          ([[], []], ["np.dot", ".str.lower"]))
    check("a compound with one known end part is a literal",
          [checks(api_surface_findings("Concept", "Rate", prose, ""))
           for prose in ("Scans ship as `.nii.gz` and `.fastq.gz` files.",
                         "Archives use `.tar.zst` or `.tar.gz`.",
                         "Types live in `.d.ts` files.")],
          [[], [], []])
    check("both fence spellings are found in the comment-masked body",
          [checks(api_surface_findings("Concept", "Rate", "", body))
           for body in ("```\nx\n```", "~~~\nx\n~~~", "<!--\n```\n-->")],
          [["fenced-code"], ["fenced-code"], []])
    check("the identifier cap names each identifier",
          api_surface_findings("Concept", "Rate",
                               "Use `alpha` and `beta` with `.csv`.",
                               "")[-1]["identifiers"],
          ["alpha", "beta"])

    # item 13
    check("schema keys, stray rules and digit lines are scars",
          [checks(merge_scar_findings(prose)) for prose in (
              "Opener.\n\nread: false", 'Opener.\n\nissues: ""',
              "Opener.\n\n---\n\nMore.", "Opener.\n\n3\n\nMore.")],
          [["frontmatter-key"], ["frontmatter-key"], ["stray-rule"],
           ["digit-line"]])
    check("scar evidence lines are one-based within the prose",
          [finding["line"] for finding in merge_scar_findings(
              "Opener.\n\ntags: x\n\n---\n\n$$\nx\n$$\n\n7")],
          [3, 5, 11])
    check("listings, Setext underlines and display math are not scars",
          [merge_scar_findings(prose) for prose in (
              "Opener.\n\n```yaml\ntype: Software\n```",
              "Heading\n---",
              "Opener.\n\n$$\n2\n$$")],
          [[], [], []])
    check("inside a list item, a key line is a scar and a digit in an "
          "indented display is not, as at the top level",
          [checks(merge_scar_findings(prose)) for prose in (
              "Opener.\n\n1. Step.\n\n   read: false",
              "Opener.\n\n10. Step:\n\n    $$\n    2\n    $$",
              "Opener.\n\n- Item:\n\n  $$\n  2\n  $$")],
          [["frontmatter-key"], [], []])

    # item 9: list-item indentation
    def list_indent(prose):
        """``(line, kind)`` per finding, displays paired as `$$` lines."""
        lines = prose.split("\n")
        marks = [index for index, line in enumerate(lines)
                 if line.strip() == "$$"]
        spans = [{"open_line": start, "close_line": end}
                 for start, end in zip(marks[0::2], marks[1::2])]
        return [(finding["line"], finding["kind"])
                for finding in list_indent_findings(prose, spans)]

    display = "$$\nx = 1\n$$"

    def indented(text, spaces):
        return "\n".join(" " * spaces + line if line else line
                         for line in text.split("\n"))

    check("displays and paragraphs at the item's text column stay in it, "
          "four spaces under 10., with a nested bullet and its parent's "
          "paragraph",
          list_indent(
              "Steps run in order.\n\n1. Count:\n\n" + indented(display, 3)
              + "\n\n   Here x counts.\n2. Fit. Learners are:\n"
              "   - a stump;\n   - a tree.\n\n   A tree overfits.\n"
              "10. Sum:\n\n" + indented(display, 4) + "\n\n"
              "    Here x sums.\n11. Repeat from step 1 until done.\n\n"
              "After training, it predicts:\n\n" + display), [])
    check("an unindented display and paragraph between consecutive steps "
          "are reported; a display short of 10.'s column is too",
          list_indent(
              "1. Count:\n\n" + display + "\n\nHere x counts.\n2. Sum.\n"
              "10. Sum:\n\n" + indented(display, 3) + "\n\n11. Stop."),
          [(3, "display"), (7, "paragraph"), (11, "display")])
    check("a display after an item that ends with a colon is reported at "
          "the end of the list, but its explanation is not",
          list_indent("1. Count.\n2. Sum:\n\n" + display + "\n\nHere x sums."),
          [(4, "display")])
    check("a later heading or rule leaves that display reported",
          [list_indent("1. Count.\n2. Sum:\n\n" + display + tail)
           for tail in ("\n\nHere x sums.\n\n## Uses\n\nText.",
                        "\n\nHere x sums.\n\n---\n\nText.", "\n\n## Uses")],
          [[(4, "display")], [(4, "display")], [(4, "display")]])
    check("prose between two lists, a new list from 1, a heading or rule "
          "between steps and a lead-in sentence are not reported",
          [list_indent(prose) for prose in (
              "- a\n- b\n\nProse between.\n\n- c",
              "1. a\n2. b\n\nProse between.\n\n1. c",
              "1. a\n\n## Section\n\n2. b",
              "1. a\n\n---\n\n2. b",
              "1. a\n2. b.\n\nThen it predicts:\n\n" + display)],
          [[], [], [], [], []])
    check("a bullet gap is reported only for a display after a colon; a "
          "display or text between two bullet lists is not",
          [list_indent(prose) for prose in (
              "- a:\n\n" + display + "\n\nHere x is one.\n\n- b",
              "- a\n\n" + display + "\n\n- b",
              "- a\n- b\n\n" + display + "\n\nHere x is one.\n\nOthers "
              "are:\n\n- c\n- d",
              "- a\n\nText.\n\n- b")],
          [[(3, "display")], [], [], []])
    check("a resumed step may interrupt a paragraph; a year opening a line "
          "starts no list",
          [list_indent(prose) for prose in (
              "1. a\n\nText.\n2. b",
              "It began in\n2026. That year it grew.\n\n" + display)],
          [[(3, "paragraph")], []])
    check("a listing, or a table with its caption, in the gap is not "
          "reported, but a paragraph beside it is",
          [list_indent(prose) for prose in (
              "1. a\n\n```\ncode\n```\n\n2. b",
              "1. a\n\n| x | y |\n| --- | --- |\n| 1 | 2 |\n*Two values.*\n\n"
              "Text.\n\n2. b")],
          [[], [(8, "paragraph")]])
    steps = "".join("%d. Run stage %d.\n" % (i, i) for i in range(1, 10))
    check("a nested list short of its item's text column is reported, 3 "
          "spaces under 10. and 2 under 1.; one at the column, a sibling "
          "and a bullet list after the steps are not",
          [list_indent(prose) for prose in (
              steps + "10. Fit. Learners are:\n   - a stump;\n   - a tree.\n"
              "11. Stop.",
              "1. Fit:\n  - a stump;\n  - a tree.\n2. Next.",
              steps + "10. Fit. Learners are:\n    - a stump;\n    - a tree.\n"
              "11. Stop.",
              "1. a\n 2. b\n3. c",
              "1. a\n2. b\n- c\n- d")],
          [[(11, "list")], [(2, "list")], [], [], []])
    check("a display after a nested item's colon stays in the outer step, "
          "inside or after the list; one at the margin ends the list",
          [list_indent(prose) for prose in (
              "1. a\n2. It combines:\n   - the error;\n   - rounds, by:\n\n"
              + indented(display, 3) + "\n\n   Here x scales.\n3. Stop.",
              "1. a\n2. It combines:\n   - rounds, by:\n\n"
              + indented(display, 3) + "\n\n   Here x scales.",
              "1. a\n2. It combines:\n   - rounds, by:\n\n" + display
              + "\n\nHere x scales.")],
          [[], [], [(5, "display")]])
    check("a misplaced nested numbered list is reported, and the step after "
          "it continues the list, so a bullet short of that step's column "
          "is reported too",
          list_indent("1. a\n2. b:\n\n  1. sub a\n  2. sub b\n3. c\n"
                      "  - sub c\n4. d"),
          [(4, "list"), (7, "list")])
    check("a same-delimiter sub-list from 1 short of the step's text column "
          "is reported, 2 spaces or 1; at the column it is not",
          [list_indent(prose) for prose in (
              "1. a\n2. b:\n  1. sub a\n  2. sub b\n3. c",
              "1. a:\n 1. sub a\n2. b",
              "1. a\n2. b:\n   1. sub a\n   2. sub b\n3. c")],
          [[(3, "list")], [(2, "list")], []])

    def mismatch(prose):
        """``(check, line)`` per list-mismatch finding, displays as `$$`."""
        lines = prose.split("\n")
        marks = [index for index, line in enumerate(lines)
                 if line.strip() == "$$"]
        spans = [{"open_line": start, "close_line": end}
                 for start, end in zip(marks[0::2], marks[1::2])]
        return [(finding["check"], finding["line"])
                for finding in list_mismatch_findings(prose, spans)]

    steps = "1. Assign each point.\n2. Move each center.\n"
    check("a lead-in count the list contradicts is a candidate; a count "
          "with or without a final Repeat step passes",
          [mismatch(prose) for prose in (
              "Its two central events run in this order:\n\n" + steps
              + "3. Split the cell.",
              "It runs in three steps:\n\n" + steps,
              "Training alternates two steps:\n\n" + steps
              + "3. Repeat from step 1 until the centers stop.",
              "Training runs in three steps:\n\n" + steps
              + "3. Repeat from step 1 until the centers stop.",
              "Two designs dominate:\n- the TEM;\n- the SEM;\n- the STEM.")],
          [[("lead-in-count", 1)], [("lead-in-count", 1)], [], [],
           [("lead-in-count", 1)]])
    check("only one whole count of items is compared: a partial count, a "
          "measure, a compound, two counts or a count before the colon "
          "sentence count nothing",
          [mismatch(prose + "\n\n" + steps + "3. Split the cell.")
           for prose in (
               "The first two steps prepare the data:",
               "The loop runs three times:",
               "The two-part division runs in order:",
               "Two phases hold four steps:",
               "It has two parts. It runs in order:",
               "It runs in at least two steps:",
               "It runs in two or more steps:",
               "The first two steps prepare four inputs:",
               "It runs in [[step|two steps]] and $2$ rounds:")],
          [[], [], [], [], [], [], [], [], [("lead-in-count", 1)]])
    check("a verb or conjunction after a count is no counted noun",
          [mismatch(prose + "\n\n" + steps + "3. Split the cell.")
           for prose in (
               "It splits a node in two as follows:",
               "The sum of two is:",
               "Splitting in two gives:",
               "It runs in two steps:")],
          [[], [], [], [("lead-in-count", 1)]])
    check("a numbered list goes on past a misplaced display; a bullet list "
          "split by a paragraph is not counted; a parent item's colon counts "
          "its nested list, which outer text ends",
          [mismatch(prose) for prose in (
              "It runs in three steps:\n\n1. Count:\n\n$$\nh = 1\n$$\n\n"
              "2. Divide.\n3. Round.",
              "It has two inputs:\n\n- the hits;\n\nEach is counted.\n\n"
              "- the runs.",
              "Steps:\n\n1. Weigh the two inputs:\n   - the hits;\n"
              "   - the runs;\n   - the rounds.\n2. Divide.",
              "1. Weigh the two inputs:\n   1. the hits;\n   2. the runs."
              "\n\nThe weights add up.\n\n   3. the rounds.")],
          [[], [], [("lead-in-count", 3)], []])
    check("a Repeat step must name an earlier step of its list, as written "
          "or as rendered",
          [mismatch(prose) for prose in (
              steps + "3. Repeat from step 3 until done.",
              steps + "3. Repeat from step 4 until done.",
              steps + "3. Repeat steps 0 and 1 until done.",
              steps + "3. Repeat from step 2 until done.",
              "1. Assign.\n1. Move.\n1. Repeat from step 2 until done.",
              "- Assign.\n- Repeat from step 3 until done.")],
          [[("repeat-step", 3)], [("repeat-step", 3)], [("repeat-step", 3)],
           [], [], []])

    def register(prose):
        """``(check, line)`` per register finding, displays as `$$`."""
        lines = prose.split("\n")
        marks = [index for index, line in enumerate(lines)
                 if line.strip() == "$$"]
        spans = [{"open_line": start, "close_line": end}
                 for start, end in zip(marks[0::2], marks[1::2])]
        return [(finding["check"], finding["line"])
                for finding in register_findings(prose, spans)]

    check("a prose sentence opening with a bare imperative and a "
          "determiner or number is a register candidate, mid-paragraph too",
          [register(prose) for prose in (
              "Train one detector per class.",
              "It votes.\nEach detector scores it. Predict the class.",
              "Use the median when outliers dominate.",
              "Fit 3 models.")],
          [[("imperative", 1)], [("imperative", 2)], [("imperative", 1)],
           [("imperative", 1)]])
    check("steps, captions, headings, displays, a lazy item line, Let, and "
          "a verb without a determiner are no imperative candidate",
          [register(prose) for prose in (
              "1. Train one detector per class.\n- Use the median.",
              "![[plot.png]]\n*Fit a line to the points.*",
              "## Use the median",
              "$$\nRun the loop.\n$$",
              "1. Count the hits\nUse the median.",
              "Let $x$ be the input.",
              "Use of the median is common. Run-time grows.")],
          [[], [], [], [], [], [], []])
    check("praise in body prose is a register candidate; the classic "
          "example, a link target and an image embed are not",
          [register(prose) for prose in (
              "It is a famous dataset.",
              "- One of the most important techniques.",
              "A stump is the classic example.",
              "It uses [[famous-dataset|the dataset]].",
              "![[famous-plot.png]]")],
          [[("praise", 1)], [("praise", 1)], [], [], []])
    check("the entry's title and a proper name are no body praise",
          [[(finding["check"], finding["line"])
            for finding in register_findings(prose, title=title)]
           for prose, title in (
               ("The **Classic Maya collapse** emptied cities.\n"
                "Classic Maya collapse ended an era.",
                "Classic Maya collapse"),
               ("It ended in the Terminal Classic period.", None),
               ("Classic Maya collapse ended an era.", None))],
          [[], [], [("praise", 1)]])

    # item 14
    check("source-meta phrases and the technical source compounds",
          [checks(source_meta_findings(prose, "Concept")) for prose in (
              "As shown in the paper, it holds.", "This source gives it.",
              "The source text states it.", "It maps the source domain.",
              "It reads the source-code tree.",
              "The previous section showed it.",
              "As the previous section showed, it holds.")],
          [["phrase"], ["phrase"], ["phrase"], [], [], ["phrase"],
           ["phrase"]])
    check("the paper, the book and the article are source-meta outside Work "
          "entries; this paper is source-meta everywhere",
          [[checks(source_meta_findings(prose, kind))
            for kind in ("Concept", "Work")]
           for prose in ("The book argues it.", "The paper argues it.",
                         "In this paper we argue it.")],
          [[["phrase"], []], [["phrase"], []], [["phrase"], ["phrase"]]])
    check("this chapter and this section are source-meta everywhere; this "
          "book and this article only outside Work entries",
          [[checks(source_meta_findings(prose, kind))
            for kind in ("Concept", "Work")]
           for prose in ("As this chapter shows, voting helps.",
                         "In this section, voting helps.",
                         "This book says voting helps.",
                         "This article notes it.",
                         "It divides the price by this book value.")],
          [[["phrase"], ["phrase"]], [["phrase"], ["phrase"]],
           [["phrase"], []], [["phrase"], []], [[], []]])
    check("the source of an origin and finance's book value are not "
          "source-meta",
          [checks(source_meta_findings(prose, "Concept")) for prose in (
              "Lake Victoria is the source of the White Nile.",
              "It divides the price by the book value per share.",
              "It sorts firms by the book-to-market ratio.",
              "The book argues that book value matters.")],
          [[], [], [], ["phrase"]])
    check("a source-meta message quotes the matched phrase",
          source_meta_findings("This source gives it.", "Concept")[0]["message"],
          'source-meta phrasing "This source"')
    check("bare authors are flagged; a named work passes the default floor",
          [checks(source_meta_findings(prose, "Concept")) for prose in (
              "The authors argue it.",
              "The authors of [[attention-paper]] argue it.",
              "The authors of *Attention Is All You Need* argue it.")],
          [["authors"], [], []])
    check("the default floor accepts a capitalized name or acronym, not a "
          "determiner",
          [checks(source_meta_findings(prose, "Concept")) for prose in (
              "The authors of SGDR recommend restarting it.",
              "The authors of GPT-3 argue it.",
              "The authors of a study argue it.",
              "The authors of The study argue it.")],
          [[], [], ["authors"], ["authors"]])
    check("a caller's resolver decides whether the authors name a Work",
          checks(source_meta_findings(
              "The authors of [[transformer]] argue it.", "Concept",
              names_work=lambda named: False)), ["authors"])

    # item 16
    check("only the opener's first bold is the title slot",
          [finding["span"] for finding in unenumerated_bold_findings(
              "**Rate** and **second** open.\n\nThe **third** follows.")],
          ["second", "third"])
    # A masked comment is blank to the checks; the opener starts after it.
    check("a leading masked comment or blank line does not end the opener",
          [[finding["span"] for finding in unenumerated_bold_findings(prose)]
           for prose in ("              \n\n**Rate** opens.\n\n"
                         "The **third** follows.",
                         "             \n**Rate** opens.",
                         "   \n**Rate** opens.")],
          [["third"], [], []])
    check("a leading heading or display block does not take the title slot",
          [[finding["span"] for finding in unenumerated_bold_findings(prose)]
           for prose in ("# Rate\n\n**Rate** opens.\n\nThe **third** follows.",
                         "## **Overview**\n\n**Rate** opens.",
                         "$$\nx\n$$\n\n**Rate** opens.")],
          [["third"], ["Overview"], []])
    check("bullet anchors, captions, Related and single spans are exempt",
          unenumerated_bold_findings(
              "**Rate** opens.\n\n- **True positives** (TP) — correct.\n"
              "*A **caption** line.*\n\n**Related:**\n\n"
              "It is **$r$** and **[[x]]**."), [])
    check("an italic taxon or strain can be a bullet anchor",
          unenumerated_bold_findings(
              "**Rate** opens.\n\n- ***Mus musculus*** — the house mouse.\n"
              "- ***E. coli* K-12** — a lab strain."), [])
    check("an anchor without a delimiter is still unenumerated bold",
          checks(unenumerated_bold_findings(
              "**Rate** opens.\n\n- ***Mus musculus*** lives here.")),
          ["unenumerated-bold"])
    check("tables and code are masked",
          unenumerated_bold_findings(
              "**Rate** opens.\n\nA | B\n---|---\n**x** | y\n\n`**code**`",
              ((2, 4),)), [])
    check("emphasis around a link, math or code span",
          [finding["kind"] for finding in emphasis_span_findings(
              "**Rate** opens.\n\nIt is *[[x]]*, **$r$** and *`c`*.")],
          ["wikilink", "math", "code"])
    check("unbalanced delimiters and code samples are not emphasis",
          emphasis_span_findings(
              "**Rate** opens.\n\nIt is **[[x]]* and `*[[y]]*`."), [])
    check("the Related footer is read for emphasis around a link",
          checks(emphasis_span_findings("**Rate** opens.",
                                        "**Related:** *[[x|X]]*")),
          ["emphasis-around-span"])
    markup = pure_math_opener_markup("$x$", "**$x$** is a variable.")
    check("a pure-math title's opener bold is exempt once, in the opener",
          (markup, checks(emphasis_span_findings(
              "**$x$** is a variable.\n\nLater **$x$** again.",
              opener_markup=markup))),
          ("**$x$**", ["emphasis-around-span"]))
    check("the pure-math exemption holds after a leading masked comment",
          [finding["line"] for finding in emphasis_span_findings(
              "              \n\n**$x$** is a variable.\n\nLater **$x$** again.",
              opener_markup=markup)],
          [5])
    check("the pure-math exemption holds in the first prose paragraph only",
          [[finding["line"] for finding in emphasis_span_findings(
              prose, opener_markup=markup)] for prose in (
                  "## Overview\n\n**$x$** is a variable.\n\nLater **$x$**.",
                  "## **$x$**\n\n**$x$** is a variable.")],
          [[5], [1]])
    check("the exemption needs a pure-math title and an opener bold",
          [pure_math_opener_markup(title, opener)
           for title, opener in (("Rate", "**Rate** opens."),
                                 ("$x$", "No bold."))],
          [None, None])
    matched = BOLD_OUTER_RE.search("***E. coli* K-12** is a strain.")
    check("the outer-bold reader keeps the mixed taxon/strain form",
          bold_parts(matched), ("E. coli K-12", "mixed", "E. coli"))

    def timed(scan):
        import time
        start = time.perf_counter()
        scan()
        return time.perf_counter() - start < 1.0

    for label, scan in (
            ("an opener bold with no parenthetical",
             lambda: list(BOLD_PAREN_RE.finditer(
                 "The **weighted mean** of " + ", ".join(
                     "$x_{%d}$" % i for i in range(40))))),
            ("a `**` inside math",
             lambda: list(BOLD_OUTER_RE.finditer(
                 "Here $a^{**}$ is the dual and " + "$x_i$ and " * 40))),
            ("an unclosed bullet anchor",
             lambda: _BULLET_ANCHOR_RE.match(
                 "- **Weights " + "$x_i$ and " * 40)),
            ("an unclosed bold before escaped dollars",
             lambda: list(BOLD_OUTER_RE.finditer("**a " + "\\$ " * 40)))):
        check("bold readers stay linear on 40 math spans after %s" % label,
              timed(scan), True)
    check("bold readers keep escaped dollars, math, `**` in math and a "
          "currency dollar",
          [BOLD_PAREN_RE.search(text).group("bold", "paren") for text in (
              "The **\\$5 bill** (FB) is worth $x$ dollars",
              "The **$k$-means algorithm** (KMA) uses $k$",
              "**$a^{**}$ dual** (AD)", "**US$ price** (USP)")],
          [("\\$5 bill", "FB"), ("$k$-means algorithm", "KMA"),
           ("$a^{**}$ dual", "AD"), ("US$ price", "USP")])

    # item 18
    check("display-label markup kinds",
          [display_label_markup(label) for label in (
              "$x$ rate", "`x`", "**x**", "*x* rate", "plain label", "a * b")],
          [["$ (LaTeX)"], ["backtick"], ["** (bold)"], ["* (italic)"], [], []])
    check("piped links report markup with a message; plain labels do not",
          [(link["target"], "message" in link) for link in display_label_links(
              "See [[gamma-delta|*gamma* delta]] and [[x#Part|x part]].\n"
              "[[y]]")],
          [("gamma-delta", True), ("x", False)])
    check("labels sharing a surface pass; an invented label does not",
          [label_shares_surface(label, surfaces) for label, surfaces in (
              ("entropy", ["Entropy (information theory)"]),
              ("deep neural networks", ["Neural network"]),
              ("fine-tuned", ["Fine-tuning"]),
              ("zebra", ["Gamma delta", "gd"]),
              ("tuner", ["Tuning"]),
              ("—", ["Gamma"]))],
          [True, True, True, False, False, True])
    check("an irregular plural label shares its singular title's surface",
          [label_shares_surface(label, surfaces) for label, surfaces in (
              ("taxa", ["Taxon"]), ("genera", ["Genus"]),
              ("loci", ["Locus (genetics)"]))],
          [True, True, True])
    check("a math title's plain form is a shared surface",
          [label_shares_surface(label, surfaces) for label, surfaces in (
              ("chi-squared test", ["$\\chi^2$ test"]),
              ("ell-one regularization", ["$\\ell_1$ regularization"]),
              ("chi-squared", ["$\\chi^2$ test"]),
              ("zebra", ["$\\chi^2$ test"]))],
          [True, True, True, False])
    check("a label keeping only the title's modifiers drops its head",
          [label_drops_head(label, title) for label, title in (
              ("greedy", "Greedy algorithm"),
              ("bias/variance", "Bias/variance trade-off"),
              ("model", "Model organism"),
              ("features", "Feature engineering"),
              ("machine learning", "Machine learning model"),
              ("large numbers", "Law of large numbers"),
              ("out-of-bag", "Out-of-bag evaluation"))],
          ["algorithm", "trade-off", "organism", "engineering", "model",
           "Law", "evaluation"])
    check("the head, its inflections and derived forms, bare terms and "
          "aliases keep a label",
          [label_drops_head(label, title, aliases) for label, title, aliases in (
              ("binary classifier", "Binary classification", ()),
              ("eukaryotic", "Eukaryote", ()),
              ("cells", "Biological cell", ()),
              ("entropy", "Information entropy", ()),
              ("decision boundaries", "Decision boundary", ()),
              ("labels", "Label (machine learning)", ()),
              ("law of large numbers", "Law of large numbers", ()),
              ("oob", "Out-of-bag evaluation", ("oob",)),
              ("zebra", "Decision threshold", ()))],
          [""] * 9)
    check("a term the target defines in italics keeps a modifier label",
          [label_drops_head("ensemble", "Ensemble learning", (),
                            "A group of predictors is called an *ensemble*."),
           label_drops_head("ensemble", "Ensemble learning", (),
                            "Ensemble learning combines predictors."),
           label_drops_head("transformers", "Transformer architecture", (),
                            "The **transformer architecture**, or simply the "
                            "*transformer*, is built on attention."),
           label_drops_head("transformer", "Transformer architecture", (),
                            "The **transformer architecture** is built on "
                            "attention.")],
          ["", "learning", "", "architecture"])
    check("a one-word surface folds to its cross-domain set word",
          [cross_domain_word(text) for text in (
              "target", "Targets", "attributes", "sensitivities",
              "target variable", "self-attention", "precision", "")],
          ["target", "target", "attribute", "sensitivity", "", "", "", ""])
    check("a multiword surface folds only to a listed cross-domain phrase",
          [cross_domain_word(text) for text in (
              "online learning", "Online-learning", "collinearity",
              "online machine learning", "multicollinearity")],
          ["online learning", "online learning", "collinearity", "", ""])
    label_prose = "A label is an answer. The word *target* is a near-synonym."
    check("a cross-domain synonym passes only where its target introduces it",
          [cross_domain_synonym_label(label, surfaces, prose)
           for label, surfaces, prose in (
               ("targets", ["Label (machine learning)"], label_prose),
               ("attribute", ["Feature (machine learning)"],
                "Features are also called *predictors* or *attributes*."),
               ("target", ["Label (machine learning)"],
                "The target is the answer."),
               ("attribute", ["Label (machine learning)"], label_prose),
               ("response", ["Label (machine learning)"],
                "It is also called the *response*."),
               ("target values", ["Label (machine learning)"], label_prose),
               ("entropy", ["Information entropy"],
                "The *entropy* of a source."))],
          [True, True, False, False, False, False, False])
    mouse = ("Organism", "Mus musculus",
             "Mus musculus is the mouse, a small rodent.",
             "***Mus musculus*** is the mouse, a small rodent.\n\nMore.")
    check("an Organism binds its common name in the description or opener",
          (organism_common_name_surfaces(*mouse),
           organism_common_name_surfaces("Concept", *mouse[1:])),
          (["mouse"], []))
    check("a bound common name, or its plural, is a valid label",
          [organism_common_name_bound(*mouse, label)
           for label in ("mouse", "Mice", "rodent", "[[x]]")],
          [True, True, False, False])
    check("an accented bound common name is a valid label",
          organism_common_name_bound(
              "Organism", "Euterpe oleracea",
              "Euterpe oleracea is the açaí palm, a palm tree.", "",
              "açaí palm"), True)

    # item 19
    one = [("flashcard", "Bias–variance trade-off", "fault")]
    check("with one card every line-3 fault is reported",
          primary_line3_faults(1, one, "Bias-variance trade-off", None),
          (one, None))
    near = [("card 1", "Bias–variance trade-off", "fault"),
            ("card 2", "Overfitting", "fault")]
    check("with several failing cards, the one near miss is reported",
          primary_line3_faults(2, near, "Bias-variance trade-off", None),
          (near[:1], None))
    check("a passing primary card: the extra cards, which are removed, "
          "draw no line-3 fault",
          primary_line3_faults(
              2, [("card 1", "Bias-variance trade-off", None),
                  ("card 2", "Overfitting", "fault")],
              "Bias-variance trade-off", None), ([], None))
    missing = primary_line3_faults(
        2, [("card 1", "Underfitting", "fault"),
            ("card 2", "Overfitting", "fault")],
        "Recall", "TPR")
    check("with no near miss, ask for the primary card, naming its answer",
          (missing[0], missing[1].startswith(
              'no card carries the primary answer "Recall (TPR)"; ')),
          ([], True))
    check("with no definition card, rewrite the first card into it, keeping "
          "its attachments, and remove the rest",
          (missing[1].endswith(
              "; rewrite the first card into the definition card, keeping its "
              "attachments, and remove every other card"),
           "preserve" in missing[1], "keep their own" in missing[1]),
          (True, False, False))
    check("with no primary term, nothing is asked",
          primary_line3_faults(2, near, "", None), ([], None))
    check("the primary card: the only card, else the first passing one, "
          "else the one near miss, else none",
          [primary_card_label(rows, "Bias-variance trade-off", None)
           for rows in (
               one, [],
               [("card 1", "Why?", "fault"),
                ("card 2", "Bias-variance trade-off", None),
                ("card 3", "Bias-variance trade-off", None)],
               [("card 1", "Overfitting", "fault"),
                ("card 2", "Bias–variance trade-off", "fault")],
               [("card 1", "Underfitting", "fault"),
                ("card 2", "Overfitting", "fault")],
               [("card 1", "Bias–variance trade-off", "fault"),
                ("card 2", "Bias-variance trade-off (BVT)", "fault")])],
          ["flashcard", None, "card 2", "card 2", None, None])
    no_primary = [("card 1", "Underfitting", "fault"),
                  ("card 2", "Overfitting", "fault")]
    check("the kept card: the primary card, else the first card when the "
          "entry has a primary answer, else none",
          [kept_card_label(rows, term, None) for rows, term in (
              ([("card 1", "Why?", "fault"),
                ("card 2", "Bias-variance trade-off", None)],
               "Bias-variance trade-off"),
              (no_primary, "Bias-variance trade-off"),
              (no_primary, ""), ([], "Bias-variance trade-off"))],
          ["card 2", "card 1", None, None])
    check("an extra card's prefix names the card and asks for its removal "
          "alone",
          EXTRA_CARD_PREFIX % 2,
          "extra card 2 (remove this extra card; it needs no other "
          "repair): ")
    marked = sr_marker_findings(
        "The analogy $a : b :: c : d$ holds.\n"
        "A reversed pair::: here.\n"
        "The operator `std::vector` is code.\n"
        "Odd ``a::b`` spans still count.\n"
        "```cpp\nstd::cout << x;\n```\n"
        "  ```\n  std::cin >> x;\n  ```\n"
        "`x` then a::b after a closed span.\n"
        "Ratios 3:1 and a:b are fine.")
    check("the plugin's single-line separators outside a backtick span or "
          "a column-0 fence are found at their lines",
          [(row["line"], row["marker"]) for row in marked],
          [(1, "::"), (2, ":::"), (4, "::"), (9, "::"), (11, "::")])
    check("an sr-marker message names the remedy",
          ("\\mathbin{:}\\mathbin{:}" in marked[0]["message"],
           "extra card" in marked[0]["message"],
           marked[0]["check"]), (True, True, "sr-marker"))
    check("an sr-marker message quotes the text around the separator",
          sr_marker_findings("word " * 30 + "so $a :: b$ holds.")[0][
              "message"].startswith('"word word word word word word so $a :: '
                                    'b$ holds." holds `::`'), True)
    check("no separator, no finding",
          (sr_marker_findings(""), sr_marker_findings(
              "Plain prose.\n```\na :: b\n```\nMore prose.")), ([], []))
    check("the plugin's comment rule: Obsidian and mid-line comments are "
          "text; a column-0 HTML comment skips its line and the next; an "
          "unclosed one ends the scan",
          [[row["line"] for row in sr_marker_findings(text)] for text in (
              "%% a :: b %%\nProse <!-- a::b --> more.\n  <!-- a::b -->",
              "<!-- a::b -->\nskipped a::b\nread a::b",
              "<!--SR:!2026-01-01,1,250--> a::b",
              "a::b\n<!-- open\nc::d -->\ne::f")],
          [[1, 2, 3], [3], [1], [1, 2]])
    check("a line that is only ? or ?? starts a card after other text in "
          "its paragraph; ?? alone does too, ? alone and code do not",
          [[(row["line"], row["marker"]) for row in sr_marker_findings(text)]
           for text in ("Why?\n?\nBecause.", "Prose.\n\n?\n\nMore.",
                        "Prose.\n\n??\n\nMore.", "Prose.\n  ??  \nEnd.",
                        "```\n?\n```", "a::b\n?\nc")],
          [[(2, "?")], [], [(3, "??")], [(2, "??")], [], [(1, "::")]])
    check("without a Flashcards section the entry's own card may be in the "
          "text, so its ? and ?? lines are not reported",
          (sr_marker_findings("Cue.\n??\nAnswer", multiline=False),
           [row["line"] for row in sr_marker_findings("Cue.\n??\nAnswer")]),
          ([], [2]))
    check("blank and separator lines use the plugin's JavaScript whitespace",
          [[row["line"] for row in sr_marker_findings(text)] for text in (
              "Q\n\ufeff\n?", "Q\n\x85\n?", "\ufeff??", "\x85??")],
          [[], [3], [1], []])
    check("a column-0 fence no later column-0 line closes ends the scan",
          [[(row["line"], row["marker"]) for row in sr_marker_findings(text)]
           for text in ("```text\na::b\n  ```\nc::d",
                        "  ```\n  a::b\n```\nc::d",
                        "```text\na::b\n```\nc::d")],
          [[(1, "```")], [(2, "::"), (3, "```")], [(4, "::")]])
    check("the scheduling state the plugin attaches under a card is not "
          "parsed: a next-line comment, or a callout through its comment",
          [[row["line"] for row in sr_marker_findings(text)] for text in (
              "a::b\n<!--SR:!2026-01-01,1,250--> c::d\ne::f",
              "a::b\n> [!sr|card-metadata]\n> c::d\n> <!--SR:!2026-01-01,1,"
              "250-->\ne::f",
              "a::b\n> [!sr|card-metadata]\nc::d")],
          [[1, 3], [1, 5], [1]])
    check("a separator the plugin finds: the reversed one first, and only "
          "its first occurrence tested against a backtick span",
          [sr_inline_marker(line) for line in (
              "a ::: b", "a :: b", "`a::b` then c::d", "a:b", "`x` a::b")],
          [":::", "::", None, None, "::"])
    check("card lines 1 and 3 holding a separator split the card; line 2 "
          "and code spans do not",
          [[(number, marker) for number, marker, _fault in
            sr_card_marker_faults(card)] for card in (
               ["The ratio $a :: b$ of two counts.", "??", "Ratio"],
               ["The ratio of two counts.", "??", "Ratio::scope"],
               ["The ratio `a::b` of two counts.", "??", "Ratio"],
               ["A reversed a ::: b pair.", "??"])],
          [[(1, "::")], [(3, "::")], [], [(1, ":::")]])
    check("a card-line fault names its remedy",
          [fault.split("; ", 1)[1] for _n, _m, fault in sr_card_marker_faults(
              ["The $a :: b$ rule.", "??", "A::B"])],
          ["write a math `::` as `\\mathbin{:}\\mathbin{:}`",
           "the answer line holds no `::`"])
    check("card syntax after a card's line 3, or in a block that is not a "
          "card, is an extra card; other content, code and a comment are not",
          [(sr_card_syntax_fault(block, after) or "")[:10] for block, after in (
              (["Why square the errors::Large errors weigh more."], 0),
              (["Why?", "?"], 0),
              (["Cue.", "??", "Term", "Why?", "?", "Because."], 3),
              (["Cue.", "??", "Term", "Q::A"], 3),
              (["Cue.", "??", "Term", "?"], 3),
              (["Cue.", "??", "Term::x"], 3),
              (["A stray user line."], 0),
              (["Cue.", "??", "Term", "<!--ordinary comment-->"], 3),
              (["The `a::b` operator."], 0),
              (["?"], 0))],
          ["holds `::`", "holds `?`,", "holds `?`,", "holds `::`",
           "holds `?`,", "", "", "", "", ""])
    check("a card-syntax fault asks for the content's removal as an extra "
          "card",
          sr_card_syntax_fault(["Q::A"]).endswith(
              "remove it as an extra card under the card set and quote it "
              "verbatim in the report"), True)
    check("one card, or none, is a complete card set",
          [flashcard_set_faults(count) for count in (0, 1)], [[], []])
    extra = flashcard_set_faults(2)
    check("a second card is a fixable extra: remove it and quote it in the "
          "report",
          (len(extra), extra[0].startswith("2 cards: "),
           "remove every other card" in extra[0],
           "verbatim, attachments included, in the report" in extra[0]),
          (1, True, True, True))
    check("an extra card is never report-only or preserved",
          [word in extra[0] for word in ("report-only", "legacy",
                                         "preserve", "never repair")],
          [False] * 4)
    check("every further card counts, in one finding",
          [(len(faults), faults[0].split(":")[0])
           for faults in (flashcard_set_faults(3),)],
          [(1, "3 cards")])
    disciplines = ("mathematics", "misc", "statistics")
    check("a discipline root is <discipline>.md tagged only #<discipline>",
          [is_discipline_root(slug, tags, disciplines) for slug, tags in (
              ("statistics", ["#statistics"]),
              ("misc", ("#misc",)),
              ("stats-overview", ["#statistics"]),
              ("statistics", ["#mathematics"]),
              ("statistics", ["#statistics", "#mathematics"]),
              ("statistics", ["statistics"]),
              ("statistics", []),
              ("statistics", None),
              ("physics", ["#physics"]),
              ("Statistics", ["#Statistics"]),
              ("", ["#"]),
              (None, ["#statistics"]))],
          [True, True] + [False] * 10)

    # item 7: the description subject (one copy for both tools)
    check("only the first letter's case is folded for a title subject",
          [description_has_entity_subject(text, "arXiv") for text in (
              "ArXiv stores preprints.", "arXiv stores preprints.",
              "Arxiv stores preprints.", "ARXIV stores preprints.")],
          [True, True, False, False])
    check("a disambiguated title's base term, after an optional article",
          [description_has_entity_subject(text, "Feature (machine learning)")
           for text in ("A feature supplies a model input.",
                        "Feature supplies a model input.",
                        "Feature (machine learning) supplies a model input.",
                        "A Feature (machine learning) supplies an input.")],
          [True, True, False, False])
    check("a placeholder, a longer noun phrase or a prefix is not the subject",
          [description_has_entity_subject(text, "Fairness") for text in (
              "This method compares groups.",
              "Machine learning fairness compares group outcomes.",
              "Fairness-aware learning compares group outcomes.",
              "Fairness, in machine learning, compares outcomes.",
              "Fairness: a property of classifiers.",
              "Fairness — a property of classifiers.")],
          [False, False, False, True, True, True])
    check("an article in the canonical name is not optional twice",
          [description_has_entity_subject(text, "The Iliad") for text in (
              "The Iliad is an epic poem.", "The The Iliad is an epic poem.",
              "Iliad is an epic poem.")],
          [True, False, False])
    check("a mathematical title's plain form is a description subject",
          [description_has_entity_subject(text, "$k$-fold") for text in (
              "k-fold splits a dataset.", "kfold splits a dataset.")],
          [True, False])
    check("a blank description or title is left to its own finding",
          [description_has_entity_subject(d, t) for d, t in (
              ("", "Fairness"), (None, "Fairness"), ("Anything.", ""))],
          [True, True, True])
    check("one item-7 subject message names every accepted subject",
          [(f["check"], f["message"], f["evidence"]["expected_subjects"])
           for f in description_subject_findings(
               "This method compares groups.", "Feature (machine learning)")],
          [("description-subject",
            "description subject must begin with the canonical title or base "
            "term (an optional leading article is allowed); expected one of: "
            '"Feature"', ["Feature"])])
    check("a valid subject has no item-7 subject finding",
          description_subject_findings("A feature supplies an input.",
                                       "Feature (machine learning)"), [])

    # item 9: an acronym title's expansion (one copy for both tools)
    check("an acronym title whose bolded opener title has no parenthetical "
          "misses its expansion",
          [acronym_expansion_missing(title, opener) for title, opener in (
              ("MNIST", "**MNIST** is a dataset of handwritten digits."),
              ("MNIST", "The **MNIST** dataset (1998) holds digits."),
              ("GPT-3", "**GPT-3** is a language model."),
              ("ILSVRC", "**ILSVRC** (2010–2017) ranked models."),
              ("DNA (biology)", "**DNA** is the genetic material."))],
          [True, True, True, True, True])
    check("an expansion directly after the bolded title, past a date, a hard "
          "wrap or a short-for lead-in, satisfies the floor",
          [acronym_expansion_missing(title, opener) for title, opener in (
              ("MNIST", "**MNIST** (Modified National Institute of Standards "
                        "and Technology) is a dataset."),
              ("ATP", "**ATP**\n(adenosine triphosphate) is the fuel."),
              ("ILSVRC", "**ILSVRC** (2010–2017) (ImageNet Large Scale Visual "
                         "Recognition Challenge) ranked models."),
              ("DBSCAN", "**DBSCAN** (short for *density-based spatial "
                         "clustering of applications with noise*) clusters."))],
          [False, False, False, False])
    check("an expansion after the bolded title's algorithm head noun "
          "satisfies the floor",
          acronym_expansion_missing(
              "RANSAC", "**RANSAC** algorithm (random sample consensus) fits "
                        "models."),
          False)
    check("titles that are not one all-capital token, and openers without "
          "the bolded title, are outside the floor",
          [acronym_expansion_missing(title, opener) for title, opener in (
              ("ROC curve", "A **ROC curve** plots rates."),
              ("MLOps", "**MLOps** is a practice."),
              ("SARS-CoV-2", "**SARS-CoV-2** is a coronavirus."),
              ("AdaBoost", "**AdaBoost** reweights mistakes."),
              ("1984", "***1984*** is a novel."),
              ("X", "**X** is a variable."),
              ("MNIST", "MNIST is a dataset."),
              ("MNIST", "**EMNIST** (Extended MNIST) extends it."),
              ("", "**MNIST** is a dataset."),
              (None, None))],
          [False] * 10)

    # item 19: the primary answer on card line 3 (one copy for both tools)
    check("acronym/full-form pairs, including compound and shared-tail forms",
          [acronym_counterpart(short, long) for short, long in (
              ("ATP", "adenosine triphosphate"),
              ("DNA", "deoxyribonucleic acid"),
              ("MLOps", "ML operations"),
              ("OOB evaluation", "out-of-bag evaluation"),
              ("Principal component analysis", "PCA"),
              ("t-distributed stochastic neighbor embedding", "t-SNE"))],
          [True] * 6)
    check("pseudonyms and unrelated names are not acronym counterparts",
          [acronym_counterpart(a, b) for a, b in (
              ("Mark Twain", "Samuel Clemens"), ("Saccharomyces cerevisiae",
                                                 "S. cerevisiae"),
              ("", "PCA"), ("PCA", ""))],
          [False, False, False, False])
    pca = ("Principal component analysis", ["pca"],
           "**Principal component analysis** (PCA) projects data.")
    check("an opener acronym whose slug is an alias is the counterpart",
          flashcard_primary_answer(*pca), ("Principal component analysis", "PCA"))
    check("without the alias the opener acronym binds nothing",
          flashcard_primary_answer(pca[0], ["principal-components"], pca[2]),
          ("Principal component analysis", None))
    check("the term is the base term or plain form; no opener, no counterpart",
          [flashcard_primary_answer(title, [], "")
           for title in ("Feature (machine learning)", "$k$-fold", "", None)],
          [("Feature", None), ("k-fold", None), ("", None), ("", None)])
    check("a hard-wrapped opener, a date before the acronym and the "
          "`algorithm` noun keep the binding",
          [flashcard_primary_answer(title, aliases, opener)[1]
           for title, aliases, opener in (
               ("Principal component analysis", ["pca"],
                "**Principal component\nanalysis** (PCA) projects data."),
               ("ILSVRC",
                ["imagenet-large-scale-visual-recognition-challenge"],
                "**ILSVRC** (2010–2017) (ImageNet Large Scale Visual "
                "Recognition Challenge) ranked models."),
               ("k-nearest neighbors", ["knn"],
                "The **k-nearest neighbors** algorithm (KNN) predicts."))],
          ["PCA", "ImageNet Large Scale Visual Recognition Challenge", "KNN"])
    check("short-for binds; a.k.a. is stripped; an annotated synonym or a "
          "later bold term does not bind",
          [flashcard_primary_answer(title, aliases, opener)[1]
           for title, aliases, opener in (
               ("AdaBoost", ["adaptive-boosting"],
                "**AdaBoost** (short for *adaptive boosting*) reweights."),
               ("PCA", ["principal-component-analysis"],
                "**PCA** (a.k.a. *principal component analysis*) projects."),
               ("Boosting", ["hypothesis-boosting"],
                "**Boosting** (originally called *hypothesis boosting*) "
                "combines weak learners."),
               ("Bacteria", ["bacterium"],
                "**Bacteria** (singular, *bacterium*) is a domain."),
               ("Counterpart scope", ["pca"],
                "**Counterpart scope** uses **Principal component analysis** "
                "(PCA)."))],
          ["adaptive boosting", "principal component analysis",
           None, None, None])
    yeast = ("Saccharomyces cerevisiae", ["s-cerevisiae"],
             "***Saccharomyces cerevisiae*** (*S. cerevisiae*) is a yeast.")
    check("a scientific Organism title binds its italic genus abbreviation",
          flashcard_primary_answer(*yeast, "Organism"),
          ("Saccharomyces cerevisiae", "S. cerevisiae"))
    check("the abbreviation binds only an Organism, in italics, with its alias",
          [flashcard_primary_answer(*args)[1] for args in (
              yeast + ("Concept",),
              (yeast[0], yeast[1], yeast[2].replace("(*S. cerevisiae*)",
                                                    "(S. cerevisiae)"),
               "Organism"),
              (yeast[0], [], yeast[2], "Organism"))],
          [None, None, None])
    check("the Organism counterpart rule is the scientific classification, "
          "not a Latin-looking title",
          [_card_counterpart("*S. cerevisiae*", "Saccharomyces cerevisiae",
                             parts)
           for parts in (None, ("Saccharomyces cerevisiae", ""))],
          [None, "S. cerevisiae"])
    check("line 3 splits one final spaced parenthetical",
          [line3_parts(line) for line in (
              " PCA (principal component analysis) ", "ROC curve",
              "ROC curve(RC)", "A (b) (c)", "", None)],
          [("PCA", "principal component analysis"), ("ROC curve", None),
           ("ROC curve(RC)", None), ("A (b)", "c"), ("", None), ("", None)])
    check("line-3 contract: one message per fault, None when met",
          [flashcard_line3_fault(line, *pca) for line in (
              "Principal component analysis (PCA)",
              "principal component analysis (PCA)",
              "Principal component analysis",
              "Principal component analysis (pca)")] +
          [flashcard_line3_fault(line, "ROC curve", ["auroc"],
                                 "A **ROC curve** plots rates.")
           for line in ("ROC curve", "ROC curve (RC)")],
          [None,
           'the term must be exactly "Principal component analysis" (same '
           "canonical casing)",
           "the established counterpart must appear exactly as (PCA)",
           "the established counterpart must appear exactly as (PCA)",
           None,
           'the parenthetical "RC" is not an opener-established, alias-bound '
           "counterpart of the title"])
    hdbscan_full = ("Hierarchical Density-Based Spatial Clustering of "
                    "Applications with Noise")
    hdbscan = ("HDBSCAN", ["hierarchical-density-based-spatial-clustering-of-"
                           "applications-with-noise"],
               "**HDBSCAN** (%s) clusters points." % hdbscan_full)
    check("an expansion over 60 characters binds, and line 3 must carry it",
          [flashcard_primary_answer(*hdbscan)[1]] +
          [flashcard_line3_fault(line, *hdbscan)
           for line in ("HDBSCAN (%s)" % hdbscan_full, "HDBSCAN")],
          [hdbscan_full, None,
           "the established counterpart must appear exactly as (%s)"
           % hdbscan_full])

    failed = [case for case in cases if not case[1]]
    for label, ok, got, want in cases:
        if verbose or not ok:
            print(("PASS" if ok else "FAIL") + ": " + label)
        if not ok:
            print("  expected %r\n  got      %r" % (want, got))
    print("%d/%d self-test cases pass" % (len(cases) - len(failed), len(cases)))
    return 1 if failed else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true", help="run self-tests")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    if not args.test:
        parser.error("no action requested; use --test")
    return run_self_test(args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
