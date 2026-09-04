#!/usr/bin/env python3
"""Stage/place a clipping's images, or rename owned images on a reprocess.

This is the mechanical image transport and publication path, done the same way
every time: a browser
User-Agent on every request (CDNs 403 a default urllib/curl agent), a temp file
OUTSIDE Sources/Images with no image extension, the real type detected from the
bytes rather than trusted from the URL, and a move — not a copy — into
<Sources/Images>/<slug>_fig_<N>.<ext>. Doing it by hand is what produces the
broken extension-twin (a .png written from a URL guess sitting next to the
.webp the MIME check produced).

What stays with you: deciding which images are figures, finding and normalizing
captions, rewriting the body's references to `![[…]]` embeds, and inserting a
`<!-- image download failed: [redacted source locator] -->` placeholder for
anything reported failed here. Use the helper's redacted ``url`` field rather
than copying a signed query string or inline payload from the source. Those
rules are in references/images.md.

CLI
    python3 fetch_images.py stage --vault '<vault>' --out-dir '<scratch>/images' \\
        --slug Teslo_Pancreatic_Cancer_2026 [--start 1] URL [URL ...]
    python3 fetch_images.py download --attachments '<vault>/Sources/Images' \\
        --owner-note '<vault>/Articles/Teslo_Pancreatic_Cancer_2026.md' \\
        --slug Teslo_Pancreatic_Cancer_2026 [--start 1] URL [URL ...]
    python3 fetch_images.py download ... --urls-file list.txt     # one URL per line, - for stdin
    python3 fetch_images.py fetch '<lottie source url>' \\
        [--out '<path>' --vault '<vault>']
    python3 fetch_images.py place --attachments '<vault>/Sources/Images' \\
        --owner-note '<vault>/Articles/Teslo_Pancreatic_Cancer_2026.md' \\
        --slug Teslo_Pancreatic_Cancer_2026 --index 3 --from-file '<rendered file>'
    python3 fetch_images.py rename --phase prepare [--dry-run] \\
        --attachments '<vault>/Sources/Images' --sources '<vault>/Sources/PDFs' \\
        --owner-note '<vault>/Articles/Old_Slug_2025.md' \\
        --old-slug Old_Slug_2025 --new-slug New_Slug_2026 \\
        --new-owner-note '<vault>/Articles/New_Slug_2026.md'
    python3 fetch_images.py rename --phase finalize [--dry-run] \\
        --attachments '<vault>/Sources/Images' --sources '<vault>/Sources/PDFs' \\
        --owner-note '<vault>/Articles/Old_Slug_2025.md' \\
        --old-slug Old_Slug_2025 --new-slug New_Slug_2026 \\
        --new-owner-note '<vault>/Articles/New_Slug_2026.md'
    python3 fetch_images.py dependencies --attachments '<vault>/Sources/Images' \\
        --owner-note '<vault>/Articles/Old_Slug_2025.md' \\
        --old-slug Old_Slug_2025
    python3 fetch_images.py preflight --vault '<vault>' --slug Proposed_Slug_2026
    python3 fetch_images.py selftest        # the built-in cases; offline

`fetch` and `place` are the two halves of a figure this skill does not download
as an image: a Lottie animation, which arrives as JSON and has to be
rendered to a GIF by something else first. `fetch` brings the source down under
the transport guards below, to a path OUTSIDE the vault; you render; `place`
moves the result in under the write guards below. Neither the fetch nor the
final write is left to the rendering step, because a script that does its own
`urlopen` and its own `os.replace` into Sources/Images has none of this.

`rename` requires an explicit phase. A clipping reprocess uses `prepare` to
publish verified new-name copies while retaining the old names, then `finalize`
only after the reported dependencies have been rewritten and an unchanged
re-probe passes. The explicit `immediate` phase remains for compatibility with
older callers whose set has no dependencies; it is deprecated for the clipping
reprocess workflow and never substitutes for the two-owner handoff.

`rename`'s required `--sources` is the vault's `Sources/PDFs`: a `<old_slug>.pdf`
found anywhere beneath (the folder is recursive — book chapters live in
`Sources/PDFs/<Work>/`) proves the figures under that stem are that document's,
and the whole rename is refused. PDF manifest ownership is checked regardless
of this inventory. Label spelling alone cannot distinguish a PDF's plain-numbered
figures from a clipping's, so a rename never runs without the inventory.

URLs are processed in the order given, which must be the body's source order:
the figure counter is shared and sequential. `--start` continues the counter
when the note already has embeds (a recovered figure from the step-12 audit
takes the next free number, not a number matching its position).

Guards, because this is the only script in the skill that writes into the vault:

* **Slugs are validated, paths are contained.** A slug holding `/`, `\\`, `..`,
  or nothing at all is rejected, and every final path is checked to be under
  the Sources/Images folder before anything is moved or renamed. `--slug` is free
  text from the model, not necessarily what `slug.py` returned.
* **Neither `download` nor a rename phase clobbers.** `prepare` exclusively
  publishes byte-identical new-name copies and retains every old name;
  `finalize` conditionally retires only its verified old duplicates. The legacy
  `immediate` phase moves only a dependency-free set and is all-or-nothing. An
  unexpected destination is an error (`--dry-run` reports it too). A case-only
  immediate rename of the same file (`teslo_…` → `Teslo_…`) is still allowed
  when identity checks confirm it. Publication, retirement and every rollback
  are conditional, so a path claimed after the plan is preserved and any mixed
  state is reported for inspection.
  `download` refuses an occupied `<slug>_fig_<N>.*` slot the same way —
  `shutil.move` replaces silently, so a re-run with the wrong `--start`
  destroyed figures with no way back. Pass `--overwrite` for the documented
  reprocess-in-place case, together with `--owner-note` naming the unchanged
  clipping note whose rendered embed exactly names the file being replaced.
* **A changed clipping stem has no hidden dependants.** For a canonical vault,
  `rename` inventories every other Markdown note for inbound old-note links and
  old-image references before and during the operation. `prepare` reports those
  dependencies while keeping both names resolvable; an incomplete scan still
  blocks it. `finalize` and legacy `immediate` refuse any dependency or
  incomplete scan with exact blocker paths. `dependencies` repeats that
  complete check before the old Articles path is retired.
* **Only `http`, `https` and `data:`** — generic URL clients also speak `file:`
  and `ftp:`, and clipped markdown legitimately carries `file://` image links.
  Each HTTP(S) hop is resolved once, every answer is checked, and the actual
  socket is pinned to that vetted address while the logical hostname remains in
  Host and TLS SNI/certificate checks. Redirects repeat the process before any
  target body is read. Loopback, link-local and private ranges are refused
  unless `--allow-private-hosts`.
* **Direct connections only** — ambient proxy settings are not used. Letting a
  forward proxy resolve the logical hostname would recreate the DNS-rebinding
  gap after local validation. Run this helper where direct egress is available;
  `--allow-private-hosts` changes the address policy, not the proxy policy.
* **Bounded downloads** — `--max-bytes` (25 MB default) and `--max-seconds`
  (120 s default, wall-clock across the whole transfer, unlike the per-socket
  `--timeout`), so a huge or slow-dripping response can't fill the vault.
* **Non-images are failures, not `.png`s, and the BYTES decide that.** A
  JSON/text/PDF error body is reported failed — naming what the bytes looked
  like — so the model writes the documented
  `<!-- image download failed: [redacted source locator] -->` placeholder
  instead of embedding a file that Obsidian can't render. A `Content-Type` is
  only a hint: an
  `image/png` header on a JSON body does not make it an image, and used to.
  SVG is accepted only when the complete file is inert and self-contained;
  active elements, event handlers, XML DTDs, and external resources are
  refused before publication.

Importable
    sniff_extension(head, content_type=None, url=None) -> str | None
    describe_bytes(head) -> str                        # "a JSON body", "a PDF", …
    download_one(url, attachments, slug, index, owner_note=None) -> dict
    fetch_source(url, out=None) -> dict                # Lottie source, outside vault
    place_file(src, attachments, slug, index, owner_note=None) -> dict
    rename_slug(attachments, old_slug, new_slug, dry_run=False,
                *, sources=..., owner_note=...) -> list[dict]
    prepare_slug_rename(attachments, old_slug, new_slug, *, sources=...,
                        owner_note=..., new_owner_note=..., dry_run=False) -> dict
    finalize_slug_rename(attachments, old_slug, new_slug, *, sources=...,
                         owner_note=..., new_owner_note=..., dry_run=False) -> dict
    dependency_status(attachments, owner_note, old_slug) -> dict
    validate_slug(slug, what="--slug") -> str          # raises ValueError
    validate_index(index, what="figure index") -> int  # raises ValueError
    run_self_test() -> int                             # also `selftest`

Output: one JSON object on stdout. Exit 0 if every item succeeded, 1 if any
failed (the JSON lists which). Stdlib only.
"""

import argparse
import base64
import binascii
import contextlib
import errno
import fnmatch
import glob
import hashlib
import http.client
import io
import ipaddress
import json
import math
import os
import re
import shutil
import socket
import ssl
import stat
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import warnings
import xml.etree.ElementTree as ET
import zipfile

_OBSIDIAN_SHARED_MODULES = ("atomic_move", "figure_state", "slugify", "yaml_scalars")

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

from atomic_move import (LinkUnavailable, MoveIncomplete, PublicationConflict, file_identity,
                         link_noreplace, move_noreplace, remove_expected,
                         replace_expected, publish_new, set_private_mode)
from dedup_index import normalize_url, read_source
from figure_state import MANIFEST_FILE, read_manifest
from slugify import is_windows_device_stem


def _name_key(name):
    # Do not use casefold here. Expansions such as `ß` -> `ss` are one name on
    # the default macOS volume but two legitimate names on a case-sensitive
    # Linux volume. Filesystem identity below settles the expansion only where
    # the active filesystem itself treats the spellings as equivalent.
    return unicodedata.normalize("NFC", name).lower()


def _manifest_name_key(name):
    """Conservative identity for ownership records, including absent files."""
    return unicodedata.normalize("NFC", name).casefold()


def _same_directory_name(directory, actual_name, wanted_name):
    """Whether two spellings resolve to one directory entry on this filesystem."""
    if _name_key(actual_name) == _name_key(wanted_name):
        return True
    try:
        return os.path.samefile(os.path.join(directory, actual_name),
                                os.path.join(directory, wanted_name))
    except OSError:
        return False


def _inside_existing_directory(path, directory, *, require_all=False):
    """Whether an existing path is physically beneath an existing directory.

    Textual ``realpath`` prefixes are not filesystem identity. On a default
    APFS volume, two differently-cased spellings can name the same directory
    while ``realpath`` preserves the caller's spelling. The old place guard
    consequently accepted an attachment passed through the other spelling and
    later removed that live vault entry as its scratch source. Compare ancestor
    directory identities instead, considering both the logical entry path and
    a symlink-resolved source. Any unreadable identity fails closed.
    """
    try:
        wanted = os.stat(directory)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ValueError("cannot identify the attachments folder %r safely: %s" %
                         (directory, exc)) from exc
    if not stat.S_ISDIR(wanted.st_mode):
        raise ValueError("attachments path is not a directory: %r" % directory)
    wanted_id = (wanted.st_dev, wanted.st_ino)

    starts = [os.path.dirname(os.path.abspath(path))]
    resolved = os.path.dirname(os.path.realpath(path))
    if resolved not in starts:
        starts.append(resolved)
    results = []
    for start in starts:
        current = start
        seen = set()
        inside = False
        while True:
            try:
                item = os.stat(current)
            except OSError as exc:
                raise ValueError("cannot establish whether %r is inside %r: %s" %
                                 (path, directory, exc)) from exc
            identity = (item.st_dev, item.st_ino)
            if identity == wanted_id:
                inside = True
                break
            if identity in seen:
                raise ValueError("directory identity loop while checking whether %r "
                                 "is inside %r" % (path, directory))
            seen.add(identity)
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
        results.append(inside)
        if inside and not require_all:
            return True
    return all(results) if require_all else any(results)


def _figure_stem_end(attachments, filename, slug, tail_pattern):
    """End offset of ``slug`` in a matching figure basename, or None.

    The suffix supplies a real directory entry for ``samefile``. This lets a
    case-folding filesystem confirm an expansion such as Straße/STRASSE without
    imposing that expansion on case-sensitive filesystems.
    """
    pattern = _name_key(tail_pattern)
    for i, char in enumerate(filename):
        if char != "_":
            continue
        suffix = filename[i:]
        if not fnmatch.fnmatchcase(_name_key(suffix), pattern):
            continue
        if _same_directory_name(attachments, filename, slug + suffix):
            return i
    return None


def _glob_slug(attachments, slug, tail):
    """Match the flat folder using the vault's case/Unicode name identity.

    Python glob compares directory entries case-sensitively even on macOS.
    Scanning the literal directory also keeps brackets in a vault path from
    being interpreted as a glob expression.
    """
    try:
        with os.scandir(attachments) as entries:
            return sorted(entry.path for entry in entries
                          if _figure_stem_end(attachments, entry.name, slug, tail)
                          is not None)
    except FileNotFoundError:
        return []

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

ALLOWED_SCHEMES = {"http", "https", "data"}
DEFAULT_MAX_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_SECONDS = 120
MAX_REDIRECTS = 10
REDIRECT_STATUSES = frozenset((301, 302, 303, 307, 308))
CHUNK = 64 * 1024

# Ambient HTTP(S) proxies are deliberately not consulted. A forward proxy that
# receives the logical hostname can resolve it again after this process vets
# DNS, recreating the exact rebinding gap this transport closes. Supporting a
# proxy safely would require pinning the proxy connection *and* defining a
# protocol that makes the proxy connect to the vetted target address while the
# origin Host/SNI stay unchanged. The stdlib proxy path makes no such promise,
# so this helper is direct-only instead of silently weakening its address guard.
PROXY_POLICY = "direct-only"


def _report_url(url, limit=200):
    """Return a useful URL locator without echoing credentials or payloads.

    Image URLs commonly carry expiring signatures in their query strings, and
    a ``data:`` URL contains the image itself. The raw capture remains the
    recovery record, so JSON results and note placeholders need only enough
    information to identify which source failed. Fragments never reach the
    server and are omitted as well.
    """
    raw = str(url or "")
    try:
        parts = urllib.parse.urlsplit(raw)
    except (TypeError, ValueError):
        match = re.match(r"\A([A-Za-z][A-Za-z0-9+.-]*):", raw)
        value = ((match.group(1).lower() + ":") if match else "URL:") \
            + "<location omitted>"
        return value[:limit]

    scheme = parts.scheme.lower()
    if scheme == "data":
        metadata = raw[5:].split(",", 1)[0]
        metadata = "".join(
            char if 0x20 <= ord(char) < 0x7f else "?" for char in metadata)
        value = "data:" + metadata[:80] + ",<payload omitted>"
        return value[:limit]
    if scheme in ("http", "https") and parts.hostname:
        host = parts.hostname
        if ":" in host and not host.startswith("["):
            host = "[" + host + "]"
        try:
            explicit_port = parts.port
        except ValueError:
            explicit_port = None
        authority = host + ((":" + str(explicit_port))
                            if explicit_port is not None else "")
        path = parts.path or "/"
        path = "".join(char if ord(char) >= 0x20 and ord(char) != 0x7f else "?"
                       for char in path)
        query = "?<query omitted>" if "?" in raw.split("#", 1)[0] else ""
        value = scheme + "://" + authority + path + query
        return value[:limit] + ("…" if len(value) > limit else "")
    value = (scheme + ":" if scheme else "URL:") + "<location omitted>"
    return value[:limit]

#: Every canonical extension this producer can return. CONVENTIONS.md §8a
#: publishes the same set; the convention harness compares them and verifies
#: wiki-linter recognizes every one as an image embed.
OUTPUT_EXTENSIONS = frozenset((
    "png", "jpg", "gif", "webp", "svg", "avif", "bmp", "tiff", "ico",
))

#: Control characters that appear in ordinary text. Anything else below 0x20,
#: plus DEL, means the payload is binary and the text branch does not apply.
_TEXT_CTRL = {0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x1b}

#: Leading byte patterns that are definitely NOT an image, with the name to put
#: in the failure message. Consulted only once the magic-byte pass has found no
#: image, so nothing here can shadow a real format.
_NOT_IMAGE_MAGIC = (
    (b"%PDF-", "a PDF"),
    (b"%!PS", "a PostScript document"),
    (b"PK\x03\x04", "a ZIP archive (or a zipped Office/OpenDocument file)"),
    (b"PK\x05\x06", "an empty ZIP archive"),
    (b"PK\x07\x08", "a spanned ZIP archive"),
    (b"\x7fELF", "an ELF executable"),
    (b"MZ", "a DOS/Windows executable"),
    (b"\xca\xfe\xba\xbe", "a Java class or Mach-O fat binary"),
    (b"\xcf\xfa\xed\xfe", "a Mach-O binary"),
    (b"\xce\xfa\xed\xfe", "a 32-bit Mach-O binary"),
    (b"\x1f\x8b", "a gzip stream"),
    (b"BZh", "a bzip2 stream"),
    (b"\xfd7zXZ\x00", "an xz stream"),
    (b"\x28\xb5\x2f\xfd", "a zstd stream"),
    (b"Rar!\x1a\x07", "a RAR archive"),
    (b"7z\xbc\xaf\x27\x1c", "a 7-Zip archive"),
    (b"\xd0\xcf\x11\xe0", "a legacy Office document"),
    (b"SQLite format 3\x00", "a SQLite database"),
    (b"OggS", "an Ogg media stream"),
    (b"\x1aE\xdf\xa3", "a Matroska/WebM media stream"),
    (b"ID3", "an MP3 audio stream"),
    (b"fLaC", "a FLAC audio stream"),
    (b"\x00asm", "a WebAssembly module"),
)

#: An SVG root element, once the prolog has been stepped over.
_SVG_ROOT_RE = re.compile(r"<svg([\s>/]|$)", re.I)
_SVG_NAMESPACE = "http://www.w3.org/2000/svg"
_SVG_ACTIVE_ELEMENTS = frozenset((
    "animate", "animatecolor", "animatemotion", "animatetransform",
    "audio", "discard", "embed", "fencedframe", "foreignobject", "frame",
    "handler", "iframe", "img", "link", "listener", "meta", "object",
    "portal", "script", "set", "source", "track", "video",
))
_SVG_EXTERNAL_ATTRIBUTES = frozenset(("base", "href", "poster", "src"))
_SVG_CSS_VALUE_ATTRIBUTES = frozenset((
    "background", "background-image", "border-image", "border-image-source",
    "clip-path", "color-profile", "content", "cursor", "fill", "fill-image",
    "filter",
    "list-style", "list-style-image", "marker", "marker-end", "marker-mid",
    "marker-start", "mask", "mask-border", "mask-border-source", "mask-image",
    "offset", "offset-path", "shape-inside", "shape-outside",
    "shape-subtract", "stroke", "stroke-image", "style",
))
_SVG_CSS_RESOURCE_FUNCTIONS = (
    "-webkit-image-set", "image-set", "image", "attr", "src",
)


def _xml_name(name):
    """Return ``(namespace, local-name)`` for an ElementTree name."""
    if name.startswith("{") and "}" in name:
        namespace, local = name[1:].split("}", 1)
        return namespace, local
    return "", name


def _css_without_comments(css):
    """Remove CSS comments without treating comment markers in strings as syntax."""
    out = []
    index = 0
    quote = None
    while index < len(css):
        char = css[index]
        if quote is not None:
            out.append(char)
            if char == "\\" and index + 1 < len(css):
                index += 1
                out.append(css[index])
            elif char == quote:
                quote = None
            index += 1
            continue
        if char in ("'", '"'):
            quote = char
            out.append(char)
            index += 1
            continue
        if css.startswith("/*", index):
            end = css.find("*/", index + 2)
            if end < 0:
                return None
            index = end + 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _css_reference_issue(css):
    """Return a reason when CSS can load anything beyond a local fragment.

    This is deliberately a small deny parser, not a CSS sanitizer. Comments are
    removed before tokens are inspected, strings outside functions are skipped,
    and escapes in identifiers or ``url()`` arguments are refused because they
    can spell an external locator without leaving a literal ``url(http...)``.
    Resource-capable ``image()``, ``image-set()`` and ``src()`` functions, and
    typed ``attr()`` values that can become URLs, are refused conservatively;
    unlike ``url()``, their arguments are not reliably distinguishable from
    inert strings with this small parser. Empty and fragment-only URL functions
    remain self-contained.
    """
    css = _css_without_comments(str(css))
    if css is None:
        return "malformed CSS comments"
    index = 0
    while index < len(css):
        char = css[index]
        if char in ("'", '"'):
            quote = char
            index += 1
            while index < len(css):
                if css[index] == "\\":
                    index += 2
                    continue
                if css[index] == quote:
                    index += 1
                    break
                index += 1
            else:
                return "malformed CSS string"
            continue
        if char == "\\":
            return "an escaped CSS token"
        if css[index:index + 7].casefold() == "@import":
            return "a CSS import"
        if re.match(
                r"@(?:-[A-Za-z0-9_]+-)?keyframes\b", css[index:], re.I):
            return "a CSS animation"
        previous = index - 1
        while previous >= 0 and css[previous].isspace():
            previous -= 1
        if previous < 0 or css[previous] in ("{", ";"):
            active_property = re.match(
                r"(?:-[A-Za-z0-9_]+-)?(?:animation|transition)"
                r"(?:-[A-Za-z0-9_-]+)?\s*:", css[index:], re.I)
            if active_property:
                return "a CSS animation or transition"
        for function_name in _SVG_CSS_RESOURCE_FUNCTIONS:
            if css[index:index + len(function_name)].casefold() != function_name:
                continue
            if index and (css[index - 1].isalnum()
                          or css[index - 1] in ("_", "-")):
                continue
            cursor = index + len(function_name)
            while cursor < len(css) and css[cursor].isspace():
                cursor += 1
            if cursor < len(css) and css[cursor] == "(":
                return "a CSS resource function"
        if css[index:index + 3].casefold() != "url":
            index += 1
            continue
        cursor = index + 3
        while cursor < len(css) and css[cursor].isspace():
            cursor += 1
        if cursor >= len(css) or css[cursor] != "(":
            index += 3
            continue
        cursor += 1
        while cursor < len(css) and css[cursor].isspace():
            cursor += 1
        if cursor < len(css) and css[cursor] in ("'", '"'):
            quote = css[cursor]
            cursor += 1
            start = cursor
            while cursor < len(css) and css[cursor] != quote:
                if css[cursor] == "\\":
                    return "an escaped CSS URL"
                cursor += 1
            if cursor >= len(css):
                return "a malformed CSS URL"
            target = css[start:cursor].strip()
            cursor += 1
            while cursor < len(css) and css[cursor].isspace():
                cursor += 1
            if cursor >= len(css) or css[cursor] != ")":
                return "a malformed CSS URL"
        else:
            start = cursor
            while cursor < len(css) and css[cursor] != ")":
                if css[cursor] in ("\\", "'", '"'):
                    return "an escaped or malformed CSS URL"
                cursor += 1
            if cursor >= len(css):
                return "a malformed CSS URL"
            target = css[start:cursor].strip()
        if target and not target.startswith("#"):
            return "an external CSS URL"
        index = cursor + 1
    return None


def _xml_directive_issue(text):
    """Detect DTDs/stylesheets outside comments and CDATA before XML parsing."""
    index = 0
    while True:
        index = text.find("<", index)
        if index < 0:
            return None
        if text.startswith("<!--", index):
            end = text.find("-->", index + 4)
            if end < 0:
                return "malformed XML comment"
            index = end + 3
            continue
        if text.startswith("<![CDATA[", index):
            end = text.find("]]>", index + 9)
            if end < 0:
                return "malformed XML CDATA"
            index = end + 3
            continue
        if text.startswith("<?", index):
            end = text.find("?>", index + 2)
            if end < 0:
                return "malformed XML processing instruction"
            if re.match(r"<\?xml-stylesheet\b", text[index:end + 2], re.I):
                return "an external XML stylesheet"
            index = end + 2
            continue
        if re.match(r"<!DOCTYPE\b", text[index:], re.I):
            return "an XML DOCTYPE"
        index += 1


def _decode_text(head):
    """`head` as text when the bytes plausibly ARE text, else None.

    The split matters because **the only text-shaped image format is SVG**: a
    payload that decodes as text and is not an SVG is not an image, whatever
    the Content-Type claims. JSON error bodies, plain-text 404s and HTML block
    pages all land here, including the spellings that used to slip past a
    `startswith` probe (a UTF-8 BOM, a leading comment, leading blank lines).

    A real image's first bytes carry NULs or other C0 control bytes within the
    first few hundred, so no raster format reaches this branch by accident.
    """
    if not head:
        return None
    chunk = head
    # a fixed-size window can cut a multi-byte character in half; back off up
    # to three bytes before concluding the payload is not UTF-8 at all.
    for _ in range(4):
        try:
            text = chunk.decode("utf-8")
            break
        except UnicodeDecodeError:
            chunk = chunk[:-1]
            if not chunk:
                return None
    else:
        return None
    for ch in text:
        code = ord(ch)
        if (code < 0x20 and code not in _TEXT_CTRL) or code == 0x7f:
            return None
    return text


def _is_svg_text(text):
    """Is the ROOT ELEMENT of this text `<svg>`?

    How SVG is validated, deliberately: an SVG is text, so there are no magic
    bytes to trust and something has to stand in for them. The rule chosen is
    *the root element must be `svg`* — step over a BOM, whitespace, an XML
    declaration or processing instruction, comments and a DOCTYPE, then require
    the first real element to be `<svg`. The looser "starts with `<?xml` and
    contains `<svg` somewhere" test this replaces accepted an XHTML page with an
    inline icon, an RSS feed with an SVG logo, and any HTML block page a CDN
    prefixed with a comment — all of which then landed in the vault as `.svg`.
    Anything truncated mid-prolog is not an SVG here: no verdict means no write.
    """
    s = text.lstrip("\ufeff").lstrip()
    while s[:1] == "<" and s[1:2] in ("?", "!"):
        if s.startswith("<!--"):
            end, skip = s.find("-->"), 3
        elif s.startswith("<?"):
            end, skip = s.find("?>"), 2
        else:                            # <!DOCTYPE …>, <![CDATA[…
            # A DOCTYPE may contain an internal subset with declarations
            # whose own ``>`` characters do not close the DOCTYPE. Scan to
            # the first unquoted ``>`` outside square brackets; no entity is
            # expanded or otherwise interpreted here.
            end, depth, quote_char = -1, 0, None
            for index, char in enumerate(s[2:], 2):
                if quote_char is not None:
                    if char == quote_char:
                        quote_char = None
                    continue
                if char in ("'", '"'):
                    quote_char = char
                elif char == "[":
                    depth += 1
                elif char == "]" and depth:
                    depth -= 1
                elif char == ">" and depth == 0:
                    end = index
                    break
            skip = 1
        if end < 0:
            return False
        s = s[end + skip:].lstrip()
    return bool(_SVG_ROOT_RE.match(s))


def _svg_safety_issue(text):
    """Name active or externally loaded SVG content, else return ``None``.

    A local SVG is displayed later by Obsidian/Electron, outside this helper's
    process. Parse its XML structure instead of trying to sanitize markup with
    regular expressions: character references and CDATA must be interpreted in
    their actual context, while comments and text labels must not become false
    element or CSS matches. Fragment-only references such as ``href="#marker"``
    and ``url("#gradient")`` remain available for ordinary diagrams.
    """
    directive_issue = _xml_directive_issue(text)
    if directive_issue:
        return directive_issue
    try:
        root = ET.fromstring(text)
    except (ET.ParseError, ValueError) as exc:
        return "malformed XML (%s)" % exc
    namespace, local = _xml_name(root.tag)
    if local.casefold() != "svg" or namespace not in ("", _SVG_NAMESPACE):
        return "a non-SVG root element or namespace"

    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        _namespace, local = _xml_name(element.tag)
        local = local.casefold()
        if local in _SVG_ACTIVE_ELEMENTS:
            return "an active script, animation, or foreign element"
        for raw_name, raw_value in element.attrib.items():
            _attr_namespace, name = _xml_name(raw_name)
            name = name.casefold()
            value = str(raw_value)
            if len(name) > 2 and name.startswith("on"):
                return "an event-handler attribute"
            if name in _SVG_EXTERNAL_ATTRIBUTES:
                locator = value.strip()
                if locator and not locator.startswith("#"):
                    return "an external href, source, or base attribute"
            if (name in ("animation", "transition")
                    or name.startswith(("animation-", "transition-"))):
                return "a CSS animation or transition attribute"
            if name in _SVG_CSS_VALUE_ATTRIBUTES:
                issue = _css_reference_issue(value)
                if issue:
                    return "an external CSS resource (%s)" % issue
        if local == "style":
            issue = _css_reference_issue("".join(element.itertext()))
            if issue:
                return "an external CSS resource (%s)" % issue
    return None


def _validate_svg_file(path, max_bytes=DEFAULT_MAX_BYTES):
    """Require a bounded, complete, inert, self-contained UTF-8 SVG file."""
    size = os.path.getsize(path)
    if size > max_bytes:
        raise ValueError(
            "SVG exceeds the %d-byte safety cap" % max_bytes)
    with open(path, "r", encoding="utf-8-sig", newline="") as source:
        text = source.read()
    if not _is_svg_text(text):
        raise ValueError("SVG root could not be validated from the complete file")
    issue = _svg_safety_issue(text)
    if issue:
        raise ValueError(
            "refusing SVG with %s; only inert self-contained SVG is supported"
            % issue)


def _image_magic(head):
    """The image format these bytes actually are, or None. Bytes only.

    Nothing here consults the Content-Type or the URL: this is the evidence
    those two are checked against, not combined with.
    """
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:3] == b"\xff\xd8\xff":
        return "jpg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    # ISO-BMFF: only the AVIF brands are an image this skill writes. Every
    # other brand (mp4, isom, heic) is a media container, and _binary_shape
    # names it rather than letting the header call it a png.
    if head[4:8] == b"ftyp" and len(head) >= 12:
        size = int.from_bytes(head[:4], "big")
        box_end = min(len(head), size) if size >= 12 else len(head)
        brands = [head[8:12]]
        brands.extend(head[index:index + 4]
                      for index in range(16, box_end - 3, 4))
        if any(brand in (b"avif", b"avis") for brand in brands):
            return "avif"
    if head[:2] == b"BM":
        return "bmp"
    if head[:4] in (b"II\x2a\x00", b"MM\x00\x2a"):
        return "tiff"
    if head[:4] == b"\x00\x00\x01\x00":
        return "ico"
    return None


def _binary_shape(head):
    """What these non-text, non-image bytes are, or None when unrecognized."""
    for magic, name in _NOT_IMAGE_MAGIC:
        if head.startswith(magic):
            return name
    if head[4:8] == b"ftyp":
        brand = head[8:12].decode("ascii", "replace").strip()
        return "an ISO media container (brand %r)" % brand
    return None


def describe_bytes(head):
    """A short human name for what `head` looks like, for a failure message.

    A refusal that says only "not an image" sends the reader back to the URL
    with nothing to go on; naming the shape ("a JSON body", "an HTML page", "a
    PDF") says whether the CDN returned an error document, a login wall or the
    wrong file entirely.
    """
    named = _binary_shape(head)          # %PDF-/%!PS are text-shaped: check first
    if named and head[:1] in (b"%",):
        return named
    ext = _image_magic(head)
    if ext:
        return "a %s image" % ext.upper()
    text = _decode_text(head)
    if text is not None:
        s = text.lstrip("\ufeff").lstrip()
        low = s.lower()
        if _is_svg_text(text):
            return "an SVG document"
        if low.startswith("<!doctype html") or low.startswith("<html") \
                or "<html" in low[:1024]:
            return "an HTML page"
        if s[:1] in "{[":
            return "a JSON body"
        if s[:1] == "<":
            return "an XML or markup document"
        return "plain text"
    return named or "unrecognized binary data"


def sniff_extension(head, content_type=None, url=None):
    """Detect a supported image signature; headers and URL names cannot supply it.

    Returns an extension, or None when the payload is not an image at all (an
    HTML error page, a JSON error body, a PDF, a failed redirect — all treated
    as a download failure).

    The order is evidence first, claims second, and it is that way round because
    a `Content-Type` is whatever the server chose to send. A mapped `image/*`
    type used to win outright, so any JSON, text, PDF, ZIP, ELF or
    comment-prefixed HTML body served as `Content-Type: image/png` was written
    into `Sources/Images/` and reported `"ok": true` — the one thing this script
    exists to prevent. So:

    1. **Magic bytes win.** A recognized image signature is the answer, even
       when the header disagrees (Substack serves webp under `.png` URLs).
    2. **Bytes that are recognizably something else lose.** Text that is not an
       SVG root, and the binary signatures in `_NOT_IMAGE_MAGIC`, are a failure
       no header can rescue.
    3. **Unrecognized bytes fail too.** Otherwise arbitrary binary data with an
       image header or a .png URL is published as a successful image. Add a
       byte signature for a new format instead of guessing its extension.

    This is format identification, not a complete image decode. Visual review
    must still check that a recognized image is intact and readable.

    A failure here is what puts the documented `<!-- image download failed: … -->`
    placeholder in the body; `describe_bytes` names the shape for the message.
    """
    text = _decode_text(head)
    if text is not None:
        # The only text-shaped image is SVG, and it has to be one at the root.
        return "svg" if _is_svg_text(text) else None
    ext = _image_magic(head)
    if ext:
        return ext
    return None


def _temp_path():
    # No image extension, and outside Sources/Images on purpose: nothing half-written
    # or wrongly-named must ever appear in the vault.
    fd, path = tempfile.mkstemp(prefix="clipping_img.", suffix="")
    os.close(fd)
    return path


def _stable_regular_snapshot(path, copy_to=None, copy_mode=None):
    """Read one regular file consistently; optionally stage the same bytes.

    The returned equality key intentionally omits ctime and link count: the
    guarded publication protocol creates private hard links, which changes
    those fields without changing the authorized content. They remain part of
    the before/after read stability check.
    """
    path = os.path.abspath(path)
    try:
        before = os.lstat(path)
    except OSError as exc:
        raise OSError(errno.ENOENT, "%r is missing or unreadable (%s)" %
                      (path, exc), path) from exc
    if not stat.S_ISREG(before.st_mode):
        raise OSError(errno.EINVAL, "%r is a symlink or non-regular file" % path,
                      path)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise OSError(getattr(exc, "errno", None) or errno.EIO,
                      "%r changed or could not be opened safely (%s)" %
                      (path, exc), path) from exc

    digest = hashlib.sha256()
    destination = None
    try:
        with os.fdopen(descriptor, "rb") as source:
            opened_before = os.fstat(source.fileno())
            if (not stat.S_ISREG(opened_before.st_mode)
                    or file_identity(path) != (
                        opened_before.st_dev, opened_before.st_ino,
                        stat.S_IFMT(opened_before.st_mode))):
                raise OSError(errno.EBUSY, "%r changed while it was opened" % path,
                              path)
            if copy_to is not None:
                destination = open(copy_to, "xb")
            try:
                while True:
                    chunk = source.read(CHUNK)
                    if not chunk:
                        break
                    digest.update(chunk)
                    if destination is not None:
                        destination.write(chunk)
                if destination is not None:
                    set_private_mode(destination, copy_to, copy_mode)
                    destination.flush()
                    os.fsync(destination.fileno())
                opened_after = os.fstat(source.fileno())
            finally:
                if destination is not None:
                    destination.close()
    except Exception:
        if copy_to is not None:
            try:
                os.unlink(copy_to)
            except OSError:
                pass
        raise

    try:
        after = os.lstat(path)
    except OSError as exc:
        if copy_to is not None:
            try:
                os.unlink(copy_to)
            except OSError:
                pass
        raise OSError(getattr(exc, "errno", None) or errno.EIO,
                      "%r changed while it was read (%s)" % (path, exc),
                      path) from exc
    stable = lambda item: (
        item.st_dev, item.st_ino, stat.S_IFMT(item.st_mode), item.st_size,
        getattr(item, "st_mtime_ns", int(item.st_mtime * 1e9)),
        getattr(item, "st_ctime_ns", int(item.st_ctime * 1e9)),
    )
    identity = lambda item: (
        item.st_dev, item.st_ino, stat.S_IFMT(item.st_mode))
    # Native Windows can project stable permission and timestamp metadata
    # differently through path stat and handle stat. Compare each API with
    # itself across the read, then bind the two views by portable identity.
    if not (stable(before) == stable(after)
            and stable(opened_before) == stable(opened_after)
            and identity(before) == identity(opened_before)
            and identity(after) == identity(opened_after)):
        if copy_to is not None:
            try:
                os.unlink(copy_to)
            except OSError:
                pass
        raise OSError(errno.EBUSY,
                      "%r changed while its bytes were copied" % path, path)
    snapshot = (
        (after.st_dev, after.st_ino, stat.S_IFMT(after.st_mode)),
        digest.hexdigest(), stat.S_IMODE(after.st_mode), after.st_size,
    )
    if copy_to is not None:
        staged = _stable_regular_snapshot(copy_to)
        if (staged[1], staged[3]) != (snapshot[1], snapshot[3]):
            raise OSError(errno.EIO, "staged bytes do not match %r" % path,
                          copy_to)
    return snapshot


def _body_after_frontmatter(text):
    """Return the body behind a closed leading YAML block, or ``None``.

    This deliberately follows ``dedup_index.read_source``'s two harmless
    tolerances (a BOM, already removed by ``utf-8-sig``, and leading blank
    lines). Ownership evidence never comes from frontmatter text itself.
    """
    lines = text.splitlines(keepends=True)
    opening = None
    for index, line in enumerate(lines):
        if line.strip():
            opening = index
            break
    if opening is None or lines[opening].strip() != "---":
        return None
    for index in range(opening + 1, len(lines)):
        if lines[index].strip() == "---":
            return "".join(lines[index + 1:])
    return None


def _has_current_sources_key(text):
    """Whether the closed leading YAML block has one top-level ``sources``."""
    lines = text.splitlines()
    opening = next((index for index, line in enumerate(lines) if line.strip()), None)
    if opening is None or lines[opening].strip() != "---":
        return False
    count = 0
    for line in lines[opening + 1:]:
        if line.strip() == "---":
            return count == 1
        if re.match(r"\Asources\s*:", line, re.IGNORECASE):
            count += 1
    return False


def _mask_span(text, opening, closing, *, mask_unclosed=True):
    """Blank delimited spans without changing lines or surrounding text.

    Ownership evidence is conservative and masks an unclosed region to EOF.
    Dependency retirement is conservative in the other direction: an unmatched
    delimiter is malformed rather than proof that later links are inert, so
    callers can leave it visible with ``mask_unclosed=False``.
    """
    chars = list(text)
    cursor = 0
    while True:
        start = text.find(opening, cursor)
        if start < 0:
            break
        end = text.find(closing, start + len(opening))
        if end < 0 and not mask_unclosed:
            break
        stop = len(text) if end < 0 else end + len(closing)
        for index in range(start, stop):
            if chars[index] not in "\r\n":
                chars[index] = " "
        if end < 0:
            break
        cursor = stop
    return "".join(chars)


def _mask_inline_code(text, *, mask_unclosed=True):
    """Blank CommonMark backtick spans, including multiline spans.

    A closing run must have exactly the opening width; a longer run is a
    different delimiter.  Treat unresolved runs like the other malformed
    delimiters: mask to EOF for positive ownership evidence, but keep them
    visible for a dependency scan that must fail closed against data loss.
    """
    chars = list(text)
    cursor = 0
    while cursor < len(text):
        start = text.find("`", cursor)
        if start < 0:
            break
        width = 1
        while start + width < len(text) and text[start + width] == "`":
            width += 1
        end = -1
        probe = start + width
        while probe < len(text):
            candidate = text.find("`", probe)
            if candidate < 0:
                break
            run_end = candidate + 1
            while run_end < len(text) and text[run_end] == "`":
                run_end += 1
            if run_end - candidate == width:
                end = candidate
                break
            probe = run_end
        if end < 0:
            if mask_unclosed:
                for index in range(start, len(text)):
                    if chars[index] not in "\r\n":
                        chars[index] = " "
                break
            cursor = start + width
            continue
        stop = end + width
        for index in range(start, stop):
            if chars[index] not in "\r\n":
                chars[index] = " "
        cursor = stop
    return "".join(chars)


def _mask_html_literal_blocks(text, *, mask_unclosed=True):
    """Blank raw HTML regions whose contents render as code or non-content."""
    chars = list(text)
    cursor = 0
    opening = re.compile(r"<(pre|code|script|style)\b[^>]*>", re.IGNORECASE)
    while True:
        match = opening.search(text, cursor)
        if match is None:
            break
        closing = re.compile(r"</%s\s*>" % re.escape(match.group(1)),
                             re.IGNORECASE)
        end_match = closing.search(text, match.end())
        if end_match is None and not mask_unclosed:
            cursor = match.end()
            continue
        stop = len(text) if end_match is None else end_match.end()
        for index in range(match.start(), stop):
            if chars[index] not in "\r\n":
                chars[index] = " "
        if end_match is None:
            break
        cursor = stop
    return "".join(chars)


def _rendered_embed_basenames(body):
    """Return filename-only Obsidian image embeds outside code/comments.

    A clipped article can quote ``![[name.png]]`` in prose, code, or comments.
    Those strings are not rendered attachment references and cannot prove that
    the note owns a same-named file. False negatives are intentional here: an
    owner check may refuse and ask for inspection, but it must never take a
    shared-folder file based on inert source text.
    """
    visible = _mask_inline_code(_mask_html_literal_blocks(
        _mask_span(_mask_span(body, "<!--", "-->"), "%%", "%%")))
    out = []
    fence = None
    for line in visible.splitlines(keepends=True):
        stripped = line.rstrip("\r\n")
        if fence is not None:
            close = re.match(r" {0,3}(%s{%d,})[ \t]*$" %
                             (re.escape(fence[0]), fence[1]), stripped)
            if close:
                fence = None
            continue
        opened = re.match(r" {0,3}(`{3,}|~{3,})", stripped)
        if opened:
            marker = opened.group(1)
            fence = (marker[0], len(marker))
            continue
        if line.startswith("\t") or line.startswith("    "):
            continue
        for match in re.finditer(r"(?<!\\)!\[\[([^\]\r\n]+)\]\]", line):
            target = match.group(1).split("|", 1)[0].split("#", 1)[0].strip()
            # The plugin's attachment convention is filename-only. Accepting
            # a path-qualified target and reducing it to basename would let a
            # reference to some other folder claim this shared flat namespace.
            if (not target or "/" in target or "\\" in target
                    or target in (".", "..")):
                continue
            out.append(target)
    return frozenset(out)


_DEPENDENCY_SKIP_DIRS = frozenset((".git", ".obsidian", ".trash", "node_modules"))
_MARKDOWN_LINK_TARGET = re.compile(
    r"!?\[[^\]\r\n]*\]\(\s*(?:<(?P<angle>[^>\r\n]+)>|(?P<plain>[^)\s\r\n]+))")
_MARKDOWN_REFERENCE_TARGET = re.compile(
    r"^[ \t]{0,3}\[[^\]\r\n]+\]:[ \t]*(?:<(?P<angle>[^>\r\n]+)>|(?P<plain>\S+))",
    re.MULTILINE)
_HTML_REFERENCE_TARGET = re.compile(
    r"\b(?:src|href)[ \t]*=[ \t]*(?:\"([^\"\r\n]+)\"|'([^'\r\n]+)')",
    re.IGNORECASE)


def _visible_markdown(text):
    """Mask literal/comment regions while retaining rendered link syntax."""
    visible = _mask_inline_code(_mask_html_literal_blocks(
        _mask_span(_mask_span(text, "<!--", "-->", mask_unclosed=False),
                   "%%", "%%", mask_unclosed=False), mask_unclosed=False),
        mask_unclosed=False)
    lines = visible.splitlines(keepends=True)
    out = []
    fence = None
    for line in lines:
        stripped = line.rstrip("\r\n")
        if fence is not None:
            close = re.match(r" {0,3}(%s{%d,})[ \t]*$" %
                             (re.escape(fence[0]), fence[1]), stripped)
            if close:
                fence = None
            out.append("\n" if line.endswith(("\n", "\r")) else "")
            continue
        opened = re.match(r" {0,3}(`{3,}|~{3,})", stripped)
        if opened:
            marker = opened.group(1)
            fence = (marker[0], len(marker))
            out.append("\n" if line.endswith(("\n", "\r")) else "")
            continue
        # Do not treat indentation as proof of a code block here. Obsidian's
        # MOCs use nested list indentation of four or more spaces; dependency
        # retirement must fail closed and see links in those list items.
        out.append(line)
    return "".join(out)


def _local_target_basename(target, *, wikilink=False):
    """Return the basename of a local Markdown target, never a remote URL."""
    target = str(target).strip()
    if wikilink:
        # An escaped pipe is still the display separator in an Obsidian table.
        target = re.split(r"(?<!\\)\||\\\|", target, maxsplit=1)[0]
        target = target.split("#", 1)[0].strip()
    else:
        target = target.strip("<>")
        target = target.split("#", 1)[0].split("?", 1)[0]
    if not target or target.startswith("//") \
            or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
        return None
    try:
        target = urllib.parse.unquote(target)
    except (UnicodeError, ValueError):
        return None
    target = target.replace("\\", "/").rstrip("/")
    return target.rsplit("/", 1)[-1].strip() or None


def _markdown_dependency_names(text, image_names, old_slug):
    """Known old image/note targets referenced by rendered Markdown."""
    visible = _visible_markdown(text)
    images = {_manifest_name_key(name): name for name in image_names}
    note_key = _manifest_name_key(old_slug)
    found = set()

    def inspect(target, wikilink=False):
        base = _local_target_basename(target, wikilink=wikilink)
        if not base:
            return
        image = images.get(_manifest_name_key(base))
        if image is not None:
            found.add(image)
        stem, extension = os.path.splitext(base)
        if ((_manifest_name_key(base) == note_key and not extension)
                or (extension.casefold() == ".md"
                    and _manifest_name_key(stem) == note_key)):
            found.add(old_slug + ".md")

    for match in re.finditer(r"(?<!\\)!?\[\[([^\]\r\n]+)\]\]", visible):
        inspect(match.group(1), wikilink=True)
    for pattern in (_MARKDOWN_LINK_TARGET, _MARKDOWN_REFERENCE_TARGET):
        for match in pattern.finditer(visible):
            inspect(match.group("angle") or match.group("plain"))
    for match in _HTML_REFERENCE_TARGET.finditer(visible):
        inspect(match.group(1) or match.group(2))
    return sorted(found, key=lambda item: (_manifest_name_key(item), item))


def _stable_markdown_text(path):
    """Read one complete UTF-8 Markdown entry and reject concurrent changes."""
    def stable(item):
        return (item.st_dev, item.st_ino, stat.S_IFMT(item.st_mode), item.st_size,
                getattr(item, "st_mtime_ns", int(item.st_mtime * 1e9)),
                getattr(item, "st_ctime_ns", int(item.st_ctime * 1e9)))

    entry_before = os.lstat(path)
    target_before = os.stat(path)
    if not stat.S_ISREG(target_before.st_mode):
        raise ValueError("not a regular Markdown file")
    with open(path, "rb") as source:
        opened_before = os.fstat(source.fileno())
        raw = source.read()
        opened_after = os.fstat(source.fileno())
    entry_after = os.lstat(path)
    target_after = os.stat(path)
    identity = lambda item: (
        item.st_dev, item.st_ino, stat.S_IFMT(item.st_mode))
    # Keep path and handle projections internally stable without requiring
    # their platform-specific metadata views to be byte-for-byte identical.
    if (stable(entry_before) != stable(entry_after)
            or stable(target_before) != stable(target_after)
            or stable(opened_before) != stable(opened_after)
            or identity(target_before) != identity(opened_before)
            or identity(target_after) != identity(opened_after)):
        raise ValueError("changed while the dependency inventory read it")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("is not complete valid UTF-8 (%s)" % exc) from exc


def _vault_markdown_files(vault):
    """Yield every vault Markdown file, following folder links without cycles."""
    def failed(exc):
        raise ValueError("cannot scan vault directory %r: %s" %
                         (getattr(exc, "filename", None) or vault, exc)) from exc

    seen = set()
    for root, dirs, files in os.walk(vault, followlinks=True, onerror=failed):
        try:
            item = os.stat(root)
        except OSError as exc:
            raise ValueError("cannot identify vault directory %r: %s" %
                             (root, exc)) from exc
        identity = (item.st_dev, item.st_ino)
        if identity in seen:
            dirs[:] = []
            continue
        seen.add(identity)
        dirs[:] = [name for name in dirs
                   if name.casefold() not in _DEPENDENCY_SKIP_DIRS]
        for name in files:
            if name.casefold().endswith(".md"):
                yield os.path.join(root, name)


def _same_logical_note(path, owner_path):
    """Identity-safe match for one directory entry, not a foreign hard link."""
    if (_manifest_name_key(os.path.basename(path))
            != _manifest_name_key(os.path.basename(owner_path))):
        return False
    try:
        return (os.path.samefile(path, owner_path)
                and os.path.samefile(os.path.dirname(path),
                                     os.path.dirname(owner_path)))
    except OSError as exc:
        raise ValueError("cannot distinguish owner note %r from %r: %s" %
                         (owner_path, path, exc)) from exc


def _canonical_vault_root(owner_path, attachments):
    """Infer the vault only when owner and images are the canonical pair."""
    return _bound_attachment_vault_root(owner_path, attachments)


def _vault_dependency_blockers(owner, old_slug, image_names):
    """External old-note/image references, or incomplete-scan blockers."""
    vault = owner.get("vault")
    if vault is None:
        return []
    blockers = []
    try:
        paths = _vault_markdown_files(vault)
        for path in paths:
            if _same_logical_note(path, owner["path"]):
                continue
            try:
                text = _stable_markdown_text(path)
            except (OSError, ValueError, UnicodeError) as exc:
                blockers.append({"path": os.path.abspath(path),
                                 "error": "cannot scan Markdown dependency: %s" % exc})
                continue
            found = _markdown_dependency_names(text, image_names, old_slug)
            if found:
                blockers.append({"path": os.path.abspath(path),
                                 "references": found})
    except (OSError, ValueError, UnicodeError) as exc:
        path = getattr(exc, "filename", None) or vault
        blockers.append({"path": os.path.abspath(path),
                         "error": "cannot complete vault Markdown inventory: %s" % exc})
    return sorted(blockers, key=lambda row: (
        _manifest_name_key(row["path"]), row["path"]))


def _dependency_error(blockers):
    details = []
    for blocker in blockers:
        reason = blocker.get("error") or ("references " +
                 ", ".join(blocker.get("references", ())))
        details.append("%s (%s)" % (blocker["path"], reason))
    return ("external Markdown dependencies block this changed-slug rename; "
            "rewrite them through a separately authorized complete dependency "
            "operation, or retain the old note and image paths: " +
            "; ".join(details))


def _attachment_vault_roots(attachments):
    """Logical and physical vault-root candidates for Sources/Images.

    A vault may symlink its whole ``Sources`` directory to a storage location.
    The logical path then owns the vault's ``Articles`` folder while the real
    target usually has none. Retaining both candidates lets owner identity
    choose that logical vault without letting an alias between two complete
    vaults borrow either one's note as attachment ownership evidence.
    """
    logical = os.path.abspath(attachments)
    resolved = os.path.realpath(logical)
    roots = []
    for path in (logical, resolved):
        parent = os.path.dirname(path)
        if (os.path.basename(path).casefold() == "images"
                and os.path.basename(parent).casefold() == "sources"):
            root = os.path.dirname(parent)
            if root not in roots:
                roots.append(root)
    return tuple(roots)


def _bound_attachment_vault_root(owner_path, attachments):
    """Bind canonical attachments to exactly one owner ``Articles`` identity."""
    roots = _attachment_vault_roots(attachments)
    if not roots:
        return None
    owner_parent = os.path.dirname(os.path.abspath(owner_path))
    try:
        owner_stat = os.stat(owner_parent)
    except OSError as exc:
        raise ValueError("cannot establish the owner note's Articles/ folder "
                         "identity: %s" % exc) from exc
    if not stat.S_ISDIR(owner_stat.st_mode):
        raise ValueError("--owner-note parent is not an Articles directory")
    owner_identity = owner_stat.st_dev, owner_stat.st_ino

    candidates = []
    for root in roots:
        articles = os.path.join(root, "Articles")
        try:
            item = os.stat(articles)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ValueError("cannot establish the owner note's vault binding "
                             "through %r: %s" % (articles, exc)) from exc
        if not stat.S_ISDIR(item.st_mode):
            raise ValueError("canonical vault path is not an Articles directory: "
                             "%r" % articles)
        candidates.append((root, (item.st_dev, item.st_ino)))

    identities = {identity for _root, identity in candidates}
    if len(identities) > 1:
        raise ValueError(
            "--attachments resolves between multiple vaults with distinct "
            "Articles/ folders; use the canonical Sources/Images path for the "
            "owner note's vault")
    matches = [root for root, identity in candidates
               if identity == owner_identity]
    if not matches:
        raise ValueError("--owner-note is not in the Articles/ folder for this "
                         "Sources/Images vault")

    lexical_owner_root = os.path.dirname(owner_parent)
    chosen = (lexical_owner_root if lexical_owner_root in matches else matches[0])
    # Preserve the established canonical spelling used in blocker reports
    # (`/private/var/...` on macOS), while resolving only the vault root itself;
    # a symlinked Sources/ child still stays attached to this logical vault.
    return os.path.realpath(chosen)


def _owner_namespace(owner_note, slug, attachments):
    """Validate the note name, its unique Articles slot, and vault binding."""
    path = os.path.abspath(os.fspath(owner_note))
    parent = os.path.dirname(path)
    expected = slug + ".md"
    if os.path.basename(parent).casefold() != "articles":
        raise ValueError("--owner-note must be a direct child of Articles/: %r" % path)
    if _manifest_name_key(os.path.basename(path)) != _manifest_name_key(expected):
        raise ValueError("--owner-note must be Articles/%s for this operation" % expected)

    # Bind canonical <vault>/Sources/Images paths to that same vault's
    # Articles folder. Noncanonical attachment folders remain usable for
    # isolated tests and deliberate library calls, but still require an
    # Articles direct child and all positive evidence below.
    # A noncanonical attachment folder returns None and keeps the documented
    # isolated-library behavior. A canonical logical or physical path must bind
    # to this exact Articles directory, and ambiguity raises here.
    _bound_attachment_vault_root(path, attachments)

    try:
        with os.scandir(parent) as entries:
            matches = [entry.path for entry in entries
                       if _manifest_name_key(entry.name)
                       == _manifest_name_key(expected)]
    except OSError as exc:
        raise ValueError("cannot inventory the owner note's Articles folder: %s" % exc) from exc
    if len(matches) != 1:
        raise ValueError("Articles/%s has %d portable name occupants; ownership "
                         "is ambiguous" % (expected, len(matches)))
    try:
        if not os.path.samefile(path, matches[0]):
            raise ValueError("--owner-note does not identify the unique Articles/%s" % expected)
    except OSError as exc:
        raise ValueError("--owner-note cannot be identified safely: %s" % exc) from exc
    return path


def _load_clipping_owner(owner_note, slug, attachments, *, require_vault=False):
    """Snapshot exact clipping-note evidence for a destructive image action."""
    if not owner_note:
        raise ValueError("--owner-note is required to overwrite or rename clipping images")
    path = _owner_namespace(owner_note, slug, attachments)
    with tempfile.TemporaryDirectory(prefix="clipping_owner.") as scratch:
        copied = os.path.join(scratch, "owner.md")
        try:
            snapshot = _stable_regular_snapshot(
                path, copy_to=copied, copy_mode=0o600)
        except (OSError, UnicodeError) as exc:
            raise ValueError(
                "--owner-note is not a stable readable regular file: %s" % exc
            ) from exc
        try:
            with open(copied, "r", encoding="utf-8-sig") as fh:
                note_text = fh.read()
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError("--owner-note is not a stable UTF-8 clipping note: %s" % exc) from exc
        origin = read_source(copied)
        if (not _has_current_sources_key(note_text) or not origin
                or not normalize_url(origin)):
            raise ValueError("--owner-note does not have a valid HTTP(S) URL as "
                             "its first current sources item")
        body = _body_after_frontmatter(note_text)
        if body is None:
            raise ValueError("--owner-note has no closed leading YAML frontmatter")
        embeds = _rendered_embed_basenames(body)
    vault = _canonical_vault_root(path, attachments)
    if require_vault and vault is None:
        raise ValueError(
            "destructive image operations require --attachments to be the "
            "owner note's canonical <vault>/Sources/Images folder so the "
            "vault-wide dependency scan cannot be bypassed")
    return {"path": path, "slug": slug, "attachments": attachments,
            "snapshot": snapshot, "embeds": embeds, "vault": vault,
            "origin": normalize_url(origin)}


def _validate_clipping_owner(owner):
    """Refuse if either the owner bytes or its portable note slot changed."""
    path = _owner_namespace(owner["path"], owner["slug"], owner["attachments"])
    current = _stable_regular_snapshot(path)
    if current != owner["snapshot"]:
        raise ValueError("--owner-note changed during the image operation; refusing stale ownership")


def _require_owned_attachment(owner, filename):
    _validate_clipping_owner(owner)
    wanted = _manifest_name_key(filename)
    matches = [name for name in owner["embeds"]
               if _manifest_name_key(name) == wanted]
    if len(matches) != 1:
        raise ValueError("%s is not an exact rendered filename-only embed in %s; "
                         "refusing to claim an unattributed attachment" %
                         (filename, owner["path"]))


def _restore_after_slot_conflict(final, published, predecessor, predecessor_snapshot,
                                 stage, stage_parent):
    """Conditionally undo this publication after a late extension twin."""
    rollback = os.path.join(stage, ".slot-conflict-rollback")
    os.mkdir(rollback)
    if predecessor is None:
        remove_expected(final, published, _stable_regular_snapshot, rollback,
                        stage_parent=stage_parent,
                        recovery_prefix=".clipping-recovery-")
        return
    if not os.path.lexists(final):
        link_noreplace(predecessor, final)
        if _stable_regular_snapshot(final) != predecessor_snapshot:
            raise PublicationConflict(
                "%s could not be verified after restoration" % final,
                recovery_path=predecessor, keep_stage=True)
        return
    replace_expected(predecessor, final, published, _stable_regular_snapshot,
                     rollback, stage_parent=stage_parent,
                     recovery_prefix=".clipping-recovery-")


def _remove_copied_source(src, expected):
    """Remove only the exact source copied into the publication stage."""
    src = os.path.abspath(src)
    parent = os.path.dirname(src) or "."
    try:
        stage = tempfile.mkdtemp(prefix=".clipping-source-cleanup.", dir=parent)
    except OSError as exc:
        return ("published successfully, but retained scratch source %r because "
                "conditional cleanup could not be staged: %s" % (src, exc))
    keep_stage = False
    try:
        try:
            removed = remove_expected(
                src, expected, _stable_regular_snapshot, stage,
                stage_parent=parent, recovery_prefix=".clipping-recovery-")
        except PublicationConflict as exc:
            keep_stage = exc.keep_stage
            return ("published successfully, but retained the changed scratch "
                    "source %r%s: %s" %
                    (src, " (recovery: %s)" % exc.recovery_path
                     if exc.recovery_path else "", exc))
        except (OSError, UnicodeError) as exc:
            # The conditional helper normally reports every partial state as a
            # PublicationConflict. Preserve the private stage as a last-resort
            # recovery path if the host raises outside that contract.
            keep_stage = True
            return ("published successfully, but scratch-source cleanup failed; "
                    "preserve %s and %r: %s" % (stage, src, exc))
        if not removed:
            return None
        displaced = os.path.join(stage, ".atomic-displaced")
        try:
            unchanged = _stable_regular_snapshot(displaced) == expected
        except (OSError, ValueError):
            unchanged = False
        if unchanged:
            return None
        try:
            link_noreplace(displaced, src)
            restored = "restored at its original path"
        except OSError as exc:
            keep_stage = True
            restored = "preserved at %s (%s)" % (displaced, exc)
        return ("published successfully, but the scratch source changed during "
                "conditional cleanup and was %s" % restored)
    finally:
        if not keep_stage:
            shutil.rmtree(stage, ignore_errors=True)


def _publish_file(src, final, overwrite=False, staging_parent=None, mode=0o644,
                  before_publish=None, after_publish=None,
                  expected_source=None):
    """Publish complete bytes and conditionally remove the copied source.

    New names use exclusive creation. An overwrite displaces and revalidates
    only the exact regular file inspected on entry, preserves its permissions,
    and reads the replacement back before success. The optional callbacks let
    an image caller guard its broader ``stem_fig_N.*`` namespace on both sides
    of the per-file publication; a late extension twin triggers conditional
    rollback rather than leaving two current files.

    On every publication failure the complete ``src`` remains the recovery
    copy at the caller-visible path; download callers expose it as ``scratch``
    and place callers retain it as ``source``. The private staged duplicate may
    therefore be cleaned without losing the reviewed bytes.
    """
    src = os.path.abspath(src)
    final = os.path.abspath(final)
    parent = os.path.abspath(staging_parent or os.path.dirname(final) or ".")
    if os.path.lexists(final):
        if not overwrite:
            raise FileExistsError(final)
        target_expected = _stable_regular_snapshot(final)
        publish_mode = target_expected[2]
    else:
        target_expected = None
        publish_mode = mode
    try:
        if os.path.samefile(src, final):
            raise ValueError("source and publication path are the same file")
    except FileNotFoundError:
        pass

    stage = tempfile.mkdtemp(prefix=".clipping-stage.", dir=parent)
    keep_stage = False
    predecessor = None
    predecessor_snapshot = None
    try:
        staged = os.path.join(stage, "complete")
        source_observed = _stable_regular_snapshot(
            src, copy_to=staged, copy_mode=publish_mode)
        if (expected_source is not None
                and source_observed != expected_source):
            raise PublicationConflict(
                "%s changed after its bytes were inspected; refusing to "
                "publish a different render" % src)
        if before_publish is not None:
            before_publish()
        if target_expected is None:
            published = publish_new(
                staged, final, _stable_regular_snapshot, parent,
                recovery_prefix=".clipping-recovery-")
        else:
            predecessor = os.path.join(stage, "predecessor")
            link_noreplace(final, predecessor)
            predecessor_snapshot = _stable_regular_snapshot(predecessor)
            if predecessor_snapshot != target_expected:
                raise PublicationConflict(
                    "%s changed before its predecessor could be retained" % final)
            published = replace_expected(
                staged, final, target_expected, _stable_regular_snapshot,
                stage, stage_parent=parent,
                recovery_prefix=".clipping-recovery-")
        if after_publish is not None:
            try:
                after_publish()
            except Exception as conflict:
                try:
                    _restore_after_slot_conflict(
                        final, published, predecessor, predecessor_snapshot,
                        stage, parent)
                except (OSError, PublicationConflict) as rollback_exc:
                    keep_stage = True
                    raise PublicationConflict(
                        "late figure-slot conflict (%s); rollback was incomplete: "
                        "%s; preserve %s" % (conflict, rollback_exc, stage),
                        recovery_path=(getattr(rollback_exc, "recovery_path", None)
                                       or stage), keep_stage=True) from rollback_exc
                raise
        return _remove_copied_source(src, source_observed)
    except LinkUnavailable as exc:
        # ``src`` is the caller-owned complete render/download and survives
        # every failed publication. Do not pass through a staging_path that
        # names the private duplicate this helper is about to clean. A distinct
        # displaced predecessor can still require the private stage, though.
        shared_recovery = getattr(exc, "recovery_path", None)
        predecessor_recovery = (
            shared_recovery
            if shared_recovery and os.path.abspath(shared_recovery) != staged
            else None)
        if (predecessor_recovery
                and _inside_existing_directory(predecessor_recovery, stage)):
            keep_stage = True
        reported = LinkUnavailable(src, final, exc.cause)
        reported.strerror = (
            "%s; the complete caller-owned source is preserved at %r" %
            (reported.strerror, src))
        if predecessor_recovery:
            reported.strerror += (
                "; the displaced predecessor is preserved at %r" %
                predecessor_recovery)
        reported.args = (reported.errno, reported.strerror)
        reported.source_recovery_path = src
        reported.recovery_path = predecessor_recovery or src
        reported.staging_path = stage if keep_stage else None
        reported.keep_stage = keep_stage
        raise reported from exc
    except PublicationConflict as exc:
        keep_stage = keep_stage or exc.keep_stage
        if keep_stage and not exc.recovery_path:
            exc.recovery_path = stage
        raise
    finally:
        if not keep_stage:
            shutil.rmtree(stage, ignore_errors=True)


def validate_slug(slug, what="--slug"):
    """Reject a slug that could steer a write out of the Sources/Images folder.

    The slug arrives as free text on the command line — the model types it, and
    it is not necessarily the string `slug.py` produced. `Sources/Images/` is the
    only place this script may write, so a separator, a parent-directory hop or
    an empty value is refused here rather than resolved into a path.
    """
    if slug is None or not str(slug).strip():
        raise ValueError(f"{what} is empty — refusing to write '<empty>_fig_N.ext'")
    slug = str(slug)
    invalid = [ch for ch in slug
               if ord(ch) < 0x20 or ord(ch) == 0x7f
               or ch in '<>:"/\\|?*']
    if invalid:
        bad = invalid[0]
        raise ValueError(f"{what} contains Windows-forbidden filename character "
                         f"{bad!r}: {slug!r} — use the portable slug returned by "
                         "the clipping slug helper")
    if ".." in slug:
        raise ValueError(f"{what} contains '..': {slug!r} — a slug is a "
                         "filename stem, not a path")
    # `.` passed every check above and named no note: it wrote `._fig_1.png`,
    # a dotfile Obsidian does not show, this plugin's `Sources/Images` sweeps do
    # not glob, and wiki-builder's unused-figure diagnostic never sees. The
    # download reported ok and the figure was gone.
    if slug.startswith((".", " ")):
        raise ValueError(f"{what} starts with a dot or space: {slug!r} — that "
                         "would create a hidden or non-portable filename")
    if not slug.strip(". "):
        raise ValueError(f"{what} is {slug!r} — that names no note; a slug is a "
                         "filename stem, not a directory")
    if slug.endswith((".", " ")):
        raise ValueError(f"{what} ends in a dot or space: {slug!r} — Windows "
                         "cannot store that filename portably")
    if is_windows_device_stem(slug):
        raise ValueError(f"{what} is reserved as a Windows device filename: "
                         f"{slug!r} — qualify the clipping slug")
    return slug


def validate_index(index, what="figure index"):
    """Require the positive counter promised by the figure naming contract."""
    if isinstance(index, bool) or not isinstance(index, int) or index < 1:
        raise ValueError(f"{what} must be a positive integer starting at 1: {index!r}")
    return index


def _positive_index_arg(value):
    """argparse adapter for :func:`validate_index`."""
    try:
        index = int(value)
        validate_index(index)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return index


def _positive_int_arg(value):
    """Argparse adapter for positive transfer byte/time limits."""
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _validate_transfer_limits(timeout, max_bytes, max_seconds):
    """Reject disabled or ill-typed resource bounds on programmatic calls."""
    for value, name in ((timeout, "timeout"), (max_seconds, "max_seconds")):
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value <= 0):
            raise ValueError(f"{name} must be a positive finite number")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")


def _ensure_within(directory, path):
    """Assert `path` really lands inside `directory`; return the resolved path."""
    root = os.path.realpath(directory)
    real = os.path.realpath(path)
    if not _inside_existing_directory(path, directory, require_all=True):
        raise ValueError(f"refusing to touch {real!r}: outside the attachments "
                         f"folder {root!r}")
    return real


class _VettedTarget:
    """One parsed URL hop and the exact socket addresses vetted for that hop."""

    __slots__ = ("url", "scheme", "host", "port", "addresses",
                 "request_target", "host_header")

    def __init__(self, url, scheme, host, port, addresses, request_target,
                 host_header):
        self.url = url
        self.scheme = scheme
        self.host = host
        self.port = port
        self.addresses = tuple(addresses)
        self.request_target = request_target
        self.host_header = host_header


# Integer prefixes keep module import declarative: constructing ``IPv6Network``
# objects here trips the repository's no-import-time-execution contract. The
# shifts retain respectively the high 96 or 48 bits used by those networks.
_NAT64_WELL_KNOWN_PREFIX_96 = 0x64FF9B0000000000000000
_NAT64_LOCAL_USE_PREFIX_48 = 0x64FF9B0001
_IPV4_COMPATIBLE_PREFIX_96 = 0


def _embedded_ipv4_addresses(ip):
    """Return IPv4 endpoints carried by a known IPv6 transition form.

    Some IPv6 spellings are classified globally by Python 3.9 even when the
    endpoint they tunnel or translate to is private.  The socket receives the
    IPv6 spelling, so checking only ``IPv6Address.is_global`` is insufficient
    for SSRF policy.  Where the outer IPv6 form itself meets the policy,
    subject its embedded IPv4 endpoint(s) to the same test as well.
    """
    if not isinstance(ip, ipaddress.IPv6Address):
        return ()

    found = []

    def add(value):
        if value is not None and value not in found:
            found.append(value)

    add(ip.ipv4_mapped)
    add(ip.sixtofour)
    if ip.teredo is not None:
        add(ip.teredo[0])  # relay/server IPv4 address
        add(ip.teredo[1])  # de-obfuscated client IPv4 address

    packed = ip.packed
    value = int(ip)
    if value >> 32 == _NAT64_WELL_KNOWN_PREFIX_96:
        add(ipaddress.IPv4Address(packed[12:16]))
    elif value >> 80 == _NAT64_LOCAL_USE_PREFIX_48:
        # RFC 6052's /48 layout splits the 32 IPv4 bits around the reserved
        # ``u`` octet: prefix(48), v4[0:16], u(8), v4[16:32], suffix(40).
        # A nonzero u octet is not a canonical translated address and is
        # represented by 0.0.0.0 so the public-policy caller refuses it.
        add(ipaddress.IPv4Address(
            packed[6:8] + packed[9:11] if packed[8] == 0 else b"\0\0\0\0"))

    # Deprecated IPv4-compatible form. Python 3.9 reports even
    # ``::127.0.0.1`` as global, though an IPv6 stack may translate it to the
    # IPv4 endpoint. The mapped form above occupies a different prefix.
    if (value >> 32 == _IPV4_COMPATIBLE_PREFIX_96
            and ip.ipv4_mapped is None):
        add(ipaddress.IPv4Address(packed[12:16]))

    # ISATAP interface identifiers end in 0000:5efe:v4 or 0200:5efe:v4.
    if packed[8:12] in (b"\0\0\x5e\xfe", b"\x02\0\x5e\xfe"):
        add(ipaddress.IPv4Address(packed[12:16]))
    return tuple(found)


def _public_ip(ip):
    """Whether an address is suitable for the default open-web fetch policy."""
    # Python releases disagree about whether the retired 6to4 prefix itself is
    # globally routable. For SSRF purposes its only effective endpoint is the
    # embedded IPv4 address, so apply the stable IPv4 policy directly instead
    # of inheriting that version-dependent outer classification.
    if isinstance(ip, ipaddress.IPv6Address) and ip.sixtofour is not None:
        return _public_ip(ip.sixtofour)
    # Python 3.9 can report the deprecated IPv6 site-local fec0::/10 range as
    # global. Hosts may still route it internally, so reject it explicitly.
    site_local = (getattr(ip, "version", None) == 6
                  and (int(ip) >> 118) == (int(ipaddress.IPv6Address("fec0::")) >> 118))
    ordinary_public = (
        ip.is_global and not ip.is_loopback and not ip.is_link_local
        and not ip.is_private and not ip.is_reserved and not ip.is_multicast
        and not ip.is_unspecified and not site_local)
    if not ordinary_public:
        return False
    return all(_public_ip(embedded)
               for embedded in _embedded_ipv4_addresses(ip))


def _request_path(parts, original_url):
    """Build an ASCII origin-form request target without re-parsing the URL."""
    path = urllib.parse.quote(
        parts.path or "/", safe="/%:@!$&'()*+,;=-._~")
    # SplitResult does not distinguish `/path` from `/path?`; preserve that
    # delimiter because an origin is allowed to route the two targets apart.
    if "?" in original_url.split("#", 1)[0]:
        path += "?" + urllib.parse.quote(
            parts.query, safe="/%?:@!$&'()*+,;=-._~")
    return path


def _vetted_target(url, allow_private=False):
    """Parse and resolve one URL hop exactly once.

    For HTTP(S), every returned address is classified before any socket opens,
    then the complete vetted ``getaddrinfo`` result is carried to
    :func:`_connect_vetted`. The hostname is never handed to a connector a
    second time. ``data:`` returns ``None`` because it has no network target.
    """
    try:
        parts = urllib.parse.urlsplit(url)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid URL: %s" % _report_url(url)) from exc
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise ValueError(f"unsupported URL scheme {scheme or '(none)'!r} — only "
                         "http, https and data: URIs are fetched")
    if scheme == "data":
        return None
    if any(ord(ch) < 0x20 or ord(ch) == 0x7f for ch in url):
        raise ValueError("HTTP(S) URL contains a control character")
    if not parts.hostname:
        raise ValueError("URL has no host: %s" % _report_url(url))
    if parts.username is not None or parts.password is not None:
        raise ValueError("credentials in HTTP(S) URLs are not supported")
    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError as exc:
        raise ValueError(f"invalid port in URL: {exc}") from exc

    logical_host = parts.hostname
    try:
        host = logical_host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError(f"invalid internationalized host {logical_host!r}") from exc

    # inet_aton accepts legacy numeric forms that getaddrinfo interprets
    # differently across operating systems (0177.0.0.1 is 127.0.0.1 on Linux,
    # but 177.0.0.1 on macOS). Refuse those before DNS under the public policy.
    if not allow_private:
        try:
            numeric = socket.inet_ntoa(socket.inet_aton(host))
        except OSError:
            numeric = None
        if numeric is not None and numeric != host:
            raise ValueError(
                f"ambiguous numeric IPv4 host {logical_host!r} — use {numeric!r} "
                "instead (pass --allow-private-hosts if intended)")

    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"cannot resolve host {logical_host!r}: {exc}") from exc
    if not infos:
        raise ValueError(f"host {logical_host!r} resolved to no addresses")

    addresses = []
    seen = set()
    for family, socktype, proto, canonname, sockaddr in infos:
        if family not in (socket.AF_INET, socket.AF_INET6) or not sockaddr:
            raise ValueError(
                f"host {logical_host!r} resolved to an unsupported address family")
        addr = str(sockaddr[0]).split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError as exc:
            raise ValueError(
                f"host {logical_host!r} resolved to an invalid address {addr!r}") from exc
        if not allow_private and not _public_ip(ip):
            raise ValueError(
                f"host {logical_host!r} resolves to the non-public address {ip} — "
                "refusing (pass --allow-private-hosts if that is intended)")
        item = (family, socktype or socket.SOCK_STREAM, proto, canonname, sockaddr)
        key = (family, item[1], proto, sockaddr)
        if key not in seen:
            addresses.append(item)
            seen.add(key)

    host_literal = f"[{host}]" if ":" in host else host
    authority = parts.netloc.rsplit("@", 1)[-1]
    if authority.startswith("["):
        explicit_port = authority.partition("]")[2].startswith(":")
    else:
        explicit_port = ":" in authority
    if explicit_port and authority.endswith(":"):
        raise ValueError("invalid empty port in URL")
    host_header = (f"{host_literal}:{port}" if explicit_port else host_literal)
    return _VettedTarget(url, scheme, host, port, addresses,
                         _request_path(parts, url), host_header)


def check_url(url, allow_private=False):
    """Allow only HTTP(S)/data and, by default, only public HTTP(S) targets."""
    _vetted_target(url, allow_private)


def _remaining_timeout(timeout, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("exceeded the wall-clock budget before the response body")
    return min(timeout, remaining)


def _connect_vetted(target, timeout, deadline):
    """Connect only to an address returned by this hop's single resolution."""
    errors = []
    for family, socktype, proto, _canonname, sockaddr in target.addresses:
        sock = socket.socket(family, socktype, proto)
        try:
            sock.settimeout(_remaining_timeout(timeout, deadline))
            sock.connect(sockaddr)
            return sock
        except Exception as exc:
            errors.append("%s: %s" % (sockaddr[0], exc))
            sock.close()
    raise OSError("could not connect to any vetted address for %s: %s" %
                  (target.host, "; ".join(errors) or "no addresses"))


def _request_once(target, timeout, deadline):
    """Issue one GET over a pinned socket; return ``(connection, response)``."""
    wire = _connect_vetted(target, timeout, deadline)
    conn = None
    try:
        if target.scheme == "https":
            # create_default_context enables certificate-chain validation and
            # hostname checks. The logical hostname, never the pinned IP, is
            # supplied for SNI and certificate matching.
            context = ssl.create_default_context()
            wire.settimeout(_remaining_timeout(timeout, deadline))
            wire = context.wrap_socket(wire, server_hostname=target.host)
        wire.settimeout(_remaining_timeout(timeout, deadline))
        conn = http.client.HTTPConnection(target.host, target.port,
                                          timeout=timeout)
        # Setting the connected socket makes HTTPConnection skip connect(), so
        # it has no opportunity to resolve target.host a second time.
        conn.sock = wire
        conn.request("GET", target.request_target, headers={
            "Host": target.host_header,
            "User-Agent": UA,
            "Accept-Encoding": "identity",
            "Connection": "close",
        })
        wire.settimeout(_remaining_timeout(timeout, deadline))
        return conn, conn.getresponse()
    except Exception:
        if conn is not None:
            conn.close()
        else:
            wire.close()
        raise


def _stream_to_file(resp, tmp, max_bytes, deadline, declared=None):
    """Copy the response body to `tmp`, bounded in both bytes and wall-clock.

    shutil.copyfileobj has no limit of either kind, and `--timeout` is a
    per-socket-operation timeout: a server dripping bytes indefinitely resets it
    on every chunk and never trips it.
    """
    # read1, not read: read(CHUNK) blocks until CHUNK bytes have accumulated, so
    # a server dripping one byte at a time would sit inside a single read for
    # hours and the deadline below would never be reached. read1 returns what
    # has arrived, which puts the check between every drip.
    read = getattr(resp, "read1", None) or resp.read
    total = 0
    with open(tmp, "wb") as fh:
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError("exceeded the wall-clock budget for this "
                                   f"download after {total} bytes")
            chunk = read(CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ValueError(f"response exceeds the {max_bytes}-byte cap "
                                 "(raise it with --max-bytes if intended)")
            fh.write(chunk)
    # `Content-Length` was used only as an upper bound, so a server that
    # announced 100 KB, sent 58 bytes and closed produced an `ok` result and a
    # corrupt PNG in the vault -- and a re-run was then refused as
    # already-present. A short read is a failed download, not a small image.
    if declared and total < declared:
        raise ValueError("truncated download: %d of %d declared bytes before "
                         "the connection closed" % (total, declared))
    return total


def _percent_decoded_chunks(text, start, deadline):
    """Yield bounded percent-decoded pieces without copying the whole payload."""
    pos = start
    while pos < len(text):
        if time.monotonic() > deadline:
            raise TimeoutError("exceeded the wall-clock budget while decoding data: URI")
        end = min(pos + CHUNK, len(text))
        if end < len(text):
            # Do not cut `%AB` across chunks. urllib intentionally leaves a
            # malformed percent escape literal; carrying only a possible
            # incomplete final triplet preserves that behavior.
            if text[end - 1] == "%":
                end -= 1
            elif end - pos >= 2 and text[end - 2] == "%":
                end -= 2
        if end <= pos:  # CHUNK is much larger than 3; defensive only.
            end = min(pos + 3, len(text))
        yield urllib.parse.unquote_to_bytes(text[pos:end])
        pos = end


def _write_bounded(fh, chunk, total, max_bytes, deadline):
    """Write one decoded data-URI chunk, enforcing byte and time limits."""
    if time.monotonic() > deadline:
        raise TimeoutError("exceeded the wall-clock budget while decoding data: URI")
    total += len(chunk)
    if total > max_bytes:
        raise ValueError(f"data: URI decodes over the {max_bytes}-byte cap")
    fh.write(chunk)
    return total


def _fetch_data_uri(url, tmp, max_bytes=DEFAULT_MAX_BYTES, deadline=None):
    # RFC 2397: `data:[<mediatype>][;<param>=<value>…][;base64],<data>` — the
    # mediatype may carry parameters, so the header is split at the FIRST
    # comma and read as `;`-tokens, with base64 mode decided by the LAST
    # token alone.  A regex admitting only a bare `;base64` refused
    # `data:image/png;charset=utf-8;base64,…` and the common inline-SVG form
    # `data:image/svg+xml;utf8,<svg…>` as malformed, so a legitimately
    # clipped image was reported failed.
    if deadline is None:
        deadline = time.monotonic() + DEFAULT_MAX_SECONDS
    comma = url.find(",")
    if url[:5].lower() != "data:" or comma < 0:
        raise ValueError("malformed data: URI")
    if comma > 4096:
        raise ValueError("data: URI media-type header is unreasonably large")
    header = url[5:comma]
    payload_start = comma + 1
    tokens = header.split(";")
    is_b64 = len(tokens) > 1 and tokens[-1].strip().lower() == "base64"
    mime = tokens[0].strip()
    payload_chars = len(url) - payload_start

    # Cheap exact preflight for the common unescaped, whitespace-free base64
    # form. Oversized input is rejected before base64 allocates its output.
    if is_b64 and url.find("%", payload_start) < 0 \
            and not any(url.find(ch, payload_start) >= 0 for ch in " \t\r\n\v\f") \
            and payload_chars % 4 == 0:
        padding = (2 if url.endswith("==") else 1 if url.endswith("=") else 0)
        decoded_size = payload_chars // 4 * 3 - padding
        if decoded_size > max_bytes:
            raise ValueError(
                f"data: URI decodes to {decoded_size} bytes, over the "
                f"{max_bytes}-byte cap")
    elif not is_b64 and payload_chars > max_bytes * 3:
        # A percent triplet is the most compact representation: three source
        # characters can produce no fewer than one decoded byte.
        raise ValueError(f"data: URI necessarily exceeds the {max_bytes}-byte cap")

    total = 0
    with open(tmp, "wb") as fh:
        if not is_b64:
            for raw in _percent_decoded_chunks(url, payload_start, deadline):
                total = _write_bounded(
                    fh, raw, total, max_bytes, deadline)
        else:
            carry = b""
            for raw in _percent_decoded_chunks(url, payload_start, deadline):
                clean = raw.translate(None, b" \t\r\n\v\f")
                data = carry + clean
                complete = len(data) // 4 * 4
                if complete >= 4:
                    complete -= 4  # padding, if any, belongs to the final quartet
                block, carry = data[:complete], data[complete:]
                if b"=" in block:
                    raise ValueError("invalid base64 data: padding before the end")
                if block:
                    try:
                        decoded = base64.b64decode(block, validate=True)
                    except binascii.Error as exc:
                        raise ValueError(f"invalid base64 data: {exc}") from exc
                    total = _write_bounded(
                        fh, decoded, total, max_bytes, deadline)
            try:
                decoded = base64.b64decode(carry, validate=True)
            except binascii.Error as exc:
                raise ValueError(f"invalid base64 data: {exc}") from exc
            total = _write_bounded(
                fh, decoded, total, max_bytes, deadline)
    return mime or None


def _lottie_json(raw, label):
    """Parse and minimally identify a Lottie animation JSON object."""
    try:
        animation = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid UTF-8 Lottie JSON: {exc}") from exc
    if not isinstance(animation, dict) or not isinstance(animation.get("layers"), list):
        raise ValueError(f"{label} is not a Lottie animation object (missing layers)")
    for field in ("w", "h", "fr"):
        value = animation.get(field)
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value <= 0):
            raise ValueError(
                f"{label} is not a Lottie animation object ({field} must be positive)")
    start, end = animation.get("ip", 0), animation.get("op")
    if (isinstance(start, bool) or isinstance(end, bool)
            or not isinstance(start, (int, float))
            or not isinstance(end, (int, float))
            or not math.isfinite(start) or not math.isfinite(end) or end <= start):
        raise ValueError(f"{label} is not a Lottie animation object (invalid frame range)")
    return animation


def _dotlottie_animation_path(manifest):
    """Return the manifest-selected animation path for dotLottie v1 or v2."""
    version = manifest.get("version") if isinstance(manifest, dict) else None
    if not isinstance(version, str) or version.split(".", 1)[0] not in ("1", "2"):
        raise ValueError("dotLottie manifest version must be 1 or 2")
    major = version.split(".", 1)[0]
    animations = manifest.get("animations")
    if not isinstance(animations, list) or not animations:
        raise ValueError(
            "invalid dotLottie manifest: animations must be a non-empty list")

    ids = []
    for item in animations:
        animation_id = item.get("id") if isinstance(item, dict) else None
        if (not isinstance(animation_id, str)
                or not re.fullmatch(r"[A-Za-z0-9._ -]+", animation_id)
                or animation_id in (".", "..")):
            raise ValueError("dotLottie animation id is missing or unsafe")
        if animation_id in ids:
            raise ValueError(f"duplicate dotLottie animation id {animation_id!r}")
        ids.append(animation_id)

    if major == "2":
        initial = manifest.get("initial")
        if initial is not None and not isinstance(initial, dict):
            raise ValueError("dotLottie v2 initial must be an object")
        selected = initial.get("animation") if initial else None
        directory = "a"
    else:
        selected = manifest.get("activeAnimationId")
        directory = "animations"
    if selected is not None and not isinstance(selected, str):
        raise ValueError("dotLottie initial animation id must be a string")
    selected = selected or ids[0]
    if selected not in ids:
        raise ValueError(
            f"dotLottie initial animation {selected!r} is not in the manifest")
    return f"{directory}/{selected}.json"


def _reject_duplicate_zip_members(archive):
    """Refuse a ZIP whose exact member names are not unique.

    ``ZipFile.getinfo(name)`` resolves through a one-entry-per-name mapping,
    while callers iterating ``infolist()`` can select a different occurrence.
    A duplicate manifest or selected animation would therefore let validation
    inspect different bytes from the renderer.  dotLottie needs neither form
    of ambiguity, so reject it before trusting any member.
    """
    seen = set()
    duplicates = set()
    for info in archive.infolist():
        if info.filename in seen:
            duplicates.add(info.filename)
        seen.add(info.filename)
    if duplicates:
        raise ValueError(
            "dotLottie ZIP contains duplicate member name(s): %s" %
            ", ".join(repr(name) for name in sorted(duplicates)))


def _validate_lottie_source(path, max_json_bytes):
    """Accept only Lottie JSON or a dotLottie ZIP containing bounded JSON."""
    if zipfile.is_zipfile(path):
        try:
            with zipfile.ZipFile(path) as archive:
                _reject_duplicate_zip_members(archive)
                manifest = next(
                    (info for info in archive.infolist()
                     if not info.is_dir() and info.filename == "manifest.json"),
                    None)
                if manifest is None:
                    raise ValueError(
                        "ZIP is not dotLottie: missing root manifest.json")
                if manifest.flag_bits & 0x1:
                    raise ValueError("dotLottie manifest is encrypted")
                if manifest.file_size > max_json_bytes:
                    raise ValueError("dotLottie manifest exceeds the size cap")
                with archive.open(manifest) as source:
                    manifest_raw = source.read(max_json_bytes + 1)
                if len(manifest_raw) > max_json_bytes:
                    raise ValueError("dotLottie manifest exceeds the size cap")
                try:
                    manifest_data = json.loads(manifest_raw.decode("utf-8-sig"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError(f"invalid dotLottie manifest: {exc}") from exc
                animation_path = _dotlottie_animation_path(manifest_data)
                try:
                    chosen = archive.getinfo(animation_path)
                except KeyError as exc:
                    raise ValueError(
                        f"dotLottie manifest references missing {animation_path!r}") from exc
                if chosen.is_dir():
                    raise ValueError(
                        f"dotLottie animation path {animation_path!r} is a directory")
                if chosen.flag_bits & 0x1:
                    raise ValueError("dotLottie animation JSON is encrypted")
                if chosen.file_size > max_json_bytes:
                    raise ValueError(
                        "expanded animation JSON exceeds the %d-byte cap" %
                        max_json_bytes)
                with archive.open(chosen) as source:
                    raw = source.read(max_json_bytes + 1)
                if len(raw) > max_json_bytes:
                    raise ValueError(
                        "expanded animation JSON exceeds the %d-byte cap" %
                        max_json_bytes)
        except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
            raise ValueError(f"invalid dotLottie archive: {exc}") from exc
        _lottie_json(raw, chosen.filename)
        return "dotlottie"

    with open(path, "rb") as source:
        raw = source.read(max_json_bytes + 1)
    if len(raw) > max_json_bytes:
        raise ValueError(
            f"animation JSON exceeds the {max_json_bytes}-byte cap")
    _lottie_json(raw, "source")
    return "json"


def _refuse_existing(attachments, slug, index, overwrite, extension=None,
                     owner=None, _published=None):
    """Refuse a figure slot that is already occupied, unless asked to overwrite.

    `shutil.move` onto an existing path replaces it with no error and no way
    back, so a re-run with the wrong `--start`, or a second article that slugs
    the same, silently destroyed the figures already filed under that name.
    `rename` has refused an occupied destination since it was written; this is
    the same rule on the download path, which had no such check at all.

    The slot is `<slug>_fig_<index>.*`, not one exact filename: the real type
    is only known after the bytes arrive, so checking the final path alone
    would still overwrite a `.webp` with a `.png` at the same index — the
    extension-twin this script exists to prevent, in reverse.

    The reprocess flow documented in references/images.md *does* want to
    replace a figure in place, so the capability is kept behind both explicit
    `--overwrite` and positive evidence from the exact clipping note that
    embeds the occupied filename.
    """
    owned = read_manifest(os.path.join(attachments, MANIFEST_FILE))
    prefix = _manifest_name_key(f"{slug}_fig_{index}.")
    for name in owned:
        if _manifest_name_key(name).startswith(prefix):
            raise ValueError(f"{name} is recorded in the PDF figure manifest — "
                             "clipping-processor cannot replace that producer's figure")
    hit = _glob_slug(attachments, slug, f"_fig_{index}.*")
    if overwrite:
        if owner is None and _published is None:
            raise ValueError("--owner-note is required with --overwrite")
        if owner is not None:
            _validate_clipping_owner(owner)
            for path in hit:
                _require_owned_attachment(owner, os.path.basename(path))
        # Replacing a PNG with a WebP at the same number would leave both on
        # disk, and consumers could not choose which is current. Keep the old
        # figure intact and require a fresh number when the format changes.
        if extension is not None:
            final = os.path.join(attachments, f"{slug}_fig_{index}.{extension}")
            if owner is not None:
                _require_owned_attachment(owner, os.path.basename(final))
            elif _published != os.path.basename(final):
                raise ValueError("internal publication evidence names the wrong figure")
            if any(not _same_file(path, final) for path in hit):
                raise ValueError(
                    "figure slot is occupied by a different filename or format: "
                    + ", ".join(os.path.basename(path) for path in hit)
                    + " — --overwrite replaces only the existing file; use "
                    "the next free index for a new format and update the embed")
        return
    if hit:
        raise ValueError(
            f"{os.path.basename(hit[0])} already exists in the attachments "
            "folder — refusing to overwrite it. Pass --overwrite if you are "
            "deliberately replacing this figure (a reprocess), or --start at "
            "the next free index if you are adding to the note.")


def _fetch_to_path(url, tmp, timeout, max_bytes, max_seconds, allow_private,
                   record=None):
    """Fetch `url` into `tmp` under every transport guard. -> (content_type, size)

    The scheme allowlist, single-resolution address pinning, redirect guard,
    `Content-Length` pre-check, byte cap, wall-clock deadline and truncation
    check live in one place. `download` and `fetch` are the same transport with
    different destinations; a second fetch implementation is a guard bypass.
    """
    _validate_transfer_limits(timeout, max_bytes, max_seconds)
    deadline = time.monotonic() + max_seconds
    target = _vetted_target(url, allow_private)
    if target is None:
        return (_fetch_data_uri(url, tmp, max_bytes, deadline),
                os.path.getsize(tmp))
    current_url = url
    for redirect_count in range(MAX_REDIRECTS + 1):
        conn, resp = _request_once(target, timeout, deadline)
        next_url = None
        try:
            status = resp.status
            if status in REDIRECT_STATUSES:
                location = resp.headers.get("Location")
                if not location:
                    raise urllib.error.HTTPError(
                        current_url, status, "redirect has no Location header",
                        resp.headers, None)
                if redirect_count >= MAX_REDIRECTS:
                    raise ValueError(
                        f"too many redirects (more than {MAX_REDIRECTS})")
                next_url = urllib.parse.urljoin(current_url, location)
            elif not 200 <= status < 300:
                raise urllib.error.HTTPError(
                    current_url, status,
                    "HTTP status is neither success nor a supported redirect",
                    resp.headers, None)
            else:
                content_type = resp.headers.get("Content-Type")
                if record is not None:
                    record["final_url"] = current_url
                declared = resp.headers.get("Content-Length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    raise ValueError(f"Content-Length {declared} exceeds the "
                                     f"{max_bytes}-byte cap")
                size = _stream_to_file(
                    resp, tmp, max_bytes, deadline,
                    int(declared) if declared and declared.isdigit() else None)
                return content_type, size
        finally:
            resp.close()
            conn.close()
        # The redirect connection is closed before DNS can block. Vet and
        # resolve its target before another request, without reading its body.
        next_target = _vetted_target(next_url, allow_private)
        if next_target is None:
            raise ValueError("an HTTP(S) redirect cannot target a data: URI")
        if target.scheme == "https" and next_target.scheme != "https":
            raise ValueError("refusing an HTTPS-to-HTTP redirect downgrade")
        current_url, target = next_url, next_target
    raise AssertionError("redirect loop exhausted without returning")


def download_one(url, attachments, slug, index, timeout=45,
                 max_bytes=DEFAULT_MAX_BYTES, max_seconds=DEFAULT_MAX_SECONDS,
                 allow_private=False, overwrite=False, owner_note=None,
                 require_vault=False):
    """Fetch one image and move it to <attachments>/<slug>_fig_<index>.<ext>."""
    result = {"index": index, "url": _report_url(url),
              "final_url": None, "ok": False, "path": None, "filename": None,
              "ext": None, "bytes": 0, "error": None}
    tmp = _temp_path()
    publication_handed_off = False
    try:
        validate_slug(slug)
        validate_index(index)
        owner = (_load_clipping_owner(owner_note, slug, attachments,
                                      require_vault=require_vault)
                 if (overwrite or require_vault) else None)
        # Before the fetch: no reason to spend a download on a slot we are
        # going to refuse to write. Re-checked after, against the real path.
        _refuse_existing(attachments, slug, index, overwrite, owner=owner)
        content_type, size = _fetch_to_path(
            url, tmp, timeout, max_bytes, max_seconds, allow_private, result)
        if size == 0:
            raise ValueError("empty response")
        with open(tmp, "rb") as fh:
            head = fh.read(4096)
        ext = sniff_extension(head, content_type, url)
        if ext is None:
            # Name what the BYTES were, not just what the header claimed: a
            # server that labels its 404 body `image/png` otherwise produces a
            # refusal quoting `image/png`, which reads like the script is wrong.
            raise ValueError("URL did not resolve to an image — the bytes look "
                             f"like {describe_bytes(head)} (Content-Type: "
                             f"{content_type or 'none'})")
        if ext == "svg":
            _validate_svg_file(tmp)
        os.makedirs(attachments, exist_ok=True)
        final = os.path.join(attachments, f"{slug}_fig_{index}.{ext}")
        _ensure_within(attachments, final)
        if owner is not None:
            _require_owned_attachment(owner, os.path.basename(final))
        _refuse_existing(attachments, slug, index, overwrite, ext, owner)
        publication_handed_off = True
        warning = _publish_file(
            tmp, final, overwrite,
            staging_parent=os.path.dirname(os.path.realpath(attachments)),
            before_publish=lambda: _refuse_existing(
                attachments, slug, index, overwrite, ext, owner),
            after_publish=lambda: _refuse_existing(
                attachments, slug, index, True, ext, owner,
                None if overwrite else os.path.basename(final)))
        result.update(ok=True, path=final, filename=os.path.basename(final),
                      ext=ext, bytes=size, content_type=content_type)
        if warning:
            result["warning"] = warning
    except Exception as exc:             # 404, timeout, unsupported scheme, non-image
        result["error"] = f"{type(exc).__name__}: {exc}"
        if publication_handed_off and os.path.lexists(tmp):
            result["scratch"] = tmp
    finally:
        if not publication_handed_off and os.path.exists(tmp):
            os.remove(tmp)
        if result.get("final_url"):
            result["final_url"] = _report_url(result["final_url"])
    return result


def fetch_source(url, out=None, timeout=45, max_bytes=DEFAULT_MAX_BYTES,
                 max_seconds=DEFAULT_MAX_SECONDS, allow_private=False,
                 overwrite=False, vault=None):
    """Download a Lottie JSON/dotLottie source under the transport guards.

    Lottie recovery needs the animation's `.json`/`.lottie` on disk
    before anything can render it, and that is not an image, so `download`
    cannot carry it. It used to be fetched by a bare `urllib.request.urlopen`
    inside a heredoc the model was told to write — which meant the one fetch in
    this skill that runs on a URL lifted straight out of a hostile page was
    also the one fetch with no scheme allowlist, no private-address refusal, no
    redirect re-check, no size cap and no wall-clock cap. This is
    `download_one`'s transport with a Lottie payload check in place of the image
    sniff. Arbitrary HTML, executables and unrelated archives are refused before
    an explicit output path can be published.

    The workflow must keep this source outside the vault. The default is a
    system temp file. An explicit `--out` requires the vault root and is
    refused when it resolves inside that vault. Getting the
    rendered result *into* `Sources/Images/` is `place_file`'s job, which is
    where the slug, containment and occupied-slot guards live.
    """
    result = {"url": _report_url(url),
              "final_url": None, "ok": False, "path": None, "bytes": 0,
              "content_type": None, "source_format": None, "error": None}
    tmp = _temp_path()
    publication_handed_off = False
    try:
        if out is not None:
            if vault is None:
                raise ValueError("an explicit --out requires --vault so the "
                                 "scratch path can be proved outside it")
            if not os.path.isdir(vault):
                raise ValueError("--vault is not a directory: %r" % vault)
            if _inside_existing_directory(out, vault):
                raise ValueError("--out must be outside --vault; Lottie source "
                                 "bytes are scratch material, not vault content")
        if out is not None and os.path.lexists(out) and not overwrite:
            raise ValueError(f"{out!r} already exists — refusing to overwrite "
                             "it (pass --overwrite if that is intended)")
        content_type, size = _fetch_to_path(
            url, tmp, timeout, max_bytes, max_seconds, allow_private, result)
        if size == 0:
            raise ValueError("empty response")
        source_format = _validate_lottie_source(tmp, max_bytes)
        if out is None:
            out, tmp = tmp, None
        else:
            publication_handed_off = True
            warning = _publish_file(tmp, out, overwrite, mode=0o600)
            if warning:
                result["warning"] = warning
        result.update(ok=True, path=os.path.abspath(out), bytes=size,
                      content_type=content_type, source_format=source_format)
    except Exception as exc:             # 404, timeout, unsupported scheme, cap
        result["error"] = f"{type(exc).__name__}: {exc}"
        if publication_handed_off and tmp is not None and os.path.lexists(tmp):
            result["scratch"] = tmp
    finally:
        if (not publication_handed_off and tmp is not None
                and os.path.exists(tmp)):
            try:
                os.remove(tmp)
            except OSError:
                pass
        if result.get("final_url"):
            result["final_url"] = _report_url(result["final_url"])
    return result


def place_file(src, attachments, slug, index, overwrite=False, owner_note=None,
               require_vault=False):
    """Move a locally produced image into <attachments>/<slug>_fig_<index>.<ext>.

    `download_one`'s placement half, for a file this script did not fetch — a
    GIF recovered from Lottie source is rendered separately. Every guard the
    download path applies to
    its own writes applies here: `validate_slug`, `_refuse_existing` (before
    and after), `_ensure_within`, and the byte sniff that picks the extension,
    so the caller's claimed filename decides nothing.

    It exists because the alternative was a rendering script doing its own
    `os.replace(tmp, out)` into `Sources/Images/`, which silently overwrote a
    previous run's GIF and exited 0 — and, since the folder is flat and shared
    by three skills, the file it replaced was not necessarily this skill's.

    The source is MOVED, not copied: it is a temp render, and a copy leaves the
    twin behind. A source already inside the attachments folder is refused —
    a half-written render must never sit in the vault (references/images.md
    item 4).
    """
    result = {"index": index, "source": src, "ok": False, "path": None,
              "filename": None, "ext": None, "bytes": 0, "error": None}
    try:
        validate_slug(slug)
        validate_index(index)
        owner = (_load_clipping_owner(owner_note, slug, attachments,
                                      require_vault=require_vault)
                 if (overwrite or require_vault) else None)
        if not os.path.isfile(src):
            raise ValueError(f"--from-file {src!r} is not a file")
        if _inside_existing_directory(src, attachments):
            raise ValueError(
                f"--from-file {src!r} is inside the attachments folder — "
                "render to a temp path outside the vault and place it from "
                "there, so nothing half-written ever appears in Sources/Images")
        if require_vault:
            for vault_root in _attachment_vault_roots(attachments):
                if _inside_existing_directory(src, vault_root):
                    raise ValueError(
                        f"--from-file {src!r} is inside the vault {vault_root!r} — "
                        "render to system scratch space outside the vault")
        _refuse_existing(attachments, slug, index, overwrite, owner=owner)
        # Sniff and size a stable private copy, then require publication to see
        # the same source snapshot. Without this tie, a renderer or cleanup
        # process could replace ``src`` after sniffing and a different byte
        # format would be published under the stale extension.
        with tempfile.TemporaryDirectory(prefix="clipping-place-check.") as check_dir:
            inspected = os.path.join(check_dir, "source")
            source_expected = _stable_regular_snapshot(
                src, copy_to=inspected, copy_mode=0o600)
            size = source_expected[3]
            if size == 0:
                raise ValueError("empty file")
            with open(inspected, "rb") as fh:
                head = fh.read(4096)
            # No Content-Type and no URL: a local file has only its bytes,
            # which is the evidence this script trusts anyway.
            ext = sniff_extension(head)
            if ext is None:
                raise ValueError("the file is not an image — the bytes look like "
                                 f"{describe_bytes(head)}")
            if ext == "svg":
                _validate_svg_file(inspected)
            os.makedirs(attachments, exist_ok=True)
            final = os.path.join(attachments, f"{slug}_fig_{index}.{ext}")
            _ensure_within(attachments, final)
            if owner is not None:
                _require_owned_attachment(owner, os.path.basename(final))
            _refuse_existing(attachments, slug, index, overwrite, ext, owner)
            warning = _publish_file(
                src, final, overwrite,
                staging_parent=os.path.dirname(os.path.realpath(attachments)),
                before_publish=lambda: _refuse_existing(
                    attachments, slug, index, overwrite, ext, owner),
                after_publish=lambda: _refuse_existing(
                    attachments, slug, index, True, ext, owner,
                    None if overwrite else os.path.basename(final)),
                expected_source=source_expected)
        result.update(ok=True, path=final, filename=os.path.basename(final),
                      ext=ext, bytes=size)
        if warning:
            result["warning"] = warning
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _same_file(a, b):
    """True when two paths are one file — a case-only rename on a case-insensitive
    volume (`teslo_…` → `Teslo_…`, the documented old-convention reprocess) looks
    like an existing destination but isn't one."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


#: Figure-label spellings only `pdf-figure-extractor` produces (CONVENTIONS
#: 8b): a supplementary marker, or a hierarchical `1-2` chapter label. This
#: skill writes plain integers, so a file carrying one of these under a stem
#: is a PDF's figure, not a clipping's.
#:
#: The separator is optional for the same reason `_FIG_GLOB` below is loose: a
#: vault predating the naming convergence (§8c) also holds files whose label
#: follows `_fig` with nothing in between, and a guard that only recognizes the
#: current spelling is a guard those files walk straight through.
_PDF_ONLY_LABEL = re.compile(r"_fig_?(?:S\d|SI\d|ED\d|\d+[.-]\d)", re.I)

#: §8a's CONSUMER glob: `<stem>_fig`, never `<stem>_fig_`, any extension.
#: `rename_slug` reads the folder as a consumer — it takes whatever is filed
#: under this note's stem — and the strict `_fig_*` it used to glob left every
#: pre-convergence figure (§8c: the ones whose number follows `_fig` with
#: nothing in between) behind under the OLD stem while reporting
#: `{"renamed": 3, "failed": 0}`: a stranded half-set nothing reports and no
#: re-run reassembles, because the next `rename` looks under the new stem.
#: `organize.py:294` and `paper_scan.figures_for` both match loosely;
#: this is the same rule. `_refuse_existing`'s strict `_fig_<N>.*` glob is a
#: different question — a PRODUCER checking the exact slot it is about to
#: write — and stays strict.
_FIG_GLOB = "_fig*"

# Consumer compatibility is a little wider than this producer's canonical
# outputs: old notes can still embed `.jpeg` and `.tif` spellings. The rename
# inventory must see those missing references even though a new download would
# publish their canonical `.jpg` / `.tiff` spelling.
_CONSUMER_IMAGE_EXTENSIONS = OUTPUT_EXTENSIONS | frozenset(("jpeg", "tif"))


def _embedded_figure_tail(filename, slug):
    """Return an old-slug image embed's loose ``_fig*`` tail, or ``None``.

    No directory entry exists for a missing attachment, so this is the
    string-only counterpart of ``_figure_stem_end``. Portable normalized name
    identity is conservative here: overlooking a missing embed would report a
    rename complete while the note still contains a broken old-stem reference.
    """
    _stem, extension = os.path.splitext(filename)
    if extension[1:].lower() not in _CONSUMER_IMAGE_EXTENSIONS:
        return None
    for index, char in enumerate(filename):
        if char != "_":
            continue
        tail = filename[index:]
        if (fnmatch.fnmatchcase(_manifest_name_key(tail), "_fig*")
                and _manifest_name_key(filename[:index])
                == _manifest_name_key(slug)):
            return tail
    return None


def _pdf_named(sources, slug):
    """Is there a `<slug>.pdf` under `sources`?  Cheap, read-only."""
    def failed(exc):
        raise ValueError("cannot verify PDF ownership in %r: %s" %
                         (exc.filename or sources, exc)) from exc

    key = _name_key(slug)
    seen = set()
    for root, dirs, files in os.walk(
            sources, followlinks=True, onerror=failed):
        dirs[:] = [name for name in dirs if not name.startswith(".")]
        try:
            item = os.stat(root)
        except OSError as exc:
            failed(exc)
        identity = (item.st_dev, item.st_ino)
        if identity in seen:
            dirs[:] = []
            continue
        seen.add(identity)
        for f in files:
            if not f.lower().endswith(".pdf"):
                continue
            stem, ext = os.path.splitext(f)
            if _name_key(stem) == key or _same_file(
                    os.path.join(root, f), os.path.join(root, slug + ext)):
                return True
    return False


def slug_occupancy(vault, slug):
    """Check the PDF and image namespaces that can already own ``slug``."""
    validate_slug(slug)
    vault = os.path.abspath(os.path.expanduser(os.fspath(vault)))
    if not os.path.isdir(vault):
        raise ValueError("--vault is not a directory: %r" % vault)
    sources = os.path.join(vault, "Sources", "PDFs")
    attachments = os.path.join(vault, "Sources", "Images")
    if os.path.lexists(sources) and not os.path.isdir(sources):
        raise ValueError("canonical Sources/PDFs path is not a directory: %r" % sources)
    if os.path.lexists(attachments) and not os.path.isdir(attachments):
        raise ValueError("canonical Sources/Images path is not a directory: %r" % attachments)
    pdf_occupied = _pdf_named(sources, slug) if os.path.isdir(sources) else False
    figures = [os.path.basename(path)
               for path in _glob_slug(attachments, slug, _FIG_GLOB)]
    return {"ok": not pdf_occupied and not figures,
            "vault": vault, "slug": slug,
            "pdf_stem_occupied": pdf_occupied,
            "image_occupants": figures}


#: What a refused member of the set does to the members that were fine.  A
#: figure set is renamed ALL OR NOTHING: the note's embeds are rewritten to one
#: slug, so a half-renamed set is a note where some embeds resolve and some do
#: not -- and neither slug holds the whole set, so no later run can tell which
#: half is which.
_STRADDLE = ("refused: this set is renamed all or nothing, and %s blocked it. "
             "Nothing was renamed. Resolve that one and re-run.")


def dependency_status(attachments, owner_note, old_slug):
    """Report external references that prevent retiring an old clipping stem."""
    validate_slug(old_slug, "--old-slug")
    owner = _load_clipping_owner(owner_note, old_slug, attachments,
                                 require_vault=True)
    image_names = sorted(
        (name for name in owner["embeds"]
         if _embedded_figure_tail(name, old_slug) is not None),
        key=lambda item: (_manifest_name_key(item), item))
    if owner["vault"] is None:
        raise ValueError("cannot infer a canonical vault from --owner-note and "
                         "--attachments; a complete Markdown dependency scan "
                         "cannot be certified")
    blockers = _vault_dependency_blockers(owner, old_slug, image_names)
    _validate_clipping_owner(owner)
    return {"ok": not blockers, "vault": os.path.abspath(owner["vault"]),
            "old_slug": old_slug, "images": image_names,
            "blockers": blockers}


def rename_slug(attachments, old_slug, new_slug, dry_run=False, *, sources,
                owner_note=None, require_vault=False,
                _allow_dependencies=False, _allow_prepared=False):
    """Rename every <old_slug>_fig_N.<ext> attachment to the new slug.

    **All or nothing.** The whole set is planned first, and if any member is
    refused nothing is renamed at all; a rename that fails part-way is rolled
    back. This used to rename file by file, so a destination that already
    existed at `_fig_2` stopped the loop's second iteration with `_fig_1`
    already moved: the note's embeds all point at one slug, so half of them
    then resolved to nothing, and the figures were split across two stems where
    no re-run could reassemble them — `rename` would refuse the collision
    again, forever, and the report said "1 renamed, 1 failed" as if that were a
    partial success.

    An existing destination is refused, not overwritten. This runs on the
    reprocess path, where a corrected author or year turns one slug into
    another that may already own figures in Sources/Images/ — os.rename would
    replace those files with no error and no way back.

    The glob is §8a's loose `<stem>_fig*`, not `<stem>_fig_*`. This side of the
    script is a CONSUMER — it moves whatever is filed under the note's stem —
    and a vault holds figures written before the two producers agreed on the
    separator (§8c). The strict form matched `X_fig_1.png` and skipped the
    separator-less file sitting right beside it, then reported
    `{"renamed": 3, "failed": 0}`: the note's embeds all moved to the new stem
    while part of its figure set stayed at the old one, unmentioned.

    `Sources/Images/` is FLAT and shared: the same stem can belong to a PDF
    whose figures `pdf-figure-extractor` wrote. Globbing the stem and renaming
    what comes back moved three of those out from under a summary note whose
    embeds then resolved to nothing. Two guards, both cheap: a label spelling
    only the other producer writes, and the required `sources` inventory, where
    a PDF of that stem settles ownership outright. A PDF-only label is a
    refusal for the WHOLE set, not just that file: it is evidence that the
    other producer owns this stem, and the plain-integer figures beside it are
    then just as likely to be its. The remaining candidates still are not
    inferred to be clipping figures: every basename must be an exact rendered
    embed in the snapshotted ``Articles/<old_slug>.md`` passed as
    ``owner_note``.
    """
    validate_slug(old_slug, "--old-slug")
    validate_slug(new_slug, "--new-slug")
    if (_allow_dependencies or _allow_prepared) and not dry_run:
        raise ValueError("internal prepared-handoff allowances are planning-only")
    if sources is None:
        raise ValueError("--sources is required for every rename so PDF-owned "
                         "figures cannot be mistaken for clipping images")
    if not os.path.isdir(sources):
        raise ValueError("--sources is not a directory: %r — cannot verify PDF ownership" % sources)
    if sources and _pdf_named(sources, old_slug):
        return [{"from": old_slug + "_fig_*", "to": None, "ok": False,
                 "error": "refusing to rename: %s.pdf exists in %s, so these "
                          "figures belong to that document and are "
                          "pdf-organizer's to move, not this skill's"
                          % (old_slug, sources)}]
    if sources and _pdf_named(sources, new_slug):
        return [{"from": old_slug + "_fig_*", "to": new_slug + "_fig_*", "ok": False,
                 "error": "refusing to rename: the destination stem %s belongs "
                          "to a PDF in %s; choose an unused clipping slug"
                          % (new_slug, sources)}]
    owner = _load_clipping_owner(owner_note, old_slug, attachments,
                                 require_vault=require_vault)
    owned = {_manifest_name_key(name)
             for name in read_manifest(os.path.join(attachments, MANIFEST_FILE))}
    # --- plan: every member is judged before any of them is touched ---------
    # every Unicode spelling of the old slug: on macOS the on-disk files are
    # often NFD while the argument is NFC, and glob compares bytes.
    plan = []
    for src in _glob_slug(attachments, old_slug, _FIG_GLOB):
        base = os.path.basename(src)
        # the matched spelling's length, not the argument's — NFC and NFD
        # spellings of one slug differ in length.
        stem_end = _figure_stem_end(attachments, base, old_slug, _FIG_GLOB)
        if stem_end is None:  # `_glob_slug` established this; keep failure explicit.
            raise ValueError("could not locate the matched figure stem in %r" % base)
        # Everything after the stem is carried across verbatim, separator
        # included, so a file written before the spellings converged keeps its
        # own label under the new stem and stays with its set, rather than
        # being re-spelled into the current convention by a rename.
        tail = base[stem_end:]
        dst = os.path.join(attachments, new_slug + tail)
        destination_prefix = _manifest_name_key(
            os.path.splitext(os.path.basename(dst))[0]) + "."
        destination_slot = _glob_slug(
            attachments, new_slug, glob.escape(os.path.splitext(tail)[0]) + ".*")
        entry = {"from": base, "to": os.path.basename(dst), "ok": False,
                 "error": None}
        if dry_run:
            entry["dry_run"] = True
        if _manifest_name_key(base) in owned:
            entry["error"] = "recorded in the PDF figure manifest; not this skill's to rename"
        elif any(name.startswith(destination_prefix) for name in owned):
            entry["error"] = "destination is recorded in the PDF figure manifest"
        elif _PDF_ONLY_LABEL.search(tail):
            entry["error"] = ("label spelling only pdf-figure-extractor "
                              "writes; this file is a PDF's figure, not this "
                              "note's")
        elif sum(_manifest_name_key(name) == _manifest_name_key(base)
                 for name in owner["embeds"]) != 1:
            entry["error"] = ("not a unique portable rendered filename-only "
                              "embed in %s; ownership is unproven" % owner["path"])
        elif not os.path.lexists(src):
            entry["error"] = "source missing"
        elif os.path.islink(src) or not os.path.isfile(src):
            entry["error"] = "source is not a regular image file"
        # lexists, not exists: a broken symlink at dst is still something there.
        elif any(not _same_file(src, path) for path in destination_slot) \
                or (os.path.lexists(dst) and not _same_file(src, dst)):
            prepared = False
            if (_allow_prepared and len(destination_slot) == 1
                    and _manifest_name_key(os.path.basename(destination_slot[0]))
                    == _manifest_name_key(os.path.basename(dst))):
                try:
                    old_snapshot = _stable_regular_snapshot(src)
                    new_snapshot = _stable_regular_snapshot(dst)
                    prepared = old_snapshot[1:] == new_snapshot[1:]
                except (OSError, UnicodeError, ValueError):
                    prepared = False
            if not prepared:
                entry["error"] = ("destination exists (the figure slot includes "
                                  "every extension)")
        else:
            try:
                _ensure_within(attachments, src)
                _ensure_within(attachments, dst)
            except ValueError as exc:
                entry["error"] = f"{type(exc).__name__}: {exc}"
        plan.append((src, dst, entry))

    # The folder walk above proves which files exist; the note supplies the
    # inverse inventory. Without this pass a missing embedded attachment is
    # silently omitted, and an empty folder misleadingly reports a successful
    # empty rename even though the old note already has a broken figure.
    existing = {_manifest_name_key(os.path.basename(src))
                for src, _dst, _entry in plan}
    for base in sorted(owner["embeds"], key=lambda item: (
            _manifest_name_key(item), item)):
        tail = _embedded_figure_tail(base, old_slug)
        if tail is None or _manifest_name_key(base) in existing:
            continue
        entry = {
            "from": base,
            "to": new_slug + tail,
            "ok": False,
            "error": ("owner note embeds this old-slug image, but the exact "
                      "attachment is missing; restore it or replace the note "
                      "embed with the documented missing-attachment placeholder "
                      "before renaming"),
        }
        if dry_run:
            entry["dry_run"] = True
        plan.append((os.path.join(attachments, base),
                     os.path.join(attachments, new_slug + tail), entry))

    # A changed stem retires both attachment names and, after publication, the
    # old Articles path. Other vault notes can depend on either. Clipping
    # processor does not have authority to rewrite unrelated Markdown, so a
    # complete canonical-vault scan must refuse the image mutation before it
    # makes those references dangle. The same scan is repeated around each
    # move below so a reference added after planning triggers rollback.
    dependency_images = sorted({
        os.path.basename(src) for src, _dst, _entry in plan
    } | {
        name for name in owner["embeds"]
        if _embedded_figure_tail(name, old_slug) is not None
    }, key=lambda item: (_manifest_name_key(item), item))
    # Path retirement is about the exact directory-entry spelling. NFD and NFC
    # can coexist on a case-sensitive filesystem even though portable matching
    # correctly treats them as one namespace for collision/ownership checks.
    changed_slug = old_slug != new_slug
    dependency_blockers = (_vault_dependency_blockers(
        owner, old_slug, dependency_images) if changed_slug else [])
    dependency_errors = [row for row in dependency_blockers if row.get("error")]
    if dependency_blockers and (not _allow_dependencies or dependency_errors):
        error = _dependency_error(dependency_blockers)
        if not plan:
            entry = {"from": old_slug + ".md", "to": new_slug + ".md",
                     "ok": False, "error": error,
                     "dependency_blockers": dependency_blockers}
            if dry_run:
                entry["dry_run"] = True
            plan.append((None, None, entry))
        else:
            for _src, _dst, entry in plan:
                entry["dependency_blockers"] = dependency_blockers
                if not entry["error"]:
                    entry["error"] = error

    identities = {}
    for src, _dst, entry in plan:
        if entry["error"]:
            continue
        try:
            identities[src] = file_identity(src)
        except OSError as exc:
            entry["error"] = ("source changed while the rename was being "
                              "planned (%s: %s)" %
                              (type(exc).__name__, exc))

    _validate_clipping_owner(owner)
    blocked = [e for _s, _d, e in plan if e["error"]]
    if blocked:
        for _src, _dst, entry in plan:
            if not entry["error"]:
                entry["error"] = _STRADDLE % blocked[0]["from"]
        return [e for _s, _d, e in plan]
    if dry_run:
        for _src, _dst, entry in plan:
            entry["ok"] = True
        return [e for _s, _d, e in plan]

    done = []
    for src, dst, entry in plan:
        try:
            _validate_clipping_owner(owner)
            if changed_slug:
                blockers = _vault_dependency_blockers(
                    owner, old_slug, dependency_images)
                if blockers:
                    entry["dependency_blockers"] = blockers
                    raise ValueError(_dependency_error(blockers))
            stage_parent = os.path.dirname(os.path.realpath(attachments))
            move_noreplace(src, dst, expected=identities[src],
                           stage_parent=stage_parent)
            entry["ok"] = os.path.lexists(dst)
            done.append((src, dst, entry))
            _validate_clipping_owner(owner)
            if changed_slug:
                blockers = _vault_dependency_blockers(
                    owner, old_slug, dependency_images)
                if blockers:
                    entry["dependency_blockers"] = blockers
                    raise ValueError(_dependency_error(blockers))
        except (OSError, ValueError) as exc:
            # Put back what has already moved, so the set is still whole under
            # one slug and the re-run after the fix is the same operation.
            if isinstance(exc, MoveIncomplete):
                entry["error"] = ("MOVE INCOMPLETE — both paths must be "
                                  "inspected before retrying: %s" % exc)
            else:
                entry["error"] = f"{type(exc).__name__}: {exc}"
            for back_src, back_dst, back_entry in reversed(done):
                try:
                    move_noreplace(
                        back_dst, back_src, expected=identities[back_src],
                        stage_parent=os.path.dirname(os.path.realpath(attachments)))
                    back_entry["ok"] = False
                    if back_entry is not entry:
                        back_entry["error"] = _STRADDLE % os.path.basename(src)
                except OSError as back:
                    back_entry["error"] = ("ROLLBACK INCOMPLETE (%s) — inspect "
                                           "both its old and new paths; neither "
                                           "was overwritten" % back)
            for _s2, _d2, other in plan:
                if not other["ok"] and not other["error"]:
                    other["error"] = _STRADDLE % os.path.basename(src)
            return [e for _s, _d, e in plan]
    return [e for _s, _d, e in plan]


def _handoff_plan(attachments, sources, owner_note, new_owner_note,
                  old_slug, new_slug):
    """Validate one two-owner image mapping without changing either set."""
    if old_slug == new_slug:
        raise ValueError("a two-phase handoff requires two distinct slug spellings")
    results = rename_slug(
        attachments, old_slug, new_slug, True, sources=sources,
        owner_note=owner_note, require_vault=True,
        _allow_dependencies=True, _allow_prepared=True)
    failed = [row for row in results if not row.get("ok")]
    if failed:
        raise ValueError("image handoff preflight failed: " + "; ".join(
            "%s (%s)" % (row.get("from"), row.get("error"))
            for row in failed))

    old_owner = _load_clipping_owner(
        owner_note, old_slug, attachments, require_vault=True)
    new_owner = _load_clipping_owner(
        new_owner_note, new_slug, attachments, require_vault=True)
    if old_owner["origin"] != new_owner["origin"]:
        raise ValueError("old and new owner notes do not have the same normalized "
                         "web origin")
    try:
        if os.path.samefile(old_owner["path"], new_owner["path"]):
            raise ValueError("old and new owner notes resolve to the same file; "
                             "a two-phase handoff needs both paths live")
    except FileNotFoundError as exc:
        raise ValueError("both old and new owner notes must remain present") from exc

    mapping = []
    for row in results:
        old_name, new_name = row["from"], row["to"]
        old_path = os.path.join(attachments, old_name)
        new_path = os.path.join(attachments, new_name)
        if _same_file(old_path, new_path):
            raise ValueError("%s and %s resolve to the same file; use the ordinary "
                             "case-only rename path" % (old_name, new_name))
        if sum(_manifest_name_key(name) == _manifest_name_key(old_name)
               for name in old_owner["embeds"]) != 1:
            raise ValueError("%s is no longer a unique rendered filename-only "
                             "embed in the old owner note %s" %
                             (old_name, old_owner["path"]))
        if sum(_manifest_name_key(name) == _manifest_name_key(new_name)
               for name in new_owner["embeds"]) != 1:
            raise ValueError("%s is not a unique rendered filename-only embed in "
                             "the new owner note %s" %
                             (new_name, new_owner["path"]))
        if any(_manifest_name_key(name) == _manifest_name_key(old_name)
               for name in new_owner["embeds"]):
            raise ValueError("the new owner note still embeds old image %s" % old_name)
        mapping.append({"from": old_name, "to": new_name})

    dependency = dependency_status(attachments, owner_note, old_slug)
    incomplete = [row for row in dependency["blockers"] if row.get("error")]
    if incomplete:
        raise ValueError(_dependency_error(incomplete))
    _validate_clipping_owner(old_owner)
    _validate_clipping_owner(new_owner)
    return old_owner, new_owner, mapping, dependency


def _rollback_new_publications(published, stage, stage_parent):
    """Withdraw only new-name copies this prepare call published."""
    failures = []
    for index, (path, expected) in enumerate(reversed(published), 1):
        rollback = os.path.join(stage, "rollback-new-%d" % index)
        try:
            os.mkdir(rollback)
            remove_expected(
                path, expected, _stable_regular_snapshot, rollback,
                stage_parent=stage_parent,
                recovery_prefix=".clipping-handoff-recovery-")
        except (OSError, UnicodeError, ValueError) as exc:
            failures.append("%s (%s)" % (path, exc))
    return failures


def prepare_slug_rename(attachments, old_slug, new_slug, *, sources,
                        owner_note, new_owner_note, dry_run=False):
    """Publish verified new-name image copies while retaining every old name."""
    old_owner, new_owner, mapping, dependency = _handoff_plan(
        attachments, sources, owner_note, new_owner_note, old_slug, new_slug)
    rows = []
    for item in mapping:
        src = os.path.join(attachments, item["from"])
        dst = os.path.join(attachments, item["to"])
        action = "already-prepared" if os.path.lexists(dst) else (
            "would-copy" if dry_run else "copy")
        rows.append(dict(item, ok=True, action=action))
    if dry_run:
        return {"ok": True, "phase": "prepare", "old_slug": old_slug,
                "new_slug": new_slug, "mapping": mapping,
                "dependency": dependency, "results": rows,
                "prepared": 0}

    stage_parent = os.path.dirname(os.path.realpath(attachments))
    stage = tempfile.mkdtemp(prefix=".clipping-handoff-prepare-",
                             dir=stage_parent)
    published = []
    try:
        for index, (item, row) in enumerate(zip(mapping, rows), 1):
            src = os.path.join(attachments, item["from"])
            dst = os.path.join(attachments, item["to"])
            _validate_clipping_owner(old_owner)
            _validate_clipping_owner(new_owner)
            current = dependency_status(attachments, owner_note, old_slug)
            incomplete = [blocker for blocker in current["blockers"]
                          if blocker.get("error")]
            if incomplete:
                raise ValueError(_dependency_error(incomplete))

            old_mode = stat.S_IMODE(os.lstat(src).st_mode)
            old_snapshot = _stable_regular_snapshot(src)
            if os.path.lexists(dst):
                new_snapshot = _stable_regular_snapshot(dst)
                if old_snapshot[1:] != new_snapshot[1:]:
                    raise ValueError("prepared destination %s is not byte-for-byte "
                                     "and mode-identical to %s" % (dst, src))
                row["action"] = "already-prepared"
            else:
                staged = os.path.join(stage, "image-%d" % index)
                copied = _stable_regular_snapshot(
                    src, copy_to=staged, copy_mode=old_mode)
                if copied != old_snapshot:
                    raise ValueError("%s changed while its handoff copy was staged"
                                     % src)
                published_snapshot = publish_new(
                    staged, dst, _stable_regular_snapshot, stage_parent,
                    recovery_prefix=".clipping-handoff-recovery-")
                published.append((dst, published_snapshot))
                if (_stable_regular_snapshot(src) != old_snapshot
                        or _stable_regular_snapshot(dst)[1:] != old_snapshot[1:]):
                    raise ValueError("the published handoff copy of %s could not be "
                                     "verified against its old source" % item["from"])
                row["action"] = "copied"
            row["sha256"] = old_snapshot[1]
            row["bytes"] = old_snapshot[3]

        _validate_clipping_owner(old_owner)
        _validate_clipping_owner(new_owner)
        dependency = dependency_status(attachments, owner_note, old_slug)
        incomplete = [blocker for blocker in dependency["blockers"]
                      if blocker.get("error")]
        if incomplete:
            raise ValueError(_dependency_error(incomplete))
    except BaseException as exc:
        failures = _rollback_new_publications(published, stage, stage_parent)
        if failures:
            raise ValueError(
                "image handoff preparation failed (%s); rollback was incomplete. "
                "Preserve and inspect %s and: %s" %
                (exc, stage, "; ".join(failures))) from exc
        shutil.rmtree(stage, ignore_errors=True)
        raise
    shutil.rmtree(stage, ignore_errors=True)
    return {"ok": True, "phase": "prepare", "old_slug": old_slug,
            "new_slug": new_slug, "mapping": mapping,
            "dependency": dependency, "results": rows,
            "prepared": sum(row["action"] == "copied" for row in rows)}


def _restore_retired_images(retired, stage_parent):
    """Restore conditionally retired old images; retain stages on any conflict."""
    failures = []
    for src, expected, stage in reversed(retired):
        displaced = os.path.join(stage, ".atomic-displaced")
        try:
            if _stable_regular_snapshot(displaced) != expected:
                raise ValueError("private retired snapshot changed")
            if os.path.lexists(src):
                if _stable_regular_snapshot(src) != expected:
                    raise ValueError("public old-image path was reoccupied by a "
                                     "different file")
                # remove_expected can detect a late conflict after it has
                # already restored the expected public inode. Its retained
                # private hard link is cleanup state, not an unrestored image.
                continue
            move_noreplace(
                displaced, src, expected=file_identity(displaced),
                stage_parent=stage_parent)
            if _stable_regular_snapshot(src) != expected:
                raise ValueError("restored public image differs from its snapshot")
        except (OSError, UnicodeError, ValueError) as exc:
            failures.append("%s (recovery stage %s: %s)" % (src, stage, exc))
    if not failures:
        for _src, _expected, stage in retired:
            shutil.rmtree(stage, ignore_errors=True)
    return failures


def finalize_slug_rename(attachments, old_slug, new_slug, *, sources,
                         owner_note, new_owner_note, dry_run=False):
    """Retire only exact old images after every old dependency has disappeared."""
    old_owner, new_owner, mapping, dependency = _handoff_plan(
        attachments, sources, owner_note, new_owner_note, old_slug, new_slug)
    if not dependency["ok"]:
        raise ValueError(_dependency_error(dependency["blockers"]))

    snapshots = []
    rows = []
    for item in mapping:
        src = os.path.join(attachments, item["from"])
        dst = os.path.join(attachments, item["to"])
        old_snapshot = _stable_regular_snapshot(src)
        new_snapshot = _stable_regular_snapshot(dst)
        if old_snapshot[1:] != new_snapshot[1:]:
            raise ValueError("%s is not the verified byte-identical prepared copy "
                             "of %s" % (dst, src))
        snapshots.append((src, dst, old_snapshot, new_snapshot))
        rows.append(dict(item, ok=True,
                         action="would-retire" if dry_run else "retire",
                         sha256=old_snapshot[1], bytes=old_snapshot[3]))
    if dry_run:
        return {"ok": True, "phase": "finalize", "old_slug": old_slug,
                "new_slug": new_slug, "mapping": mapping,
                "dependency": dependency, "results": rows, "retired": 0}

    stage_parent = os.path.dirname(os.path.realpath(attachments))
    retired = []
    try:
        for src, dst, old_snapshot, new_snapshot in snapshots:
            _validate_clipping_owner(old_owner)
            _validate_clipping_owner(new_owner)
            current = dependency_status(attachments, owner_note, old_slug)
            if not current["ok"]:
                raise ValueError(_dependency_error(current["blockers"]))
            if (_stable_regular_snapshot(src) != old_snapshot
                    or _stable_regular_snapshot(dst) != new_snapshot):
                raise ValueError("an old or new image changed after finalization "
                                 "preflight")
            stage = tempfile.mkdtemp(prefix=".clipping-handoff-retire-",
                                     dir=stage_parent)
            try:
                removed = remove_expected(
                    src, old_snapshot, _stable_regular_snapshot, stage,
                    stage_parent=stage_parent,
                    recovery_prefix=".clipping-handoff-recovery-")
            except BaseException:
                if os.path.lexists(os.path.join(stage, ".atomic-displaced")):
                    retired.append((src, old_snapshot, stage))
                else:
                    shutil.rmtree(stage, ignore_errors=True)
                raise
            if not removed:
                shutil.rmtree(stage, ignore_errors=True)
                raise ValueError("old image disappeared before retirement: %s" % src)
            retired.append((src, old_snapshot, stage))
            if _stable_regular_snapshot(dst) != new_snapshot:
                raise ValueError("new image changed while its old duplicate was "
                                 "being retired: %s" % dst)
            current = dependency_status(attachments, owner_note, old_slug)
            if not current["ok"]:
                raise ValueError(_dependency_error(current["blockers"]))

        _validate_clipping_owner(old_owner)
        _validate_clipping_owner(new_owner)
        dependency = dependency_status(attachments, owner_note, old_slug)
        if not dependency["ok"]:
            raise ValueError(_dependency_error(dependency["blockers"]))
        for _src, dst, _old_snapshot, new_snapshot in snapshots:
            if _stable_regular_snapshot(dst) != new_snapshot:
                raise ValueError("new image changed before finalization completed: %s"
                                 % dst)
    except BaseException as exc:
        failures = _restore_retired_images(retired, stage_parent)
        if failures:
            raise ValueError(
                "image handoff finalization failed (%s); rollback was incomplete. "
                "Preserve every public image and: %s" %
                (exc, "; ".join(failures))) from exc
        raise
    for _src, _expected, stage in retired:
        shutil.rmtree(stage, ignore_errors=True)
    for row in rows:
        row["action"] = "retired"
    return {"ok": True, "phase": "finalize", "old_slug": old_slug,
            "new_slug": new_slug, "mapping": mapping,
            "dependency": dependency, "results": rows,
            "retired": len(rows)}


class _FakeResponse:
    """Just enough of an `http.client.HTTPResponse` for `_stream_to_file`.

    The download path is exercised WITHOUT a socket: this is the only way to
    test the byte cap, the wall-clock deadline and the truncation check at all,
    since each of them needs a server that misbehaves in a specific way, and a
    self-test that reaches the network is a self-test that fails on a train.
    `read` raises rather than returning data, because the choice of `read1` is
    load-bearing (a server dripping one byte at a time never returns from a
    `read(CHUNK)`, so the deadline below it is never reached).
    """

    def __init__(self, chunks, headers=None, status=200, reason="OK"):
        self._chunks = list(chunks)
        self.headers = dict(headers or {})
        self.status = status
        self.reason = reason
        self.read_count = 0
        self.closed = False

    def read1(self, _n=None):
        self.read_count += 1
        return self._chunks.pop(0) if self._chunks else b""

    def read(self, _n=None):
        raise AssertionError("_stream_to_file must read1(), not read()")

    def close(self):
        self.closed = True


class _FakeConnection:
    """Connection lifetime probe for offline redirect transport tests."""

    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


#: The smallest valid PNG, for the paths that need real image bytes.
_PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
        b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


def run_self_test():
    """The guards, run against the inputs they exist to refuse.

    Everything here is offline. The scheme and private-host guards are called
    directly, the streaming limits are driven by `_FakeResponse`, and the one
    end-to-end download is a `data:` URI, which opens no socket. Nothing is
    written outside a temp directory, which is removed on the way out.
    """
    from unittest.mock import PropertyMock, patch

    cases = []

    def check(label, got, want):
        cases.append((label, got == want, got, want))

    def raises(label, fn, *a, **kw):
        """A guard is only a guard if it refuses; record WHAT it refused with."""
        try:
            fn(*a, **kw)
        except (ValueError, TypeError, TimeoutError, urllib.error.HTTPError,
                argparse.ArgumentTypeError) as exc:
            cases.append((label, True, type(exc).__name__, "refused"))
            return str(exc)
        except Exception as exc:                       # noqa: BLE001
            cases.append((label, False, "%s: %s" % (type(exc).__name__, exc),
                          "refused"))
            return ""
        cases.append((label, False, "accepted", "refused"))
        return ""

    phase_stderr = io.StringIO()
    try:
        with contextlib.redirect_stderr(phase_stderr):
            main([
                "rename", "--attachments", "unused-images",
                "--sources", "unused-pdfs", "--owner-note", "unused.md",
                "--old-slug", "Old_Slug_2025",
                "--new-slug", "New_Slug_2026",
            ])
        missing_phase_exit = None
    except SystemExit as exc:
        missing_phase_exit = exc.code
    check("rename CLI refuses an omitted phase before touching paths",
          (missing_phase_exit, "--phase" in phase_stderr.getvalue()),
          (2, True))

    # --- sniff_extension: bytes beat Content-Type beat the URL --------------
    exercised_extensions = set()
    for label, head, ct, url, want in (
            ("PNG magic", _PNG, None, None, "png"),
            ("JPEG magic", b"\xff\xd8\xff\xe0JFIF", None, None, "jpg"),
            ("GIF87a", b"GIF87a\x01\x00", None, None, "gif"),
            ("GIF89a", b"GIF89a\x01\x00", None, None, "gif"),
            ("WEBP", b"RIFF\x24\x00\x00\x00WEBPVP8 ", None, None, "webp"),
            ("AVIF", b"\x00\x00\x00 ftypavif\x00\x00", None, None, "avif"),
            ("AVIF with a generic MIAF major brand",
             b"\x00\x00\x00\x1cftypmif1\x00\x00\x00\x00avifmif1", None,
             None, "avif"),
            ("BMP", b"BM\x36\x00", None, None, "bmp"),
            ("SVG, xml declaration first", b"<?xml version='1.0'?>\n<svg />",
             None, None, "svg"),
            ("SVG, bare root", b"<svg xmlns='...'></svg>", None, None, "svg"),
            # the disagreement cases: the bytes are the truth
            ("PNG bytes, jpeg Content-Type", _PNG, "image/jpeg", None, "png"),
            ("PNG bytes, .jpg URL", _PNG, None, "http://x/a.jpg", "png"),
            ("PNG bytes, text/html Content-Type", _PNG, "text/html",
             "http://x/a", "png"),
            # No recognized image bytes: neither header nor URL can rescue it.
            ("Content-Type png", b"\x00\x01\x02\x03", "image/png", None, None),
            ("Content-Type with a charset", b"\x00\x01", "image/png; charset=x",
             None, None),
            ("Content-Type jpeg without JPEG bytes", b"\x00\x01", "image/jpeg",
             None, None),
            ("Content-Type uppercase", b"\x00\x01", "IMAGE/PNG", None, None),
            ("unmapped image/*, URL extension", b"\x00\x01", "image/tiff",
             "http://x/a.tiff", None),
            ("unmapped image/*, no URL", b"\x00\x01", "image/heif", None, None),
            ("octet-stream, .png URL", b"\x00\x01", "application/octet-stream",
             "http://x/a.png", None),
            ("octet-stream, .jpeg URL", b"\x00\x01",
             "application/octet-stream", "http://x/a.jpeg", None),
            ("octet-stream, uppercase URL extension", b"\x00\x01",
             "application/octet-stream", "http://x/A.PNG", None),
            ("octet-stream, URL extension behind a query", b"\x00\x01",
             "application/octet-stream", "http://x/a.webp?w=800", None),
            ("octet-stream, no usable URL extension", b"\x00\x01",
             "application/octet-stream", "http://x/a", None),
            ("no Content-Type, no extension", b"\x00\x01", None, "http://x/a",
             None),
            # NOT images: a failure, so the model writes the documented
            # placeholder instead of embedding something Obsidian cannot render
            ("an HTML error page", b"<!DOCTYPE html><html>", "text/html",
             "http://x/a.png", None),
            ("an HTML page with no doctype", b"<html><body>nope",
             "text/html", "http://x/a.png", None),
            ("a JSON error body", b'{"error": "not found"}',
             "application/json", "http://x/a.png", None),
            ("a PDF", b"%PDF-1.7\n", "application/pdf", "http://x/a.png", None),
            ("plain text", b"nope", "text/plain", "http://x/a.png", None),
            # --- the LYING `image/*` header ---------------------------------
            # A mapped image/* Content-Type used to win outright, so every one
            # of these was written into Sources/Images as a .png and reported
            # `"ok": true, "failed": 0` — the exact thing SKILL.md's "never
            # writes a non-image into the vault" promises cannot happen.
            ("a JSON body served as image/png", b'{"error": "not found"}',
             "image/png", "http://x/a.png", None),
            ("plain text served as image/png", b"nope, not an image",
             "image/png", "http://x/a.png", None),
            ("a PDF served as image/jpeg", b"%PDF-1.7\n%\xc7\xec\x8f\xa2",
             "image/jpeg", "http://x/a.jpg", None),
            ("a ZIP served as image/png", b"PK\x03\x04\x14\x00\x00\x00\x08\x00",
             "image/png", "http://x/a.png", None),
            ("an ELF binary served as image/png", b"\x7fELF\x02\x01\x01\x00",
             "image/png", "http://x/a.png", None),
            ("a gzip stream served as image/webp", b"\x1f\x8b\x08\x00\x00\x00",
             "image/webp", None, None),
            ("a Windows executable served as image/gif", b"MZ\x90\x00\x03\x00",
             "image/gif", None, None),
            ("an mp4 served as image/gif", b"\x00\x00\x00 ftypisom\x00\x00\x02\x00",
             "image/gif", None, None),
            # HTML the old `startswith` probe could not see, under an image
            # header: a byte-order mark, a CDN's comment, leading blank lines.
            ("HTML behind a UTF-8 BOM", b"\xef\xbb\xbf<!DOCTYPE html><html>",
             "image/png", "http://x/a.png", None),
            ("HTML behind a comment", b"<!-- cf-cache -->\n<!DOCTYPE html><html>",
             "image/png", "http://x/a.png", None),
            ("HTML behind blank lines", b"\n\n   <html><body>blocked",
             "image/png", "http://x/a.png", None),
            ("an uppercase DOCTYPE-less page", b"<HTML><BODY>blocked",
             "image/png", None, None),
            # ...and the same bytes with an honest header still fail, so the
            # fix did not simply move the trust from the header to nowhere.
            ("a JSON body served honestly", b'{"error": "not found"}',
             "application/json", "http://x/a.png", None),
            # --- magic bytes the sniffer did not know ------------------------
            ("TIFF, little-endian", b"II\x2a\x00\x08\x00\x00\x00", None, None,
             "tiff"),
            ("TIFF, big-endian", b"MM\x00\x2a\x00\x00\x00\x08", None, None,
             "tiff"),
            ("ICO", b"\x00\x00\x01\x00\x01\x00\x10\x10\x00\x00", None, None,
             "ico"),
            ("an AVIF image sequence", b"\x00\x00\x00 ftypavis\x00\x00", None,
             None, "avif"),
            ("TIFF bytes under a lying image/png header",
             b"II\x2a\x00\x08\x00\x00\x00", "image/png", "http://x/a.png",
             "tiff"),
            ("ICO bytes under a lying image/jpeg header",
             b"\x00\x00\x01\x00\x01\x00", "image/jpeg", None, "ico"),
            # --- SVG is validated at the ROOT ELEMENT ------------------------
            ("SVG behind a comment and a doctype",
             b"<!-- generated -->\n<!DOCTYPE svg PUBLIC '-//W3C//DTD SVG 1.1//EN'>"
             b"\n<svg xmlns='http://www.w3.org/2000/svg'></svg>", None, None,
             "svg"),
            ("SVG behind a DOCTYPE internal subset",
             b"<!DOCTYPE svg [<!ENTITY label 'safe > text'>]><svg></svg>",
             None, None, "svg"),
            ("SVG behind a UTF-8 BOM", b"\xef\xbb\xbf<svg xmlns='x'></svg>",
             None, None, "svg"),
            ("SVG behind a processing instruction",
             b"<?xml version='1.0'?>\n<?xml-stylesheet href='a.css'?>\n<svg />",
             None, None, "svg"),
            # an XML document whose root is not <svg> is not an SVG, however
            # loudly the header says otherwise
            ("an RSS feed served as image/svg+xml",
             b"<?xml version='1.0'?><rss><channel/></rss>", "image/svg+xml",
             None, None),
            ("XHTML that merely contains an <svg> later",
             b"<?xml version='1.0'?><html><body><svg/></body></html>",
             "image/svg+xml", "http://x/a.svg", None),
            ("binary bytes under an image/svg+xml header", b"\x00\x01\x02\x03",
             "image/svg+xml", None, None),
            ("binary bytes behind a .svg URL", b"\x00\x01\x02\x03",
             "application/octet-stream", "http://x/a.svg", None)):
        check("sniff_extension, %s" % label,
              sniff_extension(head, ct, url), want)
        if want is not None:
            exercised_extensions.add(want)
    check("signature fixtures cover the full advertised output-extension set",
          exercised_extensions, set(OUTPUT_EXTENSIONS))

    for label, svg in (
            ("fragment references",
             '<svg><defs><linearGradient id="g"/></defs>'
             '<rect style="fill:url(#g)"/><use href="#g"/></svg>'),
            ("quoted fragment CSS",
             '<svg><style>.x{fill:url("#g")}</style><rect class="x"/></svg>'),
            ("encoded fragment href",
             '<svg><use href="&#35;g"/></svg>'),
            ("inert comment text",
             '<svg><!-- <script onload="bad()"> --><rect/></svg>'),
            ("literal text that resembles CSS",
             '<svg><text>@import url(https://example.test/not-css)</text></svg>'),
            ("an inert CSS string that names a resource function",
             '<svg><style>.x::after{content:"image(https://example.test/a)"}'
             '</style></svg>'),
            ("an escaped inert CSS content string",
             '<svg><style>.x::after{content:"\\2022"}</style></svg>'),
            ("an animation-named CSS class without animation",
             '<svg><style>.animation:hover{fill:red}</style></svg>'),
            ("a local shape-inside presentation reference",
             '<svg><path id="shape"/><text shape-inside="url(#shape)"/></svg>'),
            ("CDATA that resembles active markup",
             '<svg><text><![CDATA[<script onload="bad()">]]></text></svg>'),
            ("a benign processing instruction with directive-looking data",
             '<svg><?generator value="<!DOCTYPE svg><script/>"?><rect/></svg>'),
            ("forbidden directives inside comments",
             '<svg><!-- <!DOCTYPE svg><?xml-stylesheet href="x"?> --></svg>')):
        check("self-contained SVG permits %s" % label,
              _svg_safety_issue(svg), None)
    for label, svg, finding in (
            ("DOCTYPE", '<!DOCTYPE svg><svg/>', "DOCTYPE"),
            ("XML stylesheet",
             '<?xml-stylesheet href="https://cdn.example/a.css"?><svg/>',
             "stylesheet"),
            ("script", '<svg><script>bad()</script></svg>', "script"),
            ("foreignObject", '<svg><foreignObject/></svg>', "foreign"),
            ("animation", '<svg><animate attributeName="x"/></svg>', "animation"),
            ("animateColor", '<svg><animateColor attributeName="fill"/></svg>',
             "animation"),
            ("event handler", '<svg onload="bad()"/>', "event-handler"),
            ("remote href", '<svg><image href="https://cdn.example/a.png"/></svg>',
             "external href"),
            ("encoded remote href",
             '<svg><image href="&#104;ttps://cdn.example/a.png"/></svg>',
             "external href"),
            ("remote source attribute",
             '<svg><image src="https://cdn.example/a.png"/></svg>',
             "external href"),
            ("data href", '<svg><image href="data:image/png;base64,AA"/></svg>',
             "external href"),
            ("external base", '<svg xml:base="https://cdn.example/"><use href="#x"/></svg>',
             "external href"),
            ("CSS import", '<svg><style>@import "a.css";</style></svg>',
             "external CSS"),
            ("CSS URL", '<svg><style>fill:url(https://cdn.example/a)</style></svg>',
             "external CSS"),
            ("comment-obfuscated CSS URL",
             '<svg><style>fill:u/**/rl(https://cdn.example/a)</style></svg>',
             "external CSS"),
            ("escaped CSS URL",
             '<svg><style>fill:u\\72l(https://cdn.example/a)</style></svg>',
             "external CSS"),
            ("CSS image string",
             '<svg><style>.x{background:image("https://cdn.example/a")}'
             '</style></svg>', "external CSS"),
            ("CSS image-set protocol-relative string",
             '<svg><style>.x{background:image-set("//cdn.example/a" 1x)}'
             '</style></svg>', "external CSS"),
            ("comment-obfuscated CSS image function",
             '<svg><style>.x{background:im/**/age("a.png")}</style></svg>',
             "external CSS"),
            ("vendor CSS image-set relative string",
             '<svg><style>.x{background:-webkit-image-set("a.png" 1x)}'
             '</style></svg>', "external CSS"),
            ("CSS src function",
             '<svg><style>@font-face{src:src("https://cdn.example/a.woff")}'
             '</style></svg>', "external CSS"),
            ("escaped CSS string in a resource function",
             '<svg><style>.x{background:image("\\68ttps://cdn.example/a")}'
             '</style></svg>', "external CSS"),
            ("external shape-inside presentation attribute",
             '<svg><text shape-inside="url(https://cdn.example/shape.svg)"/>'
             '</svg>', "external CSS"),
            ("external mask-image presentation attribute",
             '<svg><rect mask-image="image(https://cdn.example/mask.svg)"/>'
             '</svg>', "external CSS"),
            ("external fill-image presentation attribute",
             '<svg><rect fill-image="image(https://cdn.example/fill.svg)"/>'
             '</svg>', "external CSS"),
            ("external offset-path presentation attribute",
             '<svg><rect offset-path="url(https://cdn.example/path.svg)"/>'
             '</svg>', "external CSS"),
            ("typed CSS attr URL",
             '<svg><text data-shape="https://cdn.example/shape.png" '
             'shape-outside="attr(data-shape url)"/></svg>', "external CSS"),
            ("CSS keyframes",
             '<svg><style>@keyframes spin{to{transform:rotate(1turn)}}'
             '</style></svg>', "CSS animation"),
            ("vendor-prefixed CSS keyframes",
             '<svg><style>@-moz-keyframes spin{to{transform:rotate(1turn)}}'
             '</style></svg>', "CSS animation"),
            ("CSS animation property",
             '<svg><style>.x{animation:spin 1ms infinite}</style></svg>',
             "CSS animation"),
            ("inline CSS transition",
             '<svg><rect style="transition:fill 1ms"/></svg>',
             "CSS animation"),
            ("malformed XML", '<svg><rect></svg>', "malformed XML"),
            ("non-SVG namespace",
             '<svg xmlns="http://www.w3.org/1999/xhtml"/>', "non-SVG"),
            ("active element in a foreign namespace",
             '<svg xmlns:x="urn:example"><x:script/></svg>', "active"),
            ("HTML responsive image in a foreign namespace",
             '<svg xmlns:h="http://www.w3.org/1999/xhtml">'
             '<h:img srcset="https://cdn.example/a.png 1x"/></svg>',
             "active")):
        check("self-contained SVG refuses %s" % label,
              finding in (_svg_safety_issue(svg) or ""), True)

    # describe_bytes is what turns a refusal into a diagnosis: "not an image"
    # sends the reader back to the URL with nothing, "a JSON body" says the CDN
    # answered with an error document.
    for label, head, want in (
            ("JSON", b'{"error": 1}', "a JSON body"),
            ("an HTML page", b"<!DOCTYPE html><html>", "an HTML page"),
            ("HTML behind a BOM", b"\xef\xbb\xbf<html>", "an HTML page"),
            ("plain text", b"upstream connect error", "plain text"),
            ("a PDF", b"%PDF-1.7\n%\xc7\xec", "a PDF"),
            ("a ZIP", b"PK\x03\x04\x14\x00",
             "a ZIP archive (or a zipped Office/OpenDocument file)"),
            ("an ELF binary", b"\x7fELF\x02\x01", "an ELF executable"),
            ("a gzip stream", b"\x1f\x8b\x08\x00", "a gzip stream"),
            ("an SVG", b"<svg xmlns='x'/>", "an SVG document"),
            ("a PNG", _PNG, "a PNG image"),
            ("something unrecognized", b"\x00\x01\x02\x03",
             "unrecognized binary data")):
        check("describe_bytes names %s" % label, describe_bytes(head), want)

    # --- validate_slug: the only thing between free text and a vault write --
    for bad, label in (("../evil", "a parent-directory hop"),
                       ("..", "the parent directory itself"),
                       ("a/../b", "a hop in the middle"),
                       ("/etc/passwd", "an absolute path"),
                       ("dir/slug", "a separator"),
                       ("dir\\slug", "a backslash separator"),
                       ("bad:name", "a Windows-forbidden colon"),
                       ('bad"name', "a Windows-forbidden quote"),
                       ("bad|name", "a Windows-forbidden pipe"),
                       ("bad?name", "a Windows-forbidden question mark"),
                       ("bad*name", "a Windows-forbidden asterisk"),
                       ("bad<name", "a Windows-forbidden angle bracket"),
                       ("bad\x1fname", "a control character"),
                       ("bad\x7fname", "DEL"),
                       ("Teslo..Cancer_2026", "`..` with no separator at all"),
                       ("trailing.", "a trailing dot"),
                       ("trailing ", "a trailing space"),
                       ("CON", "a Windows device basename"),
                       ("com1.txt", "a Windows device basename before a dot"),
                       ("", "an empty slug"),
                       ("   ", "a whitespace-only slug"),
                       (None, "no slug at all"),
                       (".", "a slug that names no note"),
                       (".hidden", "a leading dot"),
                       (" leading", "a leading space"),
                       ("nul\x00byte", "an embedded NUL")):
        raises("validate_slug refuses %s (%r)" % (label, bad),
               validate_slug, bad)
    check("validate_slug passes an ordinary slug",
          validate_slug("Teslo_Pancreatic_Cancer_2026"),
          "Teslo_Pancreatic_Cancer_2026")
    check("...and a slug with a dot in it, which is not a hop",
          validate_slug("Geron_ML_1.5_2024"), "Geron_ML_1.5_2024")
    check("...and reports which argument was wrong",
          "--old-slug" in raises("validate_slug names its argument",
                                 validate_slug, "../x", "--old-slug"), True)
    for bad in (0, -1, 1.5, "1", True, None):
        raises("validate_index refuses a non-positive or non-integer index %r" % (bad,),
               validate_index, bad)
    check("validate_index accepts the first and later figure numbers",
          [validate_index(1), validate_index(20)], [1, 20])
    rendered_fixture = """![[Visible_fig_1.png]]
`![[Inline_code_fig_2.png]]`
`multiline code
![[Multiline_code_fig_2b.png]]
continues here`
```md
![[Fence_fig_3.png]]
```
    ![[Indented_fig_4.png]]
<!-- ![[Html_comment_fig_5.png]] -->
%% ![[Obsidian_comment_fig_6.png]] %%
<code>![[Html_code_fig_6b.png]]</code>
<script>![[Script_fig_6c.png]]</script>
\\![[Escaped_fig_7.png]]
![[folder/Qualified_fig_8.png]]
![[Aliased_fig_9.png|640]]
"""
    check("only rendered filename-only embeds establish clipping ownership",
          _rendered_embed_basenames(rendered_fixture),
          frozenset(("Visible_fig_1.png", "Aliased_fig_9.png")))
    check("malformed literal delimiters do not create ownership evidence",
          _rendered_embed_basenames(
              "unclosed ` ![[Inline_fig_1.png]]\n"
              "%% ![[Comment_fig_2.png]]\n"
              "<code>![[Html_fig_3.png]]\n"),
          frozenset())
    dependency_fixture = """[[Old_Slug_2025|old note]]
![[Sources/Images/Old_Slug_2025_fig_1.png#crop|figure]]
[note](../Articles/Old_Slug_2025.md)
<img src="Sources/Images/Old_Slug_2025_fig_2.png">
`![[Old_Slug_2025_fig_3.png]]`
<!-- [[Old_Slug_2025]] -->
[remote](https://example.com/Old_Slug_2025_fig_4.png)
"""
    check("dependency parsing sees local old-note/image targets but not inert or remote text",
          _markdown_dependency_names(
              dependency_fixture,
              ["Old_Slug_2025_fig_%d.png" % n for n in range(1, 5)],
              "Old_Slug_2025"),
          ["Old_Slug_2025.md", "Old_Slug_2025_fig_1.png",
           "Old_Slug_2025_fig_2.png"])
    check("dependency parsing sees links in nested lists and after a stray backtick",
          _markdown_dependency_names(
              "    - [[Old_Slug_2025]]\nstray ` prose\n"
              "        - ![[Old_Slug_2025_fig_1.png]]\n",
              ["Old_Slug_2025_fig_1.png"], "Old_Slug_2025"),
          ["Old_Slug_2025.md", "Old_Slug_2025_fig_1.png"])
    check("malformed comments and code cannot hide retirement dependencies",
          _markdown_dependency_names(
              "` [[Old_Slug_2025]] ``\n"
              "%% unclosed ![[Old_Slug_2025_fig_1.png]]\n"
              "<code>unclosed [[Old_Slug_2025]]\n",
              ["Old_Slug_2025_fig_1.png"], "Old_Slug_2025"),
          ["Old_Slug_2025.md", "Old_Slug_2025_fig_1.png"])

    import shutil
    tmp = tempfile.mkdtemp(prefix="fetch_images_selftest.")
    previous_tempdir = tempfile.tempdir
    try:
        # The leak check must observe this run's scratch files, not another
        # self-test or real download using the same system temporary folder.
        tempfile.tempdir = tmp
        att = os.path.join(tmp, "Sources", "Images")
        os.makedirs(att)
        pdfs = os.path.join(tmp, "Sources", "PDFs")
        os.mkdir(pdfs)
        occupied_pdf = os.path.join(pdfs, "Taken_Slug_2026.pdf")
        with open(occupied_pdf, "wb") as fh:
            fh.write(b"%PDF-1.4\n")
        with open(os.path.join(att, "Taken_Slug_2026_fig_1.png"), "wb") as fh:
            fh.write(_PNG)
        check("slug preflight reports both PDF and image-prefix owners",
              slug_occupancy(tmp, "Taken_Slug_2026"),
              {"ok": False, "vault": os.path.abspath(tmp),
               "slug": "Taken_Slug_2026", "pdf_stem_occupied": True,
               "image_occupants": ["Taken_Slug_2026_fig_1.png"]})
        check("slug preflight reports a genuinely free stem",
              slug_occupancy(tmp, "Free_Slug_2026")["ok"], True)
        os.unlink(os.path.join(att, "Taken_Slug_2026_fig_1.png"))
        os.unlink(occupied_pdf)
        os.rmdir(pdfs)
        sources = os.path.join(tmp, "Sources", "PDFs")
        os.makedirs(sources)
        articles = os.path.join(tmp, "Articles")
        os.makedirs(articles)
        dst = os.path.join(tmp, "body")

        def clipping_note(slug, embeds=(), source="https://example.com/article",
                          body_prefix=""):
            """Write one canonical clipping owner for a guarded self-test."""
            expected = _manifest_name_key(slug + ".md")
            for name in os.listdir(articles):
                if _manifest_name_key(name) == expected:
                    os.unlink(os.path.join(articles, name))
            path = os.path.join(articles, slug + ".md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("---\nsources:\n  - %s\n---\n%s" %
                         (source, body_prefix))
                for name in embeds:
                    fh.write("\n![[%s]]\n" % name)
            return path

        def checked_rename(*args, **kwargs):
            """Every ordinary self-test call follows the required ownership path."""
            kwargs.setdefault("sources", sources)
            if "owner_note" not in kwargs and len(args) >= 3:
                matched = [os.path.basename(path)
                           for path in _glob_slug(args[0], args[1], _FIG_GLOB)]
                kwargs["owner_note"] = clipping_note(args[1], matched)
            return rename_slug(*args, **kwargs)

        def touch(path, data=b"x"):
            with open(path, "wb") as fh:
                fh.write(data)
            return path

        # Native Windows can expose a stable file differently through path
        # stat and handle stat. The readers must tolerate that projection while
        # still rejecting changes within either view and mismatched identities.
        real_fstat = os.fstat

        class _HandleStat:
            def __init__(self, item, ctime_delta=100, ino_delta=0):
                self.item = item
                self.ctime_delta = ctime_delta
                self.ino_delta = ino_delta

            def __getattr__(self, name):
                if name == "st_ctime_ns":
                    return getattr(self.item, name) + self.ctime_delta
                if name == "st_mode":
                    return stat.S_IFMT(self.item.st_mode) | 0o444
                if name == "st_ino":
                    return self.item.st_ino + self.ino_delta
                return getattr(self.item, name)

        def projected_fstat(descriptor):
            return _HandleStat(real_fstat(descriptor))

        snapshot_path = touch(os.path.join(tmp, "stable-snapshot.bin"), b"stable")
        markdown_path = touch(
            os.path.join(tmp, "stable-note.md"),
            b"---\nsources:\n  - https://example.com/article\n---\nbody\n")
        with patch.object(os, "fstat", side_effect=projected_fstat):
            projected_snapshot = _stable_regular_snapshot(snapshot_path)
            projected_markdown = _stable_markdown_text(markdown_path)
        check("stable readers tolerate distinct path/handle metadata projections",
              (projected_snapshot[1], projected_markdown.endswith("body\n")),
              (__import__("hashlib").sha256(b"stable").hexdigest(), True))

        calls = {"count": 0}

        def changing_fstat(descriptor):
            calls["count"] += 1
            return _HandleStat(real_fstat(descriptor),
                               ctime_delta=calls["count"] * 100)

        try:
            with patch.object(os, "fstat", side_effect=changing_fstat):
                _stable_regular_snapshot(snapshot_path)
            snapshot_changed = False
        except OSError:
            snapshot_changed = True
        check("regular snapshots reject a handle view that changes during the read",
              snapshot_changed, True)

        calls["count"] = 0
        try:
            with patch.object(os, "fstat", side_effect=changing_fstat):
                _stable_markdown_text(markdown_path)
            markdown_changed = False
        except ValueError:
            markdown_changed = True
        check("Markdown snapshots reject a handle view that changes during the read",
              markdown_changed, True)

        def mismatched_fstat(descriptor):
            return _HandleStat(real_fstat(descriptor), ino_delta=1)

        try:
            with patch.object(os, "fstat", side_effect=mismatched_fstat):
                _stable_markdown_text(markdown_path)
            markdown_mismatched = False
        except ValueError:
            markdown_mismatched = True
        check("Markdown snapshots bind path and handle views by file identity",
              markdown_mismatched, True)

        urls_file = touch(os.path.join(tmp, "urls.txt"),
                          b"\xef\xbb\xbfhttps://example.com/a.png\n\n"
                          b"https://example.com/b.png\n")
        check("--urls-file is decoded as UTF-8-sig",
              _read_urls_file(urls_file),
              ["https://example.com/a.png", "https://example.com/b.png"])
        os.unlink(urls_file)
        check("--urls-file is closed after the complete read",
              os.path.lexists(urls_file), False)
        bad_urls = touch(os.path.join(tmp, "bad-urls.txt"), b"https://x/\xff.png\n")
        raises("--urls-file refuses invalid UTF-8 instead of dropping bytes",
               _read_urls_file, bad_urls)

        check("report URLs omit HTTP credentials, queries, and fragments",
              _report_url(
                  "https://alice:secret@example.com:8443/image.png?token=abc#crop"),
              "https://example.com:8443/image.png?<query omitted>")
        check("report URLs omit inline data payloads",
              _report_url("data:image/png;base64,SECRET-BYTES"),
              "data:image/png;base64,<payload omitted>")
        check("an unparseable report URL reveals no location text",
              _report_url("not a URL with secret material"),
              "URL:<location omitted>")
        malformed_secret = (
            "https://alice:password@example.com\N{FULLWIDTH SOLIDUS}private"
            "?token=secret")
        malformed_error = raises(
            "a malformed URL is refused without echoing its raw text",
            _vetted_target, malformed_secret)
        check("the malformed-URL error omits credentials, path, and query",
              all(secret not in malformed_error
                  for secret in ("alice", "password", "private", "secret")),
              True)

        def current_owner(folder, slug, extra=()):
            embeds = [os.path.basename(path)
                      for path in _glob_slug(folder, slug, _FIG_GLOB)]
            embeds.extend(extra)
            return clipping_note(slug, embeds)

        # --- _ensure_within -------------------------------------------------
        check("_ensure_within accepts a path inside",
              _ensure_within(att, os.path.join(att, "a_fig_1.png")),
              os.path.realpath(os.path.join(att, "a_fig_1.png")))
        raises("_ensure_within refuses a `..` escape",
               _ensure_within, att, os.path.join(att, "..", "a.png"))
        raises("_ensure_within refuses the folder itself", _ensure_within,
               att, att)
        # a SIBLING whose name merely starts with the folder's name: a prefix
        # test without the separator accepts `Sources/Imagesevil/`
        sibling = os.path.join(tmp, "Sources", "Imagesevil")
        os.makedirs(sibling)
        raises("_ensure_within refuses a sibling with a shared prefix",
               _ensure_within, att, os.path.join(sibling, "a.png"))
        outside = touch(os.path.join(tmp, "outside.png"))
        link = os.path.join(att, "link_fig_1.png")
        try:
            os.symlink(outside, link)
            raises("_ensure_within resolves a symlink out of the folder",
                   _ensure_within, att, link)
            os.remove(link)
        except (OSError, NotImplementedError):
            pass                              # no symlink support: skip, silently

        # --- the scheme and private-host guards, called directly ------------
        for url, label in (("file:///etc/passwd", "file:"),
                           ("FILE:///etc/passwd", "file: in capitals"),
                           ("javascript:alert(1)", "javascript:"),
                           ("ftp://example.com/a.png", "ftp:"),
                           ("/relative/a.png", "a scheme-less path")):
            raises("check_url refuses %s" % label, check_url, url)
        # A host-less URL is refused here, by name, rather than falling into the
        # resolver as an opaque `getaddrinfo` failure.
        check("check_url refuses an http URL with no host, and says so",
              "no host" in raises("check_url refuses a host-less URL",
                                  check_url, "http:///a.png"), True)
        check("check_url allows a data: URI",
              check_url("data:image/png;base64,AAAA"), None)
        check("the proxy policy is explicit and does not weaken address pinning",
              PROXY_POLICY, "direct-only")
        # Loopback, link-local and private space, in the spellings that are
        # meant to slip past a string test. These resolve locally (a numeric
        # literal or /etc/hosts), so no DNS query leaves the machine.
        for host, label in (("127.0.0.1", "dotted-quad loopback"),
                            ("2130706433", "loopback as a decimal integer"),
                            ("0177.0.0.1", "loopback in octal"),
                            ("[::1]", "IPv6 loopback"),
                            ("localhost", "localhost by name"),
                            ("169.254.169.254", "the link-local metadata address"),
                            ("10.0.0.5", "RFC1918 private space"),
                            ("192.168.1.1", "a home router"),
                            ("100.64.0.1", "shared carrier/private-overlay space"),
                            ("0.0.0.0", "the unspecified address")):
            url = "http://%s/a.png" % host
            try:
                socket.getaddrinfo(host.strip("[]"), 80,
                                   type=socket.SOCK_STREAM)
            except socket.gaierror:
                # Some platforms reject a legacy numeric spelling before this
                # script can classify it. The mocked cases below cover those.
                continue
            raises("check_url refuses %s (%s)" % (label, host), check_url, url)
            check("...unless --allow-private-hosts is passed (%s)" % host,
                  check_url(url, True), None)
        # Resolve one target once, reject every returned address, then connect
        # only to a vetted sockaddr. The second DNS answer below is the private
        # rebinding answer an ordinary URL client would consume.
        _public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("177.0.0.1", 0))]
        with patch.object(socket, "getaddrinfo", return_value=_public) as _dns:
            for _host in ("0177.0.0.1", "0x7f000001", "2130706433", "127.1"):
                raises("ambiguous numeric host is refused before a public DNS answer: "
                       + _host, check_url, "http://" + _host + "/a.png")
            check("numeric alias refusal does not consult the host resolver",
                  _dns.call_count, 0)

        _public4 = [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                     ("198.51.100.20", 80))]
        _private4 = [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                      ("127.0.0.1", 80))]
        # TEST-NET addresses are not is_global in modern Python, so use a
        # genuinely global fixture for classifications below.
        _public4[0] = (_public4[0][0], _public4[0][1], _public4[0][2], "",
                       ("177.0.0.1", 80))

        class _SocketProbe:
            def __init__(self):
                self.connected = None
                self.timeouts = []
                self.closed = False

            def settimeout(self, value):
                self.timeouts.append(value)

            def connect(self, sockaddr):
                self.connected = sockaddr

            def close(self):
                self.closed = True

        with patch.object(socket, "getaddrinfo",
                          side_effect=[_public4, _private4]) as _dns:
            target = _vetted_target("http://media.example/a.png")
            probe = _SocketProbe()
            with patch.object(socket, "socket", return_value=probe):
                connected = _connect_vetted(
                    target, 5, time.monotonic() + 5)
            check("a rebinding answer is never requested after target vetting",
                  _dns.call_count, 1)
            check("the actual socket is pinned to the vetted IPv4 sockaddr",
                  (connected is probe, probe.connected),
                  (True, ("177.0.0.1", 80)))

        _public6 = [(socket.AF_INET6, socket.SOCK_STREAM, 6, "",
                     ("2606:4700:4700::1111", 8443, 0, 0))]
        with patch.object(socket, "getaddrinfo", return_value=_public6):
            ipv6 = _vetted_target(
                "https://[2606:4700:4700::1111]:8443/a.png")
        check("IPv6 stays bracketed in the logical Host header",
              ipv6.host_header, "[2606:4700:4700::1111]:8443")
        check("the IPv6 sockaddr is retained verbatim for the pinned socket",
              ipv6.addresses[0][4], ("2606:4700:4700::1111", 8443, 0, 0))

        with patch.object(socket, "getaddrinfo",
                          return_value=_public4 + _private4):
            raises("one private answer rejects a mixed public/private DNS set",
                   _vetted_target, "http://mixed.example/a.png")
        with patch.object(socket, "getaddrinfo", return_value=_private4):
            check("--allow-private-hosts remains the explicit private escape hatch",
                  _vetted_target("http://private.example/a.png", True).addresses,
                  tuple(_private4))

        # Python 3.9 classifies several IPv6 transition spellings as globally
        # routable without classifying the IPv4 endpoint they carry. A NAT64,
        # 6to4, compatible, or ISATAP address can otherwise tunnel this fetch
        # to loopback/RFC1918 space while passing the nominal IPv6 check.
        tunneled_private = (
            ("IPv4-mapped", "::ffff:127.0.0.1"),
            ("IPv4-compatible", "::127.0.0.1"),
            ("well-known NAT64", "64:ff9b::7f00:1"),
            ("local-use NAT64", "64:ff9b:1:a00:0:100::"),
            ("6to4", "2002:7f00:1::"),
            ("Teredo", "2001:0:808:808:0:ffff:80ff:fffe"),
            ("ISATAP", "2606:4700::5efe:7f00:1"),
        )
        for label, literal in tunneled_private:
            hidden = _embedded_ipv4_addresses(ipaddress.ip_address(literal))
            check("%s exposes its embedded IPv4 endpoint" % label,
                  bool(hidden), True)
            check("%s with a private embedded endpoint is non-public" % label,
                  _public_ip(ipaddress.ip_address(literal)), False)
            tunneled = [(socket.AF_INET6, socket.SOCK_STREAM, 6, "",
                         (literal, 80, 0, 0))]
            with patch.object(socket, "getaddrinfo", return_value=tunneled):
                raises("the URL guard refuses private IPv4 through %s" % label,
                       _vetted_target, "http://transition.example/a.png")
        check("deprecated IPv6 site-local space is never treated as public",
              _public_ip(ipaddress.ip_address("fec0::1")), False)

        # Public embedded endpoints are not rejected merely because the outer
        # form has one. Python 3.9 independently marks compatible/NAT64 space
        # reserved, so those remain outside this script's open-web policy.
        for label, literal in (
                ("6to4", "2002:808:808::"),
                ("ISATAP", "2606:4700::5efe:808:808")):
            check("%s with a public IPv4 endpoint remains public" % label,
                  _public_ip(ipaddress.ip_address(literal)), True)
        public_6to4 = ipaddress.ip_address("2002:808:808::")
        with patch.object(ipaddress.IPv6Address, "is_global",
                          new_callable=PropertyMock, return_value=False), \
                patch.object(ipaddress.IPv6Address, "is_private",
                             new_callable=PropertyMock, return_value=True):
            check("6to4 policy is stable when Python classifies its outer prefix private",
                  _public_ip(public_6to4), True)

        request_probe = {}

        class _WireProbe(_SocketProbe):
            def __init__(self):
                super().__init__()
                self.sent = bytearray()

            def sendall(self, data):
                self.sent.extend(data)

            def makefile(self, _mode, *args, **kwargs):
                return io.BytesIO(
                    b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")

        wire = _WireProbe()
        default_tls = ssl.create_default_context()
        check("the real default TLS context validates chains and hostnames",
              (default_tls.check_hostname, default_tls.verify_mode),
              (True, ssl.CERT_REQUIRED))

        class _TLSProbe:
            check_hostname = True
            verify_mode = ssl.CERT_REQUIRED

            def wrap_socket(self, sock, server_hostname=None):
                request_probe["sni"] = server_hostname
                request_probe["tls_input"] = sock
                return sock

        with patch.object(socket, "getaddrinfo", return_value=_public4):
            https_target = _vetted_target(
                "https://Media.Example:8443/a%2Fb?q=a%20b+plus#omit-me")
            explicit_default = _vetted_target(
                "https://Media.Example:443/empty-query?#omit-me")
        check("Host preserves an explicitly written default port",
              explicit_default.host_header, "media.example:443")
        check("an empty query delimiter is preserved while its fragment is omitted",
              explicit_default.request_target, "/empty-query?")
        tls_probe = _TLSProbe()
        with patch.dict(globals(), {"_connect_vetted": lambda *_a, **_kw: wire}), \
                patch.object(ssl, "create_default_context", return_value=tls_probe):
            https_conn, https_resp = _request_once(
                https_target, 5, time.monotonic() + 5)
        sent_request = wire.sent.decode("iso-8859-1")
        check("HTTPS keeps the logical host for SNI and Host, never the pinned IP",
              (request_probe["sni"], "Host: media.example:8443\r\n" in sent_request,
               "177.0.0.1" in sent_request),
              ("media.example", True, False))
        check("the request target preserves percent/query spelling and omits fragments",
              sent_request.split("\r\n", 1)[0],
              "GET /a%2Fb?q=a%20b+plus HTTP/1.1")
        check("the TLS wrapper receives the already-pinned socket",
              request_probe["tls_input"] is wire, True)
        check("the TLS context contract keeps certificate hostname validation on",
              (tls_probe.check_hostname, tls_probe.verify_mode),
              (True, ssl.CERT_REQUIRED))
        https_resp.close()
        https_conn.close()

        # Redirects are followed manually. Each next URL is resolved/guarded
        # before another request and before its redirect body can be consumed.
        redir = _FakeResponse(
            [b"untrusted redirect body"], {"Location": "http://private.example/x"},
            status=302, reason="Found")
        redir_conn = _FakeConnection()
        with patch.object(socket, "getaddrinfo",
                          side_effect=[_public4, _private4]) as _dns, \
                patch.dict(globals(), {"_request_once": lambda *_a, **_kw:
                           (redir_conn, redir)}):
            raises("a redirect to a private address is refused before requesting it",
                   _fetch_to_path, "http://media.example/a.png", dst, 5,
                   1000, 30, False)
        check("the redirect target is a separately guarded single resolution",
              _dns.call_count, 2)
        check("a rejected redirect body is never read",
              (redir.read_count, redir.closed, redir_conn.closed),
              (0, True, True))

        downgrade = _FakeResponse(
            [b"downgrade body"], {"Location": "http://media2.example/x"},
            status=302, reason="Found")
        with patch.object(socket, "getaddrinfo",
                          side_effect=[_public4, _public4]), \
                patch.dict(globals(), {"_request_once": lambda *_a, **_kw:
                           (_FakeConnection(), downgrade)}):
            raises("an HTTPS redirect cannot downgrade to HTTP",
                   _fetch_to_path, "https://media.example/a.png", dst, 5,
                   1000, 30, False)
        check("the refused downgrade body is never read", downgrade.read_count, 0)

        first = _FakeResponse([], {"Location": "/final?q=1%202"},
                              status=302, reason="Found")
        final = _FakeResponse([_PNG], {"Content-Type": "image/png",
                                      "Content-Length": str(len(_PNG))})
        calls = []

        def fake_request(target, *_a, **_kw):
            calls.append(target)
            return (_FakeConnection(), first if len(calls) == 1 else final)

        record = {}
        with patch.object(socket, "getaddrinfo",
                          side_effect=[_public4, _public4]) as _dns, \
                patch.dict(globals(), {"_request_once": fake_request}):
            content_type, fetched = _fetch_to_path(
                "http://media.example/start", dst, 5, 1000, 30, False, record)
        check("a safe redirect resolves exactly once per requested hop",
              (_dns.call_count, len(calls)), (2, 2))
        check("a safe redirect reaches the final body and reports its URL",
              (content_type, fetched, record["final_url"],
               open(dst, "rb").read()),
              ("image/png", len(_PNG),
               "http://media.example/final?q=1%202", _PNG))

        for status in (300, 304, 305, 306, 399):
            unexpected = _FakeResponse(
                [_PNG], {"Content-Type": "image/png"}, status=status,
                reason="Not a followed redirect")
            with patch.object(socket, "getaddrinfo", return_value=_public4), \
                    patch.dict(globals(), {"_request_once": lambda *_a, _r=unexpected,
                               **_kw: (_FakeConnection(), _r)}):
                raises("HTTP %d cannot be accepted as a successful payload" % status,
                       _fetch_to_path, "http://media.example/a.png", dst, 5,
                       1000, 30, False)
            check("HTTP %d body is not read" % status, unexpected.read_count, 0)

        # A hostile origin can put arbitrary text in the HTTP reason phrase,
        # including a reflected signed query. It is not useful diagnostics and
        # must not bypass URL redaction through HTTPError.__str__.
        denied = _FakeResponse(
            [], {}, status=403,
            reason="reflected token=do-not-report#private")
        secret_url = "http://media.example/a.png?token=do-not-report#private"
        with patch.object(socket, "getaddrinfo", return_value=_public4), \
                patch.dict(globals(), {"_request_once": lambda *_a, **_kw:
                           (_FakeConnection(), denied)}):
            denied_result = download_one(
                secret_url, att, "Redacted_Error_2026", 1)
        check("an HTTP failure report redacts its query and fragment everywhere",
              (denied_result["url"],
               "do-not-report" in json.dumps(denied_result),
               "private" in json.dumps(denied_result)),
              ("http://media.example/a.png?<query omitted>", False, False))

        raises("a redirect to file: is refused at the hop",
               _vetted_target, "file:///etc/passwd")

        for field, values in (("timeout", (0, -1, True, None)),
                              ("max_bytes", (0, -1, True, 1.5, None)),
                              ("max_seconds", (0, -1, True, None))):
            for bad in values:
                limits = {"timeout": 5, "max_bytes": 1000, "max_seconds": 30}
                limits[field] = bad
                raises("programmatic %s refuses %r" % (field, bad),
                       _validate_transfer_limits, limits["timeout"],
                       limits["max_bytes"], limits["max_seconds"])
        for bad in ("0", "-1", "1.5", "nope"):
            raises("CLI transfer limits refuse %r" % bad,
                   _positive_int_arg, bad)

        # --- _stream_to_file, driven by a fake response ---------------------
        far = time.monotonic() + 60
        check("_stream_to_file returns the byte count",
              _stream_to_file(_FakeResponse([b"abc", b"de"]), dst, 1000, far), 5)
        check("...and writes exactly those bytes", open(dst, "rb").read(),
              b"abcde")
        check("a declared Content-Length that matches is fine",
              _stream_to_file(_FakeResponse([b"abcde"]), dst, 1000, far, 5), 5)
        # A server that announced 100 bytes, sent 58 and closed used to produce
        # `ok` and a corrupt image, and the re-run was then refused as present.
        raises("a short read against Content-Length is a failed download",
               _stream_to_file, _FakeResponse([b"abc"]), dst, 1000, far, 100)
        raises("the byte cap is enforced across chunks", _stream_to_file,
               _FakeResponse([b"x" * 40, b"x" * 40]), dst, 50, far)
        raises("...and on a single oversized chunk", _stream_to_file,
               _FakeResponse([b"x" * 4096]), dst, 50, far)
        check("a response exactly at the cap is not over it",
              _stream_to_file(_FakeResponse([b"x" * 50]), dst, 50, far), 50)
        # The wall-clock deadline: `--timeout` is per socket operation and a
        # server dripping bytes resets it on every chunk, so this is the only
        # bound on a slow-drip transfer.
        err = raises("the wall-clock deadline is enforced", _stream_to_file,
                     _FakeResponse([b"x", b"x", b"x"]), dst, 1000,
                     time.monotonic() - 1)
        check("...and says so in words", "wall-clock" in err, True)
        # read1, not read: a `read(CHUNK)` blocks until CHUNK bytes have
        # accumulated, so the deadline above would never be reached.
        check("_stream_to_file prefers read1 over read",
              _stream_to_file(_FakeResponse([b"ab"]), dst, 1000, far), 2)
        # the wiring download_one uses: the declared length comes off headers
        resp = _FakeResponse([b"abc"], {"Content-Length": "99"})
        declared = resp.headers.get("Content-Length")
        raises("the declared length is read off the response headers",
               _stream_to_file, resp, dst, 1000, far,
               int(declared) if declared and declared.isdigit() else None)

        # --- data: URIs, and one end-to-end download with no socket ---------
        b64 = base64.b64encode(_PNG).decode("ascii")
        data_url = "data:image/png;base64," + b64
        check("_fetch_data_uri decodes and reports the mime type",
              _fetch_data_uri(data_url, dst), "image/png")
        check("...and writes the bytes", open(dst, "rb").read(), _PNG)
        raises("a malformed data: URI is refused", _fetch_data_uri,
               "data:not-a-uri", dst)
        raises("a data: URI over the cap is refused", _fetch_data_uri,
               data_url, dst, 10)
        oversized_b64 = ("data:application/octet-stream;base64,"
                         + base64.b64encode(b"x" * 52).decode("ascii"))
        with patch.object(base64, "b64decode",
                          side_effect=AssertionError("must fail before decode")):
            raises("an unescaped oversized base64 URI is rejected before allocation",
                   _fetch_data_uri, oversized_b64, dst, 50)
        percent_b64 = oversized_b64.replace("=", "%3D")
        raises("a percent-escaped base64 URI is bounded while decoding",
               _fetch_data_uri, percent_b64, dst, 50)
        raises("data URI decoding observes the whole-transfer deadline",
               _fetch_data_uri, "data:text/plain,abc", dst, 100,
               time.monotonic() - 1)
        raises("invalid base64 is refused rather than decoded permissively",
               _fetch_data_uri, "data:text/plain;base64,@@@@", dst, 100)
        # RFC 2397 allows parameters on the mediatype, and real pages carry
        # them: `;charset=utf-8` before `;base64`, and the plain-text
        # inline-SVG `;utf8` form.  Both used to be refused as malformed, so
        # a legitimately clipped image was reported failed.
        check("a mediatype parameter before ;base64 still decodes",
              _fetch_data_uri("data:image/png;charset=utf-8;base64," + b64,
                              dst), "image/png")
        check("...and writes the same bytes", open(dst, "rb").read(), _PNG)
        svg_body = b"<svg xmlns='http://www.w3.org/2000/svg'/>"
        svg_uri = "data:image/svg+xml;utf8," + svg_body.decode("ascii")
        check("the plain-form ;utf8 SVG data: URI decodes as text",
              _fetch_data_uri(svg_uri, dst), "image/svg+xml")
        check("...to the literal SVG bytes", open(dst, "rb").read(), svg_body)
        check("a parameterless plain-form URI still decodes",
              _fetch_data_uri("data:text/plain,hi%20there", dst),
              "text/plain")
        check("...percent-decoded", open(dst, "rb").read(), b"hi there")
        # RFC 2397's data production is URL characters, so a base64 payload
        # may percent-escape its padding and plus signs — browsers unquote
        # before decoding, and refusing the escapes failed an image the
        # browser renders fine.
        check("percent-escaped base64 padding decodes",
              (_fetch_data_uri("data:image/png;base64,"
                               + b64.replace("=", "%3D"), dst),
               open(dst, "rb").read()),
              ("image/png", _PNG)),
        check("...and percent-escaped `+` decodes to the same bytes",
              (_fetch_data_uri("data:image/png;base64,"
                               + b64.replace("+", "%2B"), dst),
               open(dst, "rb").read()),
              ("image/png", _PNG))
        check("a bare `data:,` payload has no mime and no bytes",
              (_fetch_data_uri("data:,x", dst), open(dst, "rb").read()),
              (None, b"x"))
        # `base64` with no `;` before it is a (bogus) mediatype, not the flag.
        check("`data:base64,` reads base64 as the mediatype, not the flag",
              (_fetch_data_uri("data:base64,x", dst),
               open(dst, "rb").read()), ("base64", b"x"))

        def strays():
            """`_temp_path`'s files, which every path through download_one must
            clean up, in this run's isolated temporary directory."""
            return {f for f in os.listdir(tempfile.gettempdir())
                    if f.startswith("clipping_img.")}

        before = strays()
        res = download_one(data_url, att, "Teslo_Cancer_2026", 1)
        check("download_one writes <slug>_fig_<N>.<ext> without echoing data",
              (res["ok"], res["filename"], res["url"]),
              (True, "Teslo_Cancer_2026_fig_1.png",
               "data:image/png;base64,<payload omitted>"))
        check("...inside the attachments folder",
              os.path.isfile(os.path.join(att, "Teslo_Cancer_2026_fig_1.png")),
              True)
        check("...world-readable, not mkstemp's 0600",
              oct(os.stat(res["path"]).st_mode & 0o777), oct(0o644))
        check("...and leaves no temp file behind", strays() - before, set())
        # the occupied-slot refusal: `shutil.move` replaces silently, so a
        # re-run with the wrong --start destroyed the figures already filed
        res2 = download_one(data_url, att, "Teslo_Cancer_2026", 1)
        check("a taken figure slot is refused, not overwritten",
              (res2["ok"], "already exists" in (res2["error"] or "")),
              (False, True))
        check("...and the file that was there is untouched",
              open(os.path.join(att, "Teslo_Cancer_2026_fig_1.png"), "rb").read(),
              _PNG)
        missing_owner = download_one(data_url, att, "Teslo_Cancer_2026", 1,
                                     overwrite=True)
        check("--overwrite without exact clipping-note evidence is refused",
              (missing_owner["ok"], "--owner-note" in (missing_owner["error"] or ""),
               open(os.path.join(att, "Teslo_Cancer_2026_fig_1.png"), "rb").read()),
              (False, True, _PNG))
        foreign_articles = os.path.join(tmp, "other-vault", "Articles")
        os.makedirs(foreign_articles)
        foreign_owner = os.path.join(foreign_articles, "Teslo_Cancer_2026.md")
        with open(foreign_owner, "w", encoding="utf-8") as fh:
            fh.write("---\nsources:\n  - https://example.com/other\n---\n"
                     "![[Teslo_Cancer_2026_fig_1.png]]\n")
        foreign = download_one(data_url, att, "Teslo_Cancer_2026", 1,
                               overwrite=True, owner_note=foreign_owner)
        check("a similarly named note in another vault cannot authorize overwrite",
              (foreign["ok"], "this Sources/Images vault" in
               (foreign["error"] or "")), (False, True))
        image_alias = os.path.join(tmp, "images-alias")
        try:
            os.symlink(att, image_alias)
        except (OSError, NotImplementedError):
            pass
        else:
            before_alias_attempt = open(os.path.join(
                att, "Teslo_Cancer_2026_fig_1.png"), "rb").read()
            alias_foreign = download_one(
                data_url, image_alias, "Teslo_Cancer_2026", 1,
                overwrite=True, owner_note=foreign_owner)
            check("a symlink alias cannot hide the canonical image vault from owner binding",
                  (alias_foreign["ok"], "this Sources/Images vault" in
                   (alias_foreign["error"] or ""),
                   open(os.path.join(att, "Teslo_Cancer_2026_fig_1.png"),
                        "rb").read()),
                  (False, True, before_alias_attempt))

        identity_owner = current_owner(att, "Teslo_Cancer_2026")
        real_realpath = os.path.realpath

        def parent_case_variant(path):
            resolved = real_realpath(path)
            if os.path.abspath(path) == os.path.abspath(articles):
                return resolved.swapcase()
            return resolved

        with patch.object(os.path, "realpath", side_effect=parent_case_variant):
            identity_evidence = _load_clipping_owner(
                identity_owner, "Teslo_Cancer_2026", att)
        check("owner binding compares Articles directory identity, not realpath spelling",
              identity_evidence["path"], os.path.abspath(identity_owner))
        inert_owner = clipping_note(
            "Teslo_Cancer_2026", (), body_prefix=(
                "\n```md\n![[Teslo_Cancer_2026_fig_1.png]]\n```\n"
                "<!-- ![[Teslo_Cancer_2026_fig_1.png]] -->\n"))
        inert = download_one(data_url, att, "Teslo_Cancer_2026", 1,
                             overwrite=True, owner_note=inert_owner)
        check("embed-shaped text in code or comments cannot claim an attachment",
              (inert["ok"], "not an exact rendered" in (inert["error"] or "")),
              (False, True))
        wrong_source_owner = clipping_note(
            "Teslo_Cancer_2026", ("Teslo_Cancer_2026_fig_1.png",),
            source="[[Sources/PDFs/Teslo_Cancer_2026.pdf]]")
        wrong_source = download_one(data_url, att, "Teslo_Cancer_2026", 1,
                                    overwrite=True,
                                    owner_note=wrong_source_owner)
        check("a PDF wikilink cannot make a note a clipping-image owner",
              (wrong_source["ok"], "HTTP(S) URL" in (wrong_source["error"] or "")),
              (False, True))
        legacy_owner = os.path.join(articles, "Teslo_Cancer_2026.md")
        with open(legacy_owner, "w", encoding="utf-8") as fh:
            fh.write("---\nsource: https://example.com/legacy\n---\n"
                     "![[Teslo_Cancer_2026_fig_1.png]]\n")
        legacy = download_one(data_url, att, "Teslo_Cancer_2026", 1,
                              overwrite=True, owner_note=legacy_owner)
        check("legacy source fallback alone cannot authorize a destructive image action",
              (legacy["ok"], "first current sources item" in
               (legacy["error"] or "")), (False, True))
        check("--overwrite is what replaces it",
              download_one(data_url, att, "Teslo_Cancer_2026", 1,
                           overwrite=True,
                           owner_note=current_owner(
                               att, "Teslo_Cancer_2026"))["ok"], True)
        # A failed cross-device move used to remove the previous good image.
        # Simulate an interrupted stage copy after it wrote bytes. The complete
        # private download is retained and named in the result; no public path
        # is exposed and no previous image changes.
        real_snapshot = _stable_regular_snapshot

        def interrupted_snapshot(path, copy_to=None, copy_mode=None):
            if copy_to is None:
                return real_snapshot(path)
            if path.endswith(".md"):
                return real_snapshot(path, copy_to=copy_to, copy_mode=copy_mode)
            with open(copy_to, "xb") as fh:
                fh.write(b"incomplete")
            raise OSError(errno.ENOSPC, "injected disk-full copy")

        keep_image = os.path.join(att, "Teslo_Cancer_2026_fig_1.png")
        image_owner = current_owner(att, "Teslo_Cancer_2026")
        with patch.dict(globals(), _stable_regular_snapshot=interrupted_snapshot):
            failed_replace = download_one(data_url, att, "Teslo_Cancer_2026", 1,
                                          overwrite=True,
                                          owner_note=image_owner)
            failed_new = download_one(data_url, att, "Teslo_Cancer_2026", 99)
        check("a failed overwrite preserves the previous complete download",
              (failed_replace["ok"], os.path.exists(keep_image)
               and open(keep_image, "rb").read()), (False, _PNG))
        check("an interrupted new download exposes no final figure",
              (failed_new["ok"], _glob_slug(att, "Teslo_Cancer_2026", "_fig_99.*")),
              (False, []))
        retained_scratch = [failed_replace.get("scratch"),
                            failed_new.get("scratch")]
        check("failed stage copies retain and report their complete downloads",
              [(bool(path and os.path.isfile(path)),
                open(path, "rb").read() if path and os.path.isfile(path) else None)
               for path in retained_scratch],
              [(True, _PNG), (True, _PNG)])
        for path in retained_scratch:
            os.remove(path)
        check("failed publications leave no staging directories",
              glob.glob(os.path.join(os.path.dirname(att), ".clipping-stage.*")), [])

        no_link_source = touch(os.path.join(tmp, "no-hard-link-source.png"), _PNG)
        no_link_target = os.path.join(att, "No_Hard_Link_2026_fig_1.png")

        def unavailable_link(source, target, *args, **kwargs):
            raise LinkUnavailable(
                source, target,
                OSError(errno.ENOTSUP, "injected filesystem has no hard links"))

        with patch.dict(globals(), publish_new=unavailable_link):
            no_link_result = place_file(
                no_link_source, att, "No_Hard_Link_2026", 1)
        check("a hard-link refusal retains and reports the original complete source",
              (no_link_result["ok"],
               "LinkUnavailable" in (no_link_result["error"] or ""),
               no_link_source in (no_link_result["error"] or ""),
               ".clipping-stage." in (no_link_result["error"] or ""),
               no_link_result["source"], open(no_link_source, "rb").read(),
               os.path.lexists(no_link_target),
               glob.glob(os.path.join(os.path.dirname(att),
                                      ".clipping-stage.*"))),
              (False, True, True, False, no_link_source, _PNG, False, []))

        # Publication authorization belongs to the exact source and target
        # snapshots, not merely their pathnames. Exercise the gaps on both
        # sides of the shared displacement protocol.
        late_src = touch(os.path.join(tmp, "late-target-source.png"), _PNG)
        late_target = touch(os.path.join(att, "Late_Target_2026_fig_1.png"),
                            b"planned predecessor")

        def replace_target_before_publish():
            os.unlink(late_target)
            touch(late_target, b"later editor save")

        try:
            _publish_file(late_src, late_target, True,
                          os.path.dirname(att), 0o644,
                          replace_target_before_publish)
            late_error = None
        except PublicationConflict as exc:
            late_error = str(exc)
        check("overwrite refuses a target replaced after its snapshot",
              bool(late_error), True)
        check("the late target and unpublished source both survive",
              (open(late_target, "rb").read(), open(late_src, "rb").read(),
               bool(late_error and ("changed" in late_error
                                    or "predecessor" in late_error))),
              (b"later editor save", _PNG, True))

        mode_src = touch(os.path.join(tmp, "mode-source.png"), _PNG)
        mode_target = touch(os.path.join(att, "Mode_Target_2026_fig_1.png"),
                            b"old")
        os.chmod(mode_target, 0o640)
        _publish_file(mode_src, mode_target, True,
                      staging_parent=os.path.dirname(att))
        check("an overwrite preserves the predecessor's permission bits",
              (open(mode_target, "rb").read(),
               stat.S_IMODE(os.stat(mode_target).st_mode),
               os.path.lexists(mode_src)),
              (_PNG, 0o640, False))

        readback_src = touch(os.path.join(tmp, "readback-source.png"), _PNG)
        readback_target = touch(
            os.path.join(att, "Readback_Target_2026_fig_1.png"), b"old bytes")
        injected_readback = {"done": False}

        def mutate_public_readback(path, copy_to=None, copy_mode=None):
            if (copy_to is None and os.path.abspath(path) == readback_target
                    and not injected_readback["done"]
                    and os.path.isfile(path)
                    and open(path, "rb").read() == _PNG):
                injected_readback["done"] = True
                with open(path, "wb") as fh:
                    fh.write(b"later in-place edit")
            return real_snapshot(path, copy_to=copy_to, copy_mode=copy_mode)

        with patch.dict(globals(),
                        _stable_regular_snapshot=mutate_public_readback):
            try:
                _publish_file(readback_src, readback_target, True,
                              staging_parent=os.path.dirname(att))
                readback_error = None
            except PublicationConflict as exc:
                readback_error = exc
        recovered_old = (readback_error.recovery_path
                         if readback_error is not None else None)
        check("a post-link editor save is retained and the predecessor is recovered",
              (bool(readback_error), open(readback_target, "rb").read(),
               open(readback_src, "rb").read(),
               open(recovered_old, "rb").read()
               if recovered_old and os.path.isfile(recovered_old) else None),
              (True, b"later in-place edit", _PNG, b"old bytes"))

        slot_src = touch(os.path.join(tmp, "slot-source.png"), _PNG)
        slot_target = os.path.join(att, "Late_Slot_2026_fig_1.png")
        slot_twin = os.path.join(att, "Late_Slot_2026_fig_1.webp")

        def create_slot_twin():
            touch(slot_twin, b"late extension twin")
            _refuse_existing(att, "Late_Slot_2026", 1, True, "png")

        raises("a late extension twin rolls a new publication back",
               _publish_file, slot_src, slot_target, False,
               os.path.dirname(att), 0o644, None, create_slot_twin)
        check("the late twin survives while our target and source return to pre-run state",
              (os.path.lexists(slot_target), open(slot_twin, "rb").read(),
               open(slot_src, "rb").read()),
              (False, b"late extension twin", _PNG))

        slot_replace_src = touch(os.path.join(tmp, "slot-replace-source.png"),
                                 _PNG)
        slot_replace_target = touch(
            os.path.join(att, "Late_Replace_2026_fig_1.png"), b"old figure")
        slot_replace_twin = os.path.join(
            att, "Late_Replace_2026_fig_1.webp")

        def create_replace_twin():
            touch(slot_replace_twin, b"late twin")
            _refuse_existing(att, "Late_Replace_2026", 1, True, "png")

        raises("a late extension twin restores an overwritten predecessor",
               _publish_file, slot_replace_src, slot_replace_target, True,
               os.path.dirname(att), 0o644, None, create_replace_twin)
        check("slot rollback preserves predecessor, twin, and source",
              (open(slot_replace_target, "rb").read(),
               open(slot_replace_twin, "rb").read(),
               open(slot_replace_src, "rb").read()),
              (b"old figure", b"late twin", _PNG))

        changed_source = touch(os.path.join(tmp, "changed-source.png"), _PNG)
        changed_target = os.path.join(att, "Changed_Source_2026_fig_1.png")
        real_remove_expected = remove_expected
        changed_once = {"done": False}

        def replace_source_before_cleanup(target, *args, **kwargs):
            if target == changed_source and not changed_once["done"]:
                changed_once["done"] = True
                os.unlink(changed_source)
                touch(changed_source, b"later source occupant")
            return real_remove_expected(target, *args, **kwargs)

        with patch.dict(globals(), remove_expected=replace_source_before_cleanup):
            cleanup_warning = _publish_file(
                changed_source, changed_target,
                staging_parent=os.path.dirname(att))
        check("source cleanup removes only the copied snapshot",
              (open(changed_target, "rb").read(),
               open(changed_source, "rb").read(),
               "retained" in (cleanup_warning or "")),
              (_PNG, b"later source occupant", True))
        # An explicit overwrite grants replacement of this clipping's figure,
        # never a file another producer has recorded as its own.
        pdf_owned = os.path.join(tmp, "pdf-owned")
        os.makedirs(pdf_owned)
        owned_name = "Doe_Paper_2026_fig_1.png"
        owned_file = touch(os.path.join(pdf_owned, owned_name), _PNG)
        with open(os.path.join(pdf_owned, MANIFEST_FILE), "w",
                  encoding="utf-8") as fh:
            fh.write(owned_name + "\t" + hashlib.sha256(_PNG).hexdigest() + "\n")
        pdf_owner = current_owner(pdf_owned, "Doe_Paper_2026")
        blocked_download = download_one(data_url, pdf_owned, "Doe_Paper_2026", 1,
                                        overwrite=True, owner_note=pdf_owner)
        owned_render = touch(os.path.join(tmp, "owned-render.png"), _PNG)
        blocked_place = place_file(owned_render, pdf_owned, "Doe_Paper_2026", 1,
                                   overwrite=True, owner_note=pdf_owner)
        check("overwrite never replaces a PDF-manifest-owned figure",
              (blocked_download["ok"], blocked_place["ok"],
               open(owned_file, "rb").read(), os.path.exists(owned_render)),
              (False, False, _PNG, True))
        check("recorded PDF figures cannot be renamed by a clipping either",
              [row["ok"] for row in checked_rename(
                  pdf_owned, "Doe_Paper_2026", "New_Note_2026")],
              [False])
        with open(os.path.join(pdf_owned, MANIFEST_FILE), "w",
                  encoding="utf-8") as fh:
            fh.write("not a valid ownership record\n")
        check("a malformed ownership manifest does not authorize a write",
              download_one(data_url, pdf_owned, "New_Clipping_2026", 1)["ok"], False)
        # the slot is `<slug>_fig_<N>.*`, not one filename: a .webp at the same
        # index is the same slot, or the extension-twin comes back
        touch(os.path.join(att, "Teslo_Cancer_2026_fig_2.webp"))
        check("a different extension at the same index is the same slot",
              download_one(data_url, att, "Teslo_Cancer_2026", 2)["ok"], False)
        old_webp = os.path.join(att, "Teslo_Cancer_2026_fig_2.webp")
        render_png = touch(os.path.join(tmp, "changed-format.png"), _PNG)
        format_owner = current_owner(att, "Teslo_Cancer_2026")
        replaced = download_one(data_url, att, "Teslo_Cancer_2026", 2,
                                overwrite=True, owner_note=format_owner)
        placed = place_file(render_png, att, "Teslo_Cancer_2026", 2,
                            overwrite=True, owner_note=format_owner)
        check("overwrite cannot create extension twins on either publication path",
              (replaced["ok"], placed["ok"], open(old_webp, "rb").read(),
               os.path.exists(render_png),
               os.path.exists(os.path.join(att, "Teslo_Cancer_2026_fig_2.png"))),
              (False, False, b"x", True, False))
        misleading = "data:image/png;base64," + base64.b64encode(
            b"\x00\xffnot an image\x01").decode("ascii")
        nonimage = download_one(misleading, att, "Teslo_Cancer_2026", 70)
        check("arbitrary binary data with an image MIME label never lands",
              (nonimage["ok"], _glob_slug(att, "Teslo_Cancer_2026", "_fig_70.*")),
              (False, []))
        bracketed = os.path.join(tmp, "Vault [research]", "Images")
        os.makedirs(bracketed)
        lower_image = touch(os.path.join(bracketed, "teslo_cancer_2026_fig_1.webp"))
        check("case variants in a bracketed vault path still occupy the slot",
              download_one(data_url, bracketed, "Teslo_Cancer_2026", 1)["ok"], False)
        check("the occupied file is retained", open(lower_image, "rb").read(), b"x")
        # a non-image is a failure, not a .png in the vault
        res = download_one("data:text/html;base64," + base64.b64encode(
            b"<!DOCTYPE html><html>nope</html>").decode("ascii"),
            att, "Teslo_Cancer_2026", 7)
        check("a non-image data: URI fails rather than landing as .png",
              (res["ok"], os.path.exists(os.path.join(
                  att, "Teslo_Cancer_2026_fig_7.png"))), (False, False))
        # ...and end to end with the header LYING about it, which is the shape
        # a CDN error body actually arrives in: `Content-Type: image/png` on a
        # JSON document. This used to land in the vault as a .png, reported ok.
        res = download_one("data:image/png;base64," + base64.b64encode(
            b'{"error": "not found"}').decode("ascii"),
            att, "Teslo_Cancer_2026", 10)
        check("a JSON body served as image/png fails, and writes nothing",
              (res["ok"], _glob_slug(att, "Teslo_Cancer_2026", "_fig_10.*")),
              (False, []))
        check("...and the error names what the bytes actually looked like",
              "a JSON body" in (res["error"] or ""), True)
        # ...end to end for the two parameterised data: URI forms (RFC 2397).
        res = download_one("data:image/png;charset=utf-8;base64," + b64,
                           att, "Teslo_Cancer_2026", 30)
        check("download_one accepts a parameterised base64 data: URI",
              (res["ok"], res["filename"]),
              (True, "Teslo_Cancer_2026_fig_30.png"))
        res = download_one(
            "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg'/>",
            att, "Teslo_Cancer_2026", 31)
        check("...and the ;utf8 inline-SVG form lands by its bytes, as .svg",
              (res["ok"], res["filename"]),
              (True, "Teslo_Cancer_2026_fig_31.svg"))
        active_svg = (
            "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' "
            "onload='bad()'/>")
        res = download_one(active_svg, att, "Teslo_Cancer_2026", 32)
        check("an active SVG is refused before vault publication",
              (res["ok"], "event-handler" in (res["error"] or ""),
               _glob_slug(att, "Teslo_Cancer_2026", "_fig_32.*"), res["url"]),
              (False, True, [],
               "data:image/svg+xml;utf8,<payload omitted>"))
        # --- fetch / place: the Lottie path, which used to bypass all of this -
        # A heredoc did its own urlopen and its own os.replace into
        # Sources/Images: no scheme allowlist, no private-host refusal, no
        # size or wall-clock cap, no slug validation, no containment check and
        # no occupied-slot refusal — and the folder is shared with two other
        # skills, so the GIF it overwrote was not necessarily this note's.
        for url, label in (("file:///etc/passwd", "file:"),
                           ("ftp://example.com/a.json", "ftp:"),
                           ("javascript:alert(1)", "javascript:")):
            check("fetch refuses %s, like download does" % label,
                  fetch_source(url)["ok"], False)
        anim = b'{"v":"5.7","w":100,"h":100,"fr":30,"ip":0,"op":60,"layers":[]}'
        got = fetch_source("data:application/json;base64,"
                           + base64.b64encode(anim).decode("ascii"))
        check("fetch accepts a Lottie JSON source and identifies its format",
              (got["ok"], got["source_format"],
               open(got["path"], "rb").read()), (True, "json", anim))
        check("...to a path outside the attachments folder",
              os.path.realpath(got["path"]).startswith(
                  os.path.realpath(att) + os.sep), False)
        check("...under the same size cap as download",
              fetch_source("data:application/json;base64,"
                           + base64.b64encode(anim).decode("ascii"),
                           max_bytes=10)["ok"], False)
        os.remove(got["path"])
        for payload, label in ((b"<!doctype html><html>", "HTML"),
                               (b"MZ\x90\x00", "an executable"),
                               (b'{"message":"not an animation"}',
                                "unrelated JSON")):
            refused = fetch_source(
                "data:application/octet-stream;base64,"
                + base64.b64encode(payload).decode("ascii"))
            check("fetch refuses %s rather than accepting arbitrary bytes" % label,
                  (refused["ok"], refused["path"]), (False, None))

        packed = os.path.join(tmp, "valid.lottie")
        with zipfile.ZipFile(packed, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "manifest.json",
                '{"version":"1","animations":[{"id":"a"}]}')
            archive.writestr("animations/a.json", anim)
        packed_bytes = open(packed, "rb").read()
        dot = fetch_source(
            "data:application/octet-stream;base64,"
            + base64.b64encode(packed_bytes).decode("ascii"))
        check("fetch accepts a dotLottie ZIP containing bounded animation JSON",
              (dot["ok"], dot["source_format"]), (True, "dotlottie"))
        os.remove(dot["path"])

        duplicate_manifest = os.path.join(tmp, "duplicate-manifest.lottie")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(
                    duplicate_manifest, "w", zipfile.ZIP_DEFLATED) as archive:
                # The old validator selected this first occurrence by iterating
                # infolist(), while the renderer's getinfo() selected the last.
                archive.writestr(
                    "manifest.json",
                    '{"version":"1","animations":[{"id":"a"}]}')
                archive.writestr("animations/a.json", anim)
                archive.writestr(
                    "manifest.json",
                    '{"version":"1","animations":[{"id":"b"}]}')
                archive.writestr("animations/b.json", anim)
        raises("dotLottie refuses duplicate manifest member names",
               _validate_lottie_source, duplicate_manifest, DEFAULT_MAX_BYTES)

        duplicate_animation = os.path.join(tmp, "duplicate-animation.lottie")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(
                    duplicate_animation, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(
                    "manifest.json",
                    '{"version":"1","animations":[{"id":"a"}]}')
                archive.writestr("animations/a.json", anim)
                archive.writestr(
                    "animations/a.json", anim.replace(b'"w":100', b'"w":1'))
        raises("dotLottie refuses duplicate selected-animation member names",
               _validate_lottie_source, duplicate_animation, DEFAULT_MAX_BYTES)

        selected_pack = os.path.join(tmp, "selected-v2.lottie")
        selected_manifest = {
            "version": "2", "initial": {"animation": "chosen"},
            "animations": [{"id": "decoy"}, {"id": "chosen"}],
            "themes": [{"id": "first-in-zip"}],
        }
        with zipfile.ZipFile(selected_pack, "w", zipfile.ZIP_DEFLATED) as archive:
            # Archive order is adversarial: theme/state metadata appears before
            # two animations, while the manifest selects the second animation.
            archive.writestr("t/first-in-zip.json", '{"rules":[]}')
            archive.writestr("a/decoy.json", anim.replace(b'"w":100', b'"w":1'))
            archive.writestr("a/chosen.json", anim)
            archive.writestr("manifest.json", json.dumps(selected_manifest))
        selected_bytes = open(selected_pack, "rb").read()
        selected = fetch_source(
            "data:application/zip;base64,"
            + base64.b64encode(selected_bytes).decode("ascii"))
        check("dotLottie selection follows v2 initial.animation, not ZIP order",
              (selected["ok"], _dotlottie_animation_path(selected_manifest)),
              (True, "a/chosen.json"))
        os.remove(selected["path"])
        check("dotLottie v1 activeAnimationId selects its manifest animation",
              _dotlottie_animation_path({
                  "version": "1.0", "activeAnimationId": "two",
                  "animations": [{"id": "one"}, {"id": "two"}],
              }), "animations/two.json")

        missing_pack = os.path.join(tmp, "missing-selected.lottie")
        with zipfile.ZipFile(missing_pack, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("a/decoy.json", anim)
            archive.writestr("manifest.json", json.dumps({
                "version": "2", "initial": {"animation": "real"},
                "animations": [{"id": "real"}],
            }))
        missing_bytes = open(missing_pack, "rb").read()
        missing = fetch_source(
            "data:application/zip;base64,"
            + base64.b64encode(missing_bytes).decode("ascii"))
        check("an unrelated Lottie JSON cannot satisfy a missing manifest target",
              (missing["ok"], missing["path"]), (False, None))
        raises("a manifest animation id cannot escape its versioned directory",
               _dotlottie_animation_path,
               {"version": "2", "animations": [{"id": "../evil"}]})

        arbitrary_zip = os.path.join(tmp, "arbitrary.zip")
        with zipfile.ZipFile(arbitrary_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("payload.txt", "not an animation")
        arbitrary_zip_bytes = open(arbitrary_zip, "rb").read()
        refused = fetch_source(
            "data:application/zip;base64,"
            + base64.b64encode(arbitrary_zip_bytes).decode("ascii"))
        check("fetch refuses an arbitrary ZIP that is not dotLottie",
              (refused["ok"], refused["path"]), (False, None))

        out_path = os.path.join(tmp, "anim.json")
        boundary_vault = os.path.join(tmp, "boundary-vault")
        os.makedirs(boundary_vault)
        touch(out_path, b"mine")
        check("fetch refuses an --out that already exists",
              fetch_source("data:application/json,x", out_path,
                           vault=boundary_vault)["ok"], False)
        check("...and leaves it untouched", open(out_path, "rb").read(), b"mine")
        bad = fetch_source("file:///not-a-permitted-source", out_path,
                           overwrite=True, vault=boundary_vault)
        check("fetch validation failure never deletes an overwrite destination",
              (bad["ok"], os.path.exists(out_path) and open(out_path, "rb").read()),
              (False, b"mine"))
        bad = fetch_source("data:text/html,%3Chtml%3E", out_path,
                           overwrite=True, vault=boundary_vault)
        check("a non-Lottie response never replaces an overwrite destination",
              (bad["ok"], os.path.exists(out_path) and open(out_path, "rb").read()),
              (False, b"mine"))
        def interrupted_fetch(url, destination, *args, **kwargs):
            touch(destination, b"partial response")
            raise TimeoutError("injected transfer interruption")
        new_out = os.path.join(tmp, "new-animation.json")
        with patch.dict(globals(), {"_fetch_to_path": interrupted_fetch}):
            new_failed = fetch_source("https://example.com/anim.json", new_out,
                                      vault=boundary_vault)
            old_failed = fetch_source("https://example.com/anim.json", out_path,
                                      overwrite=True, vault=boundary_vault)
        check("an interrupted explicit fetch leaves no retry-blocking partial file",
              (new_failed["ok"], os.path.exists(new_out)), (False, False))
        check("an interrupted fetch leaves the previous source byte-identical",
              (old_failed["ok"], os.path.exists(out_path)
               and open(out_path, "rb").read()), (False, b"mine"))
        check("retrying an interrupted fetch works without overwrite",
              fetch_source("data:application/json;base64,"
                           + base64.b64encode(anim).decode("ascii"),
                           new_out, vault=boundary_vault)["ok"], True)
        inside_out = os.path.join(boundary_vault, "animation.json")
        check("an explicit fetch output cannot land inside the vault",
              (fetch_source("data:application/json;base64,"
                            + base64.b64encode(anim).decode("ascii"),
                            inside_out, vault=boundary_vault)["ok"],
               os.path.lexists(inside_out)), (False, False))

        # `place` is the write half, and it is the SAME guards as `download`.
        gif = b"GIF89a\x01\x00\x01\x00\x00\xff\x00,"
        render = touch(os.path.join(tmp, "render.gif"), gif)
        res = place_file(render, att, "Teslo_Cancer_2026", 20)
        check("place files a rendered GIF as <slug>_fig_<N>.<ext>",
              (res["ok"], res["filename"]),
              (True, "Teslo_Cancer_2026_fig_20.gif"))
        check("...moving it, so no twin is left at the render path",
              os.path.exists(render), False)
        check("...world-readable like a downloaded figure",
              oct(os.stat(res["path"]).st_mode & 0o777), oct(0o644))
        # the occupied slot: `os.replace` in the heredoc overwrote a previous
        # run's GIF and exited 0
        render = touch(os.path.join(tmp, "render.gif"), b"GIF89a\x02\x00,")
        res = place_file(render, att, "Teslo_Cancer_2026", 20)
        check("place refuses an occupied figure slot, as download does",
              (res["ok"], "already exists" in (res["error"] or "")),
              (False, True))
        check("...and the file that was there is untouched",
              open(os.path.join(att, "Teslo_Cancer_2026_fig_20.gif"),
                   "rb").read(), gif)
        check("...while --overwrite is what replaces it",
              place_file(render, att, "Teslo_Cancer_2026", 20,
                         overwrite=True,
                         owner_note=current_owner(
                             att, "Teslo_Cancer_2026"))["ok"], True)
        replacement = touch(os.path.join(tmp, "replacement.gif"), gif)
        keep_gif = os.path.join(att, "Teslo_Cancer_2026_fig_20.gif")
        prior_gif = open(keep_gif, "rb").read()
        gif_owner = current_owner(att, "Teslo_Cancer_2026")
        with patch.dict(globals(), _stable_regular_snapshot=interrupted_snapshot):
            failed_place = place_file(replacement, att, "Teslo_Cancer_2026", 20,
                                      overwrite=True, owner_note=gif_owner)
        check("a failed rendered-image replacement preserves the previous GIF",
              (failed_place["ok"], os.path.exists(keep_gif)
               and open(keep_gif, "rb").read()), (False, prior_gif))
        check("...and leaves the render available for retry",
              open(replacement, "rb").read(), gif)
        # the extension comes from the BYTES, not from the name the renderer
        # chose: a blank or failed render named `.gif` is not a GIF
        html = touch(os.path.join(tmp, "failed.gif"), b"<!DOCTYPE html><html>")
        res = place_file(html, att, "Teslo_Cancer_2026", 21)
        check("place refuses a non-image whatever the filename says",
              (res["ok"], _glob_slug(att, "Teslo_Cancer_2026", "_fig_21.*")),
              (False, []))
        check("...naming what the bytes looked like",
              "an HTML page" in (res["error"] or ""), True)
        png = touch(os.path.join(tmp, "actually.gif"), _PNG)
        check("...and a PNG named .gif is filed by its bytes",
              place_file(png, att, "Teslo_Cancer_2026", 22)["filename"],
              "Teslo_Cancer_2026_fig_22.png")
        changing_render = touch(os.path.join(tmp, "changing-render.gif"), gif)
        real_publish_file = _publish_file

        def change_after_sniff(src, final, *args, **kwargs):
            touch(src, b"late non-image replacement")
            return real_publish_file(src, final, *args, **kwargs)

        with patch.dict(globals(), {"_publish_file": change_after_sniff}):
            changed = place_file(
                changing_render, att, "Teslo_Cancer_2026", 25)
        check("place refuses a source that changes after byte sniffing",
              (changed["ok"], os.path.lexists(os.path.join(
                  att, "Teslo_Cancer_2026_fig_25.gif"))), (False, False))
        check("...and preserves the changed render for inspection or retry",
              open(changing_render, "rb").read(), b"late non-image replacement")
        # slug validation and containment, on the placement path too
        render = touch(os.path.join(tmp, "render2.gif"), gif)
        check("place refuses a slug that is a path",
              place_file(render, att, "../escape", 23)["ok"], False)
        check("place refuses an empty slug",
              place_file(render, att, "  ", 23)["ok"], False)
        check("...and the render is still there, not consumed by a refusal",
              os.path.exists(render), True)
        # references/images.md item 4: nothing half-written may sit in the vault
        inside = touch(os.path.join(att, "scratch.gif"), gif)
        res = place_file(inside, att, "Teslo_Cancer_2026", 24)
        check("place refuses a source inside the attachments folder",
              (res["ok"], "inside the attachments folder" in (res["error"] or "")),
              (False, True))
        if os.path.exists(inside):       # a refusal leaves it where it was
            os.remove(inside)

        case_alias_source = touch(os.path.join(att, "case-alias-scratch.gif"), gif)
        real_realpath = os.path.realpath

        def case_preserving_realpath(path):
            resolved = real_realpath(path)
            if os.path.abspath(path) == case_alias_source:
                # Model the default-APFS behavior behind the regression:
                # identity is shared, but realpath preserves a different path
                # spelling than the one used for --attachments.
                return os.path.join(os.path.dirname(resolved).swapcase(),
                                    os.path.basename(resolved))
            return resolved

        with patch.object(os.path, "realpath", side_effect=case_preserving_realpath):
            case_alias_result = place_file(
                case_alias_source, att, "Teslo_Cancer_2026", 24)
        check("place compares ancestor identity rather than case-sensitive realpaths",
              (case_alias_result["ok"], os.path.isfile(case_alias_source),
               "inside the attachments folder" in
               (case_alias_result["error"] or "")),
              (False, True, True))
        os.remove(case_alias_source)

        res = download_one("file:///etc/passwd", att, "Teslo_Cancer_2026", 8)
        check("download_one refuses a file: URL", res["ok"], False)
        res = download_one(data_url, att, "../escape", 9)
        check("download_one refuses a slug that is a path", res["ok"], False)
        res = download_one(data_url, att, "Teslo_Cancer_2026", 0)
        check("download_one refuses figure zero and writes no slot",
              (res["ok"], _glob_slug(att, "Teslo_Cancer_2026", "_fig_0.*")),
              (False, []))
        zero_render = touch(os.path.join(tmp, "zero-index.gif"), gif)
        res = place_file(zero_render, att, "Teslo_Cancer_2026", 0)
        check("place refuses figure zero without consuming the render",
              (res["ok"], os.path.exists(zero_render)), (False, True))
        check("no failed download leaves its temp file behind",
              strays() - before, set())

        # --- rename_slug ----------------------------------------------------
        def figures(slug, names=("_fig_1.png", "_fig_2.png", "_fig_3.png")):
            # a fresh folder per fixture: a shared one carries the previous
            # case's renames into the next one's assertions
            folder = tempfile.mkdtemp(prefix="rename.", dir=tmp)
            for n in names:
                touch(os.path.join(folder, slug + n), _PNG)
            return folder

        missing_guard = figures("Needs_Ownership_2025", ("_fig_1.png",))
        raises("rename refuses to run without the recursive PDF ownership inventory",
               rename_slug, missing_guard, "Needs_Ownership_2025", "New_Slug_2026")
        raises("rename also requires the exact clipping owner note",
               rename_slug, missing_guard, "Needs_Ownership_2025", "New_Slug_2026",
               sources=sources)

        def canonical_rename_fixture(label, old_slug, names=("_fig_1.png",)):
            vault = tempfile.mkdtemp(prefix="dependency-%s." % label, dir=tmp)
            image_dir = os.path.join(vault, "Sources", "Images")
            pdf_dir = os.path.join(vault, "Sources", "PDFs")
            note_dir = os.path.join(vault, "Articles")
            os.makedirs(image_dir)
            os.makedirs(pdf_dir)
            os.makedirs(note_dir)
            embeds = []
            for tail in names:
                name = old_slug + tail
                touch(os.path.join(image_dir, name), _PNG)
                embeds.append(name)
            owner_path = os.path.join(note_dir, old_slug + ".md")
            with open(owner_path, "w", encoding="utf-8") as fh:
                fh.write("---\nsources:\n  - https://example.com/%s\n---\n" % label)
                for name in embeds:
                    fh.write("![[%s]]\n" % name)
            return vault, image_dir, pdf_dir, owner_path, embeds

        # A logical vault may symlink its whole Sources/ directory to storage
        # outside the vault. Owner binding must use the logical Articles/
        # identity in that layout, while an alias between two complete vaults
        # remains ambiguous and cannot borrow ownership evidence.
        linked_vault = tempfile.mkdtemp(prefix="linked-sources-vault.", dir=tmp)
        linked_store = tempfile.mkdtemp(prefix="linked-sources-store.", dir=tmp)
        linked_articles = os.path.join(linked_vault, "Articles")
        linked_sources = os.path.join(linked_store, "Sources")
        os.makedirs(linked_articles)
        os.makedirs(os.path.join(linked_sources, "Images"))
        os.makedirs(os.path.join(linked_sources, "PDFs"))
        linked_supported = True
        try:
            os.symlink(linked_sources, os.path.join(linked_vault, "Sources"),
                       target_is_directory=True)
        except (OSError, NotImplementedError):
            linked_supported = False
        if linked_supported:
            linked_slug = "Linked_Clipping_2025"
            linked_image = linked_slug + "_fig_1.png"
            touch(os.path.join(linked_vault, "Sources", "Images", linked_image),
                  _PNG)
            linked_owner = os.path.join(linked_articles, linked_slug + ".md")
            with open(linked_owner, "w", encoding="utf-8") as fh:
                fh.write("---\nsources:\n  - https://example.com/linked\n---\n"
                         "![[%s]]\n" % linked_image)
            bound = _load_clipping_owner(
                linked_owner, linked_slug,
                os.path.join(linked_vault, "Sources", "Images"))
            check("a symlinked Sources directory binds to the logical vault owner",
                  bound["vault"], os.path.realpath(linked_vault))

            source_vault = tempfile.mkdtemp(prefix="source-complete-vault.", dir=tmp)
            os.makedirs(os.path.join(source_vault, "Articles"))
            os.makedirs(os.path.join(source_vault, "Sources", "Images"))
            alias_vault = tempfile.mkdtemp(prefix="aliased-complete-vault.", dir=tmp)
            os.makedirs(os.path.join(alias_vault, "Articles"))
            try:
                os.symlink(os.path.join(source_vault, "Sources"),
                           os.path.join(alias_vault, "Sources"),
                           target_is_directory=True)
            except (OSError, NotImplementedError):
                alias_supported = False
            else:
                alias_supported = True
            if alias_supported:
                alias_owner = os.path.join(
                    alias_vault, "Articles", linked_slug + ".md")
                with open(alias_owner, "w", encoding="utf-8") as fh:
                    fh.write("---\nsources:\n  - https://example.com/alias\n---\n"
                             "![[%s]]\n" % linked_image)
                raises("an alias between two complete vaults cannot borrow owner evidence",
                       _load_clipping_owner, alias_owner, linked_slug,
                       os.path.join(alias_vault, "Sources", "Images"))

        dep_vault, dep_images, dep_pdfs, dep_owner, dep_names = \
            canonical_rename_fixture("external", "Old_Dependency_2025")
        dep_wiki = os.path.join(dep_vault, "Wiki")
        os.makedirs(dep_wiki)
        dep_reference = os.path.join(dep_wiki, "reference.md")
        with open(dep_reference, "w", encoding="utf-8") as fh:
            fh.write("[[Old_Dependency_2025|old note]]\n"
                     "![[Sources/Images/Old_Dependency_2025_fig_1.png]]\n")
        dependency_report = dependency_status(
            dep_images, dep_owner, "Old_Dependency_2025")
        check("dependency re-probe names every external blocker path and target",
              (dependency_report["ok"], dependency_report["blockers"]),
              (False, [{"path": os.path.realpath(dep_reference),
                        "references": ["Old_Dependency_2025.md",
                                       "Old_Dependency_2025_fig_1.png"]}]))
        blocked_dependency = rename_slug(
            dep_images, "Old_Dependency_2025", "New_Dependency_2026",
            sources=dep_pdfs, owner_note=dep_owner)
        check("external Markdown dependencies refuse every image move",
              ([row["ok"] for row in blocked_dependency],
               os.path.isfile(os.path.join(dep_images, dep_names[0])),
               os.path.realpath(dep_reference) in
               (blocked_dependency[0]["error"] or "")),
              ([False], True, True))
        with open(dep_reference, "w", encoding="utf-8") as fh:
            fh.write("`[[Old_Dependency_2025]]`\n"
                     "<!-- ![[Old_Dependency_2025_fig_1.png]] -->\n")
        check("code and comments do not manufacture dependency blockers",
              dependency_status(dep_images, dep_owner,
                                "Old_Dependency_2025")["blockers"], [])

        handoff_vault, handoff_images, handoff_pdfs, handoff_owner, handoff_names = \
            canonical_rename_fixture("two-phase", "Old_Handoff_2025")
        handoff_new_slug = "New_Handoff_2026"
        handoff_new_owner = os.path.join(
            handoff_vault, "Articles", handoff_new_slug + ".md")
        with open(handoff_new_owner, "w", encoding="utf-8") as fh:
            fh.write("---\nsources:\n  - https://example.com/two-phase\n---\n")
            for name in handoff_names:
                fh.write("![[%s]]\n" % name.replace(
                    "Old_Handoff_2025", handoff_new_slug, 1))
        handoff_wiki = os.path.join(handoff_vault, "Wiki")
        os.makedirs(handoff_wiki)
        handoff_reference = os.path.join(handoff_wiki, "reference.md")
        with open(handoff_reference, "w", encoding="utf-8") as fh:
            fh.write("[[Old_Handoff_2025|old note]]\n"
                     "![[Old_Handoff_2025_fig_1.png]]\n")
        prepared = prepare_slug_rename(
            handoff_images, "Old_Handoff_2025", handoff_new_slug,
            sources=handoff_pdfs, owner_note=handoff_owner,
            new_owner_note=handoff_new_owner)
        handoff_old_image = os.path.join(handoff_images, handoff_names[0])
        handoff_new_image = os.path.join(
            handoff_images, handoff_names[0].replace(
                "Old_Handoff_2025", handoff_new_slug, 1))
        check("prepare publishes an exact new image while old dependencies resolve",
              (prepared["ok"], prepared["dependency"]["ok"],
               os.path.isfile(handoff_old_image),
               os.path.isfile(handoff_new_image),
               open(handoff_old_image, "rb").read(),
               open(handoff_new_image, "rb").read()),
              (True, False, True, True, _PNG, _PNG))
        try:
            finalize_slug_rename(
                handoff_images, "Old_Handoff_2025", handoff_new_slug,
                sources=handoff_pdfs, owner_note=handoff_owner,
                new_owner_note=handoff_new_owner)
            premature_finalize = False
        except ValueError:
            premature_finalize = True
        check("finalize refuses while an old-note or old-image dependency remains",
              (premature_finalize, os.path.isfile(handoff_old_image),
               os.path.isfile(handoff_new_image)), (True, True, True))
        with open(handoff_reference, "w", encoding="utf-8") as fh:
            fh.write("[[New_Handoff_2026|new note]]\n"
                     "![[New_Handoff_2026_fig_1.png]]\n")
        real_remove_expected = remove_expected

        def refuse_before_retirement(*_args, **_kwargs):
            raise PublicationConflict("injected pre-displacement conflict")

        with patch.dict(globals(), remove_expected=refuse_before_retirement):
            try:
                finalize_slug_rename(
                    handoff_images, "Old_Handoff_2025", handoff_new_slug,
                    sources=handoff_pdfs, owner_note=handoff_owner,
                    new_owner_note=handoff_new_owner)
                pre_displacement_error = ""
            except PublicationConflict as exc:
                pre_displacement_error = str(exc)
        check("a pre-displacement finalize conflict is not a false mixed rollback",
              ("rollback was incomplete" in pre_displacement_error,
               os.path.isfile(handoff_old_image),
               os.path.isfile(handoff_new_image)), (False, True, True))

        def refuse_after_restoration(target, _expected, _snapshot, stage_dir,
                                     **_kwargs):
            os.link(target, os.path.join(stage_dir, ".atomic-displaced"))
            raise PublicationConflict("injected conflict after restoration")

        with patch.dict(globals(), remove_expected=refuse_after_restoration):
            try:
                finalize_slug_rename(
                    handoff_images, "Old_Handoff_2025", handoff_new_slug,
                    sources=handoff_pdfs, owner_note=handoff_owner,
                    new_owner_note=handoff_new_owner)
                post_restoration_error = ""
            except PublicationConflict as exc:
                post_restoration_error = str(exc)
        handoff_stage_parent = os.path.dirname(os.path.realpath(handoff_images))
        check("a finalize conflict after atomic restoration cleans private state",
              ("rollback was incomplete" in post_restoration_error,
               os.path.isfile(handoff_old_image),
               os.path.isfile(handoff_new_image),
               [name for name in os.listdir(handoff_stage_parent)
                if name.startswith(".clipping-handoff-retire-")]),
              (False, True, True, []))
        globals()["remove_expected"] = real_remove_expected
        finalized = finalize_slug_rename(
            handoff_images, "Old_Handoff_2025", handoff_new_slug,
            sources=handoff_pdfs, owner_note=handoff_owner,
            new_owner_note=handoff_new_owner)
        check("finalize retires only the exact old copy after a clean re-probe",
              (finalized["ok"], finalized["retired"],
               os.path.lexists(handoff_old_image),
               open(handoff_new_image, "rb").read()),
              (True, 1, False, _PNG))

        nfd_old = unicodedata.normalize("NFD", "Müller_Dependency_2025")
        nfc_new = unicodedata.normalize("NFC", "Müller_Dependency_2025")
        nfd_vault, nfd_images, nfd_pdfs, nfd_owner, nfd_names = \
            canonical_rename_fixture("normalization", nfd_old)
        nfd_ref = os.path.join(nfd_vault, "reference.md")
        with open(nfd_ref, "w", encoding="utf-8") as fh:
            fh.write("![[%s]]\n" % nfd_names[0])
        nfd_result = rename_slug(
            nfd_images, nfd_old, nfc_new,
            sources=nfd_pdfs, owner_note=nfd_owner)
        check("an NFD-to-NFC pathname change still scans external dependencies",
              ([row["ok"] for row in nfd_result],
               os.path.isfile(os.path.join(nfd_images, nfd_names[0]))),
              ([False], True))

        race_vault, race_images, race_pdfs, race_owner, race_names = \
            canonical_rename_fixture("late-reference", "Old_Race_2025")
        race_reference = os.path.join(race_vault, "late.md")
        with open(race_reference, "w", encoding="utf-8") as fh:
            fh.write("No dependency yet.\n")
        real_move = move_noreplace
        inserted_dependency = {"done": False}

        def add_dependency_after_move(src, dst, expected=None, **kwargs):
            moved = real_move(src, dst, expected=expected, **kwargs)
            if not inserted_dependency["done"]:
                inserted_dependency["done"] = True
                with open(race_reference, "w", encoding="utf-8") as fh:
                    fh.write("[[Old_Race_2025]]\n")
            return moved

        with patch.dict(globals(), move_noreplace=add_dependency_after_move):
            race_result = rename_slug(
                race_images, "Old_Race_2025", "New_Race_2026",
                sources=race_pdfs, owner_note=race_owner)
        check("a dependency created during rename rolls the image move back",
              ([row["ok"] for row in race_result],
               os.path.isfile(os.path.join(race_images, race_names[0])),
               os.path.lexists(os.path.join(
                   race_images, "New_Race_2026_fig_1.png")),
               os.path.realpath(race_reference) in
               (race_result[0]["error"] or "")),
              ([False], True, False, True))

        pdf_vault, pdf_images, pdf_sources, pdf_owner, pdf_names = \
            canonical_rename_fixture("linked-pdf", "Linked_PDF_2025")
        outside_pdfs = os.path.join(tmp, "linked-pdf-target")
        os.makedirs(outside_pdfs)
        touch(os.path.join(outside_pdfs, "Linked_PDF_2025.pdf"), b"%PDF-1.7\n")
        try:
            os.symlink(outside_pdfs, os.path.join(pdf_sources, "linked"))
        except (OSError, NotImplementedError):
            pass
        else:
            linked_pdf_result = rename_slug(
                pdf_images, "Linked_PDF_2025", "New_Linked_2026",
                sources=pdf_sources, owner_note=pdf_owner)
            check("PDF ownership inventory follows linked source subfolders",
                  ([row["ok"] for row in linked_pdf_result],
                   os.path.isfile(os.path.join(pdf_images, pdf_names[0]))),
                  ([False], True))

        folder = figures("Old_Slug_2025")
        out = checked_rename(folder, "Old_Slug_2025", "New_Slug_2026")
        check("a clean rename renames the whole set",
              ([e["ok"] for e in out], sorted(os.listdir(folder))),
              ([True, True, True],
               ["New_Slug_2026_fig_1.png", "New_Slug_2026_fig_2.png",
                "New_Slug_2026_fig_3.png"]))
        folder = figures("Old_Slug_2025", ("_fig_1.png", "_fig_2.png"))
        one_file_owner = clipping_note(
            "Old_Slug_2025", ("Old_Slug_2025_fig_1.png",))
        out = rename_slug(folder, "Old_Slug_2025", "New_Slug_2026",
                          sources=sources, owner_note=one_file_owner)
        check("one unattributed same-stem file blocks the whole clipping rename",
              ([entry["ok"] for entry in out], sorted(os.listdir(folder))),
              ([False, False],
               ["Old_Slug_2025_fig_1.png", "Old_Slug_2025_fig_2.png"]))
        check("the unembedded basename is reported as unproven ownership",
              sum("ownership is unproven" in (entry["error"] or "")
                  for entry in out), 1)
        folder = figures("Old_Slug_2025", ("_fig_1.png",))
        # Construct the intentionally pre-convergence test name in two pieces;
        # the convention harness treats literal full filenames as producer
        # examples, while this one is explicitly a consumer migration fixture.
        legacy_missing = "Old_Slug_2025_" + "fig3.jpeg"
        legacy_new = "New_Slug_2026_" + "fig3.jpeg"
        missing_owner = clipping_note(
            "Old_Slug_2025",
            ("Old_Slug_2025_fig_1.png", legacy_missing,
             "Other_Slug_2025_fig_9.png", "Old_Slug_2025_fig_notes.md"))
        out = rename_slug(folder, "Old_Slug_2025", "New_Slug_2026",
                          sources=sources, owner_note=missing_owner)
        check("a missing legacy loose old-slug image embed blocks the whole rename",
              ([entry["ok"] for entry in out], sorted(os.listdir(folder))),
              ([False, False], ["Old_Slug_2025_fig_1.png"]))
        check("the missing embed is a deterministic plan row with its new name",
              [(entry["from"], entry["to"])
               for entry in out if "exact attachment is missing" in
               (entry["error"] or "")],
              [(legacy_missing, legacy_new)])
        check("other-slug and non-image embeds are excluded from the rename inventory",
              [entry["from"] for entry in out],
              ["Old_Slug_2025_fig_1.png", legacy_missing])
        empty_folder = figures("Empty_Slug_2025", ())
        near_miss_missing = "Empty_Slug_2025_" + "figure_7.tif"
        broken_owner = clipping_note(
            "Empty_Slug_2025", (near_miss_missing,))
        out = rename_slug(empty_folder, "Empty_Slug_2025", "New_Slug_2026",
                          sources=sources, owner_note=broken_owner)
        check("an empty folder with a missing embedded figure is reported as failed",
              (len(out), out[0]["ok"], "exact attachment is missing" in
               (out[0]["error"] or "")), (1, False, True))
        check("renaming a stem with no figures is empty, not an error",
              checked_rename(folder, "Nobody_Home_2020", "X_2021"), [])
        folder = figures("müLLER_Trial_2025", ("_fig_1.png",))
        out = checked_rename(folder, unicodedata.normalize("NFD", "Müller_Trial_2025"),
                          "Muller_New_2026")
        check("a different case and Unicode spelling still renames the real figure",
              ([entry["ok"] for entry in out], sorted(os.listdir(folder))),
              ([True], ["Muller_New_2026_fig_1.png"]))
        folder = figures("STRASSE_Trial_2025", ("_fig_1.png",))
        expansion_is_same_name = os.path.exists(
            os.path.join(folder, "Straße_Trial_2025_fig_1.png"))
        out = checked_rename(folder, "Straße_Trial_2025", "New_Trial_2026")
        check("casefold expansion follows only when the filesystem says it is one name",
              ([entry["to"] for entry in out], [entry["ok"] for entry in out],
               sorted(os.listdir(folder))),
              ((["New_Trial_2026_fig_1.png"], [True],
                ["New_Trial_2026_fig_1.png"])
               if expansion_is_same_name else
               ([], [], ["STRASSE_Trial_2025_fig_1.png"])))
        folder = figures("STRASSE_Trial_2025", ("_fig_1.png",))
        with patch("os.path.samefile", return_value=False):
            check("a case-sensitive filesystem does not select a casefold-expanded stem",
                  _glob_slug(folder, "Straße_Trial_2025", _FIG_GLOB), [])
        folder = figures("Old_Slug_2025")
        touch(os.path.join(folder, "new_slug_2026_fig_2.webp"), b"other owner")
        before_set = sorted(os.listdir(folder))
        for dry in (True, False):
            out = checked_rename(folder, "Old_Slug_2025", "New_Slug_2026", dry_run=dry)
            check("rename refuses another format in its destination slot (dry=%s)" % dry,
                  ([entry["ok"] for entry in out], sorted(os.listdir(folder))),
                  ([False, False, False], before_set))
        folder = figures("Old_Slug_2025")
        os.mkdir(os.path.join(folder, "Old_Slug_2025_fig_assets"))
        check("a matching directory refuses the rename instead of moving user content",
              all(not entry["ok"] for entry in checked_rename(
                  folder, "Old_Slug_2025", "New_Slug_2026")), True)
        folder = figures("Old_Slug_2025", ())
        backing = touch(os.path.join(folder, "backing.png"), _PNG)
        linked = os.path.join(folder, "Old_Slug_2025_fig_1.png")
        try:
            os.symlink(backing, linked)
        except (OSError, NotImplementedError):
            pass
        else:
            out = checked_rename(folder, "Old_Slug_2025", "New_Slug_2026")
            check("a matching symlink is not treated as a regular image move",
                  ([entry["ok"] for entry in out], os.path.islink(linked),
                   open(backing, "rb").read()), ([False], True, _PNG))

        # §8a: a CONSUMER matches `<stem>_fig`, never `<stem>_fig_`. This side
        # globbed the strict form, so a vault holding pre-convergence names
        # (§8c) had them left behind under the OLD stem while the note's embeds
        # all moved — and the report said `{"renamed": 3, "failed": 0}`.
        # The two pre-convergence spellings, written out literally because
        # what the case is about is exactly that files named this way are
        # still on disk in long-lived vaults and the loose §8a glob has to
        # take them. Pre-convergence, so the number sits straight on `_fig`:
        old = "_fig3.png"                # pre-convergence: no separator
        old_s1 = "_figS1.png"            # pre-convergence, supplementary
        folder = figures("Old_Slug_2025", ("_fig_1.png", "_fig_2.webp", old))
        out = checked_rename(folder, "Old_Slug_2025", "New_Slug_2026")
        check("the loose §8a glob takes the pre-convergence spelling too",
              ([e["ok"] for e in out], sorted(os.listdir(folder))),
              ([True, True, True],
               sorted(["New_Slug_2026" + old, "New_Slug_2026_fig_1.png",
                       "New_Slug_2026_fig_2.webp"])))
        check("...and nothing is left stranded under the old stem",
              _glob_slug(folder, "Old_Slug_2025", "_fig*"), [])
        # a hand-named `_figure_3.png` is this stem's figure as well, and its
        # tail is carried across verbatim rather than re-spelled
        folder = figures("Old_Slug_2025", ("_fig_1.png", "_figure_3.png"))
        out = checked_rename(folder, "Old_Slug_2025", "New_Slug_2026")
        check("...as is a hand-named `_figure_N`",
              ([e["ok"] for e in out], sorted(os.listdir(folder))),
              ([True, True],
               ["New_Slug_2026_fig_1.png", "New_Slug_2026_figure_3.png"]))
        # the ownership guard has to read the older spelling as well, or a
        # loose glob just widens what gets taken from the other producer
        folder = figures("Doe_Old_2025", ("_fig_1.png", old_s1))
        out = checked_rename(folder, "Doe_Old_2025", "New_Note_2026")
        check("a pre-convergence supplementary label still refuses the set",
              ([e["ok"] for e in out], sorted(os.listdir(folder))),
              ([False, False],
               sorted(["Doe_Old_2025" + old_s1, "Doe_Old_2025_fig_1.png"])))
        check("...naming the label as the reason, as it does for `_fig_S1`",
              sum("pdf-figure-extractor" in (e["error"] or "") for e in out), 1)

        # ALL OR NOTHING. One occupied destination used to stop the loop with
        # the earlier files already renamed: the note's embeds point at one
        # slug, so half of them resolved to nothing and no re-run could put the
        # set back together.
        folder = figures("Old_Slug_2025")
        touch(os.path.join(folder, "New_Slug_2026_fig_2.png"), b"someone else's")
        out = checked_rename(folder, "Old_Slug_2025", "New_Slug_2026")
        check("one occupied destination refuses the whole set",
              [e["ok"] for e in out], [False, False, False])
        check("...naming the file that blocked it",
              sum("destination exists" in (e["error"] or "") for e in out), 1)
        check("...and the others say why they were not done",
              sum("all or nothing" in (e["error"] or "") for e in out), 2)
        check("...with nothing renamed and nothing lost",
              sorted(os.listdir(folder)),
              ["New_Slug_2026_fig_2.png", "Old_Slug_2025_fig_1.png",
               "Old_Slug_2025_fig_2.png", "Old_Slug_2025_fig_3.png"])
        check("...and the occupied destination is untouched",
              open(os.path.join(folder, "New_Slug_2026_fig_2.png"), "rb").read(),
              b"someone else's")
        out = checked_rename(folder, "Old_Slug_2025", "New_Slug_2026", dry_run=True)
        check("--dry-run reports the same refusal the run would make",
              [e["ok"] for e in out], [False, False, False])
        check("...and is marked as a dry run",
              all(e.get("dry_run") for e in out), True)
        folder = figures("Old_Slug_2025")
        out = checked_rename(folder, "Old_Slug_2025", "New_Slug_2026", dry_run=True)
        check("--dry-run on a clean set reports every file and writes nothing",
              ([e["ok"] for e in out],
               sorted(os.listdir(folder))[0]),
              ([True, True, True], "Old_Slug_2025_fig_1.png"))

        folder = figures("Old_Slug_2025", ("_fig_1.png",))
        old_path = os.path.join(folder, "Old_Slug_2025_fig_1.png")
        new_path = os.path.join(folder, "New_Slug_2026_fig_1.png")
        changing_owner = clipping_note(
            "Old_Slug_2025", ("Old_Slug_2025_fig_1.png",))
        real_move = move_noreplace

        def _change_note_after_move(src, dst, expected=None, **kwargs):
            moved = real_move(src, dst, expected=expected, **kwargs)
            with open(changing_owner, "a", encoding="utf-8") as fh:
                fh.write("\nlate edit\n")
            return moved

        globals()["move_noreplace"] = _change_note_after_move
        try:
            out = rename_slug(folder, "Old_Slug_2025", "New_Slug_2026",
                              sources=sources, owner_note=changing_owner)
        finally:
            globals()["move_noreplace"] = real_move
        check("a note changed during rename retracts the image move",
              (open(old_path, "rb").read(), os.path.lexists(new_path)),
              (_PNG, False))
        check("the stale ownership snapshot is reported",
              "owner-note changed" in (out[0]["error"] or ""), True)

        # Preflight is only an inventory. A competing writer can claim the
        # destination after it, so the write itself must be exclusive.
        folder = figures("Old_Slug_2025", ("_fig_1.png",))
        old_path = os.path.join(folder, "Old_Slug_2025_fig_1.png")
        new_path = os.path.join(folder, "New_Slug_2026_fig_1.png")
        real_move = move_noreplace

        def _late_destination(src, dst, expected=None, **kwargs):
            touch(dst, b"late destination")
            return real_move(src, dst, expected=expected, **kwargs)

        globals()["move_noreplace"] = _late_destination
        try:
            out = checked_rename(folder, "Old_Slug_2025", "New_Slug_2026")
        finally:
            globals()["move_noreplace"] = real_move
        check("a destination created after rename preflight is preserved",
              (open(old_path, "rb").read(), open(new_path, "rb").read()),
              (_PNG, b"late destination"))
        check("...and the raced move is reported failed", [e["ok"] for e in out],
              [False])

        folder = figures("Old_Slug_2025", ("_fig_1.png",))
        old_path = os.path.join(folder, "Old_Slug_2025_fig_1.png")
        new_path = os.path.join(folder, "New_Slug_2026_fig_1.png")
        real_move = move_noreplace

        def _replace_source_after_plan(src, dst, expected=None, **kwargs):
            os.unlink(src)
            touch(src, b"late source identity")
            if expected is not None and file_identity(src) == expected:
                # Linux filesystems can immediately reuse the unlinked inode.
                # This fixture exercises the expected-identity mismatch, so
                # keep that mismatch deterministic just as atomic_move's own
                # source-replacement self-test does.
                expected = (expected[0], -1, expected[2])
            return real_move(src, dst, expected=expected, **kwargs)

        globals()["move_noreplace"] = _replace_source_after_plan
        try:
            out = checked_rename(folder, "Old_Slug_2025", "New_Slug_2026")
        finally:
            globals()["move_noreplace"] = real_move
        check("a source replaced after planning is not silently renamed",
              (open(old_path, "rb").read(), os.path.lexists(new_path)),
              (b"late source identity", False))
        check("...and the identity change is reported as a failure",
              [entry["ok"] for entry in out], [False])

        # On a host using the hard-link fallback, destination publication can
        # succeed before unlinking the source fails. Both names are residue and
        # must be retained and reported rather than mistaken for no mutation.
        folder = figures("Old_Slug_2025", ("_fig_1.png",))
        old_path = os.path.join(folder, "Old_Slug_2025_fig_1.png")
        new_path = os.path.join(folder, "New_Slug_2026_fig_1.png")
        real_move = move_noreplace

        def _incomplete_move(src, dst, expected=None, **_kwargs):
            os.link(src, dst)
            raise MoveIncomplete(src, dst, OSError("injected unlink failure"))

        globals()["move_noreplace"] = _incomplete_move
        try:
            out = checked_rename(folder, "Old_Slug_2025", "New_Slug_2026")
        finally:
            globals()["move_noreplace"] = real_move
        check("an incomplete fallback move retains both figure names",
              (open(old_path, "rb").read(), open(new_path, "rb").read()),
              (_PNG, _PNG))
        check("...and reports the residue explicitly",
              "MOVE INCOMPLETE" in (out[0]["error"] or ""), True)

        # Rollback is another forward move and has the same race. If the old
        # name is reclaimed after its file moved, retain both entries and name
        # the incomplete rollback instead of overwriting either one.
        folder = figures("Old_Slug_2025", ("_fig_1.png", "_fig_2.png"))
        old_one = os.path.join(folder, "Old_Slug_2025_fig_1.png")
        new_one = os.path.join(folder, "New_Slug_2026_fig_1.png")
        real_move, calls = move_noreplace, []

        def _late_rollback_source(src, dst, expected=None, **kwargs):
            calls.append((src, dst))
            if len(calls) == 2:
                touch(old_one, b"late source")
                raise OSError(28, "injected second move failure")
            return real_move(src, dst, expected=expected, **kwargs)

        globals()["move_noreplace"] = _late_rollback_source
        try:
            out = checked_rename(folder, "Old_Slug_2025", "New_Slug_2026")
        finally:
            globals()["move_noreplace"] = real_move
        check("a source recreated before rollback is never overwritten",
              (open(old_one, "rb").read(), open(new_one, "rb").read()),
              (b"late source", _PNG))
        check("...and the incomplete rollback is reported",
              any("ROLLBACK INCOMPLETE" in (e["error"] or "") for e in out), True)

        # A rename that fails PART-WAY — a full disk, a vault mount that drops
        # out — is put back, for the same reason a refusal stops the set: half
        # a set under each slug is the state no re-run can repair. The shared
        # exclusive-move primitive is swapped for this call so the second move
        # can fail on demand without depending on the host filesystem.
        folder = figures("Old_Slug_2025")
        real_move, calls = move_noreplace, []

        def _flaky_move(src, dst, expected=None, **kwargs):
            calls.append(src)
            if len(calls) == 2:
                raise OSError(28, "No space left on device")
            return real_move(src, dst, expected=expected, **kwargs)

        globals()["move_noreplace"] = _flaky_move
        try:
            out = checked_rename(folder, "Old_Slug_2025", "New_Slug_2026")
        finally:
            globals()["move_noreplace"] = real_move
        check("a rename that fails part-way is rolled back",
              sorted(os.listdir(folder)),
              ["Old_Slug_2025_fig_1.png", "Old_Slug_2025_fig_2.png",
               "Old_Slug_2025_fig_3.png"])
        check("...and no member is reported renamed",
              [e["ok"] for e in out], [False, False, False])
        check("...with the OS error named",
              sum("No space left" in (e["error"] or "") for e in out), 1)

        # A case-only rename is not a collision: it is the documented
        # old-convention reprocess, and on an insensitive filesystem src and
        # dst may be one file.
        folder = figures("teslo_cancer_2026", ("_fig_1.png",))
        out = checked_rename(folder, "teslo_cancer_2026", "Teslo_Cancer_2026")
        check("a case-only rename is allowed", [e["ok"] for e in out], [True])
        # ...whose collision preflight is decided by `_same_file`, not by the
        # names. On an insensitive filesystem src and dst are one directory
        # entry and `lexists(dst)` is true. A hard link reproduces the same-file
        # preflight on any filesystem, though its second directory entry cannot
        # reproduce the later atomic case-only move; keep this probe dry-run.
        one = touch(os.path.join(tmp, "one"), b"x")
        two = os.path.join(tmp, "two")
        check("_same_file: a path is itself", _same_file(one, one), True)
        check("_same_file: a missing path is not a match",
              _same_file(one, os.path.join(tmp, "nope")), False)
        check("_same_file: two different files are not one",
              _same_file(one, touch(two, b"y")), False)
        try:
            folder = figures("teslo_cancer_2026", ("_fig_1.png",))
            os.link(os.path.join(folder, "teslo_cancer_2026_fig_1.png"),
                    os.path.join(folder, "Teslo_Cancer_2026_fig_1.png"))
        except (OSError, AttributeError, NotImplementedError):
            pass                              # no hard links here: skip, silently
        else:
            check("a same-inode destination passes collision preflight",
                  all(e["ok"] for e in checked_rename(folder, "teslo_cancer_2026",
                                                   "Teslo_Cancer_2026",
                                                   dry_run=True)), True)

        # Sources/Images is FLAT and shared. Two guards say the stem is a PDF's.
        folder = figures("Doe_Foo_2025", ("_fig_1.png", "_fig_S1.png"))
        out = checked_rename(folder, "Doe_Foo_2025", "New_Note_2026")
        check("a supplementary label refuses the set",
              [e["ok"] for e in out], [False, False])
        check("...naming the label as the reason",
              sum("pdf-figure-extractor" in (e["error"] or "") for e in out), 1)
        check("...and moves nothing",
              sorted(os.listdir(folder)),
              ["Doe_Foo_2025_fig_1.png", "Doe_Foo_2025_fig_S1.png"])
        for label in ("_fig_ED2.png", "_fig_SI3.png", "_fig_1-2.png",
                      "_fig_2.1.png"):
            folder = figures("Doe_Bar_2025", ("_fig_1.png", label))
            out = checked_rename(folder, "Doe_Bar_2025", "New_Note_2026")
            check("a %s label is pdf-figure-extractor's" % label,
                  any(e["ok"] for e in out), False)
        # ...and a plain integer label is this skill's own, so it renames
        folder = figures("Doe_Baz_2025", ("_fig_1.png", "_fig_12.png"))
        out = checked_rename(folder, "Doe_Baz_2025", "New_Note_2026")
        check("a plain integer label is this skill's", [e["ok"] for e in out],
              [True, True])
        folder = figures("Doe_Fig_S1_2025", ("_fig_1.png",))
        check("PDF-only label syntax inside a clipping title does not own its figures",
              [e["ok"] for e in checked_rename(
                  folder, "Doe_Fig_S1_2025", "Doe_Trial_2025")], [True])

        # ...and a `<stem>.pdf` on disk settles ownership outright
        os.makedirs(os.path.join(sources, "sub"))
        touch(os.path.join(sources, "sub", "Doe_Qux_2025.pdf"))
        folder = figures("Clipping_Topic_2025", ("_fig_1.png",))
        check("a PDF also reserves the destination stem before figures exist",
              [entry["ok"] for entry in checked_rename(
                  folder, "Clipping_Topic_2025", "Doe_Qux_2025", sources=sources)],
              [False])
        with open(os.path.join(folder, MANIFEST_FILE), "w",
                  encoding="utf-8") as fh:
            fh.write("Reserved_Paper_2025_fig_1.png\t" + hashlib.sha256(_PNG).hexdigest() + "\n")
        check("a missing figure's PDF manifest record still reserves the rename destination",
              [entry["ok"] for entry in checked_rename(
                  folder, "Clipping_Topic_2025", "Reserved_Paper_2025")], [False])
        with open(os.path.join(folder, MANIFEST_FILE), "w",
                  encoding="utf-8") as fh:
            fh.write("Reserved_Paper_2025_fig_1.webp\t" + hashlib.sha256(_PNG).hexdigest() + "\n")
        check("manifest ownership reserves the destination index across extensions",
              [entry["ok"] for entry in checked_rename(
                  folder, "Clipping_Topic_2025", "Reserved_Paper_2025")], [False])
        folder = figures("Doe_Qux_2025", ("_fig_1.png",))
        out = checked_rename(folder, "Doe_Qux_2025", "New_Note_2026",
                          sources=sources)
        check("a PDF of that stem refuses the rename",
              [e["ok"] for e in out], [False])
        check("...naming pdf-organizer as whose move it is",
              "pdf-organizer" in (out[0]["error"] or ""), True)
        check("...and leaves the figures alone",
              os.listdir(folder), ["Doe_Qux_2025_fig_1.png"])
        folder = figures("Clipping_No_PDF_2025", ("_fig_1.png",))
        check("...while a stem with no PDF renames normally",
              [e["ok"] for e in checked_rename(
                  folder, "Clipping_No_PDF_2025", "New_Note_2026")], [True])
        accented = "Müller_Topic_2026"
        touch(os.path.join(sources, "sub", unicodedata.normalize("NFD", accented) + ".pdf"))
        folder = figures(accented, ("_fig_1.png",))
        out = checked_rename(folder, accented, "New_Note_2026", sources=sources)
        check("an NFD PDF filename still owns an NFC figure stem",
              [e["ok"] for e in out], [False])
        check("...and its figures stay under their original stem",
              os.listdir(folder), [accented + "_fig_1.png"])
        raises("a mistyped --sources path cannot silently disable ownership checks",
                   checked_rename, folder, accented, "New_Note_2026",
               sources=os.path.join(sources, "missing-folder"))
        scandir = os.scandir

        def unreadable_sources(path):
            if path == os.path.join(sources, "sub"):
                raise PermissionError(13, "permission denied", path)
            return scandir(path)

        before = {name: open(os.path.join(folder, name), "rb").read()
                  for name in os.listdir(folder)}
        with patch.object(os, "scandir", side_effect=unreadable_sources):
            raises("an incomplete PDF inventory cannot authorize an image rename",
               checked_rename, folder, accented, "New_Note_2026", sources=sources)
        check("failed ownership enumeration preserves every image name and byte",
              {name: open(os.path.join(folder, name), "rb").read()
               for name in os.listdir(folder)}, before)
        raises("rename_slug validates both slugs", checked_rename, folder,
               "../old", "new")
        raises("...including the new one", checked_rename, folder, "old",
               "../new")

        # --- the documented procedures, which are the other half of a guard --
        # A guard the prose routes around is not a guard. Each case below was a
        # live bypass: a `rename` invocation with no `--sources` (so the
        # ownership refusal never engaged), a stem-owner probe that could not
        # see into `Sources/PDFs/<Work>/`, a caps list read as fixed properties
        # when three are flags, and a Lottie converter doing its own fetch and
        # its own write into Sources/Images with none of this file's guards.
        def doc(*parts):
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

        skill_md = doc("SKILL.md")
        images_md = doc("references", "images.md")
        reprocess_md = doc("references", "duplicates-and-reprocessing.md")
        lottie_md = doc("references", "lottie-recovery.md")

        # `rename`'s ownership guard is real, and `--sources` is what arms it.
        # It appeared in NO markdown file, so both documented invocations ran
        # without it and the refusal never fired in practice.
        commands = re.sub(r"\\\r?\n[ \t]*", " ",
                          skill_md + "\n" + images_md + "\n" + reprocess_md)
        rename_calls = re.findall(
            r"fetch_images\.py['\"]? rename[^\n`]*--attachments[^\n`]*",
            commands)
        check("every documented `rename` invocation passes --sources",
              (len(rename_calls) >= 1,
               [c for c in rename_calls if "--sources" not in c]),
              (True, []))
        check("every documented `rename` invocation passes --owner-note",
              (len(rename_calls) >= 1,
               [c for c in rename_calls if "--owner-note" not in c]),
              (True, []))
        check("every documented `rename` invocation selects an explicit phase",
              (len(rename_calls) >= 1,
               [c for c in rename_calls if "--phase" not in c]),
              (True, []))
        check("the image procedure requires the recursive PDF ownership guard",
              bool(re.search(r"recursive PDF ownership.{0,100}both stems",
                             images_md, re.S)) and
              "Never use bare `cp`/`mv`, omit either owner guard" in images_md,
              True)
        check("the image procedure explains exact positive clipping ownership",
              "web URL as its first current `sources:`" in images_md and
              "exactly embed every old attachment" in images_md and
              "--owner-note" in images_md, True)
        check("changed-slug docs require the vault-wide dependency probe",
              ("every Markdown note outside the owner" in reprocess_md
               and "fetch_images.py' dependencies" in reprocess_md
               and "Before finalizing" in images_md), True)
        check("dependency refusal is reported before destructive old-path cleanup",
              ("never delete first" in reprocess_md
               and "exact blocker paths" in images_md), True)

        # `Sources/PDFs/` is recursive by contract (a split book lives in
        # `Sources/PDFs/<Work>/`), so the step-3 stem-owner probe has to
        # recurse. `ls -d '<vault>/Sources/PDFs/<slug>.'*` could not see a
        # chapter stem, and the collision it exists to catch went unreported.
        check("the naming procedure checks PDF stems recursively",
              bool(re.search(r"PDF stems throughout recursive\s+`Sources/PDFs/`",
                             reprocess_md)), True)
        check("...and no longer globs that folder one level deep",
              "ls -d '<vault>/Sources/PDFs/" in skill_md + reprocess_md, False)

        # The caps are defaults behind flags, and `--allow-private-hosts` turns
        # off a guard the same bullet list sells as unconditional. None of the
        # four was named anywhere in the prose.
        for flag in ("--max-bytes", "--max-seconds", "--timeout",
                     "--allow-private-hosts"):
            check("references/images.md names %s" % flag, flag in images_md,
                  True)
        check("...and explains that --allow-private-hosts enables private destinations",
              bool(re.search(r"--allow-private-hosts[^\n]*enables[^\n]*private",
                             images_md)), True)

        # The Lottie converter: the download and the final placement must go
        # through this script, and the heredoc must keep to rendering.
        check("the documented Lottie flow fetches through this script",
              "fetch_images.py' fetch" in lottie_md, True)
        check("...and places through this script",
              "fetch_images.py' place" in lottie_md, True)
        heredoc = re.search(r"<<'PYEOF'\n(.*?)\nPYEOF", lottie_md, re.S)
        check("the converter heredoc is still extractable", bool(heredoc), True)
        if heredoc:
            body = heredoc.group(1)
            # its comments explain what it no longer does, so judge the CODE
            code = "\n".join(ln for ln in body.split("\n")
                             if not ln.lstrip().startswith("#"))
            check("the converter does not fetch anything itself",
                  ("urlopen" in code, "urllib" in code), (False, False))
            check("...and does not write its scratch file beside its output",
                  ('out + ".tmp' in code, "mkstemp" in code), (False, True))
            check("...and does not name Sources/Images in its code at all",
                  "Sources/Images" in code, False)
            # It parses, and it escapes the animation for HTML embedding: a
            # `</script>` inside any string field of a hostile Lottie used to
            # close the tag early, so the generated page ran a THIRD script
            # tag the animation's author wrote.
            ns = {"__name__": "_selftest_not_main", "__file__": __file__}
            try:
                exec(compile(body, "lottie_to_gif.py", "exec"), ns)
                cases.append(("the converter's module body still parses and "
                              "runs (no import-time side effects)", True,
                              "ok", "ok"))
            except Exception as exc:                      # noqa: BLE001
                cases.append(("the converter's module body still parses and "
                              "runs (no import-time side effects)", False,
                              "%s: %s" % (type(exc).__name__, exc), "ok"))
            embed = ns.get("json_for_script")
            check("the converter exposes the JSON-for-<script> escaper",
                  callable(embed), True)
            if not callable(embed):
                # what the converter used to interpolate, so the two cases
                # below still RUN — and fail — rather than quietly not running
                embed = json.dumps
            hostile = {"nm": "</script><script>fetch('http://evil/')</script>",
                       "op": 2, "w": 1, "h": 1}
            emb = embed(hostile)
            page = ("<script>lottie.loadAnimation({animationData:%s});"
                    "</script>" % emb)
            check("a hostile Lottie cannot close the <script> tag",
                  (page.lower().count("<script"), "</script" in emb.lower()),
                  (1, False))
            check("...and the escaped JSON still decodes to the same animation",
                  json.loads(emb), hostile)
            validate_anim = ns.get("validate_anim")
            check("the renderer validates untrusted animation data before launch",
                  callable(validate_anim), True)
            if callable(validate_anim):
                base_anim = {"w": 100, "h": 100, "fr": 30, "ip": 0, "op": 60,
                             "layers": []}
                check("a self-contained animation passes renderer preflight",
                      validate_anim(base_anim), None)
                for label, extra in (
                        ("an external image", {"assets": [{"p": "figure.png", "u": "https://example.com/"}]}),
                        ("a private image URL", {"assets": [{"p": "http://127.0.0.1/image"}]}),
                        ("an external font", {"fonts": {"list": [{"fPath": "https://example.com/font.woff"}]}}),
                        ("an expression", {"layers": [{"ks": {"o": {"x": "fetch('https://example.com/')"}}}]}),
                        ("zero frame rate", {"fr": 0}),
                        ("an infinite dimension", {"w": float("inf")}),
                        ("no frames", {"op": 0})):
                    raises("renderer refuses %s before browser work" % label,
                           validate_anim, {**base_anim, **extra})
                check("embedded image bytes need no network permission",
                      validate_anim({**base_anim,
                                     "assets": [{"p": data_url, "e": 1}]}), None)
            allowed = ns.get("render_request_allowed")
            check("the renderer exposes its network allowlist", callable(allowed), True)
            if callable(allowed):
                check("only the fixed renderer library may be fetched",
                      [allowed(url) for url in (ns["LOTTIE_CDN"],
                       "http://127.0.0.1/image", "https://example.com/asset",
                       ns["LOTTIE_CDN"] + "?redirect=elsewhere")],
                      [True, False, False, False])
            publish_scratch = ns.get("publish_scratch")
            check("the renderer exposes exclusive scratch publication",
                  callable(publish_scratch), True)
            if callable(publish_scratch):
                rendered = os.path.join(tmp, "lottie-rendered.gif")
                published = os.path.join(tmp, "lottie-published.gif")
                with open(rendered, "wb") as fh:
                    fh.write(b"GIF89a-new")
                publish_scratch(rendered, published)
                check("scratch publication moves complete bytes to a new name",
                      (os.path.lexists(rendered), open(published, "rb").read()),
                      (False, b"GIF89a-new"))
                retry = os.path.join(tmp, "lottie-retry.gif")
                with open(retry, "wb") as fh:
                    fh.write(b"GIF89a-retry")
                try:
                    publish_scratch(retry, published)
                    output_refused = False
                except FileExistsError:
                    output_refused = True
                check("scratch publication refuses an existing output",
                      output_refused, True)
                check("a refused scratch publication preserves both occupants",
                      (open(retry, "rb").read(), open(published, "rb").read()),
                      (b"GIF89a-retry", b"GIF89a-new"))
            if callable(ns.get("load_anim")):
                raises("the renderer also refuses duplicate manifest names",
                       ns["load_anim"], duplicate_manifest)
                raises("the renderer also refuses duplicate animation names",
                       ns["load_anim"], duplicate_animation)
                packed = os.path.join(tmp, "oversized.lottie")
                with zipfile.ZipFile(packed, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr(
                        "manifest.json",
                        '{"version":"1","animations":[{"id":"a"}]}')
                    archive.writestr("animations/a.json", b" " * 1024)
                ns["MAX_JSON_BYTES"] = 64
                raises("a small ZIP cannot expand past the animation JSON cap",
                       ns["load_anim"], packed)

        # Fresh-note downloads must remain outside the vault until a public
        # owner note exists. Exercise the CLI branch end to end with a data URI.
        stage_vault = os.path.join(tmp, "stage-vault")
        os.mkdir(stage_vault)
        stage_out = os.path.join(tmp, "stage-output")
        stage_stdout = io.StringIO()
        with patch.object(sys, "stdout", stage_stdout):
            stage_code = main([
                "stage", "--vault", stage_vault, "--out-dir", stage_out,
                "--slug", "Example_Image_2026",
                "data:image/png;base64," +
                base64.b64encode(_PNG).decode("ascii"),
            ])
        stage_report = json.loads(stage_stdout.getvalue())
        check("stage CLI downloads a fresh-note image only to outside scratch",
              (stage_code, stage_report["mode"],
               os.path.isfile(os.path.join(
                   stage_out, "Example_Image_2026_fig_1.png")),
               _inside_existing_directory(stage_out, stage_vault)),
              (0, "stage", True, False))
    finally:
        tempfile.tempdir = previous_tempdir
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [c for c in cases if not c[1]]
    for label, ok, got, want in cases:
        if not ok:
            print("FAIL  %s\n        got  %r\n        want %r"
                  % (label, got, want))
    print("%d/%d self-test cases pass" % (len(cases) - len(failed), len(cases)))
    return 1 if failed else 0


def _read_urls_file(path):
    """Read a URL list completely as strict UTF-8 and close owned handles."""
    if path == "-":
        binary = getattr(sys.stdin, "buffer", None)
        if binary is not None:
            text = binary.read().decode("utf-8-sig", "strict")
        else:  # StringIO and other programmatic callers are already Unicode.
            text = sys.stdin.read().lstrip("\ufeff")
        return [line.strip() for line in text.splitlines() if line.strip()]
    with open(path, "r", encoding="utf-8-sig", errors="strict") as stream:
        return [line.strip() for line in stream if line.strip()]


def main(argv=None):
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (OSError, ValueError):
            pass
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n")[0],
        epilog="Network policy: direct connections only; ambient HTTP(S) proxy "
               "settings are not used because proxy-side DNS would defeat "
               "address pinning.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("download", help="download images into Sources/Images/")
    d.add_argument("urls", nargs="*")
    d.add_argument("--attachments", required=True)
    d.add_argument("--slug", required=True)
    d.add_argument("--start", type=_positive_index_arg, default=1)
    d.add_argument("--urls-file", help="file with one URL per line; - for stdin")
    d.add_argument("--timeout", type=_positive_int_arg, default=45,
                   help="per-socket-operation timeout, seconds (default 45)")
    d.add_argument("--max-bytes", type=_positive_int_arg, default=DEFAULT_MAX_BYTES,
                   help=f"per-image size cap (default {DEFAULT_MAX_BYTES})")
    d.add_argument("--max-seconds", type=_positive_int_arg, default=DEFAULT_MAX_SECONDS,
                   help="wall-clock budget for one image, across the whole "
                        f"transfer (default {DEFAULT_MAX_SECONDS})")
    d.add_argument("--allow-private-hosts", action="store_true",
                   help="permit hosts resolving to loopback/link-local/private "
                        "addresses (off by default; does not enable proxies)")
    d.add_argument("--overwrite", action="store_true",
                   help="replace an existing figure only at the same filename; "
                        "a format change needs a fresh index (reprocess only; off by "
                        "default, because a wrong --start otherwise destroys "
                        "the figures already filed under that name)")
    d.add_argument("--owner-note", required=True,
                   help="published Articles/<slug>.md whose rendered embed "
                        "exactly names the attachment")

    s = sub.add_parser("stage", help="download validated images to scratch "
                       "outside the vault before the note is published")
    s.add_argument("urls", nargs="*")
    s.add_argument("--out-dir", required=True,
                   help="unique empty scratch directory outside --vault")
    s.add_argument("--vault", required=True,
                   help="vault root used to enforce the scratch boundary")
    s.add_argument("--slug", required=True)
    s.add_argument("--start", type=_positive_index_arg, default=1)
    s.add_argument("--urls-file", help="UTF-8 file with one URL per line; - for stdin")
    s.add_argument("--timeout", type=_positive_int_arg, default=45)
    s.add_argument("--max-bytes", type=_positive_int_arg,
                   default=DEFAULT_MAX_BYTES)
    s.add_argument("--max-seconds", type=_positive_int_arg,
                   default=DEFAULT_MAX_SECONDS)
    s.add_argument("--allow-private-hosts", action="store_true")

    f = sub.add_parser("fetch", help="download a validated Lottie JSON/dotLottie "
                       "source; the default is a system temp path")
    f.add_argument("url")
    f.add_argument("--out", help="scratch path outside the vault (default: a "
                   "system temp file); requires --vault; an existing path is "
                   "refused unless --overwrite")
    f.add_argument("--vault", help="vault root used to prove an explicit "
                   "--out is outside the vault")
    f.add_argument("--timeout", type=_positive_int_arg, default=45,
                   help="per-socket-operation timeout, seconds (default 45)")
    f.add_argument("--max-bytes", type=_positive_int_arg, default=DEFAULT_MAX_BYTES,
                   help=f"size cap (default {DEFAULT_MAX_BYTES})")
    f.add_argument("--max-seconds", type=_positive_int_arg, default=DEFAULT_MAX_SECONDS,
                   help="wall-clock budget across the whole transfer "
                        f"(default {DEFAULT_MAX_SECONDS})")
    f.add_argument("--allow-private-hosts", action="store_true",
                   help="permit hosts resolving to loopback/link-local/private "
                        "addresses (off by default; does not enable proxies)")
    f.add_argument("--overwrite", action="store_true")

    p = sub.add_parser("place", help="move a locally rendered image into "
                       "Sources/Images/ under this script's write guards")
    p.add_argument("--attachments", required=True)
    p.add_argument("--slug", required=True)
    p.add_argument("--index", type=_positive_index_arg, required=True)
    p.add_argument("--from-file", required=True, dest="from_file",
                   help="the rendered file, which must live OUTSIDE the "
                        "attachments folder; it is moved, not copied, and its "
                        "extension comes from its bytes, not from its name")
    p.add_argument("--overwrite", action="store_true",
                   help="replace an existing figure only at the same filename; "
                        "a format change needs a fresh index (off by default)")
    p.add_argument("--owner-note", required=True,
                   help="published Articles/<slug>.md whose rendered embed "
                        "exactly names the attachment")

    r = sub.add_parser(
        "rename", help="prepare or finalize an attachment handoff after a slug change")
    r.add_argument("--attachments", required=True)
    r.add_argument("--sources", required=True,
                   help="the vault's Sources/PDFs folder; "
                   "a <slug>.pdf there proves the figures are a "
                   "PDF's and the rename is refused")
    r.add_argument("--old-slug", required=True)
    r.add_argument("--new-slug", required=True)
    r.add_argument("--owner-note", required=True,
                   help="the unchanged Articles/<old-slug>.md; every renamed "
                        "attachment must be an exact rendered filename-only embed")
    r.add_argument("--new-owner-note",
                   help="published Articles/<new-slug>.md with the same web "
                        "origin and exact mapped new embeds; required for "
                        "prepare/finalize")
    r.add_argument("--phase", choices=("immediate", "prepare", "finalize"),
                   required=True,
                   help="required: prepare publishes new-name copies while "
                        "retaining old names; finalize retires exact old copies "
                        "after dependencies are clear; immediate is a deprecated "
                        "compatibility path for an unreferenced set")
    r.add_argument("--dry-run", action="store_true")

    q = sub.add_parser(
        "dependencies", help="re-probe external Markdown links and embeds before "
        "retiring an old clipping note or attachment stem")
    q.add_argument("--attachments", required=True)
    q.add_argument("--old-slug", required=True)
    q.add_argument("--owner-note", required=True,
                   help="the unchanged Articles/<old-slug>.md whose old image "
                        "embeds define the dependency inventory")

    o = sub.add_parser(
        "preflight", help="check whether a proposed clipping slug already has "
                          "a PDF or image-prefix owner")
    o.add_argument("--vault", required=True)
    o.add_argument("--slug", required=True)

    sub.add_parser("selftest", help="run the built-in cases (offline)")

    args = ap.parse_args(argv)

    if args.cmd == "selftest":
        return run_self_test()

    if args.cmd == "preflight":
        try:
            report = slug_occupancy(args.vault, args.slug)
        except (OSError, UnicodeError, ValueError) as exc:
            report = {"ok": False, "vault": args.vault, "slug": args.slug,
                      "error": str(exc), "pdf_stem_occupied": None,
                      "image_occupants": []}
        print(json.dumps(dict(report, mode="preflight"), indent=2,
                         ensure_ascii=False))
        return 0 if report["ok"] else 1

    if args.cmd == "dependencies":
        try:
            report = dependency_status(args.attachments, args.owner_note,
                                       args.old_slug)
        except (OSError, UnicodeError, ValueError) as exc:
            report = {"ok": False, "old_slug": args.old_slug,
                      "error": str(exc), "blockers": []}
        print(json.dumps(dict(report, mode="dependencies"), indent=2,
                         ensure_ascii=False))
        return 0 if report["ok"] else 1

    if args.cmd in ("download", "stage"):
        urls = list(args.urls)
        if args.urls_file:
            try:
                urls += _read_urls_file(args.urls_file)
            except (OSError, UnicodeError) as exc:
                print(json.dumps({"mode": args.cmd, "slug": args.slug,
                                  "error": "cannot read --urls-file as complete "
                                           "UTF-8: %s" % exc,
                                  "results": [], "downloaded": 0,
                                  "failed": len(urls) or 1},
                                 indent=2, ensure_ascii=False))
                return 1
        if not urls:
            ap.error("no URLs given")
        try:
            validate_slug(args.slug)      # once, loudly, not N identical failures
        except ValueError as exc:
            print(json.dumps({"mode": args.cmd, "slug": args.slug,
                              "error": str(exc), "results": [], "downloaded": 0,
                              "failed": len(urls)}, indent=2, ensure_ascii=False))
            return 1
        attachments = args.attachments if args.cmd == "download" else args.out_dir
        if args.cmd == "stage":
            if not os.path.isdir(args.vault):
                print(json.dumps({"mode": "stage", "slug": args.slug,
                                  "error": "--vault is not a directory: %r" % args.vault,
                                  "results": [], "downloaded": 0,
                                  "failed": len(urls)}, indent=2,
                                 ensure_ascii=False))
                return 1
            try:
                if _inside_existing_directory(attachments, args.vault):
                    raise ValueError("--out-dir must be outside --vault")
                if os.path.lexists(attachments) and (
                        not os.path.isdir(attachments)
                        or os.listdir(attachments)):
                    raise ValueError("--out-dir must be a new or empty unique "
                                     "scratch directory")
            except (OSError, ValueError) as exc:
                print(json.dumps({"mode": "stage", "slug": args.slug,
                                  "error": str(exc), "results": [],
                                  "downloaded": 0, "failed": len(urls)},
                                 indent=2, ensure_ascii=False))
                return 1
        results = []
        for i, url in enumerate(urls, start=args.start):
            results.append(download_one(
                url, attachments, args.slug, i, timeout=args.timeout,
                max_bytes=args.max_bytes, max_seconds=args.max_seconds,
                allow_private=args.allow_private_hosts,
                overwrite=(args.overwrite if args.cmd == "download" else False),
                owner_note=(args.owner_note if args.cmd == "download" else None),
                require_vault=(args.cmd == "download")))
        failed = [x for x in results if not x["ok"]]
        out = {"mode": args.cmd, "slug": args.slug,
               ("attachments" if args.cmd == "download" else "staging_dir"):
                   attachments, "results": results,
               "downloaded": len(results) - len(failed), "failed": len(failed),
               "next_index": args.start + len(results)}
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 1 if failed else 0

    if args.cmd == "fetch":
        res = fetch_source(args.url, args.out, timeout=args.timeout,
                           max_bytes=args.max_bytes,
                           max_seconds=args.max_seconds,
                           allow_private=args.allow_private_hosts,
                           overwrite=args.overwrite, vault=args.vault)
        print(json.dumps(dict(res, mode="fetch"), indent=2,
                         ensure_ascii=False))
        return 0 if res["ok"] else 1

    if args.cmd == "place":
        res = place_file(args.from_file, args.attachments, args.slug,
                         args.index, overwrite=args.overwrite,
                         owner_note=args.owner_note, require_vault=True)
        print(json.dumps(dict(res, mode="place", slug=args.slug,
                              attachments=args.attachments), indent=2,
                         ensure_ascii=False))
        return 0 if res["ok"] else 1

    try:
        if args.phase != "immediate" and not args.new_owner_note:
            raise ValueError("--new-owner-note is required with --phase %s" %
                             args.phase)
        if args.phase == "prepare":
            report = prepare_slug_rename(
                args.attachments, args.old_slug, args.new_slug,
                sources=args.sources, owner_note=args.owner_note,
                new_owner_note=args.new_owner_note, dry_run=args.dry_run)
            print(json.dumps(dict(report, mode="rename"), indent=2,
                             ensure_ascii=False))
            return 0 if report["ok"] else 1
        if args.phase == "finalize":
            report = finalize_slug_rename(
                args.attachments, args.old_slug, args.new_slug,
                sources=args.sources, owner_note=args.owner_note,
                new_owner_note=args.new_owner_note, dry_run=args.dry_run)
            print(json.dumps(dict(report, mode="rename"), indent=2,
                             ensure_ascii=False))
            return 0 if report["ok"] else 1
        results = rename_slug(
            args.attachments, args.old_slug, args.new_slug,
            args.dry_run, sources=args.sources,
            owner_note=args.owner_note, require_vault=True)
    except (OSError, UnicodeError, ValueError) as exc:
        print(json.dumps({"mode": "rename", "phase": args.phase,
                          "ok": False, "old_slug": args.old_slug,
                          "new_slug": args.new_slug, "error": str(exc),
                          "results": [], "renamed": 0, "failed": 1},
                         indent=2, ensure_ascii=False))
        return 1
    failed = [x for x in results if not x["ok"]]
    print(json.dumps({"mode": "rename", "phase": "immediate",
                      "warning": "--phase immediate is deprecated for clipping "
                                 "reprocessing; use prepare then finalize",
                      "ok": not failed, "old_slug": args.old_slug,
                      "new_slug": args.new_slug, "results": results,
                      "renamed": len(results) - len(failed),
                      "failed": len(failed)}, indent=2, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
