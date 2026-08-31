#!/usr/bin/env python3
"""Compute a polished note's filename slug: <Author>_<short_topic>_<year>.

Which 2-4 content words identify the topic is a judgment call and stays with
you — pass them in with --topic. What this script owns is the mechanical part
that is easy to get subtly wrong by hand and must come out the same every time:
first-author resolution (comma-flip, suffix and multi-author guards), surname
extraction, Title-Casing with acronym and internal-capital preservation,
punctuation removal, and the image prefix that must match the note stem exactly.

The full rules, with their examples, are in references/filename-slug.md.

CLI
    python3 slug.py --author "Ruxandra Teslo" --topic "Pancreatic Cancer" --year 2026
    python3 slug.py --author "Buck, Carlsmith, and Greenblatt" --topic "AI Takeover" --year 2024
    python3 slug.py --author Smith --author Jones --topic "Synbio Bullish" --year 2024
    python3 slug.py --no-author --topic "LLMs Deep Dive" --year 2025
    python3 slug.py --author "Ruxandra Teslo" --title "Pancreatic cancer just met its match" --year 2026
    python3 slug.py --test          # the reference's own cases, run

    --author    an author name; repeat it for a list, or pass one string holding
                several names ("Buck, Carlsmith, and Greenblatt") — only the
                first author is ever used
    --no-author drop the author segment (no clean human author)
    --topic     the content words you chose, space- or underscore-separated
    --title     derive the topic automatically by dropping filler words. A
                convenience for the easy cases; it marks topic_auto=true in the
                output and you should check the result reads as a topic. Read
                `notes` — it lists exactly which words were kept and dropped.
    --year      4-digit year from the corrected `published` (or `created`)
    --acronym   an extra acronym to uppercase (repeatable, or comma-separated):
                --acronym CRISPR --acronym "EGFR,SNP"

Case in: pass acronyms as they should appear (LLMs, GPT4, OOMs, iPhone, macOS,
PyTorch). Any word already carrying a capital keeps its own casing; a plain
lowercase word is Title-Cased; a lowercase word mixing letters and digits is
uppercased as a unit (gpt4 -> GPT4); and a lowercase word that is a known
acronym is fully uppercased, with a plural `s` left lowercase (llms -> LLMs).
Clipped titles are often sentence-case, so that last rule fires often — but the
built-in list can't know your field's initialisms, so short words that were
merely Title-Cased are listed in `notes` for you to check, and `--acronym` is
how you correct one. Getting this wrong is not cosmetic: the note's stem is
also the `_fig_<N>` image prefix, so renaming the note by hand afterwards
orphans its images.

Two mechanical rules the prose rule leaves out, both because a filename has to
survive them. `+`, `#` and `*` are spelled out rather than dropped (`C++` ->
`CPlusPlus`, `C#` -> `CSharp`, `C*` -> `CStar`), because dropping them collapses
four distinct topics onto `C` — the case CONVENTIONS.md §4a names by name — and
typeset charges fold to ASCII first, so `Ca²⁺` and `Ca2+` are one stem. And the
slug is capped at MAX_SLUG_BYTES: the stem is also the `_fig_<N>` image prefix,
so an uncapped one writes the note and then fails every figure of it with
ENAMETOOLONG. Both trims are reported in `notes`.

Importable
    first_author(names) -> str
    author_kind(name) -> (kind, why)             # person / publication / unsure
    surname(name) -> str
    topic_segment(words) -> str
    build_slug(author=..., topic=..., year=..., no_author=False) -> dict
    run_self_test() -> int                       # also `--test`
    SlugError                                    # degenerate (empty) slug

Output: one JSON object on stdout. Exit 0 normally; 1 when the inputs reduce to
an empty slug (there is no safe filename to return, and a caller joining "" onto
Articles/ would write to the directory itself). Stdlib only.
"""

import argparse
import json
import re
import sys
import unicodedata

# Generational and credential suffixes that are essentially never an ordinary
# surname, so a trailing one can be dropped on sight.
SUFFIXES = {"jr", "jr.", "sr", "sr.", "iii", "iv",
            "phd", "ph.d.", "md", "m.d.", "msc", "bsc", "dphil",
            "esq", "esq.", "mba", "dds"}

# ...and the ones that are BOTH a suffix and an ordinary short surname or a
# lone initial. `ma`, `ba`, `do`, `rn`, `ii` and `v` sat in the set above and
# were dropped on sight, so `--author 'Jack Ma'` produced
# `Jack_Alibaba_Strategy_2024` — the given name as the author segment, with an
# empty `notes` list saying nothing happened. That is the worst shape a slug bug
# takes here: the slug is also the figure-filename prefix (CONVENTIONS §4c, §8b),
# so every image of that clipping is filed under a stem nobody will ever look
# for, and the note reads as correct.
#
# These are only read as a suffix where the writing MARKS them as one:
#   * after a comma — `first_author`'s `Name, Suffix` branch, where the comma is
#     the marker ("Smith, RN" is a credential; "Ma, Jack" is surname-first and
#     still flips);
#   * spelled in capitals inside a name that is not itself all-capitals —
#     `Jane Smith RN`, but not `Jack Ma` (title case) and not `JACK MA` (a
#     shouted byline, which clipped metadata is full of).
# Every other reading is left alone and reported in `notes`, because a kept
# token is visible in the slug while a dropped one is not.
AMBIGUOUS_SUFFIXES = {"ii", "v", "ma", "ba", "do", "rn"}

# "No clean human author" markers — the cases the slug rule says to drop the
# author segment for. Anything else is treated as a person's name.
NON_HUMAN = re.compile(
    r"^(the\s+)?(editorial\s+team|editors?|editorial\s+board|admin(istrator)?|"
    r"anonymous|anon|staff|staff\s+writer|newsletter\s+team|team|guest\s+author|"
    r"contributor|the\s+editors)$", re.IGNORECASE)

# references/filename-slug.md:22 lists "a publication account" alongside those
# markers, and the regex above matches none of them: "Quanta Magazine" slugged to
# the surname `Magazine`, "The Atlantic" to `Atlantic`, "Works in Progress" to
# `Progress` — an invented author, emitted with no note at all. That is worth
# catching because the slug is both the note stem and the figure prefix
# (CONVENTIONS §4c, §8b), so correcting the name by hand afterwards silently
# orphans every figure of that note.
#
# Detection is by masthead SHAPE only — a trailing word no surname is, a leading
# article, a lowercase word that is no name particle. Nothing here guesses whether
# a token "looks like" a person: eating a real person's name is the worse of the
# two failures, so a word that is genuinely both ("Post", "Press") only flags for
# review, and anything unrecognised keeps its author exactly as before.

# Words a masthead ends in that a surname essentially never is. Closed and short
# on purpose — every addition is another chance to eat a real name.
PUBLICATION_TAIL = {
    "magazine", "journal", "times", "review", "news", "newsletter", "media",
    "gazette", "herald", "tribune", "chronicle", "substack", "blog", "podcast",
    "weekly", "daily", "quarterly", "newsroom", "desk", "bureau", "team",
    "editorial", "editors", "staff", "institute", "foundation", "university",
    "lab", "labs", "laboratory", "inc", "ltd", "llc", "plc", "gmbh", "corp",
}

# Both a publication word and a real surname — Emily Post, Bill Press. Too
# two-way to drop on, so these return "unsure": the author is kept and the call
# is handed to the operator in `notes`.
AMBIGUOUS_TAIL = {"post", "press"}

LEADING_ARTICLES = {"the", "a", "an"}

# Nobiliary and patronymic particles, which legitimately sit lowercase inside a
# person's name. Without them the phrase test below would eat "Ludwig van
# Beethoven" and "van der Waals". "of" and "in" are deliberately absent — they
# are what makes "Journal of Medicine" and "Works in Progress" read as phrases.
NAME_PARTICLES = {
    "van", "von", "de", "del", "della", "der", "den", "di", "da", "das", "dos",
    "du", "la", "le", "las", "los", "el", "al", "bin", "ibn", "ben", "bar",
    "ter", "ten", "af", "av", "zu", "y", "e", "mac", "mc", "st", "het", "op",
}

MULTI_SEP = re.compile(r"\s+and\s+|\s*&\s*|\s*;\s*", re.IGNORECASE)

# Articles, prepositions, possessives and rhetorical filler — dropped from a
# title when --title derives the topic automatically.
FILLER = {
    "a", "an", "the", "of", "for", "to", "in", "on", "at", "by", "with", "from",
    "and", "or", "but", "as", "is", "are", "was", "were", "be", "been", "it",
    "its", "it's", "this", "that", "these", "those", "i", "im", "i'm", "we",
    "you", "your", "my", "our", "their", "his", "her", "just", "how", "why",
    "what", "when", "where", "who", "met", "about", "into", "over", "up",
    "out", "so", "very", "really", "new", "s",
}

# Acronyms and initialisms are fully uppercased (filename-slug.md). Only the
# documented set plus initialisms that can't collide with an ordinary English
# word are built in — uppercasing a word that wasn't an acronym is as wrong as
# failing to uppercase one, so anything ambiguous ("it", "who", "all", "car")
# is deliberately absent and belongs on --acronym.
DEFAULT_ACRONYMS = {
    # the seven the prose names, plus GPU from its plural example
    "LLM", "RNA", "AI", "KRAS", "GPT", "AGI", "OOM", "GPU",
    # and initialisms with no lowercase English homograph, so uppercasing them
    # can't misfire. "WHO", "PET", "SEC", "CAR", "IT" and friends are excluded
    # for exactly that reason — reach for --acronym when you need one.
    "ASI", "CPU", "TPU", "NPU", "DNA", "PCR", "CRISPR", "MRI", "RCT", "IVF",
    "API", "URL", "HTTP", "HTTPS", "PDF", "SDK", "CLI", "GUI", "OS",
    "FDA", "NIH", "NASA", "EPA", "IPO", "GDP", "CEO", "CTO", "VC", "ML",
    "NLP", "RL",
}

# Filenames are an allowlist, not a blocklist. `#`, `$`, `&`, `%`, `@` and `+`
# used to survive a blocklist that only named the punctuation someone thought
# of; `#` is the one that breaks things, because `[[C#_And_F#_2020]]` parses in
# Obsidian as a heading anchor, so wiki-builder's `sources:` link to that note
# silently resolves to nothing. Keep letters, digits and `_`; drop everything
# else — hyphens included, per "Smith-Jones -> SmithJones". `isalnum` is
# Unicode-aware on purpose, so an accented surname survives (Müller, not Mller).
#
# These are the symbols that are simply DROPPED. The three below are not.
SYMBOL_CHARS = "$&%@"

# `+`, `#` and `*` are spelled out instead of dropped, because dropping them
# collapses distinct topics onto one filename: `C++`, `C#` and `C*` all reduced
# to `C`, so three notes fought over `C_2026.md` and each overwrote the last —
# the exact case CONVENTIONS.md §4a names by name ("`C`, `C++`, `C#` and `C*`
# produce four distinct slugs, not one"). §4a's own rule is kebab-case and this
# one is Title_Case_Underscored (§4c), so the spelling differs and the fact does
# not: the three symbols are distinguishable after slugging.
#
# The word takes the case of the word it sits in, so `C++` -> `CPlusPlus` and a
# lowercase `c++` -> `cplusplus` -> `Cplusplus`; either way the three stay
# three. `-` is deliberately absent: §4c drops hyphens ("Smith-Jones ->
# SmithJones"), and a charge minus cannot be told from a compound hyphen
# without §4a's machinery, which is a different rule and not this one's to copy.
SYMBOL_WORDS = {"+": "Plus", "#": "Sharp", "*": "Star"}


def _fold_typeset(word):
    """Fold typeset digits and signs to ASCII: `Ca²⁺` and `Ca2+` are one thing.

    Per character and only for the compatibility forms that land on a digit or
    a sign, rather than a blanket NFKC: a full compatibility fold also rewrites
    the micro sign, ligatures and full-width letters, and this rule keeps a
    name's own characters (Müller, not Muller).
    """
    out = []
    for ch in word:
        if ch.isascii():
            out.append(ch)
            continue
        folded = unicodedata.normalize("NFKC", ch)
        out.append(folded if len(folded) == 1 and folded.isascii()
                   and (folded.isdigit() or folded in "+-") else ch)
    return "".join(out)


def _spell_symbols(word):
    """Replace the SYMBOL_WORDS characters with their words, in the word's case.

    Only inside a word that has something else in it. A word that is nothing but
    these characters is decoration, not a name — `***` and `+++` are a rule or an
    emphasis run, and spelling them produces `Starstarstar`, a topic segment out
    of a title that has none. Left alone they empty, which is what raises
    SlugError rather than writing a file named after punctuation.
    """
    if not any(ch in word for ch in SYMBOL_WORDS):
        return word
    if not any(ch.isalnum() for ch in word):
        return word
    cap = any(ch.isupper() for ch in word)
    out = []
    for ch in word:
        spelled = SYMBOL_WORDS.get(ch)
        if spelled is None:
            out.append(ch)
        else:
            out.append(spelled if cap else spelled.lower())
    return "".join(out)


def _strip_punct(word):
    # NFC first: a decomposed "u" + combining diaeresis would otherwise lose the
    # accent (which is not alphanumeric) and silently become a plain "u".
    word = unicodedata.normalize("NFC", word)
    return "".join(ch for ch in word if ch.isalnum() or ch == "_")


def _clean_word(raw):
    """One raw title word, ready to be cased: typeset folded, symbols spelled,
    everything else that is not a letter, a digit or `_` removed."""
    return _strip_punct(_spell_symbols(_fold_typeset(raw)))


class SlugError(ValueError):
    """Raised when the inputs reduce to an empty slug."""


def _suffix_kind(token):
    """``"clear"``, ``"ambiguous"`` or ``None`` for one trailing name token."""
    t = (token or "").strip().lower()
    if not t:
        return None
    bare = t.rstrip(".")
    if t in SUFFIXES or bare in {x.rstrip(".") for x in SUFFIXES}:
        return "clear"
    if t in AMBIGUOUS_SUFFIXES or bare in AMBIGUOUS_SUFFIXES:
        return "ambiguous"
    return None


def _reads_as_credential(token, rest):
    """Is this ambiguous trailing token *written* the way a credential is?

    Credentials are written in capitals (`RN`, `MD`, `II`); surnames are not
    (`Ma`, `Do`, `Ba`). That only means something when the rest of the name
    disagrees, so an all-capitals byline is left alone rather than read as a
    two-letter credential — and a lone initial (`Sid V`) is not enough evidence
    either way, so it is kept and reported.
    """
    letters = [c for c in token if c.isalpha()]
    if len(letters) < 2 or not all(c.isupper() for c in letters):
        return False
    return any(c.islower() for t in rest for c in t)


def first_author(names):
    """Pick the first author out of a list, or out of one mashed-together string.

    A comma flips surname-first order ("Smith, John" -> "John Smith") only when
    it genuinely marks that: not when it separates different people, and not
    when what follows it is a generational or credential suffix.
    """
    notes = []
    if isinstance(names, str):
        names = [names]
    names = [n.strip() for n in names if n and n.strip()]
    if not names:
        return "", ["no author given"]
    if len(names) > 1:
        notes.append("author list: took the first entry")
        names = names[:1]

    s = names[0]
    is_list = bool(MULTI_SEP.search(s)) or s.count(",") > 1
    if is_list:
        # a list of people, not a surname-first name: take the part before the
        # first separator and ignore the rest
        head = MULTI_SEP.split(s)[0]
        head = head.split(",")[0]
        return head.strip(), notes + ["multi-author string: took the portion before the first separator"]

    if s.count(",") == 1:
        before, after = [p.strip() for p in s.split(",")]
        kind = _suffix_kind(after)
        if kind:
            notes.append(f"dropped trailing suffix {after!r} (not surname-first)")
            if kind == "ambiguous":
                notes.append(f"{after!r} is also an ordinary surname — the comma "
                             "is what read it as a suffix here; drop the comma "
                             "if it is the name")
            return before, notes
        if before and after:
            notes.append("surname-first name: flipped to natural order")
            return f"{after} {before}", notes
    return s, notes


def author_kind(name):
    """Classify a resolved author: ``("person" | "publication" | "unsure", why)``.

    ``publication`` is a no-clean-human-author case and the segment is dropped;
    ``unsure`` is kept, because a slug missing an author is a visible gap the
    operator can fix, while a slug carrying an invented surname looks correct and
    is only found once the figures have gone missing. ``why`` is the sentence the
    caller puts in `notes` — every one of these calls is reported, never silent.
    """
    s = " ".join((name or "").split())
    if not s:
        return "person", None
    if NON_HUMAN.match(s):
        return "publication", "an editorial or anonymous byline, not a person"
    toks = s.split()
    tail = _strip_punct(toks[-1]).lower()
    if tail in PUBLICATION_TAIL:
        return "publication", "ends in %r, a publication word" % toks[-1]
    if len(toks) > 1 and toks[0].lower() in LEADING_ARTICLES:
        return "publication", "starts with an article, which a personal name does not"
    # A lowercase word inside an otherwise capitalised name makes it a phrase
    # rather than a name ("Works in Progress"). Particles are the exception, which
    # is why "Ludwig van Beethoven", "van der Waals" and "Gerard 't Hooft" stay
    # people — and one capitalised token is required before the test runs at all,
    # since clipped metadata is often all-lowercase and "ruxandra teslo" is a
    # person, not a masthead. A lowercase prefix before an internal capital,
    # as in d'Ormesson or d’Hondt, is still part of a personal name.
    if len(toks) > 1 and any(t[:1].isupper() for t in toks):
        stray = [t for t in toks
                 if t.islower() and _strip_punct(t).lower() not in NAME_PARTICLES]
        if stray:
            return "publication", ("reads as a phrase, not a personal name (%s)"
                                   % ", ".join(repr(t) for t in stray))
    if tail in AMBIGUOUS_TAIL:
        return "unsure", ("ends in %r, which is both a publication word and a "
                          "real surname" % toks[-1])
    return "person", None


def surname(name, notes=None):
    """Last whitespace-separated token, original case, punctuation removed.

    A trailing generational or credential suffix is dropped — but only one that
    cannot also be a surname. The tokens that can (`AMBIGUOUS_SUFFIXES`) are
    dropped only when they are *written* as a credential, and either way the
    call is recorded in `notes` instead of being applied silently: this function
    picks the author segment, which is also the figure-filename prefix, so a
    wrong answer files a whole clipping's images under a stem nothing looks for.
    """
    toks = [t for t in name.split() if t]
    while len(toks) > 1:
        kind = _suffix_kind(toks[-1])
        if kind == "clear":
            toks.pop()
            continue
        if kind == "ambiguous":
            token, rest = toks[-1], toks[:-1]
            if _reads_as_credential(token, rest):
                if notes is not None:
                    notes.append(
                        f"dropped trailing {token!r}: capitals inside a name "
                        "that is not, so it reads as a credential rather than "
                        f"a surname — pass --author {' '.join(toks)!r} if it "
                        "really is the surname")
                toks.pop()
                continue
            if notes is not None:
                notes.append(
                    f"kept {token!r} as the author segment: it is both an "
                    "ordinary surname and a suffix, and nothing here marks it "
                    "as a suffix — re-run with it removed from --author if it "
                    "is one")
        break
    # a name that is NOTHING but a clear suffix names nobody: better an empty
    # author segment (which `build_slug` reports) than a note called `Jr_…`.
    if len(toks) == 1 and _suffix_kind(toks[0]) == "clear":
        toks = []
    if not toks:
        return ""
    return _strip_punct(toks[-1])


_PLURAL_ACRONYM_RE = re.compile(r"^[a-z]{2,5}s$")
_SHORT_WORD_RE = re.compile(r"^[a-z]{2,5}$")


def _case_word(w, acronyms=None, uncertain=None):
    if not w:
        return w
    acronyms = DEFAULT_ACRONYMS if acronyms is None else acronyms
    if any(c.isupper() for c in w):
        return w                                  # LLMs, iPhone, macOS, PyTorch, GPT4
    if any(c.isdigit() for c in w) and any(c.isalpha() for c in w):
        return w.upper()                          # gpt4 -> GPT4
    if w.upper() in acronyms:
        return w.upper()                          # agi -> AGI
    if _PLURAL_ACRONYM_RE.match(w) and w[:-1].upper() in acronyms:
        return w[:-1].upper() + "s"               # ooms -> OOMs, llms -> LLMs
    if uncertain is not None and _SHORT_WORD_RE.match(w) and w not in FILLER:
        uncertain.append(w)                       # could be an unlisted acronym
    return w[0].upper() + w[1:]                   # plain word -> Title Case


def topic_segment(words, acronyms=None, notes=None):
    """Title-Case the chosen content words and join them with underscores."""
    if isinstance(words, str):
        words = re.split(r"[\s_]+", words)
    out, uncertain, symbol_words, spelled_words, emptied = [], [], [], [], []
    for raw in words:
        raw = raw.strip()
        w = _clean_word(raw)
        if not w:
            if raw:
                emptied.append(raw)
            continue
        if any(ch in raw for ch in SYMBOL_CHARS):
            symbol_words.append(f"{raw} → {w}")
        if any(ch in raw for ch in SYMBOL_WORDS):
            spelled_words.append(f"{raw} → {w}")
        out.append(_case_word(w, acronyms, uncertain))
    if notes is not None:
        if uncertain:
            notes.append(
                "Title-Cased short words that could be unlisted acronyms: "
                + ", ".join(sorted(set(uncertain)))
                + " — re-run with --acronym <WORD> for any that should be "
                  "uppercase")
        if spelled_words:
            notes.append("symbols spelled out: " + "; ".join(spelled_words)
                         + " — dropping them would collapse C++, C# and C* onto "
                           "one filename")
        if symbol_words:
            notes.append("symbols removed from: " + "; ".join(symbol_words)
                         + " — check the words still read distinctly")
        if emptied:
            notes.append("dropped (no filename-safe characters): "
                         + ", ".join(emptied))
    return "_".join(out)


def topic_from_title(title, limit=4, notes=None):
    """Advisory: drop filler words from a title and keep the first few left.

    Deliberately crude — it drops a fixed filler list and keeps word order, so a
    title whose topic isn't simply "its first content words" comes out wrong
    ("Pancreatic cancer just met its match" keeps `Match`). That is why it sets
    topic_auto and why `notes` spells out kept vs dropped: the point is to give
    you something to check, not something to trust. Pass --topic to decide.
    """
    words = [w for w in (_clean_word(x) for x in re.split(r"[\s_]+", title))
             if w]
    kept = [w for w in words if w.lower() not in FILLER]
    dropped = [w for w in words if w.lower() in FILLER]
    over_limit = kept[limit:]
    kept = kept[:limit]
    if notes is not None:
        notes.append("topic from title — kept: "
                     + (", ".join(kept) if kept else "(nothing)"))
        if dropped:
            notes.append("topic from title — dropped as filler: "
                         + ", ".join(dropped))
        if over_limit:
            notes.append(f"topic from title — dropped past --topic-limit "
                         f"{limit}: " + ", ".join(over_limit))
    return kept


def parse_acronyms(values):
    """Fold --acronym values (repeatable, comma-separated) into the default set."""
    acronyms = set(DEFAULT_ACRONYMS)
    for value in values or []:
        for item in re.split(r"[,\s]+", str(value)):
            item = _strip_punct(item.strip())
            if item:
                acronyms.add(item.upper())
    return acronyms


#: The longest slug this rule may produce, in BYTES.
#:
#: The stem is not only the note's name: it is also the `_fig_<N>.<ext>` image
#: prefix (§4c, §8b), so the longest name that has actually has to land on disk is
#: about thirteen bytes longer than the slug. There was no cap at all, and a
#: clipped title that survived as four long words produced a ~250-character
#: slug: `Articles/<slug>.md` fitted (255 is the usual limit), every
#: `<slug>_fig_<N>.png` did not, and the run reported a clean note whose embeds
#: all resolved to nothing — ENAMETOOLONG surfacing as missing figures, one step
#: away from where it happened. 180 leaves room for the longest figure tail
#: (`_fig_999.jpeg`) inside the 200-byte limit pdf-organizer holds every derived
#: basename to (`organize.py`'s MAX_NAME_BYTES), so the two skills agree about
#: what fits.
MAX_SLUG_BYTES = 180


def _byte_len(text):
    return len(text.encode("utf-8"))


def _truncate_bytes(text, limit):
    """`text` cut to at most `limit` bytes, never splitting a character."""
    if limit <= 0:
        return ""
    return text.encode("utf-8")[:limit].decode("utf-8", "ignore")


def _join_segments(author_seg, topic_seg, year_seg):
    return "_".join(s for s in (author_seg, topic_seg, year_seg) if s)


def _fit(author_seg, topic_seg, year_seg, notes=None):
    """Trim the segments until the joined slug fits MAX_SLUG_BYTES.

    The TOPIC gives, from the end, and the author and year are kept whole: those
    two are the note's identity and the topic is already an abbreviation, so
    losing its fourth word costs a shade of meaning while losing the year costs
    the pairing with the source. A single topic word longer than the whole
    budget is cut rather than dropped — a truncated topic still says what the
    note is about, an empty one does not — and only an author segment that
    overflows on its own is cut, which takes garbage metadata to produce.

    Every trim is reported in `notes`: the operator's slug is not what they
    typed, and a silent truncation is how two long titles end up sharing a stem.
    """
    if _byte_len(_join_segments(author_seg, topic_seg, year_seg)) <= MAX_SLUG_BYTES:
        return author_seg, topic_seg
    words = [w for w in topic_seg.split("_") if w]
    dropped = []
    while len(words) > 1 and _byte_len(_join_segments(
            author_seg, "_".join(words), year_seg)) > MAX_SLUG_BYTES:
        dropped.insert(0, words.pop())
    topic_seg = "_".join(words)
    truncated = []
    if _byte_len(_join_segments(author_seg, topic_seg, year_seg)) > MAX_SLUG_BYTES:
        fixed = _byte_len(_join_segments(author_seg, "", year_seg))
        room = MAX_SLUG_BYTES - fixed - (1 if fixed else 0)
        if room > 0:
            truncated.append(topic_seg)
            topic_seg = _truncate_bytes(topic_seg, room).rstrip("_")
        else:
            dropped.extend(words)
            topic_seg = ""
            truncated.append(author_seg)
            room = MAX_SLUG_BYTES - _byte_len(year_seg) - (1 if year_seg else 0)
            author_seg = _truncate_bytes(author_seg, room).rstrip("_")
    if notes is not None:
        notes.append(
            "slug capped at %d bytes — %s. The stem is also the figure prefix, "
            "so an over-long one writes the note and then fails every image "
            "with ENAMETOOLONG. Pass a shorter --topic if this reads badly."
            % (MAX_SLUG_BYTES,
               "; ".join(filter(None, [
                   "dropped " + ", ".join(dropped) if dropped else "",
                   "truncated " + ", ".join(truncated) if truncated else ""]))))
    return author_seg, topic_seg


def build_slug(author=None, topic=None, title=None, year=None, no_author=False,
               topic_limit=4, acronyms=None):
    notes = []
    author_seg = ""
    topic_auto = False

    if not no_author:
        picked, anotes = first_author(author or [])
        notes.extend(anotes)
        kind, why = author_kind(picked)
        if picked and kind == "publication":
            notes.append(f"no clean human author ({picked!r}: {why}) — author segment dropped")
        elif picked:
            if kind == "unsure":
                notes.append(f"kept {picked!r} as the author segment, but it {why} — "
                             f"re-run with --no-author if it is a publication")
            author_seg = surname(picked, notes)
            if not author_seg:
                notes.append("could not resolve a surname — author segment dropped")
    else:
        notes.append("author segment dropped on request")

    if topic:
        words = topic
    elif title:
        notes.append("topic derived from the title automatically — check it reads as a topic")
        words = topic_from_title(title, topic_limit, notes)
        topic_auto = True
    else:
        words = []
    topic_seg = topic_segment(words, acronyms, notes)
    if not topic_seg:
        notes.append("no usable topic words survived — the slug has no topic segment")

    year_seg = ""
    if year:
        m = re.search(r"\d{4}", str(year))
        if m:
            year_seg = m.group(0)
        else:
            notes.append(f"no 4-digit year in {year!r} — year segment dropped")

    author_seg, topic_seg = _fit(author_seg, topic_seg, year_seg, notes)
    slug = _join_segments(author_seg, topic_seg, year_seg)
    slug = unicodedata.normalize("NFC", slug)
    if not slug:
        # Returning "" is worse than failing: os.path.join(cleaned, "") writes to
        # the directory, and image_prefix "" hands fetch_images an empty --slug.
        raise SlugError(
            "author=%r topic=%r title=%r year=%r reduce to an empty slug — "
            "nothing survived punctuation removal. Choose the topic words "
            "yourself with --topic (and a --year) rather than writing a file "
            "named '.md'." % (author, topic, title, year))
    return {
        "author_segment": author_seg,
        "topic_segment": topic_seg,
        "topic_auto": topic_auto,
        "year_segment": year_seg,
        "slug": slug,
        "filename": slug + ".md",
        "image_prefix": slug + "_fig_",
        "ok": True,
        "notes": notes,
    }


def run_self_test():
    """Every case `references/filename-slug.md` ships, plus the shapes that
    break a filename.

    The reference's examples were prose: nothing executed them, so the rule they
    state and the rule this file implements could differ without anything
    noticing. Every author case, every topic case and every combined example
    there is one case here. The rest are the inputs that produce an unusable
    stem — symbol-only words, typeset charges, an empty slug, a name too long
    for the filesystem — because the stem is also the figure prefix, so a slug
    that is wrong or unwritable takes the note's whole image set with it.
    """
    cases = []

    def check(label, got, want):
        cases.append((label, got == want, got, want))

    def slug_of(**kw):
        # SlugError is a result here, not a crash: a suite that dies on the
        # first surprise reports one line instead of the whole picture.
        try:
            return build_slug(**kw)["slug"]
        except SlugError:
            return "SlugError"

    # --- author segment: every case references/filename-slug.md ships -------
    for label, given, want in (
            ("plain name", "Ruxandra Teslo", "Teslo"),
            ("particles: the last token is the surname",
             "Jürgen van der Berg", "Berg"),
            ("surname-first flips", "Smith, John", "Smith"),
            ("a suffix after the comma is not a given name",
             "Martin Luther King, Jr.", "King"),
            ("hyphen dropped, casing kept", "Mary Smith-Jones", "SmithJones"),
            ("`and` list: the first author only", "Teslo and Smith", "Teslo"),
            ("comma list: the first author only",
             "Buck, Carlsmith, and Greenblatt", "Buck"),
            ("`&` list: the first author only", "Smith & Jones", "Smith"),
            ("`;` list: the first author only", "Smith; Jones", "Smith"),
            ("surname-first with particles flips too",
             "van der Berg, Jürgen", "Berg")):
        picked, _why = first_author(given)
        check("author %s (%r)" % (label, given), surname(picked), want)
    # authors normally arrive as a YAML list: the first entry is the first author
    check("author list: the first entry wins",
          surname(first_author(["Ruxandra Teslo", "John Smith"])[0]), "Teslo")
    check("a structured author list still resolves a surname-first first name",
          slug_of(author=["Smith, John", "Jones, Mary"],
                  topic="Cell Signals", year=2026),
          "Smith_Cell_Signals_2026")
    check("a structured author list still drops the first author's comma suffix",
          slug_of(author=["Martin Luther King, Jr.", "Jane Doe"],
                  topic="Civil Rights", year=2026),
          "King_Civil_Rights_2026")
    # the two suffix guards are separate, and each covers what the other does
    # not: the comma one keeps `King, Jr.` from flipping to `Jr. Martin Luther
    # King`, and `surname`'s keeps `Martin Luther King Jr.` — no comma at all —
    # from sluggifying as `Jr`.
    check("a suffix after the comma is dropped, not flipped",
          first_author("Martin Luther King, Jr.")[0], "Martin Luther King")
    for given, want in (("Martin Luther King Jr.", "King"),
                        ("Ruxandra Teslo PhD", "Teslo"),
                        ("John Smith III", "Smith")):
        check("a suffix with no comma is dropped too (%r)" % given,
              surname(given), want)
    check("a name that is nothing but a suffix resolves to no surname",
          surname("Jr."), "")

    # --- a suffix list holding ordinary surnames ----------------------------
    # `ma`, `ba`, `do`, `rn`, `ii` and `v` were in SUFFIXES and dropped on
    # sight, so `--author 'Jack Ma'` slugged as `Jack_…` — the GIVEN name — and
    # `notes` was empty. The slug is the figure-filename prefix (§8b), so the
    # note looked right while its images went under a stem nothing looks for.
    for given, want in (("Jack Ma", "Ma"),
                        ("Yo-Yo Ma", "Ma"),
                        ("Kim Do", "Do"),
                        ("Ibrahima Ba", "Ba"),
                        ("Naosuke Ii", "Ii"),
                        ("Jürgen van der Ma", "Ma")):
        check("a short surname is not a suffix (%r)" % given,
              surname(given), want)
    check("...end to end, the slug carries the surname, not the given name",
          slug_of(author="Jack Ma", topic="Alibaba Strategy", year=2024),
          "Ma_Alibaba_Strategy_2024")
    # ...and it is never silent: a token that is both gets a note either way.
    kept_notes = []
    check("keeping an ambiguous token is reported, not silent",
          (surname("Jack Ma", kept_notes), len(kept_notes)), ("Ma", 1))
    check("...and the note reaches build_slug's output",
          any("Ma" in n for n in build_slug(author="Jack Ma", topic="Alibaba",
                                            year=2024)["notes"]), True)
    check("an unambiguous suffix stays silent, because there is no call to make",
          surname("Ruxandra Teslo PhD", []) and [], [])

    # The credential reading is still available where the writing marks it:
    # capitals inside a name that is not, or a comma.
    for given, want in (("Jane Smith RN", "Smith"),
                        ("John Smith II", "Smith"),
                        ("Ruxandra Teslo MD", "Teslo"),
                        ("W E B Du Bois DDS", "Bois")):
        check("a capitalised credential inside a mixed-case name is dropped (%r)"
              % given, surname(given), want)
    # A LONE INITIAL is not evidence either way — `Martin Luther King V` reads
    # as generational, `Sid V` reads as a stage name, and one capital letter
    # cannot tell them apart. So it is kept (the visible answer) and reported,
    # which is the rule for every call this function cannot make confidently.
    for given in ("Martin Luther King V", "Sid V"):
        lone = []
        check("a lone initial is kept and reported, not guessed (%r)" % given,
              (surname(given, lone), len(lone)), ("V", 1))
    dropped_notes = []
    check("...and that drop is reported too",
          (surname("Jane Smith RN", dropped_notes), len(dropped_notes)),
          ("Smith", 1))
    # a shouted byline is not evidence of a credential — clipped metadata is
    # full of them, and `MA` there is the surname
    check("an all-capitals byline keeps its last token", surname("JACK MA"),
          "MA")
    # a comma is the other marker, and it does not disturb the surname-first flip
    check("a comma marks even an ambiguous suffix",
          surname(first_author("Smith, RN")[0]), "Smith")
    check("...while a surname-first name with a given name still flips",
          surname(first_author("Ma, Jack")[0]), "Ma")
    check("...and the comma-suffix drop says the token is also a surname",
          sum("also an ordinary surname" in n
              for n in first_author("Smith, RN")[1]), 1)
    # "no clean human author" — the four the reference names — drops the segment
    for given in ("Editorial Team", "Anonymous", "Quanta Magazine", ""):
        check("no clean human author (%r) drops the segment" % given,
              build_slug(author=given, topic="Deep Dive",
                         year=2025)["author_segment"], "")
    check("...and the slug is then topic_year",
          slug_of(author="Editorial Team", topic="Deep Dive", year=2025),
          "Deep_Dive_2025")
    for given, want in (("Jean d'Ormesson", "dOrmesson"),
                        ("Victor d’Hondt", "dHondt")):
        check("an attached lowercase name particle keeps its surname (%r)" % given,
              slug_of(author=given, topic="Voting Systems", year=2025),
              want + "_Voting_Systems_2025")
    check("a lowercase phrase word still identifies a publication",
          slug_of(author="Works in Progress", topic="Voting Systems", year=2025),
          "Voting_Systems_2025")

    # --- topic segment: every case the reference ships ----------------------
    for title_words, want in (
            ("Pancreatic Cancer", "Pancreatic_Cancer"),
            ("LLMs Deep Dive", "LLMs_Deep_Dive"),
            ("llms deep dive", "LLMs_Deep_Dive"),      # sentence-case clipping
            ("Synbio Bullish", "Synbio_Bullish"),
            ("Transformer Genomics", "Transformer_Genomics"),
            ("GPT-4 AGI OOMs", "GPT4_AGI_OOMs"),
            ("gpt4 agi ooms", "GPT4_AGI_OOMs"),
            ("Intelligence Explosion", "Intelligence_Explosion"),
            ("Start Google", "Start_Google"),
            # a word carrying an internal capital keeps its own casing
            ("iPhone macOS PyTorch eLife", "iPhone_macOS_PyTorch_eLife")):
        check("topic %r" % title_words, topic_segment(title_words), want)
    # "Other punctuation is removed, not replaced": the words either side of an
    # em-dash join, they do not become two words or gain a separator.
    check("punctuation is removed, not replaced",
          topic_segment("What's Next: AI—Now?"), "Whats_Next_AINow")
    # the one reference title whose topic really is "its first content words",
    # so the --title convenience gets it right
    check("--title derivation, filler dropped",
          slug_of(title="How to start Google", no_author=True, year=2025),
          "Start_Google_2025")
    # ...and the one it deliberately gets wrong, which is why it is advisory
    check("--title derivation keeps a word a human would drop",
          slug_of(title="Pancreatic cancer just met its match",
                  no_author=True, year=2026), "Pancreatic_Cancer_Match_2026")
    # 2-4 content words: the fifth is dropped, and the drop is reported rather
    # than leaving the operator to notice their topic lost a word
    _long = "How deep learning transforms protein structure prediction accuracy"
    _r = build_slug(title=_long, no_author=True, year=2025)
    check("--title keeps at most --topic-limit words",
          _r["slug"], "Deep_Learning_Transforms_Protein_2025")
    check("...and says which words it dropped past the limit",
          any("past --topic-limit" in n for n in _r["notes"]), True)
    check("--topic-limit is honoured",
          slug_of(title=_long, no_author=True, year=2025, topic_limit=2),
          "Deep_Learning_2025")

    # --- the three combined worked examples --------------------------------
    check("combined: Teslo 2026",
          build_slug(author="Ruxandra Teslo", topic="Pancreatic Cancer",
                     year=2026)["filename"],
          "Teslo_Pancreatic_Cancer_2026.md")
    check("combined: anonymous editorial 2025",
          build_slug(author="Anonymous", topic="LLMs Deep Dive",
                     year=2025)["filename"], "LLMs_Deep_Dive_2025.md")
    check("combined: first author only, 2024",
          build_slug(author="Smith & Jones", topic="Synbio Bullish",
                     year=2024)["filename"], "Smith_Synbio_Bullish_2024.md")
    # the image prefix IS the stem: a divergence orphans every figure
    built = build_slug(author="Ruxandra Teslo", topic="Pancreatic Cancer",
                       year=2026)
    check("image prefix is the stem plus _fig_",
          built["image_prefix"], built["slug"] + "_fig_")

    # --- symbols that used to collapse onto one slug ------------------------
    # CONVENTIONS.md §4a names this case: C, C++, C# and C* are four things.
    # They were four titles reducing to `C`, so three of the four notes fought
    # over one filename and each overwrote the last.
    for topic, want in (("C", "C"), ("C++", "CPlusPlus"), ("C#", "CSharp"),
                        ("C* Search", "CStar_Search"), ("F#", "FSharp"),
                        ("A* Pathfinding", "AStar_Pathfinding"),
                        ("c++", "Cplusplus")):
        check("symbol topic %r" % topic, topic_segment(topic), want)
    check("the four C slugs are four",
          len({topic_segment(t) for t in ("C", "C++", "C#", "C*")}), 4)
    # a symbol that is still dropped is still reported
    _n = []
    check("dropped symbols are reported", bool(topic_segment("R&D Spend", None, _n)
                                               and _n), True)
    check("...and the word survives", topic_segment("R&D Spend"), "RD_Spend")
    # typeset charges fold to their ASCII spelling: `Ca²⁺` and `Ca2+` are one
    # thing written two ways and must not produce two stems
    check("typeset charge", topic_segment("Ca²⁺ Signalling"),
          "Ca2Plus_Signalling")
    check("ASCII charge agrees", topic_segment("Ca2+ Signalling"),
          "Ca2Plus_Signalling")
    check("a subscript folds too", topic_segment("H₂O Transport"),
          "H2O_Transport")

    # --- alphabets and characters that are not ASCII ------------------------
    # Greek capitals are letters: they survive, they are not Title-Cased away,
    # and a hyphen inside the word is dropped like any other.
    for topic, want in (("ΔG Estimation", "ΔG_Estimation"),
                        ("Σ-Algebra", "ΣAlgebra"),
                        ("Ω Notation", "Ω_Notation"),
                        ("Α-Helix Folding", "ΑHelix_Folding")):
        check("Greek capital %r" % topic, topic_segment(topic), want)
    # CJK and Arabic are alphanumeric, so they survive rather than emptying the
    # slug. (§4a's kebab rule raises on these; this is the §4c rule, whose
    # output is a note filename and may carry the user's own script.)
    check("CJK survives", topic_segment("機械学習"), "機械学習")
    check("Arabic survives", topic_segment("التعلم الآلي"), "التعلم_الآلي")
    check("an accented surname keeps its accent",
          surname("Jürgen Müller"), "Müller")
    # an emoji is not alphanumeric: it is dropped, and the drop is reported
    _n = []
    check("emoji dropped", topic_segment("🚀 Launch Costs", None, _n),
          "Launch_Costs")
    check("...and reported", any("dropped" in m for m in _n), True)
    check("an emoji-only topic empties",
          topic_segment("🚀🔥"), "")

    # --- the degenerate slug ------------------------------------------------
    # Returning "" is worse than failing: os.path.join(cleaned, "") writes to
    # the directory itself and image_prefix "" hands fetch_images an empty slug.
    for label, kw in (
            ("all-punctuation topic", dict(topic="--- *** ???", no_author=True)),
            ("all-punctuation topic and author",
             dict(author="!!!", topic="???")),
            ("nothing at all", dict(no_author=True))):
        try:
            got = build_slug(**kw)["slug"]
        except SlugError:
            got = "SlugError"
        check("%s raises rather than returning an empty slug" % label,
              got, "SlugError")
    # ...but a year alone is a filename, so it is not degenerate
    check("a year survives an emptied topic",
          slug_of(topic="***", no_author=True, year=2026), "2026")

    # --- the length cap -----------------------------------------------------
    long_word = "Supercalifragilistic" * 15                  # 300 chars
    res = build_slug(author="Teslo", topic=long_word, year=2026)
    check("an over-long single topic word is cut to the cap",
          _byte_len(res["slug"]) <= MAX_SLUG_BYTES, True)
    check("...and the year survives it", res["slug"].endswith("_2026"), True)
    check("...and the author survives it", res["slug"].startswith("Teslo_"), True)
    check("...and the truncation is reported",
          any("capped" in n for n in res["notes"]), True)
    # Four fifty-character words: three fit beside the author and the year, the
    # fourth does not. The topic gives from the END, so the slug is pinned
    # exactly — a cap that dropped from the front would keep the wrong words and
    # a cap that dropped the year would lose the pairing with the source.
    _w = ["Alpha" + "x" * 45, "Bravo" + "y" * 45, "Charlie" + "z" * 43]
    res = build_slug(author="Teslo", topic=" ".join(_w + ["Delta" + "q" * 45]),
                     year=2026)
    check("over-long topic words are dropped whole, from the end",
          res["slug"], "Teslo_" + "_".join(_w) + "_2026")
    check("...and the drop is reported by name",
          any("Delta" in n for n in res["notes"]), True)
    check("the figure prefix fits a real filesystem name too",
          len((res["image_prefix"] + "999.jpeg").encode("utf-8")) <= 200, True)
    # a slug that already fits is untouched — the cap must not round-trip
    check("a short slug is left exactly alone",
          slug_of(author="Teslo", topic="Pancreatic Cancer", year=2026),
          "Teslo_Pancreatic_Cancer_2026")
    # multi-byte characters are counted in bytes, and never cut in half
    res = build_slug(no_author=True, topic="機" * 200, year=2026)
    check("a multi-byte topic is capped in bytes",
          _byte_len(res["slug"]) <= MAX_SLUG_BYTES, True)
    check("...without splitting a character",
          res["slug"] == unicodedata.normalize("NFC", res["slug"])
          and "�" not in res["slug"], True)

    # --- year segment -------------------------------------------------------
    check("a year is found inside a date",
          slug_of(no_author=True, topic="Deep Dive", year="2025-03-04"),
          "Deep_Dive_2025")
    _r = build_slug(no_author=True, topic="Deep Dive", year="undated")
    check("an unparseable year is dropped and reported",
          (_r["slug"], any("year" in n for n in _r["notes"])),
          ("Deep_Dive", True))

    # --- the reference's own examples have to be reproducible from it --------
    # references/filename-slug.md said "a one-author, plain-English title needs
    # nothing beyond the script", which reads as `--title`. Seven of its eight
    # examples do not come out of `--title` — it drops a filler list and keeps
    # the first few words left, so "Pancreatic cancer just met its match" keeps
    # `Match`. The slug is the image-filename prefix, so the two paths file one
    # clipping's figures under two stems. `--topic` is the documented path and
    # reproduces every example; these cases pin both halves of that.
    _doc_examples = (
        ("Pancreatic cancer just met its match", "Pancreatic Cancer",
         "Pancreatic_Cancer"),
        ("How LLMs work: a deep dive", "LLMs Deep Dive", "LLMs_Deep_Dive"),
        ("Why I'm bullish on synbio", "Synbio Bullish", "Synbio_Bullish"),
        ("A new transformer architecture for genomics",
         "Transformer Genomics", "Transformer_Genomics"),
        ("From GPT-4 to AGI: counting the OOMs", "GPT-4 AGI OOMs",
         "GPT4_AGI_OOMs"),
        ("From AGI to superintelligence: the intelligence explosion",
         "Intelligence Explosion", "Intelligence_Explosion"),
        ("How to start Google", "Start Google", "Start_Google"))
    for title, topic, want in _doc_examples:
        check("--topic reproduces the documented example %r" % want,
              build_slug(topic=topic, year=2026)["topic_segment"], want)
    off = [want for title, _topic, want in _doc_examples
           if build_slug(title=title, year=2026)["topic_segment"] != want]
    check("...while --title does not, which is why it is advisory",
          len(off) >= 6, True)
    _t = build_slug(title="Pancreatic cancer just met its match", year=2026)
    check("a --title run marks itself automatic", _t["topic_auto"], True)
    check("...and says in notes what it kept, so it can be checked",
          any("kept" in n for n in _t["notes"]), True)
    check("a --topic run claims nothing automatic",
          build_slug(topic="Pancreatic Cancer", year=2026)["topic_auto"], False)

    # ...and the reference must not tell the reader otherwise. `os` is imported
    # here rather than at module scope: nothing in the slug rule itself touches
    # the filesystem, and it should stay that way.
    import os
    _ref = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "references",
        "filename-slug.md"))
    try:
        with open(_ref, encoding="utf-8") as _fh:
            _md = _fh.read()
    except OSError as _exc:
        _md = ""
        cases.append(("references/filename-slug.md sits next to this script",
                      False, "%s: %s" % (type(_exc).__name__, _exc),
                      "readable"))
    check("the reference no longer says the script alone is enough",
          "needs nothing beyond the script" in _md, False)
    check("...and names --topic as the documented path",
          bool(re.search(r"`--topic` example.{0,80}documented path|"
                         r"--topic.{0,60}documented path", _md)), True)
    check("...and warns that --title is a suggestion to check",
          bool(re.search(r"suggestion to check", _md)), True)

    failed = [c for c in cases if not c[1]]
    for label, ok, got, want in cases:
        if not ok:
            print("FAIL  %s\n        got  %r\n        want %r"
                  % (label, got, want))
    print("%d/%d self-test cases pass" % (len(cases) - len(failed), len(cases)))
    return 1 if failed else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--author", action="append", default=[])
    ap.add_argument("--no-author", action="store_true")
    ap.add_argument("--topic")
    ap.add_argument("--title")
    ap.add_argument("--year")
    ap.add_argument("--topic-limit", type=int, default=4)
    ap.add_argument("--acronym", action="append", default=[],
                    help="extra acronym to uppercase; repeatable or comma-separated")
    ap.add_argument("--test", action="store_true", help="run the self-test")
    args = ap.parse_args(argv)

    if args.test:
        return run_self_test()

    if not args.topic and not args.title:
        ap.error("give --topic (preferred) or --title")

    try:
        result = build_slug(author=args.author, topic=args.topic,
                            title=args.title, year=args.year,
                            no_author=args.no_author,
                            topic_limit=args.topic_limit,
                            acronyms=parse_acronyms(args.acronym))
    except SlugError as exc:
        print(json.dumps({"slug": None, "filename": None, "image_prefix": None,
                          "ok": False, "error": str(exc)},
                         indent=2, ensure_ascii=False))
        return 1

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
