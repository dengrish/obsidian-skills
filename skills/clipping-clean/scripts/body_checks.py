#!/usr/bin/env python3
"""Mechanical checks and region-scoped list repairs for a clipping draft.

Every check here finds *candidates*: a match is a place to inspect against the
source, never permission to rewrite. The rules that decide what a match means
are in references/review-checklist.md and references/nested-lists.md.

  sweep PATH      the review checklist's numbered mechanical sweep (1-15,
                  including 12b), each with its expectation and the matching
                  lines. The leading YAML block and fenced code are skipped;
                  an unclosed fence is reported and its lines are scanned.
  siblings PATH   sweep item 12b alone: list items one tab deep that follow an
                  earlier flush item of the same list block, which renders as
                  nesting. Blank lines, quoted or not, do not end a list.
  outline PATH    the heading outline and coarse counts (list lines, quote
                  lines, links, image embeds, tables, code blocks) for
                  comparing the draft's structure with the source.
  repair --op OP --lines RANGES PATH [--dry-run]
                  apply one confirmed nested-list repair to the listed lines
                  only (1-based, `12` or `12-18`, comma-separated), keeping any
                  blockquote prefix. OP is `stacked` (collapse a run of list
                  markers to one), `overindent` (collapse two or more leading
                  tabs to one) or `dedent` (strip exactly one leading tab).
                  YAML and fenced-code lines are never changed. The draft is
                  rewritten in place; a path inside an Obsidian vault is
                  refused, because a draft belongs in the run's scratch.

    python3 '<skill>/scripts/body_checks.py' sweep '<draft>'
    python3 '<skill>/scripts/body_checks.py' repair --op dedent --lines '41-44' '<draft>'

Output is plain text, except `repair`, which prints JSON. Exit 0 when the file
was read (matches are not failures), 1 when it could not be read or a repair
was refused, 2 for a usage error. Stdlib only.
Run ``python3 body_checks.py --test`` for the self-test.
"""

import argparse
import json
import os
import re
import sys
import tempfile


#: POSIX [[:space:]] without the newline a split line never carries.
SP = r"[ \t\r\f\v]"

#: A fenced-code opener or closer, optionally inside a blockquote.
FENCE_RE = re.compile(r"^((?:>[ \t]?)*)[ ]{0,3}(`{3,}|~{3,})(.*)$")

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
STACKED_RE = re.compile(
    r"^(?:>%s?)*%s*(?:[-*]|[0-9]+\.)(?:%s+(?:[-*]|[0-9]+\.))+%s"
    % (SP, SP, SP, SP))
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
HR_RE = re.compile(r"^(?:[-*_]{3,}|<hr>)%s*$" % SP)
SEPARATOR_RE = re.compile(r"^___%s*$" % SP)

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
    """Index of the first body line after a leading YAML block, else 0."""
    if lines and lines[0].rstrip() == "---":
        for i in range(1, len(lines)):
            if lines[i].rstrip() in ("---", "..."):
                return i + 1
    return 0


def code_regions(lines, start=0):
    """``(set of 0-based fenced lines, [unclosed opener indexes], [opener
    indexes of closed blocks])``.

    Fence lines count as code. An opener with no closer is not treated as a
    fence, so a damaged fence cannot hide the rest of the note from the sweep.
    """
    inside, unclosed, openers = set(), [], []
    i = start
    while i < len(lines):
        m = FENCE_RE.match(lines[i])
        if m and not (m.group(2)[0] == "`" and "`" in m.group(3)):
            char, width = m.group(2)[0], len(m.group(2))
            j = i + 1
            while j < len(lines):
                c = FENCE_RE.match(lines[j])
                if (c and c.group(2)[0] == char and len(c.group(2)) >= width
                        and not c.group(3).strip()):
                    break
                j += 1
            if j < len(lines):
                inside.update(range(i, j + 1))
                openers.append(i)
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
    ends only at an unindented paragraph that follows a blank line, or at
    fenced code. Every item exactly one tab deep that comes after an earlier
    flush item of the same block is reported, even when a stray indented item
    precedes that flush item. Genuine parent-child nesting has the same
    shape, so every hit is a candidate to judge against the source.
    """
    start = frontmatter_end(lines)
    inside, _unclosed, _openers = code_regions(lines, start)
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


# --- region-scoped repairs --------------------------------------------------

def _split_quote(line):
    m = QUOTED_RE.match(line)
    return (m.group(1), m.group(2)) if m else ("", line)


def collapse_stacked_markers(line):
    """`- - text` -> `- text`; the last marker of the run is kept."""
    prefix, body = _split_quote(line)
    m = STACKED_MARKERS_RE.match(body)
    if m:
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


def plan_repair(text, op, spec):
    """``(new text, changed, skipped)`` for one repair over the listed lines."""
    if op not in REPAIRS:
        raise RepairError("unknown repair %r" % op)
    lines = text.split("\n")
    start = frontmatter_end(lines)
    inside, _unclosed, _openers = code_regions(lines, start)
    changed, skipped = [], []
    for n in parse_ranges(spec, len(lines)):
        i = n - 1
        if i < start or i in inside:
            skipped.append({"line": n, "reason": "YAML or fenced code"})
            continue
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
    report, notes = sweep_report("x\n```\nnever closed\n# heading")
    check("an unclosed fence is reported and scanned as prose",
          (notes, dict((h.split()[0], r) for h, r in report)["1"]),
          (["unclosed code fence at L2: scanned as prose; check the fence"],
           ["L4: # heading"]))
    check("every numbered sweep item is present, 12b included",
          [h.split()[0] for h, _r in sweep_report("")[0]],
          ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12",
           "12b", "13", "14", "15"])
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

    check("stacked collapse keeps the last marker",
          collapse_stacked_markers("- - **Q:** why"), "- **Q:** why")
    check("stacked collapse works inside a blockquote",
          collapse_stacked_markers("> - - - **A:** x"), "> - **A:** x")
    check("stacked collapse handles ordered markers",
          collapse_stacked_markers("1. 1. text"), "1. text")
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
        ap.error("give a subcommand (sweep, siblings, outline, repair) or --test")
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
