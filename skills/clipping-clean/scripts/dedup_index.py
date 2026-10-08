#!/usr/bin/env python3
"""Build the Articles/ dedup index and check raw clippings against it.

`Articles/` is this skill's output and its sole dedup index: a raw is
already processed if and only if the first current `sources:` item (legacy
`source:` only when `sources:` is absent) of some Articles/ note normalizes to
its URL. This script does the mechanical half of step 1 — one pass over Articles/,
URL normalization on both sides, and (optionally) a verdict per raw — so the
scan is a single pass rather than a quadratic one, and the normalization rules
are applied the same way every run.

The decisions stay with the model: what to do with each verdict (skip a
duplicate in batch, ask in explicit-single-file mode) is in SKILL.md step 1;
references/duplicates-and-reprocessing.md covers reprocessing and collisions.

CLI
    python3 dedup_index.py '<cleaned_dir>' [--raw PATH ...] [--url URL ...]
                           [--slug STEM ...] [--exclude PATH ...] [--dump-index]

    <cleaned_dir>   the vault's Articles/ folder
    --raw           a raw .md file, or a folder of them (Inbox/); repeatable
    --url           a bare URL to check, instead of / as well as --raw
    --slug          a proposed clipping-note stem to check against the portable
                    direct-child Articles/ namespace; repeatable
    --exclude       a note to leave out of the index — use it when reprocessing a
                    file that itself lives in Articles/, so it can't match itself;
                    a legacy wiki-add research extract is refused
    --dump-index    include the whole {normalized_url: path} map in the output
    --test          run the built-in cases (no arguments, writes nothing
                    outside a temp dir)

Importable
    normalize_url(url) -> str
    variant_key(url) -> str
    split_frontmatter(text) -> (frontmatter_lines, body) | None
    read_source(path)  -> str | None
    is_research_extract(path) -> bool
    is_research_extract_text(text) -> bool
    build_index(cleaned_dir, exclude=()) -> (index, unindexable, non_url)
    check(entries, index) -> list[dict]
    article_name_index(cleaned_dir) -> {portable_name: [paths]}
    check_slugs(slugs, name_index) -> list[dict]
    stem_mismatches(paths) -> list[dict]
    run_self_test() -> int

Output: one JSON object on stdout. Exit status is 0 whenever the scan ran.
Each `checked` row lists, in `research_extracts`, the matching Articles notes
that are legacy wiki-add research extracts (wiki-add creates none). Its
`variant_matches` lists the Articles notes and earlier inputs whose URL
differs from its own only by an http scheme, a mobile or AMP host label, a
trailing `/amp` segment or an arXiv version; they do not change its status.
`stem_mismatch` lists URL-owning notes whose rendered
`![[…_fig…]]` embeds use another stem. Dot-prefixed subfolders (private
stages, hidden folders) are not scanned. Stdlib only.
"""

import argparse
import json
import os
import re
import stat
import sys
import unicodedata
from urllib.parse import unquote_plus, urlsplit, urlunsplit

_OBSIDIAN_SHARED_MODULES = (
    'entry_structure', 'markdown_tables', 'slugify', 'yaml_scalars')

# --- obsidian shared-layer bootstrap (canonical; see shared/RUNTIME.md) ---
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

from entry_structure import mask_body_comments
from yaml_scalars import read_note_origin, read_regular_text, yaml_lines


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
# exactly what the naming gate (SKILL.md step 2) exists to catch. Strip what is
# provably noise, and no further.
TRACKING_PARAMS = {
    "fbclid", "gclid", "mc_cid", "mc_eid", "triedredirect",
}
TRACKING_PREFIXES = ("utm_",)
#: Substack also serves custom domains; there the `/p/<post>` path marks the
#: platform, so its referral parameters are stripped on those hosts too.
SUBSTACK_TRACKING_PARAMS = {"r", "showwelcome"}
X_TRACKING_PARAMS = {"s", "t"}

#: A fragment that ROUTES rather than anchors: `#/posts/1`, `#!/posts/1`.
#: Dropping every fragment collapsed a fragment-routed SPA onto one key — every
#: article on `app.example.com/#/posts/<n>` normalized to `app.example.com`, so
#: the first one clipped made every later one a `duplicate` and the whole site
#: became un-clippable after one article. An `#anchor-id` still goes: that is a
#: position within one page, not part of the page's identity.
ROUTING_FRAGMENT = ("/", "!")


def _normalized_netloc(parts):
    """Lowercase only the host, preserving case-sensitive user information."""
    netloc = parts.netloc
    userinfo, separator, authority = netloc.rpartition("@")
    prefix = userinfo + separator if separator else ""
    authority = authority if separator else netloc
    if authority.startswith("["):
        closing = authority.find("]")
        host = authority[:closing + 1].lower()
        suffix = authority[closing + 1:]
    else:
        host, port_separator, port = authority.rpartition(":")
        if not port_separator:
            host, suffix = authority, ""
        else:
            suffix = port_separator + port
        host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    return prefix + host + suffix


def normalize_url(url):
    """Normalize an HTTP(S) URL for identity; invalid origins return no key."""
    if not isinstance(url, str):
        return ""
    url = url.strip()
    if len(url) >= 2 and url[0] == url[-1] and url[0] in "\"'":
        url = url[1:-1].strip()
    if not url:
        return ""
    if any(ord(ch) < 0x20 or ord(ch) == 0x7f for ch in url):
        return ""
    try:
        parts = urlsplit(url)
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
            return ""
        if any(ch.isspace() for ch in parts.hostname):
            return ""
        # Accessing port validates it; urlsplit alone accepts `:not-a-port`.
        port = parts.port
    except ValueError:
        return ""
    authority = parts.netloc.rsplit("@", 1)[-1]
    if authority.endswith(":") or port == 0:
        return ""
    scheme = parts.scheme.lower()
    host = _normalized_netloc(parts)
    path = parts.path.rstrip("/")
    host_name = parts.hostname.lower().rstrip(".")
    normalized_host_name = (host_name[4:] if host_name.startswith("www.")
                            else host_name)
    is_substack = (normalized_host_name == "substack.com"
                   or normalized_host_name.endswith(".substack.com")
                   or re.fullmatch(r"/p/[^/]+", path) is not None)
    is_x = normalized_host_name in {
        "x.com", "twitter.com", "mobile.twitter.com"}
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
    # later slug ownership check or listed in `variant_matches`; a false
    # duplicate has no downstream recovery.
    query = "&".join(query_fields)
    # An anchor fragment is dropped; a routing fragment is the page and stays.
    # An emptied query drops its trailing "?" too.
    fragment = parts.fragment
    fragment = fragment if fragment[:1] in ROUTING_FRAGMENT else ""
    return urlunsplit((scheme, host, path, query, fragment))


#: Host labels that mark a mobile or AMP copy of a page (`en.m.wikipedia.org`).
VARIANT_HOST_LABELS = {"m", "mobile", "amp"}


def variant_key(url):
    """A looser key that also folds the scheme, a mobile or AMP copy and an
    arXiv version, so a copy saved under one of them can be found.

    It never decides a verdict: `check()` only lists its matches in
    `variant_matches`, for a reader to compare. Query and routing fragment stay
    as `normalize_url` leaves them.
    """
    norm = normalize_url(url)
    if not norm:
        return ""
    parts = urlsplit(norm)
    userinfo, separator, authority = parts.netloc.rpartition("@")
    host, colon, port = (authority.partition(":")
                         if not authority.startswith("[") else (authority, "", ""))
    labels = host.split(".")
    if not all(label.isdigit() for label in labels):
        # Keep the last two labels: `m.com` is a site, not a mobile copy.
        labels = [label for i, label in enumerate(labels)
                  if i >= len(labels) - 2 or label not in VARIANT_HOST_LABELS]
    host = ".".join(labels)
    path = re.sub(r"/amp$", "", parts.path)
    if host == "arxiv.org":
        path = re.sub(r"^(/(?:abs|pdf)/.+?)v[0-9]+(\.pdf)?$", r"\1\2", path)
    netloc = userinfo + separator + host + colon + port
    return urlunsplit(("https", netloc, path, parts.query, parts.fragment))


def _frontmatter_fence(line):
    """True for a column-zero YAML fence, allowing only trailing whitespace.

    YAML block-scalar content is indented.  Treating ``line.strip() == "---"``
    as a closing fence therefore lets an ordinary ``|`` value end frontmatter
    early, before a later current or duplicate ``sources:`` key is seen.
    """
    return line.rstrip(" \t") == "---"


def split_frontmatter(text):
    """(frontmatter_lines, body) for a closed leading YAML block, else None.

    Leading blank lines are skipped before the opening fence. Fences are
    tested on ``yaml_lines()`` lines, which break only at CR, LF and CRLF as
    the shared origin reader's do, and ``body`` is the exact text suffix
    after the closing fence, so callers can recover the prefix by length.
    """
    bare = yaml_lines(text)
    opening = next((i for i, line in enumerate(bare) if line.strip()), None)
    if opening is None or not _frontmatter_fence(bare[opening]):
        return None
    for i in range(opening + 1, len(bare)):
        if _frontmatter_fence(bare[i]):
            # Both yaml_lines forms yield the same items, so `i` lines up.
            return (bare[opening + 1:i],
                    "".join(yaml_lines(text, keepends=True)[i + 1:]))
    return None


#: wiki-add's research guide (skills/wiki-add/references/research.md, "Legacy
#: research extracts") owns this marker. A legacy wiki-add research extract
#: carries it on the first body line after its frontmatter; wiki-add cites web
#: pages directly and creates none. A marked note is a legacy extract that
#: stays valid: it remains in the URL index as a URL and name owner, but
#: clipping-clean never overwrites, reprocesses or renames it.
RESEARCH_EXTRACT_MARKER = "<!-- obsidian:wiki-add-research-source -->"


#: The strict nonblocking UTF-8 reader shared with every Articles/ reader.
_read_regular_text = read_regular_text


def is_research_extract_text(text):
    """Whether the body after a closed leading frontmatter opens with the marker."""
    split = split_frontmatter(text)
    if split is None:
        return False
    first = next((line.strip() for line in split[1].splitlines() if line.strip()), "")
    return first == RESEARCH_EXTRACT_MARKER


def is_research_extract(path):
    """Whether a readable regular note is a legacy wiki-add research extract.

    wiki-add creates none.
    """
    text = _read_regular_text(path)
    return text is not None and is_research_extract_text(text)


#: A note's origin: `sources:` item 1, else a legacy scalar `source:`.
#: paper-summarize reads the same Articles/ notes through the same shared
#: function, so the two skills cannot disagree about which notes they own.
#: Its tolerances (BOM, CRLF, leading blank lines) keep an editor round-trip
#: from hiding a note from every duplicate check; its refusals (unterminated
#: fence, invalid UTF-8, ambiguous keys) keep a note from being indexed under
#: a URL its prose happens to contain. An unreadable note is reported as
#: `unindexable`, which is recoverable; a note indexed under the wrong URL
#: misses its own duplicate check and answers somebody else's.
read_source = read_note_origin


def _md_files(folder):
    def failed(exc):
        raise ValueError("cannot complete Markdown scan of %r: %s" %
                         (exc.filename or folder, exc)) from exc

    out = []
    ancestors = {os.path.normpath(folder): frozenset()}
    for root, dirs, files in os.walk(folder, onerror=failed, followlinks=True):
        try:
            info = os.stat(root)
        except OSError as exc:
            failed(exc)
        identity = (info.st_dev, info.st_ino)
        lineage = ancestors.pop(os.path.normpath(root))
        if identity in lineage:
            raise ValueError("cannot complete Markdown scan of %r: "
                             "directory symlink cycle" % root)
        # Track ancestors, not every visited directory: separate logical aliases
        # must remain visible, while a link back into its own ancestry cannot
        # yield a complete inventory. Dot-prefixed folders hold private
        # publication stages and hidden content Obsidian does not show; they
        # are neither owners nor captures. An explicitly passed root is still
        # scanned.
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in dirs:
            ancestors[os.path.normpath(os.path.join(root, name))] = (
                lineage | {identity})
        for f in sorted(files):
            if f.lower().endswith(".md"):
                out.append(os.path.join(root, f))
    return sorted(out)


def _validated_exclusions(cleaned_dir, exclude):
    """Resolve explicit reprocessing exclusions to unique direct note paths.

    A typo must never make a duplicate check look clean. Exclusions therefore
    have to identify one existing, regular direct child of the Articles folder
    under the plugin's portable filename identity. A legacy wiki-add research
    extract is never excluded: it stays a visible URL and name owner.
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
        if is_research_extract(candidate):
            raise ValueError("--exclude %r is a wiki-add research extract; "
                             "clipping-clean never reprocesses or overwrites "
                             "it" % requested)
        resolved.append(os.path.abspath(candidate))
    return resolved


def build_index(cleaned_dir, exclude=()):
    """Scan Articles/ once. Returns (index, unindexable, non_url).

    index       {normalized_url: [note paths]}   — normally one path per URL
    unindexable [paths]  notes with a missing/unparseable `sources:`; these are
                invisible to every duplicate check, so report the count
    non_url     [{path, source}]  notes whose origin is a wikilink to a local
                document rather than a URL — parseable, but deliberately not
                part of the URL index.  These are paper-summarize's summary
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
        # A Markdown-named symlink occupies the flat Articles namespace, but it
        # is not an Articles note and must not let a target elsewhere claim a
        # clipping URL. Keep this at the ownership-index boundary: a selected
        # read-only raw capture may legitimately be reached through an alias.
        try:
            if not stat.S_ISREG(os.lstat(path).st_mode):
                unindexable.append(path)
                continue
        except OSError:
            unindexable.append(path)
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


#: A rendered Obsidian embed; an escaped `\![[` is literal text.
_EMBED = re.compile(r"(?<!\\)!\[\[([^\]\r\n]+)\]\]")


def _foreign_figure_embeds(text, stem):
    """Filename-only `…_fig…` file embeds in ``text`` not under ``stem``."""
    own = _portable_name(stem) + "_fig"
    found = []
    for match in _EMBED.finditer(text):
        target = match.group(1).split("|", 1)[0].split("#", 1)[0].strip()
        if ("/" in target or "\\" in target
                or os.path.splitext(target)[1].lower() in ("", ".md")):
            continue
        key = _portable_name(target)
        if "_fig" in key and not key.startswith(own):
            found.append(target)
    return found


def _embed_stem(name):
    """The text before an embed's last `_fig`, else its whole stem."""
    match = re.match(r"(?is)(.*)_fig", name)
    return match.group(1) if match else os.path.splitext(name)[0]


def stem_mismatches(paths):
    """Notes whose `![[…_fig…]]` embeds use another source stem.

    A clipping files its images under its own note stem (CONVENTIONS §8), so
    a note renamed without its images is invisible to every stem-based figure
    inventory. Each row names the note, its other-stem embeds and their
    stems; references/duplicates-and-reprocessing.md says how to re-stem them
    on request. Code, comments and path-qualified targets do not count.
    """
    rows = []
    for path in sorted(set(paths)):
        text = _read_regular_text(path)
        split = split_frontmatter(text) if text is not None else None
        if split is None:
            continue
        stem = os.path.splitext(os.path.basename(path))[0]
        # The raw body is a cheap prefilter; the lexer runs only on a hit.
        if not _foreign_figure_embeds(split[1], stem):
            continue
        embeds = sorted(set(_foreign_figure_embeds(
            mask_body_comments(split[1], mask_code=True), stem)))
        if embeds:
            rows.append({"path": path, "embeds": embeds,
                         "stems": sorted({_embed_stem(name) for name in embeds})})
    return rows


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
    # Preserve separators and syntax guards: these stems become Markdown,
    # wikilink, URL-style, and HTML attachment targets as well as filenames.
    invalid = [ch for ch in slug
               if ord(ch) < 0x20 or ord(ch) == 0x7f
               or ch in '<>:"/\\|?*'] if isinstance(slug, str) else []
    if not isinstance(slug, str) or not slug or invalid or ".." in slug \
            or slug.startswith((".", " ")) \
            or os.path.basename(slug) != slug \
            or "/" in slug or "\\" in slug or slug.casefold().endswith(".md"):
        raise ValueError("--slug takes a non-empty filename stem, without a path "
                         "or .md extension, using path- and Markdown-safe characters: "
                         "%r" % slug)
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

    `variant_matches` lists the notes and earlier inputs whose URL has this
    row's `variant_key` under another normalized key. The status ignores them.
    """
    live = {k: list(v) for k, v in index.items()}
    variants = {}
    for norm, paths in index.items():
        variants.setdefault(variant_key(norm), []).extend(
            (norm, path) for path in paths)
    seen_this_run = {}
    results = []
    for ent in entries:
        src = ent.get("source")
        norm = normalize_url(src)
        if not norm:
            results.append({**ent, "normalized": None, "status": "no-source",
                            "matches": [], "variant_matches": []})
            continue
        matches = live.get(norm, [])
        if matches:
            status = ("duplicate-of-earlier-input" if norm in seen_this_run
                      else "duplicate")
        else:
            status = "new"
            live.setdefault(norm, [])
        key = variant_key(norm)
        results.append({**ent, "normalized": norm, "status": status,
                        "matches": list(matches),
                        "variant_matches": [path for other, path
                                            in variants.get(key, ())
                                            if other != norm]})
        if status == "new":
            seen_this_run[norm] = ent.get("id")
            live[norm].append(ent.get("id") or "<pending write>")
            variants.setdefault(key, []).append(
                (norm, ent.get("id") or "<pending write>"))
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
    case("only the host is lowercased when user information is present",
         normalize_url("https://User:SeCrEt@WWW.Example.COM/a"),
         "https://User:SeCrEt@example.com/a")
    differ("case-sensitive URL credentials do not collapse onto one origin",
           "https://User:SeCrEt@example.com/a",
           "https://User:secret@example.com/a")
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
                "https://example.com:not-a-port/article",
                "https://example.com:/article", "https://example.com:0/article",
                "https://bad host/x", "https://example.com/a\nsmuggled",
                "https://example.com/a\tsmuggled", "file:///article.md",
                "not a URL"):
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
    same("a custom-domain Substack post drops its referral and redirect flags",
         "https://www.noahpinion.blog/p/x?r=a&utm_medium=ios&triedRedirect=true",
         "https://noahpinion.blog/p/x")
    differ("?r= off a Substack post path still distinguishes pages",
           "https://example.com/docs?r=main", "https://example.com/docs?r=dev")
    same("www normalization does not disable X sharing-parameter cleanup",
         "https://www.x.com/example/status/1?s=20",
         "https://x.com/example/status/1")
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

    # --- variant_key: copies saved under a URL variant are listed ----------
    # A citation drops a mobile host, an AMP copy and an arXiv version, and a
    # clipping keeps whatever URL it captured. The verdict stays exact; the
    # looser key only lists the copies a reader must compare.
    for label, url, want in (
            ("a mobile host label is folded",
             "http://en.m.wikipedia.org/wiki/X?utm_source=y",
             "https://en.wikipedia.org/wiki/X"),
            ("an AMP host and a trailing /amp segment are folded",
             "https://amp.example.com/a/amp", "https://example.com/a"),
            ("an arXiv version is folded",
             "https://arxiv.org/abs/2305.18290v3", "https://arxiv.org/abs/2305.18290"),
            ("an old-style arXiv PDF version is folded",
             "https://arxiv.org/pdf/hep-th/9901001v2.pdf",
             "https://arxiv.org/pdf/hep-th/9901001.pdf"),
            ("a site named m keeps its host", "https://m.com/a", "https://m.com/a"),
            ("the query is kept", "https://m.example.com/a?id=1",
             "https://example.com/a?id=1")):
        case("variant_key: %s" % label, variant_key(url), want)
    variant_index = {normalize_url(url): [path] for url, path in (
        ("https://en.m.wikipedia.org/wiki/X", "Mobile.md"),
        ("https://arxiv.org/abs/2305.18290v3", "Versioned.md"),
        ("https://m.example.com/q?id=1", "Query.md"),
        ("https://m.com/a", "Site.md"),
        ("https://example.com/same", "Same.md"))}
    variant_rows = check([
        {"id": "Inbox/raw.md", "source": "http://example.com/raw"},
        {"id": "wiki", "source": "https://en.wikipedia.org/wiki/X"},
        {"id": "https-raw", "source": "https://example.com/raw"},
        {"id": "arxiv", "source": "https://arxiv.org/abs/2305.18290"},
        {"id": "query", "source": "https://example.com/q?id=2"},
        {"id": "com", "source": "https://com/a"},
        {"id": "same", "source": "https://example.com/same"},
        {"id": "none", "source": None}], variant_index)
    case("variant matches list mobile, scheme and arXiv copies; status stays exact",
         [(row["status"], row["variant_matches"]) for row in variant_rows],
         [("new", []), ("new", ["Mobile.md"]), ("new", ["Inbox/raw.md"]),
          ("new", ["Versioned.md"]), ("new", []), ("new", []),
          ("duplicate", []), ("no-source", [])])

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
                ("quoted current key beats stale legacy origin",
                 '---\n"sources": ["%s"]\nsource: https://stale.invalid/\n---\n'
                 % URL, URL),
                ("escaped current key beats stale legacy origin",
                 '---\n"sour\\u0063es": ["%s"]\nsource: https://stale.invalid/\n---\n'
                 % URL, URL),
                ("quoted and bare duplicate current keys are ambiguous",
                 '---\n"sources": ["%s"]\nsources: ["https://wrong.invalid/"]\n---\n'
                 % URL, None),
                ("malformed later member cannot establish ownership",
                 '---\nsources:\n  - "%s"\n  - [nested]\n---\n' % URL, None),
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
                ("an indented block-scalar rule is not the closing fence",
                 '---\nsource: "https://stale.example/legacy"\nnotes: |\n'
                 '  ---\nsources:\n  - "%s"\n---\n' % URL, URL),
                ("duplicate sources keys are ambiguous",
                 '---\nsources:\n  - "%s"\nsources:\n'
                 '  - "https://other.example/b"\n---\n' % URL, None),
                ("an indented rule cannot hide a duplicate current origin",
                 '---\nsources:\n  - "%s"\nnotes: |\n  ---\nsources:\n'
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
        if hasattr(os, "mkfifo"):
            fifo = os.path.join(tmp, "capture-fifo.md")
            os.mkfifo(fifo)
            case("a Markdown-named FIFO cannot block a source read",
                 read_source(fifo), None)
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
        # paper-summarize's shape: a summary note keyed to a PDF basename. It
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
        linked_url = "https://outside.example/article"
        link_target = article(
            "link-target.txt", "---\nsources:\n  - %s\n---\n" % linked_url)
        os.symlink(os.path.join(tmp, "missing-target"),
                   os.path.join(vault, "Broken.md"))
        os.symlink(link_target, os.path.join(vault, "Linked.md"))
        name_index = article_name_index(vault)
        slug_results = check_slugs(
            ["Held", "Broken", "Linked", "a", "Free"], name_index)
        case("slug checks include directories, broken links, links and case aliases",
             [(row["slug"], row["status"]) for row in slug_results],
             [("Held", "occupied"), ("Broken", "occupied"),
              ("Linked", "occupied"), ("a", "occupied"),
              ("Free", "free")])
        linked_index, linked_unindexable, _ = build_index(vault)
        case("a Markdown symlink occupies the slug but cannot claim its target URL",
             (normalize_url(linked_url) in linked_index,
              os.path.join(vault, "Linked.md") in linked_unindexable),
             (False, True))
        with patch.object(os, "listdir", return_value=[
                    "Caf\u00e9.md", "Cafe\u0301.MD", "ignored.txt"]):
            ambiguous_index = article_name_index(vault)
        case("NFC/case-equivalent direct names are ambiguous",
             check_slugs(["CAF\u00c9"], ambiguous_index)[0]["status"],
             "ambiguous")
        case("an ambiguous slug reports every occupying spelling",
             len(check_slugs(["caf\u00e9"], ambiguous_index)[0]["matches"]), 2)
        for invalid_slug in ("", "\0", ".", "..", "path/name", "path\\name",
                             "x.md", "bad:name", "bad?name", "two..dots",
                             "line\nbreak", 7):
            try:
                check_slugs([invalid_slug], name_index)
            except ValueError:
                rejected = True
            else:
                rejected = False
            case("invalid slug is rejected: %r" % invalid_slug, rejected, True)

        for ordinary_slug in ("CON", "COM1", "AUX.extra", "trail.", "trail "):
            case("ordinary macOS/Linux stem is accepted: %r" % ordinary_slug,
                 _slug_filename(ordinary_slug), ordinary_slug + ".md")

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
        with open(os.path.join(hidden, "Reviewed.md"), "w",
                  encoding="utf-8") as fh:
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

        # A synchronized folder can be linked into Inbox or a legacy nested
        # Articles tree. Its Markdown must not disappear from a successful scan.
        linked_target = os.path.join(tmp, "linked-captures")
        linked_raw = os.path.join(tmp, "linked-inbox")
        linked_articles = os.path.join(tmp, "linked-articles")
        for folder in (linked_target, linked_raw, linked_articles):
            os.makedirs(folder)
        note(os.path.join("linked-captures", "Captured.md"),
             "---\nsource: %s\n---\n" % URL)
        raw_alias = os.path.join(linked_raw, "synced")
        owner_alias = os.path.join(linked_articles, "legacy")
        os.symlink(linked_target, raw_alias, target_is_directory=True)
        os.symlink(linked_target, owner_alias, target_is_directory=True)
        empty_articles = os.path.join(tmp, "empty-articles")

        def scan(argv):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(argv)
            return code, json.loads(output.getvalue())

        code, result = scan([empty_articles, "--raw", linked_raw])
        case("a linked inbox folder contributes its capture to the public scan",
             (code, [(row["id"], row["status"]) for row in result.get("checked", [])]),
             (0, [(os.path.join(raw_alias, "Captured.md"), "new")]))
        code, result = scan([linked_articles, "--url", URL])
        case("a linked Articles folder cannot hide an existing URL owner",
             (code, [(row["status"], row["matches"]) for row in result.get("checked", [])]),
             (0, [("duplicate", [os.path.join(owner_alias, "Captured.md")])]))
        second_alias = os.path.join(linked_raw, "synced-again")
        os.symlink(linked_target, second_alias, target_is_directory=True)
        code, result = scan([empty_articles, "--raw", linked_raw])
        case("noncyclic sibling aliases remain visible and deduplicate normally",
             (code, [(row["id"], row["status"]) for row in result.get("checked", [])]),
             (0, [(os.path.join(second_alias, "Captured.md"), "new"),
                  (os.path.join(raw_alias, "Captured.md"), "duplicate-of-earlier-input")]))

        linked_scandir = os.scandir

        def linked_denied(path):
            if path in (raw_alias, second_alias, owner_alias):
                raise PermissionError(13, "permission denied", path)
            return linked_scandir(path)

        for label, argv in (
                ("unreadable linked captures make the raw inventory incomplete",
                 [empty_articles, "--raw", linked_raw]),
                ("unreadable linked owners make the URL index incomplete",
                 [linked_articles, "--url", URL])):
            with patch.object(os, "scandir", side_effect=linked_denied):
                code, result = scan(argv)
            case(label, (code, bool(result.get("error")), "checked" in result),
                 (1, True, False))

        os.symlink(linked_target, os.path.join(linked_target, "loop"),
                   target_is_directory=True)
        for label, argv in (
                ("a linked raw cycle cannot publish a partial capture inventory",
                 [empty_articles, "--raw", linked_raw]),
                ("a linked Articles cycle cannot publish a partial ownership index",
                 [linked_articles, "--url", URL])):
            code, result = scan(argv)
            case(label, (code, "cycle" in result.get("error", ""), "checked" in result),
                 (1, True, False))

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main([vault, "--slug", "Held", "--slug", "Free"])
        public_slugs = json.loads(output.getvalue()).get("slug_checks", [])
        case("the public CLI returns repeatable slug checks",
             (code, [(row["slug"], row["status"]) for row in public_slugs]),
             (0, [("Held", "occupied"), ("Free", "free")]))

        # A legacy wiki-add research extract remains a URL owner. The scan
        # names it so the workflow reports it rather than offering a clipping
        # overwrite.
        extract_url = "https://example.com/researched"
        extract = article("Researched.md",
                          '---\nsources:\n  - "%s"\n---\n%s\nResearch extract\n'
                          % (extract_url, RESEARCH_EXTRACT_MARKER))
        plain_url = "https://example.com/plain"
        plain = article("Plain_Capture.md",
                        '---\nsources:\n  - "%s"\n---\nProse, then %s\n'
                        % (plain_url, RESEARCH_EXTRACT_MARKER))
        code, result = scan([vault, "--url", extract_url, "--url", plain_url])
        case("the scan flags a matching research extract without reshaping matches",
             (code, [(row["status"], row["matches"], row["research_extracts"])
                     for row in result.get("checked", [])]),
             (0, [("duplicate", [extract], [extract]),
                  ("duplicate", [plain], [])]))
        refused, refusal = scan([vault, "--url", extract_url, "--slug",
                                 "Researched", "--exclude", extract])
        code, result = scan([vault, "--url", extract_url, "--slug", "Researched"])
        case("an exclusion cannot hide a research extract or free its slug",
             (refused, "research extract" in refusal.get("error", ""),
              "checked" in refusal, code,
              [(row["status"], row["research_extracts"])
               for row in result.get("checked", [])],
              [row["status"] for row in result.get("slug_checks", [])]),
             (1, True, False, 0, [("duplicate", [extract])], ["occupied"]))
        case("only the first body line after closed frontmatter is the marker",
             (is_research_extract_text(
                 "---\ntitle: x\n---\n\n%s\n" % RESEARCH_EXTRACT_MARKER),
              is_research_extract_text(RESEARCH_EXTRACT_MARKER + "\n"),
              is_research_extract_text(
                  "---\ntitle: x\n%s\n" % RESEARCH_EXTRACT_MARKER)),
             (True, False, False))
        crlf_note = "\r\n---\r\nsources:\r\n  - %s\r\n---\r\nBody\r\n" % URL
        crlf_split = split_frontmatter(crlf_note)
        case("split_frontmatter returns bare frontmatter lines and the exact body suffix",
             (crlf_split, crlf_note.endswith(crlf_split[1] if crlf_split else "\0")),
             ((["sources:", "  - %s" % URL], "Body\r\n"), True))
        case("split_frontmatter refuses an unterminated block",
             split_frontmatter("---\nsources:\n  - %s\nBody\n" % URL), None)
        # U+2028, U+2029 and NEL are YAML content, not line breaks. Splitting
        # at them cut a quoted title in two and hid the note's origin.
        sep_note = ('---\ntitle: "Old title"\nsources:\n  - "%s"\n---\n'
                    'Body line\x85\n' % URL)
        case("split_frontmatter keeps U+2028, U+2029 and NEL inside their lines",
             split_frontmatter(sep_note),
             (['title: "Old title"', "sources:", '  - "%s"' % URL],
              "Body line\x85\n"))
        for folder in ("sep-inbox", "sep-articles"):
            os.makedirs(os.path.join(tmp, folder))
        note(os.path.join("sep-inbox", "raw.md"),
             '---\ntitle: "Why X matters"\n'
             'source: "https://example.com/post"\n---\n')
        note(os.path.join("sep-articles", "Doe_X_2026.md"),
             '---\ntitle: "Old title"\n'
             'sources: ["https://example.com/owned"]\n---\n')
        code, result = scan([os.path.join(tmp, "sep-articles"),
                             "--raw", os.path.join(tmp, "sep-inbox"),
                             "--url", "https://example.com/owned"])
        case("a U+2028 title keeps a capture's source: the capture is new",
             (code, [(row["status"], row["source"])
                     for row in result.get("checked", [])][:1]),
             (0, [("new", "https://example.com/post")]))
        case("...and a note with a U+2029 title stays indexed as a duplicate",
             (result.get("unindexable"),
              [row["status"] for row in result.get("checked", [])][1:]),
             ([], ["duplicate"]))
        code, result = scan([vault, "--raw", os.path.join(tmp, "Inbx")])
        case("a mistyped --raw path is an error, not a silent no-source row",
             (code, "does not exist" in result.get("error", ""),
              "checked" in result), (1, True, False))

        # Dot-prefixed folders are private stages or hidden content: a staged
        # copy inside Articles/ is not a second owner, and a hidden Inbox
        # subfolder is not a capture.
        os.makedirs(os.path.join(vault, ".organize-stage-x"))
        article(os.path.join(".organize-stage-x", "Researched.md"),
                '---\nsources:\n  - "%s"\n---\nstaged copy\n' % extract_url)
        code, result = scan([vault, "--url", extract_url])
        case("a private stage inside Articles is not a second URL owner",
             (code, [row["matches"] for row in result.get("checked", [])],
              normalize_url(extract_url) in result.get("collisions", {})),
             (0, [[extract]], False))
        os.makedirs(os.path.join(tmp, "hidden-inbox", ".hidden"))
        note(os.path.join("hidden-inbox", ".hidden", "Raw.md"),
             "---\nsource: https://example.com/hidden\n---\n")
        visible_raw = note(os.path.join("hidden-inbox", "Visible.md"),
                           "---\nsource: https://example.com/visible\n---\n")
        case("a hidden Inbox subfolder is not scanned for captures",
             _md_files(os.path.join(tmp, "hidden-inbox")), [visible_raw])

        # A note renamed without its images keeps embedding the old stem.
        # Only rendered filename-only embeds of another stem are reported.
        renamed = article(
            "Doe_I_Test_2026.md",
            '---\nsources:\n  - "https://example.com/renamed"\n---\n'
            "![[Doe_Test_2026_fig_1.png]]\n![[Doe_I_Test_2026_fig_2.png|300]]\n"
            "`![[Code_Only_2020_fig_1.png]]`\n```\n![[Fenced_2020_fig_1.png]]\n```\n"
            "<!-- ![[Commented_2020_fig_1.png]] -->\n"
            "![[Sources/Images/Pathed_2020_fig_1.png]]\n![[Doe_Test_2026_fig_3.png]]\n")
        own_stem = article("Fig_Facts_2025.md",
                           '---\nsources:\n  - "https://example.com/figfacts"\n---\n'
                           "![[fig_facts_2025_FIG_1.png]]\n")
        article("Paper_Summary_2025.md",
                '---\nsources:\n  - "[[Paper_Summary_2025_src.pdf]]"\n---\n'
                "![[Paper_Summary_2025_src_fig_1.png]]\n")
        case("stem_mismatches lists only rendered other-stem figure embeds",
             stem_mismatches([renamed, own_stem]),
             [{"path": renamed,
               "embeds": ["Doe_Test_2026_fig_1.png", "Doe_Test_2026_fig_3.png"],
               "stems": ["Doe_Test_2026"]}])
        code, result = scan([vault, "--url", URL])
        case("the scan reports stem mismatches for URL-owning notes only",
             (code, [row["path"] for row in result.get("stem_mismatch", [])]),
             (0, [renamed]))

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
    ap.add_argument("cleaned_dir", nargs="?",
                    help="Articles/ directory to index")
    ap.add_argument("--raw", action="append", default=[],
                    help="raw .md file or folder of them; repeatable")
    ap.add_argument("--url", action="append", default=[],
                    help="bare URL to check; repeatable")
    ap.add_argument("--slug", action="append", default=[],
                    help="proposed clipping-note stem to check; repeatable")
    ap.add_argument("--exclude", action="append", default=[],
                    help="note to leave out of the index (reprocessing a Articles/ file)")
    ap.add_argument("--dump-index", action="store_true",
                    help="include normalized URL ownership in the report")
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
    # Only a published Articles owner can be a legacy research extract; a
    # pending earlier input in this batch cannot.
    owners = {path for paths in index.values() for path in paths}
    for r in results:
        r["research_extracts"] = [path for path in r["matches"]
                                  if path in owners and is_research_extract(path)]
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
        "stem_mismatch": stem_mismatches(
            path for paths in index.values() for path in paths),
    }
    if args.dump_index:
        out["index"] = index
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
