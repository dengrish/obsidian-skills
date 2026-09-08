# Photo and PDF attachments

Read before downloading attachments or maintaining locally saved source files.
The collector saves source bytes; it does not interpret figures, summarize PDFs,
perform OCR or turn linked webpages into new sources.

## Match files to the primary post

New timeline windows and explicitly authorized reconciliation requests use
`expansions=attachments.media_keys` with
`media.fields=media_key,type,url,alt_text,width,height`. Match `includes.media`
only to the returned primary post's own `attachments.media_keys`. Save photos;
do not download videos, animated-video variants or unrelated expanded media.
A quote post's own attachments are eligible, but the quoted post is not fetched.

Treat missing or conflicting attachment metadata as incomplete. Earlier records
may contain media keys without URLs. Webpage-card thumbnails in `entities.urls`
are not a substitute for original attached images. Do not construct an image URL
from a media key, scrape X or purchase a post again just to fill this gap.

For PDFs, use returned expanded or unwound URLs whose path directly identifies
a `.pdf` document, including URLs with query strings. Do not follow a blog,
newsletter, landing page or login flow looking for documents. Unsupported links
remain source links. The downloaded bytes must be a supported image or PDF;
an HTTP success or filename extension alone is not sufficient.

## Download and reuse

The sibling `scripts/feed_media.py` helper implements attachment discovery,
bounded HTTPS retrieval, local receipts and guarded publication. Use it through
`feed_collect.py`; do not rewrite a downloader or copy it into another plugin.
Collection downloads available attachments before publishing the account note.
`--max-downloads` and `--max-attachment-bytes` bound that run's attachment work,
independently of the paid X post/request budgets. Zero downloads leaves files
deferred. Download limits never authorize increasing the X budget.

To process URLs already present in saved posts without calling the X API:

```bash
python3 '<skill>/scripts/feed_collect.py' attachments --vault '<vault>' \
    --max-downloads 40 --max-attachment-bytes 268435456
```

No X credential is needed for this command. Ready files are reused after
verification; missing metadata is reported. Failed or interrupted downloads
are retained as explicit receipt states rather than repeatedly fetched behind
the user's back. An explicit `--retry-attachments` retries those file downloads
within the same limits; it never authorizes a paid X post reread.
If an interrupted private cache has partial or changed bytes, preserve that
file: an explicit retry uses a fresh cache leaf and keeps its recovery locator
in durable state. Report retained recovery files for inspection; do not delete
or overwrite them merely because the new download succeeded.

An old post whose attachment metadata is missing requires the separate
`reconcile --ids ... --allow-paid-reread` workflow under [X access](x-api.md).
Select only known affected IDs and obtain authorization for that reread; then
reuse the stored response for publication or download retries. Do not reread
every saved post or promise that an API provider's billing deduplication is free.

## Files and notes

- Photos go to flat `Sources/Images/` and appear as full vault-relative local
  embeds beneath their post text. PDFs go to `Sources/PDFs/` and appear as local
  links, not embedded PDF viewers. Preserve the source URL in the receipt.
- Names follow `x-<post-id>-<asset-hash>.<ext>`. They identify the captured source
  without inventing a title or requiring the knowledge plugin. File extensions
  follow verified content. The collector never claims a figure-extract manifest
  entry or renames somebody else's asset.
- URL identity and verified content digests are recorded in the durable feed
  state. Repeated runs use those receipts. Preserve the state with the account
  notes and downloaded files; losing it does not authorize adopting an occupied
  filename or downloading paid posts again.
- Reuse a photo by its X media key. Capture PDFs separately for each post, even
  when another post links the same URL: the document at that URL may have changed.
  The note's collapsed source metadata records each file's capture time, source
  URL, local path, digest and status without exposing private recovery paths.
- Downloads use public HTTPS with no X Authorization header, ambient cookies or
  proxy credentials. Validate and pin public addresses for every redirect hop;
  reject local/private destinations, unsupported ports, credentials in URLs,
  active image formats, oversized files and error pages disguised as documents.
- Stage complete validated files privately on the destination filesystem and
  publish exclusively through the shared safe-write helper. Preserve unexpected
  occupants, case/Unicode collisions and later edits. A failed file does not
  erase successfully collected post text or silently fall back to a remote embed.

Report attachment counts separately from X post rows. Show missing, deferred or
failed attachments truthfully; do not present a source locator as a saved file.
`publish` is offline and does not repair missing files through hidden downloads.

## Source changes and cleanup

Positive post removal, withholding or a new edited version can retire attachments
that are no longer referenced by any retained post. Remove only collector-owned
files whose bytes still match their receipt, through conditional cleanup. Check
other Markdown notes and Canvas files first; keep and report foreign references or changed occupants
instead of breaking links or deleting unknown content. Shared assets still used
by another collected post remain in place.

This is source-compliance maintenance, not general vault orphan cleanup. It does
not permit changing immutable market-research records or renaming assets used by
another workflow. An ambiguous API or download error does not prove deletion.
