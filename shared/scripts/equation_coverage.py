#!/usr/bin/env python3
"""Conservative candidates for defining math missing canonical display form.

Equation coverage is ultimately semantic: an agent must decide whether the
note's prose states every operand and operation, then typeset only that stated
relationship.  This helper supplies a narrow deterministic floor for wording
that has already produced real omissions. It recognizes three families:
explicit square-root-of-variance definitions, defining equations left inline,
and a small set of prose calculations whose operands and operation are named.
It does not generate LaTeX and is not a general natural-language mathematics
parser.

Callers pass the full-entry prose region only, after blanking fenced,
indented, and inline code.  Frontmatter, Related footers, Flashcards, and
legacy stubs remain outside this detector.  Parsed table spans may be supplied
to exclude table cells; whole-line italic captions are excluded here.

Stdlib only, Python 3.8+.
"""

import argparse
import re

__all__ = ["find_missing_display_equation_candidates"]


_DISPLAY_BLOCK_RE = re.compile(
    r"(?ms)^ {0,3}\$\$[ \t]*\n(.*?)\n {0,3}\$\$[ \t]*$")
_INLINE_MATH_RE = re.compile(
    r"(?<![\\$])\$(?!\$)((?:\\.|[^$\n])+?)(?<!\\)\$(?!\$)")
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
    ("averaged-probability",
     re.compile(
         r"(?:\b(?:class[ \t]+)?probabilit(?:y|ies)\b[ \t,*]{0,20}"
         r"(?:(?:is|are)[ \t]+)?averag(?:ed|ing)\b|"
         r"\baverag(?:e|es|ed|ing)\b[^.!?;\n\x00]{0,40}"
         r"\b(?:class[ \t]+)?probabilit(?:y|ies)\b)",
         re.IGNORECASE)),
    ("majority-vote",
     re.compile(
         r"\b(?:majority[ \t]+(?:class|vote)[ \t]+"
         r"(?:wins|is[ \t]+returned)|class[ \t]+"
         r"(?:that[ \t]+receives|with)[ \t]+the[ \t]+most[ \t]+votes?)\b",
         re.IGNORECASE)),
    ("average-or-sum-of-predictions",
     re.compile(
         r"(?:\b(?:average|mean)[ \t]+of[ \t]+(?:the[ \t]+)?"
         r"predictions?\b|\bsum[ \t]+of\b[^.!?;\n\x00]{0,50}"
         r"\bpredictions?\b|\bpredicts?\b[^.!?;\n\x00]{0,80}"
         r"\bby[ \t]+summ(?:ing|ation)\b[^.!?;\n\x00]{0,60}"
         r"\bpredictions?\b)", re.IGNORECASE)),
    ("regression-average",
     re.compile(
         r"(?:\bfor[ \t]+regression\b[^.!?;\n\x00]{0,80}"
         r"\b(?:it|aggregation)[ \t]+is[ \t]+the[ \t]+average\b|"
         r"\bfor[ \t]+regression\b[^.!?;\n\x00]{0,100}\bleaf\b"
         r"[^.!?;\n\x00]{0,80}\b(?:predicts?|returns?)\b"
         r"[^.!?;\n\x00]{0,60}\b(?:mean|average)\b)", re.IGNORECASE)),
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


def _display_line_spans(prose, require_content=True,
                        require_blank_adjacency=True):
    """Return inclusive zero-based line spans for canonical display blocks."""
    spans = []
    lines = prose.split("\n")
    for match in _DISPLAY_BLOCK_RE.finditer(prose):
        if require_content and not match.group(1).strip():
            continue
        start = _line_number(prose, match.start()) - 1
        end = _line_number(prose, match.end()) - 1
        if require_blank_adjacency:
            blank_before = start == 0 or not lines[start - 1].strip()
            blank_after = end == len(lines) - 1 or not lines[end + 1].strip()
            if not (blank_before and blank_after):
                continue
        spans.append((start, end))
    return spans


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
            or bool(re.search(r"(?:^|[^a-z\\])n(?:[_({]|(?=$|[^a-z]))",
                              rhs)))


def _probability_average_operands_are_named(compact):
    """Whether an average aggregates probabilities rather than raw values."""
    rhs = compact.split("=", 1)[1] if "=" in compact else compact
    return ("probab" in rhs or r"\pr" in rhs
            or bool(re.search(
                r"(?:^|[^a-z\\])p(?:[_({]|(?=$|[^a-z]))", rhs)))


def _majority_aggregation_is_named(compact):
    """Require a vote/count aggregation, not merely a generic argmax."""
    if any(marker in compact for marker in ("mode", "majority", "vote")):
        return True
    if "argmax" not in compact:
        return False
    rhs = compact.split("=", 1)[1] if "=" in compact else compact
    has_vote_sum = "\\sum" in rhs
    has_indicator = any(marker in rhs for marker in
                        (r"\mathbf{1}", r"\mathbb{1}", r"\mathbbm{1}",
                         r"\indicator", r"\delta"))
    # In compact hard-voting notation, an equality inside the argmax RHS is
    # normally the indicator predicate ``h_m(x)=c``.
    has_class_equality = "=" in rhs
    return has_vote_sum and (has_indicator or has_class_equality)


def _named_fraction_result_is_named(compact, context):
    """Match a prose quantity to the result named on a fraction's left side."""
    lhs = compact.split("=", 1)[0]
    words = context.lower()
    if "probability" in words:
        return ("prob" in lhs or r"\pr" in lhs
                or _lhs_has_symbol(lhs, ("p",)))
    if "rate" in words:
        return (any(marker in lhs for marker in
                    ("rate", "tpr", "fpr", "fnr", "tnr", "precision",
                     "recall", "specificity", "sensitivity", "error"))
                or _lhs_has_symbol(lhs, ("r",)))
    if "proportion" in words or "share" in words:
        return ("prop" in lhs or "share" in lhs
                or _lhs_has_symbol(lhs, ("p", "q")))
    if "score" in words:
        return ("score" in lhs or "f_1" in lhs or "f1" in lhs
                or _lhs_has_symbol(lhs, ("s", "z")))
    if "coefficient" in words:
        return (any(marker in lhs for marker in
                    ("coef", r"\beta", r"\rho"))
                or _lhs_has_symbol(lhs, ("r", "c")))
    return False


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
    return bool(expected) and all(expected)


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
    if kind == "averaged-probability":
        return (_display_has_average_operator(compact)
                and _probability_average_operands_are_named(compact))
    if kind == "majority-vote":
        return _majority_aggregation_is_named(compact)
    if kind in {"average-or-sum-of-predictions", "regression-average",
                "neighbor-value-average"}:
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
        elif kind == "regression-average":
            rhs = compact.split("=", 1)[1] if "=" in compact else compact
            has_relevant_operand = (
                _prediction_operands_are_named(compact)
                or bool(re.search(
                    r"(?:^|[^a-z\\])y(?:[_({^]|(?=$|[^a-z]))", rhs)))
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
    """Whether a matching canonical display follows the prose nearby."""
    nearby_blocks = []
    for start, end in display_spans:
        if 0 < start - line_index <= 3:
            block = "\n".join(lines[start:end + 1])
            if _display_supports(kind, block, context):
                return True
        if (kind == "nearest-center-assignment-and-update"
                and 0 < start - line_index <= 8):
            nearby_blocks.append("\n".join(lines[start:end + 1]))
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


def _inline_formula_is_substantive(formula):
    value = (formula or "").strip()
    if _SIMPLE_NUMERIC_ASSIGNMENT_RE.fullmatch(value):
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
    satisfied only by a nearby canonical display block; an unrelated equation
    elsewhere in the entry no longer hides it. A defining formula found inline
    is always reported because its placement, rather than mere coverage, is the
    problem. The executing agent still verifies context before editing.
    """
    prose = masked_prose or ""
    excluded = set()
    for start, end in excluded_line_spans or ():
        excluded.update(range(max(0, start), max(0, end) + 1))

    display_spans = _display_line_spans(prose)
    all_display_spans = _display_line_spans(
        prose, require_content=False, require_blank_adjacency=False)
    prose_lines = prose.split("\n")
    visible_lines = []
    for line_index, line in enumerate(prose_lines):
        in_display = any(start <= line_index <= end
                         for start, end in all_display_spans)
        if line_index in excluded or in_display or _CAPTION_RE.match(line):
            # A non-whitespace sentinel prevents a match from bridging across
            # an excluded table or caption while preserving line offsets.
            visible_lines.append("\0" * len(line))
        else:
            visible_lines.append(line)
    visible = "\n".join(visible_lines)

    # Remove emphasis delimiters only from the prose/cue view. The raw inline
    # formula must remain byte-faithful: deleting ``_`` changed ``x_0`` into
    # ``x0`` before the simple-assignment exception could classify it.
    plain_chars = list(visible)
    protected = bytearray(len(visible))
    for math_match in _INLINE_MATH_RE.finditer(visible):
        protected[math_match.start():math_match.end()] = \
            b"\x01" * (math_match.end() - math_match.start())
    for index, char in enumerate(plain_chars):
        if not protected[index] and char in "*_":
            plain_chars[index] = " "
    plain_visible = "".join(plain_chars)
    calculation_visible = _fold_hard_wraps(plain_visible)
    opening_break = re.search(r"\n[ \t]*\n", plain_visible)
    opening_end = opening_break.start() if opening_break else len(plain_visible)

    candidates = []

    for match in _INLINE_MATH_RE.finditer(visible):
        formula = match.group(1)
        if not _inline_formula_is_substantive(formula):
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
            # Averaged probabilities name soft voting itself. Outside the
            # opener they commonly occur only as a comparison/link from a
            # different ensemble method, where duplicating soft voting's
            # equation would work against atomic notes.
            if kind == "averaged-probability" and match.start() > opening_end:
                continue
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
    # calculation (for example "majority class" and "most votes"). Keep the
    # first stable candidate per kind/line/phrase, then report in source order.
    unique = {}
    for candidate in candidates:
        key = (candidate["kind"], candidate["line"], candidate["phrase"].lower())
        unique.setdefault(key, candidate)
    candidates = list(unique.values())
    candidates.sort(key=lambda item: (item["line"], item["kind"], item["phrase"]))
    return candidates


def run_self_test(verbose=False):
    cases = [
        ("pronoun definition",
         "It is the square root of the variance.", 1, ()),
        ("named definition with emphasis",
         "The **standard deviation** is the square root of variance.", 1, ()),
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
        ("a one-line display spelling is not the required form",
         "It is the square root of variance.\n\n$$\\sigma=1$$", 1, ()),
        ("an unclosed delimiter is not a display equation",
         "It is the square root of variance.\n\n$$\n\\sigma=1", 1, ()),
        ("an empty display block does not satisfy coverage",
         "It is the square root of variance.\n\n$$\n$$", 1, ()),
        ("a whitespace-only display block does not satisfy coverage",
         "It is the square root of variance.\n\n$$\n   \n$$", 1, ()),
        ("a display without a blank line before it is not canonical coverage",
         "It is the square root of variance.\n$$\n"
         "\\sigma = \\sqrt{\\operatorname{Var}(X)}\n$$", 1, ()),
        ("a display without a blank line after it is not canonical coverage",
         "It is the square root of variance.\n\n$$\n"
         "\\sigma = \\sqrt{\\operatorname{Var}(X)}\n$$\nNext.", 1, ()),
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
        ("averaged class probabilities are a prose calculation candidate",
         "It predicts from class probabilities averaged over all classifiers.",
         1, ()),
        ("a soft-voting display covers its probability operands",
         "It predicts from class probabilities averaged over all classifiers."
         "\n\n$$\n\\hat{y}(x) = \\operatorname*{argmax}_k "
         "\\frac{1}{N} \\sum_j \\hat{p}_{j,k}(x)\n$$", 0, ()),
        ("an average-error comparison is not a defining calculation",
         "The average prediction error is lower on this dataset.", 0, ()),
        ("an on-average probability comparison is not a calculation",
         "The probability of error is lower on average for this model.", 0, ()),
        ("a majority vote is a prose calculation candidate",
         "Each member votes and the majority class wins.", 1, ()),
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
        ("avoidance in a coordinated predicate does not reject averaging",
         "The method avoids hard voting and averages class probabilities.",
         1, ()),
        ("omission in a coordinated predicate does not reject an equation",
         "The method omits missing values and computes the score as "
         "$s=f(x)$.", 1, ()),
        ("an average of neighbor values is a prose calculation candidate",
         "Regression returns the average of their values.", 1, ()),
        ("a regression ensemble average is a prose calculation candidate",
         "For classification aggregation is the mode; for regression it is "
         "the average.", 1, ()),
        ("a regression leaf mean is a prose calculation candidate",
         "For regression, each leaf predicts the mean target of the training "
         "instances that reach it.", 1, ()),
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
         "leaf.\n\n$$\np_k = n_k / n\n$$", 0, ()),
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
        ("an average of unrelated values does not cover averaged probabilities",
         "It predicts from class probabilities averaged over all classifiers."
         "\n\n$$\np=1/N\\sum_i x_i\n$$", 1, ()),
        ("a generic argmax does not cover majority voting",
         "Each member votes and the majority class wins.\n\n$$\n"
         "\\hat y = \\operatorname*{argmax}_k s_k\n$$", 1, ()),
        ("an indicator-count argmax covers majority voting",
         "Each member votes and the majority class wins.\n\n$$\n"
         "\\hat y = \\operatorname*{argmax}_k \\sum_j "
         "\\mathbf{1}[h_j(x)=k]\n$$", 0, ()),
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
    for name, prose, expected, spans in cases:
        got = len(find_missing_display_equation_candidates(prose, spans))
        ok = got == expected
        if verbose or not ok:
            print(("PASS" if ok else "FAIL") + ": " + name)
        if not ok:
            print("  expected %r, got %r" % (expected, got))
            failed += 1
    print("%d/%d self-test cases pass" % (len(cases) - failed, len(cases)))
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
