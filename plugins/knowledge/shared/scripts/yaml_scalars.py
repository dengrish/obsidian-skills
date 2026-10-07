"""Read the single-line YAML scalars used in vault frontmatter, using stdlib.

This is not a YAML document parser. Callers own fences, keys, list placement
and schema checks, with one exception: `read_note_origin` finds a note's own
leading frontmatter, because clipping-clean and paper-summarize read each
other's `Articles/` notes and must agree about which notes they own.
Unsupported structures and malformed scalars raise ValueError rather than
supplying a guessed title or source identity. Non-null plain values stay
strings so each schema can validate its own booleans, dates and numbers.
"""
import argparse
import os
import re
import stat


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


def _open_value(raw, quote=None, depth=0):
    """The (quote, depth) a value line leaves open; (None, 0) means closed.

    It reads with ``strip_comment``'s token rules and starts from the state
    the line before left open, so a quoted or flow value can be followed
    across its indented continuation lines.
    """
    token_start = True
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
                quote, token_start = None, False
            i += 1
            continue
        if ch == "#" and (i == 0 or raw[i - 1] in " \t"):
            break
        if token_start and ch in "\"'":
            quote = ch
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
    return quote, depth


def split_flow(inner):
    """Split a valid non-nested flow-list payload.

    An empty payload is the valid list ``[]``. A single trailing comma after an
    item is valid YAML and is ignored; any other empty comma-delimited element
    is invalid and raises ``ValueError`` instead of being silently dropped.
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
    if len(out) > 1 and out[-1] == "" and out[-2] != "":
        out.pop()
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
    A quoted or flow value of another key continues only on indented lines.
    One that runs into an unindented line, or past the last line, is
    malformed: its next line could otherwise pose as a ``sources:`` key.
    """
    result, active, item_indent, have_key = {}, None, None, False
    other_block, pending = False, None

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
        if pending:
            if line.strip(" \t") and line[0] not in " \t":
                raise ValueError("an open quoted or flow value continues "
                                 "on an unindented line")
            pending = _open_value(line, *pending)
            if pending == (None, 0):
                pending = None
            continue
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
            pending = _open_value(raw_value)
            if pending == (None, 0):
                pending = None
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
    if pending:
        raise ValueError("unterminated quoted or flow value")
    return result


def read_regular_text(path):
    """Decode one regular file strictly as UTF-8 (BOM allowed), else None.

    Follow an explicitly selected read-only alias, but open nonblocking and
    classify the handle before reading. A `.md` path swapped to a FIFO between
    a path-stat and ordinary `open()` could otherwise block the whole batch
    indefinitely while waiting for a writer.
    """
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return None
        with os.fdopen(descriptor, "r", encoding="utf-8-sig",
                       errors="strict") as fh:
            descriptor = None                 # fdopen now owns the descriptor
            return fh.read()
    except (OSError, UnicodeError, ValueError):
        return None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def yaml_lines(text, keepends=False):
    """Split at YAML line breaks only: CRLF, CR and LF.

    ``str.splitlines`` also splits at U+2028, U+2029, NEL and form feed.
    YAML reads those as content, so a quoted title holding one would break
    into two lines and hide the note's origin.
    """
    lines = re.findall(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+\Z", text)
    return lines if keepends else [line.rstrip("\r\n") for line in lines]


def _origin_fence(line):
    """True for a column-zero ``---`` with only trailing spaces or tabs.

    YAML block-scalar content is indented, so an indented rule inside a
    ``|`` value must not end the frontmatter before a later ``sources:`` key.
    """
    return line.rstrip(" \t") == "---"


def read_note_origin(path):
    """A note's origin, or None: the first current ``sources`` item.

    A legacy scalar ``source`` is read only when ``sources`` is absent, so
    unmigrated notes keep their identity; an empty or null ``sources`` never
    falls through to it. clipping-clean and paper-summarize both read the
    shared ``Articles/`` notes through this one function, because a note that
    the two skills read differently is either invisible to one skill's
    duplicate check or claimed by both.

    The tolerances are the ones an editor round-trip produces and Obsidian
    still reads as frontmatter: a BOM, CRLF line endings, leading blank lines
    before the opening fence, and trailing spaces or tabs on a fence. Lines
    break only where YAML breaks them (``yaml_lines``). The whole note must
    decode strictly as UTF-8 before its metadata can establish ownership, so
    invalid bytes in the body cannot hide behind a valid-looking origin.

    A CLOSING fence is required. An unterminated ``---`` is not frontmatter,
    and reading on into the body would take whatever ``source:`` the prose or
    a quoted block contains. Missing, non-regular, undecodable, unterminated
    and malformed notes all return None, which callers report rather than
    guess. ``read_note_origin_detail`` also says which of these it was.
    """
    return read_note_origin_detail(path)[0]


def read_note_origin_detail(path):
    """(origin, problem): ``read_note_origin``'s origin, and why it is None.

    ``problem`` is None when the origin was read, or when the note is
    readable and has none: no frontmatter, no source field, or an empty or
    null ``sources``. Otherwise it names what stopped the read: text that is
    not readable UTF-8, an unterminated block, or malformed metadata. A
    malformed note may still be the caller's own note, so the caller reports
    the problem rather than calling the note foreign.
    """
    text = read_regular_text(path)
    if text is None:
        return None, "not readable UTF-8 text"
    lines = yaml_lines(text)
    opening = next((i for i, line in enumerate(lines) if line.strip()), None)
    if opening is None or not _origin_fence(lines[opening]):
        return None, None
    closing = next((i for i in range(opening + 1, len(lines))
                    if _origin_fence(lines[i])), None)
    if closing is None:
        return None, "unterminated frontmatter"
    try:
        fields = parse_source_fields(lines[opening + 1:closing])
    except ValueError as exc:
        return None, str(exc)
    if "sources" in fields:
        return (fields["sources"] or [None])[0], None
    return fields.get("source") or None, None


#: Origin-ownership fixtures: the frontmatter text between the fences and the
#: origin `read_note_origin` must return. The self-test runs them, and the
#: compatibility suite runs them against pdf-organize's own rename-ownership
#: reader, which must agree on which notes are about ``ORIGIN_CASE_PDF``.
ORIGIN_CASE_PDF = "[[Doe_Study_2025.pdf]]"
ORIGIN_CASE_URL = "https://example.org/observed#section"
ORIGIN_CASES = (
    ('sources:\n  - "%s"\nsource: "%s"' % (ORIGIN_CASE_URL, ORIGIN_CASE_PDF),
     ORIGIN_CASE_URL),
    ('"sources": ["%s"]' % ORIGIN_CASE_URL, ORIGIN_CASE_URL),
    ('"so\\u0075rces": ["%s"]' % ORIGIN_CASE_PDF, ORIGIN_CASE_PDF),
    ("'sources':\n- '%s' # origin" % ORIGIN_CASE_PDF, ORIGIN_CASE_PDF),
    ('tags:\n- "#misc"\nsources:\n- "%s"' % ORIGIN_CASE_PDF, ORIGIN_CASE_PDF),
    ('"sources": ["%s"]\nsources:\n  - "%s"' % (ORIGIN_CASE_URL, ORIGIN_CASE_PDF),
     None),
    ('"sources": ["%s"]\nsource: "%s"' % (ORIGIN_CASE_URL, ORIGIN_CASE_PDF),
     ORIGIN_CASE_URL),
    ('sources: "%s"\nsource: "%s"' % (ORIGIN_CASE_URL, ORIGIN_CASE_PDF), None),
    ('sources: []\nsource: "%s"' % ORIGIN_CASE_PDF, None),
    ('sources:\n  - "%s"\n  - [nested]' % ORIGIN_CASE_PDF, None),
    ('sources:\n  - "%s"\n  - null' % ORIGIN_CASE_PDF, None),
    ('"source": "%s"\nsource: "%s"' % (ORIGIN_CASE_URL, ORIGIN_CASE_PDF), None),
    ('? sources\n: ["%s"]\nsource: "%s"' % (ORIGIN_CASE_URL, ORIGIN_CASE_PDF),
     None),
    ('<<: *other\nsource: "%s"' % ORIGIN_CASE_PDF, None),
    ('source: "%s"' % ORIGIN_CASE_PDF, ORIGIN_CASE_PDF),
    # U+2028, U+2029 and NEL are content in YAML, not line breaks.
    ('title: "A B"\nsources:\n  - "%s"' % ORIGIN_CASE_PDF, ORIGIN_CASE_PDF),
    ('description: "A\x85B"\nsources: ["%s"]' % ORIGIN_CASE_URL, ORIGIN_CASE_URL),
    ('title: "A B"\nsource: "%s"' % ORIGIN_CASE_PDF, ORIGIN_CASE_PDF),
    # A quoted or flow value continues only on indented lines.
    ("title: 'A long\n  wrapped title'\nsources:\n- '%s'" % ORIGIN_CASE_PDF,
     ORIGIN_CASE_PDF),
    ("title: 'Clipped\nsources: [\"%s\"] #'\nsource: %s"
     % (ORIGIN_CASE_PDF, ORIGIN_CASE_URL), None),
    ('tags: [a,\nsources: ["%s"]\nx: 1]\nsource: %s'
     % (ORIGIN_CASE_PDF, ORIGIN_CASE_URL), None),
)


def self_test():
    import io
    import shutil
    import tempfile
    import threading
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
            self.assertEqual(split_flow('"a", '), ['"a"'])
            for inner in (",", '"a",,', ',"a"', '"a",,"b"'):
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

        def test_source_fields_follow_open_values_to_their_end(self):
            url = "https://example.invalid/right"
            for lines in (
                    ["title: 'A long", "  wrapped # title'", "sources:", "- " + url],
                    ['title: "A \\"long\\"', '', '  title"', "sources: [" + url + "]"],
                    ["tags: [a,", "  # comment", "  'b c']", "sources: [" + url + "]"],
                    ["title: O'Reilly # it's", "aliases: [O'Reilly]",
                     "sources: [" + url + "]"]):
                with self.subTest(lines=lines):
                    self.assertEqual(parse_source_fields(lines),
                                     {"sources": [url]})
            for lines in (
                    ["title: 'Clipped", 'sources: ["[[Doe.pdf]]"] #\'',
                     "source: " + url],
                    ["title: \"Clipped", "#\"", "source: " + url],
                    ["tags: {a: [b,", "  c]", "sources: [x]}", "source: " + url],
                    ["source: " + url, "title: 'never closed"],
                    ["source: " + url, "tags: [a,", "  b"]):
                with self.subTest(lines=lines), self.assertRaises(ValueError):
                    parse_source_fields(lines)

        def test_yaml_lines_break_only_at_yaml_line_breaks(self):
            text = "a b c\x85d\x0ce\r\nf\rg\nh"
            self.assertEqual(yaml_lines(text),
                             ["a b c\x85d\x0ce", "f", "g", "h"])
            self.assertEqual("".join(yaml_lines(text, keepends=True)), text)
            self.assertEqual(yaml_lines("x\n"), ["x"])
            self.assertEqual(yaml_lines(""), [])

    class NoteOriginTests(unittest.TestCase):
        def setUp(self):
            self.tmp = tempfile.mkdtemp(prefix="yaml_scalars_selftest.")
            self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

        def note(self, name, body):
            path = os.path.join(self.tmp, name)
            with open(path, "wb") as fh:
                fh.write(body if isinstance(body, bytes) else body.encode("utf-8"))
            return path

        def test_origin_ownership_cases(self):
            for number, (metadata, expected) in enumerate(ORIGIN_CASES):
                with self.subTest(metadata=metadata):
                    path = self.note("case-%d.md" % number, "---\n" + metadata +
                                     "\n---\nOrdinary note body.\n")
                    self.assertEqual(read_note_origin(path), expected)

        def test_editor_round_trip_forms_keep_their_origin(self):
            url = "https://example.com/a"
            for label, body in (
                    ("BOM", "﻿---\nsource: %s\n---\n" % url),
                    ("CRLF", "---\r\nsources:\r\n  - %s\r\n---\r\nbody\r\n" % url),
                    ("BOM and CRLF", "﻿---\r\nsource: %s\r\n---\r\n" % url),
                    ("leading blank lines", "\n \n---\nsource: %s\n---\n" % url),
                    ("trailing fence whitespace",
                     "--- \t\nsources:\n  - %s\n---  \n" % url),
                    ("indented block-scalar rule",
                     '---\nsource: "https://stale.example/"\nnotes: |\n  ---\n'
                     'sources:\n  - "%s"\n---\n' % url)):
                with self.subTest(label=label):
                    path = self.note(label.replace(" ", "-") + ".md", body)
                    self.assertEqual(read_note_origin(path), url)

        def test_only_a_closed_leading_block_is_frontmatter(self):
            url = "https://example.com/a"
            for label, body in (
                    ("unterminated", "---\nsource: %s\n\nprose\n" % url),
                    ("body rule does not reopen",
                     "---\ntitle: x\n---\n\n---\nsource: %s\n---\n" % url),
                    ("prose before the fence",
                     "Intro\n---\nsource: %s\n---\n" % url),
                    ("indented opening fence", " ---\nsource: %s\n---\n" % url),
                    ("no frontmatter", "just prose\n"),
                    ("empty note", ""),
                    ("no origin key", "---\ntitle: x\n---\n"),
                    ("empty legacy origin", "---\nsource:\n---\n"),
                    ("nested origin",
                     "---\ncitation:\n  source: %s\n---\n" % url)):
                with self.subTest(label=label):
                    path = self.note(label.replace(" ", "-") + ".md", body)
                    self.assertIsNone(read_note_origin(path))

        def test_origin_detail_names_why_there_is_no_origin(self):
            url = "https://example.com/a"
            for label, body, want in (
                    ("origin", "---\nsources:\n  - %s\n---\n" % url, (url, None)),
                    ("no frontmatter", "just prose\n", (None, None)),
                    ("no origin key", "---\ntitle: x\n---\n", (None, None)),
                    ("empty sources", "---\nsources: []\n---\n", (None, None)),
                    ("null sources", "---\nsources: null\n---\n", (None, None)),
                    ("unterminated", "---\nsource: %s\n\nprose\n" % url,
                     (None, "unterminated frontmatter")),
                    ("duplicate", "---\nsources: [%s]\nsources: [%s]\n---\n"
                     % (url, url), (None, "duplicate source field: sources")),
                    ("null item", "---\nsources:\n  - %s\n  - null\n---\n" % url,
                     (None, "sources contains an empty or null item")),
                    ("invalid UTF-8",
                     b"---\nsources:\n  - %s\n---\n\xff\n" % url.encode(),
                     (None, "not readable UTF-8 text"))):
                with self.subTest(label=label):
                    path = self.note(label.replace(" ", "-") + ".md", body)
                    self.assertEqual(read_note_origin_detail(path), want)
                    self.assertEqual(read_note_origin(path), want[0])

        def test_unreadable_notes_establish_nothing(self):
            text = "﻿---\nsource: https://example.com/a\n---\n"
            self.assertEqual(read_regular_text(self.note("bom.md", text)),
                             text[1:])
            for label, body in (
                    ("invalid frontmatter",
                     b'---\ntitle: \xff\nsources:\n  - "https://example.com/a"\n---\n'),
                    ("invalid body",
                     b'---\nsources:\n  - "https://example.com/a"\n---\nbody \xff\n')):
                with self.subTest(label=label):
                    path = self.note(label.replace(" ", "-") + ".md", body)
                    self.assertIsNone(read_regular_text(path))
                    self.assertIsNone(read_note_origin(path))
            for path in (os.path.join(self.tmp, "missing.md"), self.tmp):
                with self.subTest(path=path):
                    self.assertIsNone(read_regular_text(path))
                    self.assertIsNone(read_note_origin(path))
            if hasattr(os, "mkfifo"):
                fifo = os.path.join(self.tmp, "capture-fifo.md")
                os.mkfifo(fifo)
                got = []
                reader = threading.Thread(
                    target=lambda: got.append((read_regular_text(fifo),
                                               read_note_origin(fifo))),
                    daemon=True)
                reader.start()
                reader.join(5)
                self.assertFalse(reader.is_alive(), "a FIFO blocked the reader")
                self.assertEqual(got, [(None, None)])

    output = io.StringIO()
    loader = unittest.defaultTestLoader
    result = unittest.TextTestRunner(stream=output).run(unittest.TestSuite(
        loader.loadTestsFromTestCase(case) for case in (ScalarTests, NoteOriginTests)))
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
