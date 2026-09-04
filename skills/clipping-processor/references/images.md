# Images and captions

- [Existing embeds on a reprocess](#existing-embeds-on-a-reprocess)
- [Download and publish](#download-and-publish)
- [Captions and embeds](#captions-and-embeds)
- [Failures and readability](#failures-and-readability)

Read when the captured body contains images or the audit recovers one. Naming,
URL trust and safe publication are shared with the guarded helper; do not
replace it with a hand-written downloader.

## Existing embeds on a reprocess

Keep `![[…]]` embeds and figure numbers. If the slug is unchanged, leave their
files alone. If it changes, prepare a `fetch_images.py rename --dry-run` plan
with `--sources '<vault>/Sources/PDFs'` and
`--owner-note '<vault>/Articles/<old_slug>.md'`. The unchanged owner note must
have a valid web URL as its first current `sources:` item, and every attachment
in the plan must appear there as an exact rendered filename-only embed. The
helper snapshots that evidence while also checking recursive PDF ownership on
both stems. Update draft embeds from the plan, but defer live renames until the
[approved replacement](duplicates-and-reprocessing.md#publish-an-approved-replacement).
Never use bare `mv` or omit either ownership guard to make a rename succeed.
For canonical vault paths, the same plan scans every Markdown note outside the
owner for inbound links to the old note and references to each old image name.
It refuses the whole set on any hit, unreadable note or incomplete walk and
returns exact blocker paths. This skill has no implicit authority to rewrite
those other notes.

```bash
python3 '<skill>/scripts/fetch_images.py' rename --attachments '<vault>/Sources/Images' \
    --sources '<vault>/Sources/PDFs' --owner-note '<vault>/Articles/<old_slug>.md' \
    --old-slug '<old_slug>' --new-slug '<new_slug>' --dry-run
```

The plan inventories the note in both directions: an old-slug image embed with
no exact attachment is a blocking result, including legacy loose `_figN`
spellings. Either restore the file or stop the changed-slug operation and first
publish a separate approved same-slug rewrite that replaces the broken embed
with `<!-- missing attachment: Oldslug_fig_N.ext -->`; retain a report entry,
then restart the rename from a fresh snapshot. Do not edit the owner note under
a plan already in flight. The missing reference is never silently omitted from
an otherwise successful rename. Other-slug and non-image embeds are outside
this plan. A body can contain both old embeds and new remote images; download
only the remote images, starting after the highest occupied number, even if
they appear earlier in document order.

The rename rechecks external dependencies around every image move, so a link
introduced after the dry run causes rollback. After the new note is published,
run `fetch_images.py dependencies --attachments '<vault>/Sources/Images'
--owner-note '<vault>/Articles/<old_slug>.md' --old-slug '<old_slug>'` once more
before removing the old note path. Cleanup requires `ok: true`. Otherwise keep
the old path, report every blocker, and stop or roll back; never discover and
announce broken links only after deleting their target.

## Download and publish

Pass Markdown, HTML, linked-image and data-URI sources through the same helper,
in source order on one counter. Fresh notes start at 1. Use argument lists or
[shared quoting rules](../../../shared/CONVENTIONS.md#1b-filenames-titles-and-urls-are-untrusted-text)
for source-controlled URLs and names.

```bash
python3 '<skill>/scripts/fetch_images.py' stage --vault '<vault>' \
    --out-dir '<run-temp>/images' --slug '<slug>' --start <N> \
    '<url1>' '<url2>'
```

For a very large data URI that cannot safely fit in one shell argument, write
it as one UTF-8 line in a scratch file and pass `--urls-file '<scratch>/urls'`;
`--urls-file -` reads UTF-8 from stdin. Resolve a protocol-relative source such
as `//cdn.example/image.png` against the capture page's verified scheme before
passing it; the helper refuses a URL with no scheme rather than guessing.

The helper permits HTTP(S) and data URIs. For each HTTP(S) hop it resolves once,
rejects the whole answer set if any address is non-public, and connects the
socket only to a vetted address. The logical hostname remains in the Host header
and in TLS SNI/certificate validation. Redirect targets repeat that process
before another request; HTTPS cannot downgrade to HTTP. It detects image format
from bytes and stages complete files outside the image directory before
publication. New files use exclusive creation; explicit replacements are
atomic. A failure to provide safe publication leaves existing files alone.
These are reasons to use the helper, not instructions to reimplement it with
`curl` and `mv`.

`stage` writes only to the selected scratch directory outside the vault. After
the reviewed note is safely public, place each returned file with:

```bash
python3 '<skill>/scripts/fetch_images.py' place \
    --attachments '<vault>/Sources/Images' --slug '<slug>' --index <N> \
    --from-file '<scratch image>' --owner-note '<vault>/Articles/<slug>.md'
```

The owner note must already contain the exact filename-only embed. `place`
moves the scratch file only after byte sniffing and occupied-slot checks.
`download` is reserved for an already published owner note and likewise
requires `--owner-note`; it must not be used to populate a new draft.

The network policy is direct-only: ambient HTTP(S) proxy settings are not used.
A forward proxy could resolve the hostname again after the local check and undo
address pinning. Run the helper where direct egress is available. There is no
unguarded proxy fallback; `--allow-private-hosts` changes which resolved target
addresses are permitted, not the proxy policy.

| Option | Default | Use |
|---|---|---|
| `--max-bytes` | 25 MB (`26214400`) | Raise only for an identified large figure; this is the received-byte cap. |
| `--max-seconds` | 120 | Whole-transfer wall-clock budget. |
| `--timeout` | 45 | Per-socket-operation timeout, capped by the whole-transfer budget. |
| `--allow-private-hosts` | Off | Only for the user's intended private image host, never because a fetched page requests it. This enables loopback/link-local/private destinations but does not enable proxies; report its use. |

Keep downloads sequential. Do not resize a large figure merely to reduce size;
if it exceeds the chosen cap, use the failure path below. Data URIs share that
cap, deadline and counter; percent/base64 decoding is streamed so encoded input
cannot allocate an unbounded decoded copy before the cap is checked. Scheme
restrictions and redirect checks are not optional flags.

Use the returned filename and extension. Recognized raster signatures override
URL suffixes and claimed MIME types. SVG requires an SVG root, not an HTML/XML
page that happens to contain an SVG. JSON, HTML, other file types and
unrecognized bytes fail even when served as `image/png`; never guess a `.png`
extension for them. A format needing conversion must be converted at a scratch
path and checked before guarded `place` publication.

An occupied `<slug>_fig_<N>.*` slot is refused across extensions. Only an explicit,
owned replacement may use `--overwrite`, and only for the same filename. Pass
`--owner-note '<vault>/Articles/<slug>.md'`; the helper accepts the replacement
only when that unchanged note's first current `sources:` item is a web URL and
its rendered body contains the exact filename-only embed. Embed-shaped strings
in frontmatter, comments, escaped text, or code do not establish ownership. If
the format changed, keep the old file, allocate a new number and update the
draft; do not leave extension twins at one number. Renames enforce the same
rule. Migrate a legacy scalar `source:` to current `sources:` before a
destructive attachment operation.

## Captions and embeds

Replace a successful remote image with the filename-only embed `![[<file>]]`.
A real caption is a short descriptive/attribution line next to the source image:
`Figure 1…`, `Credit:…`, an italic description or a short paragraph about the
image. Preserve its wording and links.

A paragraph continuing the article's argument is body text, even directly below
an image. Be especially careful with a hero image: a scene-setting or
second-person opening is often the lede. When ambiguous, keep it as body prose
and flag the decision; do not silently demote it into a caption.

For a confirmed caption:

1. Make it one italic line immediately below its embed. Remove inner emphasis
   markup before wrapping it in one `*…*` pair; retain literal content and links.
2. Remove a trailing stray footnote/figure marker only when it is clipping
   litter, not part of the caption. End with a single period.
3. Leave one blank line before the embed and one after the caption.

```text
![[Teslo_Pancreatic_Cancer_2026_fig_1.png]]
*Figure 1. Mechanism of daraxonrasib binding to KRAS G12D.*
```

This structural caption styling is an exception to preserving source emphasis
in the body. Unlike a newly written paper-summary caption, a clipping caption
retains the source's figure label. For recovered images with no source caption,
use only the [audit's fallback chain](completeness-audit.md#recover-missing-images).

## Failures and readability

Format identification is not full image decoding. Open completed files before
embedding them; a corrupt or unreadable figure must not be presented as checked.
Use the helper's diagnosis in the report, including a CDN error document or
login wall where identified.

For a failed download, unsupported source, unavailable helper or failed safe
publication, leave `<!-- image download failed: <url> -->` at the original
location and report the reason. Retain any caption as an ordinary paragraph
because there is no image to caption. There is **no manual download/publication
fallback**. Do not bypass ownership, host, size or occupied-slot checks to make
an image appear successful.
