#!/usr/bin/env python3
"""Shared detection of literal prose shapes that require backticks.

wiki-build permits two code-like shapes in every entry type: bracket special
tokens such as ``[CLS]`` and literal file extensions such as ``.csv``. Both
must be backticked in running prose. Callers first blank fenced, indented, and
inline code, then pass the line-preserving result here. Math, link/embed and URL
syntax, table spans, headings, and whole-line italic captions are excluded
because they either do not render the literal shape or have their own formatting
rules.

The extension list is deliberately conservative. A generic ``.word`` pattern
would misclassify domains, prose punctuation, and method names; the executing
agent's semantic pass remains responsible for uncommon extensions outside this common
set.

Stdlib only, Python 3.10+ (the plugin runtime floor).
"""

import argparse
import re

__all__ = ["find_bare_code_shapes"]


SPECIAL_TOKENS = ("CLS", "MASK", "SEP", "IMG")
FILE_EXTENSIONS = (
    # Documents, data, configuration, and notebooks.
    "csv", "tsv", "json", "yaml", "yml", "xml", "txt", "md", "pdf",
    "docx", "xlsx", "pptx", "epub", "ipynb", "toml", "ini", "log",
    # Code, markup, and compiled artifacts commonly named in wiki prose.
    "py", "r", "js", "ts", "html", "css", "sql", "sh", "tex", "cpp",
    "java", "so", "dll", "dylib", "exe",
    # Arrays, models, archives, graphs, and media.
    "npy", "npz", "pkl", "pickle", "parquet", "h5", "hdf5", "pt",
    "pth", "onnx", "zip", "tar", "gz", "bz2", "xz", "dot", "png",
    "jpg", "jpeg", "gif", "svg", "webp", "avif", "bmp", "tif",
    "tiff", "ico", "lottie",
)

_SPECIAL_RE = re.compile(
    r"(?<![!\[])\[(?:"
    + "|".join(re.escape(token) for token in SPECIAL_TOKENS)
    + r")\](?!\])")
_EXTENSION_ALT = "|".join(sorted((re.escape(ext) for ext in FILE_EXTENSIONS),
                                 key=len, reverse=True))
# A compound extension that starts with a known one, such as ``.tar.gz`` or
# ``.tar.zst``, is one literal shape and is reported whole. A dot that follows
# another dot or an ellipsis, as in ``...so`` or ``1..r``, is punctuation, not
# a file extension.
_EXTENSION_RE = re.compile(
    r"(?<![\w/`.…])\.(?:%s)(?:\.[A-Za-z0-9]{1,10})*(?![\w`])"
    % _EXTENSION_ALT,
    re.IGNORECASE,
)
_DISPLAY_MATH_RE = re.compile(r"\$\$.*?\$\$", re.DOTALL)
_INLINE_MATH_RE = re.compile(r"(?<!\$)\$[^$\n]*\$(?!\$)")
_URL_RE = re.compile(r"\b(?:https?|ftp)://\S+", re.IGNORECASE)
_WIKILINK_RE = re.compile(r"!?\[\[[^\]\n]+\]\]")
_MARKDOWN_LINK_RE = re.compile(
    r"!?\[(?:[^\[\]\n]|\[[^\[\]\n]*\])*\]\s*"
    r"(?:\((?:[^()\n]|\([^()\n]*\))*\)|\[[^\]\n]*\])")
_HEADING_RE = re.compile(r"^ {0,3}#{1,6}(?:[ \t]+|$)")
_CAPTION_RE = re.compile(r"^\s*\*(?!\*)\S(?:.*\S)?\*\s*$")


def _replace_escaped_dollars(text):
    """Blank dollar signs escaped by an odd backslash run, length preserved."""
    chars = list(text or "")
    for index, char in enumerate(chars):
        if char != "$":
            continue
        backslashes, cursor = 0, index - 1
        while cursor >= 0 and chars[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2:
            chars[index] = " "
    return "".join(chars)


def find_bare_code_shapes(masked_text, excluded_line_spans=()):
    """Return bare special-token/extension occurrences in running prose.

    Results are dictionaries with ``kind``, ``token``, and one-based ``line``.
    ``masked_text`` must retain original line breaks after code/listings have
    been blanked. ``excluded_line_spans`` contains inclusive zero-based table
    spans, as returned by ``markdown_tables.markdown_table_spans``.
    """
    excluded = set()
    for start, end in excluded_line_spans or ():
        excluded.update(range(max(0, start), max(0, end) + 1))

    math_source = _replace_escaped_dollars(masked_text or "")
    math_masked = _DISPLAY_MATH_RE.sub(
        lambda match: "".join("\n" if char == "\n" else " "
                              for char in match.group(0)),
        math_source)
    findings = []
    for line_index, raw_line in enumerate(math_masked.split("\n")):
        if line_index in excluded:
            continue
        if _HEADING_RE.match(raw_line) or _CAPTION_RE.match(raw_line):
            continue
        line = _WIKILINK_RE.sub(lambda match: " " * len(match.group(0)), raw_line)
        line = _MARKDOWN_LINK_RE.sub(
            lambda match: " " * len(match.group(0)), line)
        line = _URL_RE.sub(lambda match: " " * len(match.group(0)), line)
        line = _INLINE_MATH_RE.sub(
            lambda match: " " * len(match.group(0)), line)
        matches = [(match.start(), "special token", match.group(0))
                   for match in _SPECIAL_RE.finditer(line)]
        matches.extend((match.start(), "file extension", match.group(0))
                       for match in _EXTENSION_RE.finditer(line))
        for _offset, kind, token in sorted(matches):
            findings.append({"kind": kind, "token": token,
                             "line": line_index + 1})
    return findings


def run_self_test(verbose=False):
    cases = [
        ("known special tokens", "Use [CLS], [MASK], [SEP], and [IMG].", 4),
        ("common literal extensions", "Save .csv, .JSON, and .ipynb files.", 3),
        ("domains, decimals, and filenames", "Version 4.5 at example.com uses file.csv.", 0),
        ("paths do not masquerade as literal extensions", "See /tmp/.csv and ./note.md.", 0),
        ("URL path extensions stay part of the destination",
         "![Plot](https://example.test/plot_(x).png)", 0),
        ("wikilinks and embeds are link syntax, not literal special tokens",
         "See [[CLS]] and ![[MASK]] entries.", 0),
        ("Markdown labels and local destinations keep their own syntax",
         "[CLS](token.md) and ![Plot [MASK]](plot_(x).png)", 0),
        ("unknown dot word stays for agent review", "The .widget suffix is uncommon.", 0),
        ("math is excluded", "The expression $[CLS] + .csv$ is malformed math.", 0),
        ("multiline display math is excluded",
         "Before.\n$$\nh_{[CLS]} = .csv\n$$\nAfter.", 0),
        ("escaped literal dollars do not hide ordinary prose",
         r"An escaped \$ precedes [CLS] and .csv before another \$.", 2),
        ("an even backslash run leaves a real math delimiter",
         r"Two slashes \\$[CLS]$ leave the dollar unescaped.", 0),
        ("heading is excluded", "## Files named .csv", 0),
        ("whole-line caption is excluded", "*Outputs saved as .csv.*", 0),
        ("table span is excluded", "A | B\n---|---\n.csv | [CLS]", 0, ((0, 2),)),
        ("ordinary prose after a table stays visible",
         "A | B\n---|---\nx | y\n\nThen save .csv.", 1, ((0, 2),)),
        ("a compound extension is one shape", "Ship a .tar.gz or .tar.bz2 file.", 2),
        ("a backticked compound extension is not bare", "Ship a `.tar.gz` file.", 0),
        ("an ellipsis before a word is punctuation, not an extension",
         "I waited...so I left, then...log in.", 0),
        ("a range's double dot is not an extension",
         "Sum the terms 1..r and stop.", 0),
        ("a Unicode ellipsis then a period is punctuation",
         "It ended….so it goes.", 0),
        ("a display indented under a two-digit step is excluded; the step's "
         "paragraph is prose",
         "10. Encode it:\n\n    $$\n    h_{[CLS]} = .csv\n    $$\n\n"
         "    Then save .csv.", 1),
        ("a caption indented under a step is excluded",
         "1. Plot it.\n\n   ![[plot.png]]\n   *Outputs saved as .csv.*", 0),
    ]
    failed = 0
    for case in cases:
        name, text, expected = case[:3]
        spans = case[3] if len(case) == 4 else ()
        got = len(find_bare_code_shapes(text, spans))
        ok = got == expected
        if verbose or not ok:
            print(("PASS" if ok else "FAIL") + ": " + name)
        if not ok:
            print("  expected %r, got %r" % (expected, got))
            failed += 1
    token_cases = [
        ("compound extension token is whole",
         "Ship a .tar.gz or .tar.bz2 file.", [".tar.gz", ".tar.bz2"]),
        ("a compound after a known extension is reported whole",
         "Archives ship as .tar.zst files.", [".tar.zst"]),
    ]
    for name, text, expected in token_cases:
        tokens = [item["token"] for item in find_bare_code_shapes(text)]
        ok = tokens == expected
        if verbose or not ok:
            print(("PASS" if ok else "FAIL") + ": " + name)
        if not ok:
            print("  expected %r, got %r" % (expected, tokens))
            failed += 1
    total = len(cases) + len(token_cases)
    print("%d/%d self-test cases pass" % (total - failed, total))
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
