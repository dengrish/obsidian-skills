#!/usr/bin/env python3
"""Detect alternate names that wiki prose introduces for its own subject.

The detector is deliberately narrow.  It recognizes an opener-bound
parenthetical and the italicized names a synonym cue directly introduces, then
uses simple grammatical evidence to avoid treating a component's name as an
alias of the entry subject. Semantic ownership and cross-domain safety remain
the executing agent's responsibility.

Stdlib only (apart from sibling shared helpers), Python 3.10+ (the plugin
runtime floor).
"""

import argparse
import os
import re
import sys

# Keep sibling imports working when a harness loads this file directly by path
# rather than running it as a script (where Python supplies this path).
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# The opener's direct parenthetical after the bold title and the lexical
# lead-ins inside it are the same slot and markers item 19 reads, so item-17
# alias evidence uses entry_checks' one copy of each pattern.
from entry_checks import (BOLD_OUTER_RE as _BOLD_OUTER_RE,
                          BOLD_PAREN_RE as _BOLD_PAREN_RE,
                          PAREN_LEADIN_RE as _PAREN_LEADIN_RE,
                          bold_parts as _bold_parts, cross_domain_word)
from entry_structure import math_title_plain_text, sentence_prefix
from plurals import singular_keys
from portable_names import portable_identity
from slugify import SlugError, base_term, has_parenthetical, slug_stem


__all__ = ["introduced_alias_candidates", "missing_introduced_aliases"]


# ``a.k.a.`` sits outside the word-bounded group: a closing ``\b`` cannot
# follow its final dot.
_SYN_CUE_RE = re.compile(
    r"\b(?:also\s+(?:called|known\s+as|termed|named)|known\s+as|short\s+for|"
    r"informally\s+called|sometimes\s+called|or\s+simply|"
    r"referred\s+to\s+as|"
    r"(?:often|commonly|usually)\s+called|"
    r"(?:many\s+)?people\s+call|some\s+call)\b|\ba\.k\.a\.?", re.IGNORECASE)

_NON_NAME_PAREN_RE = re.compile(
    r"^(?:b\.|c\.|d\.|fl\.|r\.|e\.g|i\.e|cf\.|vs\.|see\s|a\s|an\s|the\s|"
    r"annual|ongoing|born\b|died\b|founded\b|established\b|launched\b|"
    r"acquired\b|renamed\b|now\b|figure\s+[A-Za-z0-9])|\d{3,4}",
    re.IGNORECASE)

# A parenthetical that is only italic names joined by a comma, semicolon or
# "or": "(*A*, *B*)", "(also called *A* or the *B*)". Only "or" may take an
# indefinite article: "(*A*, a *B*)" pairs a name with a description.
_PAREN_ITALIC_RE = re.compile(r"\*([^*\n]+)\*")
_PAREN_NAME_LIST_RE = re.compile(
    r"\*[^*\n]+\*(?:\s*(?:[,;]\s+(?:the\s+)?|,?\s+or\s+(?:(?:the|an?)\s+)?)"
    r"\*[^*\n]+\*)*",
    re.IGNORECASE)

_DIRECT_SYNONYM_RE = re.compile(
    r"^\s*(?:(?:the|an?)\s+)?\*([^*\n]{2,60})\*", re.IGNORECASE)

# A further name in the same cue: "also called *A* or the *B*", "or a *B*".
_CHAINED_SYNONYM_RE = re.compile(
    r"\s*,?\s+or\s+(?:(?:the|an?)\s+)?\*([^*\n]{2,60})\*",
    re.IGNORECASE)


def _fold_name(value):
    """Case- and Unicode-normalization-fold a slug or link target."""
    return portable_identity(value or "")


def _parenthetical_names(raw):
    """Return the names a parenthetical gives, lead-ins and emphasis stripped.

    An article is part of the lead-in only after a synonym marker: "(also
    called the *A*)" names *A*, while "(a *B*)" stays a description.
    """
    value = " ".join((raw or "").split())
    names = _PAREN_LEADIN_RE.sub("", value)
    listed = names
    if names != value:
        listed = re.sub(r"^(?:the|an?)\s+", "", names, flags=re.IGNORECASE)
    if _PAREN_NAME_LIST_RE.fullmatch(listed):
        return [name.strip() for name in _PAREN_ITALIC_RE.findall(listed)]
    return [names.replace("*", "").replace("_", "").strip()]


def _opening_block(prose_lines):
    """Return the first contiguous run of non-empty prose lines."""
    block = []
    for line in prose_lines:
        if line.strip():
            block.append(line.strip())
        elif block:
            break
    return " ".join(block)


def _surface_keys(value):
    """Return singular/plural comparison keys for a subject surface."""
    value = re.sub(r"\[\[[^\]|]+\|([^\]]+)\]\]", r"\1", value or "")
    value = re.sub(r"\[\[([^\]]+)\]\]", r"\1", value)
    value = math_title_plain_text(value).strip()
    value = re.sub(r"^(?:the|a|an)\s+", "", value, flags=re.IGNORECASE)
    if not value:
        return set()
    try:
        return singular_keys(_fold_name(slug_stem(value)))
    except SlugError:
        return set()


def _cue_names_subject(prefix, subject_forms):
    """Whether a synonym cue's local grammatical subject is the entry subject."""
    wanted = set()
    for form in subject_forms or ():
        wanted.update(_surface_keys(form))
        if has_parenthetical(form):
            wanted.update(_surface_keys(base_term(form)))
    if subject_forms is None:
        return True
    if not wanted:
        return False

    for bold in _BOLD_OUTER_RE.finditer(prefix):
        visible, _style, _italic = _bold_parts(bold)
        if not (_surface_keys(visible) & wanted):
            continue
        tail = prefix[bold.end():]
        if re.fullmatch(
                r"\s*(?:\([^()\n]{0,80}\))?\s*(?:\$[^$\n]+\$)?\s*"
                r"(?:[,;:—–-]\s*)?(?:which\s*)?", tail,
                re.IGNORECASE):
            return True

    plain = prefix.replace("*", "").replace("_", "")
    plain = re.sub(r"\[\[[^\]|]+\|([^\]]+)\]\]", r"\1", plain)
    plain = re.sub(r"\[\[([^\]]+)\]\]", r"\1", plain).strip()
    if re.search(r"\b(?:it|that\s+it)\s+(?:is|was|has\s+been)\s*$", plain,
                 re.IGNORECASE):
        return True
    if re.search(
            r"\bthis\s+(?:entry|concept|method|algorithm|technique|approach|"
            r"procedure|model|measure|metric|dataset|function|task|regime)\s+"
            r"(?:is|was)\s*$", plain, re.IGNORECASE):
        return True

    copula = re.search(
        r"(?P<subject>[A-Za-z][A-Za-z0-9'’ -]{0,80})\s+"
        r"(?:is|are|was|were|has\s+been|have\s+been)\s*$", plain,
        re.IGNORECASE)
    if copula:
        subject = re.split(r"\b(?:that|and|but)\b", copula.group("subject"),
                           flags=re.IGNORECASE)[-1].strip(" ,;:—–-")
        # A leading consequence connective (", so the logit is") is not part
        # of the subject; a title that contains one ("If-then rule") still is.
        bare = re.sub(r"^(?:so|hence|thus|therefore|then)\s+", "", subject,
                      flags=re.IGNORECASE)
        return bool((_surface_keys(subject) | _surface_keys(bare)) & wanted)
    return False


def introduced_alias_candidates(prose_lines, subject_forms=None):
    """Return ordered ``(name, evidence_kind)`` candidates from body prose.

    ``subject_forms`` should contain the canonical title and any accepted
    aliases.  Passing ``None`` exposes all syntactic candidates for callers
    that deliberately want to inspect them without ownership filtering.
    Callers must pass rendered prose with fenced, indented, and inline code
    already masked; syntax examples are not assertions about the subject.
    """
    prose_lines = list(prose_lines or ())
    if subject_forms is not None:
        subject_forms = tuple(subject_forms)
    prose = "\n".join(prose_lines)
    seen = set()
    out = []

    def add(candidate, where):
        candidate = " ".join(candidate.split()).strip(" ,;:.")
        if not candidate or _NON_NAME_PAREN_RE.match(candidate):
            return
        key = candidate.lower()
        if key not in seen:
            seen.add(key)
            out.append((candidate, where))

    for match in _BOLD_PAREN_RE.finditer(_opening_block(prose_lines)):
        visible, _style, _italic = _bold_parts(match)
        visible = math_title_plain_text(visible)
        if subject_forms is not None:
            wanted = set().union(*(_surface_keys(form) for form in subject_forms))
            if not (_surface_keys(visible) & wanted):
                continue
        for name in _parenthetical_names(match.group("paren")):
            add(name, "opener parenthetical")
    for match in _SYN_CUE_RE.finditer(prose):
        direct = _DIRECT_SYNONYM_RE.match(prose[match.end():])
        if direct and _cue_names_subject(
                sentence_prefix(prose, match.start()), subject_forms):
            add(direct.group(1), "italicized synonym")
            chained = _CHAINED_SYNONYM_RE.match(
                prose, match.end() + direct.end())
            while chained:
                add(chained.group(1), "italicized synonym")
                chained = _CHAINED_SYNONYM_RE.match(prose, chained.end())
    return out


def missing_introduced_aliases(prose_lines, title, aliases, canonical_slug):
    """Return introduced names not covered by the canonical slug or aliases.

    Each result is ``(candidate, evidence_kind, expected_alias_slug)``.  The
    helper applies only mechanical exclusions: equivalence, inflection, and a
    word from the designated cross-domain set (``entry_checks.COMMON_NOUNS``),
    which never becomes an alias. A caller must still judge whether the
    candidate names the same entity and whether another cross-domain alias is
    safe.
    """
    aliases = list(aliases or ())
    title = title or ""
    have = {_fold_name(canonical_slug)}
    for alias in aliases:
        if not alias:
            continue
        have.add(_fold_name(alias))
        try:
            have.add(_fold_name(slug_stem(alias)))
        except SlugError:
            pass
    inflections = set().union(*(singular_keys(form) for form in have))
    subject_forms = [title]
    if has_parenthetical(title):
        subject_forms.append(base_term(title))
    subject_forms.extend(alias for alias in aliases if alias)

    missing = []
    for candidate, where in introduced_alias_candidates(prose_lines, subject_forms):
        try:
            candidate_slug = slug_stem(candidate)
        except SlugError:
            continue
        if (singular_keys(_fold_name(candidate_slug)) & inflections
                or cross_domain_word(candidate)):
            continue
        missing.append((candidate, where, candidate_slug))
    return missing


def run_self_test(verbose=False):
    """Exercise candidate ownership, cleanup, deduplication, and coverage."""
    cases = []

    def add(name, got, expected):
        cases.append((name, got, expected))

    add("opener acronym",
        introduced_alias_candidates(["A **ROC curve** (RC) plots rates."],
                                    ["ROC curve"]),
        [("RC", "opener parenthetical")])
    add("superscript-star math keeps its subject identity",
        introduced_alias_candidates(
            [r"**$\boldsymbol{A}^{*}$ search** (A-star) explores a graph."],
            ["$A^{*}$ search"]),
        [("A-star", "opener parenthetical")])
    add("LaTeX and Unicode chi-squared identify the same subject",
        introduced_alias_candidates(
            [r"**$\chi^2$ test** (chi-square test) compares counts."],
            ["χ² test"]),
        [("chi-square test", "opener parenthetical")])
    add("short-for marker is stripped",
        introduced_alias_candidates(
            ["**AdaBoost** (short for *adaptive boosting*) reweights errors."],
            ["AdaBoost"]),
        [("adaptive boosting", "opener parenthetical")])
    add("originally-called marker is stripped",
        introduced_alias_candidates(
            ["**Boosting** (originally called *hypothesis boosting*) combines models."],
            ["Boosting"]),
        [("hypothesis boosting", "opener parenthetical")])
    add("date parenthetical is excluded",
        introduced_alias_candidates(
            ["**A. M. Turing** (1912–1954) was a mathematician."],
            ["A. M. Turing"]),
        [])
    add("status and exhibit parentheticals are not aliases",
        [introduced_alias_candidates([value], [title]) for title, value in (
            ("Meta", "**Meta** (founded 2015) builds products."),
            ("Facebook", "**Facebook** (now Meta) was renamed."),
            ("Plot", "**Plot** (Figure 1) shows data."),
            ("Turing", "**Turing** (born 1912) worked."))],
        [[], [], [], []])
    add("a date before an Event acronym expansion does not hide the expansion",
        introduced_alias_candidates(
            ["**ILSVRC** (2010–2017) (ImageNet Large Scale Visual "
             "Recognition Challenge) was an annual competition."],
            ["ILSVRC"]),
        [("ImageNet Large Scale Visual Recognition Challenge",
          "opener parenthetical")])
    add("many-people-call cue",
        introduced_alias_candidates(
            ["**Min-max scaling** — which many people call *normalization* — rescales data."],
            ["Min-max scaling"]),
        [("normalization", "italicized synonym")])
    add("cue takes only immediate italic name",
        introduced_alias_candidates(
            ["**ROC curve**, also called *receiver plot*, contrasts *false positives*."],
            ["ROC curve"]),
        [("receiver plot", "italicized synonym")])
    add("a cue introduces every name it chains with or",
        introduced_alias_candidates(
            ["**Normal distribution**, also called the *Gaussian "
             "distribution* or the *bell curve*, is a distribution."],
            ["Normal distribution"]),
        [("Gaussian distribution", "italicized synonym"),
         ("bell curve", "italicized synonym")])
    add("an indefinite article may precede a cued or chained name",
        introduced_alias_candidates(
            ["A **bull put spread**, also known as a *put credit spread* or "
             "a *short put vertical*, sells a put."],
            ["Bull put spread"]),
        [("put credit spread", "italicized synonym"),
         ("short put vertical", "italicized synonym")])
    add("a.k.a. cues a synonym with or without its final dot",
        [introduced_alias_candidates([value], ["Stochastic gradient descent"])
         for value in (
             "**Stochastic gradient descent**, a.k.a. *online gradient "
             "descent*, updates weights.",
             "**Stochastic gradient descent**, a.k.a *online gradient "
             "descent*, updates weights.")],
        [[("online gradient descent", "italicized synonym")]] * 2)
    add("component synonym is excluded",
        introduced_alias_candidates(
            ["A **ROC curve** compares rates. The false positive rate, also "
             "called the *fall-out*, is one axis."],
            ["ROC curve"]),
        [])
    add("explicit pronoun owns synonym",
        introduced_alias_candidates(
            ["**MNIST** is widely studied. It is often called the *hello "
             "world* of machine learning."],
            ["MNIST"]),
        [("hello world", "italicized synonym")])
    add("plural canonical subject owns synonym",
        introduced_alias_candidates(
            ["A **feature** is an input. Features are also called *predictors*."],
            ["Feature (machine learning)"]),
        [("predictors", "italicized synonym")])
    add("singular lead-in and emphasis are stripped",
        introduced_alias_candidates(
            ["**Archaea** (singular, *archaeon*) are prokaryotes."],
            ["Archaea"]),
        [("archaeon", "opener parenthetical")])
    add("an article after a parenthetical lead-in is stripped",
        [introduced_alias_candidates([value], [title]) for title, value in (
            ("Normal distribution", "**Normal distribution** (also called "
             "the *Gaussian distribution*) is common."),
            ("Normal distribution", "**Normal distribution** (also known as "
             "a *bell curve*) is common."),
            ("SGD", "**SGD** (a.k.a. *online gradient descent*) updates "
             "weights."))],
        [[("Gaussian distribution", "opener parenthetical")],
         [("bell curve", "opener parenthetical")],
         [("online gradient descent", "opener parenthetical")]])
    add("an article without a lead-in keeps a parenthetical descriptive",
        introduced_alias_candidates(
            ["**Mus musculus** (a *house mouse*) lives with humans."],
            ["Mus musculus"]),
        [])
    add("several italic names in one parenthetical are separate candidates",
        [introduced_alias_candidates([value], ["Normal distribution"])
         for value in (
             "**Normal distribution** (*Gaussian distribution*, *bell "
             "curve*) is common.",
             "**Normal distribution** (also called the *Gaussian "
             "distribution* or the *bell curve*) is common.")],
        [[("Gaussian distribution", "opener parenthetical"),
          ("bell curve", "opener parenthetical")]] * 2)
    add("only or takes an article in a name list: a comma or semicolon "
        "before an indefinite description never splits it off",
        [[name for name, _how in introduced_alias_candidates([value], ["TNF"])]
         for value in (
             "**TNF** (*tumor necrosis factor*, a *cytokine*) signals.",
             "**TNF** (*tumor necrosis factor*; a *cytokine*) signals.",
             "**TNF** (*tumor necrosis factor*, or a *cachexin*) signals.",
             "**TNF** (*tumor necrosis factor*, the *cachexin*) signals.")],
        [["tumor necrosis factor, a cytokine"],
         ["tumor necrosis factor; a cytokine"],
         ["tumor necrosis factor", "cachexin"],
         ["tumor necrosis factor", "cachexin"]])
    add("scientific abbreviation is retained",
        introduced_alias_candidates(
            ["***Escherichia coli*** (*E. coli*) is a bacterium."],
            ["Escherichia coli"]),
        [("E. coli", "opener parenthetical")])
    add("case-insensitive duplicate candidates are collapsed",
        introduced_alias_candidates(
            ["**MNIST**, also called *benchmark set*, is common. It is also "
             "called *Benchmark set*."],
            ["MNIST"]),
        [("benchmark set", "italicized synonym")])
    add("low-level inspection needs no subject forms",
        introduced_alias_candidates(
            ["A component is also called the *auxiliary unit*."], None),
        [("auxiliary unit", "italicized synonym")])
    add("wrong opener subject is excluded",
        introduced_alias_candidates(
            ["**Related measure** (RM) differs from the subject."], ["Subject"]),
        [])
    add("missing alias returns expected slug",
        missing_introduced_aliases(
            ["A **ROC curve** (receiver plot) shows rates."],
            "ROC curve", [], "roc-curve"),
        [("receiver plot", "opener parenthetical", "receiver-plot")])
    add("existing alias covers introduced name",
        missing_introduced_aliases(
            ["A **ROC curve**, also called *receiver plot*, shows rates."],
            "ROC curve", ["receiver-plot"], "roc-curve"),
        [])
    add("canonical slug covers introduced name",
        missing_introduced_aliases(
            ["**ROC curve** (ROC curve) shows rates."],
            "ROC curve", [], "roc-curve"),
        [])
    add("inflection-equivalent alias covers introduced name",
        missing_introduced_aliases(
            ["A **feature** is an input. Features are also called *predictors*."],
            "Feature", ["predictor"], "feature"),
        [])
    add("a designated cross-domain word is never a missing alias",
        [missing_introduced_aliases([prose], title, [], slug)
         for prose, title, slug in (
             ("A **feature** is an input. Features are also called "
              "*predictors*.", "Feature (machine learning)",
              "feature-machine-learning"),
             ("**Recall**, also called *sensitivity*, finds positives.",
              "Recall (machine learning)", "recall-machine-learning"))],
        [[], []])
    add("a multiword name around a designated word is still a candidate",
        missing_introduced_aliases(
            ["A **label**, also called the *target variable*, is an answer."],
            "Label (machine learning)", [], "label-machine-learning"),
        [("target variable", "italicized synonym", "target-variable")])
    add("an indefinite-article synonym is a missing alias",
        missing_introduced_aliases(
            ["**Mean absolute error**, also called an *average absolute "
             "deviation*, measures error."],
            "Mean absolute error", [], "mean-absolute-error"),
        [("average absolute deviation", "italicized synonym",
          "average-absolute-deviation")])
    add("a listed cross-domain word stays excluded beside a real alias",
        missing_introduced_aliases(
            ["**Recall** (also called *sensitivity* or *true positive rate*) "
             "finds positives."],
            "Recall (machine learning)", [], "recall-machine-learning"),
        [("true positive rate", "opener parenthetical",
          "true-positive-rate")])
    add("a synonym after a so connective names the subject",
        missing_introduced_aliases(
            ["The **logit** of a probability is the log of its odds, so the "
             "logit is also called the *log-odds*."], "Logit", [], "logit"),
        [("log-odds", "italicized synonym", "log-odds")])
    add("a synonym after a hence connective names the subject",
        missing_introduced_aliases(
            ["The **logit** of a probability is the log of its odds, hence the "
             "logit is also called the *log-odds*."], "Logit", [], "logit"),
        [("log-odds", "italicized synonym", "log-odds")])
    add("a connective word inside the title stays part of the subject",
        missing_introduced_aliases(
            ["An **if-then rule** maps a condition to an action; the if-then "
             "rule is also called a *production rule*."], "If-then rule", [],
            "if-then-rule"),
        [("production rule", "italicized synonym", "production-rule")])
    add("irregular singular of a canonical plural is not a missing alias",
        missing_introduced_aliases(
            ["**Archaea** (singular, *archaeon*) are prokaryotes."],
            "Archaea", [], "archaea"),
        [])
    add("irregular plural of a canonical singular is not a missing alias",
        missing_introduced_aliases(
            ["A **cilium** (plural *cilia*) is a hairlike projection."],
            "Cilium", [], "cilium"),
        [])
    add("a listed cross-domain word or phrase is never a missing alias",
        [missing_introduced_aliases([prose], title, [], slug)
         for prose, title, slug in (
             ("**Multicollinearity**, also called *collinearity*, couples "
              "features.", "Multicollinearity", "multicollinearity"),
             ("**Online machine learning**, also called *online learning*, "
              "learns incrementally.", "Online machine learning",
              "online-machine-learning"))],
        [[], []])

    failed = 0
    for name, got, expected in cases:
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
