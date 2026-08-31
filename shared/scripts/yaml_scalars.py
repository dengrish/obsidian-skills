"""Read the single-line YAML scalars used in vault frontmatter, using stdlib.

This is not a YAML document parser. Callers own fences, keys, lists and schema
checks; unsupported structures and malformed scalars raise ValueError rather
than supplying a guessed title or source identity. Non-null plain values stay
strings so each schema can validate its own booleans, dates and numbers.
"""
import argparse
import re


def strip_comment(raw):
    """Remove a trailing YAML comment, respecting quotes and flow-list items."""
    if not isinstance(raw, str):
        raise ValueError("expected YAML text")
    quote, depth, token_start = None, 0, True
    i = 0
    while i < len(raw):
        ch = raw[i]
        if quote:
            if quote == '"' and ch == "\\":
                i += 2
                continue
            if ch == quote:
                if quote == "'" and raw[i:i + 2] == "''":
                    i += 2
                    continue
                quote = None
            i += 1
            continue
        if ch == "#" and (i == 0 or raw[i - 1].isspace()):
            return raw[:i].rstrip()
        if token_start and ch in "\"'":
            quote, token_start = ch, False
        elif token_start and ch in "[{":
            depth += 1
        elif depth and ch in ",:":
            token_start = True
        elif depth and ch in "]}":
            depth -= 1
            token_start = False
        elif not ch.isspace():
            token_start = False
        i += 1
    return raw.rstrip()


_ESCAPES = {
    "0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t",
    "n": "\n", "v": "\v", "f": "\f", "r": "\r", "e": "\x1b",
    " ": " ", '"': '"', "/": "/", "\\": "\\", "N": "\x85",
    "_": "\xa0", "L": "\u2028", "P": "\u2029",
}


def parse_scalar(raw):
    """Return (value, style); style is double, single, bare or empty.

    Bare null/~ is None. A missing value or comment-only value is empty.
    Quoted strings retain their internal whitespace, including escaped text.
    Tags, aliases, collections and multiline scalars need a document parser
    and are deliberately rejected here.
    """
    if raw is None:
        return None, "empty"
    if not isinstance(raw, str):
        raise ValueError("expected YAML text")
    if any(ch in raw for ch in "\r\n"):
        raise ValueError("multiline YAML scalars are not supported")
    if any(ord(ch) < 32 and ch != "\t" for ch in raw):
        raise ValueError("invalid control character in YAML scalar")
    s = strip_comment(raw).strip()
    if not s:
        return "", "empty"
    if s[0] not in "\"'":
        if s in ("null", "Null", "NULL", "~"):
            return None, "bare"
        if s[0] in "[]{}!&*|>%@`" or re.search(r":(?:\s|$)", s) \
                or re.match(r"[-?](?:\s|$)", s):
            raise ValueError("expected a single-line YAML scalar")
        return s, "bare"
    quote = s[0]
    out = []
    i = 1
    while i < len(s):
        ch = s[i]
        if ch == quote:
            if quote == "'" and s[i:i + 2] == "''":
                out.append("'")
                i += 2
                continue
            if s[i + 1:].strip():
                raise ValueError("unexpected text after a quoted YAML scalar")
            return "".join(out), "double" if quote == '"' else "single"
        if quote == '"' and ch == "\\":
            i += 1
            if i >= len(s):
                raise ValueError("unterminated YAML escape")
            esc = s[i]
            if esc in _ESCAPES:
                out.append(_ESCAPES[esc])
            elif esc in "xuU":
                size = {"x": 2, "u": 4, "U": 8}[esc]
                digits = s[i + 1:i + 1 + size]
                if len(digits) != size or not re.fullmatch(r"[0-9a-fA-F]+", digits):
                    raise ValueError("invalid hexadecimal YAML escape")
                point = int(digits, 16)
                if point > 0x10ffff or 0xd800 <= point <= 0xdfff:
                    raise ValueError("invalid Unicode code point in YAML escape")
                out.append(chr(point))
                i += size
            else:
                raise ValueError("unknown YAML escape: \\" + esc)
        else:
            out.append(ch)
        i += 1
    raise ValueError("unterminated quoted YAML scalar")


def self_test():
    import io
    import unittest

    class ScalarTests(unittest.TestCase):
        def test_source_identities(self):
            cases = [
                ('"[[Garc\\u00eda_Study_2025.pdf#page=2]]" # origin',
                 "[[García_Study_2025.pdf#page=2]]"),
                ("'https://example.org/O''Reilly#part' # verified",
                 "https://example.org/O'Reilly#part"),
                ("https://example.org/O'Reilly#part # verified",
                 "https://example.org/O'Reilly#part"),
            ]
            for raw, expected in cases:
                with self.subTest(raw=raw):
                    self.assertEqual(parse_scalar(raw)[0], expected)

        def test_quoted_title_and_whitespace(self):
            self.assertEqual(parse_scalar('"A \\"quoted\\" title" # note'),
                             ('A "quoted" title', "double"))
            self.assertEqual(parse_scalar("'  a  '"), ("  a  ", "single"))
            self.assertEqual(parse_scalar('"#computer-science"'),
                             ("#computer-science", "double"))

        def test_escapes(self):
            self.assertEqual(parse_scalar(r'"\x41\u03bc\U0001F4DA"')[0], "Aμ📚")
            self.assertEqual(parse_scalar(r'"a\nb\t\\c"')[0], "a\nb\t\\c")
            self.assertEqual(parse_scalar(r"'a\nb'"), (r"a\nb", "single"))

        def test_null_and_empty(self):
            for raw in ("null", "Null # missing", "NULL", "~"):
                self.assertEqual(parse_scalar(raw), (None, "bare"))
            for raw in ("", "   ", "# no value"):
                self.assertEqual(parse_scalar(raw), ("", "empty"))
            self.assertEqual(parse_scalar(None), (None, "empty"))
            self.assertEqual(parse_scalar('"null"'), ("null", "double"))

        def test_schema_keeps_plain_values(self):
            for raw in ("true", "false", "2026-08-30", "42", "O'Reilly", "a#b"):
                self.assertEqual(parse_scalar(raw), (raw, "bare"))

        def test_malformed_does_not_supply_an_identity(self):
            for raw in ('"Malformed "yaml""', "'unclosed", r'"bad\q"',
                        r'"bad\uXX00"', r'"bad\U00110000"', r'"bad\uD800"',
                        '"title"#not-a-comment', '"title" trailing',
                        "a: nested", "[one, two]", "*alias", "!tag title",
                        ">-", "line\nbreak", "\x00bad"):
                with self.subTest(raw=raw), self.assertRaises(ValueError):
                    parse_scalar(raw)

        def test_flow_list_comments(self):
            raw = '["a # literal", \'O\'\'Reilly\', "b"] # note'
            self.assertEqual(strip_comment(raw), raw.rsplit(" # note", 1)[0])
            self.assertEqual(strip_comment(' # list follows'), "")
            self.assertEqual(strip_comment("O'Reilly # note"), "O'Reilly")

    output = io.StringIO()
    result = unittest.TextTestRunner(stream=output).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ScalarTests))
    failed = len(result.failures) + len(result.errors)
    if failed:
        print(output.getvalue())
    print("%d/%d self-test cases pass" % (result.testsRun - failed, result.testsRun))
    return 0 if result.wasSuccessful() else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true", help="run scalar regression tests")
    args = parser.parse_args(argv)
    if args.test:
        return self_test()
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
