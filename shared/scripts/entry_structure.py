#!/usr/bin/env python3
"""Shared structural checks for wiki-entry prose and flashcards.

These helpers deliberately inspect placement and spelling, not factual
correctness.  A Person/Event date is structurally valid only when a
parenthetical in one of wiki-builder's documented forms immediately follows
the first outer-bold subject; a year later in the sentence may describe
something else.

Stdlib only, Python 3.10+ (the plugin runtime floor).
"""

import argparse
import datetime
import os
import re
import sys
import unicodedata

# Keep sibling imports working when a harness loads this file directly by path
# rather than running it as a script (where Python supplies this path).
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from markdown_tables import markdown_block_start, markdown_table_spans

__all__ = [
    "answer_surface_match",
    "body_opens_with_prose",
    "count_sentences",
    "ends_with_sentence_period",
    "flashcard_line1_faults",
    "flashcard_line1_markup",
    "math_title_plain_text",
    "mask_body_comments",
    "mask_escaped_wikilinks",
    "opener_subject_date_status",
    "normalized_answer_surface",
    "opening_paragraph",
    "parse_flashcard_blocks",
    "sentence_prefix",
    "split_sentences",
    "strip_flashcard_review_metadata",
]


# A wiki title may use one inline-LaTeX region for a load-bearing mathematical
# symbol, while descriptions, wikilink labels, and flashcard answers must be
# plain text. These maps name mathematical content instead of deleting it.
# Formatting commands are handled separately because they contribute no
# content of their own.
_MATH_FORMATTING_COMMANDS = (
    "boldsymbol", "mathbf", "mathbb", "mathcal", "mathfrak", "mathit",
    "mathrm", "mathsf", "mathtt", "operatorname", "text",
)
_MATH_COMMAND_NAMES = {
    "alpha": "alpha", "beta": "beta", "gamma": "gamma",
    "delta": "delta", "epsilon": "epsilon", "varepsilon": "epsilon",
    "zeta": "zeta", "eta": "eta", "theta": "theta",
    "vartheta": "theta", "iota": "iota", "kappa": "kappa",
    "lambda": "lambda", "mu": "mu", "nu": "nu", "xi": "xi",
    "omicron": "omicron", "pi": "pi", "varpi": "pi", "rho": "rho",
    "varrho": "rho", "sigma": "sigma", "varsigma": "sigma",
    "tau": "tau", "upsilon": "upsilon", "phi": "phi",
    "varphi": "phi", "chi": "chi", "psi": "psi", "omega": "omega",
    "Gamma": "Gamma", "Delta": "Delta", "Theta": "Theta",
    "Lambda": "Lambda", "Xi": "Xi", "Pi": "Pi", "Sigma": "Sigma",
    "Upsilon": "Upsilon", "Phi": "Phi", "Psi": "Psi", "Omega": "Omega",
    "ell": "ell", "ast": "star", "star": "star", "infty": "infinity",
    "times": "times", "cdot": "dot", "pm": "plus-or-minus",
    "mp": "minus-or-plus", "le": "less-than-or-equal-to",
    "leq": "less-than-or-equal-to", "ge": "greater-than-or-equal-to",
    "geq": "greater-than-or-equal-to", "neq": "not-equal-to",
    "approx": "approximately", "sim": "similar-to", "to": "to",
}
_UNICODE_MATH_NAMES = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta",
    "ε": "epsilon", "ζ": "zeta", "η": "eta", "θ": "theta",
    "ι": "iota", "κ": "kappa", "λ": "lambda", "μ": "mu",
    "ν": "nu", "ξ": "xi", "ο": "omicron", "π": "pi",
    "ρ": "rho", "σ": "sigma", "ς": "sigma", "τ": "tau",
    "υ": "upsilon", "φ": "phi", "χ": "chi", "ψ": "psi",
    "ω": "omega", "Γ": "Gamma", "Δ": "Delta", "Θ": "Theta",
    "Λ": "Lambda", "Ξ": "Xi", "Π": "Pi", "Σ": "Sigma",
    "Υ": "Upsilon", "Φ": "Phi", "Χ": "Chi", "Ψ": "Psi",
    "Ω": "Omega", "ℓ": "ell",
}
_SUPERSCRIPT_CHARS = {
    "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
    "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
    "⁺": "+", "⁻": "-", "⁼": "=", "⁽": "(", "⁾": ")",
    "ⁱ": "i", "ⁿ": "n",
}
_SUPERSCRIPT_RE = re.compile(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁱⁿ]+")
_SUBSCRIPT_CHARS = {
    "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4",
    "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9",
    "₊": "+", "₋": "-", "₌": "=", "₍": "(", "₎": ")",
    "ₐ": "a", "ₑ": "e", "ₕ": "h", "ᵢ": "i", "ⱼ": "j",
    "ₖ": "k", "ₗ": "l", "ₘ": "m", "ₙ": "n", "ₒ": "o",
    "ₚ": "p", "ᵣ": "r", "ₛ": "s", "ₜ": "t", "ₓ": "x",
}
_SUBSCRIPT_RE = re.compile(
    "[%s]+" % re.escape("".join(_SUBSCRIPT_CHARS)))
_FORMATTING_RE = re.compile(
    r"\\(?:%s)\s*\{([^{}]*)\}" % "|".join(_MATH_FORMATTING_COMMANDS))


def _escaped_at(text, offset):
    """Whether the preceding backslash run escapes this Markdown delimiter."""
    start = offset
    while start and text[start - 1] == "\\":
        start -= 1
    return (offset - start) % 2 == 1


def mask_body_comments(text, *, mask_code=False):
    """Blank HTML/Obsidian comments, retaining every character/line offset.

    Use only for the read-only explanatory-body view, never for flashcard
    content: its separate parser must preserve and validate review attachments.
    Comment delimiters shown in code are literal. Parse comments before code
    masking so a fence shown *inside* a comment cannot hide later visible prose.
    Link inventories may additionally blank those code spans with mask_code.
    """
    text = text or ""
    chars = list(text)
    def blank(start, end):
        for pos in range(start, end):
            if chars[pos] not in "\r\n":
                chars[pos] = " "

    index, fence, fence_indent = 0, None, 0
    previous_nonblank = ""
    previous_blank = True
    indented_code = False
    while index < len(text):
        if index == 0 or text[index - 1] == "\n":
            end = text.find("\n", index)
            end = len(text) if end < 0 else end
            line = text[index:end]
            match = re.match(r"^(\s*)(`{3,}|~{3,})(.*)$", line)
            if fence:
                if (match and match[2][0] == fence[0]
                        and len(match[2]) >= len(fence)
                        and not match[3].strip()
                        and len(match[1].expandtabs(4)) <= fence_indent):
                    fence = None
                if mask_code:
                    blank(index, end)
                index = end + 1
                continue
            if match and not (match[2][0] == "`" and "`" in match[3]):
                fence, fence_indent = match[2], max(3, len(match[1].expandtabs(4)))
                if mask_code:
                    blank(index, end)
                index = end + 1
                previous_blank = False
                continue
            indented = bool(re.match(r"^(?: {4}|\t)", line))
            in_list = bool(
                re.match(r"^ {0,3}(?:[-*+]|\d{1,9}[.)])(?:\s|$)",
                         previous_nonblank)
                or previous_nonblank[:1].isspace())
            if indented_code and not line.strip():
                index = end + 1
                continue
            if indented and (indented_code or (previous_blank and not in_list)):
                indented_code = True
                if mask_code:
                    blank(index, end)
                index = end + 1
                continue
            indented_code = False
            previous_blank = not line.strip()
            if line.strip():
                previous_nonblank = line
        if text[index] == "`" and not _escaped_at(text, index):
            match = re.match(r"`+", text[index:])
            run = match[0]
            # Inline code may cross a soft newline, but the block parser
            # ends its paragraph before a blank line or a new structural block.
            # A later unrelated tick must not hide either one.
            remainder = text[index + len(run):]
            boundary = re.search(
                r"\n(?:[ \t]*\n| {0,3}(?:#{1,6}(?:[ \t]|$)|>[ \t]*|"
                r"`{3,}|~{3,}|(?:[-*+]|\d{1,9}[.)])[ \t]+|"
                r"(?:-{3,}|_{3,}|\*{3,}|={2,}|\$\$)[ \t]*(?:\n|$)))",
                remainder)
            code_region = remainder[:boundary.start()] if boundary else remainder
            close = re.search(r"(?<!`)" + re.escape(run) + r"(?!`)", code_region)
            if close is not None:
                end = index + len(run) + close.end()
                if mask_code:
                    blank(index, end)
                index = end
                continue
            index += len(run)
            continue
        opener = ("<!--" if text.startswith("<!--", index) else
                  "%%" if text.startswith("%%", index) else None)
        if opener and not _escaped_at(text, index):
            closer = "-->" if opener == "<!--" else "%%"
            end = text.find(closer, index + len(opener))
            # An unfinished body comment hides the remaining rendered body.
            end = len(text) if end < 0 else end + len(closer)
            blank(index, end)
            index = end
            continue
        index += 1
    return "".join(chars)


def mask_escaped_wikilinks(text):
    """Blank literal escaped wiki syntax so it cannot become a link action."""
    text = text or ""
    chars = list(text)
    for match in re.finditer(r"!?\[\[[^\]\n]*\]\]", text):
        start = match.start()
        bracket = start + int(text[start] == "!")
        if bracket != start and _escaped_at(text, start):
            # Escaping ! disables embedding, not the following live wikilink.
            # Remove the exclamation only from this read-only view so the
            # entry-link regex can see the remaining [[target]].
            chars[start] = " "
            continue
        if not _escaped_at(text, bracket):
            continue
        for index in range(start, match.end()):
            if chars[index] not in "\r\n":
                chars[index] = " "
    return "".join(chars)


def _math_fragment_plain_text(value):
    """Render a small title-math fragment without discarding command names."""
    value = value or ""
    for _ in range(8):
        unwrapped = _FORMATTING_RE.sub(r"\1", value)
        if unwrapped == value:
            break
        value = unwrapped

    # Common structural operators get a readable order before braces are
    # removed. The patterns are intentionally shallow: wiki titles contain a
    # symbol, not arbitrary display equations.
    for _ in range(4):
        rewritten = re.sub(
            r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}",
            lambda match: "%s over %s" % (
                _math_fragment_plain_text(match.group(1)),
                _math_fragment_plain_text(match.group(2))),
            value)
        rewritten = re.sub(
            r"\\sqrt\s*\{([^{}]*)\}",
            lambda match: "square-root-of-%s" %
            _math_fragment_plain_text(match.group(1)),
            rewritten)
        if rewritten == value:
            break
        value = rewritten

    def command_name(match):
        command = match.group(1)
        known = _MATH_COMMAND_NAMES.get(command)
        if known is not None:
            return known
        # Unknown commands remain visible and searchable instead of silently
        # disappearing as they did in the former local implementations.
        return " %s " % command.replace("_", "-")

    value = re.sub(r"\\([A-Za-z]+)", command_name, value)
    value = re.sub(r"\\[,;:!>]", "", value)
    value = re.sub(r"\\[ ~]", " ", value)
    return value.replace("{", "").replace("}", "").strip()


_SINGLE_DIGIT_NAMES = {
    "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
    "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine",
}


def _spoken_script_fragment(raw):
    """Name a small subscript/exponent without punctuation artifacts."""
    fragment = _math_fragment_plain_text(raw).strip().replace("−", "-")
    compact = re.sub(r"\s+", "", fragment)
    if compact in {"1/2", "1over2"}:
        return "one-half"
    if compact.startswith("-") and len(compact) > 1:
        tail = _spoken_script_fragment(compact[1:])
        return ("negative-" + tail) if tail else "negative"
    fragment = fragment.replace("+", " plus ")
    fragment = fragment.replace("-", " minus ")
    fragment = fragment.replace("=", " equals ")
    fragment = fragment.replace("/", " over ")
    fragment = re.sub(
        r"(?<![0-9])([0-9])(?![0-9])",
        lambda match: _SINGLE_DIGIT_NAMES[match.group(1)], fragment)
    return re.sub(r"[^0-9A-Za-z]+", "-", fragment).strip("-")


def _plain_subscript(raw):
    """Return a semantic suffix for a title's rendered subscript."""
    spoken = _spoken_script_fragment(raw)
    return ("-" + spoken) if spoken else ""


def _plain_tex_subscripts(value):
    """Speak LaTeX subscripts inside one inline-math fragment."""
    subscript = re.compile(r"_\s*\{([^{}]*)\}")
    for _ in range(8):
        rewritten = subscript.sub(
            lambda match: _plain_subscript(match.group(1)), value)
        if rewritten == value:
            break
        value = rewritten
    return re.sub(
        r"_\s*(\\[A-Za-z]+|[A-Za-z0-9+\-=])",
        lambda match: _plain_subscript(match.group(1)), value)


def _plain_exponent(raw):
    """Return a semantic suffix for a title's rendered exponent."""
    exponent = _math_fragment_plain_text(raw).strip()
    if exponent in {"*", "star"}:
        return "-star"
    if exponent == "2":
        return "-squared"
    if exponent == "3":
        return "-cubed"
    compact = re.sub(r"\s+", "", exponent).replace("−", "-")
    if compact == "-1":
        return "-inverse"
    if compact in {"1/2", "1over2"}:
        return "-to-the-one-half"
    if compact == "+":
        return "-plus"
    if not exponent:
        return ""
    spoken = _spoken_script_fragment(exponent)
    return ("-to-the-" + spoken) if spoken else ""


def math_title_plain_text(text):
    """Convert a mathematical wiki title to a meaning-preserving plain form.

    Ordinary title text and case are retained. Inline-LaTeX delimiters and
    formatting commands are removed while their content remains; Greek names
    and scripts are spoken so ``$A^{*}$ search`` becomes ``A-star search``,
    ``$\\ell_1$ norm`` becomes ``ell-one norm``, and both ``$\\chi^2$ test``
    and ``χ² test`` become ``chi-squared test``. Unknown LaTeX commands keep a
    readable command name rather than disappearing.
    """
    value = text or ""
    value = value.translate(str.maketrans(_UNICODE_MATH_NAMES))
    value = _SUPERSCRIPT_RE.sub(
        lambda match: _plain_exponent(
            match.group(0).translate(str.maketrans(_SUPERSCRIPT_CHARS))), value)
    value = _SUBSCRIPT_RE.sub(
        lambda match: _plain_subscript(
            match.group(0).translate(str.maketrans(_SUBSCRIPT_CHARS))), value)
    value = re.sub(
        r"\$([^$\n]*)\$",
        lambda match: "$%s$" % _plain_tex_subscripts(match.group(1)), value)
    value = value.replace("$", "")

    # Resolve braces from the inside out so formatting nested inside an
    # exponent still contributes to its spoken form.
    for _ in range(8):
        unwrapped = _FORMATTING_RE.sub(r"\1", value)
        if unwrapped == value:
            break
        value = unwrapped
    exponent = re.compile(r"\^\s*\{([^{}]*)\}")
    for _ in range(8):
        rewritten = exponent.sub(
            lambda match: _plain_exponent(match.group(1)), value)
        if rewritten == value:
            break
        value = rewritten
    value = re.sub(
        r"\^\s*(\\[A-Za-z]+|[A-Za-z0-9*+\-=])",
        lambda match: _plain_exponent(match.group(1)), value)

    value = _math_fragment_plain_text(value)
    return re.sub(r"\s+", " ", value).strip()


_BOLD_OUTER_RE = re.compile(
    r"(?<!\*)\*\*((?:\$[^$\n]+\$|\*[^*\n]+\*|[^*\n])+?)\*\*(?!\*)")

# The forms below mirror wiki-builder/references/rare-types.md. Historical
# years are not zero-padded: the BCE/CE rule explicitly needs values below
# 1000, so ``YYYY`` in the prose guide denotes a year rather than four literal
# digits. Exact ranges use an unspaced en dash; circa/unknown-bound ranges use
# the guide's spaced en dash. This intentionally rejects visually plausible
# alternatives such as ``1947 to 2020`` or a hyphenated ``1947-2020``.
_YEAR = r"(?:[1-9]\d{0,3})(?: (?:BCE|CE))?"
_EXACT_RANGE = rf"{_YEAR}–{_YEAR}"
_CIRCA_YEAR = rf"c\. {_YEAR}"
_CIRCA_RANGE = rf"(?:{_CIRCA_YEAR} – (?:{_CIRCA_YEAR}|{_YEAR})|{_YEAR} – {_CIRCA_YEAR})"
_PARTIAL_RANGE = rf"(?:(?:{_CIRCA_YEAR}|{_YEAR}) – \?|\? – (?:{_CIRCA_YEAR}|{_YEAR}))"
_FLORUIT_RANGE = rf"fl\. {_YEAR}–{_YEAR}"
_BORN = rf"b\. {_YEAR}"
_CALENDAR_DATE = r"(?:[1-9]\d{3})-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])"
_CALENDAR_DATE_RE = re.compile(_CALENDAR_DATE)

_PERSON_DATE_RE = re.compile(
    rf"(?:{_EXACT_RANGE}|{_CIRCA_RANGE}|{_PARTIAL_RANGE}|{_FLORUIT_RANGE}|{_BORN})")
_EVENT_DATE_RE = re.compile(
    rf"(?:{_YEAR}|{_CALENDAR_DATE}|{_EXACT_RANGE}|{_CIRCA_YEAR}|"
    rf"{_CIRCA_RANGE}|{_PARTIAL_RANGE}|(?:annual|ongoing), since {_YEAR})")


# Sentence-shape checks are shared because wiki-builder and wiki-linter apply
# the same floor to descriptions, legacy stubs, and flashcard definitions.  A
# duplicated implementation previously disagreed on quoted sentence endings:
# ``... called them \"cells.\"`` was valid prose but the linter looked only at
# the final byte and reported a missing period.
_ABBREVS = [
    "e.g.", "i.e.", "cf.", "et al.", "approx.", "vs.", "ca.", "c.", "fl.",
    "Dr.", "Prof.", "Mr.", "Mrs.", "Ms.", "St.", "Jr.", "Sr.", "Fig.",
    "b.", "d.", "r.", "U.S.", "U.K.", "var.", "subsp.", "ssp.",
    "sp.", "spp.", "aff.", "cv.", "fo.", "Dept.", "Inc.", "vol.",
    "pp.",
]
_ABBREV_RE = re.compile(
    r"(?:^|[^0-9A-Za-z])(?:%s)$"
    % "|".join(re.escape(a) for a in sorted(_ABBREVS, key=len, reverse=True)),
    re.IGNORECASE,
)
# ``No.`` is an abbreviation only with its conventional capitalization.
# Folding it case-insensitively made the ordinary sentence ending in
# ``yes or no.`` disappear from the sentence count.
_CASE_SENSITIVE_ABBREV_RE = re.compile(r"(?:^|[^0-9A-Za-z])No\.$")
_INITIAL_RE = re.compile(r"(?:^|[^0-9A-Za-z'’])[A-Za-z]\.$")
_NEXT_INITIAL_RE = re.compile(r"^\s+[A-Za-z]\.\s")
_HONORIFIC_TAIL_RE = re.compile(r"(?:^|\s)(?:Dr|Prof|Mr|Mrs|Ms)\.\s*$")
_PREVIOUS_INITIAL_TAIL_RE = re.compile(r"(?:^|\s)[A-Za-z]\.\s*$")
_STRONG_SENTENCE_START_RE = re.compile(
    r"^\s+(?:A|An|The|This|That|These|Those|It|Its|He|His|She|Her|"
    r"They|Their|We|Our|You|Your|I|My|"
    r"However|But|Yet|Meanwhile|Therefore)\b")
_CLAUSE_END_ABBREV_RE = re.compile(
    r"(?:^|[^0-9A-Za-z])(?:U\.S\.|U\.K\.|et al\.)$", re.IGNORECASE)
_SENTENCE_CLOSERS = "\"'”’»)]}"
_TERMINAL_PERIOD_RE = re.compile(
    r"\.(?:[\"'”’»)\]}]*)\s*$")

_OBSIDIAN_LINK_RE = re.compile(r"!?\[\[[^\]\n]+\]\]")
_MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]\n]*\]\([^\n)]*\)")
_MARKDOWN_REFERENCE_LINK_RE = re.compile(
    r"!?\[[^\]\n]*\]\[[^\]\n]*\]")
_MARKDOWN_REFERENCE_DEFINITION_RE = re.compile(
    r"(?:^ {0,3}\[[^\]\n]+\]:[ \t]*\S|"
    r"\[[^\]\n]+\]:[ \t]*<?https?://\S+)")
_INLINE_LATEX_RE = re.compile(
    r"(?<![\\$])\$(?!\$)(?:\\.|[^$\n])+?(?<!\\)\$(?!\$)")
_ASTERISK_EMPHASIS_RE = re.compile(
    r"(?<!\*)\*(?![\s*])[^*\n]*?(?<!\s)\*(?!\*)")
_UNDERSCORE_EMPHASIS_RE = re.compile(
    r"(?<![\w_])_(?![\s_])[^_\n]*?(?<![\s_])_(?![\w_])")
_HTML_RE = re.compile(r"<!--.*?-->|</?[A-Za-z][^>\n]*>")
_HTML_ENTITY_RE = re.compile(
    r"&(?:#[0-9]+|#x[0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]+);")
_OBSIDIAN_TAG_RE = re.compile(r"(?<![\w#])#[A-Za-z][\w/-]*")
_HIGHLIGHT_RE = re.compile(r"==[^=\n]+==")
_OBSIDIAN_COMMENT_RE = re.compile(r"%%.*?%%")
_FOOTNOTE_RE = re.compile(r"\[\^[^\]\n]+\]")
_BLOCK_MARKDOWN_RE = re.compile(
    r"^ {0,3}(?:#{1,6}[ \t]+|>[ \t]*|[-+*][ \t]+|\d+[.)][ \t]+)")
_INDENTED_CODE_RE = re.compile(r"^(?: {4}|\t)")
_NON_PROSE_BODY_START_RE = re.compile(
    r"^(?: {4}|\t| {0,3}(?:"
    r"\[[^\]\n]+\]:|"              # reference-definition-shaped metadata
    r"\$\$|!\[\[|!\["              # display or image
    r"))")


def body_opens_with_prose(text):
    """Whether the first nonblank body line can begin a prose paragraph.

    Keep its original indentation: four spaces or a tab make an indented code
    block, and calling ``lstrip`` before this decision turns that listing into
    apparent prose.  This is the shared item-9 structural floor used by both
    wiki-builder and wiki-linter; sentence quality remains an agent review.
    """
    lines = (text or "").split("\n")
    first_index = next((index for index, line in enumerate(lines)
                        if line.strip()), None)
    if first_index is None:
        return False
    first = lines[first_index]
    if (_NON_PROSE_BODY_START_RE.match(first)
            or markdown_block_start(first)):
        return False
    return not any(start == first_index
                   for start, _end in markdown_table_spans(text or ""))


def _sentence_end_offsets(compact):
    """Yield conservative sentence-end offsets in compacted prose."""
    for match in re.finditer(r"[.!?]+", compact):
        cursor = match.end()
        while cursor < len(compact) and compact[cursor] in _SENTENCE_CLOSERS:
            cursor += 1
        following = compact[cursor:cursor + 1]
        if following and not following.isspace():
            continue
        # A terminal period always ends the final sentence, even when its
        # last token is a one-letter label (``option A.``) or abbreviation.
        if not following:
            yield cursor
            continue
        if match.group(0) == ".":
            head = compact[max(0, match.end() - 16):match.end()]
            initial = bool(_INITIAL_RE.search(head))
            abbreviation = bool(
                _ABBREV_RE.search(head)
                or _CASE_SENSITIVE_ABBREV_RE.search(head))
            # An abbreviation can also end a sentence. Split only when the
            # following surface begins with a strong sentence-start word;
            # this preserves ``U.S. Army`` and ``e.g. linear regression``
            # while recognizing ``U.S. It runs online.``.
            if initial or abbreviation:
                before = compact[:match.start()]
                after = compact[cursor:]
                # Initial chains and honorific + initial forms are names, not
                # sentence boundaries. This matters especially for ``J. A.``:
                # the next ``A.`` otherwise looks like the article ``A``.
                name_initial = bool(
                    initial
                    and (_NEXT_INITIAL_RE.match(after)
                         or _PREVIOUS_INITIAL_TAIL_RE.search(before)
                         or _HONORIFIC_TAIL_RE.search(before)))
                clause_end = (not name_initial and initial) or bool(
                    _CLAUSE_END_ABBREV_RE.search(head))
                # An ordinary abbreviation may end a sentence before a clear
                # sentence-start word. Honorifics remain attached to names.
                if (abbreviation and not _HONORIFIC_TAIL_RE.search(head)
                        and not re.search(r"(?:^|[^A-Za-z])(?:Dr|Prof|Mr|Mrs|Ms)\.$",
                                          head)):
                    clause_end = True
                strong_next = bool(
                    _STRONG_SENTENCE_START_RE.search(compact[cursor:]))
                if not (clause_end and strong_next):
                    continue
        yield cursor


def sentence_prefix(text, end):
    """Return the current sentence's text before ``end``.

    The boundary rules are exactly those used by :func:`split_sentences`, so
    alias extraction cannot drift on initials or abbreviations.
    """
    prefix = (text or "")[:max(0, end)]
    start = 0
    for boundary in _sentence_end_offsets(prefix):
        start = boundary
    return prefix[start:].lstrip()


def split_sentences(text):
    """Conservatively split prose without breaking at initials/abbreviations.

    The returned surfaces have whitespace compacted but preserve punctuation
    and presentation text. An unterminated tail remains a surface; callers
    that require grammatical completion apply their own terminal check.
    """
    compact = " ".join((text or "").split())
    if not compact:
        return []
    surfaces = []
    start = 0
    for end in _sentence_end_offsets(compact):
        surface = compact[start:end].strip()
        if surface:
            surfaces.append(surface)
        start = end
    tail = compact[start:].strip()
    if tail:
        surfaces.append(tail)
    return surfaces


def opening_paragraph(text):
    """Return the first paragraph, recognizing whitespace-only blank lines."""
    value = (text or "").strip("\n")
    if not value:
        return ""
    return re.split(r"\n[ \t]*\n", value, maxsplit=1)[0].strip()


def count_sentences(text):
    """Conservatively count sentence-ending punctuation runs.

    Decimals, version dots, initials, and common abbreviations do not count as
    boundaries. Closing quotes and brackets may sit between the punctuation
    and following whitespace; they belong to the sentence rather than hiding
    its boundary.
    """
    compact = " ".join((text or "").split())
    return sum(1 for _ in _sentence_end_offsets(compact))


def ends_with_sentence_period(text):
    """Whether prose ends in a period, allowing closing quotes/brackets."""
    return bool(_TERMINAL_PERIOD_RE.search(text or ""))


def normalized_answer_surface(text):
    """Fold case, Unicode, punctuation, slashes, and whitespace for leaks.

    Identifier-significant symbols remain (``A*``, ``C++``, and ``C#`` do not
    collapse to a bare letter); other Unicode punctuation, including every
    dash and slash form, becomes space. This makes ``bias/variance``,
    ``bias–variance``, and ``bias variance`` the same answer surface without
    over-normalizing technical names.
    """
    value = unicodedata.normalize(
        "NFKC", math_title_plain_text(text)).casefold()
    # These mathematical separator lookalikes are Unicode symbols (Sm), not
    # punctuation, so the category-based rule below does not catch them.
    value = value.translate(str.maketrans({
        "$": " ",       # inline-LaTeX delimiter, not rendered answer text
        "\u2044": " ",  # fraction slash
        "\u2215": " ",  # division slash
        "\u2212": " ",  # minus sign
    }))
    value = "".join(
        " " if (char.isspace()
                or (char not in "#*" and
                    unicodedata.category(char).startswith("P"))) else char
        for char in value)
    return " ".join(value.split())


def answer_surface_match(text, candidate):
    """Return ``bounded`` for a whole answer surface, otherwise ``None``."""
    haystack = normalized_answer_surface(text)
    needle = normalized_answer_surface(candidate)
    if not needle:
        return None
    start = 0
    while True:
        found = haystack.find(needle, start)
        if found < 0:
            return None
        end = found + len(needle)
        identifier_chars = "#*+"
        left_ok = (found == 0 or not (
            haystack[found - 1].isalnum()
            or haystack[found - 1] in identifier_chars))
        right_ok = (end == len(haystack) or not (
            haystack[end].isalnum() or haystack[end] in identifier_chars))
        if left_ok and right_ok:
            return "bounded"
        start = found + 1


def flashcard_line1_markup(text):
    """Return forbidden Markdown/HTML forms in a card definition.

    Inline LaTeX is intentionally absent: it is the one markup form line 1
    permits. The labels are stable, human-readable evidence for both callers.
    """
    value = text or ""
    # Markdown-like characters can be valid mathematical syntax. Mask complete
    # inline-LaTeX spans before classifying presentation markup, while leaving
    # wrappers around a span visible (``**$x$**`` still reports bold).
    visible = _INLINE_LATEX_RE.sub(
        lambda match: " " * len(match.group(0)), value)
    faults = []
    if _OBSIDIAN_LINK_RE.search(visible):
        faults.append("wikilink/embed")
    if _MARKDOWN_LINK_RE.search(visible):
        faults.append("Markdown link/image")
    if _MARKDOWN_REFERENCE_LINK_RE.search(visible):
        faults.append("Markdown reference link/image")
    if _MARKDOWN_REFERENCE_DEFINITION_RE.search(visible):
        faults.append("Markdown reference definition")
    if "`" in visible:
        faults.append("backtick code")
    if "**" in visible or "__" in visible:
        faults.append("bold")
    if (_ASTERISK_EMPHASIS_RE.search(visible)
            or _UNDERSCORE_EMPHASIS_RE.search(visible)):
        faults.append("italic")
    if re.search(r"~~[^~\n]+~~", visible):
        faults.append("strikethrough")
    if _HTML_RE.search(visible):
        faults.append("HTML")
    if _HTML_ENTITY_RE.search(visible):
        faults.append("HTML entity")
    if _OBSIDIAN_TAG_RE.search(visible):
        faults.append("Obsidian tag")
    if _HIGHLIGHT_RE.search(visible):
        faults.append("highlight")
    if _OBSIDIAN_COMMENT_RE.search(visible):
        faults.append("Obsidian comment")
    if _FOOTNOTE_RE.search(visible):
        faults.append("footnote")
    if (_BLOCK_MARKDOWN_RE.search(visible)
            # Masking a leading ``$x$`` leaves spaces; inspect real indentation
            # so permitted inline LaTeX cannot manufacture a code block.
            or _INDENTED_CODE_RE.search(value)):
        faults.append("block Markdown")
    if "$$" in value:
        faults.append("display LaTeX")
    latex_remainder = _INLINE_LATEX_RE.sub("", value.replace("$$", ""))
    latex_remainder = re.sub(r"\\\$", "", latex_remainder)
    if "$" in latex_remainder:
        faults.append("unmatched LaTeX delimiter")
    return faults


def flashcard_line1_faults(text):
    """Return item-19 sentence/markup faults for one card definition."""
    value = (text or "").strip()
    faults = []
    sentence_start = value.lstrip(" \t\"'“‘([{")
    # A symbol or equation may legitimately begin the definition; do not read
    # the first LaTeX command letter as prose capitalization.
    if (sentence_start and not sentence_start.startswith("$")
            and sentence_start[0].isalpha()
            and not sentence_start[0].isupper()):
        faults.append("does not start with a capitalized word")
    if not ends_with_sentence_period(value):
        faults.append("does not end with a period")
    sentence_count = count_sentences(value)
    if sentence_count > 1:
        faults.append("contains roughly %d sentences" % sentence_count)
    markup = flashcard_line1_markup(text or "")
    if markup:
        faults.append("has forbidden %s" % ", ".join(markup))
    return faults


_FLASHCARD_BLOCK_ID_SUFFIX_RE = re.compile(
    r"[ \t]+\^[-A-Za-z0-9]+[ \t]*$")
_FLASHCARD_INLINE_SR_SUFFIX_RE = re.compile(
    r"[ \t]+<!--SR:(?:(?!-->).)*-->[ \t]*$")
_SR_METADATA_CALLOUT_RE = re.compile(
    r"^> \[!sr\|card-metadata\][ \t]*$")


def _full_line_html_comment_end(lines, start):
    """Return the end of a whole-line Spaced Repetition comment block."""
    if not re.match(r"^[ \t]*<!--SR:", lines[start]):
        return None
    for index in range(start, len(lines)):
        closing = lines[index].find("-->")
        if closing < 0:
            continue
        if lines[index][closing + 3:].strip():
            return None
        return index + 1
    # An unterminated comment is malformed visible content, not scheduling
    # metadata. Keep its source bytes untouched and expose it to item 19.
    return None


def _metadata_callout_end(lines, start):
    """Return the end of a complete Spaced Repetition metadata callout.

    Spaced Repetition 1.15 writes an exact ``sr|card-metadata`` callout whose
    quoted body contains the schedule comment. Restrict recognition to that
    marker and a body made only of the schedule comment (plus an optional
    Obsidian block ID) so an ordinary callout cannot hide malformed card text.
    """
    if not _SR_METADATA_CALLOUT_RE.match(lines[start]):
        return None
    index = start + 1
    started = False
    while index < len(lines):
        quoted = re.match(r"^>[ \t]?(.*)$", lines[index])
        if not quoted:
            return None
        content = quoted.group(1)
        if not started:
            if not content.strip():
                index += 1
                continue
            if not re.match(r"^[ \t]*<!--SR:", content):
                return None
            started = True
        closing = content.find("-->")
        if closing >= 0:
            suffix = content[closing + 3:]
            if (suffix.strip()
                    and not _FLASHCARD_BLOCK_ID_SUFFIX_RE.fullmatch(suffix)):
                return None
            return index + 1
        index += 1
    return None


def _strip_line3_review_metadata(line):
    """Return a card term without protected inline state, for linting only."""
    visible = line
    block_id = _FLASHCARD_BLOCK_ID_SUFFIX_RE.search(visible)
    if block_id:
        visible = visible[:block_id.start()]
    schedule = _FLASHCARD_INLINE_SR_SUFFIX_RE.search(visible)
    if schedule:
        visible = visible[:schedule.start()]
    return visible


def strip_flashcard_review_metadata(text):
    """Hide recognized review metadata from a read-only flashcard lint view.

    A schedule can be an inline suffix on content line 3, a following
    whole-line ``<!--SR:…-->`` block, or an ``sr|card-metadata`` callout. A
    trailing Obsidian block ID on line 3 or inside the callout is protected too.
    Only the returned linting view changes; callers retain the source bytes.
    Following-line metadata must begin immediately after line 3; a blank line or
    ordinary content ends the attachment position. Metadata in another position
    and ordinary visible content remain visible so item 19 can report malformed
    cards rather than silently discard content.
    """
    lines = (text or "").split("\n")
    visible = list(lines)
    ordinary_lines = 0
    card_complete = False
    index = 0
    while index < len(lines):
        if not lines[index].strip():
            ordinary_lines = 0
            card_complete = False
            index += 1
            continue

        # Only a complete, contiguous attachment immediately after line 3 is
        # protected. Keep accepting adjacent attachment blocks so unusual but
        # valid user-owned scheduling state is never reassigned or deleted.
        if card_complete:
            comment_end = _full_line_html_comment_end(lines, index)
            if comment_end is not None:
                for comment_line in range(index, comment_end):
                    visible[comment_line] = ""
                index = comment_end
                continue

            callout_end = _metadata_callout_end(lines, index)
            if callout_end is not None:
                for callout_line in range(index, callout_end):
                    visible[callout_line] = ""
                index = callout_end
                continue

            # The first non-attachment byte after line 3 closes the attachment
            # position. A later SR-looking block must remain visible.
            card_complete = False

        ordinary_lines += 1
        if ordinary_lines == 3:
            visible[index] = _strip_line3_review_metadata(lines[index])
            card_complete = True
        index += 1
    return "\n".join(visible)


def parse_flashcard_blocks(text):
    """Return visible flashcard blocks split on whitespace-only blank lines.

    Recognized Spaced Repetition state and trailing block IDs attached to a
    complete card are omitted by ``strip_flashcard_review_metadata``. Ordinary
    visible content stays in its block so callers can report it as malformed
    rather than silently treating it as review state.
    """
    visible = strip_flashcard_review_metadata(text)
    cards, buffer = [], []
    for line in visible.split("\n"):
        if not line.strip():
            if buffer:
                cards.append(buffer)
                buffer = []
        else:
            buffer.append(line)
    if buffer:
        cards.append(buffer)
    return cards


def opener_subject_date_status(opener, entry_type):
    """Return ``valid``, ``missing``, or ``malformed`` for the opener date.

    ``missing`` means no parenthetical immediately follows the first outer
    bold subject. ``malformed`` means that slot contains a parenthetical, but
    its complete content is not one of the documented forms for ``entry_type``.
    The function does not decide whether the dates themselves are factually
    correct.
    """
    bold = _BOLD_OUTER_RE.search(opener or "")
    if not bold:
        return "missing"
    tail = (opener or "")[bold.end():]
    parenthetical = re.match(r"(\s*)\(([^)\n]*)\)", tail)
    if not parenthetical:
        return "missing"
    if not parenthetical.group(1):
        return "malformed"
    value = parenthetical.group(2)
    pattern = _PERSON_DATE_RE if entry_type == "Person" else _EVENT_DATE_RE
    if not pattern.fullmatch(value):
        return "malformed"
    if entry_type == "Event" and _CALENDAR_DATE_RE.fullmatch(value):
        try:
            datetime.datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return "malformed"
    return "valid"


def run_self_test(verbose=False):
    cases = [
        ("ordinary Person range", "Person",
         "**Isaac Newton** (1643–1727) was a physicist.", "valid"),
        ("living Person marker", "Person",
         "**Researcher** (b. 1947) works here.", "valid"),
        ("circa Person range", "Person",
         "**Scholar** (c. 460 BCE – c. 370 BCE) wrote treatises.", "valid"),
        ("one uncertain Person bound", "Person",
         "**Scholar** (c. 970 – 1037) wrote treatises.", "valid"),
        ("floruit Person range", "Person",
         "**Artist** (fl. 1480–1510) painted murals.", "valid"),
        ("partial Person range", "Person",
         "**Writer** (? – 1650) wrote essays.", "valid"),
        ("approximate partial Person range", "Person",
         "**Writer** (c. 1600 – ?) wrote essays.", "valid"),
        ("explicit CE disambiguator", "Person",
         "**Researcher** (b. 1947 CE) works here.", "valid"),
        ("leading prose and Event range", "Event",
         "The **Manhattan Project** (1942–1946) developed weapons.", "valid"),
        ("single-date Event", "Event",
         "The **Trinity test** (1945-07-16) was a detonation.", "valid"),
        ("approximate single-date Event", "Event",
         "**Festival** (c. 1900) was held once.", "valid"),
        ("recurring Event marker", "Event",
         "**Conference** (annual, since 1987) meets each year.", "valid"),
        ("ongoing Event marker", "Event",
         "**Program** (ongoing, since 2020) coordinates research.", "valid"),
        ("missing parenthetical", "Person",
         "**Researcher** was born in 1947.", "missing"),
        ("missing separator before parenthetical", "Person",
         "**Researcher**(1947–2020) was a scientist.", "malformed"),
        ("later unrelated parenthetical", "Person",
         "**Researcher** won a prize in 2020 (born 1947).", "missing"),
        ("word separator is malformed", "Person",
         "**Researcher** (1947 to 2020) was a scientist.", "malformed"),
        ("hyphen range is malformed", "Event",
         "**Festival** (1990-1992) was held yearly.", "malformed"),
        ("impossible calendar date is malformed", "Event",
         "**Festival** (1990-02-31) opened that day.", "malformed"),
        ("unlisted biographical phrase is malformed", "Person",
         "**Researcher** (born in 1947) is a scientist.", "malformed"),
        ("wrong recurring qualifier is malformed", "Event",
         "**Conference** (yearly since 1987) meets each year.", "malformed"),
    ]
    failed = 0
    for name, entry_type, opener, expected in cases:
        got = opener_subject_date_status(opener, entry_type)
        ok = got == expected
        if verbose or not ok:
            print(("PASS" if ok else "FAIL") + ": " + name)
        if not ok:
            print("  expected %r, got %r" % (expected, got))
            failed += 1
    helper_cases = [
        ("body opener distinguishes prose from Markdown blocks",
         [body_opens_with_prose(value) for value in (
             "A prose sentence opens the entry.", "", "+ item", "1. item",
             "1) item", ">quoted", "```python", "~~~text", "    code",
             "\tcode", "## Heading", "---", "| table |\n| --- |",
             "Metric | Value\n--- | ---", "[ref]: https://example.test",
             "<div>", "$$x$$", "![[figure.png]]")],
         [True] + [False] * 17),
        ("ordinary title text and case are preserved",
         math_title_plain_text("Ordinary Title-Case"),
         "Ordinary Title-Case"),
        ("inline math delimiters leave their symbol",
         math_title_plain_text("$k$-nearest neighbors"),
         "k-nearest neighbors"),
        ("formatting commands unwrap without losing content",
         [math_title_plain_text(value) for value in (
             r"$\mathbf{k}$-nearest neighbors",
             r"$\boldsymbol{k}$-nearest neighbors")],
         ["k-nearest neighbors", "k-nearest neighbors"]),
        ("a superscript star remains part of the algorithm name",
         [math_title_plain_text(value) for value in (
             "$A^{*}$ search", r"$\boldsymbol{A}^{\star}$ search")],
         ["A-star search", "A-star search"]),
        ("LaTeX and Unicode chi-squared share one stable form",
         [math_title_plain_text(value) for value in (
             r"$\chi^2$ test", "χ² test")],
         ["chi-squared test", "chi-squared test"]),
        ("LaTeX and Unicode ell-one subscripts share one stable form",
         [math_title_plain_text(value) for value in (
             r"$\ell_1$ norm", "ℓ₁ norm")],
         ["ell-one norm", "ell-one norm"]),
        ("inverse exponents name the inverse operation",
         [math_title_plain_text(value) for value in (
             r"$L^{-1}$ regularization", "L⁻¹ regularization")],
         ["L-inverse regularization", "L-inverse regularization"]),
        ("a one-half exponent remains semantic",
         math_title_plain_text(r"$x^{1/2}$ transform"),
         "x-to-the-one-half transform"),
        ("positive superscripts use a stable plus reading",
         [math_title_plain_text(value) for value in (r"$R^{+}$", "R⁺")],
         ["R-plus", "R-plus"]),
        ("general negative exponents do not create repeated hyphens",
         math_title_plain_text(r"$x^{-2}$ moment"),
         "x-to-the-negative-two moment"),
        ("an underscore outside inline math remains ordinary title text",
         math_title_plain_text("Ordinary_Title"),
         "Ordinary_Title"),
        ("common structural math remains readable",
         [math_title_plain_text(value) for value in (
             r"$\frac{a}{b}$ ratio", r"$\sqrt{x}$ transform")],
         ["a over b ratio", "square-root-of-x transform"]),
        ("an unknown command name cannot disappear",
         math_title_plain_text(r"$\frobnicate{x}$ norm"),
         "frobnicate x norm"),
        ("plain terminal period",
         ends_with_sentence_period("A complete definition."), True),
        ("period inside straight quotation marks",
         ends_with_sentence_period('Hooke called them "cells."'), True),
        ("period inside curly quotation marks and parenthesis",
         ends_with_sentence_period('The label was “cell.”)'), True),
        ("question mark is not the required card terminator",
         ends_with_sentence_period("Which quantity?"), False),
        ("closing quote does not hide a second sentence",
         count_sentences('One ends here." Another follows.'), 2),
        ("initials and decimal remain one sentence",
         count_sentences("B. F. Skinner used version 3.5."), 1),
        ("sentence splitting preserves abbreviations and initials",
         split_sentences(
             "B. F. Skinner worked in the U.S. and used examples, e.g. "
             "reinforcement schedules. A second sentence follows."),
         ["B. F. Skinner worked in the U.S. and used examples, e.g. "
          "reinforcement schedules.", "A second sentence follows."]),
        ("an initial chain beginning with J. A. stays in one sentence",
         split_sentences(
             "J. A. Swets developed detection theory. It matters."),
         ["J. A. Swets developed detection theory.", "It matters."]),
        ("common publication abbreviations stay inside their sentence",
         [split_sentences(value) for value in (
             "The U.S. Dept. sets rules. It enforces them.",
             "Acme Inc. builds tools. It ships them.",
             "See vol. 2 for details. It continues.",
             "See pp. 2–4 for details. It continues.")],
         [["The U.S. Dept. sets rules.", "It enforces them."],
          ["Acme Inc. builds tools.", "It ships them."],
          ["See vol. 2 for details.", "It continues."],
          ["See pp. 2–4 for details.", "It continues."]]),
        ("lowercase no is an ordinary sentence ending",
         count_sentences("Answer yes or no. The result matters."), 2),
        ("a terminal one-letter label still ends a sentence",
         count_sentences("The procedure selects option A."), 1),
        ("a multi-dot abbreviation may end a sentence",
         count_sentences("A service used in the U.S. It runs online."), 2),
        ("sentence splitting recognizes an abbreviation boundary",
         split_sentences("A service used in the U.S. It runs online."),
         ["A service used in the U.S.", "It runs online."]),
        ("an abbreviation within a proper name is not a boundary",
         count_sentences("The U.S. Army maintains a service."), 1),
        ("an example abbreviation before lowercase prose is not a boundary",
         count_sentences("Use a model, e.g. linear regression."), 1),
        ("an honorific before an initial is not a boundary",
         split_sentences("Dr. A. Smith wrote a paper."),
         ["Dr. A. Smith wrote a paper."]),
        ("a single-letter label may end a sentence",
         count_sentences("A procedure selects option A. The next phase begins."),
         2),
        ("et al may end a sentence",
         count_sentences("Smith et al. It adds regularization."), 2),
        ("et al may end before a possessive-pronoun sentence",
         [count_sentences(value) for value in (
             "Smith et al. Their method differs.",
             "Smith et al. Its method differs.")], [2, 2]),
        ("a country abbreviation may end before a possessive pronoun",
         count_sentences("This follows U.S. Their method differs."), 2),
        ("clean card line passes",
         flashcard_line1_faults("A complete answer-key definition."), []),
        ("quoted clean card passes",
         flashcard_line1_faults('The term Hooke called "cells."'), []),
        ("lowercase and missing period are both reported",
         flashcard_line1_faults("an incomplete definition"),
         ["does not start with a capitalized word",
          "does not end with a period"]),
        ("Markdown link is rejected",
         flashcard_line1_markup("A [linked](target) definition."),
         ["Markdown link/image"]),
        ("Markdown reference link is rejected",
         flashcard_line1_markup("A [linked][target] definition."),
         ["Markdown reference link/image"]),
        ("Markdown reference definitions are rejected",
         [flashcard_line1_markup(value) for value in (
             "[Source]: https://example.com.",
             "[Source]:https://example.com.",
             "A [Source]: https://example.com.")],
         [["Markdown reference definition"]] * 3),
        ("underscore emphasis and strikethrough are rejected",
         flashcard_line1_markup("An _italic_ and ~~deleted~~ definition."),
         ["italic", "strikethrough"]),
        ("inline LaTeX remains allowed",
         flashcard_line1_markup(r"A quantity equal to $x^2$."), []),
        ("inline LaTeX may begin a card without becoming indentation",
         flashcard_line1_markup(r"$x$ is the measured quantity."), []),
        ("Markdown-like math operators remain inline LaTeX",
         flashcard_line1_markup(r"A product $x*y*z$ with $x_i<y_i$."), []),
        ("emphasis wrapped around inline LaTeX remains forbidden",
         flashcard_line1_markup(r"A **$x$** quantity."), ["bold"]),
        ("HTML is rejected",
         flashcard_line1_markup("A <span>styled</span> definition."),
         ["HTML"]),
        ("HTML comments are rejected",
         flashcard_line1_markup("A <!-- hidden --> definition."), ["HTML"]),
        ("Obsidian tags are rejected without confusing C hash",
         (flashcard_line1_markup("A #statistics concept."),
          flashcard_line1_markup("The language C# is used.")),
         (["Obsidian tag"], [])),
        ("Obsidian highlights are rejected",
         flashcard_line1_markup("A ==highlighted== definition."),
         ["highlight"]),
        ("Obsidian comments are rejected",
         [flashcard_line1_markup(value) for value in (
             "A %%hidden%% definition.",
             "A %%50% hidden%% definition.")],
         [["Obsidian comment"]] * 2),
        ("footnotes are rejected",
         flashcard_line1_markup("A footnote[^1] marker."), ["footnote"]),
        ("HTML entities are rejected",
         flashcard_line1_markup("A nonbreaking&nbsp;space."),
         ["HTML entity"]),
        ("display LaTeX is rejected on a card line",
         flashcard_line1_markup("A $$x=1$$ definition."), ["display LaTeX"]),
        ("block Markdown is rejected on a card line",
         [flashcard_line1_markup(value) for value in
          ("# A definition.", "> A definition.", "- A definition.")],
         [["block Markdown"]] * 3),
        ("an unmatched inline-LaTeX delimiter is rejected",
         flashcard_line1_markup("A quantity uses $x."),
         ["unmatched LaTeX delimiter"]),
        ("an escaped literal dollar is not an unmatched delimiter",
         flashcard_line1_markup(r"A price of \$5 is recorded."), []),
        ("Unicode dashes, slashes, and whitespace normalize alike",
         normalized_answer_surface("Bias/variance\u00a0trade–off"),
         "bias variance trade off"),
        ("punctuation-normalized answer leak is bounded",
         answer_surface_match(
             "The bias – variance trade off links two error sources.",
             "Bias/variance trade-off"), "bounded"),
        ("mathematical slash and minus lookalikes normalize as separators",
         [answer_surface_match(value, "bias/variance trade-off") for value in (
             "The bias\u2044variance trade off is described.",
             "The bias\u2215variance trade off is described.",
             "The bias\u2212variance trade off is described.")],
         ["bounded", "bounded", "bounded"]),
        ("math delimiters cannot hide an answer surface",
         [answer_surface_match(value, "k-nearest neighbors") for value in (
             "A $k$-nearest neighbors method.",
             r"A $\boldsymbol{k}$-nearest neighbors method.")],
         ["bounded", "bounded"]),
        ("semantic exponent spelling cannot hide an answer surface",
         answer_surface_match(
             "An $A^{*}$ search explores a graph.", "A-star search"),
         "bounded"),
        ("short answer remains boundary-sensitive",
         answer_surface_match("A region is divided.", "ion"), None),
        ("long answer remains boundary-sensitive",
         answer_surface_match("Covariance compares paired deviations.",
                              "variance"), None),
        ("symbol characters remain significant",
         normalized_answer_surface("C++"), "c++"),
        ("hash in a language name remains significant",
         normalized_answer_surface("C#"), "c#"),
        ("star in a language name remains significant",
         normalized_answer_surface("A*"), "a*"),
        ("a bare letter does not match inside a plus identifier",
         answer_surface_match("A language called C++ is used.", "C"), None),
        ("a bare letter does not match inside a hash identifier",
         answer_surface_match("A language called C# is used.", "C"), None),
        ("a bare letter does not match inside a star identifier",
         answer_surface_match("Pathfinding uses A*.", "A"), None),
        ("next-line review metadata is removed from the linting view",
         strip_flashcard_review_metadata(
             "A complete definition.\n??\nTerm\n<!--SR:state-->"),
         "A complete definition.\n??\nTerm\n"),
        ("same-line review metadata and a block ID are removed from the linting view",
         strip_flashcard_review_metadata(
             "A complete definition.\n??\nTerm <!--SR:state--> ^term-card"),
         "A complete definition.\n??\nTerm"),
        ("a next-line schedule preserves a line-3 block ID outside the linting view",
         strip_flashcard_review_metadata(
             "A complete definition.\n??\nTerm ^term-card\n<!--SR:state-->"),
         "A complete definition.\n??\nTerm\n"),
        ("the exact SR metadata callout is removed from the linting view",
         strip_flashcard_review_metadata(
             "A complete definition.\n??\nTerm\n"
             "> [!sr|card-metadata] \n>  <!--SR:state--> ^term-card"),
         "A complete definition.\n??\nTerm\n\n"),
        ("a blank detaches review metadata from the preceding card",
         strip_flashcard_review_metadata(
             "A complete definition.\n??\nTerm\n\n<!--SR:state-->"),
         "A complete definition.\n??\nTerm\n\n<!--SR:state-->"),
        ("an unterminated attached SR comment remains visible",
         strip_flashcard_review_metadata(
             "A complete definition.\n??\nTerm\n<!--SR:state"),
         "A complete definition.\n??\nTerm\n<!--SR:state"),
        ("ordinary line-four content closes the metadata attachment position",
         parse_flashcard_blocks(
             "A complete definition.\n??\nTerm\nVisible content\n"
             "<!--SR:detached-->"),
         [["A complete definition.", "??", "Term", "Visible content",
           "<!--SR:detached-->"]]),
        ("each blank-separated card keeps only its own contiguous metadata",
         parse_flashcard_blocks(
             "Definition one.\n??\nTerm one\n<!--SR:first-->\n\n"
             "Definition two.\n??\nTerm two\n"
             "> [!sr|card-metadata]\n> <!--SR:second--> ^second-card"),
         [["Definition one.", "??", "Term one"],
          ["Definition two.", "??", "Term two"]]),
        ("detached metadata cannot cross a blank or steal the next card",
         parse_flashcard_blocks(
             "Definition one.\n??\nTerm one\n\n"
             "> [!sr|card-metadata]\n> <!--SR:detached-->\n\n"
             "Definition two.\n??\nTerm two\n<!--SR:second-->"),
         [["Definition one.", "??", "Term one"],
          ["> [!sr|card-metadata]", "> <!--SR:detached-->"],
          ["Definition two.", "??", "Term two"]]),
        ("a leading HTML comment remains malformed card content",
         strip_flashcard_review_metadata(
             "<!--SR:misplaced-->\nA complete definition.\n??\nTerm"),
         "<!--SR:misplaced-->\nA complete definition.\n??\nTerm"),
        ("whitespace-only section padding does not become card content",
         parse_flashcard_blocks("\n   \nA complete definition.\n??\nTerm\n"),
         [["A complete definition.", "??", "Term"]]),
        ("ordinary joined card content remains visible after line three",
         parse_flashcard_blocks(
             "Definition one.\n??\nTerm one\nDefinition two.\n??\nTerm two"),
         [["Definition one.", "??", "Term one", "Definition two.",
           "??", "Term two"]]),
        ("an ordinary line-four HTML comment is malformed visible content",
         parse_flashcard_blocks(
             "A complete definition.\n??\nTerm\n<!--ordinary comment-->"),
         [["A complete definition.", "??", "Term",
           "<!--ordinary comment-->"]]),
        ("an unterminated ordinary line-four comment stays visible",
         parse_flashcard_blocks(
             "A complete definition.\n??\nTerm\n<!--ordinary comment"),
         [["A complete definition.", "??", "Term",
           "<!--ordinary comment"]]),
        ("an ordinary callout is not mistaken for SR-owned state",
         parse_flashcard_blocks(
             "A complete definition.\n??\nTerm\n"
             "> [!note]\n> Visible content"),
         [["A complete definition.", "??", "Term",
           "> [!note]", "> Visible content"]]),
        ("an SR callout with non-schedule body remains malformed visible content",
         parse_flashcard_blocks(
             "A complete definition.\n??\nTerm\n"
             "> [!sr|card-metadata]\n> Visible content"),
         [["A complete definition.", "??", "Term",
           "> [!sr|card-metadata]", "> Visible content"]]),
        ("content after an SR callout remains visible",
         parse_flashcard_blocks(
             "A complete definition.\n??\nTerm\n"
             "> [!sr|card-metadata]\n> <!--SR:state-->\n> Visible content"),
         [["A complete definition.", "??", "Term"],
          ["> Visible content"]]),
        ("metadata parsing never changes the source bytes",
         (lambda source: (
             parse_flashcard_blocks(source), source.encode("utf-8")))(
                 "A complete definition.\n??\n"
                 "Térm <!--SR:!2026-09-20,30,250--> ^term-card"),
         ([["A complete definition.", "??", "Térm"]],
          ("A complete definition.\n??\n"
           "Térm <!--SR:!2026-09-20,30,250--> ^term-card").encode("utf-8"))),
    ]
    for opening, closing in (("<!--", "-->"), ("%%", "%%")):
        hidden = opening + "\n## Flashcards\n```\n[[hidden]]\n" + closing
        source = "Visible before.\n" + hidden + "\nVisible after [[real]]."
        masked = mask_body_comments(source)
        helper_cases.append((
            "body comment is hidden without consuming following prose: " + opening,
            (len(masked), [i for i, c in enumerate(masked) if c == "\n"],
             "[[hidden]]" in masked, masked.endswith("Visible after [[real]].")),
            (len(source), [i for i, c in enumerate(source) if c == "\n"], False, True)))
        for code in ("`" + opening + "`", "``" + opening + "``",
                     "```text\n" + opening + "\n```",
                     "    " + opening):
            source = code + "\n\nVisible [[real]]."
            helper_cases.append((
                "a comment delimiter inside code cannot hide later prose: " + repr(code),
                mask_body_comments(source), source))
    source = "An unmatched ` tick.\n\n[[visible]]\n\nAnother ` tick."
    helper_cases.append((
        "unmatched inline ticks cannot hide later paragraphs",
        mask_body_comments(source, mask_code=True), source))
    source = "Wrapped `literal\n<!-- example` then [[visible]]."
    helper_cases.append((
        "soft-wrapped inline code keeps its literal comment delimiter",
        mask_body_comments(source), source))
    helper_cases.append((
        "soft-wrapped inline code hides only its own link examples",
        ("[[sample]]" in mask_body_comments(
            "Wrapped `[[sample]]\n<!-- example` then [[visible]].", mask_code=True),
         "[[visible]]" in mask_body_comments(source, mask_code=True)),
        (False, True)))
    helper_cases.append((
        "only an odd backslash run escapes wiki markup",
        ["[[target]]" in mask_escaped_wikilinks("\\" * n + "[[target]]")
         for n in range(5)],
        [True, False, True, False, True]))
    helper_cases.append((
        "escaping the embed prefix preserves the following live wikilink",
        mask_escaped_wikilinks(r"\![[target]]"), "\\ [[target]]"))
    for name, got, expected in helper_cases:
        ok = got == expected
        if verbose or not ok:
            print(("PASS" if ok else "FAIL") + ": " + name)
        if not ok:
            print("  expected %r, got %r" % (expected, got))
            failed += 1
    total = len(cases) + len(helper_cases)
    print("%d/%d self-test cases pass" % (total - failed, total))
    return failed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true", help="run self-tests")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    if not args.test:
        parser.error("no action requested; use --test")
    return 1 if run_self_test(args.verbose) else 0


if __name__ == "__main__":
    raise SystemExit(main())
