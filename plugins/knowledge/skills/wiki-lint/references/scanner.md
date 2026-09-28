# The scanner — CLI, output contract, and what it does not check

Read this when a scan exits non-zero, a JSON field/finding is unfamiliar, or an `item16`/`item18` result needs interpretation. Those checks have intentional allowances described under [Before you call a finding a false positive](#before-you-call-a-finding-a-false-positive). Run the helper at [Step 0](../SKILL.md#step-0--inventory-the-vault); use [QC actions](qc-items.md#finding-actions) to decide what may be changed.

Contents: [CLI](#cli) · [Output contract](#output-contract) · [Item keys](#item-keys-in-problems) · [Coverage limits](#deterministic-scanner-and-autonomous-semantic-pass).

The scanner is `scripts/scan_vault.py`, a read-only stdlib Python helper. Its JSON describes detections, not permission to edit the vault.

## CLI

```
python3 scripts/scan_vault.py WIKI [--vault DIR] [--images DIR] [--out FILE] [--indent N] [--test]
```

- `WIKI` — the vault's **`Wiki/` folder**, not the vault root. The scanner walks entries only inside this folder. Suggestion logs and unrelated root notes are never linted or listed inside a MOC.
- `--vault DIR` — the selected vault root for qualified entry links, parent resolution, backfill targets, and MOC diagnostics. Pass it even when a read-only run omits `--images`.
- `--images DIR` — the vault's flat **`Sources/Images/`** folder. With it, every supported local image embed in every entry is checked to name a file that is really there, emitted as `item12/missing-image`. **Pass it on every apply-capable run.** For a preview/report-only run with a genuinely absent default image folder, omit this argument while retaining `--vault`, and report the image checks as unavailable under [Step 0](../SKILL.md#step-0--inventory-the-vault). Without the argument that check silently does not run, and an entry embedding a figure that is not on disk scans clean. Image identity is matched on the **basename**, case- and normalization-folded on every host, so a path-qualified `![[Sources/Images/X.png]]`, a unique case/normalization variant, and a legacy nested file are not reported as missing; producers still write and references should use the exact on-disk spelling. Embeds shown inside fenced, indented, or inline code are skipped: listing syntax is not a rendered embed. See the `image_folder_findings` row for folder, collision, and unreadable-inventory findings.
- `--out FILE` — write the JSON to `FILE` instead of stdout. Use this on any real vault with a filename unique to the run, since a fixed shared temporary name can supply another vault's results, and read the file in slices (filter by `item`, by slug, by key) rather than pulling the whole object into context.
- `--indent N` — JSON indent, default `2`; `--indent 0` emits one compact line.
- `--test` — runs the scanner's built-in self-test and exits; it is not a vault scan.
- Exit status `2` with a usage error if `WIKI` is not a directory, or a supplied `--vault` or `--images` path is not a directory. Exit status `1` with an explicit error if a Wiki directory cannot be walked or its identity cannot be established: no worklists are produced and a requested output file is left untouched. That incomplete inventory cannot establish missing names, aliases, or complete MOC coverage. Individual unreadable leaf files instead remain known occupants and receive `item0`. Other failures are genuine crashes worth recording as execution friction in the [run report](backlogs.md#run-report). Any nonzero exit, missing helper, malformed JSON, or incomplete output blocks every dependent write; never reuse an earlier report as the failed scan's result.

The body and section readers ignore hidden HTML/Obsidian comments and escaped wikilink examples while retaining source line positions. A commented template heading is not an extra Flashcards section, and a commented link neither triggers pruning nor suppresses a later visible backfill candidate. Delimiters inside code stay literal. This read-only body view does not alter the separate flashcard parser or its protected scheduling attachments.

An unreadable leaf or unsupported/ambiguous alias metadata can hide an alias owner even when every filename is known. The affected path's existing QC message says **“Alias inventory is incomplete”**. Local QC and direct-filename checks continue, but the scan suppresses dangling-link findings, alias-dependent canonicalization and duplicate/self-link removal, alias-addition candidates, and all backfill candidates. Bare parent targets requiring alias resolution remain `unparsed`. Preserve these unresolved links; safely correct the metadata/readability under its normal scope, then rescan to restore ordinary work. A readable note with definitively no frontmatter, or unrelated field-value QC with fully parsed aliases, does not create this uncertainty.

Aliases and backfill surface ownership include every parsed physical file, even when several files share one portable basename. An alias belonging to any such file stays `item10/ambiguous`, and an alias parent stays `ambiguous`, until filename ownership is resolved. It cannot become a dangling-link removal, an arbitrary canonical rewrite, or a backfill destination. Unrelated aliases and qualified direct-file checks continue normally.

The scanner **never writes to the vault.** It reads Markdown files recursively inside `Wiki/` and prints; the executing agent applies every authorized fix, MOC, `parents:` value, and log append in the same autonomous run.

## Output contract

One JSON object with these keys.

| key | type | contents |
| --- | --- | --- |
| `run_timestamp` | string | `YYYY-MM-DD HH:MM` at scan time. Use the initial value for suggestion-item `Seen` timestamps unless a coordinating run supplied its own; rescans and invoked skills do not count as additional runs. |
| `wiki_path` | string | absolute path actually scanned (confirms an overridden path took effect) |
| `vault_root` | string | selected root used for qualified entry links, parent resolution, backfill targets, and canonical/legacy MOC diagnostics: explicit `--vault` when supplied; otherwise inferred from a supplied `Sources/Images` path, the nearest `.obsidian` ancestor, or the parent of `wiki_path`, in that order |
| `inventory` | object | `entries` is the count and `slugs` is the sorted list of entry filenames without `.md`. The resolution model contributes at most one parsed owner for a portable basename collision; every parseable physical file still receives local QC. |
| `discipline_tags` | object | Observed discipline-enum slug → integer entry count, including `misc`. Counts include recognized values in an invalid mixed list alongside its `item8` finding; they do not establish valid misc membership. |
| `off_enum_tags` | object | malformed / off-enum tag slug → the entries carrying it. Every one of these is an item-8 finding too; this key groups them by bad slug so a vault-wide pattern is visible at a glance. |
| `untagged_entries` | array | Repair worklist of entries with a provably blank `tags:` key or empty list. These receive `item8` and have no implied misc membership. Inspect the note and assign its one specific discipline tag, or `"#misc"` alone, before placement. Missing, scalar/null, duplicate-key, malformed, or structurally unparseable frontmatter cannot establish a genuine blank and remains separately reported; unrelated field-value QC does not itself block this worklist. |
| `problems` | array | `{"slug", "item", "message"}`, sorted. When several physical files share one portable basename, file-specific findings add the Wiki-relative `"path"` (including `.md`) so each body can be repaired without choosing by walk order; ordinary rows retain the historical three fields. The deterministic violations. See *Item keys* below. |
| `problem_tally` | array | per item: `{"item", "entries", "pct_of_entries", "issues"}`, ranked by entries affected. `entries` counts affected files, including unreadable `item0` files; `pct_of_entries` is the one-decimal percentage of parsed entries touched, the recurrence evidence a wiki-build proposal cites. |
| `collision_candidates` | array | `{"a", "b", "probe", "detail"}` — two slugs the item-5 probes matched. `probe` ∈ `exact`, `plural`, `hyphenation`, `word-order`, `word-order-singular`, `µ-variant`, `stem-morphology`; `detail` is the two colliding identifiers. `word-order-singular` sorts the tokens *after* singularising each one, which is what catches `weight-tying` against `tying-weights` — a pair a raw token sort misses on `weights` ≠ `weight`. `stem-morphology` is create-time probe (f), using the shared light-stem key, and is emitted only when an earlier, more specific probe has not already covered the pair. Unordered pairs are de-duplicated per probe. **Review only — never merged.** wiki-build's create-time probe (g), token-superset, is deliberately **not** mirrored in this vault-wide sweep — qualified-vs-base pairs (`feature-machine-learning` beside `machine-learning`) are exactly what the disambiguation rules produce on purpose, so a whole-vault pass would flood on legitimate pairs; its absence from this probe list is by design. |
| `rename_candidates` | array | `{"slug", "new_slug", "inbound_links", "target_exists"}` — entries whose filename ≠ `slug(title)`. `inbound_links` is how many actual prose/Related wikilinks a rename would have to rewrite. It uses the same path-aware resolver as item 10, so path-qualified, anchored, case/normalization-variant, and explicit-`.md` spellings count against the file they open; a bare target with several same-basename owners is conservatively omitted instead of assigned by walk order. `target_exists: true` means the destination is already taken — an existing file **(whether or not it parsed as an entry: a file with no frontmatter is absent from `inventory` and still occupies its name, and a rename into it would clobber that occupant)**, another entry's alias (the renamed file would outrank that alias and capture its links), **or a second candidate in this same list proposing the same `new_slug`** — so this is a likely duplicate/disambiguation and must **not** be renamed into (applying both of a colliding pair in sequence would have the second silently overwrite the first). `new_slug` is never empty: a title that reduces to the empty slug (CJK, all-symbol) is reported as an `item5` problem instead, because renaming to it would produce a file literally called `.md`. **Propose for approval — never auto-applied.** |
| `backfill_candidates` | array | `{"slug", "target", "surface", "bare_noun_alias", "organism_common_name", "discipline_root"}` — a bare-text mention of `target`'s title/alias (or its plural), or an explicitly bound Organism common-name surface, found in `slug`'s prose. `target` is the supplied safe entry destination: an ordinary unambiguous slug, or the full extensionless vault-relative path when another file shares the basename, such as `Wiki/statistics` beside a previous-layout `MOCs/statistics.md`. Preserve that target in body and Related links. Existing links, embeds, ambiguous title/alias surfaces, duplicate Wiki-basename destinations, targets already linked in that entry, and designated common-noun surfaces/destinations are excluded. `organism_common_name: true` means the target's description or opening sentence directly equates its canonical Organism title with that complete surface (or its natural inflection); a bound `fruit fly` never donates the broader head `fly`. It is a locally valid display label, never an instruction to add a global alias, and still needs the ordinary identity/closeness judgment. Other single lowercase aliases of qualified destinations remain candidates and carry `bare_noun_alias: true`; batch-review them under the closeness bar rather than treating the flag as an automatic decision. `discipline_root: true` marks a target that is a Wiki discipline root; the closeness bar accepts one only where the passage discusses the field itself, so batch-review these the same way. A root title directly after a modifier word ("cell biology", "summary statistics") names a subfield or a different sense and is not emitted. Unwritable presentation surfaces are masked so they cannot hide a later eligible occurrence: whole-line italic captions, parsed Markdown-table rows, ATX and Setext headings, fenced/indented/inline code, inline and display LaTeX math, Markdown link-reference definitions, inline Markdown image syntax including alt text, inline/full/collapsed/shortcut Markdown-link labels resolved by those definitions, bare URLs/autolinks, and Obsidian links/embeds. The plural form inflects the title's head token, so irregular forms such as `Confusion matrices` and `Hypotheses` are matched. |
| `hub_footer` | array | `{"target", "footers", "entries"}` — a non-root entry listed in at least `max(15, inventory entries ÷ 20)` Related footers (`footers`). `entries` names the footers where `target` is not the entry's resolved parent or child and shares no parent with it other than a discipline root; a target with no such footer is omitted. `target` is the supplied safe destination, as in `backfill_candidates`. Empty while alias ownership is incomplete. Report-only; Task 2 judges each listed item under the [prune rules](link-hygiene.md#prune-links-within-the-requested-scope). |
| `card_rivals` | array | `{"slug", "cue", "rivals"}` for each entry whose primary cue has a rival: `cue` is line 1 of its first card that carries the primary answer, else of its first card, and `rivals` lists, sorted, the other entries with a cue that are its Related-footer targets or share one of its resolved parents other than a discipline root. A basename shared by several files takes no part. It is input to item 19's forward check, a floor rather than an exhaustive rival set, and authorizes no edit. |
| `image_folder_findings` | array | `{"path", "kind", "message"}` for a nested directory/file, recognizable temporary/staging artifact, unreadable path, or portable basename collision under the supplied `--images` directory. The `kind` is `nested-directory`, `nested-file`, `temporary-artifact`, `unreadable`, `unusable-file`, or `portable-name-collision`; a collision also carries `paths` with every case/NFC-equivalent owner. The flat-folder and publish-only-finished-files rules come from `CONVENTIONS.md` §8. These are folder-level, report-only observations kept outside `problems`, so they do not inflate entry tallies or authorize moving/renaming/deleting user files. A colliding name remains present for embed-existence checks. An `unreadable` finding suppresses all `item12/missing-image` results for that run because a partial inventory cannot establish absence. The two PDF sidecars and `.DS_Store` are omitted. Empty when `--images` is not supplied or the folder conforms. |
| `spaced_repetition` | object | Advisory, read-only view of `<vault>/.obsidian/plugins/obsidian-spaced-repetition/data.json`. `settings` is `read`, `absent` or `unreadable` (a symlink, non-regular file, invalid JSON or no `settings` object). `uncovered_tags` maps each discipline slug in use to its entry count when the plugin's `flashcardTags` (default `#flashcards`) does not list it; it is empty when `convertFoldersToDecks` is on. `separator_findings` names a `multilineReversedCardSeparator` other than `??` and a nonempty `multilineCardEndMarker`. `schedules_outside_notes` is `false` only when `dataStore` is `NOTES` and `scheduleData.cardSchedules` is an empty object, `null` when the settings were not read, and `true` otherwise. `entries_with_card_attachments` counts the scanned entries whose Flashcards section carries any recognized scheduling attachment or block ID. The scanner never writes the settings file. |
| `hierarchy_diagnostic` | object | Report-only state of entry parents, canonical MOCs, and legacy vault-root MOCs, detailed below. Findings are evidence for an authorized Task 3 closure, never write authorization. |

### Hierarchy diagnostics

Misc membership, coverage, and its sole-parent rule require one structurally
valid tag list containing only `"#misc"` and one tags key. Blank, scalar,
malformed, duplicate, or mixed tags do not qualify. Mixed lists still produce
specific-discipline coverage diagnostics alongside `item8`. Other field-value
QC findings do not exclude an otherwise valid misc tag.

- `entries` counts entries in the scan. `placement_gaps` records
  missing discipline or misc coverage. `unresolved_parents` records `missing`, `ambiguous`,
  `unparsed`, `unreadable`, `legacy-moc`, or `noncanonical-moc` targets.
  `noncanonical-moc` identifies a real `MOCs/<unknown>.md` file outside the
  canonical names that cannot serve as a recognized discipline MOC. No MOC, canonical or legacy, can supply a conceptual parent. `parent_state_findings`
  reports `moc-parent` for forbidden MOC ancestors, `missing-discipline-root`
  for active groups without a valid Wiki root, `root-parent-mismatch` for roots
  with populated parents, and `misc-parent-mismatch` for misc members not
  pointing solely to their Wiki root. Roots alone may have empty parents.
- `unlinked_children` records `slug`, `children`, `footer_links`, `unlinked`
  and `branch_heads` for each parent entry other than misc whose body prose
  and Related footer leave a direct child (an entry whose resolved parents
  include it) unlinked while the footer holds fewer than 12 links.
  `children` counts its direct children and `footer_links` every wikilink in
  its footer; `unlinked` gives the unlinked children as safe targets and
  `branch_heads` the subset with children of their own. A link through a
  path, case variant or unambiguous alias counts; the list is empty while
  alias ownership is incomplete. Task 3 acts on it under
  [Populate parents](hierarchy.md#populate-parents).
- `moc_file_states` inventories each active discipline plus known existing
  MOCs, including existing zero-member discipline MOCs and misc when present
  or needed. Each record includes
  `discipline` (the discipline slug or `misc`), `path`, `target`
  (`MOCs/<group>-moc`), `entries`, and
  `state`: `missing`, `empty`, `readable`, or `unreadable`. Unreadable records
  carry `error`; unsafe directory or leaf ownership must not be mistaken for
  a missing file ready for creation. The state describes the file, not an
  owned region; recognized discipline and misc MOCs are generated as whole notes.
  A valid legacy provenance footer is excluded when deciding whether the outline is
  `empty`, so a footer-only misc note remains an empty navigation list.
- `legacy_moc_states` inventories recognized legacy vault-root MOCs
  (`<vault>/<discipline>-moc.md` for a specific discipline, never
  `misc-moc.md`) and previous-layout `MOCs/<discipline>.md` files, with the
  same file-state information plus `canonical_path`. It is an ownership
  safeguard, not generated-file ownership; only a previous-layout file has a
  [migration](hierarchy.md#migrate-the-previous-moc-layout). A legacy name
  keeps a bare link to it ambiguous, and so does any vault-root note named
  like a canonical MOC.
- `moc_inventory_findings` contains records with `kind`, `path`, and `message`,
  plus the relevant `discipline`, `paths`, or `canonical_path`. Kinds include
  `unsafe-directory`, `ambiguous-directory`, `noncanonical-directory`,
  `ambiguous-moc`, `noncanonical-moc`, `unexpected-moc`, `legacy-location`,
  `previous-layout`, and `stale-moc`. An `unexpected-moc` record is a direct
  `MOCs/*.md` file whose name is neither canonical (`<discipline>-moc.md`) nor
  the previous layout (`<discipline>.md`).
  The flat `MOCs/` inventory rejects directory/leaf symlinks, non-regular or
  unreadable occupants, changed directory state, and portable-equivalent
  ownership conflicts. A missing directory is valid initialization state.
- `moc_consistency_findings` validates the complete content of every readable
  or empty recognized MOC. It checks bullet structure and indentation, canonical targets/labels, wrong-discipline
  links, entry coverage, duplicate same-parent placements,
  discipline eponymous-root shape, and exact parent-union consistency. For
  misc, a `misc-format` finding identifies plain categories or nesting beyond
  the root and its single member level. A `misc-order` finding identifies violations of folded canonical
  title order with exact vault-relative path tie-breakers. A
  `wrong-discipline-link` finding also identifies entries without a valid
  misc-only tag list when listed in misc. An empty active
  MOC reports missing entries when members exist; an empty zero-member misc
  file is valid after an authorized refresh. A valid legacy
  [provenance footer](../../../shared/PROVENANCE.md) is tolerated as metadata
  outside the outline, and malformed, duplicate or misplaced legacy
  attribution is an `invalid-provenance` finding. Other comments, prose, headings, fences, and
  frontmatter are malformed outline lines. Task 3 regeneration emits only the
  outline and never adds or carries forward a footer
  ([hierarchy](hierarchy.md#build-or-maintain-the-moc-files)).
- Every generated entry target uses its full extensionless vault-relative
  path, such as `Wiki/methods/k-means`. Parents, including a discipline root
  (`[[machine-learning]]`, `[[misc]]`), use the bare slug and keep the actual
  Wiki path only when a basename is shared, as it is beside a previous-layout
  MOC. The roots themselves have `[]`. File-state
  inspection and tree parsing use the same guarded snapshot.
- Exact union comparison requires every required group MOC to be readable/empty and
  structurally parseable, with a usable entry placement in each. An unsafe
  occurrence below an unresolved/wrong-discipline ancestor blocks
  inference even if another occurrence is usable. `self_parented`
  and `parent_cycles` describe existing edges.

The actions for these fields and the completion postcondition are in
[hierarchy](hierarchy.md#read-diagnostics-and-verify-completion).

A real MOC filename owner outranks a Wiki alias with that spelling. Only a
recognized, readable canonical MOC (discipline or misc) receives `item10/case` to
qualify a bare target as `MOCs/<discipline>-moc` or `MOCs/misc-moc`, preserving its anchor and label.
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
| `item1` | No or unterminated frontmatter, a leading blank line, an unparseable or stray line, or a block-list indentation or unquoted-hash item error. |
| `item2` | Fields out of schema order, a missing mandatory key, a duplicate or unexpected (user) key, or a quoting violation. |
| `item2/type-enum` | `type:` is blank, non-scalar, or outside the 15 canonical values. This detects spelling, not the semantic choice of type. |
| `item2/read-missing` | No `read:` key. |
| `item2/read-null` | Present but valueless: bare `read:`, null, or `~`. |
| `item2/read-type` | A recognizable boolean answer in another spelling, such as quoted `"false"`, `yes`/`no`, or `0`/`1`. |
| `item2/read-unknown` | No recognizable boolean meaning, including arbitrary strings and lists. |
| `item2/parents-null` | A present but valueless bare `parents:` key where the canonical empty list is `parents: []`. |
| `item2/parents-form` | `parents:` is scalar, populated flow form, contains a noncanonical/non-wikilink item, or repeats a target. |
| `item2/obsidian-key` | A valid Obsidian-owned appearance/publish key, not a schema violation. |
| `item2/provenance` | Malformed, duplicate or misplaced legacy skill-provenance metadata. Missing footers are not defects or evidence of a particular producer. |
| `item3` | A date is missing, not `YYYY-MM-DD`, or not a valid calendar date. |
| `item3/report-only` | `created` is later than `updated`. |
| `item4` | Missing, scalar, malformed, or exactly duplicated source references, including invalid PDF page anchors and anchored Markdown sources. |
| `item4/source-identity` | PDF and Markdown references share a normalized stem; this does not prove they are one source. |
| `item5` | A portable slug owned by two files, a title that cannot be slugged, `slug(title)` ≠ filename (also listed in `rename_candidates`), or a bare-slug common-noun title that needs qualification. |
| `item6` | A code-identifier title, an API-surface failure string, fenced code, or backticked identifiers in a non-`Software` entry. |
| `item7` | Description missing, longer than 110 characters, more than one conservatively detected sentence, non-plain-text, missing its initial capital where the canonical running form does not start lowercase, missing its final period, or clearly starting with another subject. Plain text excludes LaTeX/dollar signs, Obsidian and Markdown links/images, reference links/definitions, emphasis, strikethrough, backticks, HTML/entities, tags, highlights, comments, footnotes, and block Markdown. The running form is the title's meaning-preserving mathematical plain form in the ordinary case and only the base term's mathematical plain form for a parenthetical-disambiguated title; the full qualified form is a finding in prose. The shared conversion unwraps formatting without dropping operators or indices (`$A^{*}$` → `A-star`; `$\ell_1$` or `ℓ₁` → `ell-one`; `$L^{-1}$` → `L-inverse`; `$x^{1/2}$` → `x-to-the-one-half`; `$R^{+}$` → `R-plus`; `$\chi^2$` or `χ²` → `chi-squared`). The sentence counter excludes decimals, versions, initials, common abbreviations, and taxonomic rank abbreviations; a real boundary immediately after one of those may be under-counted and remains part of the autonomous agent review. The conservative subject check permits an article and first-letter case carve-out; complex grammatical heads and tense still need agent judgment. |
| `item8` | Wiki tags are blank/empty, missing, malformed, off-enum, noncanonical, duplicated, name more than one discipline, or combine `#misc` with a specific discipline. The rule is exactly one quoted enum value in block form, with `#misc` as the sole fallback. Genuine blanks remain in `untagged_entries` for evidence-based repair, not automatic misc placement. |
| `item9` | Blank space after frontmatter, a non-prose opener, non-ATX Setext heading, wrong-level or marked-up body heading, or a missing/malformed Person/Event opener date. Date spelling uses the complete grammar in the builder's rare-types guide, and a full `YYYY-MM-DD` must be a possible calendar date; factual correctness remains source-dependent. Sentence case and whether a heading earns a section are checked by the executing agent. |
| `item9/imperative-link` | A narrow navigation-only cue (`see`, `see also`, `refer to`, `consult`, or `for details see`) points directly at a wikilink in prose. Listings, figure/table material, and captions are excluded. Ordinary prose such as “to see how…” is not matched. |
| `item9/duplicate-sentence` | A long sentence has the same normalized word sequence in more than one entry after link and presentation syntax are normalized. Listings, display equations, tables, captions, images, Related footers, and flashcards are excluded; inline code and inline math retain their identifiers and operators in the comparison key. Short/common sentences stay below the floor. This is an ownership candidate rather than proof that either copy is wrong. |
| `item10/self` | A body or Related target resolves to the current entry through its canonical/path/`.md`/case spelling or an own alias. |
| `item10/dangling` | An actual entry-link target is absent after resolution checks against a complete alias inventory. Suppressed while alias ownership is incomplete. |
| `item10/case` | An existing target needs case/Unicode normalization or unambiguous path qualification, including a bare target whose sole owner is a recognized, readable canonical MOC (discipline or misc) and must become `MOCs/<discipline>-moc` or `MOCs/misc-moc`. |
| `item10/alias` | A target resolves to another entry's unambiguous alias; a filename match takes precedence. |
| `item10/ambiguous` | Multiple files own the basename, multiple entries claim the alias, or an alias belongs to an entry with multiple physical filename owners. An exact or unique-suffix qualified path resolves one file; a qualified path matching none stays ambiguous while several basename owners remain, because the scanner cannot safely choose whether Obsidian intended one of them or a missing path. |
| `item10/unparsed` | The target file exists but did not parse as an entry; its own finding is `item0` or `item1`. |
| `item10/moc` | A bare or explicit MOC navigation target is unknown, or an explicit `MOCs/` target is missing or unsafe. It is not an entry dangler or Wiki alias. |
| `item10/late-link` | A linked target's first body link follows an earlier plain mention of its title, alias, plural, or first-link display label, with the backfill masks applied. Alias-only bare nouns of qualified destinations, the word of a first-link label that is a cross-domain synonym its target introduces, a word inside a hyphenated compound, a discipline root inside a compound ("cell biology"), a descriptor immediately followed by the link itself, part of a longer italic term (*blending training set*), and an italic gene symbol before a link to its Gene/Protein entry are not counted. The agent judges the mention under [late first links](link-hygiene.md#backfill-add-missing-links). Suppressed while alias ownership is incomplete. |
| `item10/dup` | The same resolved entry appears more than once in actual body prose, excluding code/listings. Path/`.md`/case/Unicode spellings and an unambiguous alias collapse to their canonical owner when the inventory identifies one owner; a file outranks an alias. If a basename or alias has several owners, distinct qualified paths remain distinct and bare ambiguous occurrences do not receive a removal finding. |
| `item10/table` | A rendered wikilink appears in a parsed Markdown table cell. Every parsed row is checked, including a row with fewer cells than the header and therefore no pipe. Parsed table rows are masked from ordinary item-10 resolution and duplicate checks. |
| `item10/redundant-pipe` | An exact `[[slug|slug]]` occurs in body prose; the Related footer is excluded because its canonical-title display label is mandatory. |
| `item11` | A missing, duplicated, nonterminal, or malformed Related footer; prose after the footer; noncanonical separators; unresolved/self links; or labels that are unpiped or differ from the resolved canonical title. |
| `item12` | An unescaped literal dollar, or an Obsidian/Markdown image embed or Markdown table without an immediate italic plain-text caption. Nested italics, wikilinks, bold, and backticks are rejected in captions; LaTeX is allowed. Fenced and indented listing samples are ignored. |
| `item12/equation-typography` | Raw ℓ-norm notation in prose, a description, or a flashcard prompt, or raw `μm`/`µm` in prose or a flashcard prompt. Descriptions use plain `ell-one`/`ell-two` and may retain Unicode `μm`; prose and card prompts use inline LaTeX such as `$\ell_1$` and `$\mu\mathrm{m}$`. |
| `item12/equation-coverage-candidate` | A conservative corpus-backed cue finds an affirmative square-root-of-variance definition, a defining formula left inline, or one of several complete prose calculations without a nearby following display that contains the covering operation. A defining formula left inline is always a form candidate, though an asymptotic bound such as $O(1/\epsilon)$ never counts as one, and an unrelated display does not suppress a prose cue. For a square-root cue, the root operand itself must be a variance operator, an established squared standard-deviation symbol, or a recognizable average of squared deviations; unrelated root and variance terms in one display do not count. The executing agent verifies semantic ownership and context, then typesets only the stated relationship; the scanner never generates LaTeX, and a square-root cue never chooses a population/sample denominator. |
| `item12/equation-format` | An existing display has equation content on the same line as its `$$` delimiters. |
| `item12/boilerplate-candidate` | Conservative well-definedness boilerplate candidates outside display blocks, captions, and tables: "nonempty" and presence guards ("requires at least one", "defined only when"), count guards such as `$m \ge 1$`, one-sided sign ranges on named strengths, rates, tolerances, and probabilities (`$\alpha \ge 0$`, "positive learning rate", `$0 < p < 1$`), nonzero-variation guards, and probabilities that sum to one. On card line 1, sums whose index bounds run over every term and restricted sums that skip undefined terms are listed too, except a sum over parameters, whose start index can exclude a bias. Ranges a definition needs (`$p \ge 1$`, `$0 \le \lambda \le 1$`, `$r \in [0,1]$`) are outside the patterns. |
| `item12/panel-composite` | The entry embeds a composite figure and a lowercase-suffixed panel of the same exhibit. |
| `item12/remote-image` | A valid remote Markdown image URL, reported as a possible localization opportunity. |
| `item12/missing-image` | An image embed has no file in the supplied `--images` directory; without that argument the check did not run. |
| `item13` | A schema key, stray `---`, or standalone digit line in body prose after listings are masked. The one canonical Flashcards separator is excluded. |
| `item14` | An exact source-meta blacklist phrase outside code/listings. `authors of` an existing entry, `the source of …`, finance's `book value`/`book-to-market`, and the technical compounds `source code/domain/language/sentence/sequence/node/vertex/distribution/task/signal/term` are excluded; bare words such as “later” and “above” do not trigger it. |
| `item16` | Missing or mismatched opener emphasis, unenumerated bold, emphasis wrapped around wikilink/math/code, or a bare known bracket token/common literal extension in running prose. One exact exception permits outer bold around a pure inline-math title in its first opener slot (`**$R^{+}$**`); the same wrapping anywhere else remains a finding. The conservative code-shape scan excludes listings, math, link/embed syntax, tables, headings, captions, URLs, domains, decimals, and filename-attached extensions. |
| `item17/alias-candidate` | The shared builder/linter detector found an opener-bound or synonym-cued name for this subject that is absent from `aliases:` after mechanical equivalence exclusions. A word from the builder's cross-domain corpus is never a candidate. Same-entity and collision safety remain judgment. |
| `item18` | Empty or own-slug alias, alias duplication/collision/noncanonical form, display-label markup, a label with no plausible target surface, or a label that exactly names a different existing canonical entry or unique alias. A body label that is a cross-domain-corpus word the target introduces in italics (`[[label-machine-learning|target]]`) has a surface. Listings and parsed tables are masked. The competing-owner case is review-only; ambiguous ownership stays silent. |
| `item18/partial-label` | A body-prose label made only of the target title's modifiers, omitting its head word (`[[greedy-algorithm|greedy]]`, `[[bias-variance-trade-off|bias/variance]]`). An inflected or derived head, an alias, and a term the target defines in italics pass; the Related footer is item 11's canonical-title check instead. |
| `item19` | Flashcard section and card structure, with a blank line after the `---` separator and the heading; the separator: `??`, or the user's `!!`; line 1's capitalization, single sentence, terminal period, markup and normalized answer leak; the card set (one definition card per entry; a further card is a report-only legacy extra); plain line 3; and the primary answer: the canonical title's plain form or base term plus any opener-established, alias-bound [counterpart](../../wiki-build/references/flashcards-and-emphasis.md#line-3-the-answer) (with several cards, a note where none carries it gets one finding). A discipline root (its slug is the enum value its sole tag names) needs no card, with or without an empty section; a card it keeps gets every per-card check. The shared parser hides recognized scheduling and block-ID attachments from this read-only view, never rewriting them. Per-card findings on a legacy extra are report-only too. On the primary card, the executing agent checks semantic reconstruction, missing mathematical operations, off-rule line-1 math and an alias pair the opener should have bound. |
| `item19/brevity-candidate` | Advisory: a card's line 1 over 25 words outside inline math, a `, where` symbol glossary after math, or a semicolon clause outside math. A review candidate, never an order. |
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
  resolution, table-cell prohibition, duplicate targets, and a first link
  that follows an earlier plain mention, with listings and parsed table spans
  masked; self-link detection; Related-footer link
  form; listing-masked image/table caption form, remote-image observation, and
  optional local image existence and composite/panel coexistence;
  conservative well-definedness boilerplate candidates; stray
  frontmatter-key/separator/digit merge scars; the exact
  source-meta blacklist; opener/emphasis formatting; conservative bare
  special-token/common-extension typography; and shared introduced-alias candidates.
- **Items 18–19:** alias slug form, within/cross-entry collisions, and the
  display-label mechanical floor, including a label that keeps only its
  target title's modifiers; plus Flashcards section/card structure, cue,
  separator/heading blank-line spacing, line-1 sentence form, markup and
  answer leaks, answer-line markup, exact canonical/base term,
  any opener-and-alias-established counterpart, the card-set shape and brevity
  candidates. The
  executing agent still decides whether an alias pair should have been bound in the
  opener and therefore made a required counterpart.
- **Worklists and diagnostics:** collision/rename candidates, eligible title,
  alias, plural, and explicitly bound Organism common-name backfill surfaces,
  with discipline-root targets flagged; hub footer items; card rivals;
  inventory/tag counts; per-discipline placement gaps, invalid parent state,
  unresolved parents, and parents with unlinked children; discipline-MOC
  file/readability and whole-file consistency; existing self-parent/cycle
  diagnostics; and Spaced Repetition settings (advisory).

The executing agent reviews the entries for semantic type and disciplinary-home calls,
paragraph unity/progression, list shape, sentence clarity, atomic scope,
stacked-body meaning, equation coverage beyond the scanner's conservative corpus-backed candidates, well-definedness boilerplate beyond its phrase candidates, equation form/notation and nearby symbol binding, introduced-alias
same-entity/collision safety beyond the emitted candidates, flashcard bidirectional clarity and line-1 math, link
closeness, and hierarchy shape. The scanner
also cannot establish source-dependent facts: citation-page correctness, figure
selection, exhibit/source fidelity, or example support. Those boundaries are
spelled out once in [QC items](qc-items.md), rather than repeated here as a
second repair standard.

## Before you call a finding a false positive

Several checks are deliberately loose or noisy; the reasons are code comments in `scripts/scan_vault.py` and, for the per-entry floors shared with wiki-build's `lint_entry.py` (items 5, 6, 13, 14, 16 and 18, and item 19's primary-card choice and card-set shape), in the plugin's `shared/scripts/entry_checks.py`. Read the comment before tightening a check or overriding a flag wholesale. The **item-18 display-label subset/superset test** must keep accepting the cross-domain bare-term links wiki-build mandates; never "fix" such a finding by adding the bare term as an alias, which creates the silent collision wiki-build prevents. The **item-16b bullet term-anchor pattern** must keep accepting wiki-build's canonical definition bullet (`- **True positives** (TP) — …`). `item12/remote-image` is report-only under [QC finding actions](qc-items.md#finding-actions) because the ordinary item-12 repair would destroy an embed wiki-build mandates; never re-file it as fixable. A check that fires often on **real** issues is working; only a genuine, recurring **false** positive justifies a narrowing proposal under the [proposal process](backlogs.md#proposal-scope).

`item16` and `item18` are the only findings with a documented, deliberate looseness, which is why they carry a read trigger for this file; both are greppable in the scan JSON.
