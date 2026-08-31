# Edge cases

**Read this when** any one of the following holds. Each is a fact you have before you act on it — a missing key, a status code, a downloaded file's type, a script's verdict — not a sense that the run has gone sideways:

- **Metadata** — the raw is missing `author`, `published` or `created`; the fetched byline is a fuller form of the raw's; the fetched date carries a time or timezone, or is year- or month-only; the raw has several authors; the fetch returned a paywall stub, a 404, or a canonical URL that differs from the raw's.
- **Body and images** — the raw has no images at all; its body is empty or near-empty; an image URL downloaded to something that isn't an image; an image is over the script's 25 MB cap or the body over 50k words.
- **Duplicates and reprocessing** — one article arrived as two URL variants (`m.`, `/amp`); two raws in one batch are captures of the same article; a `source:` matches but the bodies differ sharply; the input is a file already in `Articles/`; the same raw is being processed a second time; the recomputed slug collides with a different existing note.
- **Completeness audit (step 12)** — the page can't be reached or is paywalled; a `curl` returns a JS-rendered skeleton; a recovered figure has no caption or text anchor to place it at; a Lottie failed to convert, or shipped alongside a static poster.

Scan the bolded case names for the match rather than reading it end to end.

Several of these are quick pointers: where a rule is fully spelled out in a workflow step, the entry just names the case and points there, so the rule lives in exactly one place and can't drift.

**Metadata**

- **Raw YAML missing fields.** Recover missing `author` or `published` from step 2's source fetch. Preserve an existing `created`; if it is absent, use today's processing date and report that fallback. A website's creation date is not the user's clipping date, so never take `created` from the fetched page.
- **Fetched author is a fuller form of the raw's** (raw "John Smith", JSON-LD "John A. Smith"). Prefer the fetched form — it's the article's own canonical byline — and note the change in the report.
- **JSON-LD date carries a time/timezone** (`2026-05-12T14:30:00Z`). Drop the time, keep the date. If the timezone would shift the day, prefer the date as it appears in the URL or visible page text; failing that, use the UTC date.
- **Multiple authors.** Block-form list, one `- Name` per line, in the source page's byline order (raw order as fallback) — the page's ordering is authoritative.
- **Paywall stub / dead 404 / differing canonical URL.** All handled in step 2: fall back to raw YAML, never overwrite `source`, and note it in the report (the affected fields go down as unverified).
- **Partial published date** (`2024`, `2024-03`) — filled to the 1st of the year/month per step 2 (`2024` → `2024-01-01`); the slug uses only the year, so nothing meaningful is lost. A web page nearly always states a full date somewhere, so a partial one here means the fetch found a coarse one, not that the article has no date. Notes about a local document now pad the same way, so `CONVENTIONS.md` §2b states one rule for both note kinds rather than two — a `published` value in `Articles/` is a full `YYYY-MM-DD` whichever skill wrote it.

**Body and images**

- **The raw file has no images.** Skip step 6's download loop; body cleanup, summary, and YAML still apply — and the step-12 audit still runs, since a clip with no images is exactly where the source may have had figures the clipper dropped.
- **The body is empty or near-empty** (Web Clipper grabbed nothing). Report it and ask whether to proceed or re-clip — don't write a near-empty polished file.
- **Very large image** — still download, don't resize; `fetch_images.py` caps a single file and reports anything over as a download failure, so an ordinary large figure needs no decision and an outsized one is already handled as a failure (`references/images.md` states the cap). **Huge body** (>50k words) — fine, don't truncate; Obsidian handles big notes.
- **An image URL resolves to a non-image** (HTML, failed redirect). Download failure per step 6 — placeholder comment, keep going.

**Duplicates and reprocessing**

- **Same article, two URL variants** (mobile vs desktop, AMP vs canonical). Step 1's normalization doesn't rewrite hosts or paths, so `m.` and `/amp` variants won't match by URL. Step 3's slug check is the net that catches them — same author, topic, and year produce the same slug — and it reports the pair rather than merging silently.
- **Two raws in one batch that are captures of the same article.** Neither exists in `Articles/` when the run starts, so the start-of-run index can't contain either. This is why step 1's index is kept live: the first raw is processed and its note added to the index, so the second matches and is skipped.
- **Same `source:` URL but very different bodies** (the article was rewritten after the first clip). Step 1's dedup still fires and the raw is skipped — the user keeps the version they curated. To take the update, they reprocess via explicit-single-file mode and choose "reprocess and overwrite."
- **Reprocessing a file already in `Articles/`.** The full behavior lives in steps 1, 6, 10 and 11: it's excluded from its own dedup scan; the old Summary callout and `___` separator are stripped; summary/`description`/`tags` are regenerated (so manual edits to those are lost) while `read:` is carried across as found and a legacy `roots:`/`wiki:` is stripped; embeds are planned for rename rather than re-downloaded; and, if the recomputed slug changed, the finished draft and image plan are finalized together under `references/duplicates-and-reprocessing.md` Guard 3, retaining the original note until publication succeeds. Batch mode never picks it up — it scans `Inbox/` only.
- **The same raw processed on two consecutive runs.** Shouldn't happen — that's the whole point of the dedup index — but if it does, the guards at steps 3 and 11 stop the write before the existing note is overwritten. A duplicate that reaches step 11 is reported, not resolved silently.
- **Slug collision with a different existing cleaned file.** Append `_2`, `_3`, … at step 3, before any image is written, and flag it in the report. A collision discovered at step 11 returns to step 3.

**Completeness audit (step 12)**

- **Audit can't reach the page** (fetch failed / 404 / paywalled). Skip it with the explicit `SKIPPED — <reason>` verdict — there's nothing trustworthy to compare against — and say so. The note is still produced from the clip.
- **JS-rendered page** (a `curl` returns a near-empty skeleton). Sub-part 1's static-first / browser-on-sparse logic handles it; only when *even* the available browser returns nothing does the audit emit `SKIPPED — JS-rendered page returned no usable content`.
- **A missed figure that can't be placed** (no caption/alt anchor, no clear text match). Don't guess a precise spot — append after the most-related paragraph and flag the placement as approximate (sub-part 3).
- **A Lottie whose conversion fails** (Chromium unavailable, timeout, blank output). The script writes nothing on failure; fall back per sub-part 3b's chain — the static poster if the figure has one (captioned as a still), otherwise a placeholder that records the lottie source URL. Never silently pass the poster off as the animation; an honestly-captioned still is fine.
- **A Lottie with a static image fallback** (a `<lottie-player>` + sibling `.svg`/`.webp`). One figure: convert the Lottie and suppress the poster when conversion succeeds; if conversion can't run, emit the poster (captioned as a still) and suppress the absent GIF. Never both (sub-parts 1 and 3b).
