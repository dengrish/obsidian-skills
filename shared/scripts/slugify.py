#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""slugify.py -- wiki-builder's canonical title -> filename slug algorithm.

Implements SKILL.md "Filenames and Wikilinks" (preprocessing pass + main
pipeline) exactly, including the three special-character rules spelled out
below.

PREPROCESSING (order is load-bearing; special-character substitutions run
before NFKD because NFKD canonicalises distinct codepoints to the same
character and would erase meaning):

  1.  microsign U+00B5 -> "u"            (distinct from Greek mu U+03BC)
  2.  Greek letters    -> "name-"        (alpha- beta- ... omega-)
  3.  dashes           -> "-"            (en, em, figure, horbar, minus)
  4.  arrows           -> "-"
  5.  super/subscript digits -> plain digits
  6.  superscript charges  U+207A -> "-plus", U+207B -> "-minus"
  7.  prime U+2032 and apostrophes -> dropped
  8.  middle dot U+00B7 -> "-"
  9.  non-decomposing Latin: ss / o / ae / oe
  10. [FIX-A] ASCII charge notation      (see below)
  11. [FIX-B] "+" -> "-plus", "#" -> "-sharp", "*" -> "-star"
  12. NFKD fold + encode("ascii", "ignore")

MAIN PIPELINE: lowercase -> non-[a-z0-9] to "-" -> collapse runs -> strip
-> append ".md".  An empty result means the title cannot be slugged
automatically; the caller must ask the user for a different title rather
than writing a file literally named ".md".

--------------------------------------------------------------------------
THE THREE SPECIAL-CHARACTER RULES
--------------------------------------------------------------------------
FIX-A and FIX-B are rules the script and the slug pipeline it implements BOTH state
(the ASCII "+"/"#"/"*" mapping and the plain-text charge normalisation) --
they agree, and changing either means changing both.  FIX-C is a
belt-and-braces extension with no effect on output.

FIX-B  "+", "#", "*" are mapped to "-plus", "-sharp", "-star" BEFORE the
       main pipeline.  Without this, step 2 of the main pipeline turns each
       of them into a bare "-" which step 4 then strips, so the titles
       "C", "C++", "C#" and "C*" ALL collide on "c.md".  With the fix they
       become c.md / c-plus-plus.md / c-sharp.md / c-star.md.  The mapping
       carries a leading hyphen so the token reads as a separate slug word,
       matching the skill's own treatment of the superscript charges.

FIX-A  ASCII charge notation is normalised so that a plain-text source and
       a typeset source produce the SAME slug for the same ion.  The skill
       only handles the typeset form: "Ca2+" -> "Ca2-plus" (falls out of
       FIX-B) matches "Ca<sup>2+</sup>" -> "ca2-plus", and "Cl-" is
       rewritten to "Cl-minus" so it matches "Cl<sup>-</sup>" -> "cl-minus".
       The minus rewrite is deliberately narrow -- it only fires on an
       ion-shaped token (1-2 letter element symbol + optional digits)
       whose trailing "-" is not followed by another word character -- so
       ordinary hyphenated titles ("Cross-validation", "X-ray", "T-cell",
       "Smith-Waterman") are untouched.

FIX-C  Curly apostrophes U+2018 / U+2019 are dropped alongside the ASCII
       apostrophe.  This is a no-op in outcome (ascii-ignore would drop
       them anyway) but makes the intent explicit, and the final sigma
       U+03C2 is mapped to "sigma-" alongside U+03C3.

Usable as a CLI and as a module:

    from slugify import slugify, slug_stem, base_term, mu_variants
    slugify("ROC curve")     -> "roc-curve.md"
    slug_stem("ROC curve")   -> "roc-curve"
    base_term("Feature (machine learning)") -> "Feature"
    mu_variants("uM buffer") -> both the U+00B5 and U+03BC spellings, for
                                probe (b) in find_collisions.py

CLI (JSON to stdout unless --stem; --help everywhere):
    slugify.py "ROC curve"      -> {"title","slug","filename","ok"}
    slugify.py "---"            -> {..., "ok": false, "error": ...}, exit 1
                                   (unsluggable -- ask the user to retitle
                                   rather than writing a file named ".md")
    slugify.py --test           -> inline self-test over the skill's worked
                                   examples plus the three special-character
                                   rules, Greek capitals, the final sigma and
                                   the CJK/empty-slug family. The case count is
                                   reported, never asserted on the nose --
                                   pinning it is what blocked adding coverage:
                                   {"total","passed","failed","failures","ok"}
    slugify.py "C++" --stem     -> c-plus-plus   (plain text, not JSON)
    A title that starts with "-" needs the separator: slugify.py -- "---".
Exit codes: 0 ok, 1 unsluggable title (or failing self-test), 2 bad usage.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata

__all__ = [
    "slugify",
    "slug_stem",
    "base_term",
    "has_parenthetical",
    "mu_variants",
    "SlugError",
    "GREEK",
    "TEST_CASES",
    "run_self_test",
]


class SlugError(ValueError):
    """Raised when a title reduces to the empty slug."""


# --------------------------------------------------------------------------
# preprocessing tables
# --------------------------------------------------------------------------

MICRO_SIGN = "µ"  # micro sign, SI prefix -- NOT Greek mu
GREEK_MU = "μ"  # Greek small letter mu

_GREEK_BASE = {
    "α": "alpha-",
    "β": "beta-",
    "γ": "gamma-",
    "δ": "delta-",
    "ε": "epsilon-",
    "ζ": "zeta-",
    "η": "eta-",
    "θ": "theta-",
    "ι": "iota-",
    "κ": "kappa-",
    "λ": "lambda-",
    "μ": "mu-",
    "ν": "nu-",
    "ξ": "xi-",
    "ο": "omicron-",
    "π": "pi-",
    "ρ": "rho-",
    "σ": "sigma-",
    "ς": "sigma-",  # final sigma (FIX-C)
    "τ": "tau-",
    "υ": "upsilon-",
    "φ": "phi-",
    "χ": "chi-",
    "ψ": "psi-",
    "ω": "omega-",
}

GREEK = dict(_GREEK_BASE)
for _lower, _name in _GREEK_BASE.items():
    GREEK[_lower.upper()] = _name

#: U+2010 HYPHEN and U+2011 NON-BREAKING HYPHEN are here because neither has
#: an NFKD decomposition to ASCII (U+2011 only compat-maps to U+2010), so
#: without this mapping step 12's ascii-ignore DROPPED them and the typeset
#: ``state‐of‐the‐art`` slugged to ``stateoftheart`` — words silently fused,
#: unlike every other dash the pipeline maps to ``-``.
DASHES = "‐‑–—‒―−"  # hyphen nbhyphen en em figure horbar minus
ARROWS = "→←↔⇌⇄"
DROPPED = "′'‘’"  # prime, ASCII apostrophe, curly quotes

SUPERSUB_DIGITS = {
    "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
    "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
    "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4",
    "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9",
}

SUPER_CHARGES = {"⁺": "-plus", "⁻": "-minus"}

NON_DECOMPOSING = {
    "ß": "ss", "ẞ": "SS",
    "ø": "o", "Ø": "O",
    "æ": "ae", "Æ": "AE",
    "œ": "oe", "Œ": "OE",
}

# FIX-B -- must run before the main pipeline or C / C++ / C# / C* all collide.
SYMBOL_WORDS = {"+": "-plus", "#": "-sharp", "*": "-star"}

# FIX-A -- narrow ion-shaped ASCII negative-charge pattern.
_ASCII_ANION_RE = re.compile(r"(?<![A-Za-z0-9-])([A-Z][a-z]?[0-9]*)-(?![A-Za-z0-9-])")

_NON_SLUG_RE = re.compile(r"[^a-z0-9]")
_HYPHEN_RUN_RE = re.compile(r"-{2,}")
_TRAILING_PAREN_RE = re.compile(r"^(?P<base>.*?)\s*\([^()]*\)\s*$")


# --------------------------------------------------------------------------
# algorithm
# --------------------------------------------------------------------------

def preprocess(title: str) -> str:
    """Run the skill's preprocessing pass (plus FIX-A/B/C) over ``title``."""
    s = title

    # 1. microsign before anything that could NFKD it into Greek mu
    s = s.replace(MICRO_SIGN, "u")

    # 2. Greek letters -> english name + separator hyphen
    if any(ch in GREEK for ch in s):
        s = "".join(GREEK.get(ch, ch) for ch in s)

    # 3/4. dashes and arrows
    s = "".join("-" if ch in DASHES or ch in ARROWS else ch for ch in s)

    # 5. super/subscript digits
    s = "".join(SUPERSUB_DIGITS.get(ch, ch) for ch in s)

    # 6. superscript charges
    s = "".join(SUPER_CHARGES.get(ch, ch) for ch in s)

    # 7. primes / apostrophes dropped outright
    s = "".join(ch for ch in s if ch not in DROPPED)

    # 8. middle dot
    s = s.replace("·", "-")

    # 9. non-decomposing Latin
    s = "".join(NON_DECOMPOSING.get(ch, ch) for ch in s)

    # 10. FIX-A: ASCII anion notation ("Cl-" -> "Cl-minus", "Ca2-" -> "Ca2-minus")
    s = _ASCII_ANION_RE.sub(r"\1-minus", s)

    # 11. FIX-B: "+" / "#" / "*" become words (covers ASCII cations too)
    s = "".join(SYMBOL_WORDS.get(ch, ch) for ch in s)

    # 12. NFKD fold to ASCII
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return s


#: The longest slug STEM this module will return.  ext4 and APFS cap a
#: filename at 255 bytes; past this budget (stem + ``.md``, with headroom) the
#: eventual ``open()``/``mv`` dies with ENAMETOOLONG -- an unhandled crash in
#: whichever consumer got there first, which is exactly the failure class the
#: empty-slug guard below exists to turn into an ask-the-user error.
#: clipping-processor's ``slug.py`` bounds its article stems the same way
#: (``MAX_SLUG_BYTES``); a wiki slug carries no ``_fig_<N>`` suffix, so its
#: budget is simply the filesystem's.
MAX_STEM_BYTES = 250


def slug_stem(title: str) -> str:
    """Return the slug WITHOUT the ``.md`` suffix.  Raises :class:`SlugError`."""
    if title is None:
        raise SlugError("title is None")
    s = preprocess(str(title))
    s = s.lower()                       # main pipeline 1
    s = _NON_SLUG_RE.sub("-", s)        # main pipeline 2
    s = _HYPHEN_RUN_RE.sub("-", s)      # main pipeline 3
    s = s.strip("-")                    # main pipeline 4
    if not s:
        raise SlugError(
            "title %r reduces to an empty slug -- ask the user for a different "
            "title rather than writing a file named '.md'" % (title,)
        )
    if len(s.encode("utf-8")) > MAX_STEM_BYTES:
        raise SlugError(
            "title %r slugs to %d bytes, past the %d-byte filename budget -- "
            "ask the user for a shorter title rather than crashing the write "
            "with ENAMETOOLONG" % (title, len(s.encode("utf-8")), MAX_STEM_BYTES)
        )
    return s


def slugify(title: str) -> str:
    """Return the on-disk filename (``<slug>.md``).  Raises :class:`SlugError`."""
    return slug_stem(title) + ".md"     # main pipeline 5


def base_term(title: str) -> str:
    """Title minus a trailing parenthetical disambiguator.

    ``"Feature (machine learning)"`` -> ``"Feature"``.  Titles without a
    trailing parenthetical come back unchanged.  Used by the body-opener,
    description-subject and flashcard checks (SKILL.md "Base-term rule for
    parenthetical titles").  Note the SLUG still derives from the full title.
    """
    if not title:
        return title
    m = _TRAILING_PAREN_RE.match(title.strip())
    if not m:
        return title.strip()
    base = m.group("base").strip()
    return base or title.strip()


def has_parenthetical(title: str) -> bool:
    """True when ``title`` carries a trailing parenthetical disambiguator."""
    t = (title or "").strip()
    return bool(t) and base_term(t) != t


def mu_variants(title: str) -> list:
    """Both micro-sign / Greek-mu spellings of ``title`` (collision probe b)."""
    out = [title]
    if MICRO_SIGN in title:
        out.append(title.replace(MICRO_SIGN, GREEK_MU))
    if GREEK_MU in title:
        out.append(title.replace(GREEK_MU, MICRO_SIGN))
    seen, uniq = set(), []
    for t in out:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


# --------------------------------------------------------------------------
# inline self-test
# --------------------------------------------------------------------------
# (title, expected filename or None when the algorithm must stop, note)

TEST_CASES = [
    # --- the worked examples block, SKILL.md lines 417-431 -------------------
    ("LambdaRank", "lambdarank.md", "L417"),
    ("ROC curve", "roc-curve.md", "L418"),
    ("F1 score", "f1-score.md", "L419"),
    ("Cross-validation", "cross-validation.md", "L420 existing hyphen preserved"),
    ("Aurélien Géron", "aurelien-geron.md", "L421 NFKD diacritics"),
    ("Schrödinger equation", "schrodinger-equation.md", "L422"),
    ("k-fold cross-validation", "k-fold-cross-validation.md", "L423"),
    ("α-helix", "alpha-helix.md", "L424 Greek letter transliterated"),
    ("γδ T cell", "gamma-delta-t-cell.md", "L425 adjacent Greek letters"),
    ("µm", "um.md", "L426 microsign"),
    ("μm", "mu-m.md", "L426 Greek mu contrast"),
    ("Smith–Waterman", "smith-waterman.md", "L427 en-dash"),
    ("DALL·E", "dall-e.md", "L428 middle dot"),
    ("[Ca²⁺]", "ca2-plus.md", "L429 superscript digit + charge"),
    ("5'-UTR", "5-utr.md", "L430 apostrophe dropped"),
    ("", None, "L431 empty title -> stop"),
    ("---", None, "L431 all-separator title -> stop"),

    # --- worked examples stated elsewhere in the slug section ----------------
    ("Cl⁻", "cl-minus.md", "L396 superscript minus charge"),
    ("Feature (machine learning)", "feature-machine-learning.md",
     "L475 slug derives from the FULL title, parenthetical included"),
    ("Information entropy", "information-entropy.md", "L473 qualified compound"),
    ("Weight tying (language model embedding sharing)",
     "weight-tying-language-model-embedding-sharing.md", "L485 qualified title"),
    ("Kullback–Leibler divergence", "kullback-leibler-divergence.md",
     "L195 en-dash in a proper name"),
    ("Ångström", "angstrom.md", "NFKD fold, ring + umlaut"),
    ("Straße", "strasse.md", "L399 non-decomposing eszett"),
    ("Søren Kierkegaard", "soren-kierkegaard.md", "L399 non-decomposing o-slash"),

    # --- FIX-B: +, #, * would otherwise all collide on c.md ------------------
    ("C", "c.md", "FIX-B baseline"),
    ("C++", "c-plus-plus.md", "FIX-B"),
    ("C#", "c-sharp.md", "FIX-B"),
    ("C*", "c-star.md", "FIX-B"),
    ("A*", "a-star.md", "FIX-B search algorithm"),
    ("gRPC++", "grpc-plus-plus.md", "FIX-B"),

    # --- FIX-A: ASCII and typeset charge notation must agree ----------------
    ("Ca2+", "ca2-plus.md", "FIX-A ASCII cation == Ca²⁺"),
    ("Ca²⁺", "ca2-plus.md", "FIX-A typeset cation"),
    ("Cl-", "cl-minus.md", "FIX-A ASCII anion == Cl⁻"),
    ("Na+", "na-plus.md", "FIX-A"),
    ("[Mg2+]", "mg2-plus.md", "FIX-A bracketed"),

    # --- FIX-A must NOT fire on ordinary hyphenated titles ------------------
    ("X-ray", "x-ray.md", "FIX-A negative control"),
    ("T-cell receptor", "t-cell-receptor.md", "FIX-A negative control"),
    ("mRNA-seq", "mrna-seq.md", "FIX-A negative control"),
    ("RNA-", "rna.md", "FIX-A negative control: acronym, not an ion"),

    # --- Greek CAPITALS -----------------------------------------------------
    # GREEK is built by case-folding _GREEK_BASE, so a capital resolves to the
    # same english name as its lowercase form.  Nothing stood guard over that
    # until these cases: the capitals are also the confusable ones, because
    # U+0391 GREEK CAPITAL ALPHA and U+0392 GREEK CAPITAL BETA are homoglyphs
    # of Latin "A" and "B" -- so the same-looking title must slug differently
    # depending on which codepoint it actually holds, and the Latin controls
    # below are half the assertion.
    ("Α-helix", "alpha-helix.md", "Greek CAPITAL alpha (U+0391)"),
    ("A-helix", "a-helix.md", "Latin capital A control -- homoglyph of the above"),
    ("Β-sheet", "beta-sheet.md", "Greek CAPITAL beta (U+0392)"),
    ("B-sheet", "b-sheet.md", "Latin capital B control -- homoglyph of the above"),
    ("ΔG", "delta-g.md", "Greek CAPITAL delta"),
    ("Ω notation", "omega-notation.md", "Greek CAPITAL omega"),
    ("Σ-algebra", "sigma-algebra.md", "Greek CAPITAL sigma"),

    # --- FIX-C: final sigma folds exactly like medial sigma ------------------
    ("σ", "sigma.md", "medial sigma U+03C3"),
    ("ς", "sigma.md", "FIX-C final sigma U+03C2 -- must equal the medial form"),
    ("σ vs ς", "sigma-vs-sigma.md", "FIX-C both sigmas in one title"),

    # --- CJK and whitespace: unsluggable, the algorithm must STOP ------------
    # Nothing survives NFKD + ascii-ignore, so the slug is empty.  §4a's rule
    # is to ask the user to retitle -- never to write a file named ".md" and
    # never to rename an existing entry to "".
    ("機械学習", None, "CJK han -> empty slug -> stop"),
    ("トランスフォーマー", None, "CJK katakana -> empty slug -> stop"),
    ("   ", None, "whitespace-only title -> stop"),

    # --- typeset hyphens: U+2010/U+2011 have no NFKD path to ASCII -----------
    # Without the DASHES mapping they were silently DROPPED by ascii-ignore,
    # fusing the words into one token instead of separating them.
    ("state‐of‐the‐art", "state-of-the-art.md",
     "U+2010 HYPHEN maps to -, never fuses"),
    ("state‑of‑the‑art", "state-of-the-art.md",
     "U+2011 NON-BREAKING HYPHEN maps to -, never fuses"),

    # --- the filename budget: an over-long stem must STOP, not ENAMETOOLONG --
    ("A " + "very " * 60 + "long title", None,
     "past MAX_STEM_BYTES -> stop (ask the user, never crash the write)"),
]


def run_self_test():
    """Run :data:`TEST_CASES`; return the result dict (no printing)."""
    failures = []
    for title, expected, note in TEST_CASES:
        try:
            got = slugify(title)
        except SlugError:
            got = None
        except Exception as exc:  # never crash the self-test
            got = "<%s: %s>" % (type(exc).__name__, exc)
        if got != expected:
            failures.append({
                "title": title,
                "note": note,
                "expected": expected,
                "got": got,
            })
    return {
        "total": len(TEST_CASES),
        "passed": len(TEST_CASES) - len(failures),
        "failed": len(failures),
        "failures": failures,
        "ok": not failures,
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _build_parser():
    p = argparse.ArgumentParser(
        prog="slugify.py",
        description="wiki-builder title -> filename slug algorithm (stdlib only).",
        epilog='example: slugify.py "ROC curve"  ->  {"slug": "roc-curve", ...}',
    )
    p.add_argument("title", nargs="?", help="entity title to slug")
    p.add_argument("--test", action="store_true",
                   help="run the inline self-test over the skill's worked examples")
    p.add_argument("--stem", action="store_true",
                   help="print only the bare slug (no .md) as plain text")
    return p


_KNOWN_FLAGS = {"-h", "--help", "--test", "--stem", "--"}


def _guard_argv(argv):
    """Let a title that looks like a flag through (the skill's "---" example).

    ``slugify.py "---"`` must reach the algorithm and report that the title
    is unsluggable, not die in argparse.  A ``--`` is inserted before the
    first non-flag token so argparse treats it as positional.
    """
    argv = list(argv)
    for i, token in enumerate(argv):
        if token in _KNOWN_FLAGS:
            if token == "--":
                return argv
            continue
        # A real flag typo looks like "-x" / "--word"; leave those to argparse
        # so the user sees the error.  Anything else that merely starts with a
        # dash ("---", "-", "-3dB point") is a title.
        if token.startswith("-") and not re.match(r"^--?[A-Za-z]", token):
            return argv[:i] + ["--"] + argv[i:]
        return argv
    return argv


def main(argv=None):
    argv = _guard_argv(sys.argv[1:] if argv is None else argv)
    args = _build_parser().parse_args(argv)

    if args.test:
        result = run_self_test()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["ok"] else 1

    if args.title is None:
        _build_parser().print_usage(sys.stderr)
        print('slugify.py: error: a title is required (or use --test)', file=sys.stderr)
        return 2

    try:
        stem = slug_stem(args.title)
    except SlugError as exc:
        print(json.dumps({
            "title": args.title,
            "slug": None,
            "filename": None,
            "ok": False,
            "error": str(exc),
        }, indent=2, ensure_ascii=False))
        return 1

    if args.stem:
        print(stem)
        return 0

    print(json.dumps({
        "title": args.title,
        "slug": stem,
        "filename": stem + ".md",
        "ok": True,
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
