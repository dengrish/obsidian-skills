#!/usr/bin/env python3
"""Conservative candidates for prose-defined equations missing display math.

Equation coverage is ultimately semantic: an agent must decide whether the
note's prose states every operand and operation, then typeset only that stated
relationship.  This helper supplies a narrow deterministic floor for wording
that has already produced a real omission.  It does not generate LaTeX and is
not a general natural-language mathematics parser.

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
_CAPTION_RE = re.compile(r"^\s*\*(?!\*)\S(?:.*\S)?\*\s*$")
_ROOT_VARIANCE_RE = re.compile(
    r"\b(?:is(?:\s+(?:defined\s+as|equal\s+to))?|equals)\s+"
    r"(?:(?:generally|usually)\s+)?(?:the\s+)?"
    r"square\s+root\s+of\s+(?:the\s+)?variance\b",
    re.IGNORECASE,
)


def find_missing_display_equation_candidates(masked_prose,
                                             excluded_line_spans=()):
    """Return high-confidence prose calculations lacking display math.

    Each result has ``kind``, ``phrase``, and one-based ``line``.  A canonical
    own-line ``$$...$$`` block anywhere in the entry suppresses this narrow
    candidate: the helper is a safety net for equation-free notes, not an
    equation-to-paragraph matcher.  The executing agent still verifies that
    the phrase defines a quantity in context before editing.
    """
    prose = masked_prose or ""
    if any(match.group(1).strip()
           for match in _DISPLAY_BLOCK_RE.finditer(prose)):
        return []

    excluded = set()
    for start, end in excluded_line_spans or ():
        excluded.update(range(max(0, start), max(0, end) + 1))

    visible_lines = []
    for line_index, line in enumerate(prose.split("\n")):
        if line_index in excluded or _CAPTION_RE.match(line):
            # A non-whitespace sentinel prevents a match from bridging across
            # an excluded table or caption while preserving line offsets.
            visible_lines.append("\0" * len(line))
        else:
            visible_lines.append(line.replace("*", "").replace("_", ""))
    visible = "\n".join(visible_lines)

    candidates = []
    for match in _ROOT_VARIANCE_RE.finditer(visible):
        candidates.append({
            "kind": "square-root-of-variance",
            "phrase": " ".join(match.group(0).split()),
            "line": visible.count("\n", 0, match.start()) + 1,
        })
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
        ("hard-wrapped definition",
         "The scale is the square\nroot of the variance.", 1, ()),
        ("inline symbols do not satisfy display coverage",
         "It is the square root of variance and is denoted $\\sigma$.", 1, ()),
        ("canonical display block satisfies the narrow floor",
         "It is the square root of variance.\n\n$$\n"
         "\\sigma = \\sqrt{\\operatorname{Var}(X)}\n$$", 0, ()),
        ("a one-line display spelling is not the required form",
         "It is the square root of variance.\n\n$$\\sigma=1$$", 1, ()),
        ("an unclosed delimiter is not a display equation",
         "It is the square root of variance.\n\n$$\n\\sigma=1", 1, ()),
        ("an empty display block does not satisfy coverage",
         "It is the square root of variance.\n\n$$\n$$", 1, ()),
        ("a whitespace-only display block does not satisfy coverage",
         "It is the square root of variance.\n\n$$\n   \n$$", 1, ()),
        ("negation is not an affirmative cue",
         "It is not the square root of variance.", 0, ()),
        ("possibility is not an affirmative cue",
         "It may be the square root of variance.", 0, ()),
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
