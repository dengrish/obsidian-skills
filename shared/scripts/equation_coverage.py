#!/usr/bin/env python3
"""Conservative candidates for defining math missing canonical display form.

Equation coverage is ultimately semantic: an agent must first decide whether
notation would clarify the concept. A candidate can remain prose-only when
a formula merely restates a simple verbal rule. If useful, verify the
relationship and its operands before typesetting. This helper supplies a
narrow deterministic floor for wording
that has already produced real omissions. It recognizes three families:
explicit square-root-of-variance definitions, defining equations left inline,
and a small set of prose calculations whose operands and operation are named.
It does not generate LaTeX and is not a general natural-language mathematics
parser.

Callers pass the entry's prose region only, after blanking fenced,
indented, and inline code. Frontmatter, Related footers, and Flashcards
remain outside this detector. Parsed table spans may be supplied
to exclude table cells; whole-line italic captions are excluded here.

A second, equally conservative floor lists well-definedness boilerplate:
conditions a formula already presupposes, such as "for a nonempty dataset",
count guards like ``m \\ge 1``, a sign range on a named strength or rate, and
probabilities that "sum to 1". The same finder reads one flashcard line 1 at a
time, where sums whose index bounds merely run over every term are listed too.
Ranges a definition needs (``p \\ge 1`` for an Lp norm, ``0 \\le \\lambda \\le
1``, ``r \\in [0,1]``) are outside its patterns, and every result remains an
agent-review candidate rather than an edit.

A third floor lists existing display lines that hold more than one equation,
such as ``a = ..., \\qquad b = ...``: every equation gets its own line. An
index range such as ``i = 1, \\ldots, m`` or ``x = 0, 1``, or a condition
such as ``\\text{for } i = 1`` qualifies an equation and is not a second one.

Displays are found by pairing unescaped ``$$`` delimiters in source order,
whatever their layout. A display that is not in canonical block form, or
that uses ``&`` or ``\\\\`` outside an environment, is a form finding: the
equation exists, so it is never reported as missing.

Stdlib only, Python 3.10+ (the plugin runtime floor).
"""

import argparse
import re

__all__ = [
    "find_boilerplate_candidates",
    "find_display_spans",
    "find_missing_display_equation_candidates",
    "find_multi_relation_display_candidates",
    "find_noncanonical_display_equation_candidates",
]


# An unescaped ``$$`` opens or closes a display. ``\\.`` consumes an escape,
# so ``\$$`` is a literal dollar followed by a lone ``$``.
_DISPLAY_DELIMITER_RE = re.compile(r"\\.|\$\$", re.DOTALL)
# Whitespace and blockquote markers may precede a canonical ``$$`` and may
# fill the blank line above or below it.
_LINE_PREFIX_RE = re.compile(r"[ \t]*(?:>[ \t]*)*")
_QUOTE_MARKER_RE = re.compile(r"(?m)^[ \t]*(?:>[ \t]?)+")
_INLINE_MATH_RE = re.compile(
    r"(?<![\\$])\$(?!\$)((?:\\.|[^$\n])+?)(?<!\\)\$(?!\$)")
_OBSIDIAN_LINK_RE = re.compile(r"(?<!!)\[\[([^\[\]\n]+)\]\]")
_CAPTION_RE = re.compile(r"^\s*\*(?!\*)\S(?:.*\S)?\*\s*$")
_ROOT_VARIANCE_RE = re.compile(
    r"\b(?:is(?:[ \t]+(?:defined[ \t]+as|equal[ \t]+to))?|equals)[ \t]+"
    r"(?:(?:generally|usually)[ \t]+)?(?:"
    r"(?:(?:the|a|an|this|that|its|their|his|her|our|your)[ \t]+)?"
    r"(?:(?:non[- ]?negative|positive|principal)[ \t]+)?"
    r"square[ \t]+root[ \t]+of[ \t]+"
    r"(?:(?:the|a|an|this|that|its|their|his|her|our|your)[ \t]+)?"
    r"(?:(?:(?:sample|population|weighted|corresponding|associated|"
    r"underlying|estimated|empirical)|"
    r"(?:[A-Za-z][A-Za-z-]*[ \t]+){0,2}[A-Za-z][A-Za-z-]*['’]s)"
    r"[ \t]+)?"
    r"variance|"
    r"(?:(?:the|a|an|this|that|its|their|his|her|our|your)[ \t]+)?"
    r"(?:(?:(?:sample|population|weighted|corresponding|associated|"
    r"underlying|estimated|empirical)|"
    r"(?:[A-Za-z][A-Za-z-]*[ \t]+){0,2}[A-Za-z][A-Za-z-]*['’]s)"
    r"[ \t]+)?"
    r"variance(?:['’]s)?[ \t]+"
    r"(?:(?:non[- ]?negative|positive|principal)[ \t]+)?"
    r"square[ \t]+root)\b",
    re.IGNORECASE,
)

# A defining inline formula needs both substantive math and a local linguistic
# cue. This deliberately excludes simple parameter/example assignments such as
# ``$k = 3$`` and ``$x_0 = 1$``; they are short expressions, not automatically
# a display equation. The cue window is bounded to the current sentence tail.
_INLINE_DEFINITION_CUE_RE = re.compile(
    r"(?:\b(?:defined|computed|calculated|expressed|written|represented|given)\s+"
    r"(?:as|by)\b|\b(?:similarity|prediction|probability|score|loss|cost|"
    r"metric|rate|boundary|function|quantity|value)\s+(?:is|equals)\b|"
    r"\b(?:defines?|computes?|calculates?|expresses?|writes?|represents?|"
    r"gives?)\s+(?:the\s+)?(?:similarity|prediction|probability|score|loss|"
    r"cost|metric|rate|boundary|function|quantity|value)\s+as\b|"
    r"\bstarts?\s+with\s+(?:a\s+)?(?:weight|"
    r"value)\b|\bpoints?\s+where\b|\b(?:single[- ]feature|one[- ]feature)\s+"
    r"case\b|\busual\s+construction\s+averages\b)",
    re.IGNORECASE,
)
_SIMPLE_NUMERIC_ASSIGNMENT_RE = re.compile(
    r"^\s*(?:[A-Za-z]|\\[A-Za-z]+)"
    r"(?:\s*[_^]\s*(?:\{[^{}\n]+\}|[A-Za-z0-9]+))*\s*=\s*"
    r"[+-]?(?:(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|"
    r"\d+(?:\.\d*)?\s*\^\s*(?:\{[+-]?\d+\}|[+-]?\d+)|"
    r"\d+(?:\.\d*)?\s*\\(?:times|cdot)\s*10\s*\^\s*"
    r"(?:\{[+-]?\d+\}|[+-]?\d+)|"
    r"\d+(?:\.\d*)?\s*/\s*\d+(?:\.\d*)?|"
    r"\\frac\s*(?:\{\s*[+-]?\d+(?:\.\d*)?\s*\}|[0-9])\s*"
    r"(?:\{\s*\d+(?:\.\d*)?\s*\}|[0-9])|"
    r"\d+(?:\.\d*)?\s*\\%|\\pi)\s*$")
_SIMPLE_NOTATIONAL_REFERENCE_RE = re.compile(
    r"^\s*(?:"
    r"[A-Za-z]|"
    r"\\operatorname\*?\s*\{[A-Za-z][A-Za-z0-9 -]*\}|"
    r"\\(?:hat|bar|tilde|vec|mathbf|mathrm|mathit|mathsf|mathbb|mathcal)"
    r"\s*\{(?:[A-Za-z0-9]|\\[A-Za-z]+)+\}|"
    r"\\(?!(?:argmax|argmin|exp|frac|lim|ln|log|max|min|operatorname|"
    r"prod|sqrt|sum|times|cdot|div)(?![A-Za-z]))[A-Za-z]+)"
    r"(?:\s*_\s*(?:\{(?:[^{}=<>]|\{[^{}]*\})+\}|[A-Za-z0-9]))*"
    r"(?:\s*\^\s*(?:\{\([^(){}=<>]+\)\}|\{[A-Za-z]\}|[A-Za-z]))?"
    r"\s*$")
_NEGATION_RE = re.compile(
    r"\b(?:not|never|neither|no\s+longer|cannot|without|"
    r"[A-Za-z]+n['’]t)\b",
    re.IGNORECASE,
)
_PREDICATE_BREAK_RE = re.compile(
    r"\b(?:but|however|whereas|although|though|yet|while|because)\b|"
    r"\band\s+(?=(?:the|a|an|this|that|it|its|their|his|her|our|your|"
    r"we|you|they|he|she)\b|(?:averag|comput|calculat|decompos|normaliz|"
    r"predict|assign|defin|express|represent|giv|writ)\w*\b)",
    re.IGNORECASE,
)
_CUE_BREAK_RE = re.compile(
    r"\b(?:but|however|whereas|although|though|yet|while|because)\b|"
    r"\b(?:for[ \t]+example|for[ \t]+instance)\b|\be\.g\.|"
    r"\band\s+(?=(?:the|a|an|this|that|it|its|their|his|her|our|your|"
    r"we|you|they|he|she)\b|(?:averag|comput|calculat|decompos|normaliz|"
    r"predict|assign|defin|express|represent|giv|writ)\w*\b)",
    re.IGNORECASE,
)
_AVOIDANCE_PREFIX_RE = re.compile(
    r"\b(?P<marker>instead[ \t]+of|rather[ \t]+than|"
    r"avoid(?:s|ed|ing)?|skip(?:s|ped|ping)?|omit(?:s|ted|ting)?)\b"
    r"(?P<object>[^.!?;:\n\x00]{0,64})$",
    re.IGNORECASE,
)
_REPLACEMENT_PREFIX_RE = re.compile(
    r"\breplac(?:e|es|ed|ing)\b([^.!?;:\n\x00]{0,96})$",
    re.IGNORECASE,
)
_FOLLOWING_REJECTION_RE = re.compile(
    r"^[ \t,]*(?:(?:is|are|was|were|be|been|being|gets?|got)[ \t,]+)"
    r"(?:(?:in[ \t]+general|usually|normally|typically)[ \t,]+)*"
    r"(?:not(?![ \t]+only)\b|never\b|no[ \t]+longer\b|"
    r"(?:isn|aren|wasn|weren|hasn|haven|hadn|doesn|don|didn|won|wouldn|"
    r"shouldn|couldn|can|mustn|needn)['’]t\b|"
    r"avoid(?:ed)?\b|replaced\b|omitted\b|skipped\b|unused\b|"
    r"inappropriate\b)",
    re.IGNORECASE,
)
_MARKDOWN_BLOCK_START_RE = re.compile(
    r"(?m)(?:^|\n)[ \t]{0,3}(?:#{1,6}[ \t]+|>[ \t]*|"
    r"[-+*][ \t]+|\d+[.)][ \t]+|`{3,}|~{3,}|---[ \t]*$)")
_MARKDOWN_BLOCK_LINE_RE = re.compile(
    r"^[ \t]{0,3}(?:#{1,6}[ \t]+|>[ \t]*|[-+*][ \t]+|"
    r"\d+[.)][ \t]+|`{3,}|~{3,}|---[ \t]*$)")

# Every pattern below is an observed, self-contained calculation shape. The
# result remains an agent-review candidate: context decides whether the phrase
# actually defines a named quantity and which symbols the note already binds.
_PROSE_CALCULATION_PATTERNS = [
    ("subtract-then-divide",
     re.compile(
         r"\bsubtract(?:s|ed|ing)?\b[^.!?;\n\x00]{0,100}\bmean\b"
         r"[^.!?;\n\x00]{0,100}\b(?:then|and)[ \t]+"
         r"divid(?:e|es|ed|ing)\b[^.!?;\n\x00]{0,100}"
         r"\bstandard[ \t]+deviation\b", re.IGNORECASE)),
    ("average-or-sum-of-predictions",
     re.compile(
         r"(?:\b(?:average|mean)[ \t]+of[ \t]+(?:the[ \t]+)?"
         r"predictions?\b|\bsum[ \t]+of\b[^.!?;\n\x00]{0,50}"
         r"\bpredictions?\b|\bpredicts?\b[^.!?;\n\x00]{0,80}"
         r"\bby[ \t]+summ(?:ing|ation)\b[^.!?;\n\x00]{0,60}"
         r"\bpredictions?\b)", re.IGNORECASE)),
    ("neighbor-value-average",
     re.compile(
         r"\baverage[ \t]+of[ \t]+(?:their|the)[ \t]+values?\b",
         re.IGNORECASE)),
    ("named-fraction-or-ratio",
     re.compile(
         r"\b(?:probability|rate|proportion|share|score|coefficient)\b"
         r"[^.!?;\n\x00]{0,100}\b(?:is|equals|represents)[ \t]+"
         r"(?:the[ \t]+)?"
         r"(?:fraction|ratio)\b", re.IGNORECASE)),
    ("normalize-by-total",
     re.compile(
         r"\bnormaliz(?:e|es|ed|ing)\b[^.!?;\n\x00]{0,100}\bby\b"
         r"[^.!?;\n\x00]{0,60}\b(?:row|column|class|grand)?[ \t]*total\b",
         re.IGNORECASE)),
    ("sum-decomposition",
     re.compile(
         r"\bdecompos(?:e|es|ed|ing|ition)\b[^.!?;\n\x00]{0,80}"
         r"\b(?:into|as)[ \t]+(?:the[ \t]+)?sum[ \t]+of\b",
         re.IGNORECASE)),
    ("nearest-center-assignment-and-update",
     re.compile(
         r"\bassign(?:s|ed|ing)?\b[^.!?;\n\x00]{0,100}"
         r"\b(?:points?|observations?|instances?)\b"
         r"[^.!?;\n\x00]{0,100}\bnearest\b[^.!?;\n\x00]{0,60}"
         r"\b(?:centers?|centroids?)\b[^.!?;\n\x00]{0,140}"
         r"\b(?:replac(?:e|es|ed|ing)|updat(?:e|es|ed|ing))\b"
         r"[^.!?;\n\x00]{0,100}\b(?:centers?|centroids?)\b"
         r"[^.!?;\n\x00]{0,120}\b(?:weighted[ \t]+)?(?:mean|average)\b"
         r"[^.!?;\n\x00]{0,80}\b(?:assigned[ \t]+(?:points?|"
         r"observations?|instances?)|(?:points?|observations?|instances?)"
         r"[ \t]+assigned)\b", re.IGNORECASE)),
]


def _line_number(text, offset):
    return text.count("\n", 0, offset) + 1


def _fold_hard_wraps(text):
    """Replace within-paragraph newlines with spaces without shifting offsets.

    Prose calculations may wrap across source lines. Paragraph breaks and new
    Markdown blocks remain newlines, so a pattern cannot borrow operands from
    an adjacent paragraph, list item, heading, quote, or fenced block.
    """
    chars = list(text)
    for match in re.finditer(r"\n", text):
        index = match.start()
        previous_start = text.rfind("\n", 0, index) + 1
        next_end = text.find("\n", index + 1)
        if next_end < 0:
            next_end = len(text)
        previous_line = text[previous_start:index]
        next_line = text[index + 1:next_end]
        if not previous_line.strip() or not next_line.strip():
            continue
        if _MARKDOWN_BLOCK_LINE_RE.match(next_line):
            continue
        if re.match(r"^[ \t]{0,3}(?:#{1,6}[ \t]+|`{3,}|~{3,}|"
                    r"---[ \t]*$)", previous_line):
            continue
        chars[index] = " "
    return "".join(chars)


def _excluded_lines(excluded_line_spans):
    """Zero-based line numbers inside inclusive ``(start, end)`` spans."""
    return {
        line
        for start, end in (excluded_line_spans or ())
        for line in range(max(0, start), max(0, end) + 1)
    }


def _displays(prose, excluded=frozenset()):
    """Pair the unescaped ``$$`` delimiters of ``prose`` in source order.

    Each display is ``(start, end, open_line, close_line, content)``: the
    offset of its opening ``$$`` and the offset just past its closing
    ``$$``, the zero-based lines of the two delimiters, and the math between
    them. A display opened after blockquote markers loses the markers of its
    continuation lines. A last unpaired ``$$`` opens no display, and a
    delimiter on an excluded line, such as a parsed table row, is skipped.

    Every form counts: a one-line or inline ``$$...$$`` still renders as
    display math and covers the calculation stated beside it. Its form is
    reported by :func:`find_noncanonical_display_equation_candidates`;
    treating it as absent produced the wrong repair (add another equation)
    instead of the safe one (put the existing delimiters on their own lines).
    """
    delimiters = []
    for match in _DISPLAY_DELIMITER_RE.finditer(prose):
        if match.group(0) != "$$":
            continue
        line = prose.count("\n", 0, match.start())
        if line not in excluded:
            delimiters.append((match.start(), line))
    displays = []
    for (start, open_line), (close, close_line) in zip(
            delimiters[0::2], delimiters[1::2]):
        content = prose[start + 2:close]
        prefix = prose[prose.rfind("\n", 0, start) + 1:start]
        if ">" in prefix and _LINE_PREFIX_RE.fullmatch(prefix):
            first, newline, rest = content.partition("\n")
            content = first + newline + _QUOTE_MARKER_RE.sub("", rest)
        displays.append((start, close + 2, open_line, close_line, content))
    return displays


def find_display_spans(prose, excluded_line_spans=()):
    """Return where each display of ``prose`` lies, paired as above.

    Each result gives the ``start`` offset of the opening ``$$``, the
    ``end`` offset just past the closing one, and the zero-based
    ``open_line`` and ``close_line`` of the two delimiters. A caller that
    masks display math uses it to agree with these finders: a ``$$`` that
    shares its line with math still opens or closes a display, and a last
    unpaired ``$$`` opens none.
    """
    return [
        {"start": start, "end": end,
         "open_line": open_line, "close_line": close_line}
        for start, end, open_line, close_line, _content in _displays(
            prose or "", _excluded_lines(excluded_line_spans))
    ]


def _display_form(prose, lines, display):
    """The delimiter-form defect of one display, or ``None`` when canonical.

    Canonical is each ``$$`` alone on its line, after nothing but whitespace
    or blockquote markers, with a blank line above and below.
    """
    start, end, open_line, close_line, _content = display
    close = end - 2
    line_end = prose.find("\n", end)
    before = prose[prose.rfind("\n", 0, start) + 1:start]
    after = prose[end:len(prose) if line_end < 0 else line_end]
    if not _LINE_PREFIX_RE.fullmatch(before) or after.strip():
        return "inline-display"
    if open_line == close_line:
        return "one-line-display"
    if (prose[start + 2:prose.find("\n", start)].strip()
            or not _LINE_PREFIX_RE.fullmatch(
                prose[prose.rfind("\n", 0, close) + 1:close])):
        return "shared-delimiter-line"
    above = lines[open_line - 1] if open_line else ""
    below = lines[close_line + 1] if close_line + 1 < len(lines) else ""
    if not (_LINE_PREFIX_RE.fullmatch(above)
            and _LINE_PREFIX_RE.fullmatch(below)):
        return "missing-blank-line"
    return None


_ALIGNMENT_TOKEN_RE = re.compile(r"\\(?:[A-Za-z]+|.)|[&{}]", re.DOTALL)


def _has_bare_alignment(content):
    """Whether ``&``, or ``\\\\`` outside a group, sits outside environments.

    Both belong inside an ``aligned``, ``gathered`` or similar environment;
    bare, they fail to render. ``\\&`` is a literal ampersand, a ``\\\\``
    inside a group such as ``\\substack{...}`` is that group's own, and a
    ``\\\\`` that ends the display starts no second row.
    """
    depth = environments = 0
    for match in _ALIGNMENT_TOKEN_RE.finditer(content):
        token = match.group(0)
        if token == r"\begin":
            environments += 1
        elif token == r"\end":
            environments = max(0, environments - 1)
        elif token == "{":
            depth += 1
        elif token == "}":
            depth = max(0, depth - 1)
        elif environments == 0 and (
                token == "&" or (token == "\\\\" and depth == 0
                                 and content[match.end():].strip())):
            return True
    return False


def find_noncanonical_display_equation_candidates(
        masked_prose, excluded_line_spans=()):
    """Return existing displays whose form is not canonical.

    Delimiter kinds: ``one-line-display`` (``$$...$$`` alone on one line),
    ``inline-display`` (prose shares a delimiter's line),
    ``shared-delimiter-line`` (the math shares a delimiter's line) and
    ``missing-blank-line`` (no blank line above or below). The kind
    ``bare-alignment`` is ``&`` or ``\\\\`` outside every environment
    (:func:`_has_bare_alignment`). A display with both defects gets one
    result for each.

    Callers pass the same code-masked prose and parsed table spans used by
    the coverage detector. Each result names the opening ``$$`` line, so the
    repair keeps the existing equation instead of adding a second one.
    """
    prose = masked_prose or ""
    lines = prose.split("\n")
    candidates = []
    for display in _displays(prose, _excluded_lines(excluded_line_spans)):
        content = display[4]
        if not content.strip():
            continue
        kinds = [_display_form(prose, lines, display)]
        if _has_bare_alignment(content):
            kinds.append("bare-alignment")
        for kind in kinds:
            if kind:
                candidates.append({
                    "kind": kind,
                    "phrase": " ".join(prose[display[0]:display[1]].split()),
                    "line": display[2] + 1,
                })
    return candidates


# Row environments lay a display out in lines; each row is checked alone.
_ROW_ENVIRONMENTS = frozenset((
    "aligned", "align", "alignat", "alignedat", "flalign", "gathered",
    "gather", "split", "multline", "eqnarray"))
# Their column pairs sit side by side on one line: ``a &= 0 & b &= 1``.
_COLUMN_PAIR_ENVIRONMENTS = frozenset((
    "aligned", "align", "alignat", "alignedat", "flalign"))
_ENVIRONMENT_ARGUMENT_RE = re.compile(
    r"\s*\{\s*([A-Za-z]+)\*?\s*\}(?:\s*\{\d+\})?")
_LATEX_TOKEN_RE = re.compile(r"\\(?:[A-Za-z]+|.)", re.DOTALL)
_ENVIRONMENT_NAME_RE = re.compile(r"\s*\{[^{}]*\}")
_DEFINING_RELATION_COMMANDS = frozenset(
    (r"\coloneqq", r"\triangleq", r"\equiv", r"\defeq"))
_RANGE_DOTS_COMMANDS = frozenset((r"\ldots", r"\dots", r"\cdots"))
# Top-level gaps and connectives that end one equation on a line. A bare
# ``\\`` outside a row layout starts no new line, so it joins two as well.
_SEGMENT_BREAK_COMMANDS = frozenset((
    r"\quad", r"\qquad", r"\enspace", r"\hspace", "\\\\",
    r"\Rightarrow", r"\Longrightarrow", r"\implies", r"\Leftarrow",
    r"\Longleftarrow", r"\impliedby", r"\iff", r"\Leftrightarrow",
    r"\Longleftrightarrow", r"\therefore"))
_HSPACE_ARGUMENT_RE = re.compile(r"\*?\s*\{[^{}]*\}")
_CLAUSE_COMMANDS = frozenset((r"\text", r"\textrm", r"\mathrm"))
# A where or with clause defines another quantity; and, so, hence, thus,
# therefore and i.e. join another equation.
_CLAUSE_WORD_RE = re.compile(
    r"\s*\{\s*,?\s*(?:where|with|and|so|hence|thus|therefore|i\.\s*e\.)"
    r"(?![A-Za-z])")
_CONJUNCTION_WORD_RE = re.compile(r"\s*\{\s*,?\s*and(?![A-Za-z])")
# A comma or semicolon separates two equations only when a relation follows
# before the next one; a list or an index range (i = 1, \ldots, m) has none.
_RELATION_AHEAD_RE = re.compile(
    r"(?:\\[,;:! ]|\\(?![,;:! ])|[^,;\\])*?(?:(?<![<>!=])=(?!=)|"
    r"\\(?:coloneqq|triangleq|equiv|defeq)(?![A-Za-z]))")
# A right side that only lists values (x = 0, 1 or i = 1, 2, 3) states an
# index range or a domain, like a list closed by \ldots.
_LIST_GAP = r"(?:\s|\\[,;:! ])*"
_LIST_VALUE = r"[-+]?\s*(?:\d+(?:\.\d+)?|[A-Za-z]|\\[A-Za-z]+)"
_VALUE_LIST_RE = re.compile(
    r"=%s%s(?:%s,%s%s)+%s[.,;]?%s" % (
        _LIST_GAP, _LIST_VALUE, _LIST_GAP, _LIST_GAP, _LIST_VALUE,
        _LIST_GAP, _LIST_GAP))
# A new physical source line continues the equation above it when that line
# ends in an operator, a relation, a comma or an opening group, or when the
# new line starts with an operator, a relation or a closing group.
_OPERATOR_COMMANDS = (
    r"cdot|times|div|pm|mp|ast|circ|oplus|otimes|cup|cap|setminus|wedge|"
    r"vee|land|lor|le|leq|ge|geq|ne|neq|lt|gt|ll|gg|approx|sim|simeq|cong|"
    r"equiv|propto|in|notin|subset|subseteq|supset|supseteq|to|mapsto|gets|"
    r"mid|coloneqq|triangleq|defeq")
_CONTINUED_LINE_END_RE = re.compile(
    r"(?:[-+*/=<>,;:|^_&({\[]|\\\{|\\(?:left|middle|[bB]igg?[lm]?|frac|"
    r"dfrac|tfrac|sqrt|sum|prod|int|%s)(?![A-Za-z]))\s*\Z" % _OPERATOR_COMMANDS)
_CONTINUING_LINE_START_RE = re.compile(
    r"\s*(?:[-+*/=<>,;:|^_&)}\]{]|\\\}|\\(?:right|middle|end|[bB]igg?[rm]?|"
    r"%s)(?![A-Za-z]))" % _OPERATOR_COMMANDS)
# A segment that states a condition on the equation beside it rather than a
# second equation: "\forall i", "\text{for } i = 1", "\text{subject to}".
# A "where" or "with" clause defines another quantity, so it is a second
# equation.
_QUALIFIER_LEAD_RE = re.compile(
    r"\s*(?:\\forall(?![A-Za-z])|\\(?:text|textrm|mathrm)\s*\{\s*"
    r"(?:for|if|when|given|subject\s+to|such\s+that|s\.\s*t\.)"
    r"(?![A-Za-z]))")
_LHS_NOISE_RE = re.compile(r"\\[,;:! ]|~|\s")


def _display_relation_segments(content):
    """Split one display line at the points where an equation can end.

    A segment ends at a top-level gap (``\\quad``, ``\\qquad``,
    ``\\enspace``, ``\\hspace`` or a ``\\\\`` outside a row layout), at a
    connective (``\\Rightarrow``, ``\\implies``, ``\\iff``,
    ``\\Leftrightarrow`` or a kin), at a ``\\text{}`` clause word (where,
    with, and, so, hence, thus, therefore, i.e.), at a comma or semicolon
    with a relation before the next one, and at a new physical source line
    that neither line continues with an operator, a relation or a group.

    Braces (literal ``\\{`` too), parentheses, brackets and
    ``\\begin``...``\\end`` environments nest. Returns ``(text, lhs,
    range_qualifier, continued)`` per segment: ``lhs`` is the text before
    the segment's first top-level ``=`` (or defining relation command), else
    ``None``; ``range_qualifier`` marks an index range: a top-level ``,
    \\ldots`` or a right side that only lists values (``x = 0, 1``);
    ``continued`` marks a segment opened by a comma, a semicolon or
    ``\\text{and}``, which carries on the condition before it.
    """
    segments = []
    start, depth, environments = 0, 0, 0
    lhs_end, range_qualifier, continued = None, False, False

    def close(end):
        text = content[start:end]
        lhs = text[:lhs_end - start] if lhs_end is not None else None
        listed = lhs is not None and bool(
            _VALUE_LIST_RE.fullmatch(text, lhs_end - start))
        segments.append((text, lhs, range_qualifier or listed, continued))

    index = 0
    while index < len(content):
        char = content[index]
        top = depth == 0 and environments == 0
        token = (_LATEX_TOKEN_RE.match(content, index) if char == "\\"
                 else None)
        if token:
            command = token.group(0)
            index = token.end()
            if command in (r"\begin", r"\end"):
                name = _ENVIRONMENT_NAME_RE.match(content, index)
                environments = max(0, environments + (
                    1 if command == r"\begin" else -1))
                index = name.end() if name else index
            elif command in (r"\{", r"\lbrace"):
                depth += 1
            elif command in (r"\}", r"\rbrace"):
                depth = max(0, depth - 1)
            elif top and (
                    command in _SEGMENT_BREAK_COMMANDS
                    or (command in _CLAUSE_COMMANDS
                        and _CLAUSE_WORD_RE.match(content, index))):
                if command == r"\hspace":
                    argument = _HSPACE_ARGUMENT_RE.match(content, index)
                    index = argument.end() if argument else index
                close(token.start())
                start, lhs_end, range_qualifier = index, None, False
                continued = bool(command in _CLAUSE_COMMANDS
                                 and _CONJUNCTION_WORD_RE.match(
                                     content, token.end()))
            elif top and command in _DEFINING_RELATION_COMMANDS:
                lhs_end = token.start() if lhs_end is None else lhs_end
            elif top and command in _RANGE_DOTS_COMMANDS:
                range_qualifier = range_qualifier or bool(re.search(
                    r",(?:\s|\\[,;:! ])*$", content[start:token.start()]))
            continue
        if char in "{([":
            depth += 1
        elif char in "})]":
            depth = max(0, depth - 1)
        elif (top and char in ",;"
              and _RELATION_AHEAD_RE.match(content, index + 1)):
            close(index)
            start, lhs_end, range_qualifier, continued = (
                index + 1, None, False, True)
        elif (top and char == "\n" and content[start:index].strip()
              and not _CONTINUED_LINE_END_RE.search(content[start:index])
              and not _CONTINUING_LINE_START_RE.match(content, index + 1)):
            close(index)
            start, lhs_end, range_qualifier, continued = (
                index + 1, None, False, False)
        elif (char == "=" and top and lhs_end is None
              and content[index - 1:index] not in ("<", ">", "!", "=")
              and content[index + 1:index + 2] != "="):
            lhs_end = index
        index += 1
    close(len(content))
    return segments


def _display_lines(content):
    """The rendered lines of one display: its rows, or the whole display.

    A row environment (``aligned``, ``gathered``, ``split``...) breaks its
    rows at each ``\\\\`` on its own level. Its markers and ``&`` column
    markers are dropped, and in an align-family layout every second ``&``
    of a row, which sets another column pair beside the first, becomes a
    ``\\quad`` gap. A ``\\\\`` outside every row environment, in a ``cases``
    or matrix body, or in a group such as ``\\substack`` starts no new line.
    """
    rows, row = [], []
    stack = []  # (row environment name or None, enclosing brace depth)
    depth = ampersands = index = 0

    def in_rows():
        return bool(stack) and depth == 0 and all(
            name and saved == 0 for name, saved in stack)

    while index < len(content):
        char = content[index]
        if char == "\\":
            token = _LATEX_TOKEN_RE.match(content, index)
            if token is None:
                # A lone trailing backslash starts no command.
                row.append(char)
                index += 1
                continue
            command = token.group(0)
            if command in (r"\begin", r"\end"):
                argument = _ENVIRONMENT_ARGUMENT_RE.match(content, token.end())
                name = argument.group(1) if argument else ""
                if command == r"\begin":
                    stack.append((name if name in _ROW_ENVIRONMENTS else None,
                                  depth))
                    depth = 0
                elif stack:
                    depth = stack.pop()[1]
                if name in _ROW_ENVIRONMENTS:
                    row.append(" ")
                    index, ampersands = argument.end(), 0
                    continue
            elif command == "\\\\" and in_rows():
                rows.append("".join(row))
                row, ampersands = [], 0
                index = token.end()
                continue
            row.append(command)
            index = token.end()
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
        elif char == "&" and (in_rows() or not stack):
            # A bare ``&`` outside every environment is a form finding.
            ampersands += 1
            pair = (in_rows() and stack[-1][0] in _COLUMN_PAIR_ENVIRONMENTS
                    and ampersands % 2 == 0)
            row.append(" \\quad " if pair else " ")
            index += 1
            continue
        row.append(char)
        index += 1
    rows.append("".join(row))
    return [row for row in rows if row.strip()]


def _equation_count(row):
    """How many equations one rendered display line sets side by side."""
    count, qualify_next, qualified = 0, False, False
    for text, lhs, range_qualifier, continued in _display_relation_segments(
            row):
        if not _LHS_NOISE_RE.sub("", text).strip(",;"):
            continue
        led = bool(_QUALIFIER_LEAD_RE.match(text))
        # A comma, a semicolon or "and" carries on the condition before it.
        qualified = (qualify_next or range_qualifier or led
                     or (continued and qualified))
        # A standalone condition ("\text{subject to}") states no equation
        # itself and qualifies the next segment.
        qualify_next = lhs is None and led
        side = _LHS_NOISE_RE.sub("", lhs or "").strip(",;")
        if side and not qualified:
            count += 1
    return count


def find_multi_relation_display_candidates(masked_prose,
                                           excluded_line_spans=()):
    """Return displays with a line that holds more than one equation.

    Every equation gets its own line: ``a = \\ldots, \\qquad b = \\ldots``
    in one display line puts two side by side, as do ``a = \\ldots, b =
    \\ldots``, ``a = \\ldots \\text{ and } b = \\ldots``, a derivation joined
    by ``\\Rightarrow`` and a ``\\text{where}`` clause defining another
    quantity. A line is the whole display, or each row of an ``aligned``,
    ``gathered`` or similar layout (:func:`_display_lines`); two equations
    on separate source lines of one display, or joined by a bare ``\\\\``,
    still share a rendered line. A line is split into equations only outside
    every group and environment (:func:`_display_relation_segments`), so a
    ``cases`` or matrix body never splits it. Conditions are not equations:
    an index range (``i = 1, \\ldots, m`` or ``x = 0, 1``), a segment led
    by ``\\forall`` or
    a ``\\text{for|if|when|given|subject to|...}`` word, the segment after a
    standalone condition such as ``\\text{subject to}``, and a comma,
    semicolon or ``\\text{and}`` that continues a condition. Every result is
    an agent-review candidate: the agent confirms each flagged line really
    holds two equations and gives each its own line, leaving the math
    unchanged. A result names the display's first content line.
    """
    prose = masked_prose or ""
    candidates = []
    for start, _end, open_line, close_line, content in _displays(
            prose, _excluded_lines(excluded_line_spans)):
        if not any(_equation_count(row) >= 2
                   for row in _display_lines(content)):
            continue
        line = open_line + 1
        if (open_line != close_line
                and not prose[start + 2:prose.find("\n", start)].strip()):
            line += 1
        candidates.append({
            "kind": "multi-relation-display",
            "phrase": " ".join(content.split()),
            "line": line,
        })
    return candidates


def _lhs_has_symbol(lhs, symbols):
    """Whether a display's left side contains one of the named symbols."""
    for symbol in symbols:
        if re.search(r"(?:^|[^a-z\\])%s(?=$|[^a-z])" % re.escape(symbol),
                     lhs):
            return True
    return False


def _prediction_result_is_named(compact):
    lhs = compact.split("=", 1)[0]
    return (any(marker in lhs for marker in
                (r"\hat", r"\bar{y", "pred", "forecast"))
            or _lhs_has_symbol(lhs, ("y", "h", "f")))


def _prediction_operands_are_named(compact):
    """Whether an aggregation's right side contains predicted values."""
    rhs = compact.split("=", 1)[1] if "=" in compact else compact
    return (any(marker in rhs for marker in
                (r"\hat", "pred", "forecast", "model", "estimator"))
            or bool(re.search(
                r"(?:^|[^a-z\\])(?:h|f)(?:[_({]|(?=$|[^a-z]))", rhs)))


def _display_has_average_operator(compact):
    """Distinguish a mean from a bare, unnormalised sum."""
    if "mean" in compact or "average" in compact:
        return True
    if "\\sum" not in compact:
        return False
    if "\\frac" in compact or "/" in compact:
        return True
    # Multiplication by an inverse count is another common mean spelling.
    return bool(re.search(
        r"(?:[a-z]|\\[a-z]+)(?:_\{?[^{}]+\}?)?\^\{?-1\}?"
        r"(?:\\cdot|\\times)?\\sum", compact))


def _latex_fraction_parts(value):
    """Yield top-level numerator/denominator groups from ``\\frac`` calls."""
    search_from = 0
    while True:
        start = value.find(r"\frac", search_from)
        if start < 0:
            return
        cursor = start + len(r"\frac")
        groups = []
        for _ in range(2):
            if cursor >= len(value) or value[cursor] != "{":
                break
            depth = 0
            group_start = cursor + 1
            for cursor in range(cursor, len(value)):
                if value[cursor] == "{":
                    depth += 1
                elif value[cursor] == "}":
                    depth -= 1
                    if depth == 0:
                        groups.append(value[group_start:cursor])
                        cursor += 1
                        break
            else:
                break
        if len(groups) == 2:
            yield groups[0], groups[1]
        search_from = start + len(r"\frac")


def _normalization_denominator_names_total(compact):
    """Require the total in the denominator, not elsewhere in a fraction."""
    rhs = compact.split("=", 1)[1] if "=" in compact else compact
    total_markers = (r"\sum", "total", "rowsum", "colsum")
    for _, denominator in _latex_fraction_parts(rhs):
        if any(marker in denominator for marker in total_markers):
            return True
    for slash in re.finditer(r"/", rhs):
        denominator = rhs[slash.end():]
        if any(marker in denominator for marker in total_markers):
            return True
    return False


def _probability_fraction_operands_are_named(compact, context):
    """Reject a probability-labelled result whose ratio has unrelated data."""
    if "probability" not in context.lower():
        return True
    rhs = compact.split("=", 1)[1] if "=" in compact else compact
    return (any(marker in rhs for marker in
                ("count", "freq", r"\sum", r"\mathbf{1}",
                 r"\mathbb{1}", r"\mathbbm{1}", "|c"))
            or bool(re.search(r"(?:^|[^a-z\\])[nm](?:[_({]|(?=$|[^a-z]))",
                              rhs)))


_GENERIC_SUBJECT_WORDS = {
    "a", "an", "each", "its", "measure", "one", "quantity", "result",
    "that", "the", "this", "value", "within",
}


def _lhs_matches_named_context(lhs, context, boundary_pattern):
    """Whether a display result is visibly tied to the prose subject.

    Open-ended notation must not mean that *any* letter-valued left-hand side
    covers a nearby definition.  Use the subject words before the defining
    operation as conservative evidence: their initials/acronym or an explicit
    name on the LHS is enough.  Closed-vocabulary symbols remain handled by
    each caller before this fallback.
    """
    boundary = re.search(boundary_pattern, context or "", re.IGNORECASE)
    if boundary is None:
        return False
    words = [word.lower() for word in re.findall(
        r"[A-Za-z][A-Za-z0-9]*", context[:boundary.start()])]
    words = [word for word in words[-6:] if word not in _GENERIC_SUBJECT_WORDS]
    if not words:
        return False
    markers = set(words)
    markers.update(word[:1] for word in words)
    if len(words) > 1:
        markers.add("".join(word[:1] for word in words))
    return _lhs_has_symbol(lhs, markers)


def _named_fraction_result_is_named(compact, context):
    """Match a prose quantity to the result named on a fraction's left side."""
    lhs = compact.split("=", 1)[0]
    words = context.lower()
    generic_lhs = bool(
        lhs and "=" in compact
        and _lhs_matches_named_context(
            lhs, context,
            r"\b(?:probability|rate|proportion|share|score|coefficient)\b"))
    if "probability" in words:
        return ("prob" in lhs or r"\pr" in lhs
                or _lhs_has_symbol(lhs, ("p",)) or generic_lhs)
    if "rate" in words:
        return (any(marker in lhs for marker in
                    ("rate", "tpr", "fpr", "fnr", "tnr", "precision",
                     "recall", "specificity", "sensitivity", "error"))
                or _lhs_has_symbol(lhs, ("r",)) or generic_lhs)
    if "proportion" in words or "share" in words:
        return ("prop" in lhs or "share" in lhs
                or _lhs_has_symbol(lhs, ("p", "q")) or generic_lhs)
    if "score" in words:
        return ("score" in lhs or "f_1" in lhs or "f1" in lhs
                or _lhs_has_symbol(lhs, ("s", "z")) or generic_lhs)
    if "coefficient" in words:
        return (any(marker in lhs for marker in
                    ("coef", r"\beta", r"\rho"))
                or _lhs_has_symbol(lhs, ("r", "c")) or generic_lhs)
    # Named ratios and scores use arbitrary conventional symbols (Jaccard's
    # ``J``, Dice's ``D``, and domain-specific abbreviations). Requiring a
    # closed list makes a correct nearby fraction a perpetual candidate.
    return generic_lhs


def _sum_components_are_named(compact, context):
    """Require named decomposition terms, not merely another plus sign."""
    expected = []
    words = context.lower()
    if "bias" in words:
        expected.append("bias" in compact)
    if "variance" in words:
        expected.append("var" in compact)
    if "noise" in words:
        expected.append(any(marker in compact for marker in
                            ("noise", r"\epsilon", r"\varepsilon",
                             r"\sigma")))
    if "loss" in words:
        expected.append(any(marker in compact for marker in
                            ("loss", r"\ell")))
    if "penalty" in words:
        expected.append(any(marker in compact for marker in
                            ("penalty", r"\lambda")))
    if expected:
        return all(expected)
    # A generic decomposition still has a determinate structural signature:
    # a named result and at least two symbolic additive terms. The prose
    # supplies their meaning; this floor need not know every domain vocabulary.
    if "=" not in compact:
        return False
    lhs, rhs = compact.split("=", 1)
    terms = [term for term in re.split(r"(?<!\\)\+", rhs) if term]
    return (_lhs_matches_named_context(
                lhs, context, r"\bdecompos(?:e|es|ed|ing|ition)\b")
            and len(terms) >= 2
            and all(re.search(r"[a-z]|\\[a-z]+", term) for term in terms))


def _plain_wikilinks(text):
    """Expose rendered wikilink labels while preserving source offsets."""
    def replace(match):
        payload = match.group(1)
        target, separator, label = payload.partition("|")
        visible = label if separator else target
        visible = visible.split("#", 1)[0].split("^", 1)[0]
        visible = visible.rsplit("/", 1)[-1].strip()
        if len(visible) > len(match.group(0)):
            visible = visible[:len(match.group(0))]
        return visible + " " * (len(match.group(0)) - len(visible))
    return _OBSIDIAN_LINK_RE.sub(replace, text or "")


def _balanced_group_end(value, start):
    """Return the offset after a balanced LaTeX grouping delimiter."""
    if start >= len(value) or value[start] not in "{([":
        return None
    pairs = {"{": "}", "(": ")", "[": "]"}
    stack = [pairs[value[start]]]
    cursor = start + 1
    while cursor < len(value):
        char = value[cursor]
        if char == "\\":
            # A command or escaped delimiter cannot close the current group.
            cursor += 2
            continue
        if char in pairs:
            stack.append(pairs[char])
        elif char == stack[-1]:
            stack.pop()
            if not stack:
                return cursor + 1
        cursor += 1
    return None


def _sqrt_operands(value):
    """Yield complete braced operands of LaTeX ``\\sqrt`` commands."""
    for match in re.finditer(r"\\sqrt(?![A-Za-z])", value or ""):
        cursor = match.end()
        if cursor < len(value) and value[cursor] == "[":
            optional_end = _balanced_group_end(value, cursor)
            if optional_end is None:
                continue
            cursor = optional_end
        if cursor >= len(value) or value[cursor] != "{":
            continue
        operand_end = _balanced_group_end(value, cursor)
        if operand_end is not None:
            yield value[cursor + 1:operand_end - 1]


def _strip_outer_grouping(value):
    """Remove complete outer grouping and sizing commands from an operand."""
    value = (value or "").replace(r"\left", "").replace(r"\right", "")
    while value and value[0] in "{([":
        end = _balanced_group_end(value, 0)
        if end != len(value):
            break
        value = value[1:-1]
    return value


_VARIANCE_OPERATOR_RE = re.compile(
    r"(?:\\operatorname\*?\{(?:variance|var)\}|"
    r"\\(?:mathrm|text)\{(?:variance|var)\}|(?:variance|var))")
_VARIANCE_SYMBOL_RE = re.compile(
    r"\\sigma(?:_\{?[^{}]+\}?)?\^(?:\{?2\}?)$")
_MEAN_MARKER_RE = re.compile(
    r"\\mu(?![A-Za-z])|\\bar\{|(?:mean|average)|"
    r"\\(?:mathbb|mathrm|operatorname)\*?\{e\}", re.IGNORECASE)


def _is_variance_operator_operand(value):
    """Whether a whole root operand is one variance call or variance symbol."""
    operand = _strip_outer_grouping(value)
    if _VARIANCE_SYMBOL_RE.fullmatch(operand):
        return True
    operator = _VARIANCE_OPERATOR_RE.match(operand)
    if operator is None or operator.end() >= len(operand):
        return False
    group_end = _balanced_group_end(operand, operator.end())
    return group_end == len(operand)


def _has_top_level_additive(value):
    """Whether an expression adds an unrelated term outside all groups."""
    pairs = {"{": "}", "(": ")", "[": "]"}
    stack = []
    cursor = 0
    while cursor < len(value):
        char = value[cursor]
        if char == "\\":
            cursor += 2
            continue
        if char in pairs:
            stack.append(pairs[char])
        elif stack and char == stack[-1]:
            stack.pop()
        elif not stack and char in "+-":
            return True
        cursor += 1
    return False


def _has_squared_deviation(value):
    """Whether an average operand contains ``(value - mean)^2``."""
    for start, char in enumerate(value):
        if char not in "([":
            continue
        end = _balanced_group_end(value, start)
        if end is None:
            continue
        cursor = end
        if value.startswith("^2", cursor):
            exponent_end = cursor + 2
        elif value.startswith("^{2}", cursor):
            exponent_end = cursor + 4
        else:
            continue
        if exponent_end > len(value):
            continue
        difference = value[start + 1:end - 1]
        if "-" in difference and _MEAN_MARKER_RE.search(difference):
            return True
    return False


def _is_expanded_variance_operand(value):
    """Whether a root operand is a canonical average squared deviation."""
    operand = _strip_outer_grouping(value)
    if not operand or _has_top_level_additive(operand):
        return False
    has_expectation = bool(re.search(
        r"\\(?:mathbb|mathrm|operatorname)\*?\{e\}", operand,
        re.IGNORECASE))
    has_average = (has_expectation
                   or "mean" in operand
                   or "average" in operand
                   or (r"\sum" in operand
                       and (r"\frac" in operand or "/" in operand)))
    return has_average and _has_squared_deviation(operand)


def _display_has_variance_square_root(compact):
    """Whether a display roots variance itself rather than unrelated terms."""
    return any(_is_variance_operator_operand(operand)
               or _is_expanded_variance_operand(operand)
               for operand in _sqrt_operands(compact))


def _display_supports(kind, block, context=""):
    """Whether a nearby display has the operators expected for ``kind``.

    Distance alone is not coverage: an unrelated equation beside a prose cue
    used to hide the missing defining display. These signatures remain broad
    enough to accept vault notation variants while requiring the operation
    that made the prose a candidate in the first place.
    """
    compact = re.sub(r"\s+", "", (block or "").lower())
    if kind == "square-root-of-variance":
        return _display_has_variance_square_root(compact)
    if kind == "subtract-then-divide":
        has_mean = any(marker in compact for marker in
                       (r"\mu", r"\bar", "mean"))
        has_scale = any(marker in compact for marker in
                        (r"\sigma", "std", "stdev"))
        return (("\\frac" in compact or "/" in compact)
                and "-" in compact and has_mean and has_scale)
    if kind in {"average-or-sum-of-predictions", "neighbor-value-average"}:
        context_words = context.lower()
        explicitly_summed = (kind == "average-or-sum-of-predictions"
                             and ("sum of" in context_words
                                  or "summing" in context_words
                                  or "summation" in context_words))
        has_operation = ("\\sum" in compact if explicitly_summed
                         else _display_has_average_operator(compact))
        if kind == "neighbor-value-average":
            rhs = compact.split("=", 1)[1] if "=" in compact else compact
            has_relevant_operand = bool(re.search(
                r"(?:^|[^a-z\\])y(?:[_({]|(?=$|[^a-z]))", rhs))
        else:
            has_relevant_operand = _prediction_operands_are_named(compact)
        return (has_operation and _prediction_result_is_named(compact)
                and has_relevant_operand)
    if kind == "named-fraction-or-ratio":
        return (("\\frac" in compact or "/" in compact)
                and _named_fraction_result_is_named(compact, context)
                and _probability_fraction_operands_are_named(compact, context))
    if kind == "normalize-by-total":
        return (("\\frac" in compact or "/" in compact)
                and _normalization_denominator_names_total(compact))
    if kind == "sum-decomposition":
        return "+" in compact and _sum_components_are_named(compact, context)
    if kind == "nearest-center-assignment-and-update":
        has_assignment = "argmin" in compact
        has_center = any(marker in compact for marker in
                         (r"\mu", "centroid", "center", "c_", "c{"))
        has_update = any(marker in compact for marker in
                         (r"\sum", "mean", "average"))
        return has_assignment and has_center and has_update
    return False


def _has_covering_display(kind, line_index, display_spans, lines, context=""):
    """Whether a matching display follows the prose nearby.

    ``display_spans`` holds ``(open_line, content)`` per display; one that
    opens on the cue's own line counts as following it.
    """
    nearby_blocks = []
    for start, content in display_spans:
        # At most one short paragraph may sit between, never a heading.
        if (0 <= start - line_index <= 6
                and not any(re.match(r"[ \t]{0,3}#{1,6}[ \t]", lines[i])
                            for i in range(line_index + 1, start))):
            if _display_supports(kind, content, context):
                return True
        if (kind == "nearest-center-assignment-and-update"
                and 0 <= start - line_index <= 8):
            nearby_blocks.append(content)
    if nearby_blocks and _display_supports(
            kind, "\n".join(nearby_blocks), context):
        return True
    return False


def _calculation_context(text, start, end, width=180):
    """Return the current clause around a prose-calculation match."""
    left = max(0, start - width)
    right = min(len(text), end + width)
    excerpt = text[left:right]
    relative_start = start - left
    relative_end = end - left
    before = excerpt[:relative_start]
    after = excerpt[relative_end:]
    left_boundary = max(before.rfind(mark) for mark in ".!?;\n\0")
    right_offsets = [after.find(mark) for mark in ".!?;\n\0"]
    right_offsets = [offset for offset in right_offsets if offset >= 0]
    right_boundary = min(right_offsets) if right_offsets else len(after)
    return excerpt[left_boundary + 1:relative_end + right_boundary]


def _sentence_tail(text, offset, width=220):
    start = max(0, offset - width)
    tail = text[start:offset]
    boundary = max(tail.rfind("."), tail.rfind("!"), tail.rfind("?"),
                   tail.rfind(";"), tail.rfind("\0"))
    for match in re.finditer(r"\n[ \t]*\n", tail):
        boundary = max(boundary, match.end() - 1)
    for match in _CUE_BREAK_RE.finditer(tail):
        boundary = max(boundary, match.end() - 1)
    for match in _MARKDOWN_BLOCK_START_RE.finditer(tail):
        # A match beginning on ``\n`` marks the next line as a new block. Keep
        # that block's own text while discarding a cue from the previous one.
        boundary = max(boundary, match.start())
    return tail[boundary + 1:]


def _predicate_is_negated(text, start, end):
    """Whether the candidate predicate, rather than an earlier clause, is negated."""
    prefix = text[:start]
    boundary = max(prefix.rfind(mark) for mark in ".!?;:,")
    for match in re.finditer(r"\n[ \t]*\n", prefix):
        boundary = max(boundary, match.end() - 1)
    local_prefix = text[boundary + 1:start]
    predicate_breaks = list(_PREDICATE_BREAK_RE.finditer(local_prefix))
    if predicate_breaks:
        local_prefix = local_prefix[predicate_breaks[-1].end():]
    avoidance_prefix = _AVOIDANCE_PREFIX_RE.search(local_prefix)
    avoided_operation = bool(
        avoidance_prefix
        and not re.search(r"\b(?:and|then)\b",
                          avoidance_prefix.group("object"), re.IGNORECASE))
    replacement_prefix = _REPLACEMENT_PREFIX_RE.search(local_prefix)
    # ``replace X with Y`` rejects X but affirms Y. A replacement verb before
    # the match therefore negates it only until its complement marker.
    replaced_operation = bool(
        replacement_prefix
        and not re.search(r"\b(?:with|by)\b", replacement_prefix.group(1),
                          re.IGNORECASE))
    immediate_prefix = local_prefix[-48:]
    predicate_start = text[start:min(end, start + 80)]
    local_predicate = immediate_prefix + " " + predicate_start
    # "Not only" is additive and affirmative. Mask just that construction so
    # a second, genuine negation in the same predicate remains detectable.
    local_predicate = re.sub(
        r"\bnot[ \t]+only\b", lambda match: " " * len(match.group(0)),
        local_predicate, flags=re.IGNORECASE)
    # Commas normally delimit clauses, but a parenthetical adverb can sit
    # inside one negated predicate: "not, in general, defined as ...".
    parenthetical_not = re.search(
        r"\bnot[ \t]*,(?:[^,.!?;:\n]{0,60},)?[ \t]*$",
        prefix[max(0, start - 100):start], re.IGNORECASE)
    suffix = text[end:min(len(text), end + 120)]
    suffix_boundary = len(suffix)
    for marker in ".!?;:\n\x00":
        offset = suffix.find(marker)
        if offset >= 0:
            suffix_boundary = min(suffix_boundary, offset)
    suffix = suffix[:suffix_boundary]
    suffix_break = _PREDICATE_BREAK_RE.search(suffix)
    if suffix_break:
        suffix = suffix[:suffix_break.start()]
    return bool(
        _NEGATION_RE.search(local_predicate) or parenthetical_not
        or re.search(r"\bno\s*$", immediate_prefix, re.IGNORECASE)
        or avoided_operation or replaced_operation
        or _FOLLOWING_REJECTION_RE.search(suffix))


# An asymptotic bound (``O(1/\epsilon)``, ``T(n) = \Theta(n^2)``) states a
# complexity, which the equation policy keeps inline; it is never a defining
# relation that needs its own display. Soft-O (``\tilde{O}``), little-o,
# sized parentheses (``O\big(n\big)``) and a relational bound
# (``R_T \le O(\sqrt{T})``, ``\le O(1/n)``) count too.
_ASYMPTOTIC_BOUND_RE = re.compile(
    r"^\s*(?:[^=<>$]*(?:=|\\in|\\sim|\\approx|\\leq?|\\geq?|<|>)\s*)?"
    r"(?:O|o|\\(?:mathcal|mathrm|operatorname|tilde|widetilde)\s*"
    r"(?:\{\s*O\s*\}|O)|\\Theta|\\Omega)"
    r"\s*(?:\\(?:left|[bB]igg?l?)\s*)?"
    r"\((?:[^()]|\([^()]*\))*\)\s*$")


def _inline_formula_is_substantive(formula):
    value = (formula or "").strip()
    if _SIMPLE_NUMERIC_ASSIGNMENT_RE.fullmatch(value):
        return False
    if _ASYMPTOTIC_BOUND_RE.fullmatch(value):
        return False
    if _SIMPLE_NOTATIONAL_REFERENCE_RE.fullmatch(value):
        return False
    if re.search(r"(?<![<>=!])=(?!=)", value):
        return True
    if re.search(
            r"\\(?:argmax|argmin|exp|frac|lim|ln|log|max|min|operatorname|"
            r"prod|sqrt|sum|times|cdot|div)(?![A-Za-z])", value):
        return True
    if "/" in value:
        return True
    return bool(re.search(
        r"(?<=[A-Za-z0-9})\]])[ \t]*[+\-*^][ \t]*"
        r"(?=[A-Za-z0-9\\({\[])", value))


def find_missing_display_equation_candidates(masked_prose,
                                             excluded_line_spans=()):
    """Return high-confidence prose calculations lacking display math.

    Each result has ``kind``, ``phrase``, and one-based ``line``. A prose cue is
    satisfied only by a matching display nearby, whatever its delimiter form
    (a noncanonical form is a separate form finding); an unrelated equation
    elsewhere in the entry does not hide it. A defining formula found inline
    is reported because its placement, rather than mere coverage, is the
    problem, unless it directly follows a wikilink, where it restates the
    linked entry's formula. The executing agent still verifies context before
    editing.
    """
    prose = masked_prose or ""
    displays = _displays(prose, _excluded_lines(excluded_line_spans))
    display_spans = [(open_line, content)
                     for _start, _end, open_line, _close, content in displays
                     if content.strip()]
    prose_lines = prose.split("\n")
    visible = _visible_prose_lines(prose, excluded_line_spans, displays)

    # Remove emphasis delimiters only from the prose/cue view. The raw inline
    # formula must remain byte-faithful: deleting ``_`` changed ``x_0`` into
    # ``x0`` before the simple-assignment exception could classify it.
    plain_visible_links = _plain_wikilinks(visible)
    plain_chars = list(plain_visible_links)
    protected = bytearray(len(visible))
    for math_match in _INLINE_MATH_RE.finditer(plain_visible_links):
        protected[math_match.start():math_match.end()] = \
            b"\x01" * (math_match.end() - math_match.start())
    for index, char in enumerate(plain_chars):
        if not protected[index] and char in "*_":
            plain_chars[index] = " "
    plain_visible = "".join(plain_chars)
    calculation_visible = _fold_hard_wraps(plain_visible)

    candidates = []

    for match in _INLINE_MATH_RE.finditer(visible):
        formula = match.group(1)
        if not _inline_formula_is_substantive(formula):
            continue
        # A formula directly after a wikilink restates the linked owner's
        # definition (review.md: a one-line restatement of a neighbor's
        # formula); it is not this entry's defining equation.
        if visible[:match.start()].rstrip().endswith("]]"):
            continue
        cue_tail = _sentence_tail(plain_visible, match.start())
        cue_matches = list(_INLINE_DEFINITION_CUE_RE.finditer(cue_tail))
        if not cue_matches:
            continue
        cue = cue_matches[-1]
        if len(cue_tail) - cue.end() > 96:
            continue
        if _predicate_is_negated(
                cue_tail, cue.start(), len(cue_tail)):
            continue
        candidates.append({
            "kind": "inline-defining-equation",
            "phrase": "$%s$" % " ".join(formula.split()),
            "line": _line_number(visible, match.start()),
        })

    for match in _ROOT_VARIANCE_RE.finditer(calculation_visible):
        line = _line_number(plain_visible, match.start())
        if _predicate_is_negated(
                calculation_visible, match.start(), match.end()):
            continue
        coverage_line = _line_number(
            plain_visible, max(match.start(), match.end() - 1))
        if _has_covering_display(
                "square-root-of-variance", coverage_line - 1, display_spans,
                prose_lines):
            continue
        candidates.append({
            "kind": "square-root-of-variance",
            "phrase": " ".join(match.group(0).split()),
            "line": line,
        })

    for kind, pattern in _PROSE_CALCULATION_PATTERNS:
        for match in pattern.finditer(calculation_visible):
            if _predicate_is_negated(
                    calculation_visible, match.start(), match.end()):
                continue
            line = _line_number(plain_visible, match.start())
            coverage_line = _line_number(
                plain_visible, max(match.start(), match.end() - 1))
            context = _calculation_context(
                calculation_visible, match.start(), match.end())
            if _has_covering_display(
                    kind, coverage_line - 1, display_spans, prose_lines,
                    context):
                continue
            candidates.append({
                "kind": kind,
                "phrase": " ".join(match.group(0).split()),
                "line": line,
            })

    # One paragraph can match two overlapping descriptions of the same
    # calculation. Keep the first stable candidate per kind/line/phrase, then
    # report in source order.
    unique = {}
    for candidate in candidates:
        key = (candidate["kind"], candidate["line"], candidate["phrase"].lower())
        unique.setdefault(key, candidate)
    candidates = list(unique.values())
    candidates.sort(key=lambda item: (item["line"], item["kind"], item["phrase"]))
    return candidates


# ---------------------------------------------------------------------------
# Well-definedness boilerplate (equations.md §1)
# ---------------------------------------------------------------------------

_GUARD_OPERATOR = r"(?:\\geq?|\\gt|≥|>)"
_SUBSCRIPT = r"(?:_\{(?:\\(?:text|mathrm)\{[^{}$]*\}|[^{}$]*)\}|_[A-Za-z0-9])"
#: A count guard on an instance, feature, class or token count:
#: ``m \ge 1``, ``N \ge 2``, ``m_{\text{node}} > 0``, ``m_a, m_b > 0``.
_COUNT_GUARD_RE = re.compile(
    r"(?<![\w\\])[mnNKT]" + _SUBSCRIPT + r"?"
    r"(?:\s*,\s*[mnNKT]" + _SUBSCRIPT + r"?)*"
    r"\s*" + _GUARD_OPERATOR + r"\s*[012](?![\d.])")
#: A one-sided sign range on a named strength, rate, tolerance or scale.
#: Two-sided ranges such as ``0 \le \lambda \le 1`` are never this shape.
_PARAMETER_SIGN_RE = re.compile(
    r"(?<![\w\\])\\(?:alpha|beta|gamma|delta|epsilon|varepsilon|eta|kappa|"
    r"lambda|mu|nu|rho|sigma|tau|omega)" + _SUBSCRIPT + r"?"
    r"\s*" + _GUARD_OPERATOR + r"\s*0(?![\d.])")
#: Nonnegative probabilities or a nonnegative variance.
_NONNEGATIVE_QUANTITY_RE = re.compile(
    r"(?:(?<![\w\\])p" + _SUBSCRIPT + r"?|\\operatorname\{Var\}\([^()$]*\))"
    r"\s*(?:\\geq?|≥)\s*0(?![\d.])")
#: A probability confined to the open unit interval so a log stays finite.
_OPEN_PROBABILITY_RE = re.compile(
    r"(?<![\d.])0\s*(?:<|\\lt)\s*(?:\\hat\{p\}|p)"
    r"(?:\^\{\([a-z]\)\}|" + _SUBSCRIPT + r")?"
    r"\s*(?:<|\\lt)\s*1(?![\d.])")
#: A sum stated equal to one inside a binding. It is matched after
#: ``_SCRIPT_GROUP_RE`` blanks sub/superscript groups, so the index bounds of
#: ``\sum_{i=1}^{m}`` never read as "= 1".
_SUM_TO_ONE_MATH_RE = re.compile(r"\\sum[^=$]*=\s*1(?![\d.])")
_SCRIPT_GROUP_RE = re.compile(r"[_^]\{[^{}]*\}|[_^][A-Za-z0-9]")
#: Card line 1: an index running over every term (``\sum_{i=1}^{m}``) or a
#: restricted sum that only skips undefined terms (``\sum_{k:p_k>0}``).
_FULL_RANGE_SUM_RE = re.compile(
    r"\\sum_\{?\s*([a-z])\s*=\s*1\s*\}?\^\{?\s*[A-Za-z]\s*\}?")
_RESTRICTED_SUM_RE = re.compile(r"\\sum_\{\s*[a-z]\s*:[^{}]*[<>][^{}]*\}")
#: Prose phrasings of the same guards, matched case-insensitively on the
#: link-label view of the text.
_BOILERPLATE_PHRASES = [
    ("nonempty-guard", re.compile(r"\bnon-?empty\b", re.IGNORECASE)),
    ("presence-guard", re.compile(
        r"\b(?:requires?|when)\s+at\s+least\s+one\b|"
        r"\bwhen\s+(?:actual\s+)?positives?\s+(?:is|are)\s+"
        r"(?:present|predicted)\b|\bmust\s+contain\s+both\b|"
        r"\bdefined\s+only\s+(?:when|if)\b", re.IGNORECASE)),
    ("nonzero-guard", re.compile(
        r"\bnon-?zero\s+(?:variation|variance|denominators?|"
        r"sums?\s+of\s+squared|feature[- ]weights?|weights?|"
        r"(?:sample|target)\s+variation)\b|"
        r"\b(?:weight\s+vector|weights?)\s+(?:is|are)\s+non-?zero\b|"
        r"\bnon-?constant\b", re.IGNORECASE)),
    ("finite-guard", re.compile(
        r"\b(?:has\s+)?finite[- ]variance\b|\bfinite\s+real\s+inputs?\b|"
        r"\bfinite\s+inputs\b|\bfinite\s+(?:outcome\s+)?probabilities\b",
        re.IGNORECASE)),
    ("parameter-sign", re.compile(
        r"\b(?:positive|non-?negative)\s+(?:integer\b|(?:learning\s+rate|"
        r"regularization\s+strength|standard\s+deviation|hyperparameter|"
        r"tolerance|step\s+size|penalty\s+strength)\b)|"
        r"\bnon-?negative\s+principal\b", re.IGNORECASE)),
    ("sum-to-one", re.compile(
        r"(?:\bnon-?negative\b|\\geq?\s*0|≥\s*0)[^.;:\n]{0,60}?"
        r"\bsum(?:s|ming)?\s+to\s+(?:1|one)\b", re.IGNORECASE)),
]
_MATH_GUARDS = [
    ("count-guard", _COUNT_GUARD_RE),
    ("parameter-sign", _PARAMETER_SIGN_RE),
    ("nonnegative-quantity", _NONNEGATIVE_QUANTITY_RE),
    ("open-probability", _OPEN_PROBABILITY_RE),
    ("sum-to-one", _SUM_TO_ONE_MATH_RE),
]
_PARAMETER_SUMMAND_RE = re.compile(r"\\(?:boldsymbol\{\\)?theta|\bw_")


def _visible_prose_lines(prose, excluded_line_spans=(), displays=None):
    """Prose with displays, captions and excluded lines blanked.

    A non-whitespace sentinel prevents a match from bridging across an
    excluded table, a caption or a display while preserving line offsets.
    Only a display's own characters, delimiters included, are blanked, so
    prose that shares a line with a display stays visible.
    """
    excluded = _excluded_lines(excluded_line_spans)
    if displays is None:
        displays = _displays(prose, excluded)
    chars = list(prose)
    for start, end, *_rest in displays:
        for index in range(start, end):
            if chars[index] != "\n":
                chars[index] = "\0"
    lines = []
    for index, (line, raw) in enumerate(
            zip("".join(chars).split("\n"), prose.split("\n"))):
        if index in excluded or _CAPTION_RE.match(raw):
            lines.append("\0" * len(line))
        else:
            lines.append(line)
    return "\n".join(lines)


def find_boilerplate_candidates(masked_prose, excluded_line_spans=(),
                                card_line=False):
    """Return well-definedness boilerplate candidates.

    ``masked_prose`` is code-masked body prose, or with ``card_line`` one
    flashcard line 1. Each result has ``kind``, ``phrase`` and one-based
    ``line``. Display blocks, captions and ``excluded_line_spans`` (parsed
    tables) are skipped: a condition inside a displayed equation belongs to
    the equation itself. On a card line, sums whose bounds only run over every
    term and restricted sums that skip undefined terms are listed as well,
    except a sum over parameters, whose start index can exclude a bias. The
    executing agent keeps any range the definition needs.
    """
    visible = _visible_prose_lines(masked_prose or "", excluded_line_spans)
    plain = _plain_wikilinks(visible)
    candidates = []
    for math_match in _INLINE_MATH_RE.finditer(visible):
        formula = math_match.group(1)
        line = _line_number(visible, math_match.start())
        for kind, pattern in _MATH_GUARDS:
            subject = (_SCRIPT_GROUP_RE.sub(" ", formula)
                       if pattern is _SUM_TO_ONE_MATH_RE else formula)
            for match in pattern.finditer(subject):
                candidates.append({"kind": kind,
                                   "phrase": " ".join(match.group(0).split()),
                                   "line": line})
        if not card_line:
            continue
        for match in _FULL_RANGE_SUM_RE.finditer(formula):
            summand = formula[match.end():match.end() + 60]
            summand = re.split(r"\\sum", summand, maxsplit=1)[0]
            if _PARAMETER_SUMMAND_RE.search(summand):
                continue
            candidates.append({"kind": "full-range-bounds",
                               "phrase": " ".join(match.group(0).split()),
                               "line": line})
        for match in _RESTRICTED_SUM_RE.finditer(formula):
            candidates.append({"kind": "restricted-sum",
                               "phrase": " ".join(match.group(0).split()),
                               "line": line})
    for kind, pattern in _BOILERPLATE_PHRASES:
        for match in pattern.finditer(plain):
            candidates.append({"kind": kind,
                               "phrase": " ".join(match.group(0).split()),
                               "line": _line_number(plain, match.start())})
    unique = {}
    for candidate in candidates:
        key = (candidate["line"], candidate["kind"],
               candidate["phrase"].lower())
        unique.setdefault(key, candidate)
    return sorted(unique.values(),
                  key=lambda item: (item["line"], item["kind"], item["phrase"]))


def run_self_test(verbose=False):
    cases = [
        ("pronoun definition",
         "It is the square root of the variance.", 1, ()),
        ("named definition with emphasis",
         "The **standard deviation** is the square root of variance.", 1, ()),
        ("a wikilink does not hide the variance cue",
         "The standard deviation is the square root of the [[variance]].",
         1, ()),
        ("defined-as spelling",
         "This quantity is defined as the square root of the variance.", 1, ()),
        ("is-equal-to spelling",
         "This quantity is equal to the square root of variance.", 1, ()),
        ("equals spelling",
         "The scale equals square root of variance.", 1, ()),
        ("an adjective square-root cue is reported",
         "Its scale is the positive square root of its variance.", 1, ()),
        ("an adjective variance noun phrase is reported",
         "The sample deviation is the square root of the sample variance.",
         1, ()),
        ("a noun-possessive variance phrase is reported",
         "The spread is the square root of the distribution's variance.",
         1, ()),
        ("a multiword possessive variance phrase is reported",
         "The spread is the square root of the random variable's variance.",
         1, ()),
        ("a possessive variance square-root cue is reported",
         "Its scale equals the variance's square root.", 1, ()),
        ("an attributive variance square-root cue is reported",
         "Its scale equals the variance square root.", 1, ()),
        ("hard-wrapped definition",
         "The scale is the square\nroot of the variance.", 1, ()),
        ("a root cue cannot bridge paragraphs",
         "The scale is the square root of\n\nvariance.", 0, ()),
        ("a root cue cannot bridge a Markdown block",
         "The scale is the square root of\n# Variance\nvariance.", 0, ()),
        ("inline symbols do not satisfy display coverage",
         "It is the square root of variance and is denoted $\\sigma$.", 1, ()),
        ("canonical display block satisfies the narrow floor",
         "It is the square root of variance.\n\n$$\n"
         "\\sigma = \\sqrt{\\operatorname{Var}(X)}\n$$", 0, ()),
        ("a variance-symbol display also covers the square-root cue",
         "It is the square root of variance.\n\n$$\n"
         "\\sigma = \\sqrt{\\sigma^2}\n$$", 0, ()),
        ("a spelled-out variance operator covers the square-root cue",
         "It is the square root of variance.\n\n$$\n"
         "s = \\sqrt{variance(X)}\n$$", 0, ()),
        ("an expanded population variance display covers the square-root cue",
         "It is the square root of variance.\n\n$$\n"
         "\\sigma = \\sqrt{\\frac{1}{N}"
         "\\sum_i (x_i - \\mu)^2}\n$$", 0, ()),
        ("an expectation of squared deviations covers the square-root cue",
         "It is the square root of variance.\n\n$$\n"
         "\\sigma = \\sqrt{\\mathbb{E}[(X - \\mu)^2]}\n$$", 0, ()),
        ("unrelated root and variance terms in one display do not cover the cue",
         "It is the square root of variance.\n\n$$\n"
         "f(x) = \\sqrt{x} + \\operatorname{Var}(Y)\n$$", 1, ()),
        ("variance added inside an unrelated root does not cover the cue",
         "It is the square root of variance.\n\n$$\n"
         "f(x) = \\sqrt{x + \\operatorname{Var}(Y)}\n$$", 1, ()),
        ("an expanded variance plus another radicand does not cover the cue",
         "It is the square root of variance.\n\n$$\n"
         "f = \\sqrt{x + \\frac{1}{N}"
         "\\sum_i (x_i - \\mu)^2}\n$$", 1, ()),
        ("whitespace-only blank lines give a display canonical adjacency",
         "It is the square root of variance.\n \t\n$$\n"
         "\\sigma = \\sqrt{\\operatorname{Var}(X)}\n$$\n \t\nNext.",
         0, ()),
        ("coverage distance is measured from a hard-wrapped cue's end",
         "It is the square\nroot of the\nvariance.\n\n$$\n"
         "\\sigma = \\sqrt{\\operatorname{Var}(X)}\n$$", 0, ()),
        ("a one-line display covers the stated calculation without pretending "
         "the equation is absent",
         "It is the square root of variance.\n\n"
         "$$\\sigma = \\sqrt{\\operatorname{Var}(X)}$$", 0, ()),
        ("an unclosed delimiter is not a display equation",
         "It is the square root of variance.\n\n$$\n\\sigma=1", 1, ()),
        ("an empty display block does not satisfy coverage",
         "It is the square root of variance.\n\n$$\n$$", 1, ()),
        ("a whitespace-only display block does not satisfy coverage",
         "It is the square root of variance.\n\n$$\n   \n$$", 1, ()),
        ("a display without a blank line before it still covers the cue",
         "It is the square root of variance.\n$$\n"
         "\\sigma = \\sqrt{\\operatorname{Var}(X)}\n$$", 0, ()),
        ("a display without a blank line after it still covers the cue",
         "It is the square root of variance.\n\n$$\n"
         "\\sigma = \\sqrt{\\operatorname{Var}(X)}\n$$\nNext.", 0, ()),
        ("a display opened on its equation's line still covers the cue",
         "It is the square root of variance.\n\n"
         "$$\\sigma = \\sqrt{\\operatorname{Var}(X)}\n$$", 0, ()),
        ("a display on the cue's own line covers the cue",
         "It is the square root of variance, "
         "$$\\sigma = \\sqrt{\\operatorname{Var}(X)}$$ in symbols.", 0, ()),
        ("prose sharing a line with an unrelated display stays visible",
         "$$x = 1$$ and the scale is the square root of variance.", 1, ()),
        ("negation is not an affirmative cue",
         "It is not the square root of variance.", 0, ()),
        ("possibility is not an affirmative cue",
         "It may be the square root of variance.", 0, ()),
        ("a negated root cue is not affirmative",
         "It never equals the square root of variance.", 0, ()),
        ("no-longer negation is not affirmative",
         "It no longer equals the square root of variance.", 0, ()),
        ("a qualitative mention remains semantic review",
         "The square root of variance is sometimes useful.", 0, ()),
        ("an underdetermined calculation gesture stays quiet",
         "It is computed with a correction factor.", 0, ()),
        ("an excluded table span stays quiet",
         "Claim | Value\n--- | ---\nIt is the square root of variance.\n"
         "*Values by measure.*", 0, ((0, 2),)),
        ("a whole-line caption stays quiet",
         "*It is the square root of variance.*", 0, ()),
        ("ordinary prose after an excluded table remains visible",
         "Claim | Value\n--- | ---\nx | y\n*Values by measure.*\n\n"
         "It is the square root of variance.", 1, ((0, 2),)),
        ("an unrelated display elsewhere does not suppress a prose cue",
         "$$\nx = 1\n$$\n\nAn unrelated result appears above.\n\n"
         "The scale is the square root of variance.", 1, ()),
        ("a defining equality left inline is reported",
         "The usual construction averages each loss over the data — "
         "$J(\\theta) = \\frac{1}{m} \\sum_i \\ell_i$.", 1, ()),
        ("a hard-wrapped inline definition cue is still visible",
         "For input $x$, the similarity is\n$\\exp(-\\gamma x^2)$.",
         1, ()),
        ("an arithmetic min-max expression left inline is reported",
         "The quantity is computed as "
         "$(x-x_{\\min})/(x_{\\max}-x_{\\min})$.", 1, ()),
        ("a direct rate cue reports an arithmetic fraction",
         "The rate is $TP/(TP+FP)$.", 1, ()),
        ("a direct loss cue reports an arithmetic expression",
         "The loss is $|y-\\hat{y}|$.", 1, ()),
        ("a direct cost cue reports a powered expression",
         "The cost equals $x^2$.", 1, ()),
        ("a direct metric cue reports an arithmetic expression",
         "The metric is $(y-\\hat{y})^2$.", 1, ()),
        ("a max operator with a subscript is substantive inline math",
         "The score is $\\max_i x_i$.", 1, ()),
        ("a logarithm operator is substantive inline math",
         "The value is $\\log p$.", 1, ()),
        ("a minimum subscript is a notational reference",
         "The minimum value is $x_{\\min}$.", 0, ()),
        ("a maximum subscript is a notational reference",
         "The maximum value is $x_{\\max}$.", 0, ()),
        ("a bare operator name is a notational reference",
         "The function is $\\operatorname{ReLU}$.", 0, ()),
        ("a minimum applied to operands remains substantive",
         "The value is $\\min_i x_i$.", 1, ()),
        ("an operator name applied to an argument remains substantive",
         "The value is $\\operatorname{Var}(X)$.", 1, ()),
        ("arithmetic inside a subscript remains a notational reference",
         "The next value is $x_{i+1}$.", 0, ()),
        ("arithmetic inside an iteration superscript is notation",
         "The updated value is $x^{(t+1)}$.", 0, ()),
        ("a decremented class subscript remains a notational reference",
         "The score is $p_{k-1}$.", 0, ()),
        ("a numeric power outside an index remains substantive",
         "The value is $x_i^2$.", 1, ()),
        ("a cue cannot cross into a new Markdown list item",
         "- The score is defined as a verbal ranking.\n"
         "- For example choose $x = y$.", 0, ()),
        ("a cue cannot cross a contrastive clause",
         "The score is high, but choose $x = y$ as an example.", 0, ()),
        ("a cue cannot cross a semicolon and example transition",
         "The score is defined verbally; for example, choose $x = y$.",
         0, ()),
        ("a distant direct cue cannot authorize a later formula",
         "Prediction is fast: a grown tree is roughly balanced, so a "
         "traversal visits logarithmically many nodes (the binary logarithm "
         "can also be written $\\log m / \\log 2$).", 0, ()),
        ("a cue may hard-wrap inside one Markdown list item",
         "- The score is defined as\n  $s = f(x)$.", 1, ()),
        ("a negated inline definition is not an equation candidate",
         "The value is not defined by $x = y$.", 0, ()),
        ("a contracted modal negates an inline definition",
         "The estimate shouldn't be defined as the average loss: $J = x$.",
         0, ()),
        ("a future contraction negates an inline definition",
         "The estimate won't be defined as $J = x$.", 0, ()),
        ("a perfect contraction negates an inline definition",
         "The estimate hasn't been defined as $J = x$.", 0, ()),
        ("a need contraction negates an inline definition",
         "The estimate needn't be defined as $J = x$.", 0, ()),
        ("parenthetical commas do not hide inline negation",
         "The estimate is not, in general, defined as $J = x$.", 0, ()),
        ("not-only wording remains affirmative",
         "The estimate is not only defined as $J = x$ but also tabulated.",
         1, ()),
        ("without negates a represented inline formula",
         "The quantity is represented as text without using $x = y$.",
         0, ()),
        ("an unrelated negation in an earlier clause does not hide a definition",
         "The input is not centered but the score is defined as $s = f(x)$.",
         1, ()),
        ("while separates an unrelated negation from a definition",
         "The input is not centered while the score is defined as $s = f(x)$.",
         1, ()),
        ("because separates an unrelated negation from a definition",
         "The input is not centered because the score is defined as $s = f(x)$.",
         1, ()),
        ("a possessive subject after and starts an affirmative predicate",
         "The input is not centered and its score is defined as $s = f(x)$.",
         1, ()),
        ("a plural possessive subject after and starts an affirmative predicate",
         "The inputs are not centered and their score is defined as $s = f(x)$.",
         1, ()),
        ("a defining expression without an equals sign is reported",
         "For input $x$ and center $c$, the similarity is "
         "$\\exp(-\\gamma (x-c)^2)$.", 1, ()),
        ("a boundary equality left inline is reported",
         "These are the points where the score is zero, "
         "$\\theta_0 + \\theta_1 x_1 = 0$.", 1, ()),
        ("an initialized weight formula left inline is reported",
         "Each instance starts with weight $w^{(i)} = 1/m$.", 1, ()),
        ("a simple example assignment stays inline",
         "For example, choose $k = 3$ neighbors.", 0, ()),
        ("a big-O bound after a definition cue stays inline",
         "When the learning rate is fixed, reaching the optimum can take "
         "$O(1/\\epsilon)$ iterations.", 0, ()),
        ("an assigned big-Theta bound stays inline",
         "The running time is $T(n) = \\Theta(n \\log n)$.", 0, ()),
        ("a calligraphic big-O bound stays inline",
         "The cost is $\\mathcal{O}(mn^2)$ per step.", 0, ()),
        ("soft-O, sized and unbraced bounds stay inline",
         "The regret rate is $R_T \\le \\tilde{O}(\\sqrt{T})$, and the cost "
         "is $\\mathcal O\\big(n/k\\big)$.", 0, ()),
        ("a bare relation to a bound stays inline",
         "The error rate is $\\le O(1/\\sqrt{T})$ after $T$ steps.", 0, ()),
        ("a little-o bound stays inline",
         "The error rate is $o(1/n)$ as the sample grows.", 0, ()),
        ("a rate formula next to a bound is still reported",
         "The rate is $r = (1 - \\eta)/m$.", 1, ()),
        ("a subscripted numeric value stays inline after a definition cue",
         "The initial value is $x_0 = 1$.", 0, ()),
        ("a Greek numeric value stays inline after a definition cue",
         "The initial value is $\\alpha = 0.1$.", 0, ()),
        ("a subscripted LaTeX symbol assignment stays inline",
         "The initial value is $\\theta_0 = 1$.", 0, ()),
        ("a decorated LaTeX symbol assignment stays inline",
         "The initial value is $\\theta_{0}^{(t)} = -0.5$.", 0, ()),
        ("a LaTeX power-of-ten value stays inline",
         "The initial value is $\\lambda = 10^{-3}$.", 0, ()),
        ("a rational numeric value stays inline after a definition cue",
         "The initial value is $r=1/2$.", 0, ()),
        ("a LaTeX-fraction numeric value stays inline after a definition cue",
         "The initial value is $r=\\frac{1}{2}$.", 0, ()),
        ("a percentage value stays inline after a definition cue",
         "The initial value is $r=50\\%$.", 0, ()),
        ("a pi value stays inline after a definition cue",
         "The initial value is $r=\\pi$.", 0, ()),
        ("an unbraced numeric power assignment stays inline",
         "The initial value is $x=10^3$.", 0, ()),
        ("a scientific-notation product assignment stays inline",
         "The initial value is $x=2\\times10^3$.", 0, ()),
        ("an unbraced LaTeX fraction assignment stays inline",
         "The initial value is $x=\\frac12$.", 0, ()),
        ("a variable exponent assignment remains substantive",
         "The value is $x=10^n$.", 1, ()),
        ("a variable scientific exponent remains substantive",
         "The value is $x=2\\times10^n$.", 1, ()),
        ("a variable LaTeX denominator remains substantive",
         "The value is $x=\\frac1n$.", 1, ()),
        ("an escaped currency dollar cannot swallow a later formula",
         r"The budget is \$5, and the score is $s = f(x)$.", 1, ()),
        ("a defining equality may contain an inequality on its right side",
         r"The cumulative function is $F(x) = P(X \le x)$.", 1, ()),
        ("a formula right after a wikilink restates the linked definition",
         r"The logit function is the inverse of the "
         r"[[logistic-function|logistic function]] "
         r"$\sigma(t) = 1/(1 + \exp(-t))$.", 0, ()),
        ("an unlinked defining formula after a cue is still reported",
         r"The loss function is $L = (y-\hat y)^2$ for one instance.", 1, ()),
        ("a one-sentence soft-voting rule is not a prose-calculation "
         "candidate",
         "It predicts from class probabilities averaged over all classifiers.",
         0, ()),
        ("an average-error comparison is not a defining calculation",
         "The average prediction error is lower on this dataset.", 0, ()),
        ("an on-average probability comparison is not a calculation",
         "The probability of error is lower on average for this model.", 0, ()),
        ("a one-sentence hard-voting rule is not a prose-calculation "
         "candidate",
         "Each member votes and the majority class wins.", 0, ()),
        ("a following negation rejects an unused prediction average",
         "The average of predictions is not used.", 0, ()),
        ("following not-only wording keeps prediction averaging affirmative",
         "The average of predictions is not only used but preferred.", 1, ()),
        ("a following judgment rejects inappropriate normalization",
         "Normalize by the row total is not appropriate.", 0, ()),
        ("rather-than wording rejects the alternative operation",
         "uses the median rather than the average of predictions", 0, ()),
        ("instead-of wording rejects averaged probabilities",
         "instead of averaging class probabilities", 0, ()),
        ("active replacement rejects the replaced prediction average",
         "replaces the average of predictions with the median", 0, ()),
        ("avoidance wording rejects averaged probabilities",
         "avoids averaging class probabilities", 0, ()),
        ("a coordinated one-sentence averaging rule is not a "
         "prose-calculation candidate",
         "The method avoids hard voting and averages class probabilities.",
         0, ()),
        ("omission in a coordinated predicate does not reject an equation",
         "The method omits missing values and computes the score as "
         "$s=f(x)$.", 1, ()),
        ("an average of neighbor values is a prose calculation candidate",
         "Regression returns the average of their values.", 1, ()),
        ("a one-sentence regression-averaging rule is not a "
         "prose-calculation candidate",
         "For classification aggregation is the mode; for regression it is "
         "the average.", 0, ()),
        ("a one-sentence leaf-mean rule is not a prose-calculation candidate",
         "For regression, each leaf predicts the mean target of the training "
         "instances that reach it.", 0, ()),
        ("a named fraction is a prose calculation candidate",
         "The class probability is the fraction of training instances in "
         "that class.", 1, ()),
        ("normalization by a row total is a prose calculation candidate",
         "Normalizing each cell by its row total yields an error rate.", 1, ()),
        ("a hard-wrapped normalization remains a candidate",
         "Normalizing each cell by the\nrow total yields an error rate.",
         1, ()),
        ("normalization cannot borrow a total from the next paragraph",
         "Normalizing each cell by the\n\nrow total yields an error rate.",
         0, ()),
        ("negated normalization is not a prose calculation candidate",
         "The table does not normalize each cell by its row total.", 0, ()),
        ("without negates normalization by a total",
         "Normalize the matrix without dividing by its row total.", 0, ()),
        ("without negates averaged probabilities",
         "The method is computed without averaging class probabilities.",
         0, ()),
        ("a stated sum decomposition is a prose calculation candidate",
         "The error decomposes into the sum of bias, variance, and noise.",
         1, ()),
        ("a hard-wrapped sum decomposition remains a candidate",
         "The error decomposes into the\nsum of bias, variance, and noise.",
         1, ()),
        ("a decomposition cannot bridge a paragraph",
         "The error decomposes into the\n\nsum of bias, variance, and noise.",
         0, ()),
        ("subtracting and dividing can hard-wrap",
         "Standardization subtracts the mean, then\ndivides by the standard "
         "deviation.", 1, ()),
        ("subtracting and dividing cannot bridge a list item",
         "- Standardization subtracts the mean.\n"
         "- Then it divides by the standard deviation.", 0, ()),
        ("an adjacent display satisfies a prose calculation cue",
         "The class probability is the fraction of class-k instances in a "
         "leaf.\n\n$$\np_k = m_k / m\n$$", 0, ()),
        ("a display after one plain-words paragraph covers the opener",
         "The **false positive rate** (FPR) is the fraction of actual "
         "negative instances that a classifier wrongly predicts as "
         "positive.\n\nEvery actual negative is either a false positive or "
         "a true negative.\n\n$$\n\\text{FPR} = \\frac{\\text{FP}}"
         "{\\text{FP} + \\text{TN}}\n$$\n", 0, ()),
        ("a display under a later heading does not cover the opener",
         "The **false positive rate** (FPR) is the fraction of actual "
         "negative instances that a classifier wrongly predicts as "
         "positive.\n\n## Formula\n\n$$\n\\text{FPR} = \\frac{\\text{FP}}"
         "{\\text{FP} + \\text{TN}}\n$$\n", 1, ()),
        ("an adjacent unrelated display does not satisfy the prose cue",
         "The class probability is the fraction of class-k instances in a "
         "leaf.\n\n$$\nx = 1\n$$", 1, ()),
        ("a same-operator standardization display does not cover probability",
         "The class probability is the fraction of class-k instances in a "
         "leaf.\n\n$$\nz = \\frac{x - \\mu}{\\sigma}\n$$", 1, ()),
        ("a linear sum does not cover an error decomposition",
         "The error decomposes into the sum of bias, variance, and noise."
         "\n\n$$\ny = a + bx\n$$", 1, ()),
        ("a matching error decomposition display supplies semantic operands",
         "The error decomposes into the sum of bias, variance, and noise."
         "\n\n$$\nE = \\operatorname{Bias}^2 + "
         "\\operatorname{Var} + \\sigma_\\epsilon^2\n$$", 0, ()),
        ("a generic named decomposition is covered without a fixed vocabulary",
         "The error decomposes into the sum of approximation and estimation error."
         "\n\n$$\nE = A + B\n$$", 0, ()),
        ("an unrelated arbitrary sum does not cover a named decomposition",
         "The error decomposes into the sum of approximation and estimation error."
         "\n\n$$\nx = A + B\n$$", 1, ()),
        ("an incomplete decomposition display does not supply every operand",
         "The error decomposes into the sum of bias, variance, and noise."
         "\n\n$$\nE = \\operatorname{Bias}^2 + "
         "\\operatorname{Var}\n$$", 1, ()),
        ("a standardization fraction does not cover averaged predictions",
         "The output is the average of the predictions.\n\n$$\n"
         "z = \\frac{x - \\mu}{\\sigma}\n$$", 1, ()),
        ("a bare sum does not cover an average of predictions",
         "The output is the average of the predictions.\n\n$$\n"
         "\\hat y=\\sum_j\\hat y_j\n$$", 1, ()),
        ("a bare sum of unrelated values does not cover prediction averaging",
         "The output is the average of the predictions.\n\n$$\n"
         "y = \\sum_i x_i\n$$", 1, ()),
        ("a matching prediction average display names its result",
         "The output is the average of the predictions.\n\n$$\n"
         "\\hat{y}(x) = \\frac{1}{M} \\sum_m \\hat{y}_m(x)\n$$",
         0, ()),
        ("a regression leaf display averages its target values",
         "For regression, a leaf $\\ell$ containing $m_\\ell$ instances "
         "with targets $y^{(i)}$ predicts their mean:\n\n$$\n"
         "\\hat{y}_\\ell = \\frac{1}{m_\\ell} "
         "\\sum_{i \\in \\ell} y^{(i)}\n$$", 0, ()),
        ("an unrelated fraction does not cover normalization by a total",
         "Normalize each cell by its row total.\n\n$$\n"
         "z = \\frac{x - \\mu}{\\sigma}\n$$", 1, ()),
        ("a row-sum fraction covers normalization by a total",
         "Normalize each cell by its row total.\n\n$$\n"
         "p_{ij} = \\frac{c_{ij}}{\\sum_j c_{ij}}\n$$", 0, ()),
        ("a sum in the numerator does not cover row-total normalization",
         "Normalize each cell by its row total.\n\n$$\n"
         "z = \\frac{\\sum_i x_i}{\\sigma}\n$$", 1, ()),
        ("a probability-labelled unrelated ratio does not cover its fraction",
         "The class probability is the fraction of class-k instances in a "
         "leaf.\n\n$$\np_k = x_k/z\n$$", 1, ()),
        ("a score may use a domain-specific result symbol",
         "The Jaccard score is the ratio of intersection to union.\n\n$$\n"
         "J = |A \\cap B| / |A \\cup B|\n$$", 0, ()),
        ("an unrelated arbitrary fraction does not cover a named score",
         "The Jaccard score is the ratio of intersection to union.\n\n$$\n"
         "x = |A \\cap B| / |A \\cup B|\n$$", 1, ()),
        ("nearest-center assignment plus a mean update is a candidate",
         "The algorithm assigns each point to its nearest center, then "
         "updates each center to the mean of its assigned points.", 1, ()),
        ("a weighted nearest-center update is a candidate",
         "It assigns each point to the nearest centroid and replaces each "
         "centroid with the weighted average of points assigned to it.",
         1, ()),
        ("the corpus instance wording remains a candidate",
         "Training alternates between assigning each instance to its nearest "
         "center and replacing each center with the mean of its assigned "
         "instances, or their weighted mean when weights are present.",
         1, ()),
        ("nearest-center assignment alone stays below the candidate floor",
         "The algorithm assigns each point to its nearest center.", 0, ()),
        ("a center mean update alone stays below the candidate floor",
         "The algorithm updates each center to the mean of assigned points.",
         0, ()),
        ("two matching k-means displays cover the two prose operations",
         "The algorithm assigns each point to its nearest center, then "
         "updates each center to the mean of its assigned points.\n\n"
         "$$\nz_i = \\operatorname*{argmin}_k "
         "\\lVert x_i - \\mu_k \\rVert^2\n$$\n\n"
         "$$\n\\mu_k = \\frac{1}{|C_k|} \\sum_{i \\in C_k} x_i\n$$",
         0, ()),
        ("a preceding display does not satisfy a later prose definition",
         "$$\n\\sigma = \\sqrt{\\operatorname{Var}(X)}\n$$\n"
         "The scale is the square root of variance.", 1, ()),
    ]
    failed = 0
    total = len(cases)
    for name, prose, expected, spans in cases:
        got = len(find_missing_display_equation_candidates(prose, spans))
        ok = got == expected
        if verbose or not ok:
            print(("PASS" if ok else "FAIL") + ": " + name)
        if not ok:
            print("  expected %r, got %r" % (expected, got))
            failed += 1
    # Display form: (name, prose, kinds in source order, spans).
    format_cases = [
        ("a one-line display is reported as existing noncanonical math",
         "Prose.\n\n$$x = 1$$", ["one-line-display"], ()),
        ("a canonical multiline display has no form finding",
         "Prose.\n\n$$\nx = 1\n$$", [], ()),
        ("a one-line display in a parsed table is outside body prose",
         "Name | Value\n--- | ---\nX | $$x = 1$$", [], ((0, 2),)),
        ("an opening or closing delimiter sharing the math's line is reported",
         "Prose.\n\n$$x = 1\n$$\n\nMore.\n\n$$\ny = 2$$",
         ["shared-delimiter-line", "shared-delimiter-line"], ()),
        ("a display sharing a line with prose is reported",
         "That is $$x = 1$$ in symbols.", ["inline-display"], ()),
        ("a display without a blank line above or below is reported",
         "Prose.\n$$\nx = 1\n$$\n\nMore.\n\n$$\ny = 2\n$$\nNext.",
         ["missing-blank-line", "missing-blank-line"], ()),
        ("whitespace-only blank lines and a blockquote display are canonical",
         "Prose.\n \t\n$$\nx = 1\n$$\n \t\n> Quote.\n>\n> $$\n> y = 2\n> $$",
         [], ()),
        ("an escaped dollar opens no display",
         "It costs \\$$5$ in total.", [], ()),
        ("a one-line aligned display is one form finding",
         "Prose.\n\n$$\\begin{aligned} a &= 1 \\\\ &= 2 \\end{aligned}$$",
         ["one-line-display"], ()),
        ("a bare & or \\\\ outside an environment fails to render",
         "$$\na &= b \\\\ &= c\n$$\n\n$$\na = 1 \\\\ b = 2\n$$",
         ["bare-alignment", "bare-alignment"], ()),
        ("aligned rows, a cases body, an escaped &, a substack and a final "
         "\\\\ render",
         "$$\n\\begin{aligned} a &= b \\\\ &= c \\end{aligned}\n$$\n\n"
         "$$\ns = \\begin{cases} 1 & x > 0 \\\\ 0 & x \\le 0 \\end{cases}\n"
         "$$\n\n$$\nc = \\text{R\\&D}\n$$\n\n"
         "$$\nr = \\sum_{\\substack{i=1 \\\\ j \\ne i}} w_i\n$$\n\n"
         "$$\na = 1 \\\\\n$$", [], ()),
    ]
    total += len(format_cases)
    for name, prose, expected, spans in format_cases:
        got = [candidate["kind"] for candidate in
               find_noncanonical_display_equation_candidates(prose, spans)]
        ok = got == expected
        if verbose or not ok:
            print(("PASS" if ok else "FAIL") + ": " + name)
        if not ok:
            print("  expected %r, got %r" % (expected, got))
            failed += 1
    # Two relations in one display: (name, prose, candidate lines, spans).
    split_cases = [
        ("two defining relations beside \\qquad are reported",
         "Prose.\n\n$$\n\\text{MSE} = \\frac{1}{m} \\sum_{i} (\\hat{y} - y_i)^2,"
         " \\qquad \\hat{y} = \\frac{1}{m} \\sum_{i} y_i\n$$", [4], ()),
        ("a relation beside a cases definition is still reported",
         "$$\ng(\\theta) = \\nabla f + 2\\alpha \\begin{pmatrix} 0 \\\\ s "
         "\\end{pmatrix}, \\qquad s = \\begin{cases} -1 & x < 0 \\\\ "
         "+1 & x > 0 \\end{cases}\n$$", [2], ()),
        ("a one-line display and a ,\\; gap are read too",
         "$$a = 1,\\; b = 2$$", [1], ()),
        ("an index range qualifies rather than adds a relation",
         "$$\nw^{(i)} = \\frac{1}{m}, \\qquad i = 1, \\ldots, m\n$$", [], ()),
        ("a thin-spaced index range after a gap adds no equation",
         "$$\ny_i = w x_i, \\quad i = 1,\\, \\ldots,\\, m\n$$", [], ()),
        ("a control-spaced index range adds no equation",
         "$$\ny_i = w x_i,\\ i = 1,\\ \\ldots,\\ m\n$$", [], ()),
        ("an elided vector is not an index range",
         "$$\nx = (x_1, \\ldots, x_n), \\quad y = (y_1, \\ldots, y_n)\n$$",
         [2], ()),
        ("forall, for and subject-to qualifiers are exempt",
         "$$\nf(x) = 0, \\quad \\forall x = 1\n$$\n\n"
         "$$\ny_i = w x_i, \\qquad \\text{for } i = 1\n$$\n\n"
         "$$\n\\max f(w) = 1 \\quad \\text{subject to} \\quad g(w) = 0\n$$",
         [], ()),
        ("a derivation joined by a connective is two equations on a line",
         "$$\nf(x) = 0 \\quad \\Rightarrow \\quad x = 1\n$$\n\n"
         "$$\na = 1 \\Rightarrow \\quad b = 2\n$$\n\n"
         "$$\na = 1, \\quad \\text{hence } b = 2\n$$", [2, 6, 10], ()),
        ("a where or with clause defines a second equation",
         "$$\ny = m x + b, \\quad \\text{where } m = 2\n$$\n\n"
         "$$\ny = m x, \\quad \\text{with } m = 2\n$$", [2, 6], ()),
        ("a derivation joined by a bare connective is two equations",
         "$$\na = t \\Rightarrow p = \\sigma(t)\n$$\n\n"
         "$$\na = t \\implies p = \\sigma(t)\n$$", [2, 6], ()),
        ("a bare where or with clause defines a second equation",
         "$$\na = \\log(o), \\text{ where } o = p/(1-p)\n$$\n\n"
         "$$\na = \\log(o) \\text{ with } o = p/(1-p)\n$$", [2, 6], ()),
        ("a comma before a control space separates two equations",
         "$$\na = b,\\ c = d\n$$", [2], ()),
        ("a connective condition, a thin-space range and a with-phrase "
         "add no equation",
         "$$\nx = 1 \\Rightarrow y > 0\n$$\n\n"
         "$$\ny_i = w x_i,\\, i = 1, \\ldots, m\n$$\n\n"
         "$$\np = 0.5 \\text{ with probability } q\n$$", [], ()),
        ("side-by-side relations and a repeated side are reported",
         "$$\nx = 1, \\quad y = 2\n$$\n\n"
         "$$\na = 1 \\quad \\text{and} \\quad b = 2\n$$\n\n"
         "$$\na = 1, \\quad a = 2\n$$", [2, 6, 10], ()),
        ("gaps inside a group, environment or text never split",
         "$$\nf = \\begin{cases} a = 1, \\quad b = 2 & x \\end{cases}\n$$\n\n"
         "$$\nS = \\{a = 1, \\quad b = 2\\}\n$$\n\n"
         "$$\na = 1 \\text{ mod \\quad } b = 2\n$$", [], ()),
        ("each row of a row layout is its own line",
         "$$\n\\begin{aligned} a &= 1 \\\\ b &= 2 \\end{aligned}\n$$\n\n"
         "$$\n\\begin{gathered} a = 1 \\\\ s = \\begin{cases} -1 & x < 0 "
         "\\\\ 1 & x > 0 \\end{cases} \\end{gathered}\n$$\n\n"
         "$$\n\\begin{aligned} a &= 1, \\quad c = 2 \\end{aligned}\n$$",
         [10], ()),
        ("an inequality beside an equation is a condition, not an equation",
         "$$\na \\le 1, \\quad b = 2\n$$", [], ()),
        ("a display in a parsed table is outside body prose",
         "Name | Value\n--- | ---\nX | $$a = 1, \\quad b = 2$$", [],
         ((0, 2),)),
        ("a lone trailing backslash is not a command",
         "$$\na = 1 \\\n$$", [], ()),
        ("a bare row break outside a row layout keeps one line",
         "$$\na = b \\\\ c = d\n$$\n\n$$\na &= b \\\\\nc &= d\n$$\n\n"
         "$$\n\\begin{aligned} a &= 1 \\end{aligned} \\\\ b = 2\n$$\n\n"
         "$$\nr = \\sum_{\\substack{i=1 \\\\ j \\ne i}} w_i\n$$", [2, 6, 11],
         ()),
        ("two equations on separate source lines share a rendered line",
         "$$\na = 1\nb = 2\n$$", [2], ()),
        ("a source line that continues an operator, relation or group is "
         "one equation",
         "$$\nv = e - f\n- g = s\n$$\n\n$$\ns = \\sqrt{a}\n= \\sqrt{b}\n$$\n\n"
         "$$\nJ = \\frac{1}{m}\n\\sum_{i=1}^{m} e_i\n$$", [], ()),
        ("a comma, a semicolon, a clause word or a connective joins two "
         "equations",
         "$$\n\\mu = 0, \\sigma = 1\n$$\n\n$$\na = 1 \\text{ and } b = 2\n$$\n\n"
         "$$\na = 1; b = 2\n$$\n\n$$\na = 1;\\ b = 2\n$$\n\n"
         "$$\na = b \\Longleftrightarrow c = d\n$$\n\n"
         "$$\na = 1 \\hspace{1em} b = 2\n$$\n\n"
         "$$\nJ = x \\text{, so } K = y\n$$", [2, 6, 10, 14, 18, 22, 26], ()),
        ("the column pairs of an aligned row share its line",
         "$$\n\\begin{aligned} a &= 0, & b &= 1 \\end{aligned}\n$$\n\n"
         "$$\n\\begin{aligned} a &= 0 & b &= 1 \\end{aligned}\n$$", [2, 6],
         ()),
        ("lists, ranges, domains and continued conditions add no equation",
         "$$\nP(X = k) = \\ldots, k = 0, 1, \\ldots, n\n$$\n\n"
         "$$\nf(x) = x^2, x \\in \\mathbb{R}\n$$\n\n"
         "$$\np(x;\\theta) = \\ldots\n$$\n\n$$\nx = 1, 2, 3\n$$\n\n"
         "$$\ny = 1 \\text{ and } y > 0\n$$\n\n"
         "$$\ny_{ij} = 0 \\quad \\text{for } i = 1 \\text{ and } j = 2\n$$\n\n"
         "$$\ny_{ij} = 0, \\quad \\text{for } i = 1, j = 2\n$$", [], ()),
        ("a comma-opened list of values is an index range, not an equation",
         "$$\np(x) = \\theta^x (1-\\theta)^{1-x}, x = 0, 1\n$$\n\n"
         "$$\ny_i = 2 x_i, i = 1, 2, 3\n$$\n\n"
         "$$\na = 1, b = 2\n$$", [10], ()),
        ("a display opened on its equation's line is read",
         "$$a = b, \\qquad c = d\n$$", [1], ()),
        ("a display in a blockquote is read without its markers",
         "> Prose.\n>\n> $$\n> a = 1, \\quad b = 2\n> $$", [4], ()),
    ]
    total += len(split_cases)
    for name, prose, expected, spans in split_cases:
        got = [candidate["line"] for candidate in
               find_multi_relation_display_candidates(prose, spans)]
        ok = got == expected
        if verbose or not ok:
            print(("PASS" if ok else "FAIL") + ": " + name)
        if not ok:
            print("  expected %r, got %r" % (expected, got))
            failed += 1
    # Display spans: (name, prose, (open_line, close_line) pairs, spans).
    span_cases = [
        ("a closing delimiter on the math's line closes its display",
         "$$\nr = 1$$\n\nProse.\n\n$$\ns = 1\n$$", [(0, 1), (5, 7)], ()),
        ("an opening delimiter on the math's line opens its display",
         "$$r = 1\n$$\n\nProse.\n\n$$\ns = 1\n$$", [(0, 1), (5, 7)], ()),
        ("a closer followed by a period closes its display",
         "$$\nr = 1\n$$.\n\nProse.\n\n$$\ns = 1\n$$", [(0, 2), (6, 8)], ()),
        ("a last unpaired delimiter opens no display",
         "$$\nr = 1\n$$\n\nProse.\n\n$$\nProse.", [(0, 2)], ()),
        ("a delimiter on an excluded line is skipped",
         "X | $$\n\n$$\nr = 1\n$$", [(2, 4)], ((0, 0),)),
    ]
    total += len(span_cases)
    for name, prose, expected, spans in span_cases:
        got = [(span["open_line"], span["close_line"])
               for span in find_display_spans(prose, spans)]
        ok = got == expected
        if verbose or not ok:
            print(("PASS" if ok else "FAIL") + ": " + name)
        if not ok:
            print("  expected %r, got %r" % (expected, got))
            failed += 1
    # Row parsing alone: (name, display content, rendered lines).
    row_cases = [
        ("a lone backslash ending the content starts no command",
         "a = 1 \\", ["a = 1 \\"]),
    ]
    total += len(row_cases)
    for name, content, expected in row_cases:
        got = _display_lines(content)
        ok = got == expected
        if verbose or not ok:
            print(("PASS" if ok else "FAIL") + ": " + name)
        if not ok:
            print("  expected %r, got %r" % (expected, got))
            failed += 1
    # Well-definedness boilerplate: (name, text, card_line, sorted kinds).
    boilerplate_cases = [
        ("a nonempty dataset with a count guard",
         "For a nonempty dataset of $m \\ge 1$ instances, the error averages.",
         False, ["count-guard", "nonempty-guard"]),
        ("a standalone denominator guard sentence",
         "The ratio requires at least one predicted positive.",
         False, ["presence-guard"]),
        ("a nonzero-weight guard and a nonconstant feature",
         "For a model with nonzero feature weights, this is a straight "
         "line. A nonconstant training feature spans 0 to 1.",
         False, ["nonzero-guard", "nonzero-guard"]),
        ("a named strength range and a positive rate",
         "With regularization strength $\\alpha \\ge 0$ and a positive "
         "[[learning-rate|learning rate]] $\\eta$, it converges.",
         False, ["parameter-sign", "parameter-sign"]),
        ("nonnegative proportions that sum to one in a binding",
         "Let $p_{i,k} \\ge 0$ be the proportion, with "
         "$\\sum_{k=1}^{K} p_{i,k}=1$:",
         False, ["nonnegative-quantity", "sum-to-one"]),
        ("an open probability interval and a prose sum-to-one guard",
         "For $0 < p < 1$ both vectors have nonnegative components that "
         "sum to 1.",
         False, ["open-probability", "sum-to-one"]),
        ("definition-needed ranges and plain properties stay quiet",
         "For $p \\ge 1$ it is a norm, the mix ratio is $r \\in [0,1]$, "
         "convexity uses $0 \\le \\lambda \\le 1$, softmax probabilities "
         "are positive and sum to 1, and singular values are nonnegative.",
         False, []),
        ("body index bounds and displayed guards stay quiet",
         "The average $\\sum_{i=1}^{m} e_i$ is taken.\n\n$$\nm \\ge 1\n$$\n\n"
         "*A caption with $m \\ge 1$.*",
         False, []),
        ("a card lists full-range bounds and a count guard",
         "The average $m^{-1}\\sum_{i=1}^{m}(\\hat{y}^{(i)}-y^{(i)})^2$ over "
         "$m\\ge1$ instances.",
         True, ["count-guard", "full-range-bounds"]),
        ("a card's parameter sum keeps its bias-excluding bounds",
         "The penalty $\\alpha\\sum_{i=1}^{n}|\\theta_i|$ leaves the bias "
         "unpenalized.",
         True, []),
        ("a card's restricted sum skipping undefined terms",
         "The entropy $-\\sum_{k:p_k>0}p_k\\log_2 p_k$ of a distribution.",
         True, ["restricted-sum"]),
        ("full-range bounds are a card-only finding",
         "The average $m^{-1}\\sum_{i=1}^{m} e_i$ is taken.",
         False, []),
    ]
    total += len(boilerplate_cases)
    for name, text, card_line, expected in boilerplate_cases:
        got = sorted(candidate["kind"] for candidate in
                     find_boilerplate_candidates(text, card_line=card_line))
        ok = got == expected
        if verbose or not ok:
            print(("PASS" if ok else "FAIL") + ": " + name)
        if not ok:
            print("  expected %r, got %r" % (expected, got))
            failed += 1
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
