# Nested-list repair

- [Recognize the damage](#recognize-the-damage)
- [Detect candidates](#detect-candidates)
- [Repair, then verify](#repair-then-verify)

Read when [body cleaning](body-cleaning.md#repair-structure-and-markup), sweep
items 8, 12 or 12b of the [review checklist](review-checklist.md#run-the-mechanical-sweep),
or your own reading flags a mangled nested list. Every detector here finds
candidates only: confirm clipping damage against the source before repairing,
and leave genuine nesting alone.

## Recognize the damage

Web Clipper routinely wrecks nested lists, worst of all on sites (Gwern especially) that use deep nesting for Q&A pairs and dialogue transcripts. Two signatures, usually together:

- *Stacked markers on one line:* `- - text`, `- - - text`, `1. 1. text`, `* * text` — collapse the leading run of markers down to a single marker.
- *Indentation deeper than the actual structure:* items or continuation lines indented more than the real nesting warrants, with no item at the intervening levels — so a sub-item or paragraph dangles under a parent that isn't really its parent. Obsidian counts one tab / four spaces as one nesting level, so this renders as broken or absurdly over-nested. **Two depths of this, and the shallow one is the easy one to miss:**
  - *Two-to-four tabs of orphaned depth* — an item or continuation at depth 2–4 under a parent at depth 0, with nothing at the levels between. Obviously broken (absurdly over-nested), and caught by the deep-indent check.
  - *A single tab that splits siblings* — subtler and the one that slips through. In a list (often a Q&A or dialogue) where the **first** item is flush (`- …` or `> - …`, depth 0) but its **sibling** items are indented one tab (`\t- …` or `> \t- …`, depth 1), the siblings render as a *nested sub-list under the first item* even though they're peers. The real Gwern damage is exactly this: `> - **Q:**` flush, then `> \t- **A:**` one tab — Q and A are turns in one exchange, not a question with a nested answer. Because it's only one tab and carries no stacked marker, **neither the stacked-marker check nor the two-step deep-indent check catches it** — it needs the sibling-consistency check. (A continuation paragraph of such an item carries the same stray one-tab indent and a lost bullet, stranding the wrapped prose.)

**Renormalize to the real logical structure:** one indent step (a single tab, or 4 spaces) per genuine level of nesting, one marker per item, and any continuation paragraph of an item indented to that item's text column (restore its bullet if it was meant to be a sub-item, or leave it as an indented plain paragraph if it's prose belonging to the item). When the "list" is really a dialogue or a Q&A that nesting only obscures, prefer the simplest faithful shape over reproducing the source's broken depth.

- *Q&A example* — `- - **Q:** …` / `⟶⟶- **A:** …` (two leading markers, answer at 2 tabs) becomes a top-level `- **Q:** …` with the answer one level under it (`⟶- **A:** …`), and any explanatory paragraphs between Q and A sit at that same one-tab depth.
- *Dialogue example* — `> - - - **Speaker A:** …` / `⟶⟶⟶⟶- **Speaker B:** …` (triple marker, four-tab depth, inside a blockquote) becomes a flat one-level list of speaker turns: `> - **Speaker A:** …` / `> - **Speaker B:** …`, with a speaker's trailing continuation sentence kept on/under their own turn rather than stranded at a random depth.

## Detect candidates

**Don't rely on eyeballing this — it's a fiddly whitespace transform that's easy to skim past.** Detect mechanically, repair, then verify mechanically, checking each match against the source before repairing. The sweep lists stacked markers (item 8, including damage inside a blockquote), lines indented two steps or deeper (item 12: two tabs, eight spaces, or a tab and four spaces, after any `>` prefix) and the single-tab sibling split (item 12b); `siblings` runs item 12b alone:

```bash
python3 '<skill>/scripts/body_checks.py' sweep '<draft>'
python3 '<skill>/scripts/body_checks.py' siblings '<draft>'
```

- **Stacked markers are candidates.** Preserve genuine nested lists and repair only confirmed clipping damage.
- **Deep indentation is only a *candidate*.** A *legitimately* nested list also indents its sub-sub-items two tabs. A deep-tab line is damage only when the indent is **orphaned**: there's no shallower list item directly above it establishing that level (a continuation paragraph or item dangling at depth 2–4 under a parent at depth 0), or it sits in a block that also has stacked markers. A 2-tab line correctly nested under a 1-tab parent item is real structure — **leave it alone.** So this check is a list of places to *inspect*, not a list to blindly flatten. Matches indented wholly or partly with spaces are candidates on the same terms, but item 12b and the `repair` ops read and change tabs only: fix a confirmed space-indented block by a reviewed edit of the scratch draft, converting each four-space step to one tab, before or instead of `overindent` or `dedent`.
- **Inconsistent sibling indent is also only a *candidate*.** It flags a **later** item one tab deeper (depth 1) than an **earlier flush** item (depth 0) in the same block; blank lines, quoted or not, do not end the block, and a stray indented item above the flush one does not hide the split. **It cannot tell the bug from real nesting, because they're structurally identical** (a shallow item followed by deeper siblings is *either* a parent with children *or* peers one of which got mis-indented). Judge each flagged block by meaning, ideally against the source: if the flush item is genuinely the **parent** of the indented ones (e.g. a bullet followed by its own sub-points), it's correct — leave it. If the items are **peers** (turns in a dialogue, entries in one list) and the flush one just happens to sit shallower, it's the bug — pull the indented siblings back to the flush item's depth so all peers align.

## Repair, then verify

Three transforms, each **region-scoped**: pass only the lines of a block you have confirmed as damaged, never every matching line in the file, or you'll flatten a genuine nested list. Each keeps a blockquote prefix, never changes YAML or fenced code, and rewrites only the scratch draft (a path inside a vault is refused). Review a `--dry-run` first, then run the same command without it:

```bash
python3 '<skill>/scripts/body_checks.py' repair --op stacked --lines '<first>-<last>' --dry-run '<draft>'
```

- `stacked` collapses a leading run of list markers to its last marker. Use it only on confirmed clipping damage outside code.
- `overindent` collapses two or more leading tabs to one, inside a confirmed-damaged block (one containing stacked markers, or orphaned deep indent with no shallower parent). A de-bulleted continuation line keeps the one-tab indent but no marker.
- `dedent` strips exactly one leading tab: in a **confirmed-peer** block (e.g. a dialogue), it pulls each one-tab-indented sibling, and its one-tab continuation lines, back to the flush item's depth.

These transforms fix all three real Gwern shapes. `stacked` + `overindent` handle the older stacked-marker / 2+-tab damage (e.g. `- - **Q:**` / `⟶⟶- **A:**` → `- **Q:**` / `⟶- **A:**`, or the blockquoted `> - - - **Speaker:**` / `> ⟶⟶⟶⟶- **Speaker:**` → `> - **Speaker:**` / `> ⟶- **Speaker:**`). `dedent` handles the subtler single-tab split — the on-disk `> - **Q:**` (flush) / `> ⟶- **A:**` (one tab) and the `> - **Lukas Biewald:**` / `> ⟶- **Wojciech Zaremba**:` / `> ⟶<continuation>` / `> ⟶- **L Biewald**:` dialogue — by pulling the indented peer turns and their continuation lines back to the first speaker's flush depth, so all turns sit level. For a genuinely 3-level list (rare in clips), none of the flat transforms is right — map each real level to one indent step instead, and check the result reads as the source intended. **After repairing, re-run the sweep: confirm remaining matches in items 8, 12 and 12b are legitimate Markdown or code, not leftover clipping damage.**
