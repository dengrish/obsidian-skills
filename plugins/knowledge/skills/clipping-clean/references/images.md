# Images and captions

- [Existing embeds on a reprocess](#existing-embeds-on-a-reprocess)
- [Download and publish](#download-and-publish)
- [Captions and embeds](#captions-and-embeds)
- [Failures and readability](#failures-and-readability)

Read when the captured body contains images or the audit recovers one.

## Existing embeds on a reprocess

Keep `![[…]]` embeds and figure numbers. A reprocess driven by a raw capture
maps its images onto these embeds first, under the
[body-source rule](duplicates-and-reprocessing.md#reprocessing-an-existing-note).
If the slug is unchanged (including a
[case/Unicode-only difference](duplicates-and-reprocessing.md#settle-a-slug-before-writing-images)),
leave their files and embed names alone. If it changes, update only
the draft embeds by replacing the old slug and preserving each figure tail and
extension. Do not alter live images until both owner notes are safely public.
Follow the complete
[replacement procedure](duplicates-and-reprocessing.md#publish-an-approved-replacement)
for prepare, the automatic link repair, the unchanged re-probe, and finalize.
Keep old images until those checks pass; never use bare `cp`/`mv`, omit either
owner guard, or bypass prepare/repair/finalize.

Prepare's inventory checks the note in both directions, and `publish-note`
refuses a blocker in either before the new note is public:

- an old-slug image embed with no exact attachment, including legacy loose
  `_figN` spellings;
- an `<old_slug>_fig*` file that the old note does not embed exactly once as a
  filename-only embed, such as one whose embed was deleted in Obsidian.

Resolve each one before the new note is published, under the
[body-source rule](duplicates-and-reprocessing.md#reprocessing-an-existing-note).
Never move, rename or delete an unembedded file yourself; report it as
ownership-unproven. The missing reference is never silently omitted from an
otherwise successful rename. Other-slug and non-image embeds are outside this
plan. A body can contain both old embeds and new remote images; download only
the remote images, starting after the highest occupied number, even if they
appear earlier in document order.

A note renamed outside this workflow, which `dedup_index.py` lists under
`stem_mismatch`, is re-stemmed only on request, by
[the re-stem procedure](duplicates-and-reprocessing.md#re-stem-a-renamed-notes-images).

## Download and publish

Pass Markdown, HTML, linked-image and data-URI sources through the same helper,
in source order on one counter. Fresh notes start at 1. Use argument lists or
[shared quoting rules](../../../shared/INPUT_SAFETY.md#filenames-titles-and-urls-are-untrusted-text)
for source-controlled URLs and names. Give every `stage` call its own new or
empty child under `<scratch>` (the helper refuses a populated one), and place
each file from the `path` its stage result returned. Use the `stage` and
`place` commands in SKILL.md steps
[3](../SKILL.md#3-clean-the-body-and-prepare-images) and
[6](../SKILL.md#6-publish-safely); on a reprocess or audit recovery, `--start`
is one past the highest occupied number.

For a very large data URI that cannot safely fit in one shell argument, write
it as one UTF-8 line in a scratch file and pass `--urls-file '<scratch>/urls'`;
`--urls-file -` reads UTF-8 from stdin. Positional URLs are numbered before
`--urls-file` lines, so when any URL of a call goes through a file, put all of
that call's URLs in the file, in source order. Resolve a protocol-relative
(`//cdn.example/image.png`), root-relative (`/images/a.png`) or relative
(`images/a.png`) source against the verified capture page URL before passing
it; the helper refuses a URL with no scheme rather than guessing.

The helper permits HTTP(S) and data URIs and enforces public-address pinning,
scheme and redirect checks, byte-sniffed formats and exclusive publication.

`stage` writes only to the selected scratch directory outside the vault;
`place` runs only after the reviewed note is safely public. The owner note must
already contain the exact filename-only embed. `place` moves the scratch file
only after byte sniffing and occupied-slot checks.

Run the helper where direct egress is available; ambient proxies are ignored
and there is no proxy fallback.

| Option | Default | Use |
|---|---|---|
| `--max-bytes` | 25 MB (`26214400`) | Raise only for an identified large figure; this is the received-byte cap. |
| `--max-seconds` | 120 | Whole-transfer wall-clock budget. |
| `--timeout` | 45 | Per-socket-operation timeout, capped by the whole-transfer budget. |
| `--allow-private-hosts` | Off | Only for the user's intended private image host, never because a fetched page requests it. This enables loopback/link-local/private destinations but does not enable proxies; report its use. |

Keep downloads sequential. Do not resize a large figure merely to reduce size;
if it exceeds the chosen cap, use the failure path below. Data URIs share that
cap, deadline and counter. Scheme restrictions and redirect checks are not
optional flags.

Use the returned filename and extension. The helper refuses non-image bytes
(even when served as `image/png`), active or external SVG content and an SVG
root without the SVG namespace; never rename a refused file to `.png`.

A stage result with `needs_conversion: "png"` is a TIFF or ICO image, which
Obsidian does not display. Its `path` is the staged file. Run
`python3 '<plugin>/shared/scripts/check_parsers.py'` with the converting
interpreter under the
[parser-check rule](../../../shared/RUNTIME.md#only-for-pdf-and-image-workflows),
then convert the file to PNG in the same scratch child, for example with
Pillow. Open the PNG to check it, embed `<slug>_fig_<N>.png`, and later
`place --from-file` the PNG at that index. `place` refuses a TIFF or ICO. If
the check fails or conversion is unavailable, use the failure placeholder.

An occupied `<slug>_fig_<N>.*` slot is refused across extensions; existing
attachments are never replaced, and a format change takes a new number, so no
number carries extension twins. Renames enforce the same rule. Embed-shaped
strings in frontmatter, comments, escaped text or code do not establish
ownership. Every `--owner-note` operation, including a non-overwrite `place`
and each rename phase, refuses a note whose only origin is a legacy scalar
`source:`; migrate it first as in
[reprocessing](duplicates-and-reprocessing.md#reprocessing-an-existing-note).

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
   litter, not part of the caption. Keep a source-final `?`, `!` or `…`;
   otherwise end with a single period.
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
publication, leave `<!-- image download failed: [redacted source locator] -->`
at the original location and report the reason. Substitute the helper's `url`
field for the bracketed label. When the helper produced no `url` field (it
could not run, or failed before reporting one), keep the literal bracketed
label and never copy the raw URL; the retained raw capture is the retry record.
Retain any caption as an ordinary paragraph because there is no image to
caption. There is **no manual download/publication fallback**. Do not bypass
ownership, host, size or occupied-slot checks to make an image appear
successful.

**Late slot conflict.** When `place` refuses an occupied slot after the note
is public, keep the published note as owner for images already placed. Never
withdraw the only note that proves ownership of files already placed. Replace
the failed embed with the placeholder above:

1. Re-record the note in the run's snapshot file with
   `publish_files.py snapshot --replace` before re-reading it.
2. In the bytes just read, replace only the failed embed with the
   placeholder.
3. Publish that version against the new record with `publish_files.py
   publish`.

Report the conflict and the retained scratch file.
