#!/usr/bin/env python3
"""The canonical source-filename rule — the one implementation in this plugin.

`pdf-organizer` writes these names and `pdf-figure-extractor` reads them, and
until this module existed each held its own copy of the shape: `CANONICAL` in
`pdf-organizer/scripts/organize.py`, and a hand-written `CHAPTER_STEM_RE` in
`pdf-figure-extractor/scripts/batch_extract.py`.  The two disagreed about where
a `_src` suffix sits, and the disagreement was total in both directions:

    Prince_UDL_2026_src_01_Intro   canonical: NO    a chapter: YES
    Prince_UDL_2026_02_SupLearn_src canonical: YES   a chapter: NO

so no chapter name satisfied both consumers.  One name re-renamed every chapter
on the next batch run (orphaning its figures under the old stem); the other
stopped the book being recognised as split, so every figure was written twice
under two stems that never collide and never deduplicate.  Neither failure
raises.  See CONVENTIONS.md §1a and §8b.

    The shape
    ---------
    <Author>_<AbbrevTitle>_<Year>                       standalone
    <Author>_<AbbrevTitle>_<Year>_<NN>_<ChapterName>    chapter
                                        [_src][_2|_3…]  optional tail, in
                                                        THAT order

`Year` is four digits or the literal `nd`.  `NN` is a zero-padded two-digit
chapter number.  The tail is optional on either form: `_src` is the user's own
marker for a source file that has a same-stemmed note beside it, and `_2`, `_3`
… disambiguate two documents that would otherwise share a name.

**The tail always comes last, after the chapter segment.**  That is the single
fact the two consumers used to disagree about.  A chapter of a book whose own
stem carries a tail does *not* inherit it — `Prince_UDL_2026_src.pdf` splits
into `Prince_UDL_2026_01_Intro.pdf`, and that chapter grows its own `_src` only
when it, too, has a note beside it.  Comparison between a book and its chapters
is therefore done on the *core* stem — the identity with `_src` removed —
which is what `core_stem()` returns and what `chapter_parts()` reports as the
book.  **A `_2`/`_3` disambiguator is NOT removed:** it marks a different
document, so a disambiguated book matches no chapter, and `split_book` refuses
to split one rather than mint chapter names that would collide (§1a).

Usage as a module (after the CONVENTIONS.md §5 bootstrap):

    import naming
    naming.looks_canonical("Prince_UDL_2026_01_Intro_src.pdf")   -> True
    naming.core_stem("Prince_UDL_2026_01_Intro_src")             -> 'Prince_UDL_2026_01_Intro'
    naming.chapter_parts("Prince_UDL_2026_01_Intro_src")
        -> ChapterName(book='Prince_UDL_2026', number='01',
                       name='Intro', tail='_src')
    naming.chapter_parts("Prince_UDL_2026")                      -> None

As a CLI:

    python3 naming.py canonical 'Prince_UDL_2026_01_Intro_src.pdf'
    python3 naming.py chapter   'Prince_UDL_2026_01_Intro_src'
    python3 naming.py --test
"""
import argparse
import collections
import os
import re
import sys

__all__ = [
    "SAFE_NAME", "CANONICAL", "TAIL", "STANDALONE_CORE", "CHAPTER_CORE",
    "ChapterName", "looks_canonical", "core_stem", "split_tail",
    "chapter_parts", "chapter_book_stem", "stem_of",
]

#: What a name this plugin *writes* may contain: ASCII, no quotes, no shell or
#: glob metacharacter, and a leading alphanumeric so a written name can never
#: be a dotfile.  Input names are unconstrained — cleaning those up is
#: pdf-organizer's whole job.  CONVENTIONS.md §1b is why this is narrow: a
#: filename is untrusted text and reaches tools this plugin does not control.
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")

#: The optional tail, in its only legal order: `_src` then a disambiguator.
#: Written as a separate pattern because both consumers need to strip it
#: before comparing a chapter against its book.
#:
#: It is never applied by a bare `search()`.  `_\d+` matches the *year* —
#: searching `Prince_UDL_2026` for a trailing disambiguator strips `_2026` and
#: leaves `Prince_UDL`, which silently unpairs every book from its chapters.
#: The tail is only ever peeled off a stem whose canonical core has already
#: been matched, which is what `_FULL_RE` below does.
TAIL = r"(?:_src)?(?:_[0-9]+)?"

#: `<Author>_<AbbrevTitle>_<Year>`, no tail.
STANDALONE_CORE = r"[A-Za-z0-9][A-Za-z0-9-]*_[A-Za-z0-9-]+_(?:[0-9]{4}|nd)"

#: `<standalone core>_<NN>_<ChapterName>`, no tail.  The chapter name admits
#: no underscore: that is what keeps `_NN_` unambiguous as the boundary
#: between a book stem and its chapter segment.
CHAPTER_CORE = STANDALONE_CORE + r"_[0-9]{2}_[A-Za-z0-9-]+"

#: A stem this plugin has already produced, either form, tail optional.
#: Match against the STEM, not the filename — `looks_canonical()` does the
#: extension stripping for you.
CANONICAL = re.compile(r"(?:%s)(?:_[0-9]{2}_[A-Za-z0-9-]+)?%s\Z"
                       % (STANDALONE_CORE, TAIL))

#: The same shape, with the base, the `_src` marker and the disambiguator
#: captured separately.  They are NOT one "tail": see `split_tail`.
_FULL_RE = re.compile(r"\A(?P<base>%s(?:_[0-9]{2}_[A-Za-z0-9-]+)?)"
                      r"(?P<src>(?:_src)?)(?P<disam>(?:_[0-9]+)?)\Z" % STANDALONE_CORE)

#: A chapter stem, tolerating a tail in *either* position.  `book` is always
#: the tail-free standalone core, so a chapter pairs with its book whatever
#: either of them carries.
#:
#: `mid` exists only to recognise the legacy mis-spelling `<book>_src_NN_Name`
#: — the form the two former implementations disagreed about.  It is not
#: canonical (`looks_canonical` still rejects it, so pdf-organizer re-renames
#: it), but recognising it here means a vault that already holds those files
#: still gets its book skipped instead of every figure written twice.
_CHAPTER_RE = re.compile(r"\A(?P<book>%s)(?P<mid>(?:_src)?)"
                         r"_(?P<number>[0-9]{2})_(?P<name>[A-Za-z0-9-]+)"
                         r"(?P<tail>%s)\Z"
                         % (STANDALONE_CORE, TAIL))

#: What `chapter_parts()` returns.  `book` is the *core* book stem — no tail —
#: because a book and its chapters carry their tails independently.
ChapterName = collections.namedtuple("ChapterName",
                                     "book number name tail")


def stem_of(name):
    """The filename stem: basename without its final extension.

    Already extracted stems must use ``is_stem=True`` on the helpers below.
    Otherwise an interior period is mistaken for another file extension.
    """
    return os.path.splitext(os.path.basename(name))[0]


def _stem(name, is_stem):
    return os.fspath(name) if is_stem else stem_of(name)


def split_tail(stem):
    """`(identity, src_marker)` — the `_src` marker split off the stem.

    **`_src` and `_N` are not one tail, and only `_src` comes off here.** They
    mean opposite things:

    * `_src` marks the SAME document in another representation — a source PDF
      sitting beside a same-stemmed note. Two files, one document.
    * `_2`, `_3`, … mark a DIFFERENT document that would otherwise collide
      (§1a(1): appended "when a target name is already taken"). Two documents.

    So the disambiguator is part of the document's identity and stays in the
    returned string; the `_src` marker is not and comes off.

    >>> split_tail("Prince_UDL_2026_01_Intro_src")
    ('Prince_UDL_2026_01_Intro', '_src')
    >>> split_tail("Smith_WealthNations_1776_2")
    ('Smith_WealthNations_1776_2', '')
    >>> split_tail("Prince_UDL_2026_src_2")
    ('Prince_UDL_2026_2', '_src')
    >>> split_tail("Smith_WealthNations_1776")
    ('Smith_WealthNations_1776', '')

    Stripping `_N` here is what made `Prince_UDL_2026_2` — a different book —
    pair with `Prince_UDL_2026`'s chapters: the second book was never skipped,
    so every one of its figures was written twice under two stems that never
    collide, and its chapter was filed under the first book. Neither raised.

    A stem that is not canonical has no meaningful marker and is returned whole
    — guessing one off a junk name is how `Prince_UDL_2026` became
    `Prince_UDL` (see `TAIL`).
    """
    m = _FULL_RE.match(stem)
    if not m:
        return (stem, "")
    return (m.group("base") + m.group("disam"), m.group("src"))


def core_stem(name, *, is_stem=False):
    """The stem's document identity: `_src` removed, `_N` kept.

    This is the string to compare a book against its chapters. A book and its
    chapters carry `_src` independently, so it must come off — but a `_N`
    disambiguator names a different document, so it must not. A
    `_N`-disambiguated book therefore matches no chapter, which is correct:
    `split_book` refuses to split one (§1a).
    Pass ``is_stem=True`` when ``name`` is already a stem; its periods are
    part of its identity, not another extension to remove.
    """
    return split_tail(_stem(name, is_stem))[0]


def looks_canonical(name, *, is_stem=False):
    """True when `name`'s stem is already in this plugin's output form.

    Answering this by eye gives different answers on different runs and both
    answers are expensive: a false positive leaves a junk name in place
    forever (the file is never re-examined), a false negative renames a
    canonical file and orphans every figure filed under its old stem.
    Pass ``is_stem=True`` for an already extracted stem. In particular,
    ``Doe_Study_2025.revised`` is not a canonical stem.
    """
    return bool(CANONICAL.match(_stem(name, is_stem)))


def chapter_parts(name, *, is_stem=False):
    """`ChapterName` when `name` is a book chapter, else None.

    `book` is the tail-free core, so a chapter carrying `_src` or a
    disambiguator reports the same book as one without — which is what lets a
    book pair with its chapters whatever tails either of them grew.
    Pass ``is_stem=True`` for an already extracted stem.
    """
    m = _CHAPTER_RE.match(_stem(name, is_stem))
    if not m:
        return None
    return ChapterName(book=m.group("book"), number=m.group("number"),
                       name=m.group("name"), tail=m.group("tail"))


def chapter_book_stem(name, *, is_stem=False):
    """The core book stem `name` is a chapter of, or None."""
    parts = chapter_parts(name, is_stem=is_stem)
    return parts.book if parts else None


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------

#: (stem, canonical?, book stem or None).  Every case here is drawn from a
#: skill's own worked examples or from a real disagreement between the two
#: former implementations; see the module docstring.
TEST_CASES = [
    # --- standalone, the ordinary case ---
    ("Vaswani_AttnAllYouNeed_2017",          True,  None),
    ("Smith_WealthNations_1776",             True,  None),
    ("AcmeCorp_StrategyMemo_nd",             True,  None),
    ("Cormen_CLRS_2022",                     True,  None),
    ("Geron_ML_2025",                        True,  None),
    # --- standalone with a tail ---
    ("Smith_WealthNations_1776_2",           True,  None),
    ("Prince_UDL_2026_src",                  True,  None),
    ("Prince_UDL_2026_src_2",                True,  None),
    ("Prince_UDL_2026_2_01_Intro",           False, None),   # _N before the chapter
    ("-Foo_Bar_2020",                        False, None),   # not a SAFE_NAME
    # --- chapters ---
    ("Prince_UDL_2026_01_Intro",             True,  "Prince_UDL_2026"),
    ("Kuhn_StructSciRev_2012_02_RouteNormSci", True, "Kuhn_StructSciRev_2012"),
    ("Smith_X_nd_01_Intro",                  True,  "Smith_X_nd"),
    ("Prince_UDL_2026_12_Conclusion",        True,  "Prince_UDL_2026"),
    # --- chapters with a tail: THE case the two implementations split on ---
    ("Prince_UDL_2026_02_SupLearn_src",      True,  "Prince_UDL_2026"),
    ("Prince_UDL_2026_01_Intro_src",         True,  "Prince_UDL_2026"),
    ("Prince_UDL_2026_01_Intro_2",           True,  "Prince_UDL_2026"),
    ("Prince_UDL_2026_01_Intro_src_2",       True,  "Prince_UDL_2026"),
    # --- tail in the wrong order is NOT canonical ---
    ("Prince_UDL_2026_2_src",                False, None),
    ("Prince_UDL_2026_01_Intro_2_src",       False, None),
    # --- the legacy mis-spelling: `_src` before the chapter segment.  Not
    #     canonical (a batch run re-renames it), but still *recognised* as a
    #     chapter, so a vault holding these files still gets its book skipped
    #     rather than every figure written twice.
    ("Prince_UDL_2026_src_01_Intro",         False, "Prince_UDL_2026"),
    # --- not canonical, not chapters ---
    ("Backup_2023",                          False, None),
    ("Geron_ML_1.5",                         False, None),
    ("download",                             False, None),
    ("document(1)",                          False, None),
    ("paper",                                False, None),
    ("Prince_UDL_20260_01_Intro",            False, None),
    ("Prince_UDL_2026_1_Intro",              False, None),   # NN not padded
    ("Prince_UDL_2026_01_Sup_Learn",         False, None),   # `_` in the name
    # Unicode digits are not in SAFE_NAME and cannot be names the writer made.
    ("Doe_Study_٢٠٢٥",                     False, None),
    ("Doe_Study_2025_٠١_Intro",             False, None),
    ("Doe_Study_2025_٢",                   False, None),
]

#: Names `SAFE_NAME` must refuse.  Each is a real shape pdf-organizer has been
#: handed, and each would reach a tool this plugin does not control.
UNSAFE_NAMES = [
    "It's a draft.pdf", "O'Reilly Media.pdf", "Prince_UDL_2026.pdf (1)",
    "Prince_UDL_2026.pdf; rm -rf x", "Müller_X_2020.pdf", ".hidden_X_2020.pdf",
    "Prince UDL 2026.pdf", "Prince_UDL_2026.pdf‽",
]


def run_self_test():
    """Run every documented case; return the result dict (no printing).

    Same shape as `slugify.run_self_test()`, so `tests/test_conventions.py`
    consumes both identically.
    """
    failures, total = [], 0

    for stem, canonical, book in TEST_CASES:
        total += 2
        got_canonical = looks_canonical(stem, is_stem=True)
        if got_canonical != canonical:
            failures.append("looks_canonical(%r) -> %r, expected %r"
                            % (stem, got_canonical, canonical))
        got_book = chapter_book_stem(stem, is_stem=True)
        if got_book != book:
            failures.append("chapter_book_stem(%r) -> %r, expected %r"
                            % (stem, got_book, book))

    # The extension must not change any verdict: every consumer holds some of
    # these as paths and some as bare stems.
    for stem, canonical, book in TEST_CASES:
        total += 1
        if looks_canonical(stem + ".pdf") != canonical:
            failures.append("looks_canonical(%r) disagrees with the bare stem"
                            % (stem + ".pdf"))

    # A real PDF can carry an extra dot segment, including a second .pdf.
    # Never strip that segment again when a consumer passes Path.stem.
    for stem in ("Doe_Study_2025.revised", "Doe_Study_2025.pdf",
                 "Doe_Book_2025_01_Intro.revised", "Doe_Book_2025_01_Intro.pdf",
                 "Doe_Book_2025_src.revised", "Doe_Book_2025_src.pdf"):
        total += 4
        if looks_canonical(stem, is_stem=True):
            failures.append("dotted stem %r was treated as canonical" % stem)
        if core_stem(stem, is_stem=True) != stem:
            failures.append("dotted stem %r lost part of its identity" % stem)
        if chapter_parts(stem, is_stem=True) is not None:
            failures.append("dotted stem %r was mistaken for a chapter" % stem)
        if looks_canonical(stem + ".pdf") or core_stem(stem + ".pdf") != stem:
            failures.append("dotted PDF %r disagrees with its exact stem" % (stem + ".pdf"))

    # A chapter pairs with its book whatever `_src` either carries: that is the
    # comparison `split_book_chapters` makes.
    for book_stem in ("Prince_UDL_2026", "Prince_UDL_2026_src"):
        for chapter in ("Prince_UDL_2026_01_Intro",
                        "Prince_UDL_2026_01_Intro_src",
                        "Prince_UDL_2026_01_Intro_2"):
            total += 1
            if chapter_book_stem(chapter) != core_stem(book_stem):
                failures.append("%r does not pair with book %r"
                                % (chapter, book_stem))

    # A `_N`-disambiguated book is a DIFFERENT document and must pair with
    # NOTHING.  This half of the suite used to assert the opposite, which is
    # how the bug it now pins survived: book #2 was never skipped, so every one
    # of its figures was written twice under two stems that never collide.
    for book_stem in ("Prince_UDL_2026_2", "Prince_UDL_2026_src_2"):
        total += 1
        if core_stem(book_stem) != "Prince_UDL_2026_2":
            failures.append("core_stem(%r) lost the disambiguator -> %r"
                            % (book_stem, core_stem(book_stem)))
        for chapter in ("Prince_UDL_2026_01_Intro",
                        "Prince_UDL_2026_01_Intro_src"):
            total += 1
            if chapter_book_stem(chapter) == core_stem(book_stem):
                failures.append("%r wrongly pairs with the disambiguated book %r"
                                % (chapter, book_stem))

    # `_N` before the chapter segment is not a chapter at all: reading it as
    # one files a different book's chapter under this book.
    for stem in ("Prince_UDL_2026_2_01_Intro", "Prince_UDL_2026_10_01_Intro"):
        total += 1
        if chapter_parts(stem) is not None:
            failures.append("%r must not parse as a chapter (the disambiguator "
                            "may not precede the chapter segment)" % stem)

    # Every canonical name must also be a name this plugin can WRITE.  A
    # leading hyphen passed `looks_canonical` while `SAFE_NAME` refused it, so
    # `-x_y_2020.pdf` read as already-organized and was never refused — and a
    # leading-hyphen filename is the argv-injection shape §1b exists for.
    for stem in ("-Foo_Bar_2020", "-Foo_Bar_2020_01_Intro", "-a_b_nd"):
        total += 1
        if looks_canonical(stem):
            failures.append("looks_canonical(%r) is True but SAFE_NAME rejects it"
                            % stem)

    for name in UNSAFE_NAMES:
        total += 1
        if SAFE_NAME.match(name):
            failures.append("SAFE_NAME accepted %r" % name)

    # A canonical name is always a safe name — otherwise the recogniser and
    # the writer disagree about what this plugin produces.
    for stem, canonical, _ in TEST_CASES:
        if not canonical:
            continue
        total += 1
        if not SAFE_NAME.match(stem + ".pdf"):
            failures.append("canonical %r is not SAFE_NAME" % stem)

    return {
        "total": total,
        "passed": total - len(failures),
        "failed": len(failures),
        "failures": failures,
        "ok": not failures,
    }


def _build_parser():
    p = argparse.ArgumentParser(
        description="The canonical source-filename rule (CONVENTIONS.md §1a).")
    p.add_argument("--test", action="store_true",
                   help="run the self-test and exit")
    sub = p.add_subparsers(dest="cmd")
    c = sub.add_parser("canonical", help="is each NAME in canonical form?")
    c.add_argument("names", nargs="+", metavar="NAME")
    h = sub.add_parser("chapter", help="report the book each NAME is a chapter of")
    h.add_argument("names", nargs="+", metavar="NAME")
    return p


def main(argv=None):
    args = _build_parser().parse_args(argv)

    if args.test:
        result = run_self_test()
        for f in result["failures"]:
            print("FAIL: " + f, file=sys.stderr)
        print("%d/%d" % (result["passed"], result["total"]))
        return 0 if result["ok"] else 1

    if args.cmd == "canonical":
        bad = 0
        for name in args.names:
            ok = looks_canonical(name)
            bad += not ok
            print("%-44s %s" % (name, "canonical" if ok else "NOT canonical"))
        return 1 if bad else 0

    if args.cmd == "chapter":
        for name in args.names:
            parts = chapter_parts(name)
            if parts:
                print("%-44s chapter %s of %s%s"
                      % (name, parts.number, parts.book,
                         "  (tail %s)" % parts.tail if parts.tail else ""))
            else:
                print("%-44s not a chapter" % name)
        return 0

    _build_parser().print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
