# Exception index

Use the matching reference when a case arises; each procedure has one owner.

| Situation | Read / outcome |
|---|---|
| Missing author/date/title, partial date, fuller byline, decorative title, paywall, failed fetch or differing canonical URL | [Metadata verification](metadata-verification.md#verify-against-the-captured-url). Preserve capture provenance; use the canonical empty author or explicit undated fallback, while a missing title blocks publication because it leaves no stable identity. |
| Legacy metadata in an approved rewrite | [Frontmatter migrations](metadata-verification.md#frontmatter-for-the-polished-note). Preserve unrelated user fields and review state. |
| No usable capture URL, empty or near-empty body | [Selection gates](../SKILL.md#1-select-the-captures-and-check-ownership). Do not publish a supposedly new or empty note. |
| No images in the raw | Skip downloads; still [audit the source](completeness-audit.md), which may contain figures the clipper omitted. |
| Huge body or large image | Do not truncate prose or resize images merely for size. [Image limits/failures](images.md#download-and-publish) govern guarded downloads; oversized responses become reported placeholders. |
| Failed/non-image response or missing download helper | [Image failures](images.md#failures-and-readability). No manual fetch/publish bypass. |
| Mobile/AMP URL variants, two captures in one batch, changed body at the same URL | [Dedup index](duplicates-and-reprocessing.md#manual-dedup-index) and [slug ownership](duplicates-and-reprocessing.md#settle-a-slug-before-writing-images). No silent merging. |
| An existing polished note is the input, its slug changed, or final publication collides | [Reprocessing and guarded replacement](duplicates-and-reprocessing.md). Retain the original until the replacement succeeds. |
| Sparse static page, required browser unavailable, paywall or unusable rendered page | [Audit fetching and verdicts](completeness-audit.md#fetch-and-declare-the-audit-scope). State what could not be checked. |
| Recovered figure lacks a caption or reliable placement anchor | [Recovery rules](completeness-audit.md#recover-missing-images). Use the evidence-based caption chain; report approximate placement. |
| Lottie with/without a poster, missing renderer or failed conversion | [Lottie recovery](lottie-recovery.md). One figure: converted GIF, otherwise a labeled still, otherwise an actionable placeholder. |
| Damaged code, math, captions or section structure | [Body cleaning](body-cleaning.md), then [review](review-checklist.md). Repair only what source evidence supports. |
