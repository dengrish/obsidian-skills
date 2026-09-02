#!/usr/bin/env python3
"""Shared structural checks for wiki-entry opening prose.

These helpers deliberately inspect placement and spelling, not factual
correctness.  A Person/Event date is structurally valid only when a
parenthetical in one of wiki-builder's documented forms immediately follows
the first outer-bold subject; a year later in the sentence may describe
something else.

Stdlib only, Python 3.8+.
"""

import argparse
import datetime
import re

__all__ = ["opener_has_subject_date", "opener_subject_date_status"]


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


def opener_has_subject_date(opener, entry_type):
    """Whether a canonical date parenthetical immediately follows the subject.

    The first outer-bold span is the entry subject under the shared wiki
    format.  Ordinary bold, triple emphasis, and mixed scientific-name/suffix
    emphasis all match the same outer span.
    """
    return opener_subject_date_status(opener, entry_type) == "valid"


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
