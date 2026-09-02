#!/usr/bin/env python3
"""Shared organism-name parsing for wiki-builder and wiki-linter.

The helpers here provide a conservative mechanical floor.  They distinguish
scientific, common, and ambiguous Organism titles only when local text supplies
enough evidence; ambiguous typography remains a source-aware model judgment.

Stdlib only, Python 3.8+.
"""

import argparse
import re

__all__ = [
    "bound_common_names",
    "first_sentence",
    "organism_title_classification",
    "scientific_abbreviation_matches",
    "taxon_title_parts",
]


_INITIAL_RE = re.compile(r"(?:^|[\s(\[])[A-Z]\.$")
_ABBREVS = (
    "al", "approx", "ca", "cf", "dept", "dr", "e.g", "ed", "eds",
    "et al", "etc", "fig", "figs", "i.e", "inc", "jr", "no", "nos",
    "prof", "rev", "sr", "ssp", "st", "subsp", "trans", "var", "vs",
)
_ABBREV_RE = re.compile(
    r"(?:^|\b)(?:" + "|".join(re.escape(x) for x in _ABBREVS) + r")\.$",
    re.IGNORECASE,
)
_LATIN_TAXON_RE = re.compile(
    r"^(?P<taxon>(?P<genus>(?:[A-Z][a-z]+|[A-Z]\.))\s+"
    r"(?P<species>[a-z][A-Za-z.-]*)"
    r"(?:\s+(?P<infra>(?!(?:strain|isolate|serovar|serotype|subtype|"
    r"biovar|pathovar|cultivar|pathotype|biotype)\b)"
    r"[a-z][A-Za-z.-]*))?)(?P<suffix>(?:\s+.*)?)$")
_RANK_MARKER_RE = re.compile(
    r"\s(?:subsp|subspecies|ssp|var|variety|subvar|forma|fo|f|cv|sp|spp|"
    r"cf|aff)\.?(?=\s|$)", re.IGNORECASE)
_GENUS_SHAPE_RE = re.compile(r"^[A-Z][a-z]{2,}$")

# Python's ``re`` treats ``[^\W\d_]`` as a Unicode letter.  Keep this pattern
# shared by the common-name capture and comparison paths so names such as
# ``coquí`` are not truncated at their first non-ASCII character.
_COMMON_NAME_WORD = r"[^\W\d_](?:[^\W\d_]|['’-])*"
_COMMON_NAME_WORD_RE = re.compile(_COMMON_NAME_WORD)

# These words may begin with a capital at the start of a title but name a
# common group or organism.  Their shape alone must never prove Latin status.
_COMMON_TAXON_GROUP_WORDS = {
    "archaea", "archaeon", "archaeons", "bacteria", "bacterium",
    "bacteriums", "dog", "dogs", "elephant", "elephants", "fish",
    "flies", "fly", "fungi", "fungus", "mouse", "mice", "protozoa",
    "protozoan", "protozoans", "rat", "rats", "virus", "viruses",
    "weed", "weeds", "wolf", "wolves", "worm", "worms", "yeast",
    "yeasts",
}
_COMMON_ORGANISM_HEADS = {
    "archaeon", "bacterium", "dog", "elephant", "fish", "fly", "fungus",
    "mouse", "protozoan", "rat", "virus", "weed", "wolf", "worm", "yeast",
}

# The title-bound parenthetical form used by both skills.  It accepts ordinary
# outer bold, triple emphasis, and mixed taxon/suffix emphasis.  Matching only
# this immediate slot prevents an unrelated italic species later in the first
# sentence from proving the title scientific.
_BOLD_PAREN_RE = re.compile(
    r"(?<!\*)\*\*(?P<bold>(?:\$[^$\n]+\$|\*[^*\n]+\*|[^*\n])+?)"
    r"\*\*(?!\*)(?:\s+algorithm)?\s*"
    r"\((?P<paren>[A-Za-z*][^()\n]{0,59})\)",
    re.IGNORECASE,
)


def first_sentence(text):
    """Return the first sentence while preserving initials/abbreviations."""
    compact = " ".join((text or "").split())
    for match in re.finditer(r"[.!?]+", compact):
        following = compact[match.end():match.end() + 1]
        if following and not following.isspace():
            continue
        if match.group(0) == ".":
            head = compact[max(0, match.end() - 16):match.end()]
            # Markdown emphasis may sit immediately around a scientific
            # initial (``(*E. coli*)``).  It is presentation, not part of the
            # token the sentence-boundary test is trying to recognize.
            head_plain = head.replace("*", "").replace("_", "")
            if _INITIAL_RE.search(head_plain) or _ABBREV_RE.search(head_plain):
                continue
        return compact[:match.end()]
    return compact


def _plain_markup(text):
    value = re.sub(r"\[\[[^\]|]+\|([^\]]+)\]\]", r"\1", text or "")
    value = re.sub(r"\[\[([^\]]+)\]\]", r"\1", value)
    return " ".join(value.replace("*", "").replace("_", "").split())


def _first_letter_ci_equal(a, b):
    if a is None or b is None or len(a) != len(b):
        return False
    return not a or (a[0].lower() == b[0].lower() and a[1:] == b[1:])


def scientific_abbreviation_matches(name, taxon):
    """Whether ``name`` is a true one-letter-genus abbreviation of ``taxon``."""
    name_words = re.findall(r"[A-Za-z]+", (name or "").replace("-", " "))
    taxon_words = re.findall(r"[A-Za-z]+", taxon or "")
    if len(name_words) < 2 or len(name_words) != len(taxon_words):
        return False
    return (
        len(name_words[0]) == 1
        and name_words[0].casefold() == taxon_words[0][:1].casefold()
        and [word.casefold() for word in name_words[1:]]
        == [word.casefold() for word in taxon_words[1:]]
    )


def taxon_title_parts(title):
    """Return a Latin binomial/trinomial core and plain suffix, or ``None``.

    Rank-marked names are intentionally excluded because their typography can
    be discontiguous (for example ``*Brassica oleracea* var. *capitata*``).
    """
    raw = (title or "").strip()
    if _RANK_MARKER_RE.search(raw):
        return None
    match = _LATIN_TAXON_RE.fullmatch(raw)
    if not match or match.group("species").casefold() in _COMMON_TAXON_GROUP_WORDS:
        return None
    return match.group("taxon"), match.group("suffix")


def bound_common_names(title, description, opening):
    """Common names directly bound to an Organism's canonical title.

    Explicit ``called``/``known as`` cues may introduce an uncommon name.  A
    weak ``is the`` or appositive cue is accepted only when its complete phrase
    ends in a recognized organism head and does not repeat a title word.  An
    optional parenthetical between title and equation must be the matching
    scientific abbreviation; an arbitrary aside cannot establish the binding.
    """
    title = (title or "").strip()
    if not title:
        return []
    word = _COMMON_NAME_WORD
    label = rf"(?P<label>{word}(?:\s+{word}){{0,3}}?)"
    subject = (
        rf"(?<!\w){re.escape(title)}"
        rf"(?:\s+\((?P<subject_paren>[^()\n]{{1,60}})\))?"
    )
    boundary = rf"(?=\s*(?:[,.;:—–]|$|\b(?:used|adopted|that|which|whose)\b))"
    patterns = [
        (True, re.compile(
            rf"{subject}\s+(?:is|are|was|were)\s+"
            rf"(?:(?:commonly|usually)\s+)?(?:called|known\s+as)\s+"
            rf"(?:(?:the|an?)\s+)?{label}{boundary}", re.IGNORECASE)),
        (True, re.compile(
            rf"{subject}\s*,\s*(?:(?:commonly|usually)\s+)?"
            rf"(?:called|known\s+as)\s+(?:(?:the|an?)\s+)?{label}"
            rf"(?=\s*[,;:—–])", re.IGNORECASE)),
        (False, re.compile(
            rf"{subject}\s+(?:is|are|was|were)\s+the\s+{label}{boundary}",
            re.IGNORECASE)),
        (False, re.compile(
            rf"{subject}\s*,\s*(?:the\s+)?{label}(?=\s*[,;:—–])",
            re.IGNORECASE)),
    ]
    found = []
    title_words = {
        item.casefold() for item in _COMMON_NAME_WORD_RE.findall(title)
    }
    for raw in (description, first_sentence(opening)):
        plain = _plain_markup(raw)
        for explicit, pattern in patterns:
            for match in pattern.finditer(plain):
                parenthetical = match.groupdict().get("subject_paren")
                if parenthetical and not scientific_abbreviation_matches(
                        parenthetical, title):
                    continue
                name = match.group("label").strip()
                words = [
                    item.casefold() for item in _COMMON_NAME_WORD_RE.findall(name)
                ]
                if not explicit and not (
                    words
                    and words[-1] in _COMMON_ORGANISM_HEADS
                    and not title_words.intersection(words)
                ):
                    continue
                if name and name.casefold() not in {item.casefold() for item in found}:
                    found.append(name)
    return found


def _title_bound_abbreviation(title, taxon, opening):
    for match in _BOLD_PAREN_RE.finditer(first_sentence(opening)):
        visible = _plain_markup(match.group("bold"))
        if not _first_letter_ci_equal(visible, title):
            continue
        candidate = _plain_markup(match.group("paren"))
        if scientific_abbreviation_matches(candidate, taxon):
            return True
    return False


def organism_title_classification(title, aliases=(), opening=""):
    """Return ``(scientific|common|ambiguous, taxon_parts_or_none)``.

    Scientific status requires evidence independent of the title's current
    emphasis: an abbreviated-genus title, a matching scientific-abbreviation
    alias, or an immediate title-bound abbreviation.  A common-name equation
    proves only that two names denote the same organism; it cannot prove that
    either name is Latin.  Merely Latin-looking, rank-marked, and genus-only
    titles remain ambiguous. Ambiguity is not a lint error; the executing agent
    checks the source and chooses the appropriate typography.
    """
    raw = (title or "").strip()
    if not raw:
        return "common", None
    if _RANK_MARKER_RE.search(raw):
        return "ambiguous", None

    parts = taxon_title_parts(raw)
    if parts:
        taxon, _suffix = parts
        if re.match(r"^[A-Z]\.\s", taxon):
            return "scientific", parts
        if any(scientific_abbreviation_matches(alias, taxon)
               for alias in (aliases or ())):
            return "scientific", parts
        if _title_bound_abbreviation(raw, taxon, opening):
            return "scientific", parts
        return "ambiguous", parts

    if (_GENUS_SHAPE_RE.fullmatch(raw)
            and raw.casefold() not in _COMMON_TAXON_GROUP_WORDS):
        return "ambiguous", None
    return "common", None


def _self_test():
    cases = [
        ("binomial with suffix", taxon_title_parts("E. coli K-12"),
         ("E. coli", " K-12")),
        ("rank-marked title stays source-aware",
         organism_title_classification("Brassica oleracea var. capitata")[0],
         "ambiguous"),
        ("common two-word title is common",
         organism_title_classification("African elephant")[0], "common"),
        ("abbreviated-genus title is scientific",
         organism_title_classification("E. coli K-12")[0], "scientific"),
        ("matching slug alias proves the full taxon",
         organism_title_classification("Caenorhabditis elegans", ["c-elegans"])[0],
         "scientific"),
        ("genus-only alias does not prove a species",
         organism_title_classification("Drosophila melanogaster", ["drosophila"])[0],
         "ambiguous"),
        ("title-bound triple-emphasis abbreviation proves the taxon",
         organism_title_classification(
             "Escherichia coli", opening="***Escherichia coli*** (*E. coli*) is a bacterium.")[0],
         "scientific"),
        ("an incidental italic taxon does not prove the title",
         organism_title_classification(
             "Pan troglodytes", opening="**Pan troglodytes** differs from *H. sapiens*.")[0],
         "ambiguous"),
        ("a common-name equation does not prove a taxon-shaped title Latin",
         organism_title_classification(
             "Mus musculus", opening="**Mus musculus** is the mouse used in genetics.")[0],
         "ambiguous"),
        ("evidence-poor genus stays source-aware",
         organism_title_classification("Didinium")[0], "ambiguous"),
        ("even direct genus prose stays source-aware",
         organism_title_classification(
             "Didinium", opening="**Didinium** is a genus of predatory ciliates.")[0],
         "ambiguous"),
        ("negated genus prose cannot prove a genus title",
         organism_title_classification(
             "Didinium", opening="**Didinium** is not a genus in this usage.")[0],
         "ambiguous"),
        ("incidental genus prose cannot prove a genus title",
         organism_title_classification(
             "Didinium", opening="**Didinium** is often confused with a genus name.")[0],
         "ambiguous"),
        ("common group title remains common",
         organism_title_classification("Bacteria")[0], "common"),
        ("common-name equations do not turn common-looking titles into Latin taxa",
         organism_title_classification(
             "Silver carp", opening="**Silver carp** is known as the Asian carp.")[0],
         "ambiguous"),
        ("another common-name equation remains non-scientific at the floor",
         organism_title_classification(
             "Dwarf hamster", opening="**Dwarf hamster** is called the Russian hamster.")[0],
         "ambiguous"),
        ("complete common-name phrase is preserved",
         bound_common_names(
             "Pan troglodytes", "Pan troglodytes is known as the common chimpanzee.", ""),
         ["common chimpanzee"]),
        ("explicit copular binding needs no article",
         bound_common_names(
             "Pan troglodytes", "Pan troglodytes is called chimpanzee.", ""),
         ["chimpanzee"]),
        ("explicit appositive binding needs no article",
         bound_common_names(
             "Pan troglodytes", "",
             "**Pan troglodytes**, known as common chimpanzee, is a great ape."),
         ["common chimpanzee"]),
        ("matching scientific parenthetical permits an equation",
         bound_common_names(
             "Schizosaccharomyces pombe", "",
             "***Schizosaccharomyces pombe*** (S. pombe), known as the fission yeast, divides by fission."),
         ["fission yeast"]),
        ("arbitrary parenthetical cannot establish an equation",
         bound_common_names(
             "Schizosaccharomyces pombe", "",
             "***Schizosaccharomyces pombe*** (laboratory strain), known as the fission yeast, divides by fission."),
         []),
        ("descriptive complement is not mistaken for a name",
         bound_common_names(
             "Mus musculus", "Mus musculus is the standard model organism used in genetics.", ""),
         []),
        ("explicit binding preserves a Unicode common name",
         bound_common_names(
             "Eleutherodactylus coqui",
             "Eleutherodactylus coqui is commonly called the coquí.", ""),
         ["coquí"]),
        ("variety abbreviation does not end the first sentence",
         first_sentence(
             "Brassica oleracea var. capitata is cultivated. It forms dense heads."),
         "Brassica oleracea var. capitata is cultivated."),
        ("subspecies abbreviation does not end the first sentence",
         first_sentence(
             "Pan troglodytes subsp. verus inhabits West Africa. It is endangered."),
         "Pan troglodytes subsp. verus inhabits West Africa."),
        ("ssp abbreviation does not end the first sentence",
         first_sentence(
             "Pan troglodytes ssp. verus inhabits West Africa. It is endangered."),
         "Pan troglodytes ssp. verus inhabits West Africa."),
    ]
    bad = [(name, got, want) for name, got, want in cases if got != want]
    for name, got, want in bad:
        print("FAIL %s: got %r, want %r" % (name, got, want))
    print("%d/%d organism-name self-test cases pass" % (len(cases) - len(bad), len(cases)))
    return not bad


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true", help="run the self-test")
    args = parser.parse_args(argv)
    if not args.test:
        parser.error("use --test")
    return 0 if _self_test() else 1


if __name__ == "__main__":
    raise SystemExit(main())
