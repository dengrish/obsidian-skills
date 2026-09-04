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
                           [--slug STEM ...] [--exclude PATH ...] [--dump-index]

    <cleaned_dir>   the vault's Articles/ folder
    --raw           a raw .md file, or a folder of them (Inbox/); repeatable
    --url           a bare URL to check, instead of / as well as --raw
    --slug          a proposed clipping-note stem to check against the portable
                    direct-child Articles/ namespace; repeatable
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
    article_name_index(cleaned_dir) -> {portable_name: [paths]}
    check_slugs(slugs, name_index) -> list[dict]
    run_self_test() -> int

Output: one JSON object on stdout. Exit status is 0 whenever the scan ran.
Stdlib only.
"""

import argparse
import json
import os
import re
import stat
import sys
import unicodedata
from urllib.parse import unquote_plus, urlsplit, urlunsplit

_OBSIDIAN_SHARED_MODULES = ('slugify', 'yaml_scalars')

# --- obsidian shared-layer bootstrap (canonical; see shared/CONVENTIONS.md) ---
import os as _os, sys as _sys
_here = _os.path.dirname(_os.path.realpath(__file__))
_required = tuple(_m + ".py" for _m in (
    globals().get("_OBSIDIAN_SHARED_MODULES") or ("slugify",)))
_env = _os.environ.get("OBSIDIAN_VAULT_SHARED")
if _env:                                   # explicit override: authoritative, no fallback
    _tried = [_os.path.abspath(_os.path.expanduser(_env))]
else:                                      # plugin-relative walk-up, at most 5 levels
    _tried, _d = [], _here
    for _ in range(5):
        _tried.append(_os.path.join(_d, "shared", "scripts"))
        _d = _os.path.dirname(_d)
    _tried.append(_here)                   # extracted skill with co-located helpers
_missing = {_p: [_m for _m in _required if not _os.path.isfile(_os.path.join(_p, _m))]
            for _p in _tried if _os.path.isdir(_p)}
_shared = next((_p for _p in _tried if _p in _missing and not _missing[_p]), None)
if _shared is None:
    raise SystemExit("""obsidian: cannot find the plugin's shared/scripts/ folder, which holds
the one canonical copy of the conventions this script depends on. A usable
folder must contain these required module(s): %s
Looked for:
  %s
Fix: install the whole plugin tree, or set OBSIDIAN_VAULT_SHARED to the
shared/scripts/ directory (unset it to use the plugin-relative walk-up).
Do NOT paste a second copy of the algorithm into this skill -- a divergent
copy is the bug the shared layer exists to prevent.""" % (
    ", ".join(_required), "\n  ".join(
        _p + (" (not a directory)" if _p not in _missing else
              " (missing: %s)" % ", ".join(_missing[_p]))
        for _p in _tried)))
_sys.path[:] = [_p for _p in _sys.path if _p not in (_shared, _here)]
_sys.path.insert(0, _shared)               # shared/scripts/ FIRST
if _here != _shared:
    _sys.path.insert(1, _here)              # sibling modules before unrelated paths
# --- end bootstrap ---

from slugify import is_windows_device_stem
from yaml_scalars import parse_scalar, strip_comment


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
    "fbclid", "gclid", "mc_cid", "mc_eid",
}
TRACKING_PREFIXES = ("utm_",)
SUBSTACK_TRACKING_PARAMS = {"r", "showwelcome"}
X_TRACKING_PARAMS = {"s", "t"}

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
    host_name = parts.hostname.lower().rstrip(".")
    is_substack = host_name == "substack.com" or host_name.endswith(".substack.com")
    is_x = host_name in {"x.com", "twitter.com", "mobile.twitter.com"}
    query_fields = []
    for field in parts.query.split("&") if parts.query else ():
        # Decode only a COPY of the key to recognize percent-encoded tracking
        # spellings. Keep every surviving field byte-for-byte. parse_qsl plus
        # urlencode used to turn `+` and `%20` into one spelling, add `=` to a
        # bare flag, replace malformed percent escapes, and re-encode Unicode.
        # Any of those can change a signed/routing query or collapse two pages
        # onto one key — the expensive failure direction for a dedup guard.
        raw_key = field.split("=", 1)[0]
        try:
            key = unquote_plus(raw_key, errors="strict").lower()
        except (UnicodeDecodeError, ValueError):
            key = raw_key.lower()
        if key in TRACKING_PARAMS \
                or any(key.startswith(p) for p in TRACKING_PREFIXES) \
                or (is_substack and key in SUBSTACK_TRACKING_PARAMS) \
                or (is_x and key in X_TRACKING_PARAMS):
            continue
        query_fields.append(field)
    # Preserve order AND spelling. An HTTP query is opaque to the origin: some
    # applications interpret repeated keys in order, distinguish encodings, or
    # sign the original query bytes. A false negative here is caught by the
    # later slug ownership check; a false duplicate has no downstream recovery.
    query = "&".join(query_fields)
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
SOURCES_RE = re.compile(r"\Asources\s*:\s*(.*)\Z", re.IGNORECASE)
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

    Both are still valid YAML frontmatter as far as Obsidian is concerned. The
    entire note is nevertheless decoded strictly before this metadata can
    establish ownership; invalid UTF-8 anywhere returns no origin.

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
        # Decode the whole note before trusting its frontmatter. Reading only
        # through the closing fence lets invalid bytes in the body hide behind
        # a valid-looking origin and claim a publication identity.
        with open(path, "r", encoding="utf-8-sig", errors="strict") as fh:
            lines = iter(fh.read().splitlines())
        for first in lines:                    # skip leading blank lines
            if first.strip():
                break
        else:
            return None
        if first.strip() != "---":
            return None
        found = {}
        pending = False
        for raw in lines:
            if raw.strip() == "---":
                return found.get("sources", found.get("source")) or None
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            if pending:
                pending = False
                mi = _ITEM_RE.match(raw)
                if mi:
                    found["sources"] = _yaml_scalar(mi.group(1))
                    continue
            m = SOURCES_RE.match(raw)
            if m:
                if "sources" in found:
                    return None                # duplicate origin keys are ambiguous
                found["sources"] = None
                # A present but unsupported/empty current field must not
                # manufacture ownership from a stale legacy value.
                pending = not strip_comment(m.group(1)).strip()
                continue
            m = SOURCE_RE.match(raw)
            if m:
                if "source" in found:
                    return None
                found["source"] = _yaml_scalar(m.group(1))
    except UnicodeError:
        return None
    except (OSError, ValueError):
        return None
    return None


def _md_files(folder):
    def failed(exc):
        raise ValueError("cannot complete Markdown scan of %r: %s" %
                         (exc.filename or folder, exc)) from exc

    out = []
    for root, _dirs, files in os.walk(folder, onerror=failed):
        for f in sorted(files):
            if f.lower().endswith(".md"):
                out.append(os.path.join(root, f))
    return sorted(out)


def _validated_exclusions(cleaned_dir, exclude):
    """Resolve explicit reprocessing exclusions to unique direct note paths.

    A typo must never make a duplicate check look clean. Exclusions therefore
    have to identify one existing, regular direct child of the Articles folder
    under the plugin's portable filename identity.
    """
    try:
        names = os.listdir(cleaned_dir)
    except OSError as exc:
        raise ValueError("cannot inspect Articles names in %r: %s" %
                         (cleaned_dir, exc)) from exc
    by_name = {}
    for name in names:
        if _portable_name(name).endswith(".md"):
            by_name.setdefault(_portable_name(name), []).append(
                os.path.join(cleaned_dir, name))
    resolved = []
    for requested in exclude:
        requested_abs = os.path.abspath(os.path.expanduser(requested))
        parent = os.path.dirname(requested_abs)
        try:
            same_parent = os.path.samefile(parent, cleaned_dir)
        except OSError:
            same_parent = False
        matches = (by_name.get(_portable_name(os.path.basename(requested_abs)), [])
                   if same_parent else [])
        if len(matches) != 1:
            detail = "no direct note" if not matches else "%d portable-name occupants" % len(matches)
            raise ValueError("--exclude %r identifies %s in Articles; refusing "
                             "an unverifiable exclusion" % (requested, detail))
        candidate = matches[0]
        try:
            if not stat.S_ISREG(os.lstat(candidate).st_mode):
                raise ValueError("--exclude %r is not a regular note" % requested)
        except OSError as exc:
            raise ValueError("cannot inspect --exclude %r: %s" %
                             (requested, exc)) from exc
        resolved.append(os.path.abspath(candidate))
    return resolved


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
    excluded = set(_validated_exclusions(cleaned_dir, exclude))
    index, unindexable, non_url = {}, [], []
    for path in _md_files(cleaned_dir):
        if os.path.abspath(path) in excluded:
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


def _portable_name(name):
    """One filename identity across supported case and Unicode semantics."""
    return unicodedata.normalize("NFC", name).casefold()


def article_name_index(cleaned_dir, exclude=()):
    """Map each portable direct-child Markdown name to every occupant.

    `Articles/` is flat. An entry whose name ends in `.md` occupies that output
    identity regardless of its filesystem type, so directories and symlinks
    (including dangling ones) remain visible to the publication preflight.
    """
    excluded = set(_validated_exclusions(cleaned_dir, exclude))
    try:
        names = os.listdir(cleaned_dir)
    except OSError as exc:
        raise ValueError("cannot inspect Articles names in %r: %s" %
                         (cleaned_dir, exc)) from exc
    index = {}
    for name in names:
        if not _portable_name(name).endswith(".md"):
            continue
        path = os.path.join(cleaned_dir, name)
        if os.path.abspath(path) in excluded:
            continue
        index.setdefault(_portable_name(name), []).append(
            path)
    for paths in index.values():
        paths.sort(key=lambda path: (_portable_name(os.path.basename(path)),
                                     os.path.basename(path)))
    return index


def _slug_filename(slug):
    """Validate one slug stem and return its Markdown filename."""
    invalid = [ch for ch in slug
               if ord(ch) < 0x20 or ord(ch) == 0x7f
               or ch in '<>:"/\\|?*'] if isinstance(slug, str) else []
    if not isinstance(slug, str) or not slug or invalid or ".." in slug \
            or slug.startswith((".", " ")) \
            or not slug.strip(". ") or slug.endswith((".", " ")) \
            or os.path.basename(slug) != slug \
            or "/" in slug or "\\" in slug or slug.casefold().endswith(".md"):
        raise ValueError("--slug takes a non-empty filename stem, without a path "
                         "or .md extension, using portable filename characters: "
                         "%r" % slug)
    if is_windows_device_stem(slug):
        raise ValueError(
            "--slug %r is a reserved Windows device basename even with .md "
            "appended; choose a more specific portable stem" % slug)
    return slug + ".md"


def check_slugs(slugs, name_index):
    """Classify proposed stems as free, occupied, or ambiguous."""
    results = []
    for slug in slugs:
        filename = _slug_filename(slug)
        matches = list(name_index.get(_portable_name(filename), ()))
        status = "free" if not matches else "occupied" if len(matches) == 1 \
            else "ambiguous"
        results.append({"slug": slug, "filename": filename, "status": status,
                        "matches": matches})
    return results


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
    from unittest.mock import patch

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
    case("query order is preserved",
          normalize_url("https://example.com/a?b=2&a=1"),
          "https://example.com/a?b=2&a=1")
    case("surviving query spelling is preserved while tracking is removed",
          normalize_url("https://example.com/a?utm_source=x&q=a%20b&flag"),
          "https://example.com/a?q=a%20b&flag")
    differ("literal plus and percent-encoded space can be different routes",
           "https://example.com/a?q=a+b",
           "https://example.com/a?q=a%20b")
    differ("a bare flag and an explicitly empty value retain their spelling",
           "https://example.com/a?preview",
           "https://example.com/a?preview=")
    same("a percent-encoded tracking key is still tracking",
         "https://example.com/a?utm%5Fsource=x",
         "https://example.com/a")
    differ("origins may route unique query keys in order",
           "https://example.com/a?a=1&b=2",
           "https://example.com/a?b=2&a=1")
    differ("repeated query keys can be order-sensitive",
           "https://example.com/a?step=first&step=second",
           "https://example.com/a?step=second&step=first")
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
                  "gclid", "mc_cid", "mc_eid"):
        same("tracking %s carries no identity" % param,
             "https://example.com/a?%s=x" % param, "https://example.com/a")
    for param in ("r", "showWelcome"):
        same("Substack tracking %s carries no identity on Substack" % param,
             "https://newsletter.substack.com/p/a?%s=x" % param,
             "https://newsletter.substack.com/p/a")
        differ("?%s= is preserved on an unrelated origin" % param,
               "https://example.com/a?%s=1" % param,
               "https://example.com/a?%s=2" % param)
    for param in ("s", "t"):
        same("X/Twitter sharing parameter %s carries no identity" % param,
             "https://x.com/example/status/1?%s=20" % param,
             "https://x.com/example/status/1")
        differ("?%s= is preserved on an unrelated origin" % param,
               "https://example.com/a?%s=1" % param,
               "https://example.com/a?%s=2" % param)
    for param in ("id", "p", "page", "v", "story", "q", "referrer", "share"):
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

        def note_bytes(name, body):
            p = os.path.join(tmp, name)
            with open(p, "wb") as fh:
                fh.write(body)
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
                ("duplicate source: keys cannot establish an origin",
                 "---\nsource: %s\nsource: https://other.example/b\n---\n" % URL,
                 None),
                ("current sources wins over an earlier legacy source",
                 '---\nsource: "[[Old_Paper_2025.pdf]]"\nsources:\n'
                 '  - "%s"\n---\n' % URL, URL),
                ("current sources wins over a later legacy source",
                 '---\nsources:\n  - "%s"\nsource: "[[Old_Paper_2025.pdf]]"\n---\n'
                 % URL, URL),
                ("duplicate sources keys are ambiguous",
                 '---\nsources:\n  - "%s"\nsources:\n'
                 '  - "https://other.example/b"\n---\n' % URL, None),
                ("empty current sources does not fall back to a legacy source",
                 '---\nsource: "%s"\nsources:\n---\n' % URL, None),
                ("unsupported current sources does not use a stale origin",
                 '---\nsource: "%s"\nsources: null\n---\n' % URL, None),
                ("malformed current origin does not use a stale origin",
                 '---\nsource: "%s"\nsources:\n  - "unterminated\n---\n' % URL,
                 None),
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
        case("invalid UTF-8 in frontmatter cannot establish ownership",
             read_source(note_bytes(
                 "invalid-frontmatter.md",
                 b'---\ntitle: \xff\nsources:\n  - "https://example.com/a"\n---\n')),
             None)
        case("invalid UTF-8 in the body cannot hide behind valid frontmatter",
             read_source(note_bytes(
                 "invalid-body.md",
                 b'---\nsources:\n  - "https://example.com/a"\n---\nbody \xff\n')),
             None)

        # Extension dispatch is case-insensitive everywhere else in the plugin.
        # On a case-sensitive Linux vault, the old lowercase-only scan silently
        # omitted an existing `Reviewed.MD` from the supposedly complete dedup
        # inventory and could classify its raw capture as new.
        mixed_case = os.path.join(tmp, "mixed-case")
        os.makedirs(mixed_case)
        upper_md = note(os.path.join("mixed-case", "Reviewed.MD"),
                        "---\nsource: %s\n---\n" % URL)
        note(os.path.join("mixed-case", "Ignored.txt"),
             "---\nsource: %s\n---\n" % URL)
        case("a complete Markdown inventory includes uppercase .MD files",
             _md_files(mixed_case), [upper_md])

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
        case("--exclude also releases that note's output-name slot",
             check_slugs(["A"], article_name_index(vault, exclude=[a]))[0]["status"],
             "free")
        try:
            build_index(vault, exclude=[os.path.join(vault, "Typo.md")])
        except ValueError:
            bad_exclusion_rejected = True
        else:
            bad_exclusion_rejected = False
        case("a nonexistent --exclude cannot silently weaken the guard",
             bad_exclusion_rejected, True)
        malformed = article("Malformed.md",
                            '---\nsources:\n  - "https://[broken/article"\n---\n')
        after_bad, unreadable, _ = build_index(vault)
        case("a malformed URL note is reported without aborting the batch",
             (after_bad, sorted(unreadable)),
             (index, sorted([c, malformed])))

        # Slug occupancy is a direct-child namespace check, separate from URL
        # ownership. Every `.md` directory entry occupies a publish name,
        # including types a provenance reader cannot open.
        os.makedirs(os.path.join(vault, "Held.md"))
        link_target = article("link-target.txt", "not a note")
        try:
            os.symlink(os.path.join(tmp, "missing-target"),
                       os.path.join(vault, "Broken.md"))
            os.symlink(link_target, os.path.join(vault, "Linked.md"))
            symlink_occupants_exercised = True
        except (OSError, NotImplementedError):
            # Preserve the portable-name occupancy part of this test on hosts
            # where creating symlinks needs a privilege the process lacks.
            for fallback in ("Broken.md", "Linked.md"):
                path = os.path.join(vault, fallback)
                if not os.path.lexists(path):
                    article(fallback, "placeholder occupant")
            symlink_occupants_exercised = False
        name_index = article_name_index(vault)
        slug_results = check_slugs(
            ["Held", "Broken", "Linked", "a", "Free"], name_index)
        case("slug checks include directories, broken links, links and case aliases",
             [(row["slug"], row["status"]) for row in slug_results],
             [("Held", "occupied"), ("Broken", "occupied"),
              ("Linked", "occupied"), ("a", "occupied"),
              ("Free", "free")])
        case("symlink occupancy cases run or degrade without crashing",
             isinstance(symlink_occupants_exercised, bool), True)
        with patch.object(os, "listdir", return_value=[
                    "Caf\u00e9.md", "Cafe\u0301.MD", "ignored.txt"]):
            ambiguous_index = article_name_index(vault)
        case("NFC/case-equivalent direct names are ambiguous",
             check_slugs(["CAF\u00c9"], ambiguous_index)[0]["status"],
             "ambiguous")
        case("an ambiguous slug reports every occupying spelling",
             len(check_slugs(["caf\u00e9"], ambiguous_index)[0]["matches"]), 2)
        for invalid_slug in ("", "\0", ".", "..", "path/name", "path\\name",
                             "x.md", "CON", "prn", "COM1", "lpt9",
                             "AUX.extra", "bad:name", "bad?name", "trail.",
                             "trail ", "two..dots", "line\nbreak", 7):
            try:
                check_slugs([invalid_slug], name_index)
            except ValueError:
                rejected = True
            else:
                rejected = False
            case("invalid slug is rejected: %r" % invalid_slug, rejected, True)

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

        # A failed walk must not publish an empty index or an empty input list.
        # Inject scandir's OS error so the real os.walk error path runs on
        # platforms where chmod does not restrict the test user's access.
        import contextlib
        import io
        hidden = os.path.join(vault, "restricted")
        os.makedirs(hidden)
        with open(os.path.join(hidden, "Reviewed.md"), "w") as fh:
            fh.write('---\nsource: "%s"\n---\nUser-edited text.\n' % URL)
        scandir = os.scandir

        def denied(path):
            if path == hidden:
                raise PermissionError(13, "permission denied", path)
            return scandir(path)

        for label, argv in (
                ("an incomplete Articles scan cannot say a URL is new",
                 [vault, "--url", URL]),
                ("an incomplete raw scan cannot say there is nothing to process",
                 [os.path.join(tmp, "empty-articles"), "--raw", hidden])):
            os.makedirs(os.path.join(tmp, "empty-articles"), exist_ok=True)
            output = io.StringIO()
            with patch.object(os, "scandir", side_effect=denied), \
                    contextlib.redirect_stdout(output):
                code = main(argv)
            result = json.loads(output.getvalue())
            case(label, (code, bool(result.get("error")), "checked" in result),
                 (1, True, False))

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main([vault, "--slug", "Held", "--slug", "Free"])
        public_slugs = json.loads(output.getvalue()).get("slug_checks", [])
        case("the public CLI returns repeatable slug checks",
             (code, [(row["slug"], row["status"]) for row in public_slugs]),
             (0, [("Held", "occupied"), ("Free", "free")]))

        # Naming must precede image writes, and a late collision must return
        # to that decision. Check the linked action gates without requiring
        # historical step numbers or several copies of the repair procedure.
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
        skill_md = _doc("SKILL.md")
        collision = re.search(
            r"(?ms)^## Settle a slug before writing images\n(.*?)(?=^## |\Z)",
            dup_md)
        guard = collision.group(1) if collision else ""
        case("the workflow links to the required pre-image collision procedure",
             bool(collision) and
             "references/duplicates-and-reprocessing.md#settle-a-slug-before-writing-images"
             in skill_md, True)
        naming = skill_md.find("Settle the slug before downloading any image")
        download = skill_md.find("fetch_images.py' stage")
        case("the naming decision precedes the image download command",
             0 <= naming < download, True)
        case("a collision uses the same disambiguator for note and image stem",
             "`<slug>_2`" in guard and "Use the suffix for both" in guard, True)
        case("the collision procedure returns a late conflict to naming",
             bool(re.search(r"final publication.{0,100}return to this check",
                            guard, re.S)), True)
        case("the publication gate also returns a late conflict to naming",
             bool(re.search(r"collision discovered.{0,100}returns to the naming decision",
                            skill_md, re.S)), True)
        case("a naming collision never authorizes moving another owner's figures",
             bool(re.search(r"(?:Never|Do not) rename another owner's figures",
                            guard)), True)
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
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (OSError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cleaned_dir", nargs="?")
    ap.add_argument("--raw", action="append", default=[],
                    help="raw .md file or folder of them; repeatable")
    ap.add_argument("--url", action="append", default=[],
                    help="bare URL to check; repeatable")
    ap.add_argument("--slug", action="append", default=[],
                    help="proposed clipping-note stem to check; repeatable")
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

    try:
        index, unindexable, non_url = build_index(args.cleaned_dir, args.exclude)
        slug_checks = (check_slugs(
            args.slug, article_name_index(args.cleaned_dir, args.exclude))
                       if args.slug else [])
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}))
        return 1

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
        try:
            paths = _md_files(raw) if os.path.isdir(raw) else [raw]
        except ValueError as exc:
            print(json.dumps({"error": str(exc)}))
            return 1
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
        "slug_checks": slug_checks,
    }
    if args.dump_index:
        out["index"] = index
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
