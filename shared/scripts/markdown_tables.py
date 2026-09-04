#!/usr/bin/env python3
"""Shared Markdown-table span parsing for the Obsidian Wiki skills.

The parser is a conservative GFM structural floor, not a renderer.  Callers
mask fenced and indented-code listings before passing text to
``markdown_table_spans``; returned inclusive line spans retain the original
line numbering. Inline code stays visible because GFM finds table cell
separators before parsing inline spans; a pipe inside code must be escaped.
Stdlib only, Python 3.8+.
"""

import argparse
import re

__all__ = ["caption_faults", "markdown_block_start", "markdown_table_spans",
           "mask_line_spans"]


_TABLE_DELIM_RE = re.compile(
    r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)+\|?\s*$")
_ONE_COLUMN_TABLE_DELIM_RE = re.compile(
    r"^\s*\|\s*:?-+:?\s*\|\s*$")
_BLOCK_HTML_TAGS = (
    "address|article|aside|base|basefont|blockquote|body|caption|center|col|"
    "colgroup|dd|details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|"
    "footer|form|frame|frameset|h1|h2|h3|h4|h5|h6|head|header|hr|html|"
    "iframe|legend|li|link|main|menu|menuitem|nav|noframes|ol|optgroup|"
    "option|p|param|section|source|summary|table|tbody|td|tfoot|th|thead|"
    "title|tr|track|ul"
)
_INLINE_HTML_TAGS = (
    "a|abbr|b|bdi|bdo|br|button|cite|code|data|del|dfn|em|i|img|ins|"
    "kbd|label|mark|q|ruby|s|samp|small|span|strong|sub|sup|time|u|var|wbr"
)
_HTML_TAG_RE = re.compile(
    r"</?(?:" + _BLOCK_HTML_TAGS + "|" + _INLINE_HTML_TAGS
    + r")(?:[ \t]|/?>|$)", re.IGNORECASE)
_TABLE_BLOCK_START_RE = re.compile(
    r"^ {0,3}(?:"
    r"#{1,6}(?:[ \t]+|$)|>|(?:[-+*]|[0-9]{1,9}[.)])(?:[ \t]+|$)|"
    r"(?:`{3,}|~{3,})|\[[^\]\n]+\]:[ \t]*(?=\S)|"
    r"<!--|<\?|<![A-Z]|<!\[CDATA\[|"
    r"</?(?:script|pre|style)(?:[ \t]|>|$)|"
    r"</?(?:" + _BLOCK_HTML_TAGS + r")(?:[ \t]|/?>|$)|"
    r"</?[A-Za-z][A-Za-z0-9-]*(?:[ \t]+[^<>\n]*)?/?>[ \t]*$)",
    re.IGNORECASE)
_THEMATIC_BREAK_RE = re.compile(
    r"^ {0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$")
_CAPTION_MATH_RE = re.compile(r"\$\$[^$\n]*\$\$|\$[^$\n]*\$")
_CAPTION_DISPLAY_MATH_RE = re.compile(r"\$\$[^$\n]*\$\$")
_NESTED_ASTERISK_ITALIC_RE = re.compile(
    r"(?<![\\*])\*(?!\*)(?=\S)[^*\n]*?(?<=\S)(?<!\\)\*(?!\*)")
_NESTED_UNDERSCORE_ITALIC_RE = re.compile(
    r"(?<![\\\w])_(?=\S)[^_\n]*?(?<=\S)(?<!\\)_(?!\w)")


def _is_table_delimiter(line):
    return bool(_TABLE_DELIM_RE.match(line)
                or _ONE_COLUMN_TABLE_DELIM_RE.match(line))


def _unescaped_pipe_positions(line):
    positions = []
    for index, character in enumerate(line or ""):
        if character != "|":
            continue
        backslashes, cursor = 0, index - 1
        while cursor >= 0 and line[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2 == 0:
            positions.append(index)
    return positions


def _table_cell_count(line):
    """Count GFM cells from unescaped separators, excluding outer pipes."""
    positions = _unescaped_pipe_positions(line)
    if not positions:
        return 1
    leading = not line[:positions[0]].strip()
    trailing = not line[positions[-1] + 1:].strip()
    return len(positions) + 1 - int(leading) - int(trailing)


def _has_table_separator(line):
    """Whether a line contains an unescaped pipe outside inline LaTeX."""
    without_math = _CAPTION_MATH_RE.sub("", line)
    return bool(re.search(r"(?<!\\)\|", without_math))


def _is_caption_candidate(line):
    """Whether ``line`` has this vault's whole-line italic caption shape."""
    stripped = (line or "").strip()
    return bool(len(stripped) >= 3
                and stripped.startswith("*") and not stripped.startswith("**")
                and stripped.endswith("*") and not stripped.endswith("**")
                and not _has_table_separator(line))


def _is_table_body_row(line):
    """Whether a non-header line continues a detected GFM table."""
    if not (line or "").strip() or _is_caption_candidate(line):
        return False
    stripped = line.strip()
    if _TABLE_BLOCK_START_RE.match(line):
        return False
    if _THEMATIC_BREAK_RE.fullmatch(line):
        return False
    return True


def markdown_block_start(line):
    """Whether one raw line starts a structural Markdown block.

    This shares the parser's CommonMark/GFM floor with callers that must tell
    a prose paragraph from a heading, list, quote, fence, reference definition,
    HTML block, or thematic break. Tables still require the following
    delimiter line and are therefore handled by ``markdown_table_spans``.
    """
    return bool(_TABLE_BLOCK_START_RE.match(line or "")
                or _THEMATIC_BREAK_RE.fullmatch(line or ""))


def markdown_table_spans(masked_body):
    """Return inclusive ``(header_line, last_row_line)`` table spans.

    ``masked_body`` must preserve line count while blanking code/listing
    content.  A body row may contain fewer cells than the header, including no
    pipe at all.  A blank, new block, horizontal rule, or immediate italic
    caption ends the table.  A caption containing LaTeX bars still ends it;
    an emphasized row with a real cell separator does not.
    """
    lines = (masked_body or "").split("\n")
    tables, consumed_through = [], -1
    for index in range(1, len(lines)):
        if index <= consumed_through or not _is_table_delimiter(lines[index]):
            continue
        if (not lines[index - 1].strip()
                or not _unescaped_pipe_positions(lines[index - 1])):
            continue
        if _table_cell_count(lines[index - 1]) != _table_cell_count(lines[index]):
            continue
        end = index
        while end + 1 < len(lines) and _is_table_body_row(lines[end + 1]):
            end += 1
        tables.append((index - 1, end))
        consumed_through = end
    return tables


def mask_line_spans(text, spans):
    """Blank inclusive line spans while preserving line/character offsets."""
    lines = (text or "").split("\n")
    for start, end in spans or ():
        for index in range(max(0, start), min(len(lines), end + 1)):
            lines[index] = " " * len(lines[index])
    return "\n".join(lines)


def caption_faults(caption):
    """Return deterministic faults for this vault's caption format."""
    cap = (caption or "").strip()
    if not (cap.startswith("*") and not cap.startswith("**")
            and cap.endswith("*") and not cap.endswith("**") and len(cap) >= 3):
        return ["missing italic caption"]
    inner = cap[1:-1]
    if not inner.strip():
        return ["empty"]
    # Markdown emphasis delimiters cannot have inner-edge whitespace, and an
    # odd backslash run escapes the apparent closing marker.
    closing_backslashes = 0
    cursor = len(cap) - 2
    while cursor >= 0 and cap[cursor] == "\\":
        closing_backslashes += 1
        cursor -= 1
    if (inner[:1].isspace() or inner[-1:].isspace()
            or closing_backslashes % 2):
        return ["missing italic caption"]
    # Inline LaTeX is the sole permitted inner markup.  Mask it before inspecting
    # Markdown emphasis so mathematical stars/underscores are not mistaken for
    # nested styling.
    prose = _CAPTION_MATH_RE.sub("", inner)
    faults = []
    if _CAPTION_DISPLAY_MATH_RE.search(inner):
        faults.append("display math")
    if "[[" in inner:
        faults.append("wikilink")
    if (re.search(r"!?\[[^\]\n]*\]\([^)\n]*\)", prose)
            or re.search(r"!?\[[^\]\n]+\]\[[^\]\n]*\]", prose)):
        faults.append("Markdown link")
    if _HTML_TAG_RE.search(prose):
        faults.append("HTML")
    if "~~" in prose:
        faults.append("strikethrough")
    if "`" in inner:
        faults.append("backtick")
    has_bold = "**" in prose or "__" in prose
    if has_bold:
        faults.append("bold")
    else:
        if (_NESTED_ASTERISK_ITALIC_RE.search(prose)
                or _NESTED_UNDERSCORE_ITALIC_RE.search(prose)):
            faults.append("italic")
        elif re.search(r"(?<!\\)\*", prose):
            faults.append("italic")
    return faults


def _self_test():
    cases = [
        ("block-start helper recognizes structural Markdown",
         [markdown_block_start(value) for value in (
             "A prose sentence.", "+ item", "1) item", ">quoted",
             "```python", "[ref]: https://example.test", "<div>", "---")],
         [False] + [True] * 7),
        ("ordinary table",
         markdown_table_spans(
             "Method | Score\n--- | ---\nA | 0.8\n*Scores.*"),
         [(0, 2)]),
        ("GFM permits one-hyphen delimiter cells",
         markdown_table_spans(
             "Method | Score\n- | -\nA | 0.8\n*Scores.*"),
         [(0, 2)]),
        ("leading-pipe table",
         markdown_table_spans(
             "| Method | Score |\n| --- | --- |\n| A | 0.8 |\n*Scores.*"),
         [(0, 2)]),
        ("one-column table",
         markdown_table_spans("| Metric |\n| --- |\n| Recall |\n*Metric.*"),
         [(0, 2)]),
        ("pipe-less short body row",
         markdown_table_spans("Metric | Note\n--- | ---\nRecall\n*Metric.*"),
         [(0, 2)]),
        ("emphasized row with a separator is not a caption",
         markdown_table_spans(
             "Metric | Value\n--- | ---\n*Recall* | *0.8*\n*Metric.*"),
         [(0, 2)]),
        ("LaTeX bar remains inside the caption",
         markdown_table_spans(
             "Metric | Value\n--- | ---\nError | 0.2\n*Error is $|x-y|$.*"),
         [(0, 2)]),
        ("display-LaTeX bar remains inside the caption",
         markdown_table_spans(
             "Metric | Value\n--- | ---\nError | 0.2\n*Error is $$|x-y|$$.*"),
         [(0, 2)]),
        ("heading ends a table with no body rows",
         markdown_table_spans("Metric | Value\n--- | ---\n## Next"),
         [(0, 1)]),
        ("prose pipes without a delimiter are not a table",
         markdown_table_spans("A | B\nordinary prose | still prose"),
         []),
        ("header and delimiter cell counts must match",
         markdown_table_spans("A | B\n| --- |\nvalue"), []),
        ("a raw pipe inside inline code is still a cell separator",
         markdown_table_spans("A | `x|y`\n--- | ---\nvalue | other"), []),
        ("an escaped pipe inside inline code stays in its cell",
         markdown_table_spans(
             r"A | `x\|y`" "\n--- | ---\nvalue | other\n*Caption.*"),
         [(0, 2)]),
        ("escaped header pipes do not create extra cells",
         markdown_table_spans(
             r"A \| name | B" "\n--- | ---\nvalue | other\n*Caption.*"),
         [(0, 2)]),
        ("an escaped content pipe cannot establish a one-column header",
         markdown_table_spans(
             r"Metric \| score" "\n| --- |\nvalue"),
         []),
        ("block HTML ends the table",
         markdown_table_spans(
             "A | B\n--- | ---\nvalue | other\n<div>next</div>"),
         [(0, 2)]),
        ("a link-reference definition ends the table",
         markdown_table_spans(
             "A | B\n--- | ---\nvalue | other\n[ref]: /target"),
         [(0, 2)]),
        ("a spaced thematic break ends the table",
         markdown_table_spans(
             "A | B\n--- | ---\nvalue | other\n- - -"),
         [(0, 2)]),
        ("a standalone type-7 HTML tag ends the table",
         markdown_table_spans(
             'A | B\n--- | ---\nvalue | other\n<a href="x">'),
         [(0, 2)]),
        ("an empty list marker ends the table",
         markdown_table_spans("A | B\n--- | ---\nvalue | other\n1."),
         [(0, 2)]),
        ("a ten-digit pseudo-list marker remains a table row",
         markdown_table_spans(
             "A | B\n--- | ---\nvalue | other\n1234567890. value"),
         [(0, 3)]),
        ("an empty invalid link-reference prefix remains a table row",
         markdown_table_spans("A | B\n--- | ---\nvalue | other\n[ref]:"),
         [(0, 3)]),
        ("span masking preserves offsets",
         mask_line_spans("alpha\nbeta\ngamma", [(1, 1)]),
         "alpha\n    \ngamma"),
        ("plain italic caption", caption_faults("*A plain caption.*"), []),
        ("LaTeX bars and stars are permitted",
         caption_faults("*Error is $|x-y|$ and $x^*$.*"), []),
        ("missing caption italics", caption_faults("A plain caption."),
         ["missing italic caption"]),
        ("empty caption", caption_faults("* *"), ["empty"]),
        ("caption wikilink", caption_faults("*A [[target|label]].*"),
         ["wikilink"]),
        ("caption Markdown link", caption_faults("*A [label](target).*"),
         ["Markdown link"]),
        ("caption HTML", caption_faults("*A <span>label</span>.*"),
         ["HTML"]),
        ("mathematical comparisons are not invented HTML tags",
         caption_faults("*For x<y and p>q, the condition holds.*"), []),
        ("caption strikethrough", caption_faults("*A ~~label~~.*"),
         ["strikethrough"]),
        ("caption backtick", caption_faults("*A `label`.*"),
         ["backtick"]),
        ("caption bold", caption_faults("*A **label**.*"), ["bold"]),
        ("caption nested italic", caption_faults("*A _label_.*"),
         ["italic"]),
        ("caption outer italics reject inner-edge whitespace",
         caption_faults("* Caption *"), ["missing italic caption"]),
        ("caption outer italics reject an escaped closing marker",
         caption_faults(r"*Caption\*"), ["missing italic caption"]),
        ("caption display math is not inline math",
         caption_faults("*Error is $$|x-y|$$.*"), ["display math"]),
        ("caption reference-style Markdown link",
         caption_faults("*A [label][reference].*"), ["Markdown link"]),
    ]
    bad = [(name, got, want) for name, got, want in cases if got != want]
    for name, got, want in bad:
        print("FAIL %s: got %r, want %r" % (name, got, want))
    print("%d/%d Markdown-table self-test cases pass"
          % (len(cases) - len(bad), len(cases)))
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
