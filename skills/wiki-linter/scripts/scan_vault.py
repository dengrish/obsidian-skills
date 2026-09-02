#!/usr/bin/env python3
"""Whole-vault scanner for the wiki-linter skill — Step 0, "Inventory the vault".

Parses every `Wiki/**/*.md` entry once (recursively, like wiki-builder's
vault_index.py) and emits a single JSON object: the vault inventory, the
deterministic QC violations ("problems"), and the three worklists the executing agent must
judge — collision candidates (item-5 probes), rename candidates, and backfill
candidates (Task 2) — plus the Task 3 hierarchy diagnostic.

A file that cannot be read (not UTF-8, dangling symlink, permission error) is
reported as an `item0` problem and skipped; it never aborts the scan.

The scanner mechanizes every deterministic check. The executing agent handles
the remaining semantic judgments automatically during the wiki-linter run; no user or other human review is required. Nothing here is applied to the vault:
the candidate lists are worklists, not auto-fixes. See
references/scanner.md for the field-by-field output contract and for what the
scanner deliberately does not check.

Stdlib only, Python 3.8+.

    python3 scripts/scan_vault.py /path/to/vault/Wiki \
        --images /path/to/vault/Sources/Images \
        --out '/tmp/wiki-scan-<run-id>.json'

`--images` is optional. It checks that every local image embed names a file in
`Sources/Images/` and emits report-only `image_folder_findings` for nested
paths or recognizable temporary/staging residue. CONVENTIONS.md §§1 and 8 make
this skill the folder's read-only validator; neither class of finding
authorizes moving or deleting a file.
"""

import argparse
import datetime
import json
import os
import re
import sys
import unicodedata


def fold_name(s):
    """Case- and Unicode-normalization-folded key for a slug or link target.

    This is how the documented vault actually resolves two names to one file:
    Obsidian matches wikilinks case-insensitively, and the vault lives on APFS,
    which is case-insensitive AND normalization-insensitive (an NFC name and
    its NFD spelling open the same file).  Every comparison that answers "do
    these two names denote one file?" goes through this; comparing the raw
    strings instead is only correct on the case-sensitive Linux filesystems
    the plugin is tested on, which is exactly why the bug never showed there.
    """
    return unicodedata.normalize("NFC", s or "").casefold()


# Disciplines are the fixed 27-tag enum (VALID_TAGS below), not self-rooted notes — wiki-builder
# replaced roots: (a wikilink to a discipline note) with tags: (#-prefixed discipline slugs). See below.

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

from slugify import (  # noqa: E402
    SlugError as _SlugError,
    base_term,
    has_parenthetical,
    slug_stem as _slug_stem,
)
from yaml_scalars import parse_scalar, strip_comment  # noqa: E402

# ===========================================================================
# NO SINGULARIZER LIVES HERE EITHER, and for the same reason.  The item-5
# `plural` and `word-order-singular` probes turn on which two word forms are
# the same word; wiki-builder's find_collisions.py probes (c) and (e) turn on
# the same fact.  This file used to carry a three-rule regular-plural stripper
# of its own, which answered "hypotheses" with "hypothes" where wiki-builder
# answered "hypothesis" -- so `hypothesis-testing` / `testing-hypotheses` was
# caught when wiki-builder probed a NEW candidate against the vault and missed
# by the sweep here.  CONVENTIONS.md §9 gives whole-vault dedup detection to
# this skill alone, so a pair already sitting in the vault was reported by
# nobody at all.  `python3 shared/scripts/plurals.py --test` is the
# conformance suite.  Do NOT paste a copy back.
# ===========================================================================
from plurals import (  # noqa: E402
    pluralize, real_permutation, singular_key, singular_keys,
    stem_key, wordorder_key_singular,
)
from organism_names import (  # noqa: E402
    bound_common_names,
    first_sentence,
    organism_title_classification,
    scientific_abbreviation_matches,
    taxon_title_parts,
)
from code_typography import find_bare_code_shapes  # noqa: E402
from equation_coverage import (  # noqa: E402
    find_missing_display_equation_candidates,
)
from entry_structure import opener_subject_date_status  # noqa: E402
from introduced_aliases import missing_introduced_aliases  # noqa: E402
from markdown_tables import (  # noqa: E402
    caption_faults,
    markdown_table_spans,
    mask_line_spans,
)


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


# The explicit mechanical floor in wiki-builder/references/writing.md,
# Cross-domain term disambiguation.  The prose rule remains broader (dictionary
# and drafting tests catch terms outside a finite set); every term it names
# explicitly must at least be guarded here, both from a bare filename and from
# becoming an automatic backfill destination.
COMMON_NOUNS = {
    "activation", "agent", "attention", "bias", "cell", "classification",
    "clustering", "domain", "ensemble", "entropy", "feature", "field",
    "filter", "function", "gradient", "inertia", "kernel", "label", "model",
    "normalization", "policy", "regression", "return", "shrinkage",
    "temperature", "tensor", "transformer", "vector",
}

# libraries used in item-6 API-surface failure-string scan
LIBS = ["PyTorch","TensorFlow","JAX","NumPy","Pandas","scikit-learn","sklearn","Keras",
        "SciPy","Matplotlib","Hugging Face","XGBoost","LightGBM","CatBoost"]


def math_skeleton(text):
    """Plain-text title form used by the flashcard answer contract.

    Line 3 cannot carry LaTeX, so a symbol-bearing title such as
    ``$\\mathbf{k}$-nearest neighbors`` is represented there as
    ``k-nearest neighbors``.  This intentionally mirrors wiki-builder's
    single-entry lint check.
    """
    s = (text or "").replace("$", "")
    for _ in range(4):
        new = re.sub(r"\\[A-Za-z]+\s*\{([^{}]*)\}", r"\1", s)
        if new == s:
            break
        s = new
    s = re.sub(r"\\[A-Za-z]+", "", s)
    s = s.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", s).strip()


_LEADING_ARTICLE_RE = re.compile(r"^(?:a|an|the)\s+", re.IGNORECASE)
_SUBJECT_BOUNDARY_RE = re.compile(r"^(?:$|[\s,(:;\u2013\u2014])")


def _first_letter_ci_equal(a, b):
    """Equality that is case-insensitive on the first letter only."""
    if a is None or b is None or len(a) != len(b):
        return False
    if not a:
        return True
    return a[0].lower() == b[0].lower() and a[1:] == b[1:]


def description_subject_forms(title):
    """Canonical title/base/math-skeleton forms accepted as item-7 subjects."""
    forms = []
    subjects = (base_term(title),) if has_parenthetical(title) else (title,)
    for subject in subjects:
        for form in (subject, math_skeleton(subject) if subject else None):
            form = (form or "").strip()
            if form and form not in forms:
                forms.append(form)
    return forms


def description_has_entity_subject(description, title):
    """Conservative mechanical floor for the entity-as-subject rule."""
    if not description or not title:
        return True  # Presence/title validity have their own findings.
    forms = description_subject_forms(title)
    starts = [description.strip()]
    article = _LEADING_ARTICLE_RE.match(starts[0])
    if article and not any(_LEADING_ARTICLE_RE.match(form) for form in forms):
        starts.append(starts[0][article.end():])
    for text in starts:
        if has_parenthetical(title):
            full = text[:len(title)]
            if (_first_letter_ci_equal(full, title)
                    and _SUBJECT_BOUNDARY_RE.match(text[len(title):])):
                continue
        for form in forms:
            if (_first_letter_ci_equal(text[:len(form)], form)
                    and _SUBJECT_BOUNDARY_RE.match(text[len(form):])):
                return True
    return False


_BOLD_OUTER_RE = re.compile(
    r"(?<!\*)\*\*((?:\$[^$\n]+\$|\*[^*\n]+\*|[^*\n])+?)\*\*(?!\*)")
_BOLD_PAREN_RE = re.compile(
    r"(?<!\*)\*\*(?P<bold>(?:\$[^$\n]+\$|\*[^*\n]+\*|[^*\n])+?)"
    r"\*\*(?!\*)(?:\s+algorithm)?\s*"
    r"\((?P<paren>[A-Za-z*][^()\n]{0,59})\)",
    re.IGNORECASE)
_PAREN_LEADIN_RE = re.compile(
    r"^(?:(?:short\s+for|originally\s+called|also\s+called|"
    r"also\s+known\s+as|known\s+as)|singular|plural|abbreviated|"
    r"formerly|n[ée]e|or)[\s,:]+", re.IGNORECASE)
_SHORT_FOR_PAREN_RE = re.compile(r"^short\s+for[\s,:]+", re.IGNORECASE)
_SCI_ABBREV_RE = re.compile(
    r"^[A-Z]\.\s*[a-z][A-Za-z.-]*(?:\s+[a-z][A-Za-z.-]*)*$")
_NON_NAME_PAREN_RE = re.compile(
    r"^(?:b\.|c\.|d\.|fl\.|r\.|e\.g|i\.e|cf\.|vs\.|see\s|a\s|an\s|the\s|"
    r"annual|ongoing)|\d{3,4}", re.IGNORECASE)


def _initial_forms(value):
    """Possible initial strings for a written-out name."""
    words = re.findall(r"[A-Za-z0-9]+", value or "")
    if not words:
        return set()
    stop = {"a", "an", "and", "of", "the", "to", "with"}

    def initial(word):
        return word if word.isupper() and 1 < len(word) <= 6 else word[:1]

    all_words = "".join(initial(word) for word in words).casefold()
    content = "".join(initial(word) for word in words
                      if word.casefold() not in stop).casefold()
    return {form for form in (all_words, content) if form}


def _acronym_counterpart(term, candidate):
    """Whether term/candidate has an acronym/full-form relationship."""
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


def _bold_parts(match):
    """Return visible text, style, and italic prefix for an outer bold span."""
    raw = match.group(1)
    if raw.startswith("*"):
        close = raw.find("*", 1)
        if close > 1:
            italic = raw[1:close]
            suffix = raw[close + 1:]
            return italic + suffix, ("full-italic" if not suffix else "mixed"), italic
    return raw, "plain", None


def organism_common_name_surfaces(entry):
    """Locally bound common names; link surfaces, never global aliases."""
    if not entry or entry.get("type") != "Organism":
        return []
    title = entry.get("title") or ""
    running_title = base_term(title) if has_parenthetical(title) else title
    opener = first_sentence(entry.get("prose") or "")
    names = bound_common_names(running_title, entry.get("desc") or "", opener)
    out = []
    for name in names:
        if name.casefold() not in {x.casefold() for x in out}:
            out.append(name)
    return out


def organism_common_name_bound(entry, display):
    """Whether an Organism explicitly equates its canonical title to label.

    This is the narrow item-18 carve-out.  A mention elsewhere in the body or
    an unsafe global alias is not enough: the description or opening sentence
    must make the title/common-name equation directly.
    """
    if not entry or entry.get("type") != "Organism":
        return False
    label = " ".join((display or "").split())
    if not re.fullmatch(r"[A-Za-z][A-Za-z'’ -]{0,49}", label):
        return False
    valid = set()
    for surface in organism_common_name_surfaces(entry):
        valid.add(surface.casefold())
        valid.add(plural_surface(surface).casefold())
    return label.casefold() in valid


def _clean_paren_name(raw):
    """Return a parenthetical name with a lexical lead-in and markup stripped."""
    value = " ".join((raw or "").split())
    value = _PAREN_LEADIN_RE.sub("", value)
    return value.replace("*", "").replace("_", "").strip()


def _clean_card_counterpart(raw, term, entry_type):
    """Return one of the three direct counterpart classes, or ``None``."""
    value = " ".join((raw or "").split())
    cleaned = _clean_paren_name(value)
    short_for = bool(_SHORT_FOR_PAREN_RE.match(value))
    scientific_abbreviation = bool(
        entry_type == "Organism"
        and taxon_title_parts(term)
        and scientific_abbreviation_matches(cleaned, taxon_title_parts(term)[0])
        and
        re.fullmatch(r"\*[^*\n]+\*", value.strip())
        and _SCI_ABBREV_RE.fullmatch(cleaned))
    if short_for or scientific_abbreviation or _acronym_counterpart(term, cleaned):
        return cleaned
    return None


def flashcard_primary_answer(title, aliases, opener, entry_type=""):
    """Return the exact plain-text term and any opener-bound counterpart."""
    term = base_term(title) if has_parenthetical(title) else (title or "")
    term = math_skeleton(term).strip()
    alias_keys = {fold_name(a) for a in aliases if a}
    counterpart = None
    opening_block = " ".join(
        line.strip() for line in (opener or "").splitlines())
    for match in _BOLD_PAREN_RE.finditer(opening_block):
        visible = math_skeleton(
            match.group("bold").replace("*", "").replace("_", "")).strip()
        if not _first_letter_ci_equal(visible, term):
            continue
        candidate = _clean_card_counterpart(
            match.group("paren"), term, entry_type)
        if candidate is None:
            continue
        try:
            candidate_slug = fold_name(_slug_stem(candidate))
        except _SlugError:
            continue
        if candidate_slug in alias_keys:
            counterpart = candidate
            break
    return term, counterpart


def flashcard_line3_fault(line3, title, aliases, opener, entry_type=""):
    """Explain a line-3 contract violation, or return ``None``."""
    expected_term, required_counterpart = flashcard_primary_answer(
        title, aliases, opener, entry_type)
    match = re.fullmatch(r"(?P<term>.*?)(?: \((?P<paren>[^()\n]+)\))?",
                         (line3 or "").strip())
    term = match.group("term") if match else (line3 or "").strip()
    counterpart = match.group("paren") if match else None
    if expected_term and term != expected_term:
        return 'the term must be exactly "%s" (same canonical casing)' % expected_term

    if counterpart is not None:
        if required_counterpart is None:
            return ('the parenthetical "%s" is not an opener-established, '
                    "alias-bound counterpart of the title" % counterpart)
        if counterpart != required_counterpart:
            return "the established counterpart must appear exactly as (%s)" % required_counterpart
    if required_counterpart is not None and counterpart != required_counterpart:
        return "the established counterpart must appear exactly as (%s)" % required_counterpart
    return None


# The conservative sentence counter intentionally mirrors
# lint_entry.count_sentences. It serves description item 7, flashcard line 1,
# and the legacy stub structure check; initials, decimals/version dots, common
# abbreviations, and taxonomic rank abbreviations do not create phantom
# sentences.
_ABBREVS = [
    "e.g.", "i.e.", "cf.", "et al.", "approx.", "vs.", "ca.", "c.", "fl.",
    "Dr.", "Prof.", "Mr.", "Mrs.", "Ms.", "St.", "Jr.", "Sr.", "Fig.",
    "No.", "b.", "d.", "r.", "U.S.", "U.K.", "var.", "subsp.", "ssp.",
    "sp.", "spp.", "aff.", "cv.", "fo.",
]
_ABBREV_RE = re.compile(
    r"(?:^|[^0-9A-Za-z])(?:%s)$"
    % "|".join(re.escape(a) for a in sorted(_ABBREVS, key=len, reverse=True)),
    re.IGNORECASE)
_INITIAL_RE = re.compile(r"(?:^|[^0-9A-Za-z'’])[A-Za-z]\.$")


def count_sentences(text):
    """Conservative sentence-boundary count for legacy stub structure."""
    compact = " ".join((text or "").split())
    count = 0
    for match in re.finditer(r"[.!?]+", compact):
        following = compact[match.end():match.end() + 1]
        if following and not following.isspace():
            continue
        if match.group(0) == ".":
            head = compact[max(0, match.end() - 16):match.end()]
            if _INITIAL_RE.search(head) or _ABBREV_RE.search(head):
                continue
        count += 1
    return count

def leftover_dollars(body):
    # `strip_fenced`, not a backtick-only regex: markdown fences a block with
    # ``` OR ~~~, `strip_fenced` has always understood both, and this scan
    # understood only the first — so a `~~~` shell listing containing `$HOME`
    # was counted, and item 12's class-1 remediation writes `\$` into the
    # middle of the listing, corrupting the command it shows.
    s = strip_fenced(body)                            # fenced code (``` and ~~~)
    s = re.sub(r"`[^`]*`", " ", s)                    # inline code
    s = s.replace(r"\$", " ")                          # escaped \$
    s = re.sub(r"\$\$.*?\$\$", " ", s, flags=re.S)    # display math
    s = re.sub(r"\$[^$\n]*\$", " ", s)               # inline math
    return s.count("$")                               # leftover literal $

# A standalone image-embed line (Obsidian ![[…png]] or Markdown ![](url))
# for the caption check. Detection runs against listing-masked text below;
# evidence and captions still come from the original lines.
EMB = re.compile(
    r"^\s*!\[\[[^\]\n]*\.(?:png|jpe?g|gif|svg|webp|tiff?|bmp|avif|ico)"
    r"(?:\|[^\]\n]*)?\]\]\s*$", re.IGNORECASE)


def _markdown_image_openers(text):
    """Yield image start and destination start for unescaped CommonMark syntax."""
    text = text or ""
    n = len(text)
    for match in re.finditer(r"!", text):
        start = match.start()
        backslashes, k = 0, start - 1
        while k >= 0 and text[k] == "\\":
            backslashes += 1
            k -= 1
        if backslashes % 2 or start + 1 >= n or text[start + 1] != "[":
            continue
        depth, i, escaped = 1, start + 2, False
        while i < n and text[i] != "\n":
            ch = text[i]
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        if depth == 0 and i + 1 < n and text[i + 1] == "(":
            yield start, i + 2


def markdown_image_spans(text):
    """Yield valid one-line Markdown image spans and full destinations."""
    for image_start, i in _markdown_image_openers(text):
        n = len(text)
        if i >= n or text[i] == "\n":
            continue
        destination = ""
        if text[i] == "<":
            j, escaped = i + 1, False
            while j < n and text[j] != "\n":
                ch = text[j]
                if ch == ">" and not escaped:
                    break
                escaped = ch == "\\" and not escaped
                if ch != "\\": escaped = False
                j += 1
            if j >= n or text[j] != ">":
                continue
            destination, i = text[i + 1:j], j + 1
        else:
            start, depth, escaped = i, 0, False
            while i < n and text[i] != "\n":
                ch = text[i]
                if escaped:
                    escaped = False; i += 1; continue
                if ch == "\\":
                    escaped = True; i += 1; continue
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    if depth == 0:
                        destination = text[start:i]
                        yield image_start, i + 1, destination
                        break
                    depth -= 1
                elif ch.isspace() and depth == 0:
                    destination = text[start:i]
                    break
                i += 1
            else:
                continue
            if i < n and text[i] == ")":
                continue
        while i < n and text[i] in " \t":
            i += 1
        if i < n and text[i] in "\"'":
            quote = text[i]; i += 1; escaped = False
            while i < n and text[i] != "\n":
                if text[i] == quote and not escaped:
                    i += 1; break
                escaped = text[i] == "\\" and not escaped
                if text[i] != "\\": escaped = False
                i += 1
        elif i < n and text[i] == "(":
            close = text.find(")", i + 1)
            if close < 0 or "\n" in text[i:close]:
                continue
            i = close + 1
        while i < n and text[i] in " \t":
            i += 1
        if i < n and text[i] == ")":
            yield image_start, i + 1, destination


def markdown_image_line(line):
    stripped = (line or "").strip()
    matches = list(markdown_image_spans(stripped))
    return bool(matches and matches[0][0] == 0 and matches[0][1] == len(stripped))
#: An Obsidian image EMBED and the filename it names, anywhere on a line:
#: `![[Doe_X_2025_fig_3.png]]`, with an optional `|width` display pipe. This is
#: the `--images` existence check's reader. Markdown `![](…)` embeds are
#: deliberately NOT here: a remote one is `item12/remote-image` (report-only,
#: and the form wiki-builder mandates for a URL), and a local one is not a form
#: wiki-builder writes.
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
    positions come from ``strip_code`` so fenced, indented and tab-indented
    listings cannot masquerade as tables.  Caption text comes from the original
    lines so real backticks remain visible to ``caption_faults``.
    """
    original_lines = body.split("\n")
    return original_lines, markdown_table_spans(strip_code(body))


_NAVIGATION_ONLY_LINK_RE = re.compile(
    r"(?:^|[.!?,;:]\s+|\(\s*|[—–-]\s+)"
    r"(?:see(?:\s+also)?|refer\s+to|consult)\s+\[\[", re.IGNORECASE)


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

def split_frontmatter(text):
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
    m = re.compile(r"(?m)^---$").search(text, 4)
    if m is None: return None, text, False
    after = text[m.end():]                        # starts at the fence line's own "\n" (or EOF)
    body = after.lstrip("\n")
    blank_after = (len(after) - len(body)) >= 2   # ≥2 leading newlines ⇒ a blank line after the fence
    return text[4:m.start()].strip("\n"), body, blank_after

# Key regex shared by parse_fm, the key_order scan and the item-2 quoting scan, so
# all three see the same keys.  It admits digits and hyphens ("f1-score:"); the old
# ^([A-Za-z_]+): silently dropped such keys, so an off-schema key with a digit in it
# was never reported and never counted as a duplicate.
FM_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:(.*)$")
FM_ITEM = re.compile(r"^\s*-(?:\s+(.*)|\s*)$")

def unquote(raw):
    """Decode a validated YAML scalar; malformed input raises ValueError."""
    return parse_scalar(raw)[0]

def split_flow(inner):
    """Split a valid non-nested flow-list payload.

    An empty payload is the valid list ``[]``. A comma-delimited empty element
    is invalid YAML and raises ``ValueError`` instead of being silently dropped.
    """
    if not inner.strip():
        return []
    out, buf, quote = [], [], None
    i = 0
    while i < len(inner):
        ch = inner[i]
        if quote:
            buf.append(ch)
            if quote == '"' and ch == "\\" and i + 1 < len(inner):
                i += 1
                buf.append(inner[i])
            elif ch == quote:
                if quote == "'" and i + 1 < len(inner) and inner[i + 1] == "'":
                    i += 1
                    buf.append(inner[i])
                else:
                    quote = None
        elif ch in "\"'" and not "".join(buf).strip():
            quote = ch
            buf.append(ch)
        elif ch == ",":
            out.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    out.append("".join(buf).strip())
    if any(x == "" for x in out):
        raise ValueError("flow list contains an empty comma-delimited item")
    return out


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


def parse_fm(fm, bad=None):
    """Frontmatter -> {key: str | [str]}.

    Handles the three list spellings wiki-builder writes: block form, flow form
    (`sources: ["stub"]`) and blank.  Flow form used to fall through to the
    scalar branch, so `sources: ["stub"]` parsed as the STRING `["stub"]` — no
    entry written that way was ever recognised as a stub, and a flow-form
    `aliases:` was invisible to alias-collision and backfill alike.

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

def source_stem(item):
    """``(stem, ext)`` of one `sources:` item, both case-folded.

    The pair is the identity of the DOCUMENT the item names, so everything that
    can vary without changing which document that is gets dropped: the `[[ ]]`
    wrapper, a `#page=N` anchor, a display pipe, and any folder qualification
    (`Sources/PDFs/X.pdf` and `X.pdf` are one file). Case AND Unicode
    normalization are folded because the documented vault lives on a filesystem
    that is insensitive to both, where `X.md`, `x.md` and the NFD spelling of
    either are all the same name.

    `("", "")` when the item carries no extension at all — the "stub" marker, or
    a malformed item whose missing extension is the form check's finding.
    """
    inner = (item or "").strip()
    if inner.startswith("[[") and inner.endswith("]]"): inner = inner[2:-2]
    inner = inner.split("|",1)[0]                       # display pipe
    inner = inner.split("#",1)[0]                       # #page=N anchor
    inner = inner.replace("\\","/").rsplit("/",1)[-1]   # folder qualification
    stem, dot, ext = inner.rpartition(".")
    if not dot: return "", ""
    # NFC as well as case, for the reason fold_name() gives: a `.pdf` item read
    # off an APFS disk is NFD and the `.md` twin typed into a note is NFC — one
    # document to the filesystem and to Obsidian, two unequal strings here, so
    # the item4 pair went unreported. §7 requires this to agree exactly with
    # wiki-builder's lint_entry.source_stem(); keep the two lines identical.
    return (unicodedata.normalize("NFC", stem.strip()).lower(),
            unicodedata.normalize("NFC", ext.strip()).lower())

WIKILINK = re.compile(r"(?<!\!)\[\[([^\]\|]+)(?:\|([^\]]+))?\]\]")  # (?<!!) excludes ![[embeds]]
ANYLINK  = re.compile(r"!?\[\[[^\]]*\]\]")                          # links + embeds, for masking


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

#: A Flashcards heading, anchored to a whole line.  A substring `find()`
#: matched the tail of a `### Flashcards` heading (mis-reporting a present
#: separator as missing) and a mid-line mention of the literal text, splitting
#: the entry's prose at a byte inside a sentence.  TOLERANT on purpose, the
#: way Obsidian renders headings (≤3 leading spaces, `##`/`###`, any run of
#: spaces/tabs before the word): every one of those spellings shows the reader
#: a Flashcards section, so treating a non-canonical one as MISSING prescribed
#: adding a second section beside the one Obsidian already renders.  The
#: canonical spelling is `## Flashcards` exactly; a tolerated variant gets its
#: own item19 finding ("fix the heading"), never "add the section".
_FLASH_HEAD_LINE = re.compile(r"^ {0,3}#{2,3}[ \t]+Flashcards[ \t]*$")
_FLASH_HEAD_CANON = re.compile(r"^## Flashcards[ \t]*$")
_RELATED_HEAD_LINE = re.compile(r"^ {0,3}\*\*Related:\*\*(?:\s|$)")


def section_marker_indexes(body):
    """Return raw lines plus rendered Related/Flashcards marker indexes.

    Fenced samples are blanked with line count preserved. A slightly
    noncanonical marker is still treated as present so the repair normalizes
    that marker instead of adding a duplicate section beside it.
    """
    lines = body.split("\n")
    masked = strip_fenced(body).split("\n")
    related = [i for i, line in enumerate(masked)
               if _RELATED_HEAD_LINE.match(line)]
    flashcards = [i for i, line in enumerate(masked)
                  if _FLASH_HEAD_LINE.match(line)]
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
    rel = lines[rel_i] if rel_i is not None else ""
    cut = len(body)
    if rel_i is not None: cut = offs[rel_i]
    fc = offs[flash_i] if flash_i is not None else -1
    if fc != -1 and fc < cut: cut = fc
    flash_head = lines[flash_i] if flash_i is not None else ""
    return body[:cut], rel, (body[fc:] if fc != -1 else ""), fc, flash_head

# `importance` is a LEGACY key — removed from wiki-builder's schema, never written on a new entry,
# but still present (populated) on every entry generated before the removal. Nothing strips it and
# nothing flags it. It stays in CANON so a legacy entry carrying it in its historical slot is not
# reported as an "unexpected frontmatter key" or as out of schema order; it is deliberately absent
# from the required-key checks and from the never-quoted list below.
CANON = ["title","type","aliases","sources","created","updated","description","tags","importance","parents","read"]

#: The keys that must be PRESENT on every entry, stub included — CANON minus
#: the one optional key (`aliases`) and the retired one (`importance`).  This
#: is wiki-builder's `lint_entry.MANDATORY_KEYS`, in the same order and with
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
#: failure this field cannot afford.  CONVENTIONS.md §2d.
READ_BOOLEANS = {"true", "false"}

#: The spellings of YAML null a `read:` key can carry: a bare key, `null` in any
#: case, and `~`.  These are NOT a type error — there is no value in them to
#: retype — so they route with the missing key, not with `read: yes`.  See the
#: `read:` block in `scan()`.
READ_NULLS = {"", "null", "~"}
VALID_TYPES = [
    "Concept", "Person", "Organization", "Dataset", "Software", "Device",
    "Event", "Standard", "Gene/Protein", "Organism", "Chemical", "Reaction",
    "Place", "Work", "Quote",
]
VALID_TAGS = {"mathematics","statistics","physics","chemistry","biology","earth-science",
 "medicine","engineering","computer-science","psychology","sociology","anthropology",
 "economics","finance","political-science","linguistics","history","philosophy","literature","law",
 "business","entrepreneurship","education","architecture","art","music","machine-learning"}  # the 27-discipline enum
TAG_ALIASES = {"ml":"machine-learning","ai":"machine-learning","artificial-intelligence":"machine-learning",
 "cs":"computer-science","comp-sci":"computer-science","poli-sci":"political-science",
 "econ":"economics","bio":"biology","chem":"chemistry","phys":"physics",
 "stats":"statistics","math":"mathematics","maths":"mathematics","lit":"literature",
 "investing":"finance","trading":"finance",
 "startup":"entrepreneurship","startups":"entrepreneurship"}  # safe auto-expansions

#: Frontmatter keys that are Obsidian's own, not this schema's. They are NOT
#: `item2` "unexpected key" findings: item 2 is a class-1 fix-in-place, and the
#: only determinate reading of "fix an unexpected key in place" is to delete it
#: — which throws away app/publish configuration the USER set, in a field this
#: plugin never writes and cannot reconstruct. They route report-only through
#: `item2/obsidian-key` instead. A genuinely off-schema key (`mood:`, a
#: stacked-merge scar) is still a plain `item2`.
OBSIDIAN_KEYS = {"cssclasses", "cssclass", "publish", "permalink", "cover",
                 "image", "banner", "icon"}


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

_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")


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
            # Retain nested/list fences while rejecting a more-indented sample
            # as the closer of a top-level fence. Tabs count as four columns.
            fence_indent = max(3, len(ln[:m.start(1)].expandtabs(4)))
            out.append("")
            continue
        if (m and m.group(1)[0] == fence[0]
                and len(m.group(1)) >= len(fence) and not m.group(2).strip()
                and len(ln[:m.start(1)].expandtabs(4)) <= fence_indent):
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


def plural_surface(title):
    """The plural SURFACE form of a title: only the HEAD (last) token inflects.

    `pluralize` is a one-TOKEN function (shared/scripts/plurals.py); handing it
    a whole title fails every irregular in its table, because a phrase is never
    a key in it — "Confusion matrix" came back "Confusion matrixes" (the final
    `x` read as a sibilant) and "Hypothesis" as "Hypothesises".  So the real
    plural of an irregular-headed title never entered the surface map, and no
    entry could ever be backfilled from a text that spells it correctly.
    Capitalisation is irrelevant here — the surface map is keyed lowercased —
    but the table lookups are lowercase-only, so the head is folded for them.
    """
    m = re.search(r"([A-Za-z]+)([^A-Za-z]*)$", title or "")
    if not m:
        return title
    head = m.group(1)
    plural = pluralize(head.lower())
    if head[:1].isupper():                       # keep the title's own casing
        plural = plural[:1].upper() + plural[1:]
    return title[:m.start(1)] + plural + m.group(2)

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
        # excluding only "entropy" still proposed [[entropy|entropies]].
        if s in COMMON_NOUNS or fold_name(surf_map[s]) in COMMON_NOUNS: continue
        m = list(WORD.finditer(s))
        if not m: continue
        key = " ".join(t.group(0) for t in m)
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


def _scan_surfaces(text, by_tokens, maxwords):
    """Yield ``(surface, matched_text)`` for every verbatim surface hit in `text`.

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
        yield surface, text[start:end]


def build_backfill(entries, surf_map):
    """Task 2 worklist: bare-text mentions of another entry's surface forms."""
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
        if e["is_stub"]: continue  # Task 2 backfill operates on full entries only
        # Table links are prohibited and will be reduced to plain text by item
        # 10, so they cannot prove that the entry already has a durable prose
        # link. Mask the shared spans before both the existing-link inventory
        # and the bare-surface scan; otherwise a bad cell link suppresses a
        # legitimate proposal for a later prose mention.
        prose = mask_line_spans(
            strip_code(e["prose"]), e.get("table_spans", ()))
        linked = set()
        for link in WIKILINK.finditer(prose):
            target = link.group(1).split("#", 1)[0].split("^", 1)[0].strip()
            target = target.replace("\\", "/").rsplit("/", 1)[-1]
            if target.lower().endswith(".md"):
                target = target[:-3]
            key = fold_name(target)
            owner = files.get(key)
            if owner is None and len(alias_owners.get(key, ())) == 1:
                owner = next(iter(alias_owners[key]))
            if owner is not None:
                linked.add(owner)
        masked = ANYLINK.sub(lambda m: " "*len(m.group(0)), prose)
        # Blank every line a link may not be written on, for the same reason in
        # each case: the backfill worklist proposes linking the FIRST occurrence,
        # so a first occurrence sitting somewhere unlinkable is an un-actionable
        # item that also HIDES the linkable occurrence further down.
        #   * whole-line italic captions — item 12 forbids wikilinks in captions;
        #   * markdown TABLE ROWS — item 10 forbids wikilinks in table cells;
        #   * fenced code blocks — a listing is shown, not asserted, and a link
        #     written inside one renders as literal `[[...]]` text.
        masked = "\n".join(
            ("" if re.match(r"^\s*\*(?!\*).*\*\s*$", ln) else ln)
            for ln in masked.split("\n"))
        proposed = set()
        for surface, matched in _scan_surfaces(masked, by_tokens, maxwords):
            tgt = surf_map.get(surface)
            if not tgt or tgt == sl or tgt in proposed: continue
            if tgt in linked: continue
            proposed.add(tgt)
            backfill.append((sl, tgt, matched, surface))
    return backfill


def iter_entry_files(wiki, on_error=None):
    """Every `.md` under `wiki`, RECURSIVELY and sorted (dot-dirs skipped).

    `os.listdir` was flat, so an entry filed in `Wiki/sub/` was invisible to the
    whole scan — and every wikilink pointing at it was reported as dangling.
    wiki-builder's vault_index.py has always walked recursively; this matches it.
    """
    out = []
    seen_dirs = set()
    for dirpath, dirnames, filenames in os.walk(wiki, followlinks=True, onerror=on_error):
        # followlinks, because a synced or shared subfolder under Wiki/ is a
        # symlink in plenty of real vaults, and skipping it made every link
        # into it read as dangling -- whose repair would unlink a working
        # reference. `seen_dirs` keeps a symlink loop from walking forever.
        try:
            key = os.stat(dirpath).st_ino, os.stat(dirpath).st_dev
        except OSError:
            key = dirpath
        if key in seen_dirs:
            dirnames[:] = []
            continue
        seen_dirs.add(key)
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in filenames:
            if name.lower().endswith(".md") and not name.startswith("."):
                out.append(os.path.join(dirpath, name))
    return sorted(out)


#: Extensions a wikilink may legitimately name that are not wiki entries: the
#: document forms CONVENTIONS 6/7 blesses in a `sources:` list. A link to one
#: is not an entry dangler and must never be unlinked as one.
_DOC_EXTS = {".pdf", ".epub", ".docx", ".md", ".html", ".txt"}


_IMAGE_ALLOWED_HIDDEN = {".figure-manifest.tsv", ".figure-review.txt", ".DS_Store"}


def _looks_temporary_image_path(relative):
    """Whether an image-folder path has a recognizable staging name."""
    for part in relative.replace("\\", "/").split("/"):
        low = part.lower()
        if low.startswith((".tmp", ".temp", ".trash")):
            return True
        if ".dltmp" in low:
            return True
        if re.search(r"\.(?:tmp|temp|part|partial|download|crdownload)(?:\.\d+)?$", low):
            return True
    return False


def image_index(images):
    """Return folded image basenames and report-only folder-layout findings.

    Folded, not `os.path.isfile`, for the reason `fold_name` gives: the
    documented vault sits on a case- and normalization-insensitive volume, so
    an entry embedding `![[Doe_X_2025_Fig_2.png]]` against a file written
    `doe_x_2025_fig_2.png` displays the image. An `isfile` probe on the
    case-SENSITIVE Linux filesystem the plugin is tested on says it is missing,
    and the finding tells the user to fix an embed that already works.

    Walked recursively although CONVENTIONS §1 makes `Sources/Images/` flat:
    Obsidian resolves an embed by basename wherever the file sits, so a user
    who has nested a subfolder gets no false "missing" findings out of it.
    Those nested paths, and recognizable temporary/staging artifacts, are
    returned separately for the run report.  They never authorize deletion.
    The two PDF ownership sidecars are intentional; `.DS_Store` is ignored OS
    metadata rather than a plugin artifact.
    """
    if images is None:
        return None, []
    names, findings = set(), []
    root = os.path.abspath(images)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        filenames.sort()
        rel_dir = os.path.relpath(dirpath, root)
        # Record directories when their parent exposes them, including a
        # symlinked directory that os.walk (correctly) does not follow.
        for dirname in dirnames:
            relative_dir = (dirname if rel_dir == "."
                            else os.path.join(rel_dir, dirname))
            relative_dir = relative_dir.replace(os.sep, "/")
            temporary = _looks_temporary_image_path(relative_dir)
            findings.append({
                "path": relative_dir,
                "kind": "temporary-artifact" if temporary else "nested-directory",
                "message": (
                    "temporary/staging directory under Sources/Images; report only — "
                    "do not delete without user approval and provenance"
                    if temporary else
                    "nested directory under the flat Sources/Images folder; report only — "
                    "do not move or delete without user approval and provenance"),
            })
        for name in filenames:
            relative = (name if rel_dir == "." else os.path.join(rel_dir, name))
            relative = relative.replace(os.sep, "/")
            # Keep recursively discovered visible basenames in the resolver so
            # the layout finding never creates a false missing-image finding.
            if not name.startswith("."):
                names.add(fold_name(name))
            if rel_dir == "." and name in _IMAGE_ALLOWED_HIDDEN:
                continue
            temporary = _looks_temporary_image_path(relative)
            if temporary:
                kind = "temporary-artifact"
                message = ("temporary/staging artifact under Sources/Images; report only — "
                           "do not delete without user approval and provenance")
            elif rel_dir != ".":
                kind = "nested-file"
                message = ("file is nested under the flat Sources/Images folder; report only — "
                           "do not move or delete without user approval and provenance")
            else:
                continue
            findings.append({"path": relative, "kind": kind, "message": message})
    findings.sort(key=lambda finding: (finding["path"], finding["kind"]))
    return names, findings


MOC_TREE_START = "<!-- wiki-linter:moc-tree:start -->"
MOC_TREE_END = "<!-- wiki-linter:moc-tree:end -->"


def moc_marker_state(path):
    """Describe one discipline MOC's ownership-marker state without writing it.

    Task 3 permits an automatic tree replacement only when the file contains
    one unique, ordered, unindented marker pair. A nonempty file with no
    marker is the documented legacy-migration state; any partial, duplicate,
    reversed, indented, or inline marker use is malformed. Keep this
    diagnostic separate from ``problems``: observing a state never grants
    permission to migrate or repair the MOC.
    """
    result = {
        "path": os.path.abspath(path),
        "state": "missing",
        "start_markers": 0,
        "end_markers": 0,
    }
    if not os.path.exists(path):
        return result
    try:
        with open(path, encoding="utf-8-sig") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        result["state"] = "unreadable"
        result["error"] = "%s: %s" % (type(exc).__name__, exc)
        return result

    result["start_markers"] = text.count(MOC_TREE_START)
    result["end_markers"] = text.count(MOC_TREE_END)
    if not text.strip():
        result["state"] = "empty"
        return result
    if not result["start_markers"] and not result["end_markers"]:
        result["state"] = "legacy-unmarked"
        return result

    lines = text.splitlines()
    exact_start = [i for i, line in enumerate(lines) if line == MOC_TREE_START]
    exact_end = [i for i, line in enumerate(lines) if line == MOC_TREE_END]
    if (result["start_markers"] == result["end_markers"] == 1
            and len(exact_start) == len(exact_end) == 1
            and exact_start[0] < exact_end[0]):
        result["state"] = "marked"
    else:
        result["state"] = "malformed-marker"
    return result


def scan(wiki, images=None):
    """Parse every entry in the `wiki` folder; return the Step 0 model as a dict.

    `images` is the vault's `Sources/Images/` folder, or None. CONVENTIONS §1
    names this skill the validator of the embeds pointing there, and until
    `--images` existed nothing in the skill had a path to that folder at all:
    an entry embedding a figure that is not on disk produced an empty problem
    list here while paper-summarizer's `note_lint.py --images` reported the
    same embed on an `Articles/` note. It is also the detector CONVENTIONS §1a
    relies on for `Wiki/` — a source rename renames every figure with it, and
    the embeds left pointing at the old stem are silent otherwise.
    """
    img_fold, image_folder_findings = image_index(images)
    vault_root = os.path.dirname(os.path.abspath(wiki))
    entries, problems = {}, []
    # Every slug whose FILE is on disk, whether or not it parsed as an entry.
    # A link to an unparseable file resolves in Obsidian, so it is not dangling
    # -- and stubbing it would write over the file.
    on_disk = set()
    seen_paths = {}
    paths_by_basename = {}
    path_records = {}             # folded Wiki-relative path -> parsed record or None
    ambiguous_files = set()
    def walk_error(exc):
        location = os.path.relpath(exc.filename, wiki) if exc.filename else "."
        problems.append((location, "item0", "unreadable wiki directory: %s" % exc))

    for path in iter_entry_files(wiki, on_error=walk_error):
        fn = os.path.basename(path)
        sl = fn[:-3]
        rel = os.path.relpath(path, wiki)
        path_key = entry_link_path_key(rel)
        paths_by_basename.setdefault(fold_name(sl), set()).add(path_key)
        path_records[path_key] = None
        # Obsidian resolves a wikilink by basename, case-insensitively, so two
        # files with the same stem in different folders — INCLUDING two stems
        # that differ only in case or Unicode normalization, which are one name
        # to Obsidian and to the vault's own APFS volume — are one slug with
        # two bodies. Report, keep the first.
        keep_entry = fold_name(sl) not in seen_paths
        if not keep_entry:
            ambiguous_files.add(fold_name(sl))
            prev_sl, prev_rel = seen_paths[fold_name(sl)]
            problems.append((sl,"item5",f'slug "{sl}" occurs in two files ({prev_rel} and {rel}'
                                        f'{"" if prev_sl == sl else ", stems differing only in case/normalization"}) — '
                                        f'Obsidian resolves [[{sl}]] to only one of them; rename or merge'))
        else:
            seen_paths[fold_name(sl)] = (sl, rel)
        # One unreadable file must not take the scan down with it: an unguarded
        # read() on a binary .md / dangling symlink / unreadable file raised, and
        # the traceback left stdout EMPTY, so the caller got no scan at all.
        try:
            # utf-8-SIG strips a BOM, which would otherwise sit in front of
            # the opening `---` and report a valid entry as having no
            # frontmatter.  Universal newlines are load-bearing too and are why
            # nothing here re-spells CRLF: text mode translates \r\n to \n on
            # read, so every line-oriented check below sees one line ending.
            # Reading with `newline=""` would leave a \r on every parsed value
            # AND blind the blank-line-after-frontmatter probe, which counts
            # leading "\n" and would see "\r\n\r\n".
            with open(path, encoding="utf-8-sig") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError) as exc:
            problems.append((sl,"item0",f"unreadable: {type(exc).__name__}: {exc}"))
            on_disk.add(sl)
            continue
        fm_raw, body, blank_after = split_frontmatter(text)
        if fm_raw is None:
            problems.append((sl,"item1","no YAML frontmatter"))
            on_disk.add(sl)
            continue
        _fm_bad = []
        fm = parse_fm(fm_raw, _fm_bad)
        for _ln in _fm_bad:
            problems.append((sl,"item1",
                             f"unparseable frontmatter line: {_ln.strip()[:60]!r}"))
        def _scalar(k):                    # a key written as a list is not a scalar
            v = fm.get(k, "")
            return v if isinstance(v, str) else ""
        sources = fm.get("sources") or []
        if isinstance(sources, str): sources = [sources]
        is_stub = (sources == ["stub"])
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
        tags_raw = fm.get("tags", []) if isinstance(fm.get("tags"), list) else ([fm["tags"]] if fm.get("tags") else [])
        tags_raw = [t.strip() for t in tags_raw if isinstance(t, str) and t.strip()]  # decoded, non-null tags
        tag_slugs = [t.lstrip("#").strip() for t in tags_raw]          # discipline slugs without the # prefix, for MOC/hierarchy use
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
        record = dict(slug=sl, title=title, aliases=aliases,
                      aliases_all=aliases_all,
                      aliases_present=aliases_present,
                      aliases_is_list=aliases_is_list, type=_scalar("type"),
                      tags_raw=tags_raw, tag_slugs=tag_slugs, is_stub=is_stub,
                      sources=sources, sources_is_list=isinstance(fm.get("sources"), list),
                      body=body, prose=prose, rel=rel, fcsec=fcsec, desc=desc,
                      created=created, updated=updated, blank_after=blank_after,
                      parents=parents_all,
                      parents_present=parents_present,
                      parents_is_list=parents_is_list,
                      parents_spelling=parents_spelling,
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

    # fold_name(slug) -> on-disk slug, for every comparison that asks "is this
    # the same FILE?" — Obsidian and the vault's APFS volume both resolve
    # case- and normalization-insensitively, so [[ROC-curve]] against
    # roc-curve.md is a resolving link with a cosmetic defect, not a dangler.
    fold_of = {}
    for _sl in entries:
        fold_of.setdefault(fold_name(_sl), _sl)
    # Files on disk that did NOT parse into `entries`: a link to one of these
    # resolves in Obsidian, so it is not a dangler and must never be unlinked.
    on_disk_fold = {fold_name(_sl) for _sl in on_disk} - set(fold_of)
    # fold_name(alias) -> (owning slug, the alias as spelled). Obsidian
    # resolves [[tpr]] to the entry whose `aliases:` carries "tpr" when no FILE
    # answers to that name -- references/writing.md calls an alias an
    # alternative slug, and wiki-builder's find_collisions.build_targets probes
    # aliases for exactly that reason. A file always wins over an alias, so
    # this is consulted only after the slug and on-disk lookups, and it is not
    # a fallback for them. Keep ambiguous owners separate: item 18 reports
    # the collision, but item 10 must not choose a rewrite target for it.
    alias_of = {}
    ambiguous_aliases = set()
    for _sl, _e in sorted(entries.items()):
        for _a in _e["aliases"]:
            _k = fold_name(_a)
            if _k:
                if _k in alias_of and alias_of[_k][0] != _sl:
                    ambiguous_aliases.add(_k)
                alias_of.setdefault(_k, (_sl, _a))

    _wiki_prefixes = {
        fold_name(os.path.basename(os.path.abspath(wiki))) + "/",
        "wiki/",
    }
    _moc_canonical_by_fold = {}
    for _entry in entries.values():
        if _entry["is_stub"]:
            continue
        for _discipline in _entry["tag_slugs"]:
            _discipline = _discipline.lower()
            if _discipline in VALID_TAGS:
                _moc_slug = _discipline + "-moc"
                _moc_canonical_by_fold[fold_name(_moc_slug)] = _moc_slug

    def _resolve_entry_file(raw_target):
        """Resolve a Wiki file target without discarding path qualification.

        Returns ``(record, status, path_key)``. ``record`` is a parsed path
        record when available; ``status`` is ``parsed``, ``unparsed``,
        ``ambiguous``, or ``missing``. A bare basename with multiple owners is
        ambiguous even if one owner is at the Wiki root. A qualified target may
        use a vault-root prefix (``Wiki/a/foo``) or a unique suffix
        (``a/foo``), and therefore remains resolvable under a basename clash.
        """
        basename_key = entry_link_key(raw_target)
        owners = paths_by_basename.get(basename_key, set())
        if not owners:
            return None, "missing", None

        target_key = entry_link_path_key(raw_target)
        lookup = target_key
        for prefix in _wiki_prefixes:
            if lookup.startswith(prefix):
                lookup = lookup[len(prefix):]
                break
        if "/" not in target_key:
            if len(owners) != 1:
                return None, "ambiguous", None
            owner = next(iter(owners))
        elif lookup in owners:
            owner = lookup
        else:
            candidates = {candidate for candidate in owners
                          if candidate.endswith("/" + lookup)}
            if len(candidates) != 1:
                return None, ("ambiguous" if candidates or len(owners) > 1
                              else "missing"), None
            owner = next(iter(candidates))

        record = path_records.get(owner)
        return record, ("parsed" if record is not None else "unparsed"), owner

    _work_surfaces = set()
    for _entry in entries.values():
        if _entry.get("type") != "Work":
            continue
        _title = _entry.get("title") or ""
        for _surface in ([_title, base_term(_title)] +
                         list(_entry.get("aliases", []))):
            _surface = " ".join((_surface or "").split()).strip()
            if not _surface:
                continue
            _work_surfaces.add(_surface)
            if "-" in _surface:
                _work_surfaces.add(_surface.replace("-", " "))
    _work_surfaces = sorted(_work_surfaces, key=lambda value: (-len(value), value))

    def _authors_phrase_names_work(text, match):
        """Whether ``the author(s) of ...`` names an existing Work entry."""
        after = text[match.end():]
        of_match = re.match(r"\s+of\s+", after, re.IGNORECASE)
        if not of_match:
            return False
        remainder = after[of_match.end():]
        linked = WIKILINK.match(remainder)
        if linked is not None and linked.start() == 0:
            target = linked.group(1)
            record, status, _path = _resolve_entry_file(target)
            key = entry_link_key(target)
            if (record is None and status == "missing"
                    and key not in ambiguous_aliases and key in alias_of):
                record = entries.get(alias_of[key][0])
            return bool(record is not None and record.get("type") == "Work")

        # Work titles are often italicized in prose. Strip only a leading
        # emphasis delimiter; the boundary after the matched surface may be
        # the closing delimiter itself.
        visible = re.sub(r"^[*_]{1,3}", "", remainder)
        return any(re.match(re.escape(surface) + r"(?![A-Za-z0-9])",
                            visible, re.IGNORECASE)
                   for surface in _work_surfaces)

    for sl,e in entries.items():
        fm_raw, is_stub, title = e["fm_raw"], e["is_stub"], e["title"]
        # ---- item 5: slug == filename; bare-slug common noun ----
        _newslug = slug(title) if title else ""
        if title and not _newslug:
            problems.append((sl,"item5",f'title "{title[:60]}" cannot be slugged automatically (it reduces to '
                                        f'the empty slug, or its slug exceeds the filename budget) — ask the '
                                        f'user for an ASCII-representable, shorter title; DO NOT rename the file'))
        elif title and _newslug != sl:
            problems.append((sl,"item5",f'title "{title}" slugs to "{_newslug}" ≠ filename'))
        if "-" not in sl and sl in COMMON_NOUNS:
            problems.append((sl,"item5",f'bare-slug common noun "{sl}" — qualify the title'))
        # ---- item 2: field order, required keys, duplicate keys, quoting ----
        known = [k for k in e["key_order"] if k in CANON]
        if [CANON.index(k) for k in known] != sorted(CANON.index(k) for k in known):
            problems.append((sl,"item2","fields out of schema order: "+", ".join(e["key_order"])))
        for k in e["key_order"]:
            if k in CANON or k == "roots":        # roots gets a dedicated migration message below
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
            problems.append((sl,"item2",f'unexpected frontmatter key "{k}"'))
        if len(e["key_order"]) != len(set(e["key_order"])):
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
        # `tags` and `read` keep their own messages below (a missing `tags:`
        # may be a roots→tags migration, and a missing `read:` is report-only).
        for _k in MANDATORY_KEYS:
            if _k in e["key_order"] or _k in ("tags", "read", "title"):
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
        # read: — the user's review checkbox (CONVENTIONS.md §2d).  Four
        # distinct states, and they route three different ways, which is why
        # they are three messages rather than one:
        #   absent      -> REPORT ONLY.  The linter never writes this field, and
        #                  the only value it could supply is `false`, which would
        #                  mark an entry the user has already read as unread —
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
                             "missing read: key — the user's review checkbox. Report it; "
                             "never write a value, since `false` would mark an entry they "
                             "have already read as unread"))
        elif _read_raw.strip().lower() in READ_NULLS and not has_block_items(fm_raw, "read"):
            problems.append((sl,"item2/read-null",
                             'read: is present but carries no value (%s) — YAML null, not a '
                             'boolean, so Obsidian shows the checkbox unticked while the entry '
                             'records no answer at all. Report it; DO NOT FIX. There is no '
                             'value here to preserve, so writing `false` would invent one and '
                             'clear a tick the user may have set — the same harm, and the same '
                             'report-only class, as a missing read: key'
                             % ("bare `read:`" if not _read_raw.strip()
                                else "`read: %s`" % _read_raw.strip())))
        elif not isinstance(_read_value, str) or _read_value.lower() not in {"true", "false", "yes", "no", "0", "1"}:
            problems.append((sl,"item2/read-unknown",
                             'read: has no recognizable boolean answer (%r) -- REPORT ONLY, '
                             'DO NOT FIX. Neither true nor false can be inferred safely; '
                             'leave this user-owned state unresolved and continue the run' % _read_raw))
        elif _read_style != "bare" or _read_value.lower() not in READ_BOOLEANS:
            problems.append((sl,"item2/read-type",
                             'read: must be a bare boolean (`true` / `false`), not %r — a '
                             'quoted "false" is a string, and Obsidian renders any non-empty '
                             'string in a checkbox property as permanently checked; `yes`/`no` '
                             'and `0`/`1` are the same field written in the wrong spelling. '
                             'Fix the spelling, keep the value' % _read_raw))
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
                    r"\[\[([^/\\\[\]\|#^]+)\]\]", _parent.strip())
                if not _parent_match:
                    problems.append((sl, "item2/parents-form",
                                     f'parents: item "{_parent}" must be one bare '
                                     "canonical wikilink with no path, display label, "
                                     "heading, block anchor, or `.md` suffix"))
                    continue
                _parent_target = _parent_match.group(1)
                _parent_key = fold_name(_parent_target)
                _parent_canonical = None
                _parent_record, _parent_status, _parent_path = \
                    _resolve_entry_file(_parent_target)
                if (_parent_status == "parsed" and _parent_record is not None
                        and _parent_key not in _moc_canonical_by_fold):
                    _parent_canonical = _parent_record["slug"]
                elif (_parent_status == "missing"
                      and _parent_key not in ambiguous_aliases
                      and _parent_key in alias_of
                      and _parent_key not in _moc_canonical_by_fold):
                    _parent_canonical = alias_of[_parent_key][0]
                elif (_parent_key in _moc_canonical_by_fold
                      and _parent_status == "missing"):
                    _parent_canonical = _moc_canonical_by_fold[_parent_key]
                if (_parent_canonical is not None
                        and _parent_target != _parent_canonical):
                    problems.append((
                        sl, "item2/parents-form",
                        f'parent target "{_parent_target}" resolves to '
                        f'"{_parent_canonical}" — use the canonical bare slug'))
                _parent_identity = fold_name(
                    _parent_canonical if _parent_canonical is not None
                    else _parent_target)
                if _parent_identity in _parent_seen:
                    problems.append((sl, "item2/parents-form",
                                     f'parent "{_parent}" is listed more than once'))
                else:
                    _parent_seen[_parent_identity] = _parent
        # No missing-importance: check — the field left the schema (see CANON above).
        if "roots" in e["key_order"]:         # the schema replaced roots: with tags: — one targeted message
            if "tags" in e["key_order"]:
                problems.append((sl,"item2",'stale roots: key — the schema replaced roots: with tags:; remove roots: (tags: is already present)'))
            else:
                problems.append((sl,"item2",'old roots: key, no tags: key — migrate roots → tags (one or more #-prefixed discipline slugs from the 27-enum, not a wikilink)'))
        elif "tags" not in e["key_order"]:
            problems.append((sl,"item2","missing tags: key (mandatory — present even when blank on a full entry)"))
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
                if k in ("title","description") and val and _style != "double":
                    problems.append((sl,"item2",f'{k} must be double-quoted'))
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
                            if _iv_style != "double":
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
                    if iv and _iv_style != "double":
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
        # created > updated is REPORT-ONLY, not a fixable violation: wiki-linter never writes created:/updated:
        # (see Dates), so filing it as a lint problem would re-report the same entries forever with nothing the
        # linter can do. Its own item key routes it to the nonblocking report-only bucket instead.
        # Compared as DATES, never as strings — the strings are only interchangeable
        # with the dates once both are known to be zero-padded, which is what _valid checks.
        _created_d, _updated_d = _valid(e["created"]), _valid(e["updated"])
        if _created_d is not None and _updated_d is not None and _created_d > _updated_d:
            problems.append((sl,"item3/report-only",f'created {e["created"]} > updated {e["updated"]} — impossible ordering (updated is the last merge date, so it cannot precede creation); DO NOT FIX, leave unresolved and report without blocking the run'))
        # ---- item 4: sources format ----
        if not e["sources"]:
            problems.append((sl,"item4","sources: is empty; every full entry needs a local source"))
        elif not e["sources_is_list"]:
            problems.append((sl,"item4","sources: must be a list, not a scalar"))
        for i,src in enumerate(e["sources"]):
            if src is None:
                problems.append((sl,"item4","sources: contains a null or invalid item"))
                continue
            if src == "stub":
                if e["sources"] != ["stub"]:
                    problems.append((sl,"item4",'"stub" marker must be the sole source item'))
                continue
            if re.fullmatch(r"\[\[[^\[\]\r\n|#]+\.(?i:pdf)#page=[1-9][0-9]*\]\]", src):
                continue
            if re.fullmatch(r"\[\[[^\[\]\r\n|#]+\.(?i:md)\]\]", src):
                continue
            problems.append((sl,"item4",f'source must be [[Name.pdf#page=N]] with a positive '
                             f'physical page number, or [[Name.md]] without an anchor; '
                             f'URLs, display labels and incomplete wikilinks are invalid: {src}'))
        _source_values = [src for src in e["sources"] if src is not None]
        for _duplicate_source in sorted({
                src for src in _source_values if _source_values.count(src) > 1}):
            problems.append((
                sl, "item4",
                f'source "{_duplicate_source}" is listed '
                f'{_source_values.count(_duplicate_source)} times — keep one '
                "exact citation"))
        # No two sources: items may name the same DOCUMENT. paper-summarizer writes a note into
        # Articles/ for every PDF it summarises, so one document sits in the vault under two
        # names — Sources/PDFs/X.pdf and Articles/X.md — and both are legal sources:
        # values. A same-stem clipping may instead be an independent source, so the match
        # needs the markdown note's provenance before any source may be removed.
        # Only a stem collision ACROSS the two extensions counts — an entry may
        # legitimately cite several distinct PDFs and several distinct clippings — and stems compare case- and NFC-insensitively (the documented
        # vault lives on a filesystem that is insensitive to both; see fold_name).
        pdf_by_stem, md_items = {}, []
        for src in e["sources"]:
            if src == "stub": continue
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
        if e["type"] != "Software":
            if re.match(r"^[A-Za-z_][\w]*(\.[A-Za-z_][\w]*)+$", title) or "()" in title:
                problems.append((sl,"item6",f'title looks like a code identifier: "{title}"'))
            libalt = "|".join(re.escape(l) for l in LIBS)
            api_fails = [
                (rf"\bIn ({libalt})\b", "In-<library> framing"),
                (rf"\b({libalt})\s+(provides|offers|exposes|has)\b", "<library> provides/offers framing"),
                (r"\bbuilt with `", "'built with `…`' how-to signpost"),
                (r"\bconstructed (with|via) `", "'constructed with/via `…`' how-to signpost"),
                (r"\bcreated (with|by) `", "'created with/by `…`' how-to signpost"),
                (r"\bavailable (through|via|in) `", "'available through `…`' how-to signpost"),
                (r"\buse `[^`]+` to\b", "'use `…` to' how-to signpost"),
                (r"`[^`]+` or `[^`]+`", "`…` or `…` alternative signposts"),
                (r"\bflag enables\b", "kwarg/flag documentation"),
                (r"`[A-Za-z_][A-Za-z0-9_]*\s*=", "backticked kwarg/default-value (`name=`)"),
                (r"`(True|False|None)`", "Python language literal in code form"),
            ]
            for pat,label in api_fails:
                if re.search(pat, e["prose"]):
                    problems.append((sl,"item6",f'API-surface failure string — {label}')); break
            # fenced code block — code listings don't belong in a non-Software entry.
            # Both fence spellings: markdown opens a block with ``` or ~~~, and
            # `strip_fenced` above has always known that, so a `~~~` listing sat
            # in a Concept entry unreported by the one check that exists to find it.
            if re.search(r"(?m)^\s*(?:`{3}|~{3,})", e["body"]):
                problems.append((sl,"item6","fenced code block — mechanically allowed only after genuine Software classification; reclassification does not waive Software's artifact-wide relevance gate"))
            # API-identifier cap — ZERO backticked identifiers in a non-Software entry.
            # (Rule change 2026-08-16: the one-name-only-signpost allowance is retired;
            # Software is the only mechanically eligible type; its separate
            # artifact-wide relevance gate can still reject the identifier. A
            # bare extension and bracket special token are not identifiers.)
            inline = re.findall(r"`([^`\n]+)`", re.sub(r"`{3}.*?`{3}", " ", e["prose"], flags=re.S))
            idtoks = [t.strip() for t in inline if t.strip()
                      and not re.fullmatch(r"\.[A-Za-z0-9]+", t.strip())   # not a bare file extension (.csv)
                      and not re.fullmatch(r"\[.+\]", t.strip())]          # not a bracket special token ([CLS])
            if len(idtoks) >= 1:
                problems.append((sl,"item6",f'{len(idtoks)} backticked identifier(s) (cap is 0 in a non-Software entry; Software may retain only artifact-wide design/interface API, never a usage catalog): {", ".join(idtoks[:6])}'))
        # ---- item 7: description length + presence (FULL ENTRIES AND STUBS) ----
        # Item 7 is NOT on the stub exemption list: wiki-builder's stub format carries a real
        # description ("Description follows the description field definition"), so the ≤110 cap, the
        # entity-as-subject form and the plain-text rule all apply to a stub exactly as to a full entry.
        # This block used to sit behind `if not is_stub:`, which silently exempted every stub.
        if not e["desc"]: problems.append((sl,"item7","missing description"))
        elif len(e["desc"]) > 110: problems.append((sl,"item7",f'description {len(e["desc"])} chars > 110'))
        marks = []
        if "$" in e["desc"]: marks.append("$ (LaTeX/currency)")
        if "`" in e["desc"]: marks.append("backtick")
        if "[[" in e["desc"]: marks.append("wikilink")
        if re.search(r"\*\*|\*\w[^*]*\*", e["desc"]): marks.append("* (bold/italic)")
        if marks:
            problems.append((sl,"item7",f'description has non-plain-text markup ({", ".join(marks)}) — renders literally in Obsidian Properties'))
        if e["desc"]:
            sentence_count = count_sentences(e["desc"])
            if sentence_count > 1:
                problems.append((
                    sl, "item7",
                    f"description must be one sentence; found roughly "
                    f"{sentence_count}"))
            if title and not description_has_entity_subject(e["desc"], title):
                forms = ", ".join(repr(form)
                                  for form in description_subject_forms(title))
                problems.append((
                    sl, "item7",
                    "description subject does not begin with the canonical "
                    "title/base term (an optional leading article is allowed); "
                    "expected one of: %s" % forms))
            if e["desc"][0].isalpha() and not e["desc"][0].isupper():
                subjects = []
                for subject in (title, base_term(title) if title else None):
                    for form in (subject, math_skeleton(subject) if subject else None):
                        if form and form not in subjects:
                            subjects.append(form)
                lowercase_title_subject = any(
                    s[0].islower() and e["desc"].startswith(s) for s in subjects)
                if not lowercase_title_subject:
                    problems.append((sl,"item7",
                                     "description does not start with a capitalized word"))
            if not e["desc"].rstrip().endswith("."):
                problems.append((sl,"item7","description does not end with a period"))
        # ---- item 8: tags validity (#-prefixed discipline slugs from the 27-enum; NOT wikilinks) ----
        e_tags_raw, e_tag_slugs = e["tags_raw"], e["tag_slugs"]
        raw_tags = raw_scalar(fm_raw, "tags")
        if raw_tags not in (None, ""):
            spelling = "flow-list" if raw_tags.startswith("[") else "scalar"
            problems.append((sl,"item8",f'tags: uses {spelling} syntax — write a block-form '
                             'list with one double-quoted tag per `-` line; a full entry with '
                             'no disciplinary home uses a blank `tags:` key'))
        if not e_tags_raw:
            if is_stub:
                problems.append((sl,"item8","stub has blank tags: — every stub needs ≥1 discipline tag, inherited from the entry that links it (wiki-builder's SKILL.md, Stubs (legacy): Structure)"))
            # blank tags: on a FULL entry is valid (no discipline genuinely applies) — not a violation
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
                              else f'"{low}" is not one of the 27 discipline slugs')
            elif slugpart != low:
                # The enum slugs are lowercase. A case variant folds onto the
                # right discipline for the census and for Obsidian's search, so
                # nothing downstream broke and nothing reported it either — the
                # entry simply carried a spelling the enum does not contain.
                faults.append(f'"{slugpart}" is a case variant of the enum slug "{low}" '
                              f'(the 27 slugs are lowercase)')
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
        # ---- item 9: body structure (FULL ENTRIES AND STUBS) ----
        # The scanner has no body-length, paragraph-flow, or atomicity check. The structural
        # floor still applies to stubs: prose starts immediately after the
        # frontmatter, and Person/Event stubs carry the date parenthetical after
        # the bolded subject (wiki-builder's SKILL.md, Stubs (legacy)). All three
        # checks below therefore run on stubs too; this block once sat behind
        # `if not is_stub:`, which dropped rules the stub format requires.
        if e["blank_after"]:
            problems.append((sl,"item9","blank line immediately after frontmatter"))
        bstrip = e["body"].lstrip()
        if bstrip[:2] in ("##","- ","* ","> ") or bstrip[:1] == "#":
            problems.append((sl,"item9","body does not open with a prose sentence"))
        if e["type"] in ("Person","Event"):
            opener = e["prose"].split("\n\n",1)[0]
            date_status = opener_subject_date_status(opener, e["type"])
            if date_status == "missing":
                problems.append((sl,"item9",f'{e["type"]} opener needs a date '
                                             f'parenthetical immediately after the bolded subject'))
            elif date_status == "malformed":
                problems.append((sl,"item9",f'{e["type"]} opener date parenthetical '
                                             f'is not one of the exact forms in '
                                             f'wiki-builder/references/rare-types.md '
                                             f'(including qualifier punctuation and '
                                             f'en-dash spacing)'))
        for line_no, cue_line in navigation_only_link_lines(e["prose"]):
            problems.append((
                sl, "item9/imperative-link",
                f'navigation-only cross-reference on prose line {line_no}: '
                f'"{cue_line[:100]}" — PROPOSAL ONLY for legacy text; integrate '
                f'the link into the sentence claim during an authorized prose edit'))
        for line_no, heading_line in enumerate(
                strip_code(e["prose"]).split("\n"), 1):
            heading = re.match(r"^ {0,3}(#{1,6})[ \t]+(.+?)\s*$", heading_line)
            if not heading:
                continue
            faults = []
            if heading.group(1) != "##":
                faults.append("level must be exactly ##")
            heading_text = heading.group(2).rstrip("#").rstrip()
            heading_markup = []
            if "[[" in heading_text: heading_markup.append("wikilink")
            if "$" in heading_text: heading_markup.append("LaTeX")
            if "`" in heading_text: heading_markup.append("backtick")
            if "*" in heading_text or "_" in heading_text:
                heading_markup.append("emphasis")
            if heading_markup:
                faults.append("plain text only (found %s)"
                              % ", ".join(heading_markup))
            if faults:
                problems.append((
                    sl, "item9",
                    "body heading on prose line %d is noncanonical: %s — %s"
                    % (line_no, heading_line.strip()[:80], "; ".join(faults))))
        if is_stub:
            stub_prose = e["prose"].strip()
            paragraphs = [p for p in re.split(r"\n\s*\n", stub_prose) if p.strip()]
            if len(paragraphs) > 1:
                problems.append((sl,"stub-one-sentence-body",
                                 f'a stub body is one sentence; found {len(paragraphs)} paragraphs'))
            elif paragraphs:
                sentence_count = count_sentences(paragraphs[0])
                if sentence_count > 1:
                    problems.append((sl,"stub-one-sentence-body",
                                     f'a stub body is one sentence; found roughly {sentence_count}'))
            else:
                problems.append((sl,"stub-one-sentence-body","stub has no body sentence"))
            _stub_masked = strip_code(e["body"])
            if (re.search(r"!\[\[[^\]\n]+\]\]", _stub_masked)
                    or any(markdown_image_spans(_stub_masked))):
                problems.append((sl,"stub-no-images","stubs never carry images"))
        # ---- item 12 (format): unescaped literal $ and remote image embeds ----
        if not is_stub:
            nd = leftover_dollars(e["body"])
            if nd:
                problems.append((sl,"item12",f'{nd} unescaped literal "$" in body — escape as \\$ (a lone $ renders as math; a $ in a URL needs the image localized)'))
            _equation_prose = strip_code(e["prose"])
            _equation_tables = markdown_tables(e["prose"])[1]
            _equation_candidates = find_missing_display_equation_candidates(
                _equation_prose, _equation_tables)
            if _equation_candidates:
                _lines = ", ".join(str(candidate["line"])
                                   for candidate in _equation_candidates)
                problems.append((
                    sl, "item12/equation-coverage-candidate",
                    "prose explicitly says a quantity is the square root of "
                    "variance, but the entry has no display equation "
                    f"(prose line(s) {_lines}) — executing agent: verify the "
                    "definition in context, bind every symbol nearby, and "
                    "typeset only the stated relationship under "
                    "wiki-builder/references/equations.md; do not infer a "
                    "population or sample denominator"))
            # Remote ![](http…) embeds are REPORT-ONLY, not a violation. wiki-builder MANDATES this exact
            # form for an external URL coming from a markdown source's clipping ("use standard markdown
            # image syntax ![alt](https://...) since wikilinks don't handle remote URLs" —
            # wiki-builder references/media.md), because an Obsidian wikilink cannot address a remote URL.
            # Filing it as an ordinary itemN problem made the linter "fix in place" a working image into
            # ![[Sources/Images/…]] — a path form wiki-builder does not use either (it embeds a BARE basename,
            # ![[Name_fig_3.png]]) — which resolves to nothing and throws the URL away. Its own item key
            # routes it to the run report instead. DO NOT re-file this as item12.
            for _start, _end, url in markdown_image_spans(strip_code(e["body"])):
                if not re.match(r"https?://", url, re.IGNORECASE):
                    continue
                problems.append((sl,"item12/remote-image",f'remote image embed ![]({url[:50]}…) — VALID, DO NOT REWRITE (wiki-builder mandates markdown syntax for remote URLs); report only, as a candidate for localizing by re-running clipping-processor on the source clipping'))
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
        # Outside the `if not is_stub:` block above on purpose — a dead embed is
        # dead whatever the entry is, and item 12's stub exemption is about the
        # figure-and-caption rules a stub has no occasion to break.
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
                problems.append((sl,"item12/missing-image",
                                 f'embed names a file that is not in the image folder: {_img} '
                                 f'(Obsidian renders this as plain text, silently) — REPORT '
                                 f'ONLY, DO NOT DELETE THE EMBED OR ITS CAPTION. There are two '
                                 f'repairs and neither is the linter\'s: the figure was never '
                                 f'extracted (run pdf-figure-extractor on the source), or an '
                                 f'approved source rename renamed it with the source '
                                 f'(CONVENTIONS §1a), in which case the embed is rewritten to '
                                 f'the new stem. Deleting the embed throws away the one record '
                                 f'of which figure belongs here'))
        # ---- item 16: opener title text plus type-specific emphasis ----------
        if not is_stub:
            opener = e["prose"].split("\n\n",1)[0]
            mo = _BOLD_OUTER_RE.search(opener)
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
                def _dex(s):                                  # strip LaTeX wrappers to a comparable text skeleton
                    s = re.sub(r"\\(?:boldsymbol|mathbf|mathrm|mathit|text)\s*\{([^}]*)\}", r"\1", s)
                    s = s.replace("$","").replace("\\","").replace("{","").replace("}","")
                    return re.sub(r"\s+"," ", s).strip()
                t_norm = re.sub(r"\s*\([^)]*\)\s*$", "", title).strip()   # drop a trailing disambiguation parenthetical
                taxon_status, taxon = (
                    organism_title_classification(
                        t_norm, e["aliases"], first_sentence(opener))
                    if e["type"] == "Organism" else ("common", None))
                compared_b = (b.replace("*", "").replace("_", "")
                              if taxon_status == "ambiguous" else b)
                bb, tt = _dex(compared_b), _dex(t_norm)
                if bb and tt and (bb[:1].lower()+bb[1:] != tt[:1].lower()+tt[1:]):
                    problems.append((sl,"item16",f'body opener "**{b}**" ≠ title "{title}" (after dropping LaTeX wrappers and a disambiguation parenthetical)'))
                else:
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
        in_opener = True; opener_skipped = False
        _item16_prose = mask_line_spans(
            strip_code(e["prose"]), e.get("table_spans", ()))
        for ln in _item16_prose.split("\n"):
            if in_opener and ln.strip() == "": in_opener = False   # opener = the first paragraph
            if re.match(r"^\s*\*(?!\*).*\*\s*$", ln):              # caption line (whole-line italic) — item-12 owns it
                continue
            # bullet term-anchor line: legit. The bolded anchor may be followed by a short parenthetical or
            # bracketed qualifier (optionally italicized) before the delimiter — wiki-builder's own canonical
            # definition bullet is `- **True positives** (TP) — positives correctly predicted as positive`,
            # which a dash-must-follow-the-`**` pattern wrongly flagged as unenumerated bold (and wiki-builder
            # re-emitted it every run). Prose after the anchor with no delimiter is still flagged.
            if re.match(r"^\s*[-*]\s+\*\*[^*\n]+\*\*(?:\s*[*_]?[\(\[][^)\]\n]{1,60}[\)\]][*_]?)*\s*[—–:\-]", ln):
                continue
            for bold_match in _BOLD_OUTER_RE.finditer(ln):
                if in_opener and not opener_skipped:               # opener's title slot — item 16 owns its form
                    opener_skipped = True; continue
                spn, _sp_style, _sp_prefix = _bold_parts(bold_match)
                spn = spn.strip()
                if not spn or spn == "Related:":
                    continue
                if re.fullmatch(r"\[\[[^\]]*\]\]|\$[^$]+\$|`[^`]+`", spn):   # emphasis around a single wikilink/math/code → emphasis-misuse check owns it
                    continue
                problems.append((sl,"item16",f'unenumerated bold "**{spn}**" — bold is only for the title, `- **Term** (qualifier) —` bullet anchors, and **Related:** (use italics or a wikilink)'))
        # ---- item 16: emphasis (bold/italic) around a wikilink/math/code span — the markup itself is the styling ----
        emphasis_zones = mask_line_spans(
            strip_indented(strip_fenced(e["prose"])),
            e.get("table_spans", ())) + "\n" + e["rel"]
        for m in re.finditer(r"(\*\*|\*)(\[\[[^\]\n]*\]\]|\$[^$\n]+\$|`[^`\n]+`)(\*\*|\*)", emphasis_zones):
            if m.group(1) != m.group(3): continue              # require balanced ** ** or * *
            inner = m.group(2)
            kind, fix = ("wikilink","the link") if inner.startswith("[[") else (("math","LaTeX") if inner.startswith("$") else ("code","backticks"))
            problems.append((sl,"item16",f'{"bold" if m.group(1)=="**" else "italic"} around a {kind} ({inner[:30]}) — remove the emphasis; {fix} already provides the styling'))
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
                'literal shape in backticks' % occurrence))
        # ---- item 13: stray frontmatter key mid-body (stacked-merge scar) ----
        # `importance` stays in this alternation on purpose: it is a legacy key, so a legacy
        # entry's stacked-merge scar can still be an `importance:` line stranded in the body.
        # That is an item-13 structural scar, not an importance rule — there is no item-20 check.
        # Fenced code is masked first. A `Software` entry legitimately SHOWS
        # YAML/config in a listing (`type: Software`, `tags: [...]`), and a
        # scar-detector that reads a listing as a scar told the linter to
        # delete a line out of the entry's own example — the one place in this
        # scan where the fix is destructive and the finding was always false.
        # item 6 keeps its own unmasked view: there, the fence IS the finding.
        # `read` is in this alternation like every other schema key: `read:` is
        # the schema's LAST key, so a partial stacked-merge scar plausibly
        # leaves exactly a `read: false` line — omitting it made qc-items'
        # "any schema key" claim false for the likeliest single-line scar.
        _merge_lines = strip_code(e["prose"]).split("\n")
        # If Related is missing, regions() reaches the legitimate separator
        # before Flashcards. Item 11 should report the missing footer without
        # cascading into an item-13 "stray separator" false positive.
        if e.get("flashcard_indexes"):
            _flash_i = e["flashcard_indexes"][0]
            _structural_separator_i = next(
                (i for i in range(_flash_i - 1, -1, -1)
                 if e["body_lines"][i].strip()), None)
            if (_structural_separator_i is not None
                    and e["body_lines"][_structural_separator_i].strip() == "---"
                    and _structural_separator_i < len(_merge_lines)):
                _merge_lines[_structural_separator_i] = ""
        _merge_scan = "\n".join(_merge_lines)
        if re.search(r"(?m)^(title|type|aliases|sources|created|updated|description|tags|importance|parents|read):",
                     _merge_scan):
            problems.append((sl,"item13","stray frontmatter key in the body — stacked-merge scar; remove it"))
        if re.search(r"(?m)^\s*---\s*$", _merge_scan):
            problems.append((
                sl, "item13",
                "stray `---` fence in explanatory body prose — stacked-merge "
                "scar; the only body separator belongs between Related and "
                "Flashcards"))
        if re.search(r"(?m)^\s*[0-9]+\s*$", _merge_scan):
            problems.append((
                sl, "item13",
                "standalone bare digit line in explanatory body prose — "
                "stacked-merge scar; remove it or restore the content it was "
                "detached from"))
        # ---- item 19: Flashcards presence/absence + one-card cap + per-card structure / markup / answer-leak ----
        if not is_stub and not e["has_flashcards"]:
            problems.append((sl,"item19","full entry missing ## Flashcards section"))
        if is_stub and e["has_flashcards"]:
            problems.append((sl,"item19","stub has a ## Flashcards section"))
        if not is_stub and e["has_flashcards"]:
            # A tolerated heading spelling (### level, extra/leading spaces) is a
            # PRESENT section with a heading to fix — never a missing section,
            # whose remedy would add a second one beside the section Obsidian
            # already renders.
            if not _FLASH_HEAD_CANON.match(e["flash_head"]):
                problems.append((sl,"item19",f'Flashcards heading spelled "{e["flash_head"].strip()[:30]}" — '
                                             f'the canonical heading is exactly "## Flashcards"; fix the '
                                             f'heading in place, do NOT add a second section'))
            # the ## Flashcards heading must sit under a '---' separator line on its own
            pre = e["body"][:e["flash_off"]].rstrip()
            pre_nb = [l for l in pre.split("\n") if l.strip()]
            if not pre_nb or pre_nb[-1].strip() != "---":
                problems.append((sl,"item19","## Flashcards not preceded by a '---' separator line on its own (Body Structure → Flashcards)"))
            else:
                _flash_i = e["flashcard_indexes"][0]
                _lines = e["body_lines"]
                _separator_i = next(
                    (i for i in range(_flash_i - 1, -1, -1)
                     if _lines[i].strip()), None)
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
            # Line-4+ HTML comments belong to the review plugin. A blank line
            # inside or between its comments is not another card whose removal
            # may be proposed. Mask comments only in this read-only check.
            after_head = re.sub(r"<!--.*?(?:-->|\Z)", "", after_head, flags=re.S)
            cards = [b for b in re.split(r"\n[ \t]*\n", after_head.strip("\n")) if b.strip()]
            if not cards:
                problems.append((sl,"item19","## Flashcards section has no card"))
            elif len(cards) > 1:
                problems.append((sl,"item19",f'{len(cards)} cards in ## Flashcards — exactly one card per entry; keep the primary card whose line 3 uses the exact canonical title/base/math-skeleton term and includes any required opener-established, alias-bound counterpart, then split or drop the rest'))
            alias_forms = [x for a in e["aliases"] for x in (a, a.replace("-"," "))]
            for ci, block in enumerate(cards, 1):
                cl = block.split("\n")
                tag = (f"card {ci}" if len(cards) > 1 else "flashcard")
                if len(cl) < 3:
                    problems.append((sl,"item19",f'{tag} malformed — needs 3 contiguous lines (definition / ?? / term), found {len(cl)} (a blank line between lines 1–3 breaks the card)'))
                    continue
                line1, line2, line3 = cl[0], cl[1].strip(), cl[2]
                if line2 not in ("??","!!"):
                    problems.append((sl,"item19",f'{tag} line 2 is "{line2[:20]}", must be exactly ?? (or !! if the user disabled the card)'))
                l1 = []                              # line 1 takes LaTeX only
                if "[[" in line1: l1.append("wikilink")
                if "`" in line1: l1.append("backtick")
                if "**" in line1: l1.append("bold")
                elif re.search(r"\*\w[^*]*\*", line1): l1.append("italic")
                if l1:
                    problems.append((sl,"item19",f'{tag} line 1 has {", ".join(l1)} — line 1 takes LaTeX only (no wikilinks/bold/italic/backticks)'))
                _sentence_faults = []
                _sentence_start = line1.lstrip(" \t\"'“‘([{")
                # A symbol or equation may legitimately begin the sentence;
                # leave its capitalization to semantic review rather than
                # treating the first LaTeX command letter as prose.
                if (_sentence_start and not _sentence_start.startswith("$")
                        and _sentence_start[0].isalpha()
                        and not _sentence_start[0].isupper()):
                    _sentence_faults.append("does not start with a capitalized word")
                if not line1.rstrip().endswith("."):
                    _sentence_faults.append("does not end with a period")
                sentence_count = count_sentences(line1)
                if sentence_count > 1:
                    _sentence_faults.append(
                        "contains roughly %d sentences" % sentence_count)
                if _sentence_faults:
                    problems.append((
                        sl, "item19",
                        f'{tag} line 1 {" and ".join(_sentence_faults)} — '
                        "the definition is one grammatically self-contained sentence"))
                # leak check: line 1 must not contain THIS card's answer — its own line-3 term (+ parenthetical
                # expansion); add the entry's aliases only when this card's term is the entry title (the primary
                # card). A secondary card legitimately names the primary entity, so don't test it against the title.
                mt = re.match(r"^(.*?)\s*(?:\(([^)]*)\))?\s*$", line3.strip())
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
                _t_full = title.strip().lower() if title else ""
                _t_base = re.sub(r"\s*\([^)]*\)\s*$", "", title).strip().lower() if title else ""
                if title and term_main.lower() in (_t_full, _t_base):
                    cands += alias_forms
                # Both spellings of every candidate: a hyphenated term leaks in
                # its natural spaced spelling too ("fine tuning" for
                # "Fine-tuning").  lint_entry tests both; the two tools must
                # agree (item 19's de-hyphenated substring check).
                _seen_cf = set()
                cands = [c for c in
                         (x for c0 in cands if c0 for x in (c0, c0.replace("-", " ")))
                         if not (c.lower() in _seen_cf or _seen_cf.add(c.lower()))]
                hit = None                           # word-boundary for ≤4-char tokens; substring otherwise
                for c in cands:
                    if not c: continue
                    if len(c) <= 4:
                        if re.search(r"(?<![A-Za-z0-9])"+re.escape(c)+r"(?![A-Za-z0-9])", line1, re.I): hit = c; break
                    elif c.lower() in line1.lower(): hit = c; break
                if hit:
                    problems.append((sl,"item19",f'{tag} line 1 leaks the answer ("{hit}")'))
                l3 = []                              # line 3 (term) is plain text — no markup at all, including LaTeX
                if "[[" in line3: l3.append("wikilink")
                if "`" in line3: l3.append("backtick")
                if "$" in line3: l3.append("$ (LaTeX)")
                if "**" in line3: l3.append("bold")
                elif re.search(r"\*\w[^*]*\*", line3): l3.append("italic")
                if l3:
                    problems.append((sl,"item19",f'{tag} line 3 (term) has {", ".join(l3)} — the term is plain text matching the title verbatim (no markup, including LaTeX)'))
                opener = e["prose"].split("\n\n", 1)[0]
                line3_fault = flashcard_line3_fault(
                    line3, title, e["aliases"], opener, e["type"])
                if line3_fault:
                    problems.append((sl, "item19",
                                     f'{tag} line 3 is "{line3[:40]}" — '
                                     f'{line3_fault}'))
        # ---- item 11: exactly one terminal Related footer on full entries ----
        # ``regions`` intentionally stops prose at the first rendered marker.
        # Without this topology check, a second footer or ordinary prose after
        # that marker disappears from every body/link scan and can conceal a
        # self-link or any other violation indefinitely.
        if not is_stub:
            _related_indexes = e.get("related_indexes", [])
            _flash_indexes = e.get("flashcard_indexes", [])
            if not _related_indexes:
                problems.append((
                    sl, "item11",
                    "full entry has no `**Related:**` footer — add one terminal "
                    "footer line before the Flashcards separator"))
            elif len(_related_indexes) > 1:
                problems.append((
                    sl, "item11",
                    f"entry has {len(_related_indexes)} rendered `**Related:**` "
                    "footer lines — consolidate them into exactly one terminal line"))
            else:
                _related_i = _related_indexes[0]
                _related_line = e["body_lines"][_related_i]
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
                            if e["body_lines"][_i].strip():
                                if e["body_lines"][_i].strip() == "---":
                                    _separator_i = _i
                                break
                        _tail_end = (_separator_i if _separator_i is not None
                                     else _flash_i)
                        _stray = [
                            _i for _i in range(_related_i + 1, _tail_end)
                            if e["body_lines"][_i].strip()]
                        if _stray:
                            problems.append((
                                sl, "item11",
                                "body content appears after the Related footer "
                                "before Flashcards — move it back into prose or "
                                "remove it; the footer must be terminal"))
                elif any(line.strip()
                         for line in e["body_lines"][_related_i + 1:]):
                    problems.append((
                        sl, "item11",
                        "body content appears after the Related footer — the "
                        "footer must be the terminal prose line"))

            if len(_flash_indexes) > 1:
                problems.append((
                    sl, "item19",
                    f"entry has {len(_flash_indexes)} rendered Flashcards "
                    "headings — consolidate them into exactly one section"))

        # ---- stubs have no Related footer ----
        if is_stub and e["has_related"]:
            problems.append((sl,"stub","stub has a **Related:** footer"))
        # ---- item 14: source-meta phrasings (prose only) ----
        META = [
            r"\b(?:the|this) paper\b", r"\bthe chapter\b",
            r"\bthe book\b", r"\bthe article\b",
            # “source code” names software material, not the document. The
            # carve-out is symmetric for “the” and “this,” including the
            # ordinary hyphenated spelling.
            r"\b(?:the|this) source\b(?!\s*(?:-| )\s*code\b)",
            r"\bas (?:mentioned|discussed|noted|shown|described) "
            r"(?:above|below|earlier|previously|later)\b",
            r"\bin the previous section\b", r"\bas we saw\b",
            r"\bthe figure (?:above|below)\b",
        ]
        _meta_text = strip_code(e["prose"])
        _meta_found = False
        for pat in META:
            if re.search(pat, _meta_text, re.I):
                problems.append((sl,"item14",f'source-meta phrasing /{pat}/'))
                _meta_found = True
                break
        if not _meta_found:
            _author_matches = list(re.finditer(r"\bthe authors?\b", _meta_text,
                                               re.IGNORECASE))
            if any(not _authors_phrase_names_work(_meta_text, match)
                   for match in _author_matches):
                problems.append((
                    sl, "item14",
                    "source-meta phrasing uses bare `the author(s)` rather than "
                    "naming an existing Work entry"))
        # ---- item 17: names introduced for this subject but absent in aliases ----
        # The shared detector is exactly the one wiki-builder runs on a new or
        # merged entry. It supplies a deterministic candidate; same-entity,
        # cross-domain, and Organism common-name safety remain executing-agent judgments.
        for _candidate, _where, _candidate_slug in missing_introduced_aliases(
                strip_code(e["prose"]).split("\n"), title, e["aliases"], sl):
            problems.append((
                sl, "item17/alias-candidate",
                f'the body introduces "{_candidate}" ({_where}) as a name for '
                f'the subject, but aliases: does not contain '
                f'"{_candidate_slug}" — review same-entity and cross-domain '
                f'safety before adding it'))
        # ---- item 10: dangling targets; first-occurrence dup within PROSE ----
        # A target that misses every entry exactly but hits one case- or
        # normalization-insensitively is NOT dangling: Obsidian resolves it to
        # that entry on the vault's APFS volume. It gets its own key, because
        # the repairs are opposites — a genuine dangler is dropped to display
        # text, while this resolving link is canonicalized in place.  Treating
        # the case variant as missing would destroy a working reference.
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
                        f'body line {_line_i + 1} — replace the link markup with '
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
            # Three forms Obsidian resolves that a bare `tgt in entries` test
            # calls dangling -- and the documented fix for a dangler writes a
            # stub, i.e. over a real file. A path-qualified link
            # (`sub/delta`), an explicit `.md` suffix, and a link to a
            # document rather than an entry (`Doe_Foo_2025.pdf`, the form
            # CONVENTIONS 6/7 blesses in a `sources:` list).
            bare = tgt.replace("\\", "/").rsplit("/", 1)[-1]
            lookup = bare[:-3] if bare.lower().endswith(".md") else bare
            lookup_key = entry_link_key(tgt)
            file_record, file_status, _file_path = _resolve_entry_file(tgt)
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
            if actual == lookup:
                continue
            if actual:
                problems.append((sl,"item10/case",
                                 f'wikilink target "{tgt}" matches the entry "{actual}" only case-/'
                                 f'normalization-insensitively — the link resolves in Obsidian, so this '
                                 f'is a FIX IN PLACE (correct the basename spelling to "{actual}", '
                                 f'preserving any path, anchor and display label), '
                                 f'NEVER a stub: on the vault\'s case-insensitive volume a stub written '
                                 f'to "{tgt}.md" opens and overwrites "{actual}.md"'))
            elif file_status == "unparsed":
                # The file EXISTS but did not parse (item0/item1), or lives in a
                # symlinked subfolder the walk did not enter. Reporting it as a
                # dangler is wrong twice over: the link resolves in Obsidian,
                # and the retired stub remedy would have opened that very file
                # and replaced it with one line.
                problems.append((sl,"item10/unparsed",
                                 f'wikilink target "{tgt}" names a file that is '
                                 f'on disk but could not be parsed as an entry. '
                                 f'The link resolves; fix that file. NEVER stub '
                                 f'this target -- the stub would overwrite it'))
            elif os.path.splitext(bare)[1].lower() in _DOC_EXTS:
                continue
            elif lookup_key in alias_of:
                # An ALIAS of another entry. Obsidian resolves it, so it is not
                # a dangler -- and the dangler remedy is the destructive one
                # here: a stub at Wiki/<tgt>.md becomes a FILE with that name,
                # a file outranks an alias, and every [[tgt]] in the vault
                # silently stops resolving to the entry that owns the alias and
                # starts resolving to the one-line stub. Nothing downstream
                # reports that as an item-18 clash, so the link is quietly
                # re-pointed at an empty note for good.
                if lookup_key in ambiguous_aliases:
                    problems.append((sl, "item10/ambiguous",
                                     f'wikilink target "{tgt}" is claimed as an alias by multiple '
                                     f'entries; preserve the link, anchor and display text until its '
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
                _anchor_match = re.search(r"[#^].*", m.group(1))
                _anchor = _anchor_match.group(0) if _anchor_match else ""
                _label = m.group(2) if m.group(2) is not None else tgt
                _replacement = f'[[{_own_sl}{_anchor}|{_label}]]'
                problems.append((sl,"item10/alias",
                                 f'wikilink target "{tgt}" is an alias of the entry '
                                 f'"{_own_sl}" (aliases: "{_own_raw}"), not an entry of its '
                                 f'own — the link RESOLVES in Obsidian. Fix in place: '
                                 f'rewrite to "{_replacement}", never stub it. Stubbing '
                                 f'creates a file that outranks the alias and steals every '
                                 f'"[[{tgt}]]" in the vault away from "{_own_sl}"'))
            else:
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
            record, status, owner_path = _resolve_entry_file(raw_target)
            if (record is not None
                    and record.get("path_key") == e.get("path_key")):
                continue
            if status in ("parsed", "unparsed"):
                owners = paths_by_basename.get(entry_link_key(raw_target), set())
                key = ("file-path:" + owner_path if len(owners) > 1
                       else fold_name(record["slug"] if record
                                      else entry_link_key(raw_target)))
            elif status == "ambiguous":
                # No safe duplicate-removal action exists until the bare or
                # partially qualified target identifies one file.
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
        for m in WIKILINK.finditer(e["rel"]):
            tgt, disp = m.group(1).strip(), m.group(2)
            # The link target may carry an anchor and/or a vault path while
            # still resolving to an entry.  Resolve the underlying basename
            # before deciding whether item 11 applies; a direct dict lookup on
            # the rendered target let [[Wiki/term#Heading]] escape the rule.
            lookup_key = entry_link_key(tgt)
            record, status, _owner_path = _resolve_entry_file(tgt)
            if status == "ambiguous" or lookup_key in ambiguous_aliases:
                continue
            if record is None and status == "missing" and lookup_key in alias_of:
                record = entries.get(alias_of[lookup_key][0])
            if (record is not None
                    and record.get("path_key") == e.get("path_key")):
                continue
            tt = record.get("title", "") if record else ""
            if not tt:
                continue
            if disp is None:
                problems.append((sl,"item11",f'Related footer bare link [[{tgt}]] should be piped to "{tt}"'))
            elif disp != tt:
                problems.append((sl, "item11",
                                 f'Related footer link [[{tgt}|{disp}]] must use '
                                 f'the canonical title "{tt}" as its display label'))

    # ---- item 18: alias collisions + within-entry dup + display-label sanity ----
    alias_owner = {}
    for sl,e in entries.items():
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
        # Keyed on fold_name, like every other "is this the same name?"
        # comparison in this file (see fold_name's docstring). Two aliases that
        # differ only in case or Unicode normalization are ONE name to Obsidian
        # and one file on the vault's APFS volume, so [[Lambda-Rank]] resolves
        # to whichever entry Obsidian picks and the other becomes unreachable
        # under its own alias. Comparing raw strings reported nothing, and
        # CONVENTIONS §9 gives whole-vault dedup to this skill alone, so on a
        # vault-wide run the pair was seen by nobody. The raw spelling is kept
        # for the message: the fix is to change one of the two spellings, and
        # the user has to be told which two they are.
        for a in al:
            k = fold_name(a)
            if k in alias_owner and alias_owner[k][0] != sl:
                own_sl, own_raw = alias_owner[k]
                problems.append((sl,"item18",
                                 f'alias "{a}" also on "{own_sl}"'
                                 + ("" if own_raw == a else
                                    f' (spelled "{own_raw}" there — the two differ only in '
                                    f'case/normalization, which is one name to Obsidian and '
                                    f"one file on the vault's volume)")))
            elif k not in alias_owner:
                alias_owner[k] = (sl, a)
    def _toks(s):                                    # tokens: lowercased, hyphens→spaces, a disambiguation parenthetical dropped
        s = re.sub(r"\s*\([^)]*\)\s*", " ", s.lower())
        return re.findall(r"[a-z0-9]+", s.replace("-", " "))
    def _stem(t):                                     # crude inflection stem: tuning/tuned/tunes/tune -> tun
        for suf in ("ing", "ed", "es", "s"):          # one suffix, longest first; keep >=3 chars of stem
            if t.endswith(suf) and len(t) - len(suf) >= 3:
                t = t[: -len(suf)]; break
        if t.endswith("e") and len(t) >= 4:           # e-drop stems: tune -> tun, so tuned/tuning match tune
            t = t[:-1]
        return t
    def _tok_match(a, b):                             # tolerant of inflection/truncation between a display token and a title token
        # The 4-char common-prefix floor alone misses short e-drop verb stems: "tuned" vs "tuning" share only
        # "tun" (3), so [[fine-tuning|fine-tuned]] false-flagged on a real vault even though the display-label
        # carve-out explicitly permits natural verb inflections. Stems must be EQUAL (not prefixes) so a
        # genuinely different word ("tuner", "transfer") still flags.
        if a in b or b in a or len(os.path.commonprefix([a, b])) >= 4:
            return True
        sa, sb = _stem(a), _stem(b)
        return len(sa) >= 3 and sa == sb
    for sl,e in entries.items():
        _display_label_text = (
            mask_line_spans(strip_code(e["prose"]), e.get("table_spans", ()))
            + "\n" + strip_code(e["rel"]))
        for m in re.finditer(r"\[\[([^\]|#^]+)(?:[#^][^\]|]*)?\|([^\]\n]+)\]\]",
                             _display_label_text):
            tgt, disp = m.group(1).strip(), m.group(2).strip()
            dmark = []
            if "$" in disp: dmark.append("$ (LaTeX)")
            if "`" in disp: dmark.append("backtick")
            if "**" in disp: dmark.append("** (bold)")
            elif re.search(r"\*\w[^*]*\*", disp): dmark.append("* (italic)")
            if dmark:
                problems.append((sl,"item18",f'wikilink display label "{disp[:40]}" has markup ({", ".join(dmark)}) — labels render as plain text; put math/emphasis in the surrounding prose'))
                continue
            # Display label is valid when, for some title/alias form, the label's tokens are a SUBSET of the form
            # (inflection/truncation tolerant) — this accepts the bare display of a cross-domain qualified link,
            # [[information-entropy|entropy]], which wiki-builder MANDATES and FORBIDS as an alias so it can never be
            # in a surface set — OR a SUPERSET of the form, i.e. the label contains all the form's tokens plus extras,
            # which accepts a more-specific display that prepends a qualifier, [[neural-network|deep neural networks]].
            # An exact-match check false-flagged both (108-of-110 false positives on a real run); "fixing" the bare
            # case by adding the bare alias is exactly the silent cross-domain collision wiki-builder exists to prevent.
            # Do NOT re-tighten to exact match, and do NOT add a single-token-strict-subset guard (re-flags bare terms).
            # Still flags a label that is neither subset nor superset of any form (a wrong target / invented label).
            target_key = entry_link_key(tgt)
            target_record, target_status, _target_path = _resolve_entry_file(tgt)
            if (target_record is None and target_status == "missing"
                    and target_key not in ambiguous_aliases
                    and target_key in alias_of):
                target_record = entries.get(alias_of[target_key][0])
            if target_record is not None and disp:
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
                forms = ([_toks(target_record["title"])]
                         + [_toks(a) for a in target_record["aliases"]])
                dt = _toks(disp)
                ok = False
                for form in forms:
                    if not form: continue
                    sub = all(any(_tok_match(d, t) for t in form) for d in dt)   # label ⊆ form: bare term / inflection
                    sup = all(any(_tok_match(d, t) for d in dt) for t in form)   # label ⊇ form: qualifier-prefixed, more specific
                    if sub or sup: ok = True; break
                if not ok and organism_common_name_bound(target_record, disp):
                    ok = True
                if dt and not ok:
                    target_title = target_record.get("title") or target_slug
                    location = _target_path or target_slug
                    problems.append((sl,"item18",f'wikilink [[{tgt}|{disp}]] — "{disp}" shares no surface form with the canonical target "{target_title}" at "{location}" (its title/aliases), and no explicit Organism common-name binding applies; likely wrong target or invented label'))

    # ---- item 5: collision probes across entries (REPORT as candidates; merge is the user's call) ----
    collisions = []
    ident_owner = {}                      # exact identifier (slug or alias) -> first owner
    for sl,e in entries.items():
        for ident in [sl] + e["aliases"]:
            if ident in ident_owner and ident_owner[ident] != sl:
                collisions.append((sl, ident_owner[ident], "exact", ident))
            else:
                ident_owner.setdefault(ident, sl)
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
                        if (ms[i][0] != ms[j][0]
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
    # `weights` does not sort to `weight`. wiki-builder/references/merge.md describes the
    # singularized comparison, and wiki-builder's find_collisions.py runs probe
    # (e) twice for it (`wordorder_key` AND `wordorder_key_singular`). CONVENTIONS §9 gives
    # whole-vault duplicate detection to wiki-linter alone — wiki-builder only probes the
    # candidates of the source in front of it — so a pair already sitting in the vault is seen
    # by NOBODY unless this scanner runs the singularized half too. The key function is
    # shared/scripts/plurals.py's, the same one wiki-builder calls, so there is nothing left
    # here to drift from it.
    #
    # `real_permutation` is that module's guard, not a copy of it: this probe fires only on a
    # GENUINE re-ordering. Equal raw sorts are the `word-order` hit above, and an identical
    # singularized token SEQUENCE is a plain plural pair `plural` already reports — either
    # would put the same pair in the worklist a second time.
    group_probe(wordorder_key_singular, "word-order-singular", real_permutation)
    # µ-variant probe via titles
    for sl,e in entries.items():
        t = e["title"]
        if "µ" in t or "μ" in t:
            alt = slug(t.replace("µ","\u03bc")) if "µ" in t else slug(t.replace("\u03bc","µ"))
            if alt != sl and alt in entries:
                collisions.append((sl, alt, "µ-variant", f"{sl}~{alt}"))
    # Probe (f), light stem morphology, is the last whole-key probe in
    # wiki-builder.  It only adds a signal when none of the earlier probes
    # already covered the pair, so a plural such as roc-curve/roc-curves keeps
    # the more precise `plural` label instead of acquiring a second finding.
    # The key itself lives in shared/scripts/plurals.py and is therefore
    # byte-for-byte the builder's create-time key rather than a local copy.
    covered_pairs = {frozenset((a, b)) for a, b, _p, _d in collisions}
    group_probe(stem_key, "stem-morphology", skip_pairs=covered_pairs)
    # dedup collisions (unordered pair + probe)
    seen_c = set(); collisions2 = []
    for a,b,p,d in collisions:
        key = (frozenset((a,b)), p)
        if key in seen_c: continue
        seen_c.add(key); collisions2.append((a,b,p,d))

    # ---- Surface map + backfill candidates (Task 2 worklist; the executing agent judges closeness) ----
    surface_owners = {}                   # lowercased surface form -> all owners
    _title_surf, _alias_surf, _organism_common_surf = set(), set(), set()
    for sl,e in entries.items():
        forms = ([("title", e["title"])]
                 + [("alias", a.replace("-", " ")) for a in e["aliases"]]
                 + [("organism-common", name)
                    for name in organism_common_name_surfaces(e)])
        for kind, f in forms:
            if not f or len(f) < 3: continue
            # `plural_surface`, not `pluralize`: the latter takes ONE token, and
            # a whole title matches no irregular in its table (see plural_surface).
            for variant in (f, plural_surface(f)):
                surface_owners.setdefault(variant.lower(), set()).add(sl)
                if kind == "title":
                    _title_surf.add(variant.lower())
                elif kind == "alias":
                    _alias_surf.add(variant.lower())
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
    # only through an alias ("attribute", "target", "predictor").  These match
    # everywhere, nearly always fail the closeness bar, and — candidates
    # carrying no memory — resurfaced for identical re-judgment every run.
    # The candidate is still emitted (the closeness call stays with the executing agent;
    # a qualified-target link to a bare term is legal in principle) but is
    # TAGGED `bare_noun_alias` so the report can batch them.  The same
    # single-word shape reached through a TITLE is already suppressed or
    # surfaced by COMMON_NOUNS and item 5's bare-slug check.
    bare_noun_alias = {s for s in _alias_surf - _title_surf
                       if re.fullmatch(r"[a-z]+", s)}
    backfill = build_backfill(entries, surf_map)

    stubs = [sl for sl,e in entries.items() if e["is_stub"]]
    fulls = [sl for sl,e in entries.items() if not e["is_stub"]]

    # ---- discipline-tag census (VALID enum slugs vs off-enum/malformed) ----
    tag_counts = {}                       # VALID discipline slug -> [non-stub count, stub count]
    off_enum = {}                         # malformed/off-enum slug -> [entries using it]
    for sl,e in entries.items():
        for d in set(e["tag_slugs"]):
            if d.lower() in VALID_TAGS:
                tag_counts.setdefault(d.lower(), [0,0])
                tag_counts[d.lower()][1 if e["is_stub"] else 0] += 1
            else:
                off_enum.setdefault(d, []).append(sl)
    # blank tags: on a FULL entry is valid — no MOC placement, listed as unplaced
    untagged_full = [sl for sl,e in entries.items()
                     if not e["is_stub"] and not e["tag_slugs"] and "tags" in e["key_order"]]

    # ---- problem tally by checklist item ----
    # The share of entries affected is the recurrence signal for wiki-builder-improvement
    # proposals — see references/backlogs.md.
    tally = {}                                   # item -> [issue_count, set_of_entries]
    for sl,item,_ in problems:
        t = tally.setdefault(item, [0, set()])
        t[0] += 1; t[1].add(sl)
    nfull = len(fulls) or 1
    full_set = set(fulls)
    tally_out = [dict(item=item, entries=len(ents), pct_of_full=100*len(ents & full_set)//nfull, issues=cnt)
                 for item,(cnt,ents) in sorted(tally.items(),
                                               key=lambda kv: (-len(kv[1][1]), -kv[1][0], kv[0]))]

    # ---- Rename candidates (item 5): filename != slug(title). PROPOSE for approval — never auto-apply (a rename rewrites links vault-wide). ----
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
            _record, _status, _owner_path = _resolve_entry_file(_m.group(1))
            if _status != "parsed" or _record is None or _owner_path is None:
                continue
            inbound[_owner_path] = inbound.get(_owner_path, 0) + 1
    renames = []
    _rename_targets = {}                  # folded new_slug -> [entries proposing it]
    for _sl,_e in sorted(entries.items()):
        _new = slug(_e["title"]) if _e["title"] else ""
        # An unsluggable title (CJK, all-symbol) yields "" — renaming to it produces a
        # file literally called ".md".  Never propose it; item 5 already reports the title.
        if not _new or _new == _sl: continue
        _rename_targets.setdefault(fold_name(_new), []).append(_sl)
        renames.append([_sl, _new, inbound.get(_e["path_key"], 0)])
    for _r in renames:
        # target_exists ⇒ likely duplicate/disambiguation; do NOT rename into it, flag both.
        # Compared FOLDED, because the destination is "taken" whenever a file the
        # vault's case-insensitive volume resolves to that name exists — except the
        # entry being renamed itself, whose case-only rename is one file changing
        # its own spelling and is safe. Two candidates aiming at ONE destination
        # counts too: applying both in sequence would have the second silently
        # overwrite the first.
        #
        # `on_disk_fold` is consulted as well as `fold_of`, and for the same
        # reason the item10/unparsed carve-out above consults it: a file that
        # is ON DISK but did not parse (no frontmatter, unreadable) is absent
        # from `entries`, so `fold_of` alone answers "free" for a destination
        # that is a real file. The approved rename is `mv wrong-name.md
        # broken.md`, which destroys it. Both sets are the same question —
        # "does a file already answer to this name?" — and only their union
        # answers it.
        _fold_new = fold_name(_r[1])
        _owner = fold_of.get(_fold_new)
        _r.append((_owner is not None and _owner != _r[0])
                  or _fold_new in on_disk_fold
                  or len(_rename_targets[_fold_new]) > 1)

    # ---- Hierarchy diagnostic (Task 3): existing parent/MOC state ----------
    # Reflects the EXISTING parents: from a prior run (blank on a never-linted vault). Under the MOC-root rule every
    # tree is rooted at the discipline's own MOC note, so NOTHING self-parents and the correct count is zero: every
    # slug reported here is stale parents: from a pre-MOC-root run or a hand-edit, which this run overwrites. That is
    # why check_rooting fires at >=1 — the old >=3 was the anchor-entry model's tolerance for ~1 legitimate root per
    # discipline, and there are no legitimate self-parents left to tolerate. See Task 3 / references/hierarchy.md.
    def _parent_targets(e):
        out = []
        for p in e.get("parents", []):
            m = re.match(r"\s*\[\[([^\]|#]+)", str(p))
            if not m:
                continue
            target = m.group(1).split("^", 1)[0].strip()
            target = target.replace("\\", "/").rsplit("/", 1)[-1]
            if target.lower().endswith(".md"):
                target = target[:-3]
            if target:
                out.append(target)
        return out
    # The scanner used to say a parent absent from ``entries`` was owned by
    # item10, but item10 deliberately scans body prose and Related only. That
    # left a missing ``parents:`` target invisible. Resolve against parsed
    # Wiki entries (including unambiguous aliases) and the discipline MOC
    # files in the vault root; root MOCs are legal hierarchy parents even
    # though they correctly sit outside the Wiki inventory.
    moc_states = []
    moc_root_keys = set()
    for _discipline, _counts in sorted(tag_counts.items()):
        if not _counts[0]:
            continue
        _moc_path = os.path.join(vault_root, _discipline + "-moc.md")
        _state = moc_marker_state(_moc_path)
        _state["discipline"] = _discipline
        moc_states.append(_state)
        if _state["state"] != "missing":
            moc_root_keys.add(fold_name(_discipline + "-moc"))

    def _resolve_parent_target(target):
        """Return ``(canonical_owner, reason)`` under hierarchy rules.

        A real filename precedes aliases.  A usable owner is a full Wiki entry
        or a root MOC; a legacy stub is a leaf and therefore cannot parent a
        full entry.  Root MOCs get an out-of-inventory sentinel so they cannot
        participate in entry cycles.
        """
        key = fold_name(target)
        if key in ambiguous_files:
            return None, "ambiguous"
        if key in fold_of and key in moc_root_keys:
            return None, "ambiguous"
        if key in fold_of:
            owner = fold_of[key]
            if entries[owner]["is_stub"]:
                return None, "stub"
            return owner, None
        # A real Wiki file outranks an alias in Obsidian even when that file
        # could not be parsed as an entry. It cannot serve as a hierarchy
        # parent until its own item0/item1 problem is repaired.
        if key in on_disk_fold:
            return None, ("ambiguous" if key in moc_root_keys else "unparsed")
        if key in moc_root_keys:
            return "@moc:" + key, None
        if key in ambiguous_aliases:
            return None, "ambiguous"
        if key in alias_of:
            owner = alias_of[key][0]
            if entries[owner]["is_stub"]:
                return None, "stub"
            return owner, None
        return None, "missing"

    canonical_parents = {
        sl: [(_target, *_resolve_parent_target(_target))
             for _target in _parent_targets(e)]
        for sl, e in entries.items()
    }

    # ``moc_consistency_findings`` is a report-only worklist for the readable
    # tree regions the linter already owns. Every MOC-local record has
    # ``kind``, ``discipline``, absolute ``path`` and ``message``; line-local
    # records also carry a 1-based ``line`` and link findings carry the
    # relevant ``slug``/``target`` where one is known. A cross-MOC
    # ``parent-union-mismatch`` instead carries ``slug``, ``disciplines``, and
    # the sorted bare targets in ``expected_parents``/``actual_parents``.
    # Nothing in this list grants write authority.
    moc_consistency_findings = []
    _moc_parse = {}

    def _moc_expected_label(entry, discipline):
        """Canonical visible label for an entry in one discipline MOC."""
        title = entry.get("title") or ""
        match = re.search(r"\s+\(([^()]*)\)\s*$", title)
        if match and slug(match.group(1)) == discipline:
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
        if _moc_state["state"] != "marked":
            continue
        _tree = {
            "structurally_parseable": True,
            "present": set(),
            "placements": {},
            "blocked_placements": set(),
            "top_level": [],
        }
        _moc_parse[_discipline] = _tree
        try:
            with open(_moc_state["path"], encoding="utf-8-sig") as _fh:
                _moc_lines = _fh.read().splitlines()
        except (OSError, UnicodeDecodeError) as _exc:
            # The marker probe succeeded but the file changed before this
            # second read. Preserve the state already observed and decline all
            # consistency inference from bytes we no longer have.
            _tree["structurally_parseable"] = False
            _moc_add(
                _moc_state, "tree-read-error",
                "marked MOC could not be read for tree consistency: %s: %s"
                % (type(_exc).__name__, _exc))
            continue
        _starts = [i for i, line in enumerate(_moc_lines)
                   if line == MOC_TREE_START]
        _ends = [i for i, line in enumerate(_moc_lines)
                 if line == MOC_TREE_END]
        if not (len(_starts) == len(_ends) == 1 and _starts[0] < _ends[0]):
            _tree["structurally_parseable"] = False
            _moc_add(
                _moc_state, "marker-changed",
                "ownership markers changed after marker-state inspection; "
                "tree consistency was not inferred")
            continue

        _stack = []                 # one parsed node at each active bullet level
        _previous_level = 0
        _seen_placement = {}        # (slug, nearest parent) -> first line
        for _idx in range(_starts[0] + 1, _ends[0]):
            _line = _moc_lines[_idx]
            _line_no = _idx + 1
            if not _line.strip():
                continue
            _bullet = _bullet_line.match(_line)
            if not _bullet:
                _tree["structurally_parseable"] = False
                _moc_add(
                    _moc_state, "malformed-line",
                    "owned tree line is not a nested '- ' bullet",
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
            if _level > 3:
                _moc_add(
                    _moc_state, "excessive-depth",
                    "tree bullet is deeper than the allowed three levels under the MOC root",
                    line=_line_no, depth=_level)

            _stack = _stack[:max(0, _level - 1)]
            _ancestor_safe = (_level == 1 or (
                len(_stack) >= _level - 1 and _stack[_level - 2]["safe"]))
            _node_safe = _indent_ok and _ancestor_safe
            _link = WIKILINK.fullmatch(_content)
            _linked_slug = None
            if _link is None and ("[[" in _content or "]]" in _content):
                _tree["structurally_parseable"] = False
                _node_safe = False
                _moc_add(
                    _moc_state, "malformed-line",
                    "linked tree bullets must contain exactly one whole-line wikilink",
                    line=_line_no)
            elif _link is not None:
                _raw_target = _link.group(1)
                _target = _raw_target.strip()
                _label = _link.group(2)
                _record, _status, _owner_path = _resolve_entry_file(_target)
                _alias_key = entry_link_key(_target)
                if _status == "missing":
                    if _alias_key in ambiguous_aliases:
                        _status = "ambiguous"
                    elif _alias_key in alias_of:
                        _record = entries[alias_of[_alias_key][0]]
                        _status = "parsed"
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
                    if _raw_target != _entry_slug:
                        _moc_add(
                            _moc_state, "noncanonical-target",
                            "MOC link resolves, but its target is not the canonical bare entry slug",
                            line=_line_no, slug=_entry_slug, target=_raw_target)
                    _expected_label = _moc_expected_label(_record, _discipline)
                    if _label != _expected_label:
                        _moc_add(
                            _moc_state, "noncanonical-label",
                            "MOC link label does not match the canonical discipline-scoped title",
                            line=_line_no, slug=_entry_slug,
                            label=_label, expected_label=_expected_label)
                    if _record["is_stub"]:
                        _node_safe = False
                        _moc_add(
                            _moc_state, "stub-link",
                            "legacy stubs must not be linked from a MOC tree",
                            line=_line_no, slug=_entry_slug, target=_target)
                    elif _discipline not in {
                            d.lower() for d in _record["tag_slugs"]
                            if d.lower() in VALID_TAGS}:
                        _node_safe = False
                        _moc_add(
                            _moc_state, "wrong-discipline-link",
                            "linked full entry does not carry this MOC's discipline tag",
                            line=_line_no, slug=_entry_slug, target=_target)
                    else:
                        # A uniquely resolvable alias, path, case variant, or
                        # wrong label is still this placement. Report its form
                        # without cascading into a false missing-entry finding.
                        _tree["present"].add(_entry_slug)
                        if _node_safe:
                            _linked_slug = _entry_slug
                            _parent = _discipline + "-moc"
                            for _ancestor in reversed(_stack):
                                if _ancestor["linked_slug"] is not None:
                                    _parent = _ancestor["linked_slug"]
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

        _required = {
            sl for sl, e in entries.items()
            if not e["is_stub"] and _discipline in {
                d.lower() for d in e["tag_slugs"] if d.lower() in VALID_TAGS}}
        for _missing_slug in sorted(_required - _tree["present"]):
            _moc_add(
                _moc_state, "missing-entry",
                "tagged full entry is absent from this marked MOC tree",
                slug=_missing_slug)

        _eponymous = entries.get(_discipline)
        if (_tree["structurally_parseable"] and _eponymous is not None
                and not _eponymous["is_stub"]
                and _discipline in {
                    d.lower() for d in _eponymous["tag_slugs"]
                    if d.lower() in VALID_TAGS}):
            _top_slugs = [node["slug"] for node in _tree["top_level"]]
            if _top_slugs != [_discipline]:
                _moc_add(
                    _moc_state, "eponymous-root",
                    "the eponymous discipline entry must be the single "
                    "top-level bullet, with every other branch nested below it",
                    slug=_discipline,
                    top_level_slugs=_top_slugs)

    # Compare the exact complete parents union only when every valid tagged
    # discipline has a marked, structurally parseable tree and the entry has a
    # usable placement in each. This prevents a partial/unowned/broken MOC from
    # turning an incomplete observation into a false union mismatch.
    for _entry_slug, _entry in sorted(entries.items()):
        if _entry["is_stub"]:
            continue
        _tagged_disciplines = sorted({
            d.lower() for d in _entry["tag_slugs"] if d.lower() in VALID_TAGS})
        if not _tagged_disciplines:
            continue
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
            for parent, _line in _moc_parse[d]["placements"][_entry_slug]})
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
                    "across all marked tagged MOCs"),
            })

    moc_consistency_findings.sort(key=lambda finding: (
        finding.get("discipline", ""),
        finding.get("line", 0),
        finding["kind"],
        finding.get("slug", ""),
        finding.get("target", ""),
    ))
    parent_state_findings = []
    for _entry_slug, _entry in sorted(entries.items()):
        if not _entry.get("parents"):
            continue
        if _entry["is_stub"]:
            parent_state_findings.append({
                "slug": _entry_slug,
                "kind": "stub-parented",
                "parents": list(_entry["parents"]),
                "message": "legacy stubs are unplaced leaves and must keep parents: []",
            })
        elif not _entry.get("tags_raw"):
            parent_state_findings.append({
                "slug": _entry_slug,
                "kind": "untagged-parented",
                "parents": list(_entry["parents"]),
                "message": "an untagged full entry has no discipline tree and must keep parents: []",
            })
    selfp = sorted(
        sl for sl, e in entries.items()
        if not e["is_stub"]
        and any(owner == sl for _target, owner, _reason in canonical_parents[sl]))

    # Placement is per discipline, because a multi-tagged entry stores the
    # union of its nearest ancestors. One valid edge cannot hide an absent
    # second-discipline edge, and a biology entry pointing only at the ML MOC
    # is not placed in biology. A broader full parent represents each valid
    # discipline it itself carries; a root MOC represents its own discipline.
    placement_gaps = []
    for sl, e in sorted(entries.items()):
        if e["is_stub"]:
            continue
        required = {d.lower() for d in e["tag_slugs"]
                    if d.lower() in VALID_TAGS}
        if not required:
            continue
        represented = set()
        for _target, owner, _reason in canonical_parents[sl]:
            if owner is None or owner == sl:
                continue
            if owner.startswith("@moc:"):
                moc_key = owner[len("@moc:"):]
                represented.update(
                    d for d in required
                    if moc_key == fold_name(d + "-moc"))
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
    placed_unparented = [gap["slug"] for gap in placement_gaps]

    unresolved_parents = []
    for _sl, _e in sorted(entries.items()):
        for _raw_parent in _e.get("parents", []):
            _match = re.match(r"\s*\[\[([^\]|#]+)", str(_raw_parent))
            if not _match:
                # Frontmatter form checks own malformed non-wikilink list
                # items. ``placed_unparented`` still exposes the resulting
                # absence of a usable hierarchy edge.
                continue
            _target = _match.group(1).split("^", 1)[0].strip()
            _target = _target.replace("\\", "/").rsplit("/", 1)[-1]
            if _target.lower().endswith(".md"):
                _target = _target[:-3]
            _owner, _reason = _resolve_parent_target(_target)
            if _reason is None:
                continue
            unresolved_parents.append({
                "slug": _sl,
                "parent": str(_raw_parent),
                "target": _target,
                "reason": _reason,
            })
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
            if owner in entries and not entries[owner]["is_stub"]
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
    per_disc, full_per_disc = {}, {}
    for sl,e in entries.items():
        if e["is_stub"]: continue
        for d in e["tag_slugs"]:
            full_per_disc[d] = full_per_disc.get(d,0) + 1
            if sl in selfp: per_disc[d] = per_disc.get(d,0) + 1

    return {
        # stamp the suggestion-log appends with this
        "run_timestamp": f"{datetime.datetime.now():%Y-%m-%d %H:%M}",
        "wiki_path": os.path.abspath(wiki),
        "vault_root": vault_root,
        "inventory": {
            "entries": len(entries),
            "full": len(fulls),
            "stubs": len(stubs),
            "full_slugs": sorted(fulls),
            "stub_slugs": sorted(stubs),
        },
        "discipline_tags": {d: {"full": c[0], "stub": c[1]} for d,c in sorted(tag_counts.items())},
        "off_enum_tags": {d: sorted(set(v)) for d,v in sorted(off_enum.items())},
        "untagged_full": sorted(untagged_full),
        "problems": [{"slug": s, "item": i, "message": m} for s,i,m in sorted(problems)],
        "problem_tally": tally_out,
        "collision_candidates": [{"a": a, "b": b, "probe": p, "detail": d}
                                 for a,b,p,d in sorted(collisions2)],
        "rename_candidates": [{"slug": s, "new_slug": n, "inbound_links": c, "target_exists": x}
                              for s,n,c,x in sorted(renames)],
        # `bare_noun_alias`: the matched surface is a single all-lowercase word
        # reached only through an alias — batch these in the report; the
        # closeness judgment itself stays with the executing agent (see build_backfill).
        "backfill_candidates": [{"slug": s, "target": t, "surface": f,
                                 "bare_noun_alias": key in bare_noun_alias,
                                 "organism_common_name":
                                     key in _organism_common_surf}
                                for s,t,f,key in sorted(backfill)],
        # Folder-level, report-only findings.  These are deliberately outside
        # `problems`: they are not entry checklist violations and must not
        # inflate per-entry problem tallies or imply deletion authority.
        "image_folder_findings": image_folder_findings,
        "hierarchy_diagnostic": {
            "full_entries": len(fulls),
            "self_parented": selfp,
            # Report-only state from the hierarchy last written (or not yet
            # written). These worklists do not authorize Task 3 or its
            # transitive scope expansion.
            "placed_unparented": placed_unparented,
            "placement_gaps": placement_gaps,
            "unresolved_parents": unresolved_parents,
            "parent_state_findings": parent_state_findings,
            "moc_marker_states": moc_states,
            "moc_consistency_findings": moc_consistency_findings,
            # Cycles of length >= 2 in `parents:` (the 1-cycle is `self_parented`).
            # Each is listed once, rotated to start at its alphabetically first
            # slug. Any entry named here has no path to a MOC root, so Task 3
            # must break the cycle before it can place either end.
            "parent_cycles": _cycles,
            "per_discipline": [{"discipline": d,
                                "self_parent": per_disc[d],
                                "full": full_per_disc.get(d, 0),
                                "check_rooting": per_disc[d] >= 1}   # trees root at the discipline MOC, so ANY self-parent is stale
                               for d in sorted(per_disc)],
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
    """A schema-clean full entry, so a case only carries the fault it names.

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
        subject = math_skeleton(base_term(title)) or math_skeleton(title) or title
        description = "%s is a worked example used by the self-test." % subject
    text += "description: %s\n" % json.dumps(description)
    text += _block("tags", tags)
    text += extra_keys
    text += _block("parents", parents)
    text += "read: false\n"
    body = prose
    is_stub = sources == ('"stub"',)
    # A clean full-entry fixture carries the required terminal footer even
    # when it has no related links. Pass ``related=False`` only when a test
    # deliberately exercises the missing-footer defect. Legacy stubs omit it.
    has_related_marker = any(
        _RELATED_HEAD_LINE.match(line)
        for line in strip_fenced(body).split("\n"))
    if (related is not False and (not is_stub or related)
            and not has_related_marker):
        body += "\n\n**Related:**" + ((" " + related) if related else "")
    if card is not False:
        term = card or title
        body += ("\n\n---\n\n## Flashcards\n\n"
                 "The idea this entry is about, stated once.\n??\n%s\n" % term)
    return "---\n" + text + "---\n" + body + "\n"


def _st_write(root, relpath, text, encoding="utf-8"):
    path = os.path.join(root, *relpath.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode, kw = ("wb", {}) if isinstance(text, bytes) else ("w", {"encoding": encoding})
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

    tmp = tempfile.mkdtemp(prefix="scan_vault-selftest-")
    try:
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
        _st_write(v, "stubby.md", _st_entry(
            "Stubby", "**Stubby** is a placeholder.", sources=('"stub"',), card=False))
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
        for _name, _raw in (("flow-leading", ',"alias"'),
                            ("flow-middle", '"alias",,"other"'),
                            ("flow-trailing", '"alias",')):
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
        res = scan(v)
        check("flow lists with leading, middle, or trailing empty elements are item 1",
              ["item1" in _st_keys(res, slug_) for slug_ in
               ("flow-leading", "flow-middle", "flow-trailing")],
              [True] * 3)

        check("a schema-clean entry produces no finding at all",
              _st_keys(res, "anchor"), [])
        check("...and is parsed into the inventory",
              res["inventory"]["full"] >= 1 and "anchor" in res["inventory"]["full_slugs"],
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
        check("CRLF line endings parse", _st_keys(res, "crlf"), [])
        check("...and a CRLF blank line after the frontmatter is still item9",
              _st_keys(res, "crlf-blank"), ["item9"])
        check("sources: [\"stub\"] is a stub",
              res["inventory"]["stub_slugs"], ["stubby"])
        check("an entry in a subfolder is scanned", "nested" in res["inventory"]["full_slugs"], True)
        if have_symlink:
            check("an entry in a SYMLINKED subfolder is scanned",
                  "symlinked" in res["inventory"]["full_slugs"], True)
        check("valid-frontmatter records remain inventoried while the four "
              "unreadable or non-frontmatter files are excluded",
              res["inventory"]["entries"], 10 + (1 if have_symlink else 0))

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
              (res1["inventory"]["entries"], res1["inventory"]["full"],
               res1["problems"]), (1, 1, []))

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
        check("...and item10/unparsed says never to stub it",
              "NEVER stub" in _st_msg(res, "hub", "item10/unparsed"), True)
        check("a path-qualified target resolves",
              "sub/delta" in _st_msg(res, "hub", "item10/dangling"), False)
        check("an explicit .md suffix resolves",
              "delta.md" in _st_msg(res, "hub", "item10/dangling"), False)
        check("a document link (.pdf) is not an entry link",
              "Doe_Foo_2025.pdf" in _st_msg(res, "hub", "item10/dangling"), False)
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
               'canonical target "Beta" at "b/foo"'
               in _st_msg(res, "wrong-qualified-reader", "item18")),
              (True, True))
        check("a repeated ambiguous alias gets no duplicate-removal finding",
              "item10/dup" in _st_keys(res, "alias-reader"), False)
        check("the ambiguous alias remains report-only instead",
              _st_msg(res, "alias-reader", "item10/ambiguous").count(
                  "claimed as an alias by multiple entries"), 2)

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
            "??\nTwocards\n\nAnother notion, stated briefly.\n??\nSecond idea\n"))
        _st_write(v, "two-sentence-card.md", _st_entry(
            "Two sentence card", "**Two sentence card** is a worked example.",
            tags=())
            .replace("The idea this entry is about, stated once.",
                     "One identifying statement. Another statement."))
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
              ("not one of the 27" in _st_msg(res, "offenum", "item8"),
               sorted(res["off_enum_tags"])), (True, ["astrology", "ml"]))
        check("flow-form tags are rejected even when every value is valid",
              "flow-list syntax" in _st_msg(res, "flow-tags", "item8"), True)
        check("scalar tags are rejected even when the value is valid",
              "scalar syntax" in _st_msg(res, "scalar-tags", "item8"), True)
        check("a blank block-form tags key remains valid on a full entry",
              _st_keys(res, "blank-tags"), [])
        check("the tag census counts the enum tags",
              res["discipline_tags"].get("statistics", {}).get("full"), 3)
        check("a second flashcard trips the one-card cap",
              "exactly one card per entry" in _st_msg(res, "twocards", "item19"), True)
        check("flashcard line 1 must be one sentence",
              "roughly 2 sentences" in _st_msg(
                  res, "two-sentence-card", "item19"), True)

        # ------------------------------------------------------------------
        # 4. near-duplicate surfaces + the backfill worklist
        # ------------------------------------------------------------------
        check("plural_surface inflects the HEAD token, not the whole title",
              [plural_surface(t) for t in
               ("Confusion matrix", "Hypothesis", "ROC curve", "Analysis")],
              ["Confusion matrices", "Hypotheses", "ROC curves", "Analyses"])
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

        # Probe (f) uses the exact same shared stem key as wiki-builder, and it
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

        # writing.md's named corpus is the scanner's mechanical minimum.  A
        # single fixture over every term prevents additions to one copied list
        # from silently escaping both the filename and backfill gates.
        v = os.path.join(tmp, "v4d")
        for term in sorted(COMMON_NOUNS):
            title = term.capitalize()
            _st_write(v, term + ".md", _st_entry(
                title, "**%s** is a worked example." % title, card=title))
        _st_write(v, "reader.md", _st_entry(
            "Reader", "**Reader** compares " + ", ".join(sorted(COMMON_NOUNS))
            + "."))
        res4d = scan(v)
        check("every explicitly named common noun is rejected as a bare slug",
              {p["slug"] for p in res4d["problems"]
               if p["item"] == "item5" and "bare-slug common noun" in p["message"]},
              COMMON_NOUNS)
        check("none of the common-noun corpus becomes an automatic backfill target",
              [b for b in res4d["backfill_candidates"]
               if b["slug"] == "reader" and b["target"] in COMMON_NOUNS], [])

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
              "both copies of source_stem)",
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
        _st_write(v, "stub-parent.md", _st_entry(
            "Stub parent", "**Stub parent** is a placeholder.",
            sources=('"stub"',), card=False))
        _st_write(v, "stub-child.md", _st_entry(
            "Stub child", "**Stub child** is a worked example.",
            parents=('"[[stub-parent]]"',)))
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
        check("check_rooting fires on the self-parent's discipline",
              [d["check_rooting"] for d in h["per_discipline"]], [True])
        check("a legacy stub cannot serve as a hierarchy parent",
              [(x["slug"], x["target"], x["reason"])
               for x in h["unresolved_parents"]],
              [("stub-child", "stub-parent", "stub"),
               ("unparsed-child", "unparsed-owner", "unparsed")])

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
            parents=('"[[machine-learning-moc]]"',)))
        _st_write(v, "exact-file-child.md", _st_entry(
            "Exact file child", "**Exact file child** is a worked example.",
            tags=('"#machine-learning"',), parents=('"[[rooted]]"',)))
        _st_write(v, "ml-parent.md", _st_entry(
            "ML parent", "**ML parent** is a worked example.",
            tags=('"#machine-learning"',),
            parents=('"[[machine-learning-moc]]"',)))
        _st_write(v, "partial-multitag.md", _st_entry(
            "Partial multitag", "**Partial multitag** is a worked example.",
            tags=('"#machine-learning"', '"#statistics"'),
            parents=('"[[machine-learning-moc]]"',)))
        _st_write(v, "partial-via-entry.md", _st_entry(
            "Partial via entry", "**Partial via entry** is a worked example.",
            tags=('"#machine-learning"', '"#statistics"'),
            parents=('"[[ml-parent]]"',)))
        _st_write(v, "complete-multitag.md", _st_entry(
            "Complete multitag", "**Complete multitag** is a worked example.",
            tags=('"#machine-learning"', '"#statistics"'),
            parents=('"[[ml-parent]]"', '"[[statistics-moc]]"')))
        _st_write(v, "wrong-discipline-root.md", _st_entry(
            "Wrong discipline root",
            "**Wrong discipline root** is a worked example.",
            tags=('"#biology"',), parents=('"[[machine-learning-moc]]"',)))
        _st_write(v, "missing-entry-parent.md", _st_entry(
            "Missing entry parent", "**Missing entry parent** is a worked example.",
            tags=('"#machine-learning"',),
            parents=('"[[definitely-missing-parent]]"',)))
        _st_write(v, "alias-owner-a.md", _st_entry(
            "Alias owner A", "**Alias owner A** is a worked example.",
            tags=('"#machine-learning"',), aliases=('"rooted"',),
            parents=('"[[machine-learning-moc]]"',)))
        _st_write(v, "alias-owner-b.md", _st_entry(
            "Alias owner B", "**Alias owner B** is a worked example.",
            tags=('"#machine-learning"',), aliases=('"rooted"',),
            parents=('"[[machine-learning-moc]]"',)))
        for _discipline in ("statistics", "mathematics", "biology", "physics"):
            _title = _discipline.title() + " rooted"
            _st_write(v, _discipline + "-rooted.md", _st_entry(
                _title, "**%s** is a worked example." % _title,
                tags=(json.dumps("#" + _discipline),),
                parents=(json.dumps("[[%s-moc]]" % _discipline),)))
        _st_write(v, "chemistry-rooted.md", _st_entry(
            "Chemistry rooted", "**Chemistry rooted** is a worked example.",
            tags=('"#chemistry"',), parents=('"[[chemistry-moc]]"',)))
        _st_write(vr, "machine-learning-moc.md",
                  MOC_TREE_START + "\n- [[rooted|Rooted]]\n" + MOC_TREE_END + "\n")
        _st_write(vr, "statistics-moc.md", "- [[statistics-rooted|Statistics rooted]]\n")
        _st_write(vr, "mathematics-moc.md", "")
        _st_write(vr, "biology-moc.md",
                  "  " + MOC_TREE_START + "\n- [[biology-rooted|Biology rooted]]\n"
                  "  " + MOC_TREE_END + "\n")
        _st_write(vr, "chemistry-moc.md", b"\xff\xfe")
        res = scan(v)
        h = res["hierarchy_diagnostic"]
        check("the vault root is derived from the scanned Wiki directory",
              res["vault_root"], os.path.abspath(vr))
        check("a tagged full entry with no usable parent is report-only hierarchy backlog",
              h["placed_unparented"],
              ["missing-entry-parent", "partial-multitag", "partial-via-entry",
               "physics-rooted", "placed-empty", "wrong-discipline-root"])
        check("placement gaps retain the missing discipline for partial unions and wrong roots",
              [(x["slug"], x["missing_disciplines"],
                x["represented_disciplines"])
               for x in h["placement_gaps"]
               if x["slug"] in ("partial-multitag", "partial-via-entry",
                                "wrong-discipline-root")],
              [("partial-multitag", ["statistics"], ["machine-learning"]),
               ("partial-via-entry", ["statistics"], ["machine-learning"]),
               ("wrong-discipline-root", ["biology"], [])])
        check("a complete multi-discipline union has no placement gap",
              any(x["slug"] == "complete-multitag"
                  for x in h["placement_gaps"]), False)
        check("missing entry and root-MOC parents are reported, while an existing root MOC resolves",
              [(x["slug"], x["target"], x["reason"])
               for x in h["unresolved_parents"]],
              [("missing-entry-parent", "definitely-missing-parent", "missing"),
               ("physics-rooted", "physics-moc", "missing")])
        check("an exact parent file wins over entries that ambiguously claim the same alias",
              any(x["slug"] == "exact-file-child" for x in h["unresolved_parents"]), False)
        check("every discipline MOC has an explicit ownership-marker state",
              {x["discipline"]: x["state"] for x in h["moc_marker_states"]},
              {"biology": "malformed-marker", "machine-learning": "marked",
               "chemistry": "unreadable", "mathematics": "empty", "physics": "missing",
               "statistics": "legacy-unmarked"})
        check("an unreadable MOC carries its read error through the scan",
              [(x["state"], x.get("error", "").split(":", 1)[0])
               for x in h["moc_marker_states"]
               if x["discipline"] == "chemistry"],
              [("unreadable", "UnicodeDecodeError")])
        check("an indented marker pair is malformed even when both marker strings occur once",
              [(x["start_markers"], x["end_markers"])
               for x in h["moc_marker_states"] if x["discipline"] == "biology"],
              [(1, 1)])

        malformed = os.path.join(vr, "marker-shapes")
        _st_write(malformed, "partial.md", MOC_TREE_START + "\n")
        _st_write(malformed, "reversed.md", MOC_TREE_END + "\n" + MOC_TREE_START + "\n")
        _st_write(malformed, "duplicate.md",
                  MOC_TREE_START + "\n" + MOC_TREE_START + "\n" + MOC_TREE_END + "\n")
        check("partial, reversed, and duplicate marker shapes are all malformed",
              [moc_marker_state(os.path.join(malformed, name + ".md"))["state"]
               for name in ("partial", "reversed", "duplicate")],
              ["malformed-marker"] * 3)

        # A marked tree is the only region whose entry coverage and nearest
        # linked ancestors are mechanically knowable. Resolvable noncanonical
        # links remain placements, while broken structure blocks exact-union
        # comparison rather than manufacturing a partial answer.
        v = os.path.join(tmp, "v6c", "Wiki")
        vr = os.path.dirname(v)
        _st_write(v, "broad.md", _st_entry(
            "Broad", "**Broad** is a worked example.",
            tags=('"#machine-learning"',),
            parents=('"[[machine-learning-moc]]"',)))
        _st_write(v, "machine-learning.md", _st_entry(
            "Machine learning", "**Machine learning** is a worked example.",
            tags=('"#machine-learning"',),
            parents=('"[[machine-learning-moc]]"',)))
        for _name in ("Leaf", "Duplicate", "Deep"):
            _st_write(v, slug(_name) + ".md", _st_entry(
                _name, "**%s** is a worked example." % _name,
                tags=('"#machine-learning"',), parents=('"[[broad]]"',)))
        _st_write(v, "qualified-machine-learning.md", _st_entry(
            "Qualified (machine learning)",
            "**Qualified (machine learning)** is a worked example.",
            tags=('"#machine-learning"',), aliases=('"qualified-handle"',),
            parents=('"[[machine-learning-moc]]"',)))
        _st_write(v, "mismatch.md", _st_entry(
            "Mismatch", "**Mismatch** is a worked example.",
            tags=('"#machine-learning"',),
            parents=('"[[machine-learning-moc]]"',)))
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
        _st_write(v, "unmarked-union.md", _st_entry(
            "Unmarked union", "**Unmarked union** is a worked example.",
            tags=('"#machine-learning"', '"#physics"'),
            parents=('"[[machine-learning-moc]]"',)))
        _st_write(v, "suppressed.md", _st_entry(
            "Suppressed", "**Suppressed** is a worked example.",
            tags=('"#statistics"',), parents=('"[[wrong-parent]]"',)))
        _st_write(v, "stub-node.md", _st_entry(
            "Stub node", "**Stub node** is a placeholder.",
            tags=('"#machine-learning"',), sources=('"stub"',), card=False))
        _st_write(v, "biology-only.md", _st_entry(
            "Biology only", "**Biology only** is a worked example.",
            tags=('"#biology"',), parents=('"[[biology-moc]]"',)))
        _st_write(
            vr, "machine-learning-moc.md",
            "        - [[outside-missing|Outside missing]]\n"
            + MOC_TREE_START + "\n"
            "- [[broad|Broad]]\n"
            "  - [[leaf|Leaf]]\n"
            "  - [[duplicate|Duplicate]]\n"
            "  - [[duplicate|Duplicate]]\n"
            "  - Theme\n"
            "    - Subtheme\n"
            "      - [[deep|Deep]]\n"
            "  - [[mismatch|Mismatch]]\n"
            "  - [[partially-blocked|Partially blocked]]\n"
            "- [[qualified-handle|Qualified (machine learning)]]\n"
            "- [[unmarked-union|Unmarked union]]\n"
            "- [[stub-node|Stub node]]\n"
            "- [[biology-only|Biology only]]\n"
            "- [[does-not-exist|Does not exist]]\n"
            "  - [[blocked-child|Blocked child]]\n"
            "  - [[partially-blocked|Partially blocked]]\n"
            + MOC_TREE_END + "\n"
            "        - [[outside-missing-too|Outside missing too]]\n")
        _st_write(
            vr, "statistics-moc.md",
            MOC_TREE_START + "\n"
            "  - [[suppressed|Suppressed]]\n"
            "not a bullet\n"
            "- [[suppressed|Suppressed]]\n"
            + MOC_TREE_END + "\n")
        _st_write(vr, "physics-moc.md", "- [[unmarked-union|Unmarked union]]\n")
        res = scan(v)
        findings = res["hierarchy_diagnostic"]["moc_consistency_findings"]
        check("marked MOC consistency reports every deterministic issue class",
              {x["kind"] for x in findings},
              {"malformed-line", "malformed-indentation", "excessive-depth",
               "unresolved-link", "noncanonical-target", "noncanonical-label",
               "stub-link", "wrong-discipline-link", "missing-entry",
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
        check("stub, wrong-discipline, and unresolved links remain distinct",
              ([(x["kind"], x.get("slug"), x.get("target")) for x in findings
                if x["kind"] in {"stub-link", "wrong-discipline-link"}],
               [(x.get("target"), x.get("reason")) for x in findings
                if x["kind"] == "unresolved-link"]),
              ([('stub-link', 'stub-node', 'stub-node'),
                ('wrong-discipline-link', 'biology-only', 'biology-only')],
               [('does-not-exist', 'missing')]))
        check("duplicate placements use the same nearest linked parent",
              [(x.get("slug"), x.get("parent")) for x in findings
               if x["kind"] == "duplicate-placement"],
              [("duplicate", "broad")])
        check("depth is counted in bullet levels below the MOC root",
              [(x.get("slug"), x.get("depth")) for x in findings
               if x["kind"] == "excessive-depth"],
              [(None, 4)])
        check("tagged full entries absent from a marked owned region are reported",
              [x["slug"] for x in findings if x["kind"] == "missing-entry"
               and x["discipline"] == "machine-learning"],
              ["absent", "machine-learning"])
        check("the exact parent union is derived from the nearest linked ancestor",
              [(x["slug"], x["expected_parents"], x["actual_parents"])
               for x in findings if x["kind"] == "parent-union-mismatch"],
              [("mismatch", ["broad"], ["machine-learning-moc"])])
        check("unmarked, malformed, and missing-placement MOCs suppress union comparison",
              any(x["kind"] == "parent-union-mismatch"
                  and x.get("slug") in {"unmarked-union", "suppressed", "absent",
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
                ["broad", "qualified-machine-learning", "unmarked-union",
                 None, None, None])])
        check("content outside the unique marker pair is never parsed as owned tree",
              any(x.get("target", "").startswith("outside-missing")
                  for x in findings), False)

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
        _st_write(v, "a/path-old.md", _st_entry(
            "Alpha renamed", "**Alpha renamed** is a worked example."))
        _st_write(v, "b/path-old.md", _st_entry(
            "Beta renamed", "**Beta renamed** is a worked example."))
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
               "never stub" in _st_msg(res, "linker", "item10/alias")),
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
        check("ONE backticked identifier in a non-Software entry is over the zero cap "
              "(the one-signpost allowance was retired 2026-08-16)",
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
        check("a full entry whose opener has NO bold span at all is item16",
              (_st_keys(res, "unbolded"),
               "no bold span" in _st_msg(res, "unbolded", "item16")),
              (["item16"], True))
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
                   "Doe_X_2025_fig_4.ico"):
            open(os.path.join(_imgdir, _f), "w").close()
        # Valid sidecars/OS metadata stay quiet.  Nested and staging residue is
        # reported without making a nested-but-resolving embed look missing.
        for _f in (".figure-manifest.tsv", ".figure-review.txt", ".DS_Store"):
            open(os.path.join(_imgdir, _f), "w").close()
        os.makedirs(os.path.join(_imgdir, "nested"))
        open(os.path.join(_imgdir, "nested", "nested-only.png"), "w").close()
        os.makedirs(os.path.join(_imgdir, ".tmp"))
        open(os.path.join(_imgdir, ".tmp", "dl_1"), "w").close()
        open(os.path.join(_imgdir, ".trash_run.dltmp_1"), "w").close()
        _figbody = (
            "**Figured** is a worked example.\n\n"
            "![[Doe_X_2025_fig_99.png]]\n*A figure that is not on disk.*\n\n"
            "![[Doe_X_2025_fig_2.png]]\n*A figure that is.*\n\n"
            "![[Sources/Images/Doe_X_2025_fig_2.png]]\n*The same file, path-qualified.*\n\n"
            "![[Doe_X_2025_FIG_3.png]]\n*The same file in another case.*\n\n"
            "![[nested-only.png]]\n*A nested file that still resolves.*\n\n"
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
        check("...and it says not to delete the embed (the repair is at the "
              "filesystem, or is a §1a rename)",
              "DO NOT DELETE" in _st_msg(res, "figured", "item12/missing-image"), True)
        check("an .ico emitted by clipping-processor uses the same existence "
              "check as every other supported image extension",
              "fig_100.ico" in _st_msg(res, "figured", "item12/missing-image"), True)
        check("NEAR MISS: an embed that resolves — bare, path-qualified, or in "
              "another case on the vault's case-insensitive volume, or from a "
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
               ("nested", "nested-directory"),
               ("nested/nested-only.png", "nested-file")})
        check("intentional PDF sidecars and .DS_Store stay out of image-folder "
              "findings",
              any(finding["path"] in _IMAGE_ALLOWED_HIDDEN
                  for finding in res["image_folder_findings"]), False)
        check("image-folder findings are explicitly report-only",
              all("report only" in finding["message"]
                  and "do not" in finding["message"]
                  for finding in res["image_folder_findings"]), True)

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
                  .replace("read: false\n---\n", "read: false\n----\n", 1))
        _st_write(v, "fence-text.md",
                  _st_entry("Fence text", "**Fence text** is a worked example.",
                            card=False)
                  .replace("read: false\n---\n", "read: false\n--- closed\n", 1))
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
        # (c) a stub whose only `## Flashcards` line sits in a fence has NO
        #     flashcards section.
        _st_write(v, "stub-fence.md", _st_entry(
            "Stub fence", "**Stub fence** is a placeholder.\n\n"
            "```\n## Flashcards\n```",
            sources=('"stub"',), card=False))
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
        # (g) two alias spellings that fold to one name are reported within
        #     the entry, not only across entries.
        _st_write(v, "fold-dup.md", _st_entry(
            "Fold dup", "**Fold dup** is a worked example.",
            aliases=('"TPR"', '"tpr"')))
        res = scan(v)
        check("a `----` closing fence is item1, not a clean entry",
              _st_keys(res, "four-dash"), ["item1"])
        check("a `--- text` closing fence is item1, not a clean entry",
              _st_keys(res, "fence-text"), ["item1"])
        check("fenced Related/Flashcards samples produce no phantom section "
              "findings, and prose past the fence is still scanned",
              (_st_msg(res, "sw-listing", "item10/dangling""").count("does not resolve"),
               "phantom-target" in " ".join(p["message"] for p in res["problems"]),
               "genuinely-dangling" in _st_msg(res, "sw-listing", "item10/dangling")),
              (1, False, True))
        check("...and the real `## Flashcards` section (outside any fence) is "
              "still recognised on the same entry",
              "item19" in _st_keys(res, "sw-listing"), False)
        check("a stub whose only '## Flashcards' is inside a fence has no "
              "flashcards section",
              "item19" in _st_keys(res, "stub-fence"), False)
        check("'##  Flashcards' (double space) is a present section plus a "
              "heading-spelling finding, not a missing section",
              ("missing ## Flashcards" in _st_msg(res, "two-space", "item19"),
               'canonical heading is exactly "## Flashcards"'
               in _st_msg(res, "two-space", "item19")),
              (False, True))
        check("a stray `read:` line in the body is an item13 scar",
              "item13" in _st_keys(res, "read-scar"), True)
        check("a hyphenated title leaking in its SPACED spelling is caught",
              "fine tuning" in _st_msg(res, "fine-tuning", "item19").lower()
              and "leaks the answer" in _st_msg(res, "fine-tuning", "item19"),
              True)
        check("a disambiguated title's primary card (line 3 = base term) "
              "gets the alias needles — the alias leak is caught",
              'leaks the answer ("attribute")'
              in _st_msg(res, "feature-machine-learning", "item19"), True)
        check("two alias spellings folding to one name are an item18 finding "
              "within the entry",
              "differ only in case/normalization"
              in _st_msg(res, "fold-dup", "item18"), True)

        # (h) backfill: a candidate reached only through a single lowercase
        #     alias word is tagged bare_noun_alias; a title-surface candidate
        #     is not.
        v = os.path.join(tmp, "v12c")
        _st_write(v, "feature-machine-learning.md", _st_entry(
            "Feature (machine learning)",
            "**Feature (machine learning)** is a worked example.",
            aliases=('"attribute"',)))
        _st_write(v, "gradient-descent.md", _st_entry(
            "Gradient descent", "**Gradient descent** is a worked example."))
        _st_write(v, "user.md", _st_entry(
            "User", "**User** is a worked example. Each attribute feeds the "
                    "model, and gradient descent fits it."))
        res = scan(v)
        _bf = {(b["target"], b["bare_noun_alias"]) for b in res["backfill_candidates"]
               if b["slug"] == "user"}
        check("an alias-mediated bare-noun surface is tagged bare_noun_alias "
              "and a title surface is not",
              (("feature-machine-learning", True) in _bf,
               ("gradient-descent", False) in _bf),
              (True, True))

        v = os.path.join(tmp, "v13-validation")
        for i, source in enumerate(("[[Doe_X_2025.pdf]]", "[[Doe_X_2025.pdf#page=0]]",
                                  "[[Doe_X_2025.pdf#page=01]]",
                                  "[[Doe_X_2025.pdf#page=1garbage]]",
                                  "https://example.test/Doe_X_2025.pdf#page=1",
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
        check("empty provenance is not a clean full entry", "item4" in _st_keys(res, "no-source"), True)
        check("unknown review states route report-only, never read-type",
              [sorted(k for k in _st_keys(res, "unknown-%d" % i) if k.startswith("item2/read"))
               for i in range(4)], [["item2/read-unknown"]] * 4)
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
            "qualified": "**Qualified** links [[sub/recall.md|Recall]]. Recall measures sensitivity.",
            "case": "**Case** links [[RECALL|Recall]]. Recall measures sensitivity.",
            "alias": "**Alias** links [[true-positive-rate|Sensitivity]]. Recall measures sensitivity.",
            "plain": "**Plain** explains why Recall measures sensitivity.",
        }
        for name, prose in texts.items():
            _st_write(v, name + ".md", _st_entry(name.title(), prose, type_="Software"))
        res = scan(v)
        check("backfill ignores listings and already-linked destinations, but a shown link cannot hide real prose",
              sorted(b["slug"] for b in res["backfill_candidates"] if b["target"] == "recall"),
              ["plain", "sample"])

        v = os.path.join(tmp, "v15-preserved-content")
        for name, tail in (
                ('studied', '<!--SR:!2026-09-20,30,250!2026-09-21,31,250-->\n\n<!-- preserved state -->\n'),
                ('multiline', '<!--SR:\n!2026-09-20,30,250\n\n!2026-09-21,31,250\n-->\n')):
            text = _st_entry(name.title(), '**%s** is a worked example.' % name.title())
            text = text.replace('read: false', 'read: true').replace('\n??\n', '\n!!\n') + tail
            _st_write(v, name + '.md', text)
        _st_write(v, 'extra.md', _st_entry('Extra', '**Extra** is a worked example.')
                  + '<!--SR:!2026-09-20,30,250-->\n\n<!-- preserved state -->\n\n'
                  + 'A different main claim.\n??\nAnother term\n')
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
        check("studied cards keep their multiline or separated review comments",
              [k for name in ('studied', 'multiline') for k in _st_keys(res, name)
               if k == 'item19'], [])
        check("metadata is not counted, but a genuine second card still is",
              '2 cards' in _st_msg(res, 'extra', 'item19'), True)
        check("a fence with trailing text cannot end the listing or hide the real flashcard",
              [k for name in ('backticks', 'tildes', 'indented-closer', 'nested-fence') for k in _st_keys(res, name)
               if k in ('item10/dangling', 'item19')], [])
        check("qualified case and explicit-extension links are never false danglers",
              'item10/dangling' in _st_keys(res, 'linked'), False)
        check("qualified unparsed destinations still route to the file's own repair",
              _st_keys(res, 'linked').count('item10/unparsed'), 2)
        check("the scanner leaves review histories and all input bytes untouched",
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
            inaccessible = scan(v)
        check("an unreadable directory is reported even with no readable entries",
              any(p['item'] == 'item0' and 'directory' in p['message']
                  for p in inaccessible['problems']), True)

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
        _st_write(v, 'full.md', _st_entry('Full', '**Full** is a worked example.'))
        for name in ('stub-one', 'stub-two'):
            _st_write(v, name + '.md', _st_entry(name.title(), '**%s** is a placeholder.' % name.title(),
                      sources=('"stub"',), tags=(), card=False))
        res = scan(v)
        check("stub findings cannot inflate the reported percentage of affected full entries",
              [(p['entries'], p['pct_of_full']) for p in res['problem_tally'] if p['item'] == 'item8'],
              [(2, 0)])

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
        _st_write(v, "wrong-level-heading.md", _st_entry(
            "Wrong level heading", "**Wrong level heading** is a worked example.\n\n"
            "### A narrower aspect\n\nThe aspect remains part of the entry."))
        _st_write(v, "marked-up-heading.md", _st_entry(
            "Marked up heading", "**Marked up heading** is a worked example.\n\n"
            "## [[canonical-target|A linked aspect]]\n\nThe aspect remains part of the entry."))
        _st_write(v, "two-sentence-description.md", _st_entry(
            "Two sentence description",
            "**Two sentence description** is a worked example.",
            description="Two sentence description states one claim. It adds another."))
        _st_write(v, "question-description.md", _st_entry(
            "Question description", "**Question description** is a worked example.",
            description="Question description asks why? It supplies an answer."))
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
            card="A search"))
        res = scan(v)
        check("invalid and list-valued type fields both fail the canonical enum",
              ["item2/type-enum" in _st_keys(res, name)
               for name in ("invalid-type", "list-type")], [True, True])
        check("description capitalization and terminal-period checks are independent",
              ("capitalized" in _st_msg(res, "lower-description", "item7"),
               "period" in _st_msg(res, "periodless-description", "item7")),
              (True, True))
        check("body headings use exactly ## and plain text",
              ["item9" in _st_keys(res, slug_) for slug_ in
               ("wrong-level-heading", "marked-up-heading")],
              [True, True])
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
              "canonical title/base term" in _st_msg(res, "fairness", "item7"), True)
        check("a placeholder subject is an item-7 mismatch",
              "canonical title/base term" in _st_msg(
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
        check("an explicitly empty flow aliases list has list shape",
              "item18" in _st_keys(res, "empty-flow-alias"), False)
        check("a symbol title's plain-text skeleton may be the description subject",
              "item7" in _st_keys(res, "k-nearest-neighbors"), False)
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
               for b in res["backfill_candidates"]
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
              "Canonical target" in _st_msg(res, "related-alias", "item11"), True)
        check("a Related display label must equal the target's canonical title",
              "canonical title"
              in _st_msg(res, "related-wrong-label", "item11"), True)
        check("fully piped Related links are the valid near miss",
              "item11" in _st_keys(res, "related-piped"), False)
        check("a flashcard term unrelated to the canonical title is rejected",
              "must be exactly"
              in _st_msg(res, "wrong-card", "item19"), True)
        check("parenthetical, math and acronym primary-answer forms stay valid",
              ["item19" in _st_keys(res, name) for name in
               ("feature-machine-learning", "k-nearest-neighbors",
                "principal-component-analysis")], [False, False, False])
        check("compound-derived and shared-tail acronyms remain valid counterparts",
              [_acronym_counterpart(short, long) for short, long in (
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
        check("pseudonyms and a later bold parenthetical are not acronym counterparts",
              ["item19" in _st_keys(res, name)
               for name in ("mark-twain", "counterpart-scope")], [False, False])
        check("an unrelated noun phrase and later parenthetical do not bind to "
              "the bolded title",
              bool(_BOLD_PAREN_RE.search(
                  "**Algorithm counterpart** predicts a class (AC) nearby.")),
              False)

        v = os.path.join(tmp, "v22-stub-structure")
        _st_write(v, "w-e-b-du-bois.md", _st_entry(
            "W. E. B. Du Bois",
            "**W. E. B. Du Bois** (b. 1868) was an American sociologist.",
            type_="Person", sources=('"stub"',), card=False))
        _st_write(v, "two-sentence-stub.md", _st_entry(
            "Two sentence stub",
            "**Two sentence stub** is a placeholder. It has another sentence.",
            sources=('"stub"',), card=False))
        _st_write(v, "two-paragraph-stub.md", _st_entry(
            "Two paragraph stub",
            "**Two paragraph stub** is a placeholder.\n\nIt has another paragraph.",
            sources=('"stub"',), card=False))
        _st_write(v, "empty-stub.md", _st_entry(
            "Empty stub", "", sources=('"stub"',), card=False))
        _st_write(v, "image-stub.md", _st_entry(
            "Image stub",
            "**Image stub** contains ![[figure.png]] and ![alt](figure-2.png).",
            sources=('"stub"',), card=False))
        _st_write(v, "image-text-stub.md", _st_entry(
            "Image text stub",
            "**Image text stub** names figure.png and the word image in prose.",
            sources=('"stub"',), card=False))
        _st_write(v, "image-code-stub.md", _st_entry(
            "Image code stub",
            "**Image code stub** shows `![[figure.png]]` as literal syntax.",
            sources=('"stub"',), card=False))
        _st_write(v, "dated-person.md", _st_entry(
            "Dated person", "**Dated person** (1901–1980) was a researcher.",
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
        check("initials, abbreviations and a birth year keep a one-sentence Person stub valid",
              [k for k in _st_keys(res, "w-e-b-du-bois")
               if k in ("stub-one-sentence-body", "stub-no-images")], [])
        check("Person/Event dates pass only in the parenthetical after the bold subject",
              ["item9" in _st_keys(res, name) for name in
               ("dated-person", "misplaced-person-date",
                "dated-event", "missing-event-date",
                "malformed-person-date", "unspaced-person-date",
                "malformed-event-date",
                "impossible-event-date")],
              [False, True, False, True, True, True, True, True])
        check("malformed and missing date messages stay distinguishable",
              ("exact forms" in _st_msg(res, "malformed-person-date", "item9"),
               "exact forms" in _st_msg(res, "unspaced-person-date", "item9"),
               "needs a date" in _st_msg(res, "missing-event-date", "item9")),
              (True, True, True))
        check("two sentences, two paragraphs and no sentence each fail stub structure",
              ["stub-one-sentence-body" in _st_keys(res, name) for name in
               ("two-sentence-stub", "two-paragraph-stub", "empty-stub")],
              [True, True, True])
        check("Obsidian and Markdown image syntax both trigger the stub no-image rule",
              _st_keys(res, "image-stub").count("stub-no-images"), 1)
        check("image filenames in ordinary prose are the valid near miss",
              "stub-no-images" in _st_keys(res, "image-text-stub"), False)
        check("image syntax inside inline code is not a stub image",
              "stub-no-images" in _st_keys(res, "image-code-stub"), False)

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
        _st_write(v, "stub-equation.md", _st_entry(
            "Stub equation", "**Stub equation** is the square root of variance.",
            sources=('"stub"',), card=False))
        _st_write(v, "listing-equation.md", _st_entry(
            "Listing equation", "**Listing equation** shows `it is the square "
            "root of variance` as literal text.\n\n```text\n"
            "It is the square root of variance.\n```", type_="Software"))
        res = scan(v)
        check("an explicit square-root-of-variance definition with no display "
              "math becomes an equation-coverage candidate",
              "item12/equation-coverage-candidate" in
              _st_keys(res, "equationless"), True)
        check("a canonical display equation clears the narrow coverage candidate",
              "item12/equation-coverage-candidate" in
              _st_keys(res, "equation-present"), False)
        check("negated wording does not become an equation-coverage candidate",
              "item12/equation-coverage-candidate" in
              _st_keys(res, "negated-equation"), False)
        check("table cells stay outside the prose equation candidate floor",
              "item12/equation-coverage-candidate" in
              _st_keys(res, "table-equation"), False)
        check("Flashcards and legacy stubs stay outside equation coverage",
              ["item12/equation-coverage-candidate" in _st_keys(res, name)
               for name in ("flashcard-equation", "stub-equation")],
              [False, False])
        check("inline and fenced code stay outside equation coverage",
              "item12/equation-coverage-candidate" in
              _st_keys(res, "listing-equation"), False)

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
               '"Yeast" at "yeast"' in _st_msg(
                   res, "conflicting-display-reader", "item18")), (True, True))
        check("a display that exactly names another entry's unique alias is item18",
              ('different unique alias' in _st_msg(
                   res, "conflicting-display-reader", "item18"),
               "do not auto-retarget" in _st_msg(
                   res, "conflicting-display-reader", "item18")), (True, True))
        check("an exact alias display owned by the chosen target remains valid",
              "item18" in _st_keys(res, "same-owner-display-reader"), False)
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
        _st_write(v, "stub-parent.md", _st_entry(
            "Stub parent", "**Stub parent** is a placeholder.",
            sources=('"stub"',), parents=('"[[root]]"',), card=False))
        _st_write(v, "untagged-parent.md", _st_entry(
            "Untagged parent", "**Untagged parent** is a worked example.",
            tags=(), parents=('"[[root]]"',)))
        for _slug, _sentence in (
                ("meta-source", "This source gives the result."),
                ("meta-later", "As discussed later, the result holds."),
                ("meta-section", "In the previous section, the case was introduced."),
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
            "later, and stays above zero."))
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
        check("a component's synonym is not promoted to the entry's alias",
              "item17/alias-candidate" in _st_keys(res, "component-name"), False)
        check("empty and own-slug aliases are item18 findings",
              ["item18" in _st_keys(res, slug_) for slug_ in
               ("empty-alias", "own-alias")], [True, True])
        check("scalar, flow/empty spelling, plain, alias/case, and resolved-duplicate parents are form findings",
              ["item2/parents-form" in _st_keys(res, slug_) for slug_ in
               ("scalar-parent", "flow-parent", "spaced-empty-parent",
                "plain-parent", "alias-parent", "case-parent",
                "duplicate-parent")],
              [True] * 7)
        check("stub and untagged populated parents are distinct hierarchy-state findings",
              [(finding["slug"], finding["kind"])
               for finding in res["hierarchy_diagnostic"]["parent_state_findings"]],
              [("stub-parent", "stub-parented"),
               ("untagged-parent", "untagged-parented")])
        check("every previously omitted exact source-meta phrase is item14",
              ["item14" in _st_keys(res, slug_) for slug_ in
               ("meta-source", "meta-later", "meta-section", "meta-saw",
                "meta-figure")], [True] * 5)
        check("named-work, source-code, temporal-later, and geometric-above uses stay clean",
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
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [c for c in cases if not c[1]]
    for label, ok, got, want in cases:
        if not ok:
            print("FAIL  %s\n        got  %r\n        want %r" % (label, got, want))
    print("%d/%d self-test cases pass" % (len(cases) - len(failed), len(cases)))
    return 1 if failed else 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="scan_vault.py",
        description="Scan a wiki-builder vault and emit the wiki-linter Step 0 inventory as JSON.")
    ap.add_argument("wiki", nargs="?",
                    help="path to the vault's Wiki/ folder (walked recursively; "
                         "entries in subfolders are scanned too)")
    ap.add_argument("--images", metavar="DIR",
                    help="the vault's flat Sources/Images/ folder; with it, every "
                         "![[…]] image embed is checked to name a file that exists "
                         "(item12/missing-image), and nested or temporary artifacts "
                         "are reported in image_folder_findings. Omitted, neither "
                         "folder check runs")
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
    # A mistyped --images must not read as "the folder is empty": that reports
    # EVERY embed in the vault as naming a missing file, and the executing agent reading
    # that has no way to tell it from a genuinely broken vault. `isdir`, not
    # `exists` — a path that is a file satisfies `exists` and then lists nothing,
    # which is the same silent-empty failure. This script does not create the
    # folder, because a typo would create the typo.
    if args.images is not None and not os.path.isdir(args.images):
        ap.error("--images is not a directory: %s. No embed was checked; this is "
                 "not a vault with no images." % args.images)
    text = json.dumps(scan(args.wiki, args.images), ensure_ascii=False,
                      indent=(args.indent or None))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print("wrote %s" % args.out, file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
