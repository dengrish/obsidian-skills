#!/usr/bin/env python3
"""Build the Articles/ dedup index and check raw clippings against it.

`Articles/` is this skill's output and its sole dedup index: a raw is
already processed if and only if some note in Articles/ carries its URL in `sources:`
URL. This script does the mechanical half of step 1 — one pass over Articles/,
URL normalization on both sides, and (optionally) a verdict per raw — so the
scan is a single pass rather than a quadratic one, and the normalization rules
are applied the same way every run.

The decisions stay with the model: what to do about a duplicate (skip in batch,
ask in explicit-single-file mode) is in references/duplicates-and-reprocessing.md.

CLI
    python3 dedup_index.py '<cleaned_dir>' [--raw PATH ...] [--url URL ...]
                           [--exclude PATH ...] [--dump-index]

    <cleaned_dir>   the vault's Articles/ folder
    --raw           a raw .md file, or a folder of them (Inbox/); repeatable
    --url           a bare URL to check, instead of / as well as --raw
    --exclude       a note to leave out of the index — use it when reprocessing a
                    file that itself lives in Articles/, so it can't match itself
    --dump-index    include the whole {normalized_url: path} map in the output
    --test          run the built-in cases (no arguments, writes nothing
                    outside a temp dir)

Importable
    normalize_url(url) -> str
    read_source(path)  -> str | None
    build_index(cleaned_dir, exclude=()) -> (index, unindexable, non_url)
    check(entries, index) -> list[dict]
    run_self_test() -> int

Output: one JSON object on stdout. Exit status is 0 whenever the scan ran.
Stdlib only.
"""

import argparse
import json
import os
import re
import sys
import unicodedata
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

# --- obsidian shared-layer bootstrap (canonical; see shared/CONVENTIONS.md) ---
import os as _os, sys as _sys
_here = _os.path.dirname(_os.path.abspath(__file__))
_env = _os.environ.get("OBSIDIAN_VAULT_SHARED")
if _env:                                   # explicit override: authoritative, no fallback
    _tried = [_os.path.abspath(_os.path.expanduser(_env))]
else:                                      # plugin-relative walk-up, at most 5 levels
    _tried, _d = [], _here
    for _ in range(5):
        _tried.append(_os.path.join(_d, "shared", "scripts"))
        _d = _os.path.dirname(_d)
_shared = next((_p for _p in _tried if _os.path.isdir(_p)), None)
if _shared is None:
    raise SystemExit("""obsidian: cannot find the plugin's shared/scripts/ folder, which holds
the one canonical copy of the conventions this script depends on.
Looked for:
  %s
Fix: install the whole plugin tree, or set OBSIDIAN_VAULT_SHARED to the
shared/scripts/ directory (unset it to use the plugin-relative walk-up).
Do NOT paste a second copy of the algorithm into this skill -- a divergent
copy is the bug the shared layer exists to prevent.""" % "\n  ".join(_tried))
_sys.path[:] = [_p for _p in _sys.path if _p not in (_shared, _here)]
_sys.path.insert(0, _shared)               # shared/scripts/ FIRST
_sys.path.append(_here)                    # own dir LAST: a local copy cannot shadow it
# --- end bootstrap ---

from yaml_scalars import parse_scalar


def _path_keys(path):
    """Comparable spellings of one file path, for the --exclude match.

    ``os.path.realpath`` resolves symlinks but preserves the *string* it was
    given, and on macOS the same filename is NFD when read off the disk and
    NFC when typed on a command line — plus the volume is case-insensitive.
    Comparing raw realpaths therefore fails to exclude the note being
    reprocessed exactly on the platform the vault lives on, and the note then
    matches its own ``source:`` and reports itself as a duplicate.  Keys are
    NFC-normalized and casefolded; two genuinely distinct files that differ
    only this way cannot coexist on that volume anyway.
    """
    real = os.path.realpath(path)
    return {real, unicodedata.normalize("NFC", real).casefold()}

# Tracking parameters carry no page identity: the same article shared by email,
# by tweet and from the archive yields three URLs differing only here. Strip
# what is recognized as tracking and nothing else — ?id=, ?p=, ?page=, ?v= and
# friends often ARE the page identity.
#
# `ref` is NOT in this set, and used to be. It is the one entry that routinely
# carries page identity rather than provenance — a git ref (`?ref=main`), a docs
# anchor, a section id — so `?ref=alpha` and `?ref=beta` were normalizing onto
# ONE key. That direction is the expensive one: two different articles sharing a
# key means the second is reported `duplicate`, and step 1 skips it, so an
# article the user clipped is silently never processed and the report says the
# run was clean. The other direction is cheap and caught downstream — an
# unstripped tracking parameter yields a `new` verdict on a re-clip, which is
# exactly what guard 2 (step 3's filename check) exists to catch. Strip what is
# provably noise, and no further.
TRACKING_PARAMS = {
    "fbclid", "gclid", "mc_cid", "mc_eid", "referrer", "share",
    "r", "showwelcome",
}
TRACKING_PREFIXES = ("utm_",)

#: A fragment that ROUTES rather than anchors: `#/posts/1`, `#!/posts/1`.
#: Dropping every fragment collapsed a fragment-routed SPA onto one key — every
#: article on `app.example.com/#/posts/<n>` normalized to `app.example.com`, so
#: the first one clipped made every later one a `duplicate` and the whole site
#: became un-clippable after one article. An `#anchor-id` still goes: that is a
#: position within one page, which is what step 1's rule means by a fragment.
ROUTING_FRAGMENT = ("/", "!")


def normalize_url(url):
    """Normalize an HTTP(S) URL for identity; invalid origins return no key."""
    if not isinstance(url, str):
        return ""
    url = url.strip()
    if len(url) >= 2 and url[0] == url[-1] and url[0] in "\"'":
        url = url[1:-1].strip()
    if not url:
        return ""
    try:
        parts = urlsplit(url)
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
            return ""
        if any(ch.isspace() for ch in parts.hostname):
            return ""
        # Accessing port validates it; urlsplit alone accepts `:not-a-port`.
        parts.port
    except ValueError:
        return ""
    scheme = parts.scheme.lower()
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/")
    query_pairs = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS
        and not any(k.lower().startswith(p) for p in TRACKING_PREFIXES)
    ]
    # Sorted, because parameter order carries no page identity either: a
    # ?a=1&b=2 clip and a ?b=2&a=1 clip of one article would otherwise be two
    # `new` verdicts, and the second one overwrites the first's note. Which
    # parameters survive is unchanged — only their order is normalized.
    query = urlencode(sorted(query_pairs))
    # An anchor fragment is dropped; a routing fragment is the page and stays.
    # An emptied query drops its trailing "?" too.
    fragment = parts.fragment
    fragment = fragment if fragment[:1] in ROUTING_FRAGMENT else ""
    return urlunsplit((scheme, host, path, query, fragment))


#: Anchored at column 0: an INDENTED `sources:`/`source:` is nested under some
#: other key and is not the note's.  Reading one indexes the note under the
#: wrong URL, which is a dedup miss -- and a dedup miss is a polished note
#: silently overwritten on the next run.  `sources:` (block-form list, schema
#: 2b) is the current key; the scalar `source:` is the pre-rename legacy shape,
#: still read so an unmigrated note stays visible to the duplicate check.
SOURCES_RE = re.compile(r"\Asources\s*:\s*(?:#.*)?\Z", re.IGNORECASE)
# YAML allows an indentless block sequence at a mapping value; serializers such
# as PyYAML emit it by default. Requiring indentation hides those saved notes
# from dedup. A sequence marker still needs whitespace before its scalar.
_ITEM_RE = re.compile(r"\A[ \t]*-[ \t]+(.*)\Z")
SOURCE_RE = re.compile(r"\Asource\s*:\s*(.*)\Z", re.IGNORECASE)

def _yaml_scalar(raw):
    """Decode a scalar without changing escaped source identities."""
    return parse_scalar(raw)[0]


def read_source(path):
    """Return a note's origin from its YAML frontmatter, or None.

    The origin is the first item of the block-form `sources:` list (schema 2b);
    a legacy scalar `source:` is read as a fallback so unmigrated notes stay
    indexed.

    Two tolerances, both in the direction the guard's asymmetry demands — a note
    this can't read is invisible to every duplicate check, and the cost of that
    miss is a polished note silently clobbered:

    * `utf-8-sig`, so a leading BOM (a note that went through an editor that
      writes one) doesn't turn the opening `---` into `\\ufeff---`;
    * leading blank lines are skipped before the opening fence is tested.

    Both are still valid YAML frontmatter as far as Obsidian is concerned.

    The tolerance stops at the CLOSING fence, which is required. A value is
    returned only once the frontmatter has been shown to end: an unterminated
    `---` is not frontmatter to Obsidian, and scanning on into the body found
    whatever `source:` the article's own prose or a quoted block happened to
    contain, then indexed the note under it. That is worse than reading nothing
    — an unreadable note is counted and reported as `unindexable`, while a note
    indexed under the wrong URL is invisible to its own duplicate check *and*
    answers somebody else's.
    """
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            for first in fh:                   # skip leading blank lines
                if first.strip():
                    break
            else:
                return None
            if first.strip() != "---":
                return None
            found = None
            pending = False
            for line in fh:
                if line.strip() == "---":
                    return found or None       # the fence closed: it is ours
                if found is None:
                    raw = line.rstrip("\n")
                    if pending:
                        # Blank and comment-only lines between `sources:` and
                        # its first item are valid YAML (Obsidian still reads
                        # item 1); consuming the flag on one left the real item
                        # unread and the note indexed as unindexable.  The
                        # sibling readers (paper_scan, organize) skip the same way.
                        if not raw.strip() or raw.lstrip().startswith("#"):
                            continue
                        pending = False
                        mi = _ITEM_RE.match(raw)
                        if mi:
                            found = _yaml_scalar(mi.group(1))
                            continue
                    if SOURCES_RE.match(raw):
                        pending = True         # the origin is the NEXT line
                        continue
                    m = SOURCE_RE.match(raw)
                    if m:
                        found = _yaml_scalar(m.group(1))
    except (OSError, ValueError):
        return None
    return None


def _md_files(folder):
    out = []
    for root, _dirs, files in os.walk(folder):
        for f in sorted(files):
            if f.endswith(".md"):
                out.append(os.path.join(root, f))
    return sorted(out)


def build_index(cleaned_dir, exclude=()):
    """Scan Articles/ once. Returns (index, unindexable, non_url).

    index       {normalized_url: [note paths]}   — normally one path per URL
    unindexable [paths]  notes with a missing/unparseable `sources:`; these are
                invisible to every duplicate check, so report the count
    non_url     [{path, source}]  notes whose origin is a wikilink to a local
                document rather than a URL — parseable, but deliberately not
                part of the URL index.  These are paper-summarizer's summary
                notes, which share this folder and key to a PDF basename
                instead; one per summarised paper is the healthy state, not an
                anomaly.  A hit whose wikilink is not a document under
                Sources/PDFs/ may instead be a clipping note whose `sources:`
                got wikilink-wrapped, which IS a defect; SKILL.md step 1 says
                how to tell and what to report.
    """
    excluded = set()
    for p in exclude:
        excluded |= _path_keys(p)
    index, unindexable, non_url = {}, [], []
    for path in _md_files(cleaned_dir):
        if excluded and (_path_keys(path) & excluded):
            continue
        src = read_source(path)
        if not src:
            unindexable.append(path)
            continue
        if not src.lower().startswith(("http://", "https://")):
            non_url.append({"path": path, "source": src})
            continue
        norm = normalize_url(src)
        if not norm:
            unindexable.append(path)
            continue
        index.setdefault(norm, []).append(path)
    return index, unindexable, non_url


def check(entries, index):
    """Check each {id, source} entry against the index.

    Entries are checked in order and each new URL is added to a live copy of the
    index, so a second raw in the same batch that captures the same article is
    caught against the first — the reason the index is kept live rather than
    frozen at start-of-run.
    """
    live = {k: list(v) for k, v in index.items()}
    seen_this_run = {}
    results = []
    for ent in entries:
        src = ent.get("source")
        norm = normalize_url(src)
        if not norm:
            results.append({**ent, "normalized": None, "status": "no-source",
                            "matches": []})
            continue
        matches = live.get(norm, [])
        if matches:
            status = ("duplicate-of-earlier-input" if norm in seen_this_run
                      else "duplicate")
        else:
            status = "new"
            live.setdefault(norm, [])
        seen_this_run.setdefault(norm, ent.get("id"))
        results.append({**ent, "normalized": norm, "status": status,
                        "matches": list(matches)})
        if status == "new":
            live[norm].append(ent.get("id") or "<pending write>")
    return results


def run_self_test():
    """Every normalization rule the docstring claims, and every shape of
    origin field a real vault has produced.

    The two halves fail differently and both fail silently. A normalization that
    collapses two DIFFERENT articles onto one key reports the second as a
    `duplicate`, so step 1 skips a raw the user clipped and the report calls the
    run clean. An origin this cannot read leaves the note out of the index
    entirely, so the next run derives it again and overwrites the polished copy.
    Neither leaves a trace, which is why they are pinned here rather than
    checked by eye.
    """
    import shutil
    import tempfile

    cases = []

    def case(label, got, want):
        cases.append((label, got == want, got, want))

    def same(label, a, b):
        cases.append(("%s: %s == %s" % (label, a, b),
                      normalize_url(a) == normalize_url(b),
                      normalize_url(a), normalize_url(b)))

    def differ(label, a, b):
        cases.append(("%s: %s != %s" % (label, a, b),
                      normalize_url(a) != normalize_url(b),
                      normalize_url(a), "anything else"))

    # --- normalize_url: every rule the docstring claims ---------------------
    case("scheme lowercased",
          normalize_url("HTTPS://example.com/a"), "https://example.com/a")
    case("host lowercased",
          normalize_url("https://EXAMPLE.com/a"), "https://example.com/a")
    case("leading www. dropped",
          normalize_url("https://www.example.com/a"), "https://example.com/a")
    case("a host merely starting with www is not touched",
          normalize_url("https://wwwx.example.com/a"),
          "https://wwwx.example.com/a")
    case("trailing slashes stripped",
          normalize_url("https://example.com/a//"), "https://example.com/a")
    case("an anchor fragment is dropped",
          normalize_url("https://example.com/a#section-2"),
          "https://example.com/a")
    case("an emptied query drops its `?`",
          normalize_url("https://example.com/a?utm_source=x"),
          "https://example.com/a")
    case("query order does not matter",
          normalize_url("https://example.com/a?b=2&a=1"),
          "https://example.com/a?a=1&b=2")
    case("None is the empty key", normalize_url(None), "")
    case("blank is the empty key", normalize_url("   "), "")
    for bad in ("https://[broken/article", "https://", "http:///article",
                "https://example.com:not-a-port/article", "https://bad host/x",
                "file:///article.md", "not a URL"):
        case("an unusable origin cannot become a dedup key: %r" % bad,
             normalize_url(bad), "")
    case("surrounding quotes are stripped",
          normalize_url('"https://example.com/a"'), "https://example.com/a")
    differ("a trailing apostrophe in a URL path is literal data",
           "https://example.com/rockin'", "https://example.com/rockin")
    for param in ("utm_source", "utm_medium", "utm_campaign", "fbclid",
                  "gclid", "mc_cid", "mc_eid", "referrer", "share", "r",
                  "showWelcome"):
        same("tracking %s carries no identity" % param,
             "https://example.com/a?%s=x" % param, "https://example.com/a")
    for param in ("id", "p", "page", "v", "story", "q"):
        differ("?%s= often IS the page identity" % param,
               "https://example.com/a?%s=1" % param,
               "https://example.com/a?%s=2" % param)
    same("the same article from three places is one key",
         "https://WWW.Example.com/posts/x/?utm_source=twitter&fbclid=9#top",
         "https://example.com/posts/x")

    # --- the two collisions: distinct pages must not share a key ------------
    # A fragment-routed SPA. Every article lives at `#/posts/<n>`, so dropping
    # every fragment made the whole site one key: clip one article and every
    # other article on it reports as a duplicate of it, forever.
    differ("a fragment-routed SPA is not one page",
           "https://app.example.com/#/posts/1",
           "https://app.example.com/#/posts/2")
    differ("...hash-bang routing too",
           "https://app.example.com/#!/posts/1",
           "https://app.example.com/#!/posts/2")
    case("a routing fragment survives normalization",
          normalize_url("https://app.example.com/#/posts/1"),
          "https://app.example.com#/posts/1")
    same("...while two anchors of one page are still one key",
         "https://example.com/a#top", "https://example.com/a#references")
    # `?ref=` is a page identity as often as it is provenance (a git ref, a docs
    # section), and collapsing two of them silently drops the second article.
    differ("?ref= distinguishes pages",
           "https://example.com/a?ref=alpha", "https://example.com/a?ref=beta")
    case("?ref= survives normalization",
          normalize_url("https://example.com/a?ref=alpha"),
          "https://example.com/a?ref=alpha")

    # --- read_source, against the note shapes a real vault holds ------------
    tmp = tempfile.mkdtemp(prefix="dedup_selftest.")
    try:
        def note(name, body, encoding="utf-8"):
            p = os.path.join(tmp, name)
            with open(p, "wb") as fh:
                fh.write(body.encode(encoding))
            return p

        URL = "https://example.com/a"
        for label, body, want in (
                ("sources list, quoted item",
                 '---\nsources:\n  - "%s"\n---\nbody\n' % URL, URL),
                ("sources list, unquoted item",
                 "---\nsources:\n  - %s\n---\n" % URL, URL),
                ("sources list, indentless quoted item",
                 '---\nsources:\n- "%s"\n---\n' % URL, URL),
                ("sources list, indentless unquoted item",
                 "---\nsources:\n- %s\n---\n" % URL, URL),
                ("sources key with a YAML comment",
                 '---\nsources: # capture URL\n- "%s"\n---\n' % URL, URL),
                ("single quote escape in URL",
                 "---\nsources:\n  - 'https://example.com/o''brien'\n---\n",
                 "https://example.com/o'brien"),
                ("double quote Unicode escape in URL",
                 '---\nsources:\n  - "https://example.com/caf\\u00e9"\n---\n',
                 "https://example.com/café"),
                ("malformed quoted origin stays unindexable",
                 '---\nsources:\n  - "https://example.com/a"broken"\n---\n', None),
                ("unclosed quoted origin stays unindexable",
                 '---\nsources:\n  - "https://example.com/a\n---\n', None),
                ("a dash without following whitespace is not a list item",
                 "---\nsources:\n  -%s\n---\n" % URL, None),
                ("sources list, wikilink first item (a summary note)",
                 '---\nsources:\n  - "[[Doe_X_2025.pdf]]"\n---\n', "[[Doe_X_2025.pdf]]"),
                ("an indented sources: belongs to another key",
                 "---\ncitation:\n  sources:\n    - %s\n---\n" % URL, None),
                ("legacy scalar", "---\nsource: %s\n---\nbody\n" % URL, URL),
                ("double-quoted", '---\nsource: "%s"\n---\n' % URL, URL),
                ("single-quoted", "---\nsource: '%s'\n---\n" % URL, URL),
                ("capitalised key", "---\nSource: %s\n---\n" % URL, URL),
                ("leading blank lines", "\n\n---\nsource: %s\n---\n" % URL, URL),
                ("an indented source: is nested under another key, not ours",
                 "---\ncitation:\n  source: %s\n---\n" % URL, None),
                ("the first source: wins",
                 "---\nsource: %s\nsource: https://other.example/b\n---\n" % URL,
                 URL),
                ("no frontmatter at all", "just prose\n", None),
                ("frontmatter with no source:", "---\ntitle: x\n---\n", None),
                ("an empty source:", "---\nsource:\n---\n", None),
                ("a `---` inside the body does not reopen it",
                 "---\ntitle: x\n---\n\n---\nsource: %s\n" % URL, None)):
            case("read_source, %s" % label, read_source(note(
                label.replace(" ", "_")[:40] + ".md", body)), want)

        # A trailing YAML comment is a comment, not part of the URL.
        case("read_source strips a trailing comment",
              read_source(note("comment.md",
                               "---\nsource: %s # canonical\n---\n" % URL)), URL)
        case("...and the key has no trailing space",
              normalize_url(read_source(note(
                  "comment2.md",
                  "---\nsource: %s # canonical\n---\n" % URL))), URL)
        case("a `#` inside the URL is a fragment, not a comment",
              read_source(note("frag.md",
                               "---\nsource: %s#top\n---\n" % URL)), URL + "#top")
        case("a comment after a quoted value is dropped too",
              read_source(note("qcomment.md",
                               '---\nsource: "%s" # canonical\n---\n' % URL)), URL)
        # A comment or blank line BETWEEN `sources:` and item 1 is valid YAML
        # (Obsidian still reads the item); consuming the pending flag on one
        # left the real item unread and the note indexed as unindexable.
        case("a comment line between sources: and item 1 does not blind the reader",
              read_source(note("scomment.md",
                               '---\nsources:\n  # capture URL\n  - "%s"\n---\n'
                               % URL)), URL)
        case("...nor does a blank line there",
              read_source(note("sblank.md",
                               '---\nsources:\n\n  - "%s"\n---\n' % URL)), URL)
        # A BOM, and CRLF line endings: both are what an editor round-trip
        # produces, and either one used to be able to hide the whole note.
        case("a BOM does not hide the frontmatter",
              read_source(note("bom.md", "﻿---\nsource: %s\n---\n" % URL)),
              URL)
        case("CRLF line endings",
              read_source(note("crlf.md",
                               "---\r\nsource: %s\r\n---\r\nbody\r\n" % URL)), URL)
        case("BOM and CRLF together",
              read_source(note("bomcrlf.md",
                               "﻿---\r\nsource: %s\r\n---\r\n" % URL)), URL)
        # An UNTERMINATED fence is not frontmatter. Reading on into the body
        # picked up a `source:` from the article's own prose and indexed the
        # note under it -- invisible to its own duplicate check, and an answer
        # to somebody else's.
        case("an unterminated fence yields nothing",
              read_source(note("unterminated.md",
                               "---\ntitle: x\n\nprose\n\nsource: %s\n" % URL)),
              None)
        case("...even when the body's source: is the first one",
              read_source(note("unterminated2.md",
                               "---\nsource: %s\n\nprose\n" % URL)), None)
        case("a missing file is not a source", read_source(
            os.path.join(tmp, "nope.md")), None)
        case("a directory is not a source", read_source(tmp), None)

        # --- build_index: what goes in, what is counted, what is set aside --
        vault = os.path.join(tmp, "Articles")
        os.makedirs(vault)

        def article(name, body):
            p = os.path.join(vault, name)
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(body)
            return p

        a = article("A.md", "---\nsource: %s\n---\n" % URL)
        b = article("B.md", "---\nsource: https://www.example.com/a/?utm_a=1\n---\n")
        c = article("C.md", "---\ntitle: no source\n---\n")
        # paper-summarizer's shape: a summary note keyed to a PDF basename. It
        # shares Articles/ and is NOT a URL source -- indexing it would key a
        # whole note under `[[Doe_Foo_2025.pdf]]`, and reporting it as
        # unindexable would tell the user their vault is broken once per paper.
        d = article("Doe_Foo_2025.md",
                    '---\nsource: "[[Doe_Foo_2025.pdf]]"\n---\n')
        index, unindexable, non_url = build_index(vault)
        case("two spellings of one URL are one key", len(index), 1)
        case("...and both notes are under it",
              sorted(index.get(normalize_url(URL), [])) , sorted([a, b]))
        case("a note with no source: is counted, not dropped",
              unindexable, [c])
        case("a wikilink source: is set aside as non-URL",
              [x["path"] for x in non_url], [d])
        case("...and is not in the URL index",
              any(d in v for v in index.values()), False)
        case("--exclude keeps a note from matching itself",
              build_index(vault, exclude=[a])[0].get(normalize_url(URL)), [b])
        malformed = article("Malformed.md",
                            '---\nsources:\n  - "https://[broken/article"\n---\n')
        after_bad, unreadable, _ = build_index(vault)
        case("a malformed URL note is reported without aborting the batch",
             (after_bad, sorted(unreadable)),
             (index, sorted([c, malformed])))

        # --- case(): verdicts, including within one batch ------------------
        res = check([{"id": "raw1", "source": URL},
                     {"id": "raw2", "source": "https://example.com/new"},
                     {"id": "raw3", "source": "https://example.com/new?utm_x=1"},
                     {"id": "raw4", "source": None}], index)
        case("a known URL is a duplicate", res[0]["status"], "duplicate")
        case("...naming the note it duplicates", res[0]["matches"], sorted([a, b]))
        case("an unknown URL is new", res[1]["status"], "new")
        case("a second capture of it in the same batch is caught",
              res[2]["status"], "duplicate-of-earlier-input")
        case("a raw with no source: is not silently `new`",
              res[3]["status"], "no-source")
        invalid_raws = check([
            {"id": "malformed", "source": "https://[broken/article"},
            {"id": "local", "source": "file:///article.md"},
            {"id": "hostless", "source": "https://"},
            {"id": "valid", "source": "https://example.com/valid"}], {})
        case("bad raw origins are no-source and do not stop later valid inputs",
             [r["status"] for r in invalid_raws],
             ["no-source", "no-source", "no-source", "new"])
        case("the live index did not leak into the caller's",
              sorted(index), sorted([normalize_url(URL)]))
        quoted_note = article("Quoted.md",
                              "---\nsources: # verified\n"
                              "- 'https://example.com/o''brien'\n---\n")
        quoted_index = build_index(vault)[0]
        quoted_check = check([{"id": "raw-quoted", "source": "https://example.com/o'brien"}],
                             quoted_index)
        case("editor-saved quote escaping cannot hide an existing article",
             (quoted_check[0]["status"], quoted_check[0]["matches"]),
             ("duplicate", [quoted_note]))

        # --- the three guards this script backs must agree with each other ---
        # Guard 2 (step 3) is the one line an agent actually reads when the
        # filename check fires, and on a different-source collision it said
        # "carry on; step 11 appends `_2`". SKILL.md step 3, SKILL.md step 11
        # and Guard 3 all say the opposite: settle the slug HERE. Following
        # Guard 2 routes execution past step 6, which downloads the images
        # under the UN-SUFFIXED slug — so the note ships as `<slug>_2.md` while
        # its figures sit at `<slug>_fig_N.*`, its embeds resolve to nothing,
        # and the next consumer to walk `<slug>_fig*` merges them into the
        # other owner's set. A contradiction between four places is a bug in
        # whichever one is read at the moment of the decision.
        def _doc(*parts):
            path = os.path.normpath(os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "..", *parts))
            try:
                with open(path, encoding="utf-8") as fh:
                    return fh.read()
            except OSError as exc:
                cases.append(("%s sits next to this script" % "/".join(parts),
                              False, "%s: %s" % (type(exc).__name__, exc),
                              "readable"))
                return ""

        dup_md = _doc("references", "duplicates-and-reprocessing.md")
        guard2 = dup_md.split("## Guard 2")[-1].split("## Guard 3")[0]
        case("Guard 2 does not defer a different-source collision to step 11",
             bool(re.search(r"Carry on; step 11 appends", guard2)), False)
        case("Guard 2 settles the slug before step 6 writes an image",
             bool(re.search(r"before step 6 writes", guard2)), True)
        case("...and says to disambiguate to `_2` there and then",
             bool(re.search(r"`<slug>_2`|`_2`", guard2)), True)
        # the other three statements of the same rule are still there, so this
        # is agreement rather than a contradiction moved somewhere else
        skill_md = _doc("SKILL.md")
        case("SKILL.md step 3 still settles the collision at step 3",
             "settled *here*, not at step 11" in skill_md, True)
        case("SKILL.md step 11 still sends a collision back to step 3",
             "go back to step 3" in skill_md, True)
        case("Guard 3 still sends a collision back to step 3",
             "go back to step 3 and re-derive the slug" in dup_md, True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [c for c in cases if not c[1]]
    for label, ok, got, want in cases:
        if not ok:
            print("FAIL  %s\n        got  %r\n        want %r"
                  % (label, got, want))
    print("%d/%d self-test cases pass" % (len(cases) - len(failed), len(cases)))
    return 1 if failed else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cleaned_dir", nargs="?")
    ap.add_argument("--raw", action="append", default=[],
                    help="raw .md file or folder of them; repeatable")
    ap.add_argument("--url", action="append", default=[],
                    help="bare URL to check; repeatable")
    ap.add_argument("--exclude", action="append", default=[],
                    help="note to leave out of the index (reprocessing a Articles/ file)")
    ap.add_argument("--dump-index", action="store_true")
    ap.add_argument("--test", action="store_true", help="run the self-test")
    args = ap.parse_args(argv)

    if args.test:
        return run_self_test()
    if not args.cleaned_dir:
        ap.error("give the Articles/ folder, or --test")

    if not os.path.isdir(args.cleaned_dir):
        print(json.dumps({"error": f"not a directory: {args.cleaned_dir}"}))
        return 1

    index, unindexable, non_url = build_index(args.cleaned_dir, args.exclude)

    # A --raw path that doesn't exist is a typo, not a clean skip: left to fall
    # through it reads a missing file, gets None, and reports `no-source`, which
    # looks exactly like a raw with no source field.
    missing = [r for r in args.raw if not os.path.exists(r)]
    if missing:
        print(json.dumps({"error": "--raw path does not exist: "
                                   + ", ".join(missing)}))
        return 1

    entries = []
    for raw in args.raw:
        paths = _md_files(raw) if os.path.isdir(raw) else [raw]
        for p in paths:
            entries.append({"id": p, "source": read_source(p)})
    for u in args.url:
        entries.append({"id": u, "source": u})

    results = check(entries, index)
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    out = {
        "cleaned_dir": args.cleaned_dir,
        "indexed_notes": sum(len(v) for v in index.values()),
        "distinct_urls": len(index),
        "unindexable": unindexable,
        "unindexable_count": len(unindexable),
        "non_url_sources": non_url,
        "collisions": {k: v for k, v in index.items() if len(v) > 1},
        "checked": results,
        "counts": counts,
    }
    if args.dump_index:
        out["index"] = index
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
