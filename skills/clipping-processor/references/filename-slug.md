# Filename and image slug rules

**Read this when** the author or the title doesn't slug cleanly — more than one author, a surname-first or suffixed name, no human author at all, acronyms or brand casing in the title, a missing `published` year — or when `scripts/slug.py` isn't available and you're building the slug by hand.

Use `--topic` as the documented path: choose 2–4 identifying content words; the
helper handles the mechanics. Automatic `--title` output is a suggestion to check: it uses
a filler list and word order, not article meaning. For example, it suggests
`Pancreatic_Cancer_Match` for “Pancreatic cancer just met its match”, while the
selected topic below is `Pancreatic_Cancer`. Check its `topic_auto` and `notes`
fields, then rerun with the intended `--topic` before any image is written.

The polished note's filename is an abbreviation, not the full title — the full title still lives in YAML. Three segments joined by underscores: **`<Author>_<short_topic>_<year>.md`**. Keeping filenames short keeps the file pane scannable and avoids OS path-length issues; the full title in YAML is what shows up in Obsidian's preview and search anyway.

## Author segment

Use the surname of the first author. Resolve it in two stages so commas do not confuse the name with a list:

1. **Pick the first author.** Authors normally arrive as a YAML list (one entry per verified author), so the first author is simply the first list entry. If instead the authors are mashed into a *single string* — multiple names joined by `and`, `&`, `;`, or a comma-separated list like `Buck, Carlsmith, and Greenblatt` — take only the portion before the first such separator as the first author, and ignore the rest.
2. **Take that first author's surname** — the last whitespace-separated token of their name, kept in original case (it's a proper noun).

The comma-flip for surname-first names applies **only within a single author's name**, and only when the comma genuinely marks surname-first order: a name written `Smith, John` / `van der Berg, Jürgen` flips to natural order (`John Smith`) so the last token is the real surname. Two guards so the flip doesn't misfire:
- **Don't flip a multi-author string.** If the comma is separating *different people* (the string has more than one comma, or contains `and`/`&`/`;`), it's an author list, not a surname-first name — resolve the first author per stage 1 instead.
- **Don't flip a trailing suffix.** A post-comma token that's a generational or credential suffix (`Jr.`, `Sr.`, `II`, `III`, `IV`, `PhD`, `MD`, `MSc`, etc.) isn't a given name — `Martin Luther King, Jr.` is not surname-first. Drop the suffix and take the surname from the remaining name (`King`).

- "Ruxandra Teslo" → `Teslo`
- "Jürgen van der Berg" → `Berg` (last token wins)
- "Smith, John" → surname-first, flip to "John Smith" → `Smith`
- "Martin Luther King, Jr." → suffix after comma, not surname-first → `King`
- "Mary Smith-Jones" → `SmithJones` (hyphens dropped, casing kept)
- Two or more authors → just the **first author's** surname, nothing appended: "Teslo and Smith" → `Teslo`; "Buck, Carlsmith, and Greenblatt" → `Buck`. (No `_etal` — the first surname already identifies the work, and the full author list lives in the YAML for search and wiki-builder. An `_etal` marker would only add noise.)
- No clean human author ("Editorial Team", "Anonymous", a publication account, blank) → drop the author segment entirely; slug becomes `<short_topic>_<year>.md`.

## Short topic segment

Use 2–4 content words from the **corrected** title, **Title-Cased** (capitalize the first letter of each word), underscore-separated. Keep the nouns and verbs that actually identify the topic; drop articles, prepositions, possessives, and rhetorical filler (`a`, `the`, `of`, `for`, `just`, `how`, `why`, `is`, `met`, `bullish on`, etc.). **Acronyms and initialisms are fully uppercased** (`LLM`, `RNA`, `AI`, `KRAS`, `GPT`, `AGI`, `OOM`) — and a trailing plural `s` stays lowercase, so `LLMs`, `OOMs`, `GPUs`. A word that mixes an acronym with a number is uppercased as a unit: `gpt4` → `GPT4`. **A word that already carries an internal capital — a brand, product, or camelCase name — keeps its own casing rather than being forced to Title Case:** `iPhone` stays `iPhone` (not `Iphone`), `macOS` stays `macOS`, `PyTorch` stays `PyTorch`, `eLife` stays `eLife`. (The Title-Case topic plus the proper-cased author make the file pane far more scannable than an all-lowercase slug.)

- "Pancreatic cancer just met its match" → `Pancreatic_Cancer`
- "How LLMs work: a deep dive" → `LLMs_Deep_Dive`
- "Why I'm bullish on synbio" → `Synbio_Bullish`
- "A new transformer architecture for genomics" → `Transformer_Genomics`
- "From GPT-4 to AGI: counting the OOMs" → `GPT4_AGI_OOMs` (acronyms/initialisms uppercased; `OOMs` keeps its lowercase plural)
- "From AGI to superintelligence: the intelligence explosion" → `Intelligence_Explosion`
- "How to start Google" → `Start_Google`

## Year segment

Use the 4-digit year from the **corrected** `published` date. If `published` couldn't be verified and isn't in the raw, fall back to the year from `created` (the clipping date). If even that's somehow missing, drop the year segment.

## Combined examples

- Teslo, "Pancreatic cancer just met its match", 2026 → `Teslo_Pancreatic_Cancer_2026.md`
- Anonymous editorial, "How LLMs work: a deep dive", 2025 → `LLMs_Deep_Dive_2025.md`
- Smith & Jones, "Synbio bullish thesis", 2024 → `Smith_Synbio_Bullish_2024.md` (first author only; the co-author is recorded in the YAML, not the filename)

Other punctuation (`:`, `,`, `?`, `'`, `"`, `—`, `–`) is removed, not replaced.

The **image filename slug is the same string as the note filename** (case preserved), with `_fig_<N>.<ext>` appended: `Teslo_Pancreatic_Cancer_2026.md` → `Teslo_Pancreatic_Cancer_2026_fig_<N>.<ext>`. Keeping the casing consistent makes the note ↔ image relationship visually obvious when scanning the Sources/Images folder — and it is also exactly the `[source_stem]_fig_<N>` pattern `wiki-builder` looks up in `Sources/Images/` when the cleaned note is later processed as a source, since the note's filename stem *is* the source stem. Don't diverge from it.

Use the **corrected** author and title from [metadata verification](metadata-verification.md), so the slug reflects the verified metadata — this is why getting source verification right matters for findability, not just for the YAML.
