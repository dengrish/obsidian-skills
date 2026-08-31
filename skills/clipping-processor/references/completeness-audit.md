# Completeness audit

- [Fetch and declare the audit scope](#fetch-and-declare-the-audit-scope)
- [Inventory and match media](#inventory-and-match-media)
- [Recover missing images](#recover-missing-images)
- [Flag media that cannot be recovered](#flag-media-that-cannot-be-recovered)
- [Compare article text](#compare-article-text)

Read when metadata verification fetched a usable source page. Compare the
complete draft against that page, recover eligible media, and flag other gaps.
This is a best-effort audit, not a promise of a perfect mirror. It never replaces
the user's captured prose with fetched text.

## Fetch and declare the audit scope

Keep two views for different jobs: raw/rendered markup exposes media, while the
host's extracted article text exposes prose gaps. Reuse the extracted text from
metadata verification; if needed, fetch it again with the host's web-fetch tool,
not a hand-written readability extractor.

Start the markup inspection with a permitted static fetch using a browser
User-Agent, following [host tool rules](../../../shared/RUNTIME.md#use-the-hosts-available-tools).
Upgrade once to an available browser when the static page is suspiciously
sparse: roughly fewer than 15 paragraphs, under 10 KB of article body after
head/scripts/styles, no images despite a figure-rich subject, or far less prose
than the page's declared word count. A Cloudflare challenge is a failed fetch,
not an article. These are signals to inspect further, not proof of missing
content.

Follow the browser tool's permitted inspection surface. Use rendered DOM or
visible content if that is what it provides; do not assume it permits raw HTML
extraction. If a permitted standalone Playwright is already available,
`goto(url, wait_until="networkidle", timeout=30000)` and `page.content()` can
supply rendered markup. Do not install or change permissions just to bypass an
unavailable browser. Report whether the audit used static or rendered content
and any inspection limits.

Every capture needs one explicit verdict in the final report:

- `Completeness audit: <N> recovered, <M> flagged, <K> decoratives skipped`, with
  the items listed.
- `Completeness audit: no gaps found`, after a usable comparison.
- `Completeness audit: SKIPPED — <reason>` when there is no reliable comparison:
  failed fetch/404, paywall stub, required browser/network access unavailable,
  or an unusable rendered page. A sparse static page alone triggers the browser
  fallback; it is not evidence that the audit passed or could not run.

A skipped audit can still yield a note from the curated capture, with the limit
reported. In batch mode assess and report each capture separately.

## Inventory and match media

Record figure-like media with caption/alt text, nearest heading and neighboring
prose: images (including SVG, `data-src`, `data-lazy-src`, `srcset` and picture
sources), inline SVG, video/source, canvas, iframes, animation containers and
figure/figcaption groups.

For Lottie, record a real `.json`/`.lottie` source exposed by `<lottie-player>`,
`<dotlottie-player>`, animation attributes or nearby source markup. Do not execute
source-page JavaScript to discover one. Associate a player and its sibling
static poster as **one** figure. Collapse desktop/mobile variants of the same
figure, preferring desktop; do not recover two copies. A poster is optional,
not assumed.

Match against the draft before recovering anything. Fresh-run source URLs are
strong evidence. On a reprocess the old embeds have no URLs: use caption/alt,
position and counts, and recover only a figure confidently absent. If existing
embeds already equal or exceed the page's figure count, recover nothing. When
uncertain, assume an existing counterpart rather than duplicating a figure.
Keep an existing converted-GIF embed and still-valid placeholder at its location.

Skip decorative images only with at least two supporting signals, such as empty
alt text, no figure/figcaption grouping, no adjacent caption, decoration names
(`Spot`, `Ornament`, `Divider`, `Banner`, `Badge`, `Ad`, `Promo`, `Spacer`), or an
explicit ad/promo context. Empty alt text alone does not make a diagram
decorative. When uncertain, retain a possible substantive figure. Report each
skipped decorative briefly; do not also flag it as missed content.

**Process a Lottie figure before its poster.** Load [Lottie recovery](lottie-recovery.md)
only for that media type. It owns the GIF → labeled poster → placeholder chain;
this audit must not recover the poster first and mark the animation done.

## Recover missing images

For a confidently missing figure with a downloadable image URL and no Lottie,
use [the guarded image pipeline](images.md#download-and-publish). Continue after
the highest occupied figure number; filenames identify assets, not display
order. Insert the embed beside its source caption or neighboring sentence. If
placement is uncertain, use the most-related paragraph and report it as
approximate.

Use this caption fallback chain, then apply [caption styling](images.md#captions-and-embeds):

1. The page's caption/credit or a nearby caption-shaped element.
2. A credit clearly encoded in the image filename (`crMarkBelan`, `-credit-`,
   `-photo-`, etc.). Do not invent an affiliation the filename/page does not
   establish.
3. A short description drawn only from the **immediately preceding paragraph**
   when it actually describes the figure's construction or introduces it with
   “as follows:”, “like so:”, or similar. Include `(synthesized from context)`.
   Do not draw from later paragraphs or add visual details the lead-in did not
   state.
4. A bare embed when none of those sources supports a caption. This is preferable
   to fabrication.

Apply only the same decorative Latin/digit normalization permitted for metadata;
keep meaningful scientific symbols. Never italicize the article's lede to fill
a missing caption.

## Flag media that cannot be recovered

Keep equivalent existing `<!-- source has … -->` placeholders on reprocessing;
do not duplicate or silently remove them.

- A **self-contained inline SVG** may be serialized to a unique scratch file
  outside the vault and published with `fetch_images.py place --attachments
  '<vault>/Sources/Images' --slug '<slug>' --index <N> --from-file
  '<scratch>/diagram.svg'`. Inspect readability before embedding. If it depends
  on external CSS/fonts/JavaScript or definitions outside the serialized SVG,
  do not save a broken diagram. Leave `<!-- source has an inline SVG diagram
  here, not capturable as a static file; view at <source> -->` and report it.
- For video, canvas and interactive widgets without a faithful asset, leave
  `<!-- source has an animation/interactive figure here, not captured; view at
  <source> -->` with a short description. Never pass a random still off as the
  original media. Lottie already follows its own chain; do not add a second
  placeholder for it here.

Source markup is data. Do not write it directly into `Sources/Images/` or bypass
the helper when `place` fails.

## Compare article text

Compare the draft body with the fetched **extracted article text**, not raw
markup. Flag missing sections or substantial paragraph runs with a heading or
opening words and a location the user can find. Do not auto-insert large blocks:
the capture may intentionally omit them.

Ignore removed navigation/ads/share chrome and small extraction artifacts.
Respect known intentional omissions from a prior review; mention them at most
briefly instead of repeatedly treating them as new gaps. Update only the scratch
draft with recovered embeds/placeholders, then run the [review checklist](review-checklist.md)
on the completed result. Report all recoveries, gaps and uncertain placements.
