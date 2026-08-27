# Metadata verification against the source (step 2)

**Read this when** you are about to trust or correct a clipping's `title`, `author` or `published` — that is, whenever the fetched page and the raw YAML disagree, the fetch fails or hits a paywall, the title carries decorative Unicode or a bolted-on annotation, or the published date is partial (year- or month-only). Skip it only when the raw values are obviously right and the fetch confirmed them.

**Web Clipper metadata is often wrong** — the title may include the site suffix, the author may be the publication account rather than the actual writer, and the `published` date is frequently off by months or years (sometimes from a meta tag that points at the site's launch date, the page's last-modified date, or a different author's earlier post). Treat raw YAML as a hint, not as truth.

Fetch the source URL with `web_fetch` and extract:

- **Title** — prefer `og:title`, then JSON-LD `headline`, then `<title>` stripped of the trailing site suffix (drop ` — Site Name`, ` | Site Name`, ` - Site Name` from the right). The on-page `<h1>` is a good cross-check. Two normalizations to apply once you have the title text:
  - **Fold decorative Unicode letterforms back to plain ASCII.** Some sites (Gwern is the canonical case) typeset titles in Unicode *font-variant* codepoints — the Mathematical Alphanumeric Symbols block (mathematical italic/bold/script/sans/monospace, e.g. `𝐷𝑒𝑎𝑡𝘩 𝑁𝑜𝑡𝑒` = "Death Note", `𝐓𝐡𝐞 𝐒𝐜𝐚𝐥𝐢𝐧𝐠 𝐇𝐲𝐩𝐨𝐭𝐡𝐞𝐬𝐢𝐬` = "The Scaling Hypothesis"), fullwidth Latin (`Ｄｅａｔｈ`), and Unicode small-caps. These are styling, not meaning; they look fine in a browser but break Obsidian search, sort order, and the filename slug, and clash with the plain-ASCII way the body refers to the same words. Map each such styled codepoint to its plain Latin equivalent. **Only fold codepoints that are font-styled variants of A–Z/a–z/0–9.** Leave genuinely meaningful non-ASCII intact: accents and diacritics in names (`Ruxandra`, `Müller`), em/en-dashes, and symbols that carry meaning rather than font styling — a Greek letter used as a variable (`λ-calculus`, `α-helix`), `C++`, `∂`, etc. If in doubt whether a character is decorative styling or meaningful, keep it.
  - **Don't append anything the source didn't put in the title.** Use the title as the page titles itself. Resist the temptation to bolt on the author or interview subject's name, the series number, or a clarifying parenthetical — e.g. an interview titled "The printing press for biological data" should not become "The printing press for biological data (Sterling Hooten)". The author lives in the `author` field; the title field is just the title.
- **Author** — prefer JSON-LD `author.name` (top-level Article schema), then `<meta name="author">`, then `<meta property="article:author">`, then the visible byline. If multiple authors, capture all in source order.
- **Published date** — prefer JSON-LD `datePublished`, then `<meta property="article:published_time">`, then a visible `<time datetime="...">` in the article header. Normalize to `YYYY-MM-DD` (drop the time component if present). **Partial dates:** if only a year is available (e.g., `2024`, or a `<time datetime="2024">` with no month or day, or a visible "2024" byline date), fill in **January 1st** of that year — so `2024` → `2024-01-01`. Same rule if year + month only (e.g., `2024-03` → `2024-03-01`): fill in the first of the month. The year segment of the filename slug (step 3) only cares about the year, so this default doesn't distort findability — it just keeps the date field a valid `YYYY-MM-DD` string for downstream tools.

**Correction rules — when raw and fetched disagree:**

| Field | Rule |
|---|---|
| `title` | Replace raw with fetched if fetched is materially different and cleaner (site suffix removed, "Untitled" replaced with real title, encoding mojibake fixed). Apply the two normalizations above (decorative-Unicode folding, no appended annotations) to whichever value you keep — a raw title can carry the same styled-Unicode or bolted-on parenthetical, so normalize it even when you don't otherwise replace it. Don't replace for cosmetic case differences. |
| `author` | Replace raw with fetched if fetched is more specific (raw is the publication name, "Editor", "Admin", "Newsletter Team" → fetched is a person's name). Replace if the names are simply different — Web Clipper occasionally grabs the wrong author. |
| `published` | Replace raw with fetched whenever fetched is a valid date and they disagree. The raw date is almost always less reliable. |
| `source` | **Never overwrite.** The raw URL is by definition correct for the file we're processing (it's the URL the user clipped from). If the fetched page has a canonical URL that differs from the raw `source`, note it in the report but don't change the field. |
| `created` | **Never overwrite.** This is the clipping date set by Web Clipper, not an article-publication date — irrelevant to source verification. |

**Paywall / login-wall detection.** If the fetched page is much shorter than expected (under ~500 words of body text) and contains phrases like "subscribe to continue", "this article is for paid subscribers", "create a free account", "sign in to read", treat the fetch as failed-due-to-paywall. Don't extract metadata from a paywall stub. Fall back to the raw YAML and note the paywall in the report.

**Fetch failures (timeout, 404, network error, paywall).** Fall back to raw YAML for all fields. Note in the report that source verification failed and which raw values were therefore unverified.

**The fetch here is for metadata only — it never becomes the body** (see Conventions). The same page is reused later, in the step-12 completeness audit, to check whether the clip missed any images or text, so the fetched content matters for *verifying* the clip — just not for *replacing* its body.

Always include a clear note in the final report when any field was corrected, showing old → new, so the user can spot-check.
