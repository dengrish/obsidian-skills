#!/usr/bin/env python3
"""Download a clipping's images into Sources/Images/, or rename them on a reprocess.

This is the mechanical half of step 6, done the same way every time: a browser
User-Agent on every request (CDNs 403 a default urllib/curl agent), a temp file
OUTSIDE Sources/Images with no image extension, the real type detected from the
bytes rather than trusted from the URL, and a move — not a copy — into
<Sources/Images>/<slug>_fig_<N>.<ext>. Doing it by hand is what produces the
broken extension-twin (a .png written from a URL guess sitting next to the
.webp the MIME check produced).

What stays with you: deciding which images are figures, finding and normalizing
captions, rewriting the body's references to `![[…]]` embeds, and inserting a
`<!-- image download failed: <url> -->` placeholder for anything reported
failed here. Those rules are in references/images.md.

CLI
    python3 fetch_images.py download --attachments '<vault>/Sources/Images' \\
        --slug Teslo_Pancreatic_Cancer_2026 [--start 1] URL [URL ...]
    python3 fetch_images.py download ... --urls-file list.txt     # one URL per line, - for stdin
    python3 fetch_images.py fetch '<lottie source url>' [--out '<path>']
    python3 fetch_images.py place --attachments '<vault>/Sources/Images' \\
        --slug Teslo_Pancreatic_Cancer_2026 --index 3 --from-file '<rendered file>'
    python3 fetch_images.py rename --attachments '<vault>/Sources/Images' \\
        --sources '<vault>/Sources/PDFs' \\
        --old-slug Old_Slug_2025 --new-slug New_Slug_2026 [--dry-run]
    python3 fetch_images.py selftest        # the built-in cases; offline

`fetch` and `place` are the two halves of a figure this skill does not download
as an image: step 12's Lottie animation, which arrives as JSON and has to be
rendered to a GIF by something else first. `fetch` brings the source down under
the transport guards below, to a path OUTSIDE the vault; you render; `place`
moves the result in under the write guards below. Neither the fetch nor the
final write is left to the rendering step, because a script that does its own
`urlopen` and its own `os.replace` into Sources/Images has none of this.

`rename`'s `--sources` is the vault's `Sources/PDFs`: given it, a `<old_slug>.pdf`
found anywhere beneath (the folder is recursive — book chapters live in
`Sources/PDFs/<Work>/`) proves the figures under that stem are that document's,
and the whole rename is refused. PDF manifest ownership is checked regardless
of this flag. Without either a manifest record or `--sources`, only label
spelling distinguishes PDF figures, so pass `--sources` on every `rename`.

URLs are processed in the order given, which must be the body's source order:
the figure counter is shared and sequential. `--start` continues the counter
when the note already has embeds (a recovered figure from the step-12 audit
takes the next free number, not a number matching its position).

Guards, because this is the only script in the skill that writes into the vault:

* **Slugs are validated, paths are contained.** A slug holding `/`, `\\`, `..`,
  or nothing at all is rejected, and every final path is checked to be under
  the Sources/Images folder before anything is moved or renamed. `--slug` is free
  text from the model, not necessarily what `slug.py` returned.
* **Neither `download` nor `rename` clobbers, and `rename` is all-or-nothing.**
  A reprocess whose corrected
  author/year lands on a slug that already has figures would otherwise
  overwrite them silently, so an existing destination is an error for that
  file (`--dry-run` reports it too) — and it refuses the whole set rather than
  the one file, because the note's embeds are rewritten to a single slug and a
  half-renamed set leaves half of them resolving to nothing under a stem no
  re-run can reassemble. A case-only rename of the same file
  (`teslo_…` → `Teslo_…` on a case-insensitive volume) is still allowed.
  `download` refuses an occupied `<slug>_fig_<N>.*` slot the same way —
  `shutil.move` replaces silently, so a re-run with the wrong `--start`
  destroyed figures with no way back. Pass `--overwrite` for the documented
  reprocess-in-place case.
* **Only `http`, `https` and `data:`** — `urlopen` also speaks `file:` and
  `ftp:`, and clipped markdown legitimately carries `file://` image links.
  Redirect targets are re-checked at every hop. Hosts resolving to loopback,
  link-local or private ranges are refused unless `--allow-private-hosts`.
* **Bounded downloads** — `--max-bytes` (25 MB default) and `--max-seconds`
  (120 s default, wall-clock across the whole transfer, unlike the per-socket
  `--timeout`), so a huge or slow-dripping response can't fill the vault.
* **Non-images are failures, not `.png`s, and the BYTES decide that.** A
  JSON/text/PDF error body is reported failed — naming what the bytes looked
  like — so the model writes the documented
  `<!-- image download failed: <url> -->` placeholder instead of embedding a
  file that Obsidian can't render. A `Content-Type` is only a hint: an
  `image/png` header on a JSON body does not make it an image, and used to.

Importable
    sniff_extension(head, content_type=None, url=None) -> str | None
    describe_bytes(head) -> str                        # "a JSON body", "a PDF", …
    download_one(url, attachments, slug, index) -> dict
    fetch_source(url, out=None) -> dict                # non-image, outside the vault
    place_file(src, attachments, slug, index) -> dict  # rendered file -> the vault
    rename_slug(attachments, old_slug, new_slug, dry_run=False,
                sources=None) -> list[dict]
    validate_slug(slug, what="--slug") -> str          # raises ValueError
    run_self_test() -> int                             # also `selftest`

Output: one JSON object on stdout. Exit 0 if every item succeeded, 1 if any
failed (the JSON lists which). Stdlib only.
"""

import argparse
import base64
import glob
import ipaddress
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

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

from figure_state import MANIFEST_FILE, read_manifest


def _slug_spellings(slug):
    """The slug plus its other Unicode normalization form(s), deduplicated.

    On macOS a filename read back from disk is often NFD (decomposed) while
    the same slug passed on the command line is NFC — byte-different strings
    for one on-screen name.  ``glob`` matches by bytes against ``os.scandir``
    output, so a glob built from the NFC spelling silently matches nothing
    against NFD files (and vice versa): ``rename`` reports zero attachments
    for a note whose figures are right there, and ``_refuse_existing`` fails
    to see an occupied slot.  Globbing every spelling closes both.  ASCII
    slugs — the normal case — produce a single spelling and cost nothing.
    """
    out = [slug]
    for form in ("NFC", "NFD"):
        v = unicodedata.normalize(form, slug)
        if v not in out:
            out.append(v)
    return out


def _glob_slug(attachments, slug, tail):
    """Glob ``<attachments>/<slug><tail>`` under every spelling of ``slug``."""
    hits = []
    for spelling in _slug_spellings(slug):
        hits.extend(glob.glob(os.path.join(
            attachments, glob.escape(spelling) + tail)))
    return sorted(set(hits))

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

MIME_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/svg+xml": "svg",
}
KNOWN_EXT = {"png", "jpg", "jpeg", "gif", "webp", "svg", "avif", "bmp", "tiff"}

# Content-Types that say "bytes" and nothing more: the URL's extension is then
# the only hint left, so the extension fallback still applies to them.
GENERIC_CT = {"", "application/octet-stream", "binary/octet-stream",
              "application/binary", "unknown/unknown"}

ALLOWED_SCHEMES = {"http", "https", "data"}
DEFAULT_MAX_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_SECONDS = 120
CHUNK = 64 * 1024

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
            end, skip = s.find(">"), 1
        if end < 0:
            return False
        s = s[end + skip:].lstrip()
    return bool(_SVG_ROOT_RE.match(s))


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
    if head[4:8] == b"ftyp" and head[8:12] in (b"avif", b"avis"):
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
    """Detect the real image type: **the bytes decide**; the header is a hint.

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
    3. **Only genuinely unrecognized bytes fall through to the claims** —
       step 6's "an `image/*` subtype with no mapping → the URL's extension,
       else png" tail, plus the uninformative-Content-Type case
       (absent, or `application/octet-stream`), where the URL is all there is.

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
    if _binary_shape(head):
        return None                      # a PDF/ZIP/ELF/media file, whatever the header says
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct == "image/svg+xml":
        # An SVG is text and these bytes are not, so the header is the only
        # claim there is and the bytes contradict it.
        return None
    if ct in MIME_EXT:
        return MIME_EXT[ct]
    is_image_ct = ct.startswith("image/")
    if not is_image_ct and ct not in GENERIC_CT:
        return None                      # text/html, application/json, pdf, …
    if url:
        ext = os.path.splitext(urllib.parse.urlsplit(url).path)[1].lstrip(".").lower()
        if ext == "svg":
            return None                  # same reason: an SVG would have decoded as text
        if ext in KNOWN_EXT:
            return "jpg" if ext == "jpeg" else ext
    # An image/* subtype we have no mapping for still gets step 6's png
    # fallback; an uninformative Content-Type with no usable URL extension and
    # no recognizable magic bytes does not — there is no evidence of an image.
    return "png" if is_image_ct else None


def _temp_path():
    # No image extension, and outside Sources/Images on purpose: nothing half-written
    # or wrongly-named must ever appear in the vault.
    fd, path = tempfile.mkstemp(prefix="clipping_img.", suffix="")
    os.close(fd)
    return path


def _publish_file(src, final, overwrite=False, staging_parent=None, mode=0o644,
                  before_publish=None):
    """Publish complete bytes without risking the previous destination.

    A cross-filesystem shutil.move copies onto the final name before unlinking
    its source. An interrupted copy exposes a partial image and, on overwrite,
    destroys the old one. Stage beside the destination folder instead, then
    publish on that filesystem. New files use an exclusive hard link so a
    competing writer cannot be overwritten between the check and publication.
    """
    final = os.path.abspath(final)
    parent = staging_parent or os.path.dirname(final)
    with tempfile.TemporaryDirectory(prefix=".clipping-stage.", dir=parent) as stage:
        staged = os.path.join(stage, "complete")
        shutil.copyfile(src, staged)
        os.chmod(staged, mode)
        if before_publish is not None:
            before_publish()
        if overwrite:
            os.replace(staged, final)
        else:
            os.link(staged, final)
    try:
        os.remove(src)
    except OSError as exc:
        return "published successfully, but could not remove scratch source %r: %s" % (src, exc)
    return None


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
    for bad in ("/", "\\", "\x00"):
        if bad in slug:
            raise ValueError(f"{what} contains {bad!r}: {slug!r} — a slug is a "
                             "filename stem, not a path")
    if ".." in slug:
        raise ValueError(f"{what} contains '..': {slug!r} — a slug is a "
                         "filename stem, not a path")
    # `.` passed every check above and named no note: it wrote `._fig_1.png`,
    # a dotfile Obsidian does not show, this plugin's `Sources/Images` sweeps do
    # not glob, and wiki-builder's unused-figure diagnostic never sees. The
    # download reported ok and the figure was gone.
    if not slug.strip(". "):
        raise ValueError(f"{what} is {slug!r} — that names no note; a slug is a "
                         "filename stem, not a directory")
    return slug


def _ensure_within(directory, path):
    """Assert `path` really lands inside `directory`; return the resolved path."""
    root = os.path.realpath(directory)
    real = os.path.realpath(path)
    if not real.startswith(root + os.sep):
        raise ValueError(f"refusing to touch {real!r}: outside the attachments "
                         f"folder {root!r}")
    return real


def _reject_non_public(host, scheme="https"):
    """Refuse a host that resolves to loopback, link-local or private space.

    Best-effort, and racy by construction — a KNOWN, ACCEPTED limitation: the
    verdict comes from this resolution, while the fetch itself resolves the
    name again inside urlopen with nothing pinning the vetted address.  A host
    whose DNS answers a public address here and a private one there (deliberate
    rebinding, or plain short-TTL round-robin) is therefore fetched despite the
    refusal.  Closing that means resolving once and connecting by IP with a
    Host header, which urllib does not offer cleanly; the guard still stops
    every straightforward `file:`/loopback/RFC1918 URL and every redirect to
    one, which is the attack a clipped page actually carries.
    """
    # inet_aton accepts legacy numeric forms that getaddrinfo interprets
    # differently across operating systems (0177.0.0.1 is 127.0.0.1 on Linux,
    # but can resolve as 177.0.0.1 on macOS). A proxy may use either reading.
    # Refuse ambiguous forms before DNS; do not trust one platform's answer.
    try:
        numeric = socket.inet_ntoa(socket.inet_aton(host))
    except OSError:
        numeric = None
    if numeric is not None and numeric != host:
        raise ValueError(f"ambiguous numeric IPv4 host {host!r} — use {numeric!r} "
                         "instead (pass --allow-private-hosts if intended)")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        # Behind a proxy the name may only be resolvable at the proxy, so an
        # unresolvable host is not evidence of anything; let the fetch itself
        # fail. Without a proxy it would fail anyway, so say so here.
        if urllib.request.getproxies().get(scheme):
            return
        raise ValueError(f"cannot resolve host {host!r}: {exc}")
    for info in infos:
        addr = info[4][0].split("%")[0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if (ip.is_loopback or ip.is_link_local or ip.is_private
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise ValueError(
                f"host {host!r} resolves to the non-public address {ip} — "
                "refusing (pass --allow-private-hosts if that is intended)")


def check_url(url, allow_private=False):
    """Allow only http/https/data:, and (by default) only public hosts.

    urlopen speaks `file:` and `ftp:` natively and Web Clipper markdown carries
    `file://` image links from the user's own disk, so an unfiltered fetch will
    happily copy /etc/passwd into the vault under an image name.
    """
    parts = urllib.parse.urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise ValueError(f"unsupported URL scheme {scheme or '(none)'!r} — only "
                         "http, https and data: URIs are fetched")
    if scheme == "data":
        return
    if not parts.hostname:
        raise ValueError(f"URL has no host: {url[:120]!r}")
    if not allow_private:
        _reject_non_public(parts.hostname, scheme)


class _GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-run check_url on every redirect hop.

    urllib's own handler permits an http → ftp redirect and does not care where
    the target resolves, so a redirect is otherwise a way straight around
    check_url.
    """

    def __init__(self, allow_private=False):
        self.allow_private = allow_private

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl, self.allow_private)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener(allow_private=False):
    # build_opener keeps the default ProxyHandler (a corporate proxy still
    # works) and swaps in the guarded redirect handler for the stock one.
    return urllib.request.build_opener(_GuardedRedirectHandler(allow_private))


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


def _fetch_data_uri(url, tmp, max_bytes=DEFAULT_MAX_BYTES):
    # RFC 2397: `data:[<mediatype>][;<param>=<value>…][;base64],<data>` — the
    # mediatype may carry parameters, so the header is split at the FIRST
    # comma and read as `;`-tokens, with base64 mode decided by the LAST
    # token alone.  A regex admitting only a bare `;base64` refused
    # `data:image/png;charset=utf-8;base64,…` and the common inline-SVG form
    # `data:image/svg+xml;utf8,<svg…>` as malformed, so a legitimately
    # clipped image was reported failed.
    if url[:5].lower() != "data:" or "," not in url:
        raise ValueError("malformed data: URI")
    header, payload = url[5:].split(",", 1)
    tokens = header.split(";")
    is_b64 = len(tokens) > 1 and tokens[-1].strip().lower() == "base64"
    mime = tokens[0].strip()
    # The base64 payload is percent-DECODED first: RFC 2397's data production
    # is URL characters, so `%3D` padding and `%2B` plus signs are legal and
    # browsers unquote before decoding — refusing them failed a clipped image
    # the browser renders fine.  `unquote_to_bytes` leaves literal `+` and `=`
    # untouched (this is not form encoding), so an unescaped payload is
    # decoded byte-identically to before.
    raw = (base64.b64decode(urllib.parse.unquote_to_bytes(payload)) if is_b64
           else urllib.parse.unquote_to_bytes(payload))
    if len(raw) > max_bytes:
        raise ValueError(f"data: URI decodes to {len(raw)} bytes, over the "
                         f"{max_bytes}-byte cap")
    with open(tmp, "wb") as fh:
        fh.write(raw)
    return mime or None


def _refuse_existing(attachments, slug, index, overwrite):
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
    replace a figure in place, so the capability is kept -- behind an explicit
    `--overwrite`, which is a thing someone has to type.
    """
    owned = read_manifest(os.path.join(attachments, MANIFEST_FILE))
    prefix = unicodedata.normalize("NFC", f"{slug}_fig_{index}.").casefold()
    for name in owned:
        if unicodedata.normalize("NFC", name).casefold().startswith(prefix):
            raise ValueError(f"{name} is recorded in the PDF figure manifest — "
                             "clipping-processor cannot replace that producer's figure")
    if overwrite:
        return
    hit = _glob_slug(attachments, slug, f"_fig_{index}.*")
    if hit:
        raise ValueError(
            f"{os.path.basename(hit[0])} already exists in the attachments "
            "folder — refusing to overwrite it. Pass --overwrite if you are "
            "deliberately replacing this figure (a reprocess), or --start at "
            "the next free index if you are adding to the note.")


def _fetch_to_path(url, tmp, timeout, max_bytes, max_seconds, allow_private,
                   record=None):
    """Fetch `url` into `tmp` under every transport guard. -> (content_type, size)

    The scheme allowlist, the private-address refusal, the guarded redirect
    handler, the `Content-Length` pre-check, the byte cap, the wall-clock
    deadline and the truncation check, in one place. It is one place on
    purpose: `download` and `fetch` are the same transport with different
    destinations, and the way this skill's guards got bypassed before was a
    second copy of the fetch — a bare `urlopen` in a heredoc — that had none of
    them.
    """
    check_url(url, allow_private)
    deadline = time.monotonic() + max_seconds
    if url.lower().startswith("data:"):
        return _fetch_data_uri(url, tmp, max_bytes), os.path.getsize(tmp)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    # a per-socket timeout longer than the whole budget can't help
    sock_timeout = min(timeout, max_seconds) if max_seconds else timeout
    with _opener(allow_private).open(req, timeout=sock_timeout) as resp:
        content_type = resp.headers.get("Content-Type")
        # geturl() is the URL the bytes actually came from: a redirect
        # target is otherwise invisible in the report.
        if record is not None:
            record["final_url"] = resp.geturl()
        declared = resp.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > max_bytes:
            raise ValueError(f"Content-Length {declared} exceeds the "
                             f"{max_bytes}-byte cap")
        size = _stream_to_file(
            resp, tmp, max_bytes, deadline,
            int(declared) if declared and declared.isdigit() else None)
    return content_type, size


def download_one(url, attachments, slug, index, timeout=45,
                 max_bytes=DEFAULT_MAX_BYTES, max_seconds=DEFAULT_MAX_SECONDS,
                 allow_private=False, overwrite=False):
    """Fetch one image and move it to <attachments>/<slug>_fig_<index>.<ext>."""
    result = {"index": index, "url": url[:200] + ("…" if len(url) > 200 else ""),
              "final_url": None, "ok": False, "path": None, "filename": None,
              "ext": None, "bytes": 0, "error": None}
    tmp = _temp_path()
    try:
        validate_slug(slug)
        # Before the fetch: no reason to spend a download on a slot we are
        # going to refuse to write. Re-checked after, against the real path.
        _refuse_existing(attachments, slug, index, overwrite)
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
        os.makedirs(attachments, exist_ok=True)
        final = os.path.join(attachments, f"{slug}_fig_{index}.{ext}")
        _ensure_within(attachments, final)
        _refuse_existing(attachments, slug, index, overwrite)
        warning = _publish_file(
            tmp, final, overwrite,
            staging_parent=os.path.dirname(os.path.realpath(attachments)),
            before_publish=lambda: _refuse_existing(attachments, slug, index, overwrite))
        result.update(ok=True, path=final, filename=os.path.basename(final),
                      ext=ext, bytes=size, content_type=content_type)
        if warning:
            result["warning"] = warning
    except Exception as exc:             # 404, timeout, unsupported scheme, non-image
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return result


def fetch_source(url, out=None, timeout=45, max_bytes=DEFAULT_MAX_BYTES,
                 max_seconds=DEFAULT_MAX_SECONDS, allow_private=False,
                 overwrite=False):
    """Download a NON-image source file, under the same transport guards.

    Step 12's Lottie conversion needs the animation's `.json`/`.lottie` on disk
    before anything can render it, and that is not an image, so `download`
    cannot carry it. It used to be fetched by a bare `urllib.request.urlopen`
    inside a heredoc the model was told to write — which meant the one fetch in
    this skill that runs on a URL lifted straight out of a hostile page was
    also the one fetch with no scheme allowlist, no private-address refusal, no
    redirect re-check, no size cap and no wall-clock cap. This is
    `download_one`'s transport with the image sniff removed.

    **It never writes into the vault.** The destination is a temp file (or an
    explicit `--out`), and getting the rendered result *into* `Sources/Images/`
    is `place_file`'s job, which is where the slug, containment and
    occupied-slot guards live.
    """
    result = {"url": url[:200] + ("…" if len(url) > 200 else ""),
              "final_url": None, "ok": False, "path": None, "bytes": 0,
              "content_type": None, "error": None}
    tmp = _temp_path()
    try:
        if out is not None and os.path.lexists(out) and not overwrite:
            raise ValueError(f"{out!r} already exists — refusing to overwrite "
                             "it (pass --overwrite if that is intended)")
        content_type, size = _fetch_to_path(
            url, tmp, timeout, max_bytes, max_seconds, allow_private, result)
        if size == 0:
            raise ValueError("empty response")
        if out is None:
            out, tmp = tmp, None
        else:
            warning = _publish_file(tmp, out, overwrite, mode=0o600)
            if warning:
                result["warning"] = warning
        result.update(ok=True, path=os.path.abspath(out), bytes=size,
                      content_type=content_type)
    except Exception as exc:             # 404, timeout, unsupported scheme, cap
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if tmp is not None and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return result


def place_file(src, attachments, slug, index, overwrite=False):
    """Move a locally produced image into <attachments>/<slug>_fig_<index>.<ext>.

    `download_one`'s placement half, for a file this script did not fetch — the
    GIF step 12 renders from a Lottie. Every guard the download path applies to
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
        if not os.path.isfile(src):
            raise ValueError(f"--from-file {src!r} is not a file")
        root = os.path.realpath(attachments)
        real_src = os.path.realpath(src)
        if real_src == root or real_src.startswith(root + os.sep):
            raise ValueError(
                f"--from-file {src!r} is inside the attachments folder — "
                "render to a temp path outside the vault and place it from "
                "there, so nothing half-written ever appears in Sources/Images")
        size = os.path.getsize(src)
        if size == 0:
            raise ValueError("empty file")
        _refuse_existing(attachments, slug, index, overwrite)
        with open(src, "rb") as fh:
            head = fh.read(4096)
        # No Content-Type and no URL: a local file has only its bytes, which is
        # the evidence this script trusts anyway.
        ext = sniff_extension(head)
        if ext is None:
            raise ValueError("the file is not an image — the bytes look like "
                             f"{describe_bytes(head)}")
        os.makedirs(attachments, exist_ok=True)
        final = os.path.join(attachments, f"{slug}_fig_{index}.{ext}")
        _ensure_within(attachments, final)
        _refuse_existing(attachments, slug, index, overwrite)
        warning = _publish_file(
            src, final, overwrite,
            staging_parent=os.path.dirname(os.path.realpath(attachments)),
            before_publish=lambda: _refuse_existing(attachments, slug, index, overwrite))
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


def _pdf_named(sources, slug):
    """Is there a `<slug>.pdf` under `sources`?  Cheap, read-only."""
    key = unicodedata.normalize("NFC", slug).casefold()
    try:
        for root, _dirs, files in os.walk(sources):
            for f in files:
                if unicodedata.normalize("NFC", os.path.splitext(f)[0]).casefold() == key \
                        and f.lower().endswith(".pdf"):
                    return True
    except OSError:
        pass
    return False


#: What a refused member of the set does to the members that were fine.  A
#: figure set is renamed ALL OR NOTHING: the note's embeds are rewritten to one
#: slug, so a half-renamed set is a note where some embeds resolve and some do
#: not -- and neither slug holds the whole set, so no later run can tell which
#: half is which.
_STRADDLE = ("refused: this set is renamed all or nothing, and %s blocked it. "
             "Nothing was renamed. Resolve that one and re-run.")


def rename_slug(attachments, old_slug, new_slug, dry_run=False, sources=None):
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
    only the other producer writes, and — when `sources` is given — a PDF of
    that stem on disk, which settles ownership outright. A PDF-only label is a
    refusal for the WHOLE set, not just that file: it is evidence that the
    other producer owns this stem, and the plain-integer figures beside it are
    then just as likely to be its.
    """
    validate_slug(old_slug, "--old-slug")
    validate_slug(new_slug, "--new-slug")
    if sources is not None and not os.path.isdir(sources):
        raise ValueError("--sources is not a directory: %r — cannot verify PDF ownership" % sources)
    if sources and _pdf_named(sources, old_slug):
        return [{"from": old_slug + "_fig_*", "to": None, "ok": False,
                 "error": "refusing to rename: %s.pdf exists in %s, so these "
                          "figures belong to that document and are "
                          "pdf-organizer's to move, not this skill's"
                          % (old_slug, sources)}]
    owned = {unicodedata.normalize("NFC", name).casefold()
             for name in read_manifest(os.path.join(attachments, MANIFEST_FILE))}
    # --- plan: every member is judged before any of them is touched ---------
    # every Unicode spelling of the old slug: on macOS the on-disk files are
    # often NFD while the argument is NFC, and glob compares bytes.
    plan = []
    for src in _glob_slug(attachments, old_slug, _FIG_GLOB):
        base = os.path.basename(src)
        # the matched spelling's length, not the argument's — NFC and NFD
        # spellings of one slug differ in length.
        matched = next(s for s in _slug_spellings(old_slug)
                       if base.startswith(s))
        # Everything after the stem is carried across verbatim, separator
        # included, so a file written before the spellings converged keeps its
        # own label under the new stem and stays with its set, rather than
        # being re-spelled into the current convention by a rename.
        dst = os.path.join(attachments, new_slug + base[len(matched):])
        entry = {"from": base, "to": os.path.basename(dst), "ok": False,
                 "error": None}
        if dry_run:
            entry["dry_run"] = True
        if unicodedata.normalize("NFC", base).casefold() in owned:
            entry["error"] = "recorded in the PDF figure manifest; not this skill's to rename"
        elif _PDF_ONLY_LABEL.search(base):
            entry["error"] = ("label spelling only pdf-figure-extractor "
                              "writes; this file is a PDF's figure, not this "
                              "note's")
        elif not os.path.lexists(src):
            entry["error"] = "source missing"
        # lexists, not exists: a broken symlink at dst is still something there.
        elif os.path.lexists(dst) and not _same_file(src, dst):
            entry["error"] = "destination exists"
        else:
            try:
                _ensure_within(attachments, src)
                _ensure_within(attachments, dst)
            except ValueError as exc:
                entry["error"] = f"{type(exc).__name__}: {exc}"
        plan.append((src, dst, entry))

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
            os.rename(src, dst)
        except OSError as exc:
            # Put back what has already moved, so the set is still whole under
            # one slug and the re-run after the fix is the same operation.
            entry["error"] = f"{type(exc).__name__}: {exc}"
            for back_src, back_dst, back_entry in reversed(done):
                try:
                    os.rename(back_dst, back_src)
                    back_entry["ok"] = False
                    back_entry["error"] = _STRADDLE % os.path.basename(src)
                except OSError as back:
                    back_entry["error"] = ("rolled back and FAILED (%s) — this "
                                           "file is at its new name while the "
                                           "rest are at their old one" % back)
            for _s2, _d2, other in plan:
                if not other["ok"] and not other["error"]:
                    other["error"] = _STRADDLE % os.path.basename(src)
            return [e for _s, _d, e in plan]
        entry["ok"] = os.path.lexists(dst)
        done.append((src, dst, entry))
    return [e for _s, _d, e in plan]


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

    def __init__(self, chunks, headers=None):
        self._chunks = list(chunks)
        self.headers = dict(headers or {})

    def read1(self, _n=None):
        return self._chunks.pop(0) if self._chunks else b""

    def read(self, _n=None):
        raise AssertionError("_stream_to_file must read1(), not read()")


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
    cases = []

    def check(label, got, want):
        cases.append((label, got == want, got, want))

    def raises(label, fn, *a, **kw):
        """A guard is only a guard if it refuses; record WHAT it refused with."""
        try:
            fn(*a, **kw)
        except (ValueError, TypeError, TimeoutError) as exc:
            cases.append((label, True, type(exc).__name__, "refused"))
            return str(exc)
        except Exception as exc:                       # noqa: BLE001
            cases.append((label, False, "%s: %s" % (type(exc).__name__, exc),
                          "refused"))
            return ""
        cases.append((label, False, "accepted", "refused"))
        return ""

    # --- sniff_extension: bytes beat Content-Type beat the URL --------------
    for label, head, ct, url, want in (
            ("PNG magic", _PNG, None, None, "png"),
            ("JPEG magic", b"\xff\xd8\xff\xe0JFIF", None, None, "jpg"),
            ("GIF87a", b"GIF87a\x01\x00", None, None, "gif"),
            ("GIF89a", b"GIF89a\x01\x00", None, None, "gif"),
            ("WEBP", b"RIFF\x24\x00\x00\x00WEBPVP8 ", None, None, "webp"),
            ("AVIF", b"\x00\x00\x00 ftypavif\x00\x00", None, None, "avif"),
            ("BMP", b"BM\x36\x00", None, None, "bmp"),
            ("SVG, xml declaration first", b"<?xml version='1.0'?>\n<svg />",
             None, None, "svg"),
            ("SVG, bare root", b"<svg xmlns='...'></svg>", None, None, "svg"),
            # the disagreement cases: the bytes are the truth
            ("PNG bytes, jpeg Content-Type", _PNG, "image/jpeg", None, "png"),
            ("PNG bytes, .jpg URL", _PNG, None, "http://x/a.jpg", "png"),
            ("PNG bytes, text/html Content-Type", _PNG, "text/html",
             "http://x/a", "png"),
            # no magic: the Content-Type decides
            ("Content-Type png", b"\x00\x01\x02\x03", "image/png", None, "png"),
            ("Content-Type with a charset", b"\x00\x01", "image/png; charset=x",
             None, "png"),
            ("Content-Type jpeg normalises to jpg", b"\x00\x01", "image/jpeg",
             None, "jpg"),
            ("Content-Type uppercase", b"\x00\x01", "IMAGE/PNG", None, "png"),
            # an image/* subtype with no mapping falls back to the URL, then png
            ("unmapped image/*, URL extension", b"\x00\x01", "image/tiff",
             "http://x/a.tiff", "tiff"),
            ("unmapped image/*, no URL", b"\x00\x01", "image/heif", None, "png"),
            # a Content-Type carrying no information at all: the URL is all
            # that is left, and without it there is no evidence of an image
            ("octet-stream, .png URL", b"\x00\x01", "application/octet-stream",
             "http://x/a.png", "png"),
            ("octet-stream, .jpeg URL normalises", b"\x00\x01",
             "application/octet-stream", "http://x/a.jpeg", "jpg"),
            ("octet-stream, uppercase URL extension", b"\x00\x01",
             "application/octet-stream", "http://x/A.PNG", "png"),
            ("octet-stream, URL extension behind a query", b"\x00\x01",
             "application/octet-stream", "http://x/a.webp?w=800", "webp"),
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
                       ("Teslo..Cancer_2026", "`..` with no separator at all"),
                       ("", "an empty slug"),
                       ("   ", "a whitespace-only slug"),
                       (None, "no slug at all"),
                       (".", "a slug that names no note"),
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

    import shutil
    tmp = tempfile.mkdtemp(prefix="fetch_images_selftest.")
    previous_tempdir = tempfile.tempdir
    try:
        # The leak check must observe this run's scratch files, not another
        # self-test or real download using the same system temporary folder.
        tempfile.tempdir = tmp
        att = os.path.join(tmp, "Sources", "Images")
        os.makedirs(att)

        def touch(path, data=b"x"):
            with open(path, "wb") as fh:
                fh.write(data)
            return path

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
        # A host-less URL is refused HERE, by name, rather than falling into the
        # resolver — where it becomes "cannot resolve host None", or nothing at
        # all on a machine with a proxy configured for the scheme.
        check("check_url refuses an http URL with no host, and says so",
              "no host" in raises("check_url refuses a host-less URL",
                                  check_url, "http:///a.png"), True)
        check("check_url allows a data: URI",
              check_url("data:image/png;base64,AAAA"), None)
        check("check_url allows an ordinary https URL with --allow-private-hosts",
              check_url("https://example.com/a.png", True), None)
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
                            ("0.0.0.0", "the unspecified address")):
            url = "http://%s/a.png" % host
            try:
                socket.getaddrinfo(urllib.parse.urlsplit(url).hostname, None)
            except socket.gaierror:
                # Unresolvable here: `_reject_non_public` documents that it lets
                # those through (they may resolve at a proxy). Nothing to assert
                # about the range check, so do not claim to have asserted it.
                continue
            raises("check_url refuses %s (%s)" % (label, host), check_url, url)
            check("...unless --allow-private-hosts is passed (%s)" % host,
                  check_url(url, True), None)
        # the redirect handler re-runs the same guard, so a redirect is not a
        # way around it
        from unittest.mock import patch
        _public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("177.0.0.1", 0))]
        with patch.object(socket, "getaddrinfo", return_value=_public) as _dns:
            for _host in ("0177.0.0.1", "0x7f000001", "2130706433", "127.1"):
                raises("ambiguous numeric host is refused before a public DNS answer: "
                       + _host, check_url, "http://" + _host + "/a.png")
            check("numeric alias refusal does not consult the host resolver",
                  _dns.call_count, 0)
        # Redirects apply the same host guard as the initial request.
        raises("a redirect to file: is refused at the hop",
               _GuardedRedirectHandler(False).redirect_request,
               None, None, 302, "Found", {}, "file:///etc/passwd")

        # --- _stream_to_file, driven by a fake response ---------------------
        far = time.monotonic() + 60
        dst = os.path.join(tmp, "body")
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
        check("download_one writes <slug>_fig_<N>.<ext>",
              (res["ok"], res["filename"]),
              (True, "Teslo_Cancer_2026_fig_1.png"))
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
        check("--overwrite is what replaces it",
              download_one(data_url, att, "Teslo_Cancer_2026", 1,
                           overwrite=True)["ok"], True)
        # A failed cross-device move used to remove the previous good image.
        # Simulate an interrupted copy after it wrote bytes, not a successful
        # transfer whose return value merely says it failed.
        import errno
        def interrupted_copy(src, dst, *args, **kwargs):
            with open(dst, "wb") as fh:
                fh.write(b"incomplete")
            raise OSError(errno.ENOSPC, "injected disk-full copy")
        keep_image = os.path.join(att, "Teslo_Cancer_2026_fig_1.png")
        with patch.object(os, "rename", side_effect=OSError(errno.EXDEV, "different filesystem")), \
                patch.object(shutil, "copyfile", side_effect=interrupted_copy):
            failed_replace = download_one(data_url, att, "Teslo_Cancer_2026", 1,
                                          overwrite=True)
            failed_new = download_one(data_url, att, "Teslo_Cancer_2026", 99)
        check("a failed overwrite preserves the previous complete download",
              (failed_replace["ok"], os.path.exists(keep_image)
               and open(keep_image, "rb").read()), (False, _PNG))
        check("an interrupted new download exposes no final figure",
              (failed_new["ok"], _glob_slug(att, "Teslo_Cancer_2026", "_fig_99.*")),
              (False, []))
        check("failed publications leave no staging directories",
              glob.glob(os.path.join(os.path.dirname(att), ".clipping-stage.*")), [])
        # An explicit overwrite grants replacement of this clipping's figure,
        # never a file another producer has recorded as its own.
        import hashlib
        pdf_owned = os.path.join(tmp, "pdf-owned")
        os.makedirs(pdf_owned)
        owned_name = "Doe_Paper_2026_fig_1.png"
        owned_file = touch(os.path.join(pdf_owned, owned_name), _PNG)
        with open(os.path.join(pdf_owned, MANIFEST_FILE), "w") as fh:
            fh.write(owned_name + "\t" + hashlib.sha256(_PNG).hexdigest() + "\n")
        blocked_download = download_one(data_url, pdf_owned, "Doe_Paper_2026", 1,
                                        overwrite=True)
        owned_render = touch(os.path.join(tmp, "owned-render.png"), _PNG)
        blocked_place = place_file(owned_render, pdf_owned, "Doe_Paper_2026", 1,
                                   overwrite=True)
        check("overwrite never replaces a PDF-manifest-owned figure",
              (blocked_download["ok"], blocked_place["ok"],
               open(owned_file, "rb").read(), os.path.exists(owned_render)),
              (False, False, _PNG, True))
        check("recorded PDF figures cannot be renamed by a clipping either",
              [row["ok"] for row in rename_slug(pdf_owned, "Doe_Paper_2026", "New_Note_2026")],
              [False])
        with open(os.path.join(pdf_owned, MANIFEST_FILE), "w") as fh:
            fh.write("not a valid ownership record\n")
        check("a malformed ownership manifest does not authorize a write",
              download_one(data_url, pdf_owned, "New_Clipping_2026", 1)["ok"], False)
        # the slot is `<slug>_fig_<N>.*`, not one filename: a .webp at the same
        # index is the same slot, or the extension-twin comes back
        touch(os.path.join(att, "Teslo_Cancer_2026_fig_2.webp"))
        check("a different extension at the same index is the same slot",
              download_one(data_url, att, "Teslo_Cancer_2026", 2)["ok"], False)
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
        check("fetch brings a NON-image source down (a Lottie is JSON)",
              (got["ok"], open(got["path"], "rb").read()), (True, anim))
        check("...to a path outside the attachments folder",
              os.path.realpath(got["path"]).startswith(
                  os.path.realpath(att) + os.sep), False)
        check("...under the same size cap as download",
              fetch_source("data:application/json;base64,"
                           + base64.b64encode(anim).decode("ascii"),
                           max_bytes=10)["ok"], False)
        os.remove(got["path"])
        out_path = os.path.join(tmp, "anim.json")
        touch(out_path, b"mine")
        check("fetch refuses an --out that already exists",
              fetch_source("data:application/json,x", out_path)["ok"], False)
        check("...and leaves it untouched", open(out_path, "rb").read(), b"mine")
        bad = fetch_source("file:///not-a-permitted-source", out_path,
                           overwrite=True)
        check("fetch validation failure never deletes an overwrite destination",
              (bad["ok"], os.path.exists(out_path) and open(out_path, "rb").read()),
              (False, b"mine"))
        def interrupted_fetch(url, destination, *args, **kwargs):
            touch(destination, b"partial response")
            raise TimeoutError("injected transfer interruption")
        new_out = os.path.join(tmp, "new-animation.json")
        with patch.dict(globals(), {"_fetch_to_path": interrupted_fetch}):
            new_failed = fetch_source("https://example.com/anim.json", new_out)
            old_failed = fetch_source("https://example.com/anim.json", out_path,
                                      overwrite=True)
        check("an interrupted explicit fetch leaves no retry-blocking partial file",
              (new_failed["ok"], os.path.exists(new_out)), (False, False))
        check("an interrupted fetch leaves the previous source byte-identical",
              (old_failed["ok"], os.path.exists(out_path)
               and open(out_path, "rb").read()), (False, b"mine"))
        check("retrying an interrupted fetch works without overwrite",
              fetch_source("data:application/json,retry", new_out)["ok"], True)

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
                         overwrite=True)["ok"], True)
        replacement = touch(os.path.join(tmp, "replacement.gif"), gif)
        keep_gif = os.path.join(att, "Teslo_Cancer_2026_fig_20.gif")
        prior_gif = open(keep_gif, "rb").read()
        with patch.object(os, "rename", side_effect=OSError(errno.EXDEV, "different filesystem")), \
                patch.object(shutil, "copyfile", side_effect=interrupted_copy):
            failed_place = place_file(replacement, att, "Teslo_Cancer_2026", 20,
                                      overwrite=True)
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

        res = download_one("file:///etc/passwd", att, "Teslo_Cancer_2026", 8)
        check("download_one refuses a file: URL", res["ok"], False)
        res = download_one(data_url, att, "../escape", 9)
        check("download_one refuses a slug that is a path", res["ok"], False)
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

        folder = figures("Old_Slug_2025")
        out = rename_slug(folder, "Old_Slug_2025", "New_Slug_2026")
        check("a clean rename renames the whole set",
              ([e["ok"] for e in out], sorted(os.listdir(folder))),
              ([True, True, True],
               ["New_Slug_2026_fig_1.png", "New_Slug_2026_fig_2.png",
                "New_Slug_2026_fig_3.png"]))
        check("renaming a stem with no figures is empty, not an error",
              rename_slug(folder, "Nobody_Home_2020", "X_2021"), [])

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
        out = rename_slug(folder, "Old_Slug_2025", "New_Slug_2026")
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
        out = rename_slug(folder, "Old_Slug_2025", "New_Slug_2026")
        check("...as is a hand-named `_figure_N`",
              ([e["ok"] for e in out], sorted(os.listdir(folder))),
              ([True, True],
               ["New_Slug_2026_fig_1.png", "New_Slug_2026_figure_3.png"]))
        # the ownership guard has to read the older spelling as well, or a
        # loose glob just widens what gets taken from the other producer
        folder = figures("Doe_Old_2025", ("_fig_1.png", old_s1))
        out = rename_slug(folder, "Doe_Old_2025", "New_Note_2026")
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
        out = rename_slug(folder, "Old_Slug_2025", "New_Slug_2026")
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
        out = rename_slug(folder, "Old_Slug_2025", "New_Slug_2026", dry_run=True)
        check("--dry-run reports the same refusal the run would make",
              [e["ok"] for e in out], [False, False, False])
        check("...and is marked as a dry run",
              all(e.get("dry_run") for e in out), True)
        folder = figures("Old_Slug_2025")
        out = rename_slug(folder, "Old_Slug_2025", "New_Slug_2026", dry_run=True)
        check("--dry-run on a clean set reports every file and writes nothing",
              ([e["ok"] for e in out],
               sorted(os.listdir(folder))[0]),
              ([True, True, True], "Old_Slug_2025_fig_1.png"))

        # A rename that fails PART-WAY — a full disk, a vault mount that drops
        # out — is put back, for the same reason a refusal stops the set: half
        # a set under each slug is the state no re-run can repair. os.rename is
        # swapped for the length of this one call because there is no portable
        # way to make the second rename of three fail on demand.
        folder = figures("Old_Slug_2025")
        real_rename, calls = os.rename, []

        def _flaky_rename(src, dst):
            calls.append(src)
            if len(calls) == 2:
                raise OSError(28, "No space left on device")
            return real_rename(src, dst)

        os.rename = _flaky_rename
        try:
            out = rename_slug(folder, "Old_Slug_2025", "New_Slug_2026")
        finally:
            os.rename = real_rename
        check("a rename that fails part-way is rolled back",
              sorted(os.listdir(folder)),
              ["Old_Slug_2025_fig_1.png", "Old_Slug_2025_fig_2.png",
               "Old_Slug_2025_fig_3.png"])
        check("...and no member is reported renamed",
              [e["ok"] for e in out], [False, False, False])
        check("...with the OS error named",
              sum("No space left" in (e["error"] or "") for e in out), 1)

        # A case-only rename is not a collision: it is the documented
        # old-convention reprocess, and on a case-insensitive volume src and
        # dst are one file.
        folder = figures("teslo_cancer_2026", ("_fig_1.png",))
        out = rename_slug(folder, "teslo_cancer_2026", "Teslo_Cancer_2026")
        check("a case-only rename is allowed", [e["ok"] for e in out], [True])
        # ...which is decided by `_same_file`, not by the names. The vault's own
        # volume is case-insensitive, where src and dst ARE one file and
        # `lexists(dst)` is true; a hard link reproduces that here on any
        # filesystem, and without `samefile` the documented reprocess is
        # refused as a collision forever.
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
            check("a destination that IS the source is not a collision",
                  [e["ok"] for e in rename_slug(folder, "teslo_cancer_2026",
                                                "Teslo_Cancer_2026")], [True])

        # Sources/Images is FLAT and shared. Two guards say the stem is a PDF's.
        folder = figures("Doe_Foo_2025", ("_fig_1.png", "_fig_S1.png"))
        out = rename_slug(folder, "Doe_Foo_2025", "New_Note_2026")
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
            out = rename_slug(folder, "Doe_Bar_2025", "New_Note_2026")
            check("a %s label is pdf-figure-extractor's" % label,
                  any(e["ok"] for e in out), False)
        # ...and a plain integer label is this skill's own, so it renames
        folder = figures("Doe_Baz_2025", ("_fig_1.png", "_fig_12.png"))
        out = rename_slug(folder, "Doe_Baz_2025", "New_Note_2026")
        check("a plain integer label is this skill's", [e["ok"] for e in out],
              [True, True])

        # ...and a `<stem>.pdf` on disk settles ownership outright
        sources = os.path.join(tmp, "Sources", "PDFs")
        os.makedirs(os.path.join(sources, "sub"))
        touch(os.path.join(sources, "sub", "Doe_Qux_2025.pdf"))
        folder = figures("Doe_Qux_2025", ("_fig_1.png",))
        out = rename_slug(folder, "Doe_Qux_2025", "New_Note_2026",
                          sources=sources)
        check("a PDF of that stem refuses the rename",
              [e["ok"] for e in out], [False])
        check("...naming pdf-organizer as whose move it is",
              "pdf-organizer" in (out[0]["error"] or ""), True)
        check("...and leaves the figures alone",
              os.listdir(folder), ["Doe_Qux_2025_fig_1.png"])
        check("...while a stem with no PDF renames normally",
              [e["ok"] for e in rename_slug(folder, "Doe_Qux_2025",
                                            "New_Note_2026")], [True])
        accented = "Müller_Topic_2026"
        touch(os.path.join(sources, "sub", unicodedata.normalize("NFD", accented) + ".pdf"))
        folder = figures(accented, ("_fig_1.png",))
        out = rename_slug(folder, accented, "New_Note_2026", sources=sources)
        check("an NFD PDF filename still owns an NFC figure stem",
              [e["ok"] for e in out], [False])
        check("...and its figures stay under their original stem",
              os.listdir(folder), [accented + "_fig_1.png"])
        raises("a mistyped --sources path cannot silently disable ownership checks",
               rename_slug, folder, accented, "New_Note_2026",
               sources=os.path.join(sources, "missing-folder"))
        raises("rename_slug validates both slugs", rename_slug, folder,
               "../old", "new")
        raises("...including the new one", rename_slug, folder, "old",
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
        audit_md = doc("references", "completeness-audit.md")

        # `rename`'s ownership guard is real, and `--sources` is what arms it.
        # It appeared in NO markdown file, so both documented invocations ran
        # without it and the refusal never fired in practice.
        rename_calls = re.findall(
            r"fetch_images\.py rename[^\n`]*--attachments[^\n`]*",
            skill_md + images_md)
        check("every documented `rename` invocation passes --sources",
              (len(rename_calls) >= 3,
               [c for c in rename_calls if "--sources" not in c]),
              (True, []))
        check("...and SKILL.md no longer says the script simply cannot tell "
              "whose figures it holds",
              bool(re.search(r"unless you give it `--sources`|"
                             r"cannot tell whose figures it is holding — with "
                             r"that flag", skill_md)), True)

        # `Sources/PDFs/` is recursive by contract (a split book lives in
        # `Sources/PDFs/<Work>/`), so the step-3 stem-owner probe has to
        # recurse. `ls -d '<vault>/Sources/PDFs/<slug>.'*` could not see a
        # chapter stem, and the collision it exists to catch went unreported.
        check("the step-3 stem-owner probe searches Sources/PDFs recursively",
              bool(re.search(r"find '<vault>/Sources/PDFs' -name '<slug>\.\*'",
                             skill_md)), True)
        check("...and no longer globs that folder one level deep",
              "ls -d '<vault>/Sources/PDFs/" in skill_md, False)

        # The caps are defaults behind flags, and `--allow-private-hosts` turns
        # off a guard the same bullet list sells as unconditional. None of the
        # four was named anywhere in the prose.
        for flag in ("--max-bytes", "--max-seconds", "--timeout",
                     "--allow-private-hosts"):
            check("references/images.md names %s" % flag, flag in images_md,
                  True)
        check("...and says --allow-private-hosts turns the host guard off",
              bool(re.search(r"--allow-private-hosts.{0,400}?\boff\b",
                             images_md, re.S)), True)

        # The Lottie converter: the download and the final placement must go
        # through this script, and the heredoc must keep to rendering.
        check("the documented Lottie flow fetches through this script",
              "fetch_images.py' fetch" in audit_md, True)
        check("...and places through this script",
              "fetch_images.py' place" in audit_md, True)
        heredoc = re.search(r"<<'PYEOF'\n(.*?)\nPYEOF", audit_md, re.S)
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
            if callable(ns.get("load_anim")):
                import zipfile
                packed = os.path.join(tmp, "oversized.lottie")
                with zipfile.ZipFile(packed, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr("animations/a.json", b" " * 1024)
                ns["MAX_JSON_BYTES"] = 64
                raises("a small ZIP cannot expand past the animation JSON cap",
                       ns["load_anim"], packed)
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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("download", help="download images into Sources/Images/")
    d.add_argument("urls", nargs="*")
    d.add_argument("--attachments", required=True)
    d.add_argument("--slug", required=True)
    d.add_argument("--start", type=int, default=1)
    d.add_argument("--urls-file", help="file with one URL per line; - for stdin")
    d.add_argument("--timeout", type=int, default=45,
                   help="per-socket-operation timeout, seconds (default 45)")
    d.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES,
                   help=f"per-image size cap (default {DEFAULT_MAX_BYTES})")
    d.add_argument("--max-seconds", type=int, default=DEFAULT_MAX_SECONDS,
                   help="wall-clock budget for one image, across the whole "
                        f"transfer (default {DEFAULT_MAX_SECONDS})")
    d.add_argument("--allow-private-hosts", action="store_true",
                   help="permit hosts resolving to loopback/link-local/private "
                        "addresses (off by default)")
    d.add_argument("--overwrite", action="store_true",
                   help="replace an existing <slug>_fig_<N>.* instead of "
                        "refusing it (the documented reprocess path; off by "
                        "default, because a wrong --start otherwise destroys "
                        "the figures already filed under that name)")

    f = sub.add_parser("fetch", help="download a non-image source file (a "
                       "Lottie's .json/.lottie) to a temp path OUTSIDE the vault")
    f.add_argument("url")
    f.add_argument("--out", help="where to write it (default: a temp file "
                   "outside the vault); an existing path is refused unless "
                   "--overwrite")
    f.add_argument("--timeout", type=int, default=45,
                   help="per-socket-operation timeout, seconds (default 45)")
    f.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES,
                   help=f"size cap (default {DEFAULT_MAX_BYTES})")
    f.add_argument("--max-seconds", type=int, default=DEFAULT_MAX_SECONDS,
                   help="wall-clock budget across the whole transfer "
                        f"(default {DEFAULT_MAX_SECONDS})")
    f.add_argument("--allow-private-hosts", action="store_true",
                   help="permit hosts resolving to loopback/link-local/private "
                        "addresses (off by default)")
    f.add_argument("--overwrite", action="store_true")

    p = sub.add_parser("place", help="move a locally rendered image into "
                       "Sources/Images/ under this script's write guards")
    p.add_argument("--attachments", required=True)
    p.add_argument("--slug", required=True)
    p.add_argument("--index", type=int, required=True)
    p.add_argument("--from-file", required=True, dest="from_file",
                   help="the rendered file, which must live OUTSIDE the "
                        "attachments folder; it is moved, not copied, and its "
                        "extension comes from its bytes, not from its name")
    p.add_argument("--overwrite", action="store_true",
                   help="replace an existing <slug>_fig_<N>.* instead of "
                        "refusing it (off by default)")

    r = sub.add_parser("rename", help="rename attachments after a slug change")
    r.add_argument("--attachments", required=True)
    r.add_argument("--sources", help="the vault's Sources/PDFs folder; "
                   "given, a <slug>.pdf there proves the figures are a "
                   "PDF's and the rename is refused")
    r.add_argument("--old-slug", required=True)
    r.add_argument("--new-slug", required=True)
    r.add_argument("--dry-run", action="store_true")

    sub.add_parser("selftest", help="run the built-in cases (offline)")

    args = ap.parse_args(argv)

    if args.cmd == "selftest":
        return run_self_test()

    if args.cmd == "download":
        urls = list(args.urls)
        if args.urls_file:
            stream = sys.stdin if args.urls_file == "-" else open(args.urls_file)
            urls += [ln.strip() for ln in stream if ln.strip()]
        if not urls:
            ap.error("no URLs given")
        try:
            validate_slug(args.slug)      # once, loudly, not N identical failures
        except ValueError as exc:
            print(json.dumps({"mode": "download", "slug": args.slug,
                              "error": str(exc), "results": [], "downloaded": 0,
                              "failed": len(urls)}, indent=2, ensure_ascii=False))
            return 1
        results = []
        for i, url in enumerate(urls, start=args.start):
            results.append(download_one(
                url, args.attachments, args.slug, i, timeout=args.timeout,
                max_bytes=args.max_bytes, max_seconds=args.max_seconds,
                allow_private=args.allow_private_hosts,
                overwrite=args.overwrite))
        failed = [x for x in results if not x["ok"]]
        out = {"mode": "download", "slug": args.slug,
               "attachments": args.attachments, "results": results,
               "downloaded": len(results) - len(failed), "failed": len(failed),
               "next_index": args.start + len(results)}
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 1 if failed else 0

    if args.cmd == "fetch":
        res = fetch_source(args.url, args.out, timeout=args.timeout,
                           max_bytes=args.max_bytes,
                           max_seconds=args.max_seconds,
                           allow_private=args.allow_private_hosts,
                           overwrite=args.overwrite)
        print(json.dumps(dict(res, mode="fetch"), indent=2,
                         ensure_ascii=False))
        return 0 if res["ok"] else 1

    if args.cmd == "place":
        res = place_file(args.from_file, args.attachments, args.slug,
                         args.index, overwrite=args.overwrite)
        print(json.dumps(dict(res, mode="place", slug=args.slug,
                              attachments=args.attachments), indent=2,
                         ensure_ascii=False))
        return 0 if res["ok"] else 1

    try:
        results = rename_slug(args.attachments, args.old_slug, args.new_slug,
                              args.dry_run, getattr(args, 'sources', None))
    except ValueError as exc:
        print(json.dumps({"mode": "rename", "old_slug": args.old_slug,
                          "new_slug": args.new_slug, "error": str(exc),
                          "results": [], "renamed": 0, "failed": 0},
                         indent=2, ensure_ascii=False))
        return 1
    failed = [x for x in results if not x["ok"]]
    print(json.dumps({"mode": "rename", "old_slug": args.old_slug,
                      "new_slug": args.new_slug, "results": results,
                      "renamed": len(results) - len(failed),
                      "failed": len(failed)}, indent=2, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
