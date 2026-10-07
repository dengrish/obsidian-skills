#!/usr/bin/env python3
"""Mechanical checks and region-scoped list repairs for a clipping draft.

Every check here finds *candidates*: a match is a place to inspect against the
source, never permission to rewrite. The rules that decide what a match means
are in references/review-checklist.md and references/nested-lists.md.

  sweep PATH      the review checklist's numbered mechanical sweep (1-17,
                  including 12b), each with its expectation and the matching
                  lines. The leading YAML block and fenced code are skipped;
                  an unclosed fence is reported and its lines are scanned.
  siblings PATH   sweep item 12b alone: list items one tab deep that follow an
                  earlier flush item of the same list block, which renders as
                  nesting. Blank lines, quoted or not, do not end a list.
  outline PATH    the heading outline and coarse counts (list lines, quote
                  lines, links, image embeds, tables, code blocks) for
                  comparing the draft's structure with the source.
  source PATH [--base-url URL]
                  the same outline and counts for saved page markup, plus one
                  JSON row per figure-like element (image, picture, inline
                  SVG, video, canvas, iframe, Lottie player, figure): best
                  image URL resolved against URL, alt, figcaption, figure
                  number, nearest preceding heading and Lottie source. Counts
                  are elements outside nav/aside and page-level header/footer,
                  whose headings and rows are tagged instead. A visually
                  hidden (screen-reader-only) heading is tagged `hidden` and
                  is never a row's nearest heading. Read-only: the stdlib
                  html.parser reads the file; nothing is fetched or executed.
  repair --op OP --lines RANGES PATH [--dry-run]
                  apply one confirmed nested-list repair to the listed lines
                  only (1-based, `12` or `12-18`, comma-separated), keeping any
                  blockquote prefix. OP is `stacked` (collapse a run of list
                  markers to one), `overindent` (collapse two or more leading
                  tabs to one) or `dedent` (strip exactly one leading tab).
                  YAML is never changed. Fenced code keeps its content:
                  `stacked` skips it, and `overindent`/`dedent` move a
                  list-nested fenced block only as a whole, by its fence's
                  indent change, refusing a range that covers part of one.
                  The draft is rewritten in place; a path inside an Obsidian
                  vault is refused, because a draft belongs in the run's
                  scratch.

    python3 '<skill>/scripts/body_checks.py' sweep '<draft>'
    python3 '<skill>/scripts/body_checks.py' repair --op dedent --lines '41-44' '<draft>'

Output is plain text, except `repair`, which prints JSON. Exit 0 when the file
was read (matches are not failures), 1 when it could not be read or a repair
was refused, 2 for a usage error. Stdlib only.
Run ``python3 body_checks.py --test`` for the self-test.
"""

import argparse
import collections
import contextlib
import html.parser
import io
import json
import os
import re
import sys
import tempfile
import unicodedata
import urllib.parse


#: POSIX [[:space:]] without the newline a split line never carries.
SP = r"[ \t\r\f\v]"

#: A fenced-code opener or closer, optionally inside a blockquote: groups are
#: the quote prefix, the indent, the fence and the info string. Any indent
#: opens a fence, because Web Clipper indents a fence inside a list item with
#: tabs.
FENCE_RE = re.compile(r"^((?:>[ \t]?)*)([ \t]*)(`{3,}|~{3,})(.*)$")

H1_RE = re.compile(r"^# ")
SUMMARY_RE = re.compile(r"^> \[!Summary\]")
REMOTE_IMAGE_RE = re.compile(
    r"!\[[^\]]*\]\(|<(?:img|picture|source|figure|video|iframe)[\s/>]", re.I)
STRAY_HTML_RE = re.compile(r"<(?:br|span|div|sup|sub|font|small|hr)[ />]")
CHROME_RE = re.compile(
    r"subscribe|read more|continue reading|sign in|share this|^comments"
    r"|loading comments|write a comment", re.I)
BACKLINK_RE = re.compile(
    r"^[\s>#*]*(?:backlinks?|what links here|mentioned in"
    r"|citations of this page)(?:[^A-Za-z0-9]|$)", re.I)
STAR_RUN_RE = re.compile(r"\*+")
#: A horizontal rule after its indent: three or more of one of `-`, `*` or
#: `_`, optionally separated by spaces or tabs (`---`, `* * *`).
RULE = r"(?P<rule>[-*_])(?:[ \t]*(?P=rule)){2,}%s*$" % SP
#: Two or more list markers on one line; a line that is just a spaced rule
#: such as `- - -` is not stacked markers.
STACKED_RE = re.compile(
    r"^(?!(?:>%s?)*%s*%s)(?:>%s?)*%s*(?:[-*]|[0-9]+\.)"
    r"(?:%s+(?:[-*]|[0-9]+\.))+%s" % (SP, SP, RULE, SP, SP, SP, SP))
CURRENCY_RE = re.compile(r"\$[0-9]")
UNESCAPED_DOLLAR_RE = re.compile(r"(?:^|[^\\])\$")
DROPPED_DOLLAR_RE = re.compile(
    r"/[ =]|/1[KMB](?:[^A-Za-z0-9]|$)|/(?:GPU|hour|min|token)"
    r"|per (?:hour|GPU|min)|[0-9]+/[0-9]|\([^)]*in (?:1[89]|20)[0-9]{2}\)")
#: Two indent steps (tabs or four-space runs) after an optional quote prefix.
DEEP_INDENT_RE = re.compile(r"^(?:>[ \t]?)*(?:\t| {4}){2}")
FOOTNOTE_DEF_RE = re.compile(r"^\[\^([0-9]+)\]:")
FOOTNOTE_REF_RE = re.compile(r"\[\^([0-9]+)\]")
TABLE_RE = re.compile(r"<table")
#: A pipe table's delimiter row, which every Markdown table has exactly once.
TABLE_DELIMITER_RE = re.compile(
    r"^[ \t]*(?:>[ \t]?)*[ \t]*\|?(?:[ \t]*:?-+:?[ \t]*\|)+"
    r"(?:[ \t]*:?-+:?)?[ \t]*$", re.M)
HR_RE = re.compile(r"^(?:[ ]{0,3}%s|<hr>%s*$)" % (RULE, SP))
SEPARATOR_RE = re.compile(r"^___%s*$" % SP)
#: A top-level bullet of the Summary callout.
SUMMARY_BULLET_RE = re.compile(r"^>[ \t]?[-*+][ \t]+(.*)$")
#: A URL, wikilink, Markdown link target or footnote marker in a bullet.
SUMMARY_LINK_RE = re.compile(r"https?://|www\.|\[\[|\]\(|\[\^")
#: Terminal punctuation and closers, then a space before a new sentence.
SENTENCE_END_RE = re.compile(r"[.!?][\"'”’)\]*_]*\s+(?=[\"'“‘(*_]*[A-Z0-9])")
#: Text ending in an abbreviation whose full stop does not end a sentence.
ABBREVIATION_RE = re.compile(
    r"(?:^|[\s(])(?:(?:[A-Za-z]\.)+|vs\.|etc\.|Dr\.|Mr\.|Mrs\.|Ms\.|St\."
    r"|No\.|Fig\.|Inc\.|Ltd\.|Co\.|Jr\.|Sr\.|al\.|Jan\.|Feb\.|Mar\.|Apr\."
    r"|Jun\.|Jul\.|Aug\.|Sept?\.|Oct\.|Nov\.|Dec\.|approx\.|ca\.|cf\.|pp?\."
    r"|vol\.|ch\.)$")
#: An inline code span: a backtick run closed by a run of the same length.
CODE_SPAN_RE = re.compile(r"(?<!`)(`+)(?!`).+?(?<!`)\1(?!`)")
#: An inline Markdown link, not an image: its text (escapes and one level of
#: brackets allowed), then its destination (one level of parentheses) and an
#: optional title.
INLINE_LINK_RE = re.compile(
    r"(?<![!\\])\[((?:[^\[\]\\]|\\.|\[[^\[\]]*\])*)\]"
    r"\(\s*(<[^<>\n]*>|[^\s()]*(?:\([^\s()]*\)[^\s()]*)*)"
    r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^()]*\)))?\s*\)")
#: Sentence punctuation a split link's text may hold besides the quote,
#: bracket and dash categories.
SPLIT_TEXT_PUNCT = frozenset("\"'.,:;!?…")
SPLIT_TEXT_CATEGORIES = ("Pi", "Pf", "Ps", "Pe", "Pd")
#: The longest gap between two links that still counts as near-adjacent.
SPLIT_GAP_MAX = 8
#: Emphasis markers, quotes and punctuation shown around a reported split.
SPLIT_EDGE = frozenset("*_~=“”„‟‘’‚‛«»‹›") | SPLIT_TEXT_PUNCT

#: The quote prefix the sibling scan and the repairs peel off and re-attach.
QUOTE_PREFIX_RE = re.compile(r"^((?:>\s?)*)")
QUOTED_RE = re.compile(r"^((?:>\s?)+)(.*)$")
LIST_ITEM_RE = re.compile(r"^(\t*)(?:[-*]|\d+\.)\s")
STACKED_MARKERS_RE = re.compile(r"^(\s*)((?:[-*]\s+|\d+\.\s+){2,})(.*)$")
OVERINDENT_RE = re.compile(r"^\t\t+(.*)$")

SNIPPET = 160


class RepairError(ValueError):
    """A repair request this helper refuses."""


def frontmatter_end(lines):
    """Index of the first body line after a leading YAML block, else 0.

    A byte-order mark before the opening fence does not hide the block.
    """
    if lines and lines[0].lstrip("\ufeff").rstrip() == "---":
        for i in range(1, len(lines)):
            if lines[i].rstrip() in ("---", "..."):
                return i + 1
    return 0


def code_regions(lines, start=0):
    """``(set of 0-based fenced lines, [unclosed opener indexes], [(opener,
    closer) indexes of closed blocks])``.

    Fence lines count as code. A closer may be indented no deeper than its
    opener (or three spaces). An opener with no closer is not treated as a
    fence, so a damaged fence cannot hide the rest of the note from the sweep.
    """
    inside, unclosed, openers = set(), [], []
    i = start
    while i < len(lines):
        m = FENCE_RE.match(lines[i])
        if m and not (m.group(3)[0] == "`" and "`" in m.group(4)):
            char, width = m.group(3)[0], len(m.group(3))
            indent = max(3, len(m.group(2).expandtabs(4)))
            j = i + 1
            while j < len(lines):
                c = FENCE_RE.match(lines[j])
                if (c and c.group(3)[0] == char and len(c.group(3)) >= width
                        and len(c.group(2).expandtabs(4)) <= indent
                        and not c.group(4).strip()):
                    break
                j += 1
            if j < len(lines):
                inside.update(range(i, j + 1))
                openers.append((i, j))
                i = j + 1
                continue
            unclosed.append(i)
        i += 1
    return inside, unclosed, openers


def body_lines(lines):
    """``([(lineno, text)] outside YAML and fenced code, [unclosed linenos])``."""
    start = frontmatter_end(lines)
    inside, unclosed, _openers = code_regions(lines, start)
    kept = [(i + 1, lines[i]) for i in range(start, len(lines))
            if i not in inside]
    return kept, [i + 1 for i in unclosed]


def snippet(line, start=0, end=None):
    """The line, or a window of it around ``start:end`` when it is long."""
    if len(line) <= SNIPPET:
        return line
    end = start if end is None else end
    left = max(0, min(start - SNIPPET // 3, len(line) - SNIPPET))
    text = line[left:left + SNIPPET]
    return ("…" if left else "") + text + ("…" if left + SNIPPET < len(line) else "")


def grep(body, rx):
    """One ``L``-numbered line of context for each body line ``rx`` matches."""
    out = []
    for n, line in body:
        m = rx.search(line)
        if m:
            out.append("L%d: %s" % (n, snippet(line, m.start(), m.end())))
    return out


def grep_only(body, rx):
    """One ``L``-numbered entry per match, holding only the match (``grep -no``)."""
    return ["L%d: %s" % (n, m.group(0))
            for n, line in body for m in rx.finditer(line)]


def sibling_candidates(lines):
    """``[(lineno, raw)]`` for the single-tab sibling split (sweep item 12b).

    A block is a run of list items and their continuations. Blank lines,
    including a blank `>` line in a loose quoted list, are neutral; a block
    ends only at an unindented paragraph that follows a blank line, or at an
    unindented code fence. Fenced code whose fence is indented continues its
    list item and is not scanned. Every item exactly one tab deep that comes
    after an earlier flush item of the same block is reported, even when a
    stray indented item precedes that flush item. Genuine parent-child
    nesting has the same shape, so every hit is a candidate to judge against
    the source.
    """
    start = frontmatter_end(lines)
    inside, _unclosed, openers = code_regions(lines, start)
    nested = set()
    for first, last in openers:
        if FENCE_RE.match(lines[first]).group(2):
            nested.update(range(first, last + 1))
    hits, block = [], []

    def flush():
        seen_flush = False
        for n, depth, is_item, raw in block:
            if not is_item:
                continue
            if depth == 0:
                seen_flush = True
            elif depth == 1 and seen_flush:
                hits.append((n, raw))
        block.clear()

    prev_blank = False
    for i in range(start, len(lines)):
        raw = lines[i]
        if i in inside:
            if i not in nested:
                flush()
            prev_blank = False
            continue
        body = raw[len(QUOTE_PREFIX_RE.match(raw).group(1)):]
        item = LIST_ITEM_RE.match(body)
        if item:
            block.append((i + 1, len(item.group(1)), True, raw))
        elif body.strip() == "":
            prev_blank = True
            continue
        elif body.startswith("\t") or not prev_blank:
            block.append((i + 1, 0, False, raw))
        else:
            flush()
        prev_blank = False
    flush()
    return hits


def footnote_numbers(body):
    """``(sorted reference numbers, sorted definition numbers)``."""
    refs, defs = set(), set()
    for _n, line in body:
        d = FOOTNOTE_DEF_RE.match(line)
        if d:
            defs.add(int(d.group(1)))
        rest = line[d.end():] if d else line
        refs.update(int(m.group(1)) for m in FOOTNOTE_REF_RE.finditer(rest))
    return sorted(refs), sorted(defs)


def decorative_rules(body):
    """HR lines after the first Summary/body ``___`` separator."""
    out, below = [], False
    for n, line in body:
        if below and HR_RE.match(line):
            out.append("L%d: %s" % (n, line))
        if SEPARATOR_RE.match(line):
            below = True
    return out


def sentence_count(text):
    """Sentences in one bullet; a full stop after an abbreviation is not an end."""
    return 1 + sum(1 for m in SENTENCE_END_RE.finditer(text)
                   if not ABBREVIATION_RE.search(text[:m.start() + 1]))


def summary_size(body):
    """Sweep item 16: the first Summary's bullets against the body's length.

    A bullet runs from its marker to the next marker or blank `>` line. Lists
    each bullet over 45 words or 2 sentences, or holding a link or footnote.
    """
    start = next((k for k, (_n, line) in enumerate(body)
                  if SUMMARY_RE.match(line)), None)
    bullets, end = [], 0
    if start is not None:
        end, prev, current = start + 1, body[start][0], None
        while (end < len(body) and body[end][0] == prev + 1
               and body[end][1].startswith(">")):
            n, line = body[end]
            m = SUMMARY_BULLET_RE.match(line)
            if m:
                current = [n, m.group(1).strip()]
                bullets.append(current)
            elif current is not None and line[1:].strip():
                current[1] += " " + line[1:].strip()
            else:
                current = None
            prev, end = n, end + 1
    words = sum(len(line.split()) for _n, line in body[end:]
                if not SEPARATOR_RE.match(line))
    out = ["bullets: %d, body words: %d (expect ~5-8 for a short post, 10-15 "
           "for longform, at most 20)" % (len(bullets), words),
           "bullets over 30 words: %d" % sum(
               1 for _n, t in bullets if len(t.split()) > 30)]
    for n, t in bullets:
        count, sentences = len(t.split()), sentence_count(t)
        link = SUMMARY_LINK_RE.search(t)
        if count <= 45 and sentences <= 2 and not link:
            continue
        entry = "L%d: %dw" % (n, count)
        if sentences > 2:
            entry += ", %d sentences" % sentences
        if link:
            entry += ", link or footnote: %s" % snippet(
                t, link.start(), link.end())
        out.append(entry)
    return out


def punctuation_only(text):
    """Is a link's text, emphasis and escapes aside, only punctuation?"""
    core = re.sub(r"[\s*_~=\\]", "", text)
    return bool(core) and all(
        c in SPLIT_TEXT_PUNCT
        or unicodedata.category(c) in SPLIT_TEXT_CATEGORIES for c in core)


def split_links(body):
    """Sweep item 17: one linked title split into adjacent links.

    Two consecutive inline links are a candidate when the gap between them
    holds only whitespace, emphasis markers or punctuation (no table pipe) and
    either link's text is only punctuation or both share one URL. A run of
    such links is one entry, widened over the emphasis, quotes and
    punctuation around it.
    Inline code is masked first, so a code span neither matches nor joins.
    """
    out = []
    for n, line in body:
        masked = CODE_SPAN_RE.sub(lambda m: "x" * len(m.group(0)), line)
        links = list(INLINE_LINK_RE.finditer(masked))
        runs, run = [], None
        for a, b in zip(links, links[1:]):
            gap = masked[a.end():b.start()]
            reasons = []
            if len(gap) <= SPLIT_GAP_MAX and not any(
                    c.isalnum() or c == "|" for c in gap):
                if (punctuation_only(a.group(1))
                        or punctuation_only(b.group(1))):
                    reasons.append("punctuation-only link text")
                if a.group(2).strip("<>") == b.group(2).strip("<>"):
                    reasons.append("same URL")
            if not reasons:
                run = None
                continue
            if run is None:
                run = [a.start(), b.end(), []]
                runs.append(run)
            run[1] = b.end()
            run[2] += [r for r in reasons if r not in run[2]]
        for start, end, reasons in runs:
            while start and line[start - 1] in SPLIT_EDGE:
                start -= 1
            while end < len(line) and line[end] in SPLIT_EDGE:
                end += 1
            text = line[start:end]
            if len(text) > 2 * SNIPPET:
                text = text[:SNIPPET] + "…" + text[-SNIPPET // 2:]
            out.append("L%d: %s: %s" % (n, ", ".join(reasons), text))
    return out


def sweep_report(text):
    """The numbered sweep as ``[(header, [result lines])]`` plus notes."""
    lines = text.split("\n")
    body, unclosed = body_lines(lines)
    notes = ["unclosed code fence at L%d: scanned as prose; check the fence"
             % n for n in unclosed]
    summary = sum(1 for _n, line in body if SUMMARY_RE.match(line))
    dollars = sum(len(UNESCAPED_DOLLAR_RE.findall(line)) for _n, line in body)
    refs, defs = footnote_numbers(body)
    footnotes = ["refs: %s" % (" ".join(map(str, refs)) or "-"),
                 "defs: %s" % (" ".join(map(str, defs)) or "-")]
    if refs != defs:
        missing = sorted(set(refs) - set(defs))
        unused = sorted(set(defs) - set(refs))
        footnotes.append("MISMATCH: refs without a definition %s; definitions "
                         "without a reference %s" % (missing or "-", unused or "-"))
    siblings = [(n, raw) for n, raw in sibling_candidates(lines)]
    report = [
        ("1  H1 in body — expect NONE", grep(body, H1_RE)),
        ("2  Summary callouts — expect exactly 1",
         ["%d%s" % (summary, "" if summary == 1 else "  <- expected 1")]),
        ("3  leftover remote image refs (Markdown or HTML) — NONE without a "
         "failure placeholder", grep(body, REMOTE_IMAGE_RE)),
        ("4  stray HTML — NONE outside kept tables, pipe-cell <br>, reported "
         "sup/sub", grep_only(body, STRAY_HTML_RE)),
        ("5  clipping-chrome candidates — inspect in context",
         grep(body, CHROME_RE)),
        ("6  backlink/nav-header candidates — inspect in context",
         grep(body, BACKLINK_RE)),
        ("7  malformed emphasis: odd *-run count — candidate",
         ["L%d: %s" % (n, snippet(line)) for n, line in body
          if len(STAR_RUN_RE.findall(line)) % 2 == 1]),
        ("8  stacked list markers — candidate, check the source",
         grep(body, STACKED_RE)),
        ("9  currency $-then-digit: each must be \\$ or math",
         grep(body, CURRENCY_RE)),
        ("10 unescaped $ parity: must be EVEN after escaping",
         ["%d (%s)" % (dollars, "even" if dollars % 2 == 0 else
                       "ODD: an unpaired or unescaped $ remains")]),
        ("11 dropped-$ candidates: compare with the source, NOISY",
         grep(body, DROPPED_DOLLAR_RE)),
        ("12 nested-list deep indent — candidate, NOISY",
         grep(body, DEEP_INDENT_RE)),
        ("12b sibling indent split — candidate, NOISY",
         ["L%d: sibling +1 tab under an earlier flush item (renders as "
          "nested): %s" % (n, raw[:70]) for n, raw in siblings]),
        ("13 footnote refs vs defs — the two lists must be identical",
         footnotes),
        ("14 leftover HTML <table> — NONE unless complex",
         grep(body, TABLE_RE)),
        ("15 decorative HR below the ___ separator — NONE",
         decorative_rules(body)),
        ("16 Summary size — candidates, judge against SKILL.md step 4",
         summary_size(body)),
        ("17 split links: adjacent links with punctuation-only text or one "
         "URL — candidate, check the source", split_links(body)),
    ]
    return report, notes


def outline_report(text):
    """``(headings, counts)`` of the note body, YAML and code excluded."""
    lines = text.split("\n")
    start = frontmatter_end(lines)
    inside, _unclosed, openers = code_regions(lines, start)
    prose = "\n".join(lines[i] for i in range(start, len(lines))
                      if i not in inside)
    heads = [(len(m.group(1)), m.group(2).strip())
             for m in re.finditer(r"^(#{1,6})\s+(.*)$", prose, re.M)]
    counts = dict(
        list_lines=len(re.findall(r"^\s*(?:>\s?)*\s*(?:[-*]|\d+\.)\s",
                                  prose, re.M)),
        quote_lines=len(re.findall(r"^\s*>", prose, re.M)),
        links=len(re.findall(r"\[[^\]]+\]\([^)]+\)", prose)),
        image_embeds=len(re.findall(r"!\[\[?", prose)),
        tables=len(TABLE_DELIMITER_RE.findall(prose))
        + len(re.findall(r"<table", prose, re.I)),
        code_blocks=len(openers),
    )
    return heads, counts


# --- saved source markup ------------------------------------------------------

#: Elements whose open/close depth the parser tracks.
TRACKED = frozenset((
    "a", "article", "aside", "blockquote", "button", "figcaption", "figure",
    "footer", "header", "main", "nav", "noscript", "picture", "script",
    "section", "style", "svg", "template", "video",
    "h1", "h2", "h3", "h4", "h5", "h6"))
HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")
#: Sectioning elements that keep a header/footer from being page chrome.
SECTIONING = ("article", "aside", "main", "nav", "section")
CHROME = ("nav", "aside", "header", "footer")
#: Element bodies that are not page content: no headings, counts or rows.
INERT = ("script", "style", "template", "svg")
IMG_TAGS = ("img", "amp-img")
#: Classes that hide a heading from sight but not from screen readers.
SR_ONLY_CLASSES = frozenset((
    "screen-reader-text", "sr-only", "visually-hidden", "visuallyhidden",
    "screen-reader-only"))
LOTTIE_TAGS = ("lottie-player", "dotlottie-player", "dotlottie-wc")
LOTTIE_PATH_ATTRS = ("data-animation-path", "data-anim-path", "data-bm-path")
LOTTIE_FILE_RE = re.compile(r"\.(?:json|lottie)(?:[?#]|$)", re.I)
PERMALINK_GLYPHS = frozenset("#¶§🔗")
SRCSET_DESCRIPTOR_RE = re.compile(r"^([0-9]*\.?[0-9]+)([wx])$")
ROW_FIELDS = ("line", "tag", "url", "src", "alt", "caption", "figure",
              "heading", "lottie", "poster", "in", "noscript")


def parse_srcset(value):
    """``[(url, descriptor)]``; a URL ends at whitespace, so its commas stay."""
    out, pos, n = [], 0, len(value)
    while pos < n:
        while pos < n and (value[pos].isspace() or value[pos] == ","):
            pos += 1
        start = pos
        while pos < n and not value[pos].isspace():
            pos += 1
        url, descriptor = value[start:pos], ""
        if url.endswith(","):
            url = url.rstrip(",")
        else:
            begin, depth = pos, 0
            while pos < n and (value[pos] != "," or depth):
                if value[pos] == "(":
                    depth += 1
                elif value[pos] == ")" and depth:
                    depth -= 1
                pos += 1
            descriptor = value[begin:pos].strip()
        if url:
            out.append((url, descriptor))
    return out


def _srcset_rank(candidate):
    """``(width, density)``; a candidate with no descriptor is 1x."""
    m = SRCSET_DESCRIPTOR_RE.match(candidate[1].split(" ")[0])
    if not m:
        return (0.0, 1.0)
    size = float(m.group(1))
    return (size, 0.0) if m.group(2) == "w" else (0.0, size)


def best_image_url(attrs, extra_srcsets=()):
    """The largest srcset candidate, else data-lazy-src, data-src, then src.

    A `data:` placeholder yields to any other URL.
    """
    candidates = []
    for value in [attrs.get("srcset"), attrs.get("data-srcset")] + list(
            extra_srcsets):
        if value:
            candidates.extend(parse_srcset(value))
    ordered = [max(candidates, key=_srcset_rank)[0]] if candidates else []
    ordered += [attrs.get(k) or "" for k in ("data-lazy-src", "data-src", "src")]
    ordered = [u.strip() for u in ordered if u.strip()]
    real = [u for u in ordered if not u.lower().startswith("data:")]
    return (real or ordered or [""])[0]


def shown_url(url):
    """A data URI abbreviated to its media type and length."""
    if url.lower().startswith("data:"):
        return "%s,… (%d chars)" % (url.split(",", 1)[0], len(url))
    return url


def _text(parts):
    return " ".join("".join(parts).split())


class SourceInventory:
    """Headings, coarse counts and figure-like media of saved page markup.

    Script and style bodies are character data to html.parser, so markup in
    them is never parsed; template and inline-SVG contents are skipped, and
    inside `<noscript>` only an image not already listed is reported.
    """

    def __init__(self, base_url=None):
        # html.parser dispatches through instance attributes, so bound
        # handlers stand in for a subclass of the imported parser.
        self.parser = html.parser.HTMLParser(convert_charrefs=True)
        self.parser.handle_starttag = self.handle_starttag
        self.parser.handle_endtag = self.handle_endtag
        self.parser.handle_data = self.handle_data
        self.feed, self.close = self.parser.feed, self.parser.close
        self.getpos = self.parser.getpos
        self.base = base_url or ""
        self.base_seen = False
        self.depth = collections.Counter()
        self.page_chrome = collections.Counter()
        self.header_footer = {"header": [], "footer": []}
        self.headings, self.media = [], []
        self.counts = dict(list_lines=0, quote_lines=0, links=0,
                           image_embeds=0, tables=0, code_blocks=0)
        self.last_heading = ""
        self.heading = None
        self.figures, self.pictures, self.quotes = [], [], []
        self.figure_count = 0
        self.video = None
        self.seen_urls = set()

    def resolve(self, url):
        url = (url or "").strip()
        if not url or url.lower().startswith("data:") or not self.base:
            return url
        return urllib.parse.urljoin(self.base, url)

    def chrome(self):
        """The nav, aside, page header or page footer around the parser."""
        for tag in CHROME:
            if self.depth[tag] if tag in ("nav", "aside") \
                    else self.page_chrome[tag]:
                return tag
        return None

    def row(self, tag, **fields):
        row = {"line": self.getpos()[0], "tag": tag}
        row.update((k, v) for k, v in fields.items() if v)
        if self.figures:
            row["figure"] = self.figures[-1]["no"]
            self.figures[-1]["rows"].append(row)
        if self.last_heading:
            row["heading"] = self.last_heading
        chrome = self.chrome()
        if chrome:
            row["in"] = chrome
        if self.depth["noscript"]:
            row["noscript"] = True
        elif tag in IMG_TAGS + ("picture",) and not chrome:
            self.counts["image_embeds"] += 1
        self.media.append(row)
        return row

    def image_row(self, tag, attrs, extra_srcsets=()):
        url = self.resolve(best_image_url(attrs, extra_srcsets))
        src = self.resolve(attrs.get("src"))
        if self.depth["noscript"] and url in self.seen_urls:
            return
        self.seen_urls.update(u for u in (url, src) if u)
        self.row(tag, url=shown_url(url),
                 src=shown_url(src) if src != url else "",
                 alt=_text([attrs.get("alt") or ""]))

    def handle_starttag(self, tag, attrs):
        attrs = dict((k, v or "") for k, v in attrs)
        if any(self.depth[t] for t in INERT):
            if tag in INERT:
                self.depth[tag] += 1
            return
        if tag == "base" and not self.base_seen and attrs.get("href"):
            self.base_seen = True
            self.base = self.resolve(attrs["href"]) if self.base \
                else attrs["href"]
        if tag in ("header", "footer"):
            landmark = not any(self.depth[t] for t in SECTIONING)
            self.header_footer[tag].append(landmark)
            self.page_chrome[tag] += landmark
        if tag in TRACKED:
            self.depth[tag] += 1
        if self.depth["noscript"]:
            if tag in IMG_TAGS and not self.pictures:
                self.image_row(tag, attrs)
            return
        chrome = self.chrome()
        if tag in HEADING_TAGS:
            self.finish_heading()
            # aria-hidden does not hide a heading from sight, so it stays.
            hidden = "hidden" in attrs or not SR_ONLY_CLASSES.isdisjoint(
                attrs.get("class", "").lower().split())
            self.heading = (int(tag[1]), [],
                            chrome or ("hidden" if hidden else None))
        elif tag == "br" and self.heading is not None:
            self.heading[1].append(" ")
        elif tag == "a" and not chrome:
            href = attrs.get("href", "").strip()
            if href and not href.startswith("#") \
                    and not href.lower().startswith("javascript:"):
                self.counts["links"] += 1
        elif tag in ("table", "pre") and not chrome:
            self.counts["tables" if tag == "table" else "code_blocks"] += 1
        elif tag == "blockquote":
            self.quotes.append(0)
        if tag in ("p", "li") and self.quotes:
            self.quotes[-1] += 1
        if tag == "li" and not chrome:
            self.counts["list_lines"] += 1
        self.media_start(tag, attrs, chrome)

    def media_start(self, tag, attrs, chrome):
        lottie = [attrs[k] for k in ("src", "data-src") + LOTTIE_PATH_ATTRS
                  if LOTTIE_FILE_RE.search(attrs.get(k, ""))]
        if tag in LOTTIE_TAGS or any(attrs.get(k) for k in LOTTIE_PATH_ATTRS) \
                or attrs.get("data-animation-type", "").lower() == "lottie" \
                or (lottie and "lottie" in attrs.get("class", "").lower()):
            self.row(tag, lottie=self.resolve(lottie[0]) if lottie else "")
        elif tag == "figure":
            self.figure_count += 1
            # Listed in place now; dropped at </figure> if media fill it.
            stub = {"line": self.getpos()[0], "tag": "figure",
                    "figure": self.figure_count}
            if self.last_heading:
                stub["heading"] = self.last_heading
            if chrome:
                stub["in"] = chrome
            self.media.append(stub)
            self.figures.append({"no": self.figure_count, "rows": [],
                                 "caption": [], "stub": stub})
        elif tag == "picture":
            self.pictures.append({"sources": [], "img": False})
        elif tag == "source" and self.video is not None:
            if "url" not in self.video and attrs.get("src"):
                self.video["url"] = self.resolve(attrs["src"])
        elif tag == "source" and self.pictures:
            self.pictures[-1]["sources"].extend(
                attrs[k] for k in ("srcset", "data-srcset") if attrs.get(k))
        elif tag in IMG_TAGS:
            if self.pictures:
                self.pictures[-1]["img"] = True
                self.image_row("picture", attrs, self.pictures[-1]["sources"])
            else:
                self.image_row(tag, attrs)
        elif tag == "video":
            self.video = self.row(
                "video", url=self.resolve(attrs.get("src")),
                poster=self.resolve(attrs.get("poster")))
        elif tag == "iframe":
            url = next((attrs[k].strip() for k in
                        ("data-lazy-src", "data-src", "src")
                        if attrs.get(k, "").strip()
                        and attrs[k].strip().lower() != "about:blank"), "")
            self.row("iframe", url=self.resolve(url))
        elif tag == "canvas":
            self.row("canvas")
        elif tag == "svg" and not self.depth["a"] and not self.depth["button"]:
            self.row("svg", alt=_text([attrs.get("aria-label", "")]))

    def handle_endtag(self, tag):
        if any(self.depth[t] for t in INERT):
            if tag in INERT and self.depth[tag]:
                self.depth[tag] -= 1
            return
        if tag in TRACKED and not self.depth[tag]:
            return
        if not self.depth["noscript"]:
            if tag in HEADING_TAGS:
                self.finish_heading()
            elif tag == "figure" and self.figures:
                self.finish_figure()
            elif tag == "picture" and self.pictures:
                self.finish_picture()
            elif tag == "video":
                self.video = None
            elif tag == "blockquote" and self.quotes:
                paragraphs = self.quotes.pop()
                if not self.chrome():
                    self.counts["quote_lines"] += max(paragraphs, 1)
        if tag in ("header", "footer") and self.header_footer[tag]:
            self.page_chrome[tag] -= self.header_footer[tag].pop()
        if tag in TRACKED:
            self.depth[tag] -= 1

    def handle_data(self, data):
        if self.depth["noscript"] or any(self.depth[t] for t in INERT):
            return
        if self.heading is not None and not (
                self.depth["a"] and data.strip()
                and set(data.strip()) <= PERMALINK_GLYPHS):
            self.heading[1].append(data)
        if self.depth["figcaption"] and self.figures:
            self.figures[-1]["caption"].append(data)

    def finish_heading(self):
        if self.heading is not None:
            level, parts, chrome = self.heading
            self.heading = None
            text = _text(parts)
            if text:
                self.headings.append((level, text, chrome))
                if chrome not in ("nav", "aside", "hidden"):
                    self.last_heading = text

    def finish_picture(self):
        picture = self.pictures.pop()
        if not picture["img"] and picture["sources"]:
            self.image_row("picture", {}, picture["sources"])

    def finish_figure(self):
        figure = self.figures.pop()
        caption = _text(figure["caption"])
        for row in figure["rows"] or [figure["stub"]]:
            if caption:
                row.setdefault("caption", caption)
        if figure["rows"]:
            self.media = [r for r in self.media if r is not figure["stub"]]
            if self.figures:
                # A nested figure's media fill its parent, e.g. a gallery.
                self.figures[-1]["rows"].extend(figure["rows"])

    def finish(self):
        """Close what the markup left open."""
        self.finish_heading()
        while self.pictures:
            self.finish_picture()
        while self.figures:
            self.finish_figure()


def source_report(text, base_url=None):
    """``(headings, counts, media rows, notes)`` of saved page markup."""
    parser = SourceInventory(base_url)
    notes = [] if base_url else [
        "no --base-url: relative URLs are left unresolved"]
    try:
        parser.feed(text)
        parser.close()
    except Exception as exc:  # html.parser is lenient; keep a partial result
        notes.append("parser stopped near L%d: %s" % (parser.getpos()[0], exc))
    parser.finish()
    media = [dict((k, r[k]) for k in ROW_FIELDS if k in r)
             for r in parser.media]
    return parser.headings, parser.counts, media, notes


# --- region-scoped repairs --------------------------------------------------

def _split_quote(line):
    m = QUOTED_RE.match(line)
    return (m.group(1), m.group(2)) if m else ("", line)


def collapse_stacked_markers(line):
    """`- - text` -> `- text`; the last marker of the run is kept.

    A spaced rule such as `* * *` is not a run of markers and stays.
    """
    prefix, body = _split_quote(line)
    m = STACKED_MARKERS_RE.match(body)
    if m and not HR_RE.match(body.lstrip()):
        body = "%s%s %s" % (m.group(1), m.group(2).split()[-1], m.group(3))
    return prefix + body


def collapse_overindent(line):
    """Two or more leading tabs -> one."""
    prefix, body = _split_quote(line)
    m = OVERINDENT_RE.match(body)
    if m:
        body = "\t" + m.group(1)
    return prefix + body


def dedent_one_tab(line):
    """Strip exactly one leading tab."""
    prefix, body = _split_quote(line)
    if body.startswith("\t"):
        body = body[1:]
    return prefix + body


REPAIRS = {
    "stacked": collapse_stacked_markers,
    "overindent": collapse_overindent,
    "dedent": dedent_one_tab,
}


def parse_ranges(spec, total):
    """Sorted 1-based line numbers from ``12,14-18``; refuses bad ranges."""
    wanted = set()
    for part in spec.split(","):
        part = part.strip()
        m = re.fullmatch(r"([0-9]+)(?:-([0-9]+))?", part)
        if not m:
            raise RepairError("line range %r is not N or N-M" % part)
        first = int(m.group(1))
        last = int(m.group(2) or first)
        if first < 1 or last < first or last > total:
            raise RepairError("line range %r is outside 1-%d" % (part, total))
        wanted.update(range(first, last + 1))
    return sorted(wanted)


def inside_vault(path):
    """Is ``path`` below a directory holding `.obsidian/`?"""
    d = os.path.dirname(os.path.realpath(path))
    while True:
        if os.path.isdir(os.path.join(d, ".obsidian")):
            return True
        parent = os.path.dirname(d)
        if parent == d:
            return False
        d = parent


def _leading_tabs(text):
    return len(text) - len(text.lstrip("\t"))


def nested_code_moves(lines, openers, op, listed):
    """``{0-based line: new text}`` for the list-nested fenced blocks that
    ``overindent`` or ``dedent`` moves.

    A block moves only when its fence is indented and the op changes the
    opener's tabs. Each line then loses, after its quote prefix, the tabs the
    op removes from the opener, so the code keeps its own indentation. A
    block listed only in part, or with a code line too shallow to move, is
    refused.
    """
    moves = {}
    if op == "stacked":
        return moves
    for first, last in openers:
        block = set(range(first, last + 1))
        if not FENCE_RE.match(lines[first]).group(2) or not block & listed:
            continue
        tabs = (_leading_tabs(_split_quote(lines[first])[1])
                - _leading_tabs(_split_quote(REPAIRS[op](lines[first]))[1]))
        if not tabs:
            continue
        if not block <= listed:
            raise RepairError("lines %d-%d are one fenced code block: list "
                              "all of it or none" % (first + 1, last + 1))
        for i in range(first, last + 1):
            prefix, body = _split_quote(lines[i])
            if body.strip() and _leading_tabs(body) < tabs:
                raise RepairError(
                    "line %d has fewer than %d leading tabs, so lines %d-%d "
                    "cannot move as one fenced code block"
                    % (i + 1, tabs, first + 1, last + 1))
            moves[i] = prefix + body[min(tabs, _leading_tabs(body)):]
    return moves


def plan_repair(text, op, spec):
    """``(new text, changed, skipped)`` for one repair over the listed lines."""
    if op not in REPAIRS:
        raise RepairError("unknown repair %r" % op)
    lines = text.split("\n")
    start = frontmatter_end(lines)
    inside, _unclosed, openers = code_regions(lines, start)
    wanted = parse_ranges(spec, len(lines))
    moves = nested_code_moves(lines, openers, op, set(n - 1 for n in wanted))
    changed, skipped = [], []
    for n in wanted:
        i = n - 1
        if i in moves:
            after = moves[i]
        elif i < start or i in inside:
            skipped.append({"line": n, "reason": "YAML or fenced code"})
            continue
        else:
            after = REPAIRS[op](lines[i])
        if after != lines[i]:
            changed.append({"line": n, "before": lines[i], "after": after})
            lines[i] = after
    return "\n".join(lines), changed, skipped


def write_in_place(path, text):
    """Replace the scratch draft with ``text``, keeping its mode."""
    mode = os.stat(path).st_mode & 0o7777
    fd, tmp = tempfile.mkstemp(prefix=".body-checks-", suffix=".tmp",
                               dir=os.path.dirname(os.path.abspath(path)))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def cmd_repair(path, op, spec, dry_run=False):
    """``(payload, exit code)`` for one repair request."""
    try:
        if inside_vault(path):
            raise RepairError("%s is inside an Obsidian vault; repair only the "
                              "scratch draft" % path)
        with open(path, encoding="utf-8", newline="") as fh:
            text = fh.read()
        new, changed, skipped = plan_repair(text, op, spec)
        if changed and not dry_run:
            write_in_place(path, new)
    except (RepairError, OSError, UnicodeError) as exc:
        return {"ok": False, "error": str(exc)}, 1
    return {"ok": True, "op": op, "dry_run": dry_run, "changed": changed,
            "skipped": skipped}, 0


# --- self-test ----------------------------------------------------------------

def run_self_test():
    cases = []

    def check(label, got, want):
        cases.append((label, got == want, got, want))

    def sibling_lines(text):
        return [n for n, _raw in sibling_candidates(text.split("\n"))]

    def items(text):
        report, _notes = sweep_report(text)
        return {h.split()[0]: r for h, r in report}

    tight = "> - **Q:** why?\n> \t- **A:** because."
    check("tight quoted Q&A split is a sibling candidate",
          sibling_lines(tight), [2])
    check("a blank `>` line does not hide the split",
          sibling_lines("> - **Q:** why?\n>\n> \t- **A:** because."), [3])
    check("a plain blank line does not hide the split",
          sibling_lines("- **Q:** why?\n\n\t- **A:** because."), [3])
    check("a flush paragraph after a blank line ends the list",
          sibling_lines("- a\n\nParagraph.\n\n\t- b"), [])
    check("ordinary paragraphs are not candidates",
          sibling_lines("One.\n\nTwo\n\tstill two.\n\nThree."), [])
    check("aligned peers are not candidates",
          sibling_lines("> - A: hi\n> - B: hello"), [])
    check("a list inside fenced code is not scanned",
          sibling_lines("```\n- a\n\t- b\n```"), [])
    check("a list inside a tab-indented fence is not scanned, and the "
          "fence does not end its list item",
          sibling_lines("- **Q:** how?\n\t```yaml\n\t- name: a\n\t```\n"
                        "\t- **A:** like that."), [5])
    check("a stray indented item before a loose flush Q&A pair does not "
          "hide the split",
          sibling_lines("Intro para.\n\n\t- stray indented item\n\n"
                        "- **Q:** why?\n\t- **A:** because."), [6])
    check("...nor does it inside a blockquote",
          sibling_lines("> \t- stray\n>\n> - **Q:** x\n> \t- **A:** y"), [4])
    orphan = ("> Intro:\n> \t\t- dangling orphan turn\n>\n"
              "> - **Q:** Why?\n> \t- **A:** Because.")
    check("an orphaned deep turn before a flush Q&A pair does not hide the "
          "split", sibling_lines(orphan), [5])
    check("...and the split is still found after the orphan is collapsed "
          "to one tab",
          sibling_lines(plan_repair(orphan, "overindent", "2")[0]), [5])
    check("one-tab items with no earlier flush item are not candidates",
          sibling_lines("Intro:\n\t- a\n\t- b\n- c"), [])

    doc = "\n".join([
        "---", "title: x", "tags:", "  - \"#ai\"", "---",
        "> [!Summary]", "> - claim", "", "___", "",
        "# Stray H1",
        "Text <img src=\"https://x.test/a.png\"> and ![a](https://x.test/b.png)",
        "<figure><img src=\"https://x.test/c.png\"/></figure>",
        "<picture><source srcset=\"x\"></picture>",
        "Line<br>break and <span>x</span>.",
        "Please subscribe now.",
        "**Backlinks (3)** for \"Intro\":",
        "*Label**:* broken",
        "- - stacked",
        "\t\t- deep",
        "Costs $5 and \\$6.",
        "A 0.03/1K rate.",
        "Note[^1] and[^2].",
        "[^1]: one",
        "<table><tr><td>x</td></tr></table>",
        "```bash",
        "# a shell comment, not an H1",
        "echo $HOME > [!Summary]",
        "---",
        "```",
        "***",
    ])
    got = items(doc)
    check("H1 outside code is found; a shell comment in a fence is not",
          got["1"], ["L11: # Stray H1"])
    check("one Summary callout; a fenced example is not a second",
          got["2"], ["1"])
    check("Markdown and HTML remote images are both found",
          [r.split(":")[0] for r in got["3"]], ["L12", "L13", "L14"])
    check("stray HTML tags are listed per match",
          got["4"], ["L15: <br>", "L15: <span>"])
    check("chrome candidates are case-insensitive", got["5"],
          ["L16: Please subscribe now."])
    check("a backlink header is a candidate", [r[:4] for r in got["6"]],
          ["L17:"])
    check("an odd *-run count is a candidate, a `***` rule included",
          [r[:4] for r in got["7"]], ["L18:", "L31:"])
    check("stacked markers are candidates", got["8"], ["L19: - - stacked"])
    check("currency before a digit is listed", got["9"],
          ["L21: Costs $5 and \\$6."])
    check("escaped dollars do not count toward parity; YAML and code do not",
          got["10"], ["1 (ODD: an unpaired or unescaped $ remains)"])
    check("dropped-$ candidates are listed", got["11"],
          ["L22: A 0.03/1K rate."])
    check("two-tab indent is a candidate", got["12"], ["L20: \t\t- deep"])
    check("eight spaces, or a tab and four spaces, are deep-indent "
          "candidates too; one step is not",
          items("        - spaced\n> \t    - mixed\n    - one step\n"
                ">     - quoted one step")["12"],
          ["L1:         - spaced", "L2: > \t    - mixed"])
    check("footnote refs and defs are compared",
          got["13"], ["refs: 1 2", "defs: 1",
                      "MISMATCH: refs without a definition [2]; definitions "
                      "without a reference -"])
    check("an HTML table is listed", [r[:4] for r in got["14"]], ["L25:"])
    check("a rule below the separator is listed; YAML and fenced ones are not",
          got["15"], ["L31: ***"])
    spaced = items("> [!Summary]\n> - a\n\n___\n\n* * *\n\n- - -\n\n_ _ _")
    check("spaced rules below the separator are decorative rules, not "
          "stacked markers", (spaced["15"], spaced["8"]),
          (["L6: * * *", "L8: - - -", "L10: _ _ _"], []))
    nested = items("1. Run it:\n\t```bash\n\techo $HOME costs $5 and $X<br>\n"
                   "\t\tindented\n\t```")
    check("a tab-indented fence in a list item is code to the sweep",
          [nested[k] for k in ("4", "9", "10", "12")],
          [[], [], ["0 (even)"], []])
    bom = '\ufeff---\ntitle: "Costs $5"\ntags:\n  - - nested\n---\nBody \\$3.\n'
    check("a BOM does not expose YAML to the sweep",
          [items(bom)[k] for k in ("8", "9", "10")],
          [[], ["L6: Body \\$3."], ["0 (even)"]])
    report, notes = sweep_report("x\n```\nnever closed\n# heading")
    check("an unclosed fence is reported and scanned as prose",
          (notes, dict((h.split()[0], r) for h, r in report)["1"]),
          (["unclosed code fence at L2: scanned as prose; check the fence"],
           ["L4: # heading"]))
    check("every numbered sweep item is present, 12b included",
          [h.split()[0] for h, _r in sweep_report("")[0]],
          ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12",
           "12b", "13", "14", "15", "16", "17"])

    long_bullet = " ".join(["word"] * 50) + "."
    summary = "\n".join([
        "---", "title: x", "---",
        "> [!Summary]",
        "> - Short claim one.",
        "> - " + long_bullet,
        "> - One. Two. Three sentences here.",
        "> - Smith et al. found it, e.g. U.S. data. Fine.",
        "> - A bullet that wraps",
        ">   onto a second line with a [[Wiki Link]].",
        "> - Cites [a page](https://x.test) and a note[^1].",
        "> - " + " ".join(["thirty-one"] * 31),
        "", "___", "",
        "Body has six words in it.",
        "```", "code words are not counted", "```",
    ])
    size = items(summary)["16"]
    check("item 16 counts bullets beside body words, code excluded",
          size[0].split(" (")[0], "bullets: 7, body words: 6")
    check("item 16 counts bullets over 30 words", size[1],
          "bullets over 30 words: 2")
    check("item 16 lists a bullet over 45 words",
          [e for e in size if e.startswith("L6:")], ["L6: 50w"])
    check("item 16 lists a bullet of more than two sentences",
          [e for e in size if e.startswith("L7:")], ["L7: 5w, 3 sentences"])
    check("item 16 does not end sentences at abbreviations",
          [e for e in size if e.startswith("L8:")], [])
    check("item 16 does not end sentences at months or approx.",
          items("\n".join([
              "> [!Summary]",
              "> - Hamas attacked on Oct. 7. Israel responded.",
              "> - On Jan. 20, 2025, Trump signed the order. It took effect.",
              "> - Costs fell approx. 5 percent. Margins rose.",
              "> - It used ca. 2e25 FLOP. It cost $100m.",
          ]))["16"][2:], [])
    check("item 16 joins a wrapped bullet and finds its wikilink",
          [e.split(",")[0] for e in size if e.startswith("L9:")], ["L9: 12w"])
    check("item 16 lists a bullet with a URL or footnote marker",
          [e.split(" link")[0] for e in size if e.startswith("L11:")],
          ["L11: 6w,"])
    check("item 16 leaves a 31-word single sentence to the count alone",
          [e for e in size if e.startswith("L12:")], [])
    check("item 16 without a Summary counts the whole body",
          items("One two three.\n")["16"][0].split(" (")[0],
          "bullets: 0, body words: 3")
    doi = "https://x.test/doi/10.1126/sageke.2002.21.pe7"
    check("item 17 finds a quote-only link split from its title, the "
          "emphasis and closing quote around it shown, on a long line",
          items(" ".join(["Prose"] * 60) + " published **[“](%s)**[A New "
                "Record](%s)” for the naked mole rat." % (doi, doi))["17"],
          ["L1: punctuation-only link text, same URL: **[“](%s)**[A New "
           "Record](%s)”" % (doi, doi)])
    check("item 17 finds one title split across two links to one URL",
          items("See [A New](https://x.test/r) [Record](https://x.test/r).")
          ["17"],
          ["L1: same URL: [A New](https://x.test/r) "
           "[Record](https://x.test/r)."])
    check("item 17 reports a run of split pieces once, a dash piece to a "
          "related URL included",
          items("[“](https://x.test/a)[Title](https://x.test/a)[”]"
                "(https://x.test/a) and [—](https://x.test/b)"
                "[Next](https://x.test/b?ref=1)")["17"],
          ["L1: punctuation-only link text, same URL: [“](https://x.test/a)"
           "[Title](https://x.test/a)[”](https://x.test/a)",
           "L1: punctuation-only link text: [—](https://x.test/b)"
           "[Next](https://x.test/b?ref=1)"])
    check("item 17 leaves different links apart, separated by text, a table "
          "pipe or an image, alone",
          items("[Smith](https://a.test) and [Jones](https://b.test), "
                "[Paper](https://c.test) · [Code](https://d.test).\n"
                "| [“](https://e.test) | [Title](https://e.test/t) |\n"
                "[A](https://f.test)![“](g.png)[B](https://h.test)")["17"], [])
    check("item 17 skips links in a code span or fenced code, and a code "
          "span between two links breaks them apart",
          items("Write `**[“](https://x.test)**[T](https://x.test)` "
                "literally.\n[“](https://x.test)`**`[T](https://x.test)\n"
                "```\n[“](https://x.test)[T](https://x.test)\n```")["17"], [])
    long_line = "a" * 400 + " subscribe " + "b" * 400
    check("a long line is windowed around its match",
          "subscribe" in grep([(1, long_line)], CHROME_RE)[0]
          and len(grep([(1, long_line)], CHROME_RE)[0]) < 200, True)

    heads, counts = outline_report(
        "---\na: b\n---\n## One\n- x\n> q\n[l](u)\n![[f.png]]\n"
        "```\n# not a heading\n```\n### Two\n| a | b |\n|---|:--:|\n| 1 | 2 |\n"
        "<table><tr><td>x</td></tr></table>\n---")
    check("outline lists headings outside code, in order", heads,
          [(2, "One"), (3, "Two")])
    check("outline counts lists, quotes, links, embeds, tables and code blocks",
          counts, dict(list_lines=1, quote_lines=1, links=1, image_embeds=1,
                       tables=2, code_blocks=1))
    check("outline counts back-to-back fenced blocks separately",
          outline_report("intro\n```a\nx\n```\n```b\ny\n```\n\n~~~\nz\n"
                         "~~~\n")[1]["code_blocks"], 3)
    check("outline does not count an unclosed fence as a code block",
          outline_report("```a\nx\n```\n```\nnever closed")[1]["code_blocks"],
          1)
    check("outline counts a tab-indented fenced block in a list item",
          outline_report("1. step\n\t```\n\tx\n\t```\n")[1]["code_blocks"], 1)

    check("srcset keeps commas inside a URL and reads descriptors",
          parse_srcset("https://c.test/w_400,h_300/a.jpg 400w,"
                       "https://c.test/w_800,h_600/a.jpg 800w"),
          [("https://c.test/w_400,h_300/a.jpg", "400w"),
           ("https://c.test/w_800,h_600/a.jpg", "800w")])
    check("srcset accepts a bare URL and trailing commas",
          parse_srcset(" a.png, b.png 2x,, "), [("a.png", ""), ("b.png", "2x")])
    check("the largest srcset candidate is the best URL",
          best_image_url({"src": "s.jpg", "srcset": "a.jpg 1x, b.jpg 2x"}),
          "b.jpg")
    check("a lazy data-src beats a data: placeholder src",
          best_image_url({"src": "data:image/gif;base64,R0lG",
                          "data-src": "real.png"}), "real.png")

    page = "\n".join([
        "<!doctype html><html><head><base href=\"/blog/\"><title>T</title>",
        "<script>var s = \"<img src='nope.png'><h2>No</h2>\";</script>",
        "<style>h2 { color: red }</style></head><body>",
        "<header><nav><a href=\"/\">Home</a><h2>Menu</h2>"
        "<img src=\"logo.png\" alt=\"logo\"></nav></header>",
        "<article><header><h1>Title <a href=\"#t\">#</a></h1></header>",
        "<p>Intro <a href=\"https://ex.test/x\">link</a> "
        "<a href=\"#fn1\">1</a>.</p>",
        "<h2>Charts</h2>",
        "<figure><img src=\"data:image/gif;base64,R0lGOD\" "
        "data-src=\"img/a.png\" alt=\"Chart A\">",
        "<figcaption>Figure 1. <em>Growth</em>.</figcaption></figure>",
        "<picture><source srcset=\"b-400.webp 400w, b-1200.webp 1200w\">"
        "<img src=\"b.jpg\" alt=\"B\"></picture>",
        "<noscript><img src=\"img/a.png\"><iframe src=\"t.html\"></iframe>"
        "</noscript>",
        "<h3>Animation</h3>",
        "<figure><lottie-player src=\"anim/spin.json\"></lottie-player>"
        "<img src=\"poster.png\" alt=\"poster\"></figure>",
        "<div class=\"lottie\" data-src=\"//cdn.test/x.lottie\"></div>",
        "<video poster=\"v.jpg\"><source src=\"v.mp4\"></video>",
        "<iframe src=\"https://player.test/embed/1\"></iframe><canvas></canvas>",
        "<svg aria-label=\"diagram\"><svg></svg><image href=\"i.png\"/></svg>",
        "<a href=\"/x\"><svg><path d=\"\"/></svg></a>",
        "<figure><table><tr><td>1</td></tr></table>"
        "<figcaption>Table 1</figcaption></figure>",
        "<ul><li>one<li>two</ul>",
        "<blockquote><p>q1</p><p>q2</p></blockquote>"
        "<blockquote>bare</blockquote><pre><code>x</code></pre>",
        "</article><template><img src=\"tpl.png\"></template>",
        "<footer><img src=\"f.png\"></footer></body></html>",
    ])
    heads, counts, media, notes = source_report(
        page, "https://site.test/post/1")
    check("source headings skip script text, tag chrome and drop a "
          "permalink glyph", heads,
          [(2, "Menu", "nav"), (1, "Title", None), (2, "Charts", None),
           (3, "Animation", None)])
    check("source counts skip chrome and in-page fragment links", counts,
          dict(list_lines=2, quote_lines=3, links=2, image_embeds=3,
               tables=1, code_blocks=1))
    rows = dict((r["url"] if "url" in r else r["tag"], r) for r in media)
    check("source rows: chrome, lazy image with its figure caption, "
          "pictures, Lottie, video, iframe, canvas, svg and an empty figure, "
          "in document order",
          [r.get("url") or r.get("lottie") or r["tag"] for r in media],
          ["https://site.test/blog/logo.png",
           "https://site.test/blog/img/a.png",
           "https://site.test/blog/b-1200.webp",
           "https://site.test/blog/anim/spin.json",
           "https://site.test/blog/poster.png",
           "https://cdn.test/x.lottie",
           "https://site.test/blog/v.mp4",
           "https://player.test/embed/1", "canvas", "svg", "figure",
           "https://site.test/blog/f.png"])
    check("a lazy figure image keeps its placeholder src, alt, caption, "
          "figure number and heading",
          rows["https://site.test/blog/img/a.png"],
          {"line": 8, "tag": "img", "url": "https://site.test/blog/img/a.png",
           "src": "data:image/gif;base64,… (28 chars)", "alt": "Chart A",
           "caption": "Figure 1. Growth.", "figure": 1,
           "heading": "Charts"})
    check("a Lottie player and its poster share one figure",
          [(r.get("figure"), r.get("heading")) for r in media
           if r.get("figure") == 2],
          [(2, "Animation"), (2, "Animation")])
    check("a video takes its <source> and poster",
          (rows["https://site.test/blog/v.mp4"].get("poster")),
          "https://site.test/blog/v.jpg")
    check("chrome rows are tagged; a header inside an article is not",
          (rows["https://site.test/blog/logo.png"].get("in"),
           rows["https://site.test/blog/f.png"].get("in"),
           rows["svg"].get("alt")),
          ("nav", "footer", "diagram"))
    check("a figure with no media is one row carrying its caption",
          (rows["figure"]["caption"], rows["figure"]["figure"]),
          ("Table 1", 3))
    check("without --base-url relative URLs stay as given, with a note",
          (source_report("<img src=\"a/b.png\">")[2][0]["url"],
           source_report("<img src=\"a/b.png\">")[3]),
          ("a/b.png", ["no --base-url: relative URLs are left unresolved"]))
    check("an unclosed figure is still reported, its caption attached",
          source_report("<figure><img src=\"https://x.test/a.png\">"
                        "<figcaption>Cap", "https://x.test/")[2],
          [{"line": 1, "tag": "img", "url": "https://x.test/a.png",
            "caption": "Cap", "figure": 1}])
    check("a heading inside an aside is not the heading of later content",
          [r.get("heading") for r in source_report(
              "<article><h2>Results</h2><aside><h3>Read more</h3></aside>"
              "<figure><img src=\"chart.png\"><figcaption>Figure 2"
              "</figcaption></figure></article>", "https://x.test/")[2]],
          ["Results"])
    hidden = source_report(
        "<h1>Title</h1><h2 class='screen-reader-text'>Introduction</h2>"
        "<figure><img src=\"a.png\"></figure>", "https://x.test/")
    check("a screen-reader-only heading is tagged hidden and is not the "
          "heading of later content",
          (hidden[0], [r.get("heading") for r in hidden[2]]),
          ([(1, "Title", None), (2, "Introduction", "hidden")], ["Title"]))
    check("a gallery's nested figures give captioned media rows, no stub",
          [(r["tag"], r.get("caption")) for r in source_report(
              "<figure class=\"wp-block-gallery\"><figure><img src=a.jpg>"
              "</figure><figure><img src=b.jpg></figure>"
              "<figcaption>Two views</figcaption></figure>",
              "https://x.test/")[2]],
          [("img", "Two views"), ("img", "Two views")])
    check("a lazy iframe reports its embed URL, not about:blank",
          source_report("<iframe src=\"about:blank\" data-lazy-src="
                        "\"https://www.youtube.com/embed/xyz\"></iframe>",
                        "https://x.test/")[2][0].get("url"),
          "https://www.youtube.com/embed/xyz")
    check("a noscript image the page did not list is reported and tagged",
          [(r["url"], r.get("noscript")) for r in source_report(
              "<noscript><img src=\"https://x.test/n.png\"></noscript>",
              "https://x.test/")[2]],
          [("https://x.test/n.png", True)])

    with tempfile.TemporaryDirectory() as tmp:
        markup = os.path.join(tmp, "page.html")
        with open(markup, "w", encoding="utf-8") as fh:
            fh.write(page)
        before = os.stat(markup).st_mtime_ns
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["source", markup, "--base-url",
                         "https://site.test/post/1"])
        lines = out.getvalue().split("\n")
        media_at = lines.index("MEDIA:")
        check("the source command prints headings, counts and one JSON row "
              "per media element, and leaves the file unchanged",
              (code, lines[0], lines[media_at - 1].startswith("COUNTS: {"),
               len([json.loads(x) for x in lines[media_at + 1:] if x]),
               os.stat(markup).st_mtime_ns == before),
              (0, "HEADINGS:", True, len(media), True))

    check("stacked collapse keeps the last marker",
          collapse_stacked_markers("- - **Q:** why"), "- **Q:** why")
    check("stacked collapse works inside a blockquote",
          collapse_stacked_markers("> - - - **A:** x"), "> - **A:** x")
    check("stacked collapse handles ordered markers",
          collapse_stacked_markers("1. 1. text"), "1. text")
    check("stacked collapse leaves a spaced rule, quoted or not",
          (collapse_stacked_markers("* * *"),
           collapse_stacked_markers("> - - -")), ("* * *", "> - - -"))
    check("a stacked repair over a spaced rule changes only the stacked line",
          [c["line"] for c in plan_repair("- - -\n- - text", "stacked",
                                          "1-2")[1]], [2])
    check("overindent collapses 2+ tabs to one",
          collapse_overindent("> \t\t\t\t- **B:** y"), "> \t- **B:** y")
    check("overindent leaves a one-tab line alone",
          collapse_overindent("\t- ok"), "\t- ok")
    check("dedent strips exactly one tab",
          dedent_one_tab("> \t\t- x"), "> \t- x")
    check("line ranges parse and merge", parse_ranges("3,1-2,2", 5), [1, 2, 3])
    for bad in ("0", "4-2", "6", "x"):
        try:
            parse_ranges(bad, 5)
            outcome = "accepted"
        except RepairError:
            outcome = "refused"
        check("bad range %r is refused" % bad, outcome, "refused")
    new, changed, skipped = plan_repair(
        "---\nk: v\n---\n- a\n\t- b\n```\n\t- code\n```", "dedent", "2,5,7")
    check("repair changes only listed prose lines",
          (new.split("\n")[4], [c["line"] for c in changed],
           [s["line"] for s in skipped]),
          ("- b", [5], [2, 7]))
    new, changed, skipped = plan_repair(bom, "stacked", "1-5")
    check("a BOM does not let repair touch YAML",
          (new == bom, changed, [s["line"] for s in skipped]),
          (True, [], [1, 2, 3, 4, 5]))
    qa = ("- - **Q:** how do I loop?\n\t\t- **A:** like this:\n\t\t\t```go\n"
          "\t\t\tfor i := range xs {\n\t\t\t\tfmt.Println(\"$HOME\", i)\n"
          "\t\t\t}\n\t\t\t```")
    check("overindent moves a nested fenced block whole, keeping the code's "
          "own indent", plan_repair(qa, "overindent", "2-7")[0].split("\n")[1:],
          ["\t- **A:** like this:", "\t```go", "\tfor i := range xs {",
           "\t\tfmt.Println(\"$HOME\", i)", "\t}", "\t```"])
    peer = "> - a\n> \t- b\n> \t\t```\n> \t\tx\n> \t\t\ty\n> \t\t```"
    check("dedent shifts a peer item and its whole nested block by one tab",
          plan_repair(peer, "dedent", "2-6")[0],
          "> - a\n> - b\n> \t```\n> \tx\n> \t\ty\n> \t```")
    check("stacked skips every line of a nested fenced block",
          [s["line"] for s in plan_repair(qa, "stacked", "1-7")[2]],
          [3, 4, 5, 6, 7])

    with tempfile.TemporaryDirectory() as tmp:
        draft = os.path.join(tmp, "draft.md")
        with open(draft, "w", encoding="utf-8", newline="") as fh:
            fh.write("- - a\r\n\t\t- b\n")
        os.chmod(draft, 0o600)
        payload, code = cmd_repair(draft, "stacked", "1", dry_run=True)
        with open(draft, encoding="utf-8", newline="") as fh:
            unchanged = fh.read()
        check("a dry run reports without writing",
              (code, len(payload["changed"]), unchanged),
              (0, 1, "- - a\r\n\t\t- b\n"))
        payload, code = cmd_repair(draft, "overindent", "2")
        with open(draft, encoding="utf-8", newline="") as fh:
            written = fh.read()
        check("a repair rewrites the draft in place, keeping line endings "
              "and mode", (code, written, os.stat(draft).st_mode & 0o777),
              (0, "- - a\r\n\t- b\n", 0o600))
        with open(draft, "w", encoding="utf-8", newline="") as fh:
            fh.write(qa)
        payload, code = cmd_repair(draft, "overindent", "2-5")
        with open(draft, encoding="utf-8", newline="") as fh:
            unchanged = fh.read()
        check("a range covering part of a nested fenced block is refused "
              "unchanged", (code, payload["error"], unchanged),
              (1, "lines 3-7 are one fenced code block: list all of it or "
               "none", qa))
        vault = os.path.join(tmp, "vault")
        os.makedirs(os.path.join(vault, ".obsidian"))
        os.makedirs(os.path.join(vault, "Articles"))
        note = os.path.join(vault, "Articles", "n.md")
        with open(note, "w", encoding="utf-8") as fh:
            fh.write("- - a\n")
        payload, code = cmd_repair(note, "stacked", "1")
        with open(note, encoding="utf-8") as fh:
            kept = fh.read()
        check("a note inside a vault is refused unchanged",
              (code, payload["ok"], kept), (1, False, "- - a\n"))

    failed = [c for c in cases if not c[1]]
    for label, _ok, got, want in failed:
        print("FAIL %s\n  got:  %r\n  want: %r" % (label, got, want))
    print("%d/%d self-test cases pass" % (len(cases) - len(failed), len(cases)))
    return 1 if failed else 0


# --- command line ---------------------------------------------------------------

def _configure_stdout():
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (OSError, ValueError):
            pass


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def build_parser():
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--test", action="store_true", help="run the self-test")
    sub = ap.add_subparsers(dest="command")
    for name, help_text in (
            ("sweep", "the review checklist's mechanical sweep"),
            ("siblings", "single-tab sibling-split candidates (item 12b)"),
            ("outline", "heading outline and coarse structure counts")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("path", metavar="PATH")
    source = sub.add_parser(
        "source", help="outline, counts and media rows of saved page markup")
    source.add_argument("--base-url", metavar="URL",
                        help="the capture URL relative sources resolve against")
    source.add_argument("path", metavar="PATH")
    repair = sub.add_parser("repair", help="apply one confirmed list repair")
    repair.add_argument("--op", required=True, choices=sorted(REPAIRS))
    repair.add_argument("--lines", required=True, metavar="RANGES",
                        help="1-based lines, e.g. 12 or 12-18,21")
    repair.add_argument("--dry-run", action="store_true",
                        help="report the change without writing")
    repair.add_argument("path", metavar="PATH")
    return ap


def main(argv=None):
    _configure_stdout()
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.test:
        return run_self_test()
    if not args.command:
        ap.error("give a subcommand (sweep, siblings, outline, source, repair) "
                 "or --test")
    if args.command == "repair":
        payload, code = cmd_repair(args.path, args.op, args.lines, args.dry_run)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return code
    try:
        text = _read(args.path)
    except OSError as exc:
        print("cannot read %s: %s" % (args.path, exc), file=sys.stderr)
        return 1
    if args.command == "siblings":
        hits = sibling_candidates(text.split("\n"))
        for n, raw in hits:
            print("L%d: sibling +1 tab under an earlier flush item (renders "
                  "as nested): %s" % (n, raw[:70]))
        if not hits:
            print("(none)")
        return 0
    if args.command == "outline":
        heads, counts = outline_report(text)
        print("HEADINGS:")
        for level, title in heads:
            print("  %s %s" % ("#" * level, title))
        print("COUNTS:", json.dumps(counts))
        return 0
    if args.command == "source":
        heads, counts, media, notes = source_report(text, args.base_url)
        for note in notes:
            print("[note] " + note)
        print("HEADINGS:")
        for level, title, chrome in heads:
            print("  %s %s%s" % ("#" * level, title,
                                 "  [%s]" % chrome if chrome else ""))
        print("COUNTS:", json.dumps(counts))
        print("MEDIA:")
        for row in media or ["(none)"]:
            print("  " + (row if isinstance(row, str)
                          else json.dumps(row, ensure_ascii=False)))
        return 0
    report, notes = sweep_report(text)
    for note in notes:
        print("[note] " + note)
    for header, results in report:
        print("[%s]" % header)
        for line in results or ["(none)"]:
            print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
