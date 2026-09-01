#!/usr/bin/env python3
"""Shared structural checks for wiki-entry opening prose.

These helpers deliberately inspect placement, not factual correctness.  A
Person/Event date is structurally present only when a year-bearing
parenthetical immediately follows the first outer-bold subject; a year later
in the sentence may describe something else.

Stdlib only, Python 3.8+.
"""

import argparse
import re

__all__ = ["opener_has_subject_date"]


_BOLD_OUTER_RE = re.compile(
    r"(?<!\*)\*\*((?:\$[^$\n]+\$|\*[^*\n]+\*|[^*\n])+?)\*\*(?!\*)")


def opener_has_subject_date(opener):
    """Whether a year-bearing parenthetical immediately follows the subject.

    The first outer-bold span is the entry subject under the shared wiki
    format.  Ordinary bold, triple emphasis, and mixed scientific-name/suffix
    emphasis all match the same outer span.
    """
    bold = _BOLD_OUTER_RE.search(opener or "")
    if not bold:
        return False
    return bool(re.match(r"\s*\([^)]*\b\d{3,4}\b[^)]*\)",
                         (opener or "")[bold.end():]))


def run_self_test(verbose=False):
    cases = [
        ("ordinary Person range",
         "**Isaac Newton** (1643–1727) was a physicist.", True),
        ("leading prose before the subject",
         "The **Manhattan Project** (1942–1946) developed weapons.", True),
        ("living Person marker", "**Researcher** (b. 1947) works here.", True),
        ("recurring Event marker",
         "**Conference** (annual, since 1987) meets each year.", True),
        ("triple-emphasis subject",
         "***Named work*** (1600) premiered in London.", True),
        ("mixed scientific-name subject",
         "***E. coli* K-12** (isolated in 1922) is a strain.", True),
        ("missing parenthetical", "**Researcher** was born in 1947.", False),
        ("later unrelated parenthetical",
         "**Researcher** won a prize in 2020 (born 1947).", False),
    ]
    failed = 0
    for name, opener, expected in cases:
        got = opener_has_subject_date(opener)
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
