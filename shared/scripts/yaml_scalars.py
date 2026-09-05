"""Read the single-line YAML scalars used in vault frontmatter, using stdlib.

This is not a YAML document parser. Callers own fences, keys, list placement
and schema checks; unsupported structures and malformed scalars raise
ValueError rather than supplying a guessed title or source identity. Non-null
plain values stay strings so each schema can validate its own booleans, dates
and numbers.
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
        if ch == "#" and (i == 0 or raw[i - 1] in " \t"):
            return raw[:i].rstrip(" \t")
        if token_start and ch in "\"'":
            quote, token_start = ch, False
        elif token_start and ch in "[{":
            depth += 1
        elif depth and ch in ",:":
            token_start = True
        elif depth and ch in "]}":
            depth -= 1
            token_start = False
        elif ch not in " \t":
            token_start = False
        i += 1
    return raw.rstrip(" \t")


def split_flow(inner):
    """Split a valid non-nested flow-list payload.

    An empty payload is the valid list ``[]``. A comma-delimited empty element
    is invalid YAML and raises ``ValueError`` instead of being silently dropped.
    """
    if not inner.strip():
        return []
    out, buf, quote = [], [], None
    i = 0
    while i < len(inner):
        ch = inner[i]
        if quote:
            buf.append(ch)
            if quote == '"' and ch == "\\" and i + 1 < len(inner):
                i += 1
                buf.append(inner[i])
            elif ch == quote:
                if quote == "'" and i + 1 < len(inner) and inner[i + 1] == "'":
                    i += 1
                    buf.append(inner[i])
                else:
                    quote = None
        elif ch in "\"'" and not "".join(buf).strip():
            quote = ch
            buf.append(ch)
        elif ch == ",":
            out.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    out.append("".join(buf).strip())
    if any(x == "" for x in out):
        raise ValueError("flow list contains an empty comma-delimited item")
    return out


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
    # YAML token separators are ASCII space and tab. Unicode spaces can be
    # part of a plain title or source identity, including just before '#'.
    s = strip_comment(raw).strip(" \t")
    if not s:
        return "", "empty"
    if s[0] not in "\"'":
        if s in ("null", "Null", "NULL", "~"):
            return None, "bare"
        if s[0] in "[]{}!&*|>%@`" or re.search(r":(?:[ \t]|$)", s) \
                or re.match(r"[-?](?:[ \t]|$)", s):
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
            if s[i + 1:].strip(" \t"):
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


def parse_source_fields(frontmatter_lines):
    """Read unambiguous top-level source fields from a closed YAML block.

    Callers supply only the lines between verified fences and own full-file
    UTF-8 decoding. Current ``sources`` remains present even when empty/null,
    so it can never fall through to stale legacy ``source`` metadata. Decode
    keys before checking duplicates and validate every current list member.
    This deliberately rejects unsupported root mapping forms; it is not a
    general YAML parser or a validator for unrelated metadata schemas.
    """
    result, active, item_indent, have_key = {}, None, None, False
    other_block = False

    def member(raw):
        value, _ = parse_scalar(raw)
        if not isinstance(value, str) or not value.strip():
            raise ValueError("sources contains an empty or null item")
        return value

    def key_value(line):
        # A key's colon can be quoted or escaped; a regex that recognizes
        # only bare source spellings silently assigns the wrong owner.
        quote, index = None, 0
        while index < len(line):
            ch = line[index]
            if quote:
                if quote == '"' and ch == "\\":
                    index += 2
                    continue
                if ch == quote:
                    if quote == "'" and line[index:index + 2] == "''":
                        index += 2
                        continue
                    quote = None
            elif index == 0 and ch in "\"'":
                quote = ch
            elif ch == ":" and (index + 1 == len(line)
                                or line[index + 1] in " \t"):
                key, _ = parse_scalar(line[:index])
                if not isinstance(key, str) or not key:
                    raise ValueError("invalid frontmatter mapping key")
                return key.casefold(), line[index + 1:]
            index += 1
        raise ValueError("unsupported or malformed frontmatter mapping")

    for raw in frontmatter_lines:
        if not isinstance(raw, str):
            raise ValueError("expected frontmatter text lines")
        line = raw.rstrip("\r\n")
        if not line.strip() or line.lstrip(" \t").startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" \t"))
        item = re.match(r"^[ \t]*-[ \t]+(.*)$", line)
        if active == "sources-block" and item:
            if "\t" in line[:indent] or (item_indent is not None and indent != item_indent):
                raise ValueError("inconsistent sources list indentation")
            item_indent = indent
            result["sources"].append(member(item[1]))
            continue
        if other_block and item:
            # YAML serializers often emit indentless tags/authors lists.
            # They belong to that unrelated empty-valued mapping key.
            continue
        if indent:
            if active is not None or not have_key:
                raise ValueError("unsupported continuation of a source field")
            # Nested values of unrelated metadata cannot define a root origin.
            continue
        active, item_indent, other_block = None, None, False
        if line.startswith(("?", ":", "{", "[", "&", "*", "!", "%")):
            raise ValueError("unsupported explicit, merged or flow root mapping")
        key, raw_value = key_value(line)
        have_key = True
        if key == "<<":
            raise ValueError("merged source ownership is unsupported")
        if key not in ("source", "sources"):
            other_block = not strip_comment(raw_value).strip(" \t")
            continue
        if key in result:
            raise ValueError("duplicate source field: " + key)
        value = strip_comment(raw_value).strip(" \t")
        if key == "source":
            result[key] = parse_scalar(raw_value)[0]
            active = "source-scalar"
        elif not value:
            result[key], active = [], "sources-block"
        elif value.startswith("[") and value.endswith("]"):
            result[key] = [member(part) for part in split_flow(value[1:-1])]
            active = "sources-flow"
        elif parse_scalar(raw_value)[0] is None:
            result[key], active = None, "sources-null"
        else:
            raise ValueError("sources must be a string list or null")
    return result


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

        def test_unicode_spaces_are_scalar_content(self):
            for space in ("\u00a0", "\u202f", "\u2003"):
                for raw in ("Plan" + space + "#2", "path:" + space + "value",
                            "-" + space + "label", space + "title" + space):
                    with self.subTest(raw=raw):
                        self.assertEqual(parse_scalar(raw), (raw, "bare"))
                        self.assertEqual(parse_scalar(raw + " # comment"),
                                         (raw, "bare"))
                for raw in ('"title"' + space, "'title'" + space + "#comment"):
                    with self.subTest(raw=raw), self.assertRaises(ValueError):
                        parse_scalar(raw)
            self.assertEqual(parse_scalar("Plan\t# comment"), ("Plan", "bare"))

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

        def test_flow_list_items(self):
            self.assertEqual(split_flow(""), [])
            self.assertEqual(
                split_flow('"a,b", \'O\'\'Reilly, Inc.\', bare'),
                ['"a,b"', "'O''Reilly, Inc.'", "bare"],
            )
            for inner in (",", '"a",', ',"a"', '"a",,"b"'):
                with self.subTest(inner=inner), self.assertRaises(ValueError):
                    split_flow(inner)

        def test_source_fields_decode_keys_before_ownership(self):
            self.assertEqual(parse_source_fields([
                r'"sour\u0063es": ["https://example.invalid/right", "[[raw]]"]',
                'source: "https://example.invalid/stale"']),
                {"sources": ["https://example.invalid/right", "[[raw]]"],
                 "source": "https://example.invalid/stale"})
            for value in ("", "[]", "null"):
                with self.subTest(value=value):
                    self.assertIn("sources", parse_source_fields([
                        "'sources': " + value, "source: https://example.invalid/stale"]))

        def test_source_fields_keep_supported_metadata_and_list_forms(self):
            self.assertEqual(parse_source_fields([
                'title: A title', 'tags: []', 'description: |',
                '  source: not an origin', 'sources:', '# origin follows',
                '- https://example.invalid/right # verified',
                "- '[[Raw O''Reilly]]'", 'source: null']),
                {"sources": ["https://example.invalid/right", "[[Raw O'Reilly]]"],
                 "source": None})
            self.assertEqual(parse_source_fields(["source: 'legacy'", "tags:",
                                                 '  - "#misc"']), {"source": "legacy"})
            self.assertEqual(parse_source_fields(["tags:", '- "#misc"',
                                                 "sources:", "- https://example.invalid/right"]),
                             {"sources": ["https://example.invalid/right"]})

        def test_source_fields_reject_ambiguous_or_malformed_claims(self):
            cases = [
                ['"sources": []', 'sources: []'],
                [r'"sour\u0063es": []', "'sources': []"],
                ['source: one', '"source": two'],
                ['sources: wrong', 'source: stale'],
                ['sources:', '  - https://example.invalid/right', '  - null'],
                ['sources:', '  - https://example.invalid/right', '  - ""'],
                ['sources:', '  - https://example.invalid/right', '  - [nested]'],
                ['sources:', '  - https://example.invalid/right', '    continuation'],
                ['sources:', '  - https://example.invalid/right', '   - wrong-indent'],
                ['sources: [https://example.invalid/right, null]'],
                ['sources: [https://example.invalid/right, "unclosed]'],
                ['sources: []', '? sources', ': [hidden]'],
                ['source: stale', '<<: *defaults'],
                ['source: stale', '{sources: [hidden]}'],
                ['source: stale', '"sources" missing-colon'],
            ]
            for lines in cases:
                with self.subTest(lines=lines), self.assertRaises(ValueError):
                    parse_source_fields(lines)

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
