# The scanner — CLI, output contract, and what it does not check

Read this when a scan exits non-zero, a JSON field/finding is unfamiliar, or an `item16`/`item18` result needs interpretation. Those checks have intentional allowances described under [Before you call a finding a false positive](#before-you-call-a-finding-a-false-positive). Run the helper at [Step 0](../SKILL.md#step-0--inventory-the-vault); use [QC actions](qc-items.md#finding-actions) to decide what may be changed.

Contents: [CLI](#cli) · [Output contract](#output-contract) · [Item keys](#item-keys-in-problems) · [Coverage limits](#deterministic-scanner-and-autonomous-semantic-pass).

The scanner is `scripts/scan_vault.py`, a read-only stdlib Python helper. Its JSON describes detections, not permission to edit the vault.

## CLI

```
python3 scripts/scan_vault.py WIKI [--images DIR] [--out FILE] [--indent N]
```

- `WIKI` — the vault's **`Wiki/` folder**, not the vault root. The scanner walks entries only inside this folder. For its limited MOC diagnostics, it derives the vault root from a supplied `Sources/Images` path, otherwise from the nearest `.obsidian` ancestor, otherwise from `WIKI`'s parent. Suggestion logs and unrelated root notes are never linted or listed inside a MOC.
- `--images DIR` — the vault's flat **`Sources/Images/`** folder. With it, every supported local image embed in every entry is checked to name a file that is really there, emitted as `item12/missing-image`. **Pass it on every real run.** `CONVENTIONS.md` §1 makes this skill that folder's embed validator and nothing else in the plugin walks `Wiki/`, so without the argument that check silently does not run at all and an entry embedding a figure that is not on disk — the state §1a's rename hazard leaves behind — scans clean. It also emits report-only `image_folder_findings` for nested files/directories, recognizable temporary/staging artifacts, an unreadable folder/subtree, and `portable-name-collision` groups. Each collision finding preserves every resolving path under `paths`; it does not collapse `Figure.png` and `figure.PNG` into an unactionable set member. Image identity is matched on the **basename**, case- and normalization-folded on every host. This conservative identity prevents filesystem-dependent missing results; a collision still counts as present for missing-image checks and receives its separate folder finding, so the report never says the same image is both present and missing. Producers still write and references should use the exact on-disk spelling. A path-qualified `![[Sources/Images/X.png]]`, a unique case/normalization variant, and a legacy nested file therefore are not reported as missing even while the nested path is reported. Embeds shown inside fenced, indented, or inline code are skipped: listing syntax is not a rendered embed. If any image subtree is unreadable, the inventory is incomplete and all missing-image checks are suppressed for that scan; the folder finding reports the gap instead of treating unreadable files as absent. Folder and collision findings never authorize moving, renaming, or deleting a file.
- `--out FILE` — write the JSON to `FILE` instead of stdout. Use this on any real vault and read the file in slices (filter by `item`, by slug, by key) rather than pulling the whole object into context.
- `--indent N` — JSON indent, default `2`; `--indent 0` emits one compact line.
- Exit status `2` with a usage error if `WIKI` is not a directory, or if `--images` is given and is not a directory. The second guard is deliberate: a mistyped image folder that read as "empty" would report **every** embed in the vault as naming a missing file, and nothing in the output would distinguish that from a genuinely broken vault. Exit status `1` with an explicit error if a Wiki directory cannot be walked or its identity cannot be established: no worklists are produced and a requested output file is left untouched. That incomplete inventory cannot establish missing names, aliases, or complete MOC coverage. Individual unreadable leaf files instead remain known occupants and receive `item0`. Other failures are genuine crashes worth recording as execution friction in the [run report](backlogs.md#run-report). Any nonzero exit, missing helper, malformed JSON, or incomplete output blocks every dependent write; never reuse an earlier report as the failed scan's result.

The body and section readers ignore hidden HTML/Obsidian comments and escaped wikilink examples while retaining source line positions. A commented template heading is not an extra Flashcards section, and a commented link neither triggers pruning nor suppresses a later visible backfill candidate. Delimiters inside code stay literal. This read-only body view does not alter the separate flashcard parser or its protected scheduling attachments.

An unreadable leaf or unsupported/ambiguous alias metadata can hide an alias owner even when every filename is known. The affected path's existing QC message says **“Alias inventory is incomplete”**. Local QC and direct-filename checks continue, but the scan suppresses dangling-link findings, alias-dependent canonicalization and duplicate/self-link removal, alias-addition candidates, and all backfill candidates. Bare parent targets requiring alias resolution remain `unparsed`. Preserve these unresolved links; safely correct the metadata/readability under its normal scope, then rescan to restore ordinary work. A readable note with definitively no frontmatter, or unrelated field-value QC with fully parsed aliases, does not create this uncertainty.

The scanner **never writes to the vault.** It reads Markdown files recursively inside `Wiki/` and prints; the executing agent applies every authorized fix, MOC, `parents:` value, and log append in the same autonomous run.

## Output contract

One JSON object with these keys.

| key | type | contents |
| --- | --- | --- |
| `run_timestamp` | string | `YYYY-MM-DD HH:MM` at scan time. Use the initial value for suggestion-item `Seen` timestamps unless a coordinating run supplied its own; rescans and invoked skills do not count as additional runs. |
| `wiki_path` | string | absolute path actually scanned (confirms an overridden path took effect) |
| `vault_root` | string | inferred vault root used only for report-only canonical `MOCs/` and legacy root-MOC file and parent-resolution diagnostics: derived from a supplied `Sources/Images` path, otherwise the nearest `.obsidian` ancestor, otherwise the parent of `wiki_path` |
| `inventory` | object | `entries` is the count and `slugs` is the sorted list of entry filenames without `.md`. The resolution model contributes at most one parsed owner for a portable basename collision; every parseable physical file still receives local QC. |
| `discipline_tags` | object | Observed discipline-enum slug → integer entry count, including `misc`. Counts include recognized values in an invalid mixed list alongside its `item8` finding; they do not establish valid misc membership. Specific disciplines with no members get no new MOC and existing files are preserved/reported; misc keeps its separate empty-list refresh rule. |
| `off_enum_tags` | object | malformed / off-enum tag slug → the entries carrying it. Every one of these is an item-8 finding too; this key groups them by bad slug so a vault-wide pattern is visible at a glance. |
| `untagged_entries` | array | Repair worklist of entries with a provably blank `tags:` key or empty list. These receive `item8` and have no implied misc membership. Inspect the note and assign specific tags or `"#misc"` alone before placement. Missing, scalar/null, duplicate-key, malformed, or structurally unparseable frontmatter cannot establish a genuine blank and remains separately reported; unrelated field-value QC does not itself block this worklist. |
| `problems` | array | `{"slug", "item", "message"}`, sorted. When several physical files share one portable basename, file-specific findings add the Wiki-relative `"path"` (including `.md`) so each body can be repaired without choosing by walk order; ordinary rows retain the historical three fields. The deterministic violations. See *Item keys* below. |
| `problem_tally` | array | per item: `{"item", "entries", "pct_of_entries", "issues"}`, ranked by entries affected. `pct_of_entries` is the share of entries touched — the recurrence evidence a wiki-build proposal cites. |
| `collision_candidates` | array | `{"a", "b", "probe", "detail"}` — two slugs the item-5 probes matched. `probe` ∈ `exact`, `plural`, `hyphenation`, `word-order`, `word-order-singular`, `µ-variant`, `stem-morphology`; `detail` is the two colliding identifiers. `word-order-singular` sorts the tokens *after* singularising each one, which is what catches `weight-tying` against `tying-weights` — a pair a raw token sort misses on `weights` ≠ `weight`. It has to be here because wiki-build runs the same two-key probe on every candidate (`wiki-build/SKILL.md`, step 3 probe (e)) and CONVENTIONS §9 makes whole-vault dedup detection this skill's alone: a pair already sitting in the vault is seen by nothing else. `stem-morphology` is create-time probe (f), using the shared light-stem key, and is emitted only when an earlier, more specific probe has not already covered the pair. Unordered pairs are de-duplicated per probe. **Review only — never merged.** wiki-build's create-time probe (g), token-superset, is deliberately **not** mirrored in this vault-wide sweep — qualified-vs-base pairs (`feature-machine-learning` beside `machine-learning`) are exactly what the disambiguation rules produce on purpose, so a whole-vault pass would flood on legitimate pairs; its absence from this probe list is by design (`wiki-build/SKILL.md`, step 3). |
| `rename_candidates` | array | `{"slug", "new_slug", "inbound_links", "target_exists"}` — entries whose filename ≠ `slug(title)`. `inbound_links` is how many actual prose/Related wikilinks a rename would have to rewrite. It uses the same path-aware resolver as item 10, so path-qualified, anchored, case/normalization-variant, and explicit-`.md` spellings count against the file they open; a bare target with several same-basename owners is conservatively omitted instead of assigned by walk order. `target_exists: true` means the destination is already taken — either an existing file **(whether or not it parsed as an entry: a file with no frontmatter is absent from `inventory` and still occupies its name, and the approved `mv` would destroy it)**, **or a second candidate in this same list proposing the same `new_slug`** — so this is a likely duplicate/disambiguation and must **not** be renamed into (applying both of a colliding pair in sequence would have the second silently overwrite the first). `new_slug` is never empty: a title that reduces to the empty slug (CJK, all-symbol) is reported as an `item5` problem instead, because renaming to it would produce a file literally called `.md`. **Propose for approval — never auto-applied.** |
| `backfill_candidates` | array | `{"slug", "target", "surface", "bare_noun_alias", "organism_common_name"}` — a bare-text mention of `target`'s title/alias (or its plural), or an explicitly bound Organism common-name surface, found in `slug`'s prose. `target` is the supplied safe entry destination: an ordinary unambiguous slug, or the full extensionless vault-relative path when qualification is required, such as `Wiki/misc` or `Wiki/statistics`. Preserve that target in body and Related links. Existing links, embeds, ambiguous title/alias surfaces, duplicate Wiki-basename destinations, targets already linked in that entry, and designated common-noun surfaces/destinations are excluded. `organism_common_name: true` means the target's description or opening sentence directly equates its canonical Organism title with that complete surface (or its natural inflection); a bound `fruit fly` never donates the broader head `fly`. It is a locally valid display label, never an instruction to add a global alias, and still needs the ordinary identity/closeness judgment. Other single lowercase aliases of qualified destinations remain candidates and carry `bare_noun_alias: true`; batch-review them under the closeness bar rather than treating the flag as an automatic decision. Unwritable presentation surfaces are masked so they cannot hide a later eligible occurrence: whole-line italic captions, parsed Markdown-table rows, ATX and Setext headings, fenced/indented/inline code, Markdown link-reference definitions, inline Markdown image syntax including alt text, inline/full/collapsed/shortcut Markdown-link labels resolved by those definitions, bare URLs/autolinks, and Obsidian links/embeds. The plural form inflects the title's head token, so irregular forms such as `Confusion matrices` and `Hypotheses` are matched. |
| `image_folder_findings` | array | `{"path", "kind", "message"}` for a nested directory/file, recognizable temporary/staging artifact, unreadable path, or portable basename collision under the supplied `--images` directory. The `kind` is `nested-directory`, `nested-file`, `temporary-artifact`, `unreadable`, `unusable-file`, or `portable-name-collision`; a collision also carries `paths` with every case/NFC-equivalent owner. The flat-folder and publish-only-finished-files rules come from `CONVENTIONS.md` §8. These are folder-level, report-only observations kept outside `problems`, so they do not inflate entry tallies or authorize moving/renaming/deleting user files. A colliding name remains present for embed-existence checks. An `unreadable` finding suppresses all `item12/missing-image` results for that run because a partial inventory cannot establish absence. The two PDF sidecars and `.DS_Store` are omitted. Empty when `--images` is not supplied or the folder conforms. |
| `hierarchy_diagnostic` | object | Report-only state of entry parents and canonical/legacy MOCs, detailed below. Findings are evidence for an authorized Task 3 closure, never write or migration authorization. |

### Hierarchy diagnostics

Misc membership, coverage, and its sole-parent rule require one structurally
valid tag list containing only `"#misc"` and one tags key. Blank, scalar,
malformed, duplicate, or mixed tags do not qualify. Mixed lists still produce
specific-discipline coverage diagnostics alongside `item8`. Other field-value
QC findings do not exclude an otherwise valid misc tag.

- `entries` counts entries in the scan. `placement_gaps` records
  missing discipline or misc coverage; `placed_unparented` is its compatibility slug
  projection. `unresolved_parents` records `missing`, `ambiguous`,
  `unparsed`, `unreadable`, `legacy-moc`, or `noncanonical-moc` targets.
  `noncanonical-moc` identifies a real `MOCs/<unknown>.md` file outside the
  discipline enum that cannot serve as a recognized MOC root. A legacy root note
  cannot satisfy a canonical `[[MOCs/<discipline>]]` parent. `parent_state_findings`
  uses `misc-parent-mismatch` for an entry validly tagged only `#misc` with populated parents
  other than exactly `MOCs/misc`; empty parents produce a misc placement gap.
- `moc_file_states` inventories each active discipline plus known existing
  MOCs, including existing zero-member discipline MOCs and misc when present
  or needed. Each record includes
  `discipline` (the discipline slug or `misc`), `path`, `target`
  (`MOCs/<group>`), `entries`, and
  `state`: `missing`, `empty`, `readable`, or `unreadable`. Unreadable records
  carry `error`; unsafe directory or leaf ownership must not be mistaken for
  a missing file ready for creation. The state describes the file, not an
  owned region; recognized discipline and misc MOCs are generated as whole notes.
- `legacy_moc_states` inventories recognized preexisting specific-discipline root
  `<discipline>-moc.md` files, never `misc-moc.md`, with the same file-state information plus `canonical_path`. Compare it
  with canonical states before creating a file: both existing paths mean
  duplicate ownership, even when their content matches.
- `moc_inventory_findings` contains records with `kind`, `path`, and `message`,
  plus the relevant `discipline`, `paths`, or `canonical_path`. Kinds include
  `unsafe-directory`, `ambiguous-directory`, `noncanonical-directory`,
  `ambiguous-moc`, `noncanonical-moc`, `unexpected-moc`, `legacy-location`,
  and `stale-moc`. `unexpected-moc` names a direct `MOCs/*.md` file whose
  stem is outside the discipline enum; preserve and report that exact path.
  The flat `MOCs/` inventory rejects directory/leaf symlinks, non-regular or
  unreadable occupants, changed directory state, and portable-equivalent
  ownership conflicts. A missing directory is valid initialization state.
  Preserve inactive discipline MOCs and report legacy paths; these findings do not
  authorize a move, deletion, or scope expansion.
- `moc_consistency_findings` validates the complete content of every readable
  or empty recognized MOC. It checks bullet structure and indentation, the
  three-level limit, canonical targets/labels, wrong-discipline
  links, entry coverage, duplicate same-parent placements,
  discipline eponymous-root shape, and exact parent-union consistency. For
  misc, a `misc-format` finding identifies nested bullets or plain category
  terms. A `misc-order` finding identifies violations of folded canonical
  title order with exact vault-relative path tie-breakers. A
  `wrong-discipline-link` finding also identifies entries without a valid
  misc-only tag list when listed in misc. An empty active
  MOC reports missing entries when members exist; an empty zero-member misc
  file is valid after an authorized refresh. A `legacy-markers` finding identifies obsolete marker comments
  with their first `line` and a `lines` list; standalone old marker lines may
  be skipped for inference but remain a repair finding. All other content
  anywhere in the file is validated: prose, headings, fences, and frontmatter
  are malformed outline lines. No marker-region ownership or adoption gate
  applies; authorized Task 3 regenerates the complete outline.
- Every generated entry target uses its full extensionless vault-relative
  path, such as `Wiki/methods/k-means`; root parents use `MOCs/<discipline>`
  or `MOCs/misc`.
  Entry parents keep qualification when a basename is shared. File-state
  inspection and tree parsing use the same guarded snapshot.
- Exact union comparison requires every required group MOC to be readable/empty and
  structurally parseable, with a usable entry placement in each. An unsafe
  occurrence below an unresolved/wrong-discipline ancestor blocks
  inference even if another occurrence is usable. `self_parented`,
  `parent_cycles`, and `per_discipline` describe existing edges;
  `per_discipline` records use `entries` for their member count.

After a completed full-vault Task 3 pass, active entry/discipline hierarchy
worklists are empty and every active MOC is readable (or empty for zero-member misc) and contains
only its generated outline. Inactive discipline MOCs, legacy migration blockers, and skipped
closures remain reported and preserved; do not describe their findings as
repaired.

A real MOC filename owner outranks a Wiki alias with that spelling. Only a
recognized, readable canonical MOC (discipline or misc) receives `item10/case` to
qualify a bare target as `MOCs/<discipline>` or `MOCs/misc`, preserving its anchor and label.
An unknown MOC name receives `item10/moc` on bare and explicit navigation
links; preserve it without automatic qualification. When a real Wiki file
and MOC share the basename, including an unknown MOC name,
`item10/ambiguous` preserves the bare link for ownership resolution. Valid
MOC navigation in entry prose or Related is excluded from entry duplicate
and label checks.

### Item keys in `problems`

`item1` … `item19` map to the builder's [numbered checklist](../../wiki-build/SKILL.md#quality-checklist). There is no `item20`; existing `importance:` is preserved and not flagged. The complete repair/report routing is in [QC finding actions](qc-items.md#finding-actions), rather than a second action list here.

| Key | Detected condition |
| --- | --- |
| `item2/type-enum` | `type:` is blank, non-scalar, or outside the 15 canonical values. This detects spelling, not the semantic choice of type. |
| `item2/read-missing` | No `read:` key. |
| `item2/read-null` | Present but valueless: bare `read:`, null, or `~`. |
| `item2/read-type` | A recognizable boolean answer in another spelling, such as quoted `"false"`, `yes`/`no`, or `0`/`1`. |
| `item2/read-unknown` | No recognizable boolean meaning, including arbitrary strings and lists. |
| `item2/parents-null` | A present but valueless bare `parents:` key where the canonical empty list is `parents: []`. |
| `item2/parents-form` | `parents:` is scalar, populated flow form, contains a noncanonical/non-wikilink item, or repeats a target. |
| `item2/obsidian-key` | A valid Obsidian-owned appearance/publish key, not a schema violation. |
| `item3/report-only` | `created` is later than `updated`; ordinary `item3` also detects date format/calendar problems. The ordering finding is nonblocking because wiki-lint does not write either date. |
| `item4` | Missing, scalar, malformed, or exactly duplicated source references, including invalid PDF page anchors and anchored Markdown sources. |
| `item4/source-identity` | PDF and Markdown references share a normalized stem; this does not prove they are one source. |
| `item7` | Description missing, longer than 110 characters, more than one conservatively detected sentence, non-plain-text, missing its initial capital where the canonical running form does not start lowercase, missing its final period, or clearly starting with another subject. Plain text excludes LaTeX/dollar signs, Obsidian and Markdown links/images, reference links/definitions, emphasis, strikethrough, backticks, HTML/entities, tags, highlights, comments, footnotes, and block Markdown. The running form is the title's meaning-preserving mathematical plain form in the ordinary case and only the base term's mathematical plain form for a parenthetical-disambiguated title; the full qualified form is a finding in prose. The shared conversion unwraps formatting without dropping operators or indices (`$A^{*}$` → `A-star`; `$\ell_1$` or `ℓ₁` → `ell-one`; `$L^{-1}$` → `L-inverse`; `$x^{1/2}$` → `x-to-the-one-half`; `$R^{+}$` → `R-plus`; `$\chi^2$` or `χ²` → `chi-squared`). The sentence counter excludes decimals, versions, initials, common abbreviations, and taxonomic rank abbreviations; a real boundary immediately after one of those may be under-counted and remains part of the autonomous agent review. The conservative subject check permits an article and first-letter case carve-out; complex grammatical heads and tense still need agent judgment. |
| `item8` | Wiki tags are blank/empty, missing, malformed, off-enum, noncanonical, duplicated, or combine `#misc` with a specific discipline. Require a nonempty quoted block list; `#misc` is the sole fallback tag. Genuine blanks remain in `untagged_entries` for evidence-based repair, not automatic misc placement. |
| `item9` | Blank space after frontmatter, a non-prose opener, non-ATX Setext heading, wrong-level or marked-up body heading, or a missing/malformed Person/Event opener date. Date spelling uses the complete grammar in the builder's rare-types guide, and a full `YYYY-MM-DD` must be a possible calendar date; factual correctness remains source-dependent. Sentence case and whether a heading earns a section are checked by the executing agent. |
| `item9/imperative-link` | A narrow navigation-only cue (`see`, `see also`, `refer to`, `consult`, or `for details see`) points directly at a wikilink in prose. Listings, figure/table material, and captions are excluded. Integrate it only when adjacent prose already states the relationship; otherwise propose a source-backed correction. Ordinary prose such as “to see how…” is not matched. |
| `item9/duplicate-sentence` | A long sentence has the same normalized word sequence in more than one entry after link and presentation syntax are normalized. Listings, display equations, tables, captions, images, Related footers, and flashcards are excluded; inline code and inline math retain their identifiers and operators in the comparison key. Short/common sentences stay below the floor. This is an ownership candidate rather than proof that either copy is wrong. Preserve both copies during routine lint. Consolidation requires source evidence and explicit refactor authorization naming the operation or the affected entries and outcome; a generic lint/fix request does not supply it. |
| `item10/self` | A body or Related target resolves to the current entry through its canonical/path/`.md`/case spelling or an own alias. |
| `item10/dangling` | An actual entry-link target is absent after resolution checks against a complete alias inventory. Suppressed while alias ownership is incomplete. |
| `item10/case` | An existing target needs case/Unicode normalization or unambiguous path qualification, including a bare target whose sole owner is a recognized, readable canonical MOC (discipline or misc) and must become `MOCs/<discipline>` or `MOCs/misc`. Preserve the label and anchor. |
| `item10/alias` | A target resolves to another entry's unambiguous alias; a filename match takes precedence. |
| `item10/ambiguous` | Multiple files own the basename or multiple entries claim the alias. An exact or unique-suffix qualified path resolves one file; a qualified path matching none stays ambiguous while several basename owners remain, because the scanner cannot safely choose whether Obsidian intended one of them or a missing path. |
| `item10/unparsed` | The target file exists but did not parse as an entry; its own finding is `item0` or `item1`. |
| `item10/moc` | A bare or explicit MOC navigation target is unknown, or an explicit `MOCs/` target is missing or unsafe. Preserve its original destination without automatic qualification and route the finding to Task 3; it is not an entry dangler or Wiki alias. |
| `item10/dup` | The same resolved entry appears more than once in actual body prose, excluding code/listings. Path/`.md`/case/Unicode spellings and an unambiguous alias collapse to their canonical owner when the inventory identifies one owner; a file outranks an alias. If a basename or alias has several owners, distinct qualified paths remain distinct and bare ambiguous occurrences do not receive a removal finding. |
| `item10/table` | A rendered wikilink appears in a parsed Markdown table cell. Every parsed row is checked, including a row with fewer cells than the header and therefore no pipe. Replace the link markup with its rendered plain text; the row is then masked from ordinary item-10 resolution and duplicate checks. |
| `item10/redundant-pipe` | An exact `[[slug|slug]]` occurs in body prose. Collapse it to `[[slug]]`; the Related footer is excluded because its canonical-title display label remains mandatory. |
| `item11` | A missing, duplicated, nonterminal, or malformed Related footer; prose after the footer; noncanonical separators; unresolved/self links; or labels that are unpiped or differ from the resolved canonical title. |
| `item12` | An unescaped literal dollar, or an Obsidian/Markdown image embed or Markdown table without an immediate italic plain-text caption. Nested italics, wikilinks, bold, and backticks are rejected in captions; LaTeX is allowed. Fenced and indented listing samples are ignored. |
| `item12/equation-typography` | Raw ℓ-norm notation in prose, a description, or a flashcard prompt, or raw `μm`/`µm` in prose or a flashcard prompt. Descriptions use plain `ell-one`/`ell-two` and may retain Unicode `μm`; prose and card prompts use inline LaTeX such as `$\ell_1$` and `$\mu\mathrm{m}$`. |
| `item12/equation-coverage-candidate` | A conservative corpus-backed cue finds an affirmative square-root-of-variance definition, a defining formula left inline, or one of several complete prose calculations without a nearby following display that contains the covering operation. A defining formula left inline is always a form candidate, and an unrelated display does not suppress a prose cue. For a square-root cue, the root operand itself must be a variance operator, an established squared standard-deviation symbol, or a recognizable average of squared deviations; unrelated root and variance terms in one display do not count. The executing agent verifies semantic ownership and context, then typesets only the stated relationship; the scanner never generates LaTeX, and a square-root cue never chooses a population/sample denominator. |
| `item12/equation-format` | An existing display has equation content on the same line as its `$$` delimiters. Keep the equation and move each delimiter to its own line; do not add a second equation. |
| `item12/panel-composite` | The entry embeds a composite figure and a lowercase-suffixed panel of the same exhibit. Preserve both until source-backed review chooses the default composite or the subject-specific panel. |
| `item12/remote-image` | A valid remote Markdown image URL, reported as a possible localization opportunity. |
| `item12/missing-image` | An image embed has no file in the supplied `--images` directory; without that argument the check did not run. |
| `item13` | A schema key, stray `---`, or standalone digit line in body prose after listings are masked. The one canonical Flashcards separator is excluded. |
| `item14` | An exact source-meta blacklist phrase outside code/listings. Named-work `authors of …` and `source code` are excluded; bare words such as “later” and “above” do not trigger it. |
| `item16` | Missing or mismatched opener emphasis, unenumerated bold, emphasis wrapped around wikilink/math/code, or a bare known bracket token/common literal extension in running prose. One exact exception permits outer bold around a pure inline-math title in its first opener slot (`**$R^{+}$**`); the same wrapping anywhere else remains a finding. The conservative code-shape scan excludes listings, math, link/embed syntax, tables, headings, captions, URLs, domains, decimals, and filename-attached extensions. |
| `item17/alias-candidate` | The shared builder/linter detector found an opener-bound or synonym-cued name for this subject that is absent from `aliases:` after mechanical equivalence exclusions. Same-entity and collision safety remain judgment. |
| `item18` | Empty or own-slug alias, alias duplication/collision/noncanonical form, display-label markup, a label with no plausible target surface, or a label that exactly names a different existing canonical entry or unique alias. Listings and parsed tables are masked. The competing-owner case is review-only; ambiguous ownership stays silent. |
| `item19` | Flashcard section/card structure and spacing, cue, line-1 capitalization/terminal period/markup/Unicode-case-punctuation-normalized answer leak, line-3 content plainness, exact-one-card rule, or a primary line-3 content value that departs from the canonical title's meaning-preserving mathematical plain form/base term and any opener-established, alias-bound counterpart. The shared parser excludes recognized scheduling and block-ID attachments from this read-only content view; it never rewrites them. The separator and heading each require a following blank line. The three counterpart classes live in the flashcard guide. The scanner does not detect semantic answer reconstruction, a missing mathematical operation, or required line-1 equation coverage, nor infer that an alias pair should have been bound in the opener; the executing agent checks those definition-quality concerns on every card. |
| `item0` | A file could not be read (encoding, symlink, permissions); it is absent from inventory/worklists and the scan continues with alias-dependent actions suppressed as described above. Its pathname remains occupied. |

A case variant, alias, ambiguous owner, or unparsed file is not a genuinely missing target. Body code samples and embeds are not entry links. Resolve findings with the linked action guide; never infer that an `itemN` is automatically fixable.

## Deterministic scanner and autonomous semantic pass

The scanner mechanizes deterministic conditions and emits detections;
[QC finding actions](qc-items.md#finding-actions) owns repair permission and
the full per-item rule. The executing agent completes the remaining semantic
checks automatically in the same run. No user or other human must review the
notes or sign off for an ordinary run to complete. Mechanical coverage is:

- **Items 1–2:** frontmatter position/fences, parseable lines, and malformed
  flow lists with empty comma-delimited elements; mandatory-key
  presence/order/quoting; canonical `type:` enum; duplicate/unexpected keys;
  `read:` state-shape variants; null and malformed `parents:`; and report-only
  Obsidian keys.
- **Items 3–8:** date spelling, calendar validity, and ordering; source-reference
  form and same-stem identity candidates; filename/slug and collision probes;
  non-`Software` API/code patterns; description presence, length, plainness,
  conservative one-sentence count and canonical-subject prefix,
  capitalization, and terminal period;
  and tag form, enum, aliases, casing, duplicates.
- **Items 9–14, 16–17:** opener, exact Person/Event date form, heading, and long exact normalized sentence overlap across entries; actual entry-link
  resolution, table-cell prohibition, and duplicate targets with listings and
  parsed table spans masked; self-link detection; Related-footer link
  form; listing-masked image/table caption form, remote-image observation, and
  optional local image existence and composite/panel coexistence; stray
  frontmatter-key/separator/digit merge scars; the exact
  source-meta blacklist; opener/emphasis formatting; conservative bare
  special-token/common-extension typography; and shared introduced-alias candidates.
- **Items 18–19:** alias slug form, within/cross-entry collisions, and the
  display-label mechanical floor; plus Flashcards section/card structure, cue,
  separator/heading blank-line spacing, line-1 sentence form, markup and
  answer leaks, line-3 plainness, exact canonical/base term,
  any opener-and-alias-established counterpart, and exact-one-card count. The
  executing agent still decides whether an alias pair should have been bound in the
  opener and therefore made a required counterpart.
- **Worklists and diagnostics:** collision/rename candidates, eligible title,
  alias, plural, and explicitly bound Organism common-name backfill surfaces;
  inventory/tag counts; per-discipline placement gaps, invalid parent state,
  and unresolved parents; discipline-MOC file/readability and whole-file
  consistency; and existing self-parent/cycle diagnostics.

The executing agent reviews the entries for semantic type and disciplinary-home calls,
paragraph unity/progression, list shape, sentence clarity, atomic scope,
stacked-body meaning, equation coverage beyond the scanner's conservative corpus-backed candidates, equation form/notation and nearby symbol binding, introduced-alias
same-entity/collision safety beyond the emitted candidates, flashcard bidirectional clarity and required line-1 equation coverage, link
closeness, and hierarchy shape. The scanner
also cannot establish source-dependent facts: citation-page correctness, figure
selection, exhibit/source fidelity, or example support. Those boundaries are
spelled out once in [QC items](qc-items.md), rather than repeated here as a
second repair standard.

## Before you call a finding a false positive

Several checks are deliberately loose or deliberately noisy, and the reasons are recorded as comments in `scripts/scan_vault.py` next to the code. Read the comment before "tightening" anything or overriding a flag wholesale — two of them exist because an earlier stricter version produced false positives at scale, and each re-breaks something wiki-build mandates if re-tightened: the **item-18 display-label subset/superset test** (an exact-match version false-flagged the cross-domain bare-term links wiki-build mandates — 108 of 110 findings on a real run — and the tempting "fix", adding the bare term as an alias, is the silent collision wiki-build exists to prevent) and the **item-16b bullet term-anchor pattern** (a stricter version flagged wiki-build's own canonical definition bullet, `- **True positives** (TP) — …`, which it then re-emitted every run). A third is the report-only `item12/remote-image` key, which was an ordinary `item12` violation until it turned out to prescribe destroying an embed wiki-build mandates — don't re-file it as a fixable finding. A check that fires often on **real** issues is the check working; only a genuine, recurring **false** positive is grounds for a proposal to narrow it under the [proposal process](backlogs.md#proposal-scope).

**These two checks are why this file has a mechanical trigger.** `item16` and `item18` are the only findings whose looseness is deliberate and documented, so they are the only ones with a recorded reason to be second-guessed — and both are greppable in the scan JSON. The third loose case, `item12/remote-image`, needs no lookup: it is fully specified in the Step 0 finding taxonomy and in item 12 of `references/qc-items.md`, and it is report-only either way.
