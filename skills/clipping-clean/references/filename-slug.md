# Filename and image slug rules

**Read this when** the author or the title doesn't slug cleanly — more than one author, a surname-first or suffixed name, no human author at all, acronyms or brand casing in the title, a missing `published` year.

Use `--topic` as the documented path: choose 2–4 identifying content words; the
helper handles the mechanics. Automatic `--title` output is a suggestion to check: it uses
a filler list and word order, not article meaning. For example, it suggests
`Pancreatic_Cancer_Match` for “Pancreatic cancer just met its match”, while the
selected topic below is `Pancreatic_Cancer`. Check its `topic_auto` and `notes`
fields, then rerun with the intended `--topic` before any image is written.

The polished note's filename is an abbreviation, not the full title — the full title still lives in YAML. Three segments joined by underscores: **`<Author>_<short_topic>_<year-or-nd>.md`**, with the author segment dropped when there is no clean human author. Keeping filenames short keeps the file pane scannable and avoids OS path-length issues; the full title in YAML is what shows up in Obsidian's preview and search anyway.

The helper caps the UTF-8 stem at 180 bytes so the longer
`<slug>_fig_<N>.<ext>` attachment names still fit. It spells `+`, `#`, and `*`
inside content words as `Plus`, `Sharp`, and `Star` (for example `C++` becomes
`CPlusPlus`) so distinct technical names do not collapse onto one slug; other
punctuation is dropped. Do not hand-build a longer or differently collapsed
stem after the helper reports its shortening or symbol notes.

## Author segment

Pass each retained author in byline order (repeat `--author`), or none. The
helper takes the first author's surname, flips a surname-first name, drops
suffixes and Vancouver initials, and drops the author segment for an editorial
or anonymous byline. Review every note it prints (for example a
possible-initials token such as `Jun LEE`), and rerun with a corrected
`--author` when its reading is wrong. For example:

- "Ruxandra Teslo" → `Teslo`
- "Jürgen van der Berg" → `Berg` (last token wins)
- "Smith, John" → surname-first, flip to "John Smith" → `Smith`
- "Martin Luther King, Jr." → suffix after comma, not surname-first → `King`
- "Mary Smith-Jones" → `SmithJones` (hyphens dropped, casing kept)
- "Smith J" / "Smith JK" → surname + initials → `Smith`
- Two or more authors → just the **first author's** surname, nothing appended: "Teslo and Smith" → `Teslo`; "Buck, Carlsmith, and Greenblatt" → `Buck`. (No `_etal` — the first surname already identifies the work, and the full author list lives in the YAML for search and wiki-build. An `_etal` marker would only add noise.)
- No clean human author ("Editorial Team", "Anonymous", a publication account, blank) → drop the author segment entirely; slug becomes `<short_topic>_<year-or-nd>.md`.

## Short topic segment

Use 2–4 content words from the **corrected** title, **Title-Cased** (capitalize the first letter of each word), underscore-separated. Keep the nouns and verbs that actually identify the topic; drop articles, prepositions, possessives, modal verbs, `not`, and rhetorical filler (`a`, `the`, `of`, `for`, `just`, `how`, `why`, `is`, `may`, `not`, `met`, etc.). **Acronyms and initialisms are fully uppercased** (`LLM`, `RNA`, `AI`, `KRAS`, `GPT`, `AGI`, `OOM`) — and a trailing plural `s` stays lowercase, so `LLMs`, `OOMs`, `GPUs`. A word that mixes a known acronym with a number is uppercased as a unit: `gpt4` → `GPT4`; ordinary numeric terms keep their spelling (`web3` → `Web3`, `10x` → `10x`, `1st` → `1st`). **A word that already carries an internal capital — a brand, product, or camelCase name — keeps its own casing rather than being forced to Title Case:** `iPhone` stays `iPhone` (not `Iphone`), `macOS` stays `macOS`, `PyTorch` stays `PyTorch`, `eLife` stays `eLife`. (The Title-Case topic plus the proper-cased author make the file pane far more scannable than an all-lowercase slug.)

- "Pancreatic cancer just met its match" → `Pancreatic_Cancer`
- "How LLMs work: a deep dive" → `LLMs_Deep_Dive`
- "Why I'm bullish on synbio" → `Synbio_Bullish`
- "A new transformer architecture for genomics" → `Transformer_Genomics`
- "From GPT-4 to AGI: counting the OOMs" → `GPT4_AGI_OOMs` (acronyms/initialisms uppercased; `OOMs` keeps its lowercase plural)
- "From AGI to superintelligence: the intelligence explosion" → `Intelligence_Explosion`
- "How to start Google" → `Start_Google`

## Year segment

Use the 4-digit year from the **corrected** `published` date. A retained raw
publication date may supply it when the live page is unavailable and the value
is reported as unverified. If neither the raw nor usable page evidence supplies
a publication year, pass `--undated`: the segment is `nd` and frontmatter is
`published: null`. Never substitute the clipping's `created` year.

## Combined examples

- Teslo, "Pancreatic cancer just met its match", 2026 → `Teslo_Pancreatic_Cancer_2026.md`
- Anonymous editorial, "How LLMs work: a deep dive", 2025 → `LLMs_Deep_Dive_2025.md`
- Smith & Jones, "Synbio bullish thesis", 2024 → `Smith_Synbio_Bullish_2024.md` (first author only; the co-author is recorded in the YAML, not the filename)
- No author, "Evergreen guide to causal diagrams", undated → `Causal_Diagrams_nd.md`

Other punctuation (`:`, `,`, `?`, `'`, `"`, `—`, `–`) is removed, not replaced.

The **image filename slug is the same string as the note filename** (case
preserved), with `_fig_<N>.<ext>` appended: `Teslo_Pancreatic_Cancer_2026.md`
→ `Teslo_Pancreatic_Cancer_2026_fig_<N>.<ext>`. Keeping the casing consistent
makes the note ↔ image relationship visually obvious when scanning the
Sources/Images folder. Since the note's filename stem *is* the source stem,
`wiki-build` finds these images by the shared
[consumer rule](../../../shared/CONVENTIONS.md#8a-the-consumer-rule-the-one-that-matters),
`[source_stem]_fig*` with any extension, when the cleaned note is later
processed as a source. Don't diverge from it. A reprocess keeps the existing
spelling of the note and its images when the new slug differs only by
[case or Unicode normalization](duplicates-and-reprocessing.md#settle-a-slug-before-writing-images).

Use the author and title retained by [metadata verification](metadata-verification.md):
corrected live evidence when available, otherwise supported capture values
reported as unverified. The slug and frontmatter must identify the same source.
