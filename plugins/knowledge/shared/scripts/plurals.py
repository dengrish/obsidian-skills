#!/usr/bin/env python3
"""Canonical English inflection and light collision-stem helpers.

Two skills ask the same question and must not answer it differently.
`wiki-build` probes a *candidate* title against the vault (`SKILL.md` step 3,
probes (c), (e), and (f)); `wiki-lint` sweeps the *whole vault* for near-duplicate
pairs, and CONVENTIONS.md §9 gives whole-vault dedup detection to wiki-lint
alone. Both rest on one fact — which two word forms are the same word — and
until this module existed each held its own copy: `singularize()` in
`wiki-build/scripts/find_collisions.py`, with its irregular tables and its
length floors, and a three-rule regular-plural stripper called `singular()` in
`wiki-lint/scripts/scan_vault.py`. The two disagreed on every irregular:

    token        find_collisions   scan_vault
    hypotheses   hypothesis        hypothes
    analyses     analysis          analys
    matrices     matrix            matrice
    indices      index             indice
    leaves       leaf              leave
    axes         axis              ax
    series       series            sery

so `hypothesis-testing` / `testing-hypotheses` fired for wiki-build, probing
one new candidate against the vault, and *not* for wiki-lint's sweep — and
the sweep is the only thing that ever looks at a pair already sitting in the
vault, so a pair that got in was seen by nobody, forever. Nothing raises; the
vault simply keeps two entries for one concept. CONVENTIONS.md §4a is the
precedent (the slug algorithm lives in `shared/scripts/slugify.py` and both
skills import it) and §9 is the ownership split this restores.

    Token level                     Slug level (the probe keys)
    -----------                     ---------------------------
    pluralize(word)                 plural_key(slug)
    singularize(word)               singular_key(slug)
    singular_forms(word) -> set     singular_keys(slug) -> set
                                    wordorder_key_singular(slug)
                                    real_permutation(slug_a, slug_b)
                                    stem_key(slug), stem_tokens(slug)

**`singular_forms` / `singular_keys` are the SYMMETRIC pair, and a probe wants
them.** English singularisation is ambiguous ("bases" = base | basis, "axes" =
axe | axis), so comparing two single best guesses only fires when the candidate
happens to be the plural; intersecting two form *sets* fires either way. The
word itself is always a member, so a singular meets its own plural halfway.

Usage as a module (after the CONVENTIONS.md §5 bootstrap):

    import plurals
    plurals.singularize("hypotheses")               -> 'hypothesis'
    plurals.singular_key("confusion-matrices")      -> 'confusion-matrix'
    plurals.singular_keys("bases")                  -> {'bases', 'base', 'basis'}
    plurals.wordorder_key_singular("testing-hypotheses")  -> 'hypothesis-testing'
    plurals.real_permutation("weight-tying", "tying-weights")   -> True
    plurals.stem_key("masked-language-modeling")    -> 'languag-mask-model'
    plurals.stem_tokens("k-means-clustering")       -> {'cluster', 'k', 'mean'}

As a CLI:

    python3 plurals.py singular hypotheses matrices leaves
    python3 plurals.py plural hypothesis matrix leaf
    python3 plurals.py key confusion-matrices testing-hypotheses
    python3 plurals.py --test
"""
import argparse
import re
import sys

__all__ = [
    "IRREGULAR_PLURALS", "IRREGULAR_SINGULARS", "AMBIGUOUS_IRREGULAR_PLURALS",
    "VES_IRREGULARS", "pluralize", "singularize", "singular_forms",
    "singular_key", "singular_keys", "plural_key", "wordorder_key_singular",
    "real_permutation", "stem_key", "stem_tokens", "run_self_test",
]

IRREGULAR_PLURALS = {
    "man": "men", "woman": "women", "child": "children", "person": "people",
    "mouse": "mice", "goose": "geese", "foot": "feet", "tooth": "teeth",
    "datum": "data", "medium": "media", "criterion": "criteria",
    "phenomenon": "phenomena", "analysis": "analyses", "basis": "bases",
    "hypothesis": "hypotheses", "thesis": "theses", "axis": "axes",
    "matrix": "matrices", "index": "indices", "vertex": "vertices",
    "appendix": "appendices", "corpus": "corpora", "genus": "genera",
    "nucleus": "nuclei", "radius": "radii", "stimulus": "stimuli",
    "bacterium": "bacteria", "archaeon": "archaea", "fungus": "fungi",
    "protozoan": "protozoa", "mitochondrion": "mitochondria",
    "curriculum": "curricula", "series": "series", "species": "species",
    # Common scientific heads that appear in entity titles. Keeping these in
    # the shared table prevents the builder and whole-vault linter from
    # disagreeing on pairs such as taxon/taxa or phylum/phyla.
    "taxon": "taxa", "phylum": "phyla", "alga": "algae",
    "larva": "larvae", "vertebra": "vertebrae", "ovum": "ova",
    "stratum": "strata", "focus": "foci", "locus": "loci",
    "cortex": "cortices", "apex": "apices",
}
IRREGULAR_SINGULARS = {
    IRREGULAR_PLURALS[key]: key for key in IRREGULAR_PLURALS
}

# Irregular plurals that ALSO read as a regular plural of a different real word:
# "bases" is the plural of both "basis" and "base".  For these the regular
# reading is the default (singularize) and the irregular one is kept as an extra
# form (singular_forms), so probe (c) still connects "bases" to "basis".
AMBIGUOUS_IRREGULAR_PLURALS = {"bases"}

# -ves plurals whose singular really ends in -f / -fe.  Everything else ending
# in -ves is a regular plural of a -ve word: "curves" -> "curve", not "curf".
_F_SINGULARS = ["leaf", "half", "knife", "wolf", "shelf", "life", "wife",
                "thief", "calf", "self"]
VES_IRREGULARS = {(w[:-1] if w[-1:] == "f" else w[:-2]) + "ves": w
                  for w in _F_SINGULARS}
F_SINGULAR_PLURALS = {
    w: (w[:-1] if w[-1:] == "f" else w[:-2]) + "ves"
    for w in _F_SINGULARS
}

_SIBILANT_RE = re.compile(r"(s|x|z|ch|sh)$")


def pluralize(word):
    """Standard English pluralisation of one slug token."""
    if not word:
        return word
    if word in IRREGULAR_PLURALS:
        return IRREGULAR_PLURALS[word]
    if word in IRREGULAR_SINGULARS:      # already plural
        return word
    if word in F_SINGULAR_PLURALS:
        return F_SINGULAR_PLURALS[word]
    if _SIBILANT_RE.search(word):
        return word + "es"
    if word.endswith("y") and len(word) > 1 and word[-2] not in "aeiou":
        return word[:-1] + "ies"
    return word + "s"


def singularize(word):
    """Standard English singularisation of one slug token (best single guess).

    ``-ves`` maps to ``-f`` only for the handful of words where that is really
    the singular.  Blanket ``-ves`` -> ``-f`` produced "curves" -> "curf",
    "waves" -> "waf": singularize was then direction-asymmetric (the singular
    "curve" stayed "curve"), so probe (c) never connected a real plural pair
    and ``--no-stem`` returned verdict ``create`` for "ROC curves" against an
    existing ``roc-curve.md`` -- a duplicate entry.
    """
    if not word:
        return word
    if word in AMBIGUOUS_IRREGULAR_PLURALS:
        return word[:-1]                 # regular reading wins: "bases" -> "base"
    if word in IRREGULAR_SINGULARS:
        return IRREGULAR_SINGULARS[word]
    if word in IRREGULAR_PLURALS:        # already singular
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("ves") and len(word) > 4:
        return VES_IRREGULARS.get(word, word[:-3] + "ve")
    if word.endswith("es") and _SIBILANT_RE.search(word[:-2]):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 2:
        return word[:-1]
    return word


def singular_forms(word):
    """EVERY plausible singular of one token, as a set.

    English singularisation is ambiguous ("bases" = base | basis; "axes" =
    axe | axis), and probe (c) has to be SYMMETRIC -- it must fire whether the
    candidate is the plural or the singular.  Comparing two single best-guess
    keys cannot do that; intersecting two form sets can.  The word itself is
    always a member, so a singular candidate meets its own plural halfway.
    """
    if not word:
        return {word}
    out = {word}
    if word in IRREGULAR_SINGULARS:
        out.add(IRREGULAR_SINGULARS[word])
    if word.endswith("ies") and len(word) > 4:
        out.add(word[:-3] + "y")
    if word.endswith("ves") and len(word) > 4:
        out.add(VES_IRREGULARS.get(word, word[:-3] + "ve"))
    if word.endswith("es") and len(word) > 2 and _SIBILANT_RE.search(word[:-2]):
        out.add(word[:-2])
    if word.endswith("s") and not word.endswith("ss") and len(word) > 2:
        out.add(word[:-1])
    return out


def _last_token_map(slug, fn):
    parts = slug.split("-")
    if not parts:
        return slug
    parts[-1] = fn(parts[-1])
    return "-".join(parts)


def singular_key(slug):
    """Probe (c) key: the slug with its head (last) token singularised."""
    return _last_token_map(slug, singularize)


def singular_keys(slug):
    """Probe (c) key SET: the slug with its head token replaced by each singular."""
    parts = slug.split("-")
    if not parts:
        return {slug}
    head = parts[-1]
    return {"-".join(parts[:-1] + [s]) for s in singular_forms(head)}


def plural_key(slug):
    """The slug with its head (last) token pluralised."""
    return _last_token_map(slug, pluralize)


def wordorder_key_singular(slug):
    """Probe (e) key with each token singularised first.

    wiki-build's SKILL.md states probe (e) as a pure token sort and then gives
    ``weight-tying`` vs ``tying-weights.md`` as its worked example, claiming
    "both produce [tying, weight] after sort".  They do not -- ``weights`` does
    not sort to ``weight``.  Probe (e) is therefore run on both the raw and the
    per-token-singularised forms, so the skill's own worked example actually
    fires.
    """
    return "-".join(sorted(singularize(t) for t in slug.split("-") if t))


def real_permutation(slug_a, slug_b):
    """True when two slugs sharing a singularised token sort are a real re-order.

    The guard on probe (e)'s singularised half, in one place because both
    callers must draw the line identically or the same pair is reported twice
    under two names.  Two slugs whose RAW token sorts already agree are the
    plain word-order hit, and two whose singularised token *sequences* are
    identical are a plain plural pair -- each is already reported by its own
    probe, so neither is a permutation finding as well.
    """
    if sorted(t for t in slug_a.split("-") if t) \
            == sorted(t for t in slug_b.split("-") if t):
        return False
    return [singularize(t) for t in slug_a.split("-") if t] \
        != [singularize(t) for t in slug_b.split("-") if t]


# Probe (f)'s light morphology is shared for the same reason as the plural and
# word-order keys above: wiki-build tests an incoming candidate, while
# wiki-lint is the only process that sees a pair already present in a vault.
# A copied suffix table lets the two worklists silently disagree. Ordered
# longest-first so ``ization`` wins over ``ation`` and ``ion``.
_STEM_SUFFIXES = [
    "izations", "isations", "ization", "isation", "ationally", "ational",
    "izing", "ising", "izers", "isers", "izer", "iser", "ized", "ised",
    "ize", "ise", "ations", "ation", "ating", "ates", "ated", "ate",
    "ements", "ement", "ments", "ment",
    "nesses", "ness", "ities", "ity", "ings", "ing", "ers", "er", "ors",
    "or", "ies", "ied", "ed", "es", "s",
]
_DOUBLE_TAIL_RE = re.compile(r"([bdfglmnprt])\1$")


def _stem_token(token):
    """Light suffix stem used only for collision signals, never titles."""
    value = token
    for suffix in _STEM_SUFFIXES:
        # Agent-noun endings are too short and too common in lexical roots for
        # a three-character remainder to be useful: ``error`` became ``er``
        # after ``-or`` removal plus doubled-tail folding. A four-character
        # floor still groups tokenizer/tokenization and modeler/modeling.
        floor = 4 if suffix in ("er", "ers", "or", "ors") else 3
        if value.endswith(suffix) and len(value) - len(suffix) >= floor:
            value = value[: -len(suffix)]
            break
    value = _DOUBLE_TAIL_RE.sub(r"\1", value)  # modell -> model
    if len(value) > 3 and value.endswith("e"):
        value = value[:-1]                       # tokeniz(e) -> tokeniz
    return value


def stem_key(slug):
    """Probe (f) key: tokens light-stemmed, then sorted."""
    return "-".join(sorted(_stem_token(t) for t in slug.split("-") if t))


def stem_tokens(slug):
    """Probe (g) token set, using the same light stem as probe (f)."""
    return {_stem_token(t) for t in slug.split("-") if t}


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------

#: `(plural, singular)`.  Every pair here is either a token the two former
#: implementations answered differently (see the module docstring), or a
#: regular case that had to keep working while they were reconciled.
PLURAL_PAIRS = [
    # --- the tokens the two implementations split on ---
    ("hypotheses", "hypothesis"), ("analyses", "analysis"),
    ("matrices", "matrix"), ("indices", "index"), ("leaves", "leaf"),
    ("mice", "mouse"), ("axes", "axis"), ("ties", "tie"),
    ("series", "series"),
    # --- the rest of the irregular table ---
    ("men", "man"), ("women", "woman"), ("children", "child"),
    ("people", "person"), ("geese", "goose"), ("feet", "foot"),
    ("teeth", "tooth"), ("data", "datum"), ("media", "medium"),
    ("criteria", "criterion"), ("phenomena", "phenomenon"),
    ("theses", "thesis"), ("vertices", "vertex"), ("appendices", "appendix"),
    ("corpora", "corpus"), ("genera", "genus"), ("nuclei", "nucleus"),
    ("radii", "radius"), ("stimuli", "stimulus"), ("bacteria", "bacterium"),
    ("archaea", "archaeon"), ("fungi", "fungus"),
    ("protozoa", "protozoan"), ("mitochondria", "mitochondrion"),
    ("curricula", "curriculum"), ("species", "species"),
    ("taxa", "taxon"), ("phyla", "phylum"), ("algae", "alga"),
    ("larvae", "larva"), ("vertebrae", "vertebra"), ("ova", "ovum"),
    ("strata", "stratum"), ("foci", "focus"), ("loci", "locus"),
    ("cortices", "cortex"), ("apices", "apex"),
    # --- -f / -fe plurals that really are -ves ---
    ("halves", "half"), ("knives", "knife"), ("wolves", "wolf"),
    ("shelves", "shelf"), ("lives", "life"), ("wives", "wife"),
    ("thieves", "thief"), ("calves", "calf"), ("selves", "self"),
    # --- regular: plain -s ---
    ("curves", "curve"), ("genes", "gene"), ("models", "model"),
    ("networks", "network"), ("layers", "layer"), ("waves", "wave"),
    ("valves", "valve"),
    # --- regular: -es after a sibilant ---
    ("classes", "class"), ("boxes", "box"), ("batches", "batch"),
    ("dishes", "dish"), ("buses", "bus"),
    # --- regular: consonant + -ies ---
    ("studies", "study"), ("policies", "policy"), ("entities", "entity"),
]

#: Plurals whose regular reading is the default but which are ALSO an
#: irregular plural of another word: `singularize` gives the regular one and
#: `singular_forms` must offer both, or probe (c) loses one of the two pairs.
AMBIGUOUS_CASES = [("bases", "base", "basis")]

#: Tokens `singularize` must leave alone -- a singular that merely looks
#: plural, or a word too short for a suffix rule to be safe on.  A short
#: singular in `-s` that is NOT in the irregular table ("gas", "bus") still
#: loses its `s`; that is the accepted cost of having no dictionary, and it is
#: symmetric, so both skills group such a token with itself and nothing else.
UNCHANGED = ["gene", "curve", "class", "matrix", "hypothesis", "analysis",
             "index", "leaf", "mouse", "axis", "tie", "is", "as",
             "proof", "safe"]

#: Slug-level cases: `(slug_a, slug_b, probe-c pair?, probe-e permutation?)`.
#: The first row is the pair that went unreported for wiki-lint and reported
#: for wiki-build -- the whole reason this module exists.
SLUG_CASES = [
    ("hypothesis-testing", "testing-hypotheses", False, True),
    ("weight-tying",       "tying-weights",      False, True),
    ("confusion-matrix",   "confusion-matrices", True,  False),
    ("roc-curve",          "roc-curves",         True,  False),
    ("decision-tree",      "decision-trees",     True,  False),
    ("random-forest",      "gradient-boosting",  False, False),
]

# `(slug_a, slug_b, same stem key?)`. The positive pair is the documented gap
# probe (f) exists to catch; the plural pair proves that callers still need to
# prefer the earlier, more specific plural probe when both keys agree.
STEM_CASES = [
    ("masked-language-model", "masked-language-modeling", True),
    ("tokenization", "tokenizer", True),
    ("roc-curve", "roc-curves", True),
    ("random-forest", "gradient-boosting", False),
]


def run_self_test():
    """Run every documented case; return the result dict (no printing).

    Same shape as `naming.run_self_test()` and `slugify.run_self_test()`, so
    `tests/test_conventions.py` consumes all three identically.
    """
    failures, total = [], 0

    for plural, singular in PLURAL_PAIRS:
        total += 1
        got = singularize(plural)
        if got != singular:
            failures.append("singularize(%r) -> %r, expected %r"
                            % (plural, got, singular))
        total += 1
        got = pluralize(singular)
        if got != plural:
            failures.append("pluralize(%r) -> %r, expected %r"
                            % (singular, got, plural))
        # The property a probe actually depends on: the two forms must MEET,
        # whichever of them is the candidate.  Comparing best guesses only
        # worked in one direction, which is how "ROC curves" got a second
        # entry beside roc-curve.md.
        total += 1
        if not (singular_forms(plural) & singular_forms(singular)):
            failures.append("singular_forms(%r) and singular_forms(%r) do not "
                            "intersect" % (plural, singular))

    for plural, regular, irregular in AMBIGUOUS_CASES:
        total += 1
        if singularize(plural) != regular:
            failures.append("singularize(%r) -> %r, expected the regular "
                            "reading %r" % (plural, singularize(plural), regular))
        total += 1
        if not {regular, irregular} <= singular_forms(plural):
            failures.append("singular_forms(%r) -> %r, missing %r or %r"
                            % (plural, sorted(singular_forms(plural)),
                               regular, irregular))

    for word in UNCHANGED:
        total += 1
        if singularize(word) != word:
            failures.append("singularize(%r) -> %r, expected it unchanged"
                            % (word, singularize(word)))

    total += 1
    if singularize("") != "" or pluralize("") != "":
        failures.append("the empty token must survive both directions")

    for a, b, is_plural_pair, is_permutation in SLUG_CASES:
        # probe (c): the two slugs' singular key sets must intersect exactly
        # when they are a plural pair.
        total += 1
        met = bool(singular_keys(a) & singular_keys(b))
        if met != is_plural_pair:
            failures.append("singular_keys(%r) & singular_keys(%r) -> %r, "
                            "expected %r" % (a, b, met, is_plural_pair))
        # probe (e): a permutation must share a singularised token sort AND
        # survive the guard, so the pair lands in exactly one worklist.
        total += 1
        perm = (wordorder_key_singular(a) == wordorder_key_singular(b)
                and real_permutation(a, b))
        if perm != is_permutation:
            failures.append("word-order-singular %r ~ %r -> %r, expected %r"
                            % (a, b, perm, is_permutation))

    for a, b, same_stem in STEM_CASES:
        total += 1
        got = stem_key(a) == stem_key(b)
        if got != same_stem:
            failures.append("stem_key(%r) == stem_key(%r) -> %r, expected %r"
                            % (a, b, got, same_stem))

    for token, expected in (("error", "error"), ("order", "order")):
        total += 1
        if _stem_token(token) != expected:
            failures.append("_stem_token(%r) -> %r, expected %r"
                            % (token, _stem_token(token), expected))

    for singular, expected in (("proof", "proofs"), ("safe", "safes")):
        total += 1
        if pluralize(singular) != expected:
            failures.append("pluralize(%r) -> %r, expected %r"
                            % (singular, pluralize(singular), expected))

    # The head token is the only one probe (c) rewrites: a plural sitting
    # earlier in the slug is part of the qualifier, not the thing named.
    for slug, key in (("confusion-matrices", "confusion-matrix"),
                      ("roc-curves", "roc-curve"),
                      ("analyses-of-variance", "analyses-of-variance")):
        total += 1
        if singular_key(slug) != key:
            failures.append("singular_key(%r) -> %r, expected %r"
                            % (slug, singular_key(slug), key))

    return {
        "total": total,
        "passed": total - len(failures),
        "failed": len(failures),
        "failures": failures,
        "ok": not failures,
    }


def _build_parser():
    p = argparse.ArgumentParser(
        description="The canonical English singulariser (CONVENTIONS.md §9 "
                    "gives whole-vault dedup to one skill; this gives both "
                    "skills one answer).")
    p.add_argument("--test", action="store_true",
                   help="run the self-test and exit")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("singular", help="singularise each WORD (all readings)")
    s.add_argument("words", nargs="+", metavar="WORD")
    pl = sub.add_parser("plural", help="pluralise each WORD")
    pl.add_argument("words", nargs="+", metavar="WORD")
    k = sub.add_parser("key", help="report each SLUG's probe keys")
    k.add_argument("slugs", nargs="+", metavar="SLUG")
    return p


def _configure_stdio():
    """Keep arbitrary words writable through narrow host pipes."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (AttributeError, OSError, ValueError):
                pass


def main(argv=None):
    _configure_stdio()
    args = _build_parser().parse_args(argv)

    if args.test:
        result = run_self_test()
        for f in result["failures"]:
            print("FAIL: " + f, file=sys.stderr)
        print("%d/%d" % (result["passed"], result["total"]))
        return 0 if result["ok"] else 1

    if args.cmd == "singular":
        for word in args.words:
            print("%-24s %-24s all: %s"
                  % (word, singularize(word),
                     ", ".join(sorted(singular_forms(word)))))
        return 0

    if args.cmd == "plural":
        for word in args.words:
            print("%-24s %s" % (word, pluralize(word)))
        return 0

    if args.cmd == "key":
        for slug in args.slugs:
            print("%-28s singular: %-24s word-order-singular: %s"
                  % (slug, singular_key(slug), wordorder_key_singular(slug)))
        return 0

    _build_parser().print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
