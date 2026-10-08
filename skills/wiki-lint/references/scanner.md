# The scanner — CLI, output contract, and what it does not check

Read this when a scan exits non-zero, a JSON field/finding is unfamiliar, or an `item16`/`item18` result needs interpretation. Those checks have intentional allowances described under [Before you call a finding a false positive](#before-you-call-a-finding-a-false-positive). Run the helper at [Step 0](../SKILL.md#step-0--inventory-the-vault); use [QC actions](qc-items.md#finding-actions) to decide what may be changed.

Contents: [CLI](#cli) · [Output contract](#output-contract) · [Item keys](#item-keys-in-problems) · [Coverage limits](#deterministic-scanner-and-autonomous-semantic-pass).

The scanner is `scripts/scan_vault.py`, a read-only stdlib Python helper. Its JSON describes detections, not permission to edit the vault.

## CLI

```
python3 '<skill>/scripts/scan_vault.py' WIKI [--vault DIR] [--images DIR] [--settled FILE] [--out FILE] [--indent N] [--test]
```

- `WIKI` — the vault's **`Wiki/` folder**, not the vault root and not one of its subfolders. The scanner walks entries only inside this folder, under the name its parent folder lists for it, so a case variant such as `wiki` on a case-folding host still reads as `Wiki`. Suggestion logs and unrelated root notes are never linted or listed inside a MOC.
- `--vault DIR` — the selected vault root for qualified entry links, parent resolution, backfill targets, and MOC diagnostics. `WIKI` must lie inside it. The two are compared by folder identity, so a symlink alias or another Unicode spelling of the vault is read in `WIKI`'s own spelling. Pass it even when a read-only run omits `--images`.
- `--images DIR` — the vault's flat **`Sources/Images/`** folder. With it, every supported local image embed in every entry is checked to name a file that is really there, emitted as `item12/missing-image`. **Pass it on every apply-capable run.** For a preview/report-only run with a genuinely absent default image folder, omit this argument while retaining `--vault`, and report the image checks as unavailable under [Step 0](../SKILL.md#step-0--inventory-the-vault). Without the argument that check silently does not run, and an entry embedding a figure that is not on disk scans clean. Image identity is matched on the **basename**, case- and normalization-folded on every host, so a path-qualified `![[Sources/Images/X.png]]`, a unique case/normalization variant, a legacy nested file, and a direct file of a symlinked subfolder are not reported as missing; producers still write and references should use the exact on-disk spelling. An embed whose file sits elsewhere in a known vault (a root from `--vault`, `--images` or an `.obsidian` ancestor), such as a pasted image in `Attachments/`, renders in Obsidian. It is reported as `item12/image-outside-folder`, not as missing. A file found only under a dot-folder such as `.trash/` is still missing. Embeds shown inside fenced, indented, or inline code are skipped: listing syntax is not a rendered embed. See the `image_folder_findings` row for folder, collision, and unreadable-inventory findings.
- `--settled FILE` — the [settled-decisions ledger](link-hygiene.md#settled-decisions), `<vault>/Reviews/.wiki-lint-settled.json` (a `{"version": 2, "backfill": [...], "hub_footer": [...]}` object of `settle_key` records). A `hub_footer` item whose `settle_keys` entry matches a ledger record is omitted (a hub target left with no item goes too). A `backfill_candidates` row whose `settle_key` matches one yields to the target's next eligible occurrence in another sentence of the entry, under that sentence's key; the row is omitted only when every such occurrence is settled. In a `"version": 1` ledger, a record that matches the target's first eligible sentence settles all of the entry's sentences of that target. `settled` reports the effect. A missing file is an empty ledger; an unreadable or malformed one suppresses nothing and is reported in `settled.error`. The scanner never writes the ledger.
- `--out FILE` — write the JSON to `FILE` instead of stdout. Use this on any real vault with a filename unique to the run, since a fixed shared temporary name can supply another vault's results, and read the file in slices (filter by `item`, by slug, by key) rather than pulling the whole object into context.
- `--indent N` — JSON indent, default `2`; `--indent 0` emits one compact line.
- `--test` — runs the scanner's built-in self-test and exits; it is not a vault scan.
- Exit status `2` with a usage error if `WIKI` is not a directory or looks like a vault root (it is the `--vault` directory, or holds `.obsidian/` or a `Wiki/` folder and is not the `Wiki` folder directly inside `--vault`), `WIKI` is not inside the selected vault or lies inside a folder named `Wiki` below it, or a supplied `--vault` or `--images` path is not a directory. Exit status `1` with an explicit error if a Wiki directory cannot be walked or its identity cannot be established: no worklists are produced and a requested output file is left untouched. That incomplete inventory cannot establish missing names, aliases, or complete MOC coverage. Individual unreadable leaf files instead remain known occupants and receive `item0`. Other failures are genuine crashes worth recording as execution friction in the [run report](backlogs.md#run-report). Any nonzero exit, missing helper, malformed JSON, or incomplete output blocks every dependent write; never reuse an earlier report as the failed scan's result.

The body and section readers ignore hidden HTML/Obsidian comments and escaped wikilink examples while retaining source line positions. A commented template heading is not an extra Flashcards section, and a commented link neither triggers pruning nor suppresses a later visible backfill candidate. Delimiters inside code stay literal. This read-only body view does not alter the separate flashcard parser or its protected scheduling attachments.

An unreadable leaf or unsupported/ambiguous alias metadata can hide an alias owner even when every filename is known. The affected path's existing QC message says **“Alias inventory is incomplete”**. Local QC and direct-filename checks continue, but the scan suppresses dangling-link findings, alias-dependent canonicalization and duplicate/self-link removal, alias-addition candidates, and all backfill candidates. Bare parent targets requiring alias resolution remain `unparsed`. Preserve these unresolved links; safely correct the metadata/readability under its normal scope, then rescan to restore ordinary work. A readable note with definitively no frontmatter, or unrelated field-value QC with fully parsed aliases, does not create this uncertainty.

Aliases and backfill surface ownership include every parsed physical file, even when several files share one portable basename. An alias belonging to any such file stays `item10/ambiguous`, and an alias parent stays `ambiguous`, until filename ownership is resolved. It cannot become a dangling-link removal, an arbitrary canonical rewrite, or a backfill destination. Unrelated aliases and qualified direct-file checks continue normally.

The scanner **never writes to the vault.** It reads Markdown files recursively inside `Wiki/` and prints; the executing agent applies every authorized fix, MOC, `parents:` value, and log append in the same autonomous run. It follows a symlinked subfolder of `Wiki/`, but not one that points back into the `Wiki/` tree, whose real folder already holds those files.

It also lists the names of the vault's other Markdown notes, outside `Wiki/`, `MOCs/` and dot-folders. It follows a symlinked folder, as Obsidian indexes it, but not one that points back into the vault. Item 10 uses that list to tell a link to a real vault note from a dangler, and to keep a `Wiki/` path that a same-named note needs. Only a vault root from `--vault`, `--images` or an `.obsidian` ancestor is listed. With the parent-folder fallback, which may be any folder, no note is known. Then, or when a vault folder cannot be read, item 10 keeps every link's path and drops only an explicit `.md` suffix.

## Output contract

One JSON object with these keys.

| key | type | contents |
| --- | --- | --- |
| `run_timestamp` | string | `YYYY-MM-DD HH:MM` at scan time. Use the initial value for suggestion-item `Seen` timestamps unless a coordinating run supplied its own; rescans and invoked skills do not count as additional runs. |
| `wiki_path` | string | absolute path actually scanned (confirms an overridden path took effect) |
| `vault_root` | string | selected root used for qualified entry links, parent resolution, backfill targets, and canonical/legacy MOC diagnostics: explicit `--vault` when supplied; otherwise inferred from a supplied `Sources/Images` path, the nearest `.obsidian` ancestor, or the parent of `wiki_path`, in that order. The CLI reports it in `WIKI`'s own spelling when `--vault` names the same folder another way |
| `inventory` | object | `entries` is the count and `slugs` is the sorted list of entry filenames without `.md`. The resolution model contributes at most one parsed owner for a portable basename collision; every parseable physical file still receives local QC. |
| `discipline_tags` | object | Observed discipline-enum slug → integer entry count, including `misc`. Counts include recognized values in an invalid mixed list alongside its `item8` finding; they do not establish valid misc membership. |
| `off_enum_tags` | object | malformed / off-enum tag slug → the entries carrying it. Every one of these is an item-8 finding too; this key groups them by bad slug so a vault-wide pattern is visible at a glance. |
| `untagged_entries` | array | Repair worklist of entries with a provably blank `tags:` key or empty list. These receive `item8` and have no implied misc membership. Inspect the note and assign its one specific discipline tag, or `"#misc"` alone, before placement. Missing, scalar/null, duplicate-key, malformed, or structurally unparseable frontmatter cannot establish a genuine blank and remains separately reported; unrelated field-value QC does not itself block this worklist. |
| `problems` | array | `{"slug", "item", "message"}`, sorted. When several physical files share one portable basename, file-specific findings add the Wiki-relative `"path"` (including `.md`) so each body can be repaired without choosing by walk order; ordinary rows retain the historical three fields. The deterministic violations. See *Item keys* below. |
| `problem_tally` | array | per item: `{"item", "entries", "pct_of_entries", "issues"}`, ranked by entries affected. `entries` counts affected files, including unreadable `item0` files; `pct_of_entries` is the one-decimal percentage of parsed entries touched, the recurrence evidence a wiki-build proposal cites. |
| `user_issues` | array | `{"slug", "form", "issues"}` for every entry whose `issues:` value is non-blank: the user's own requests for that entry ([details](#user_issues)). |
| `collision_candidates` | array | `{"a", "b", "probe", "detail"}`: two slugs the item-5 probes matched, a merge candidate rather than a decision ([details](#collision_candidates)). |
| `rename_candidates` | array | `{"slug", "new_slug", "inbound_links", "target_exists"}`: entries whose filename ≠ `slug(title)` ([details](#rename_candidates)). When several physical files share one portable basename, each row adds the Wiki-relative `"path"` (including `.md`), as `problems` does. |
| `backfill_candidates` | array | `{"slug", "target", "surface", "bare_noun_alias", "organism_common_name", "discipline_root", "base_term", "line", "settle_key", "settle_keys"}`: a bare-text mention of another entry in `slug`'s prose, Task 2's backfill worklist ([details](#backfill_candidates)). |
| `hub_footer` | array | `{"target", "footers", "entries", "settle_keys"}`: a heavily shared Related-footer target, report-only input to Task 2 ([details](#hub_footer)). |
| `settled` | object | The `--settled` ledger's effect: `path` (the ledger read, `null` without `--settled`), `backfill_suppressed` and `hub_footer_suppressed` (how many backfill occurrences and hub items its records settled), `stale` (`{"backfill": [...], "hub_footer": [...]}`, the ledger records in its own shape that matched no current row, which the closeout drops; empty while alias ownership is incomplete), `upgrade` (for a version-1 ledger, the records of the later sentences its records settle, which the closeout adds; `[]` for any other ledger, and `null` for a version-1 ledger while alias ownership is incomplete) and `error` (`null`, or why an unreadable or malformed ledger suppressed nothing). The ledger never suppresses a `problems` finding. |
| `card_rivals` | array | `{"slug", "cue", "rivals"}` for each entry whose primary cue has a rival: `cue` is line 1 of its first card that carries the primary answer, else of its first card, and `rivals` lists, sorted, the other entries with a cue that are its Related-footer targets or share one of its resolved parents other than a discipline root. A basename shared by several files takes no part. It is input to item 19's forward check, a floor rather than an exhaustive rival set, and authorizes no edit. |
| `image_folder_findings` | array | `{"path", "kind", "message"}`: report-only observations of the `--images` folder ([details](#image_folder_findings)). |
| `spaced_repetition` | object | Advisory, read-only view of the Spaced Repetition plugin's settings ([details](#spaced_repetition)). |
| `hierarchy_diagnostic` | object | Report-only state of entry parents, canonical MOCs, and legacy vault-root MOCs, detailed below. Findings are evidence for an authorized Task 3 closure, never write authorization. |

### `user_issues`

The user's own requests for each entry, handled under
[User issues](../SKILL.md#user-issues).

- One record per entry whose `issues:` value is non-blank, sorted by slug,
  with the Wiki-relative `"path"` added when several files share the
  basename, as in `problems`.
- `form` is `string` (the Obsidian Text property, one plain or quoted line
  that may describe several issues; `issues` holds the whole decoded value as
  one element) or `list` (block or one-line flow form, one decoded element per
  non-empty item).
- Blank values
  ([§2d](../../../shared/CONVENTIONS.md#2d-issues--the-users-issue-inbox):
  `""`, a bare `issues:`, `null`, `~`, `''`, `[]`, a whitespace-only string, a
  list whose items are all empty or null) are not listed, and a malformed
  value is `item2/issues-malformed` instead.
- A value or list item that an unquoted `#` comment cuts off is
  `item2/issues-malformed`, never a blank value or a shortened record.
- Edit the field from the entry's bytes, never from this decoded text.

### `collision_candidates`

**A candidate, never a merge decision:** Task 1b's
[merge check](qc-items.md#5-filename-collision-and-disambiguation) merges a
pair only when the evidence verifies one entity under alternate names.

- `probe` ∈ `exact`, `plural`, `hyphenation`, `word-order`,
  `word-order-singular`, `µ-variant`, `stem-morphology`, `base-term`;
  `detail` is the shared identifier for `exact`, and the two colliding
  identifiers joined by `~` for every other probe. Unordered pairs are
  de-duplicated per probe.
- The `word-order-singular` probe sorts the tokens *after* singularising
  each one, which is what catches `weight-tying` against `tying-weights` — a
  pair a raw token sort misses on `weights` ≠ `weight`.
- The `stem-morphology` probe is create-time probe (f), using the shared
  light-stem key, and is emitted only when an earlier, more specific probe has
  not already covered the pair.
- The `base-term` probe pairs an entry whose slug or alias, singular or
  plural, equals a parenthetical title's base term with that qualified entry
  (`outlier` beside `outlier-statistics`), again only when an earlier probe
  has not covered the pair: a bare entry or alias that equals a qualified
  entry's base term is a duplicate or naming candidate, unlike the
  qualifier-versus-other-base pairs the omitted token-superset probe would
  flood on.
- wiki-build's create-time probe (g), token-superset, is deliberately **not**
  mirrored in this vault-wide sweep — qualified-vs-base pairs
  (`feature-machine-learning` beside `machine-learning`) are exactly what the
  disambiguation rules produce on purpose, so a whole-vault pass would flood
  on legitimate pairs; its absence from this probe list is by design.

### `rename_candidates`

**Task 1b retitles a free destination through the
[entry-retitle protocol](refactors.md#retitle-an-entry); an occupied one is
never retitled into, and a same-entity occupant goes to Task 1b's merge
check.**

- Each physical file whose filename differs from its title slug gets its own
  row, including every file of a basename that several files share. Such a
  row carries the file's `path`.
- `inbound_links` is how many actual prose/Related wikilinks a rename would
  have to rewrite. It uses the same path-aware resolver as item 10, so
  path-qualified, anchored, case/normalization-variant, and explicit-`.md`
  spellings count against the file they open; a bare target with several
  same-basename owners is conservatively omitted instead of assigned by walk
  order.
- `target_exists: true` means the destination is already taken, so this is a
  likely duplicate/disambiguation and must **not** be renamed into. It is
  taken by:
  - an existing file **(whether or not it parsed as an entry: a file with no
    frontmatter is absent from `inventory` and still occupies its name, and a
    rename into it would clobber that occupant)**, including another file
    that shares the renamed file's basename;
  - another entry's alias (the renamed file would outrank that alias and
    capture its links);
  - **or a second candidate in this same list proposing the same
    `new_slug`** (applying both of a colliding pair in sequence would have the
    second silently overwrite the first).
- The renamed file itself never takes its destination: a `new_slug` that
  differs from the filename only in case or Unicode normalization has
  `target_exists: false`, and the retitle protocol respells that same file.
- `new_slug` is never empty: a title that reduces to the empty slug (CJK,
  all-symbol) is reported as an `item5` problem instead, because renaming to
  it would produce a file literally called `.md`.

### `backfill_candidates`

Each row is a bare-text mention of `target`'s title/alias or parenthetical
base term (or its plural), or an explicitly bound Organism common-name
surface, found in `slug`'s prose.

- **`target`** is the supplied safe entry destination: an ordinary
  unambiguous slug, or the full extensionless vault-relative path when another
  vault file shares the basename, such as `Wiki/statistics` beside a
  previous-layout `MOCs/statistics.md` or `Wiki/variance` beside an
  `Articles/variance.md` note. Preserve that target in body and Related links.
  `hub_footer` and `unlinked_children` targets take the same form.
- **Exclusions.** Existing links, embeds, ambiguous title/alias surfaces,
  duplicate Wiki-basename destinations, targets already linked in that entry,
  and designated common-noun surfaces/destinations are excluded.
- **`organism_common_name: true`** means the target's description or opening
  sentence directly equates its canonical Organism title with that complete
  surface (or its natural inflection); a bound `fruit fly` never donates the
  broader head `fly`. It is a locally valid display label, never an
  instruction to add a global alias, and still needs the ordinary
  identity/closeness judgment.
- **`bare_noun_alias: true`** marks the other single lowercase aliases of
  qualified destinations, which remain candidates; batch-review them under the
  closeness bar rather than treating the flag as an automatic decision.
- **`discipline_root: true`** marks a target that is a Wiki discipline root;
  the closeness bar accepts one only where the passage discusses the field
  itself, so batch-review these the same way. A root title directly after a
  modifier word ("cell biology", "summary statistics"), which names a subfield
  or a different sense, or named only as a setting ("in/for/within/across …")
  or genus ("a … system") is not emitted.
- **`base_term: true`** marks the base term of a parenthetical title
  ("outlier" for Outlier (statistics)), offered only when that base term is
  not a cross-domain floor term (`COMMON_NOUNS` or `CROSS_DOMAIN_PHRASES`) and
  never when an existing body link already uses the surface as the display
  label of a different target. A base surface counts as an alias of its entry
  for `bare_noun_alias` and for `item10/late-link`, and the agent judges it
  under the closeness bar like any other.
- **`line`** is the proposed occurrence's 1-based body line (the line after
  the closing frontmatter `---` is line 1). Body and prose line numbers in
  `problems` messages count the same way. The occurrence is the target's
  first eligible one whose sentence the ledger has not settled. An occurrence
  inside a hyphen or en-dash compound (`protein` in `protein-coding`) or inside
  a longer italic or bold term (a bolded title opener) is skipped in favor of a
  later standalone one.
- **`settle_key`** is `{"entry", "target", "surface", "context"}`, the
  [settled-ledger](link-hygiene.md#settled-decisions) record that settles a
  rejection, where `context` is the SHA-1 hex digest of the
  whitespace-collapsed sentence holding the proposed occurrence. When that
  key matches a `--settled` record, the target's next eligible occurrence in
  another sentence is offered under that sentence's key, and the row is
  omitted only when every such occurrence is settled. Two mentions in one
  sentence are one occurrence.
- **`settle_keys`** lists the row's own `settle_key`, then the key of each
  later sentence holding an eligible occurrence of the target that the ledger
  has not settled. A rejection records them all.
- **Masked surfaces.** Unwritable presentation surfaces are masked so they
  cannot hide a later eligible occurrence: whole-line italic captions, parsed
  Markdown-table rows, ATX and Setext headings, fenced/indented/inline code,
  inline and display LaTeX math, Markdown link-reference definitions, inline
  Markdown image syntax including alt text, inline/full/collapsed/shortcut
  Markdown-link labels resolved by those definitions, bare URLs/autolinks, and
  Obsidian links/embeds.
- **Plurals.** The plural form inflects the title's head token, so irregular
  forms such as `Confusion matrices` and `Hypotheses` are matched.

### `hub_footer`

Report-only; Task 2 judges each listed item under the
[prune rules](link-hygiene.md#prune-links-within-the-requested-scope).

- `target` is a non-root entry listed in at least
  `max(15, inventory entries ÷ 20)` Related footers (`footers`), given as the
  supplied safe destination, as in `backfill_candidates`.
- `entries` names the footers where `target` is not the entry's resolved
  parent or child, shares no parent with it other than a discipline root, and
  does not list the entry in its own Related footer; a target with no such
  footer is omitted. The list is empty while alias ownership is incomplete.
- `settle_keys` gives one `settle_key` per `entries` item,
  `{"entry", "target", "context"}`, the
  [settled-ledger](link-hygiene.md#settled-decisions) record that settles a
  kept item, where `context` is the SHA-1 hex digest of the
  whitespace-collapsed footer line; an item whose key matches a `--settled`
  record is omitted, and so is a target left with no item.

### `image_folder_findings`

Folder-level, report-only observations under the supplied `--images`
directory, kept outside `problems` so they do not inflate entry tallies or
authorize moving/renaming/deleting user files. The flat-folder and
publish-only-finished-files rules come from `CONVENTIONS.md` §8.

- One record per nested directory/file, recognizable temporary/staging
  artifact, unreadable path, or portable basename collision. The `kind` is
  `nested-directory`, `nested-file`, `temporary-artifact`, `unreadable`,
  `unusable-file`, or `portable-name-collision`.
- A collision also carries `paths` with every case/NFC-equivalent owner;
  paths that reach one underlying file (two links to the same target, or a
  hard link) are one owner, not a collision. A colliding name remains present
  for embed-existence checks.
- A symlinked subfolder's direct files are indexed, but a directory inside it
  is a directory finding (`nested-directory`, or `temporary-artifact` for a
  staging name) and is not descended.
- An `unreadable` finding suppresses all `item12/missing-image` results for
  that run because a partial inventory cannot establish absence.
- The three PDF figure sidecars and `.DS_Store` are omitted. The list is
  empty when `--images` is not supplied or the folder conforms.

### `spaced_repetition`

An advisory, read-only view of
`<vault>/.obsidian/plugins/obsidian-spaced-repetition/data.json`. The scanner
never writes the settings file; the run lists these notices under *Notes for
the user* in its [run report](backlogs.md#run-report).

- `settings` is `read`, `absent` or `unreadable` (a symlink, non-regular file,
  invalid JSON or no `settings` object).
- `uncovered_tags` maps each discipline slug in use to its entry count when
  the plugin's `flashcardTags` (default `#flashcards`) does not list it; it is
  empty when `convertFoldersToDecks` is on.
- `separator_findings` names:
  - a `multilineCardSeparator` other than `?`;
  - a `multilineReversedCardSeparator` other than `??`;
  - a nonempty `multilineCardEndMarker`;
  - a `singleLineCardSeparator` or `singleLineReversedCardSeparator` changed
    from `::` or `:::` to anything but empty;
  - each active cloze conversion: every `clozePatterns` entry or, without
    that list, each of the `convertHighlightsToClozes`,
    `convertBoldTextToClozes` and `convertCurlyBracketsToClozes` toggles that
    is on;
  - a `noteFoldersToIgnore` that leaves an existing `Articles/` folder parsed
    for cards.

### Hierarchy diagnostics

Misc membership, coverage, and its sole-parent rule require one structurally
valid tag list containing only `"#misc"` and one tags key. Blank, scalar,
malformed, duplicate, or mixed tags do not qualify. Mixed lists still produce
specific-discipline coverage diagnostics alongside `item8`. Other field-value
QC findings do not exclude an otherwise valid misc tag.

- `entries` counts entries in the scan. `placement_gaps` records
  missing discipline or misc coverage. `unresolved_parents` records `missing`, `ambiguous`,
  `unparsed`, `unreadable`, `legacy-moc`, or `unexpected-moc` targets.
  An `unexpected-moc` target is a file the MOC inventory reports as
  `unexpected-moc`. No MOC, canonical or legacy, can supply a conceptual parent. `parent_state_findings`
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
  the previous layout (`<discipline>.md`). A `noncanonical-moc` record is a
  discipline MOC whose filename differs only in case or Unicode normalization;
  its MOC state is `unreadable`.
  The flat `MOCs/` inventory rejects directory/leaf symlinks, non-regular or
  unreadable occupants, changed directory state, and portable-equivalent
  ownership conflicts. A missing directory is valid initialization state.
- `moc_consistency_findings` validates the complete content of every readable
  or empty recognized MOC. It checks bullet structure and indentation, canonical targets/labels, wrong-discipline
  links, entry coverage, duplicate same-parent placements,
  discipline eponymous-root shape (the root appears exactly once, as the
  single top-level bullet), and exact parent-union consistency, which skips
  discipline roots; a root with parents is a `root-parent-mismatch` finding
  instead. For
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

`item1` … `item19` map to the builder's [numbered checklist](../../wiki-build/references/quality-checklist.md). There is no `item20`; existing `importance:` is preserved and not flagged. The complete repair/report routing is in [QC finding actions](qc-items.md#finding-actions), rather than a second action list here.

| Key | Detected condition |
| --- | --- |
| `item1` | No or unterminated frontmatter, a leading blank line, an unparseable or stray line, a flow list with an empty element, a block-list indentation or unquoted-hash item error, or a duplicate key other than `issues:`. The lines of an `issues:` value are left to `item2/issues-malformed`. A frontmatter that only the separator above `## Flashcards` closes (a lost, `----` or `--- text` closing fence) is `item1` as well. |
| `item2` | Fields out of schema order, a missing mandatory key, an unexpected (user) key, or a quoting violation. |
| `item2/type-enum` | `type:` is blank, non-scalar, or outside the 15 canonical values. This detects spelling, not the semantic choice of type. |
| `item2/read-missing` | No `read:` key. |
| `item2/read-null` | Present but valueless: bare `read:`, null, or `~`. |
| `item2/read-type` | A recognizable boolean answer in another spelling, such as quoted `"false"`, `yes`/`no`, or `0`/`1`. |
| `item2/read-unknown` | No recognizable boolean meaning, including arbitrary strings and lists. |
| `item2/issues-missing` | No `issues:` key, the user's issue inbox. Every blank spelling is present and conforming. |
| `item2/issues-malformed` | `issues:` is neither blank, one string nor a list of strings: a mapping, a nested list, a list item that is not one string, a literal or folded block scalar, a value that starts on the line after its key, a string or flow list continued on another line, a value followed by list items, a duplicate `issues:` key, a value or list item with an unquoted `#` at its start or after a space or tab (a YAML comment that cuts its text off), or text that is not valid one-line YAML, such as a plain `issues: a: b`, an unclosed quote or an unreadable flow list. The message names the shape. It is the only finding on the value's lines, which never become `item1` rows or an alias-inventory gap. |
| `item2/parents-null` | A present but valueless bare `parents:` key where the canonical empty list is `parents: []`. |
| `item2/parents-form` | `parents:` is scalar, populated flow form, contains a noncanonical/non-wikilink item, or repeats a target. lint_entry reports it as `2-parents-form`, as it does a MOC parent (`moc-parent`) and a discipline root with parents (`root-parent-mismatch`), except a target spelled by case, alias or an unneeded `Wiki/` path, or one target repeated in two spellings: those need the vault inventory, so only the scan reports them. |
| `item2/obsidian-key` | A valid Obsidian-owned appearance/publish key, not a schema violation. |
| `item2/provenance` | Malformed, duplicate or misplaced legacy skill-provenance metadata. Missing footers are not defects or evidence of a particular producer. |
| `item3` | A date is missing, not `YYYY-MM-DD`, or not a valid calendar date. |
| `item3/report-only` | `created` is later than `updated`. |
| `item4` | Missing, scalar, malformed, or exactly duplicated source references, including invalid PDF page anchors, anchored Markdown sources and malformed URLs (a Markdown link, display text, a wikilinked or scheme-less address, whitespace, a control or invisible character, a port outside 1–65535 or a non-http scheme). A full http(s) URL is a valid source, double-quoted or plain ([§2a](../../../shared/CONVENTIONS.md#2a-wiki-entry--wikimd)). Every entry, a discipline root included, needs at least one source; Task 1b fills an empty `sources:` under [item 4](qc-items.md#4-sources). |
| `item4/source-identity` | PDF and Markdown references share a normalized stem, or a chapter PDF is cited beside its whole-book PDF, with or without the book's `_src` marker. The stem pair does not prove one source; the chapter name does. URL items never enter this check. |
| `item5` | A portable slug owned by two files, a title that cannot be slugged, `slug(title)` ≠ filename (also listed in `rename_candidates`), or a bare slug that is a word or phrase of the shared cross-domain corpus (`COMMON_NOUNS` or `CROSS_DOMAIN_PHRASES`, such as `tree-of-life`), or its plural, and needs qualification; Task 1b retitles it. The semantic pass tests every other bare title against the cross-domain naming rule. |
| `item6` | A code-identifier title, an API-surface failure string, fenced code, or backticked identifiers in a non-`Software` entry. |
| `item7` | Description missing, longer than 110 characters, more than one conservatively detected sentence, non-plain-text, missing its initial capital or final period, or clearly starting with another subject ([details](#item7)). |
| `item7/hedge-candidate` | Advisory: the description carries a frequency hedge, with the same words and exclusions as `item19/hedge-candidate`. A review candidate, never an order; lint_entry reports it as `7-hedge-candidate`. |
| `item8` | Wiki tags are blank/empty, missing, malformed, off-enum, noncanonical, duplicated, name more than one discipline, or combine `#misc` with a specific discipline. The rule is exactly one quoted enum value in block form, with `#misc` as the sole fallback. Genuine blanks remain in `untagged_entries` for evidence-based repair, not automatic misc placement. |
| `item9` | Blank space after frontmatter, a non-prose opener, non-ATX Setext heading, wrong-level or marked-up body heading, a body heading that repeats the title (delete it, never demote it), or a missing/malformed Person/Event opener date. Date spelling uses the complete grammar in the builder's rare-types guide, and a full `YYYY-MM-DD` must be a possible calendar date; factual correctness remains source-dependent. Sentence case and whether a heading earns a section are checked by the executing agent. |
| `item9/imperative-link` | A narrow navigation-only cue (`see`, `see also`, `refer to`, `consult`, or `for details see`) points directly at a wikilink in prose. Listings, figure/table material, and captions are excluded. Ordinary prose such as “to see how…” is not matched. |
| `item9/duplicate-sentence` | A long sentence has the same normalized word sequence in more than one entry after link and presentation syntax are normalized. Listings, display equations, tables, captions, images, Related footers, and flashcards are excluded; inline code and inline math retain their identifiers and operators in the comparison key. Short/common sentences stay below the floor. This is an ownership candidate rather than proof that either copy is wrong; Task 1b consolidates it into the owner. Paraphrased duplicates stay invisible to it, so the semantic pass compares each entry with the neighbors the builder's [overlap audit](../../wiki-build/references/review.md#overlapownership-audit-this-runs-entries-and-their-relevant-neighbors) names: body and Related link targets, backlinkers, entries citing the same source, and family members. |
| `item9/acronym-expansion` | The title, or a disambiguated title's base term, is one token of capital letters and digits with at least two capitals, optionally hyphenated, and no lowercase letter (MNIST, ATP, DNA; not ROC curve, MLOps or SARS-CoV-2), and the opener bolds it without the full-form parenthetical principle 5(f) puts directly after it (past a `Person` or `Event` date). The parenthetical's wording is not judged; an opener that does not bold the title is item 16's finding instead. lint_entry reports it as `9-acronym-expansion`. Other acronym and full-form pairs remain the agent's review. |
| `item9/list-indent` | A display block or continuation paragraph that belongs to a list item is indented short of the item's text column (3 spaces after `1.`, 4 after `10.`), so Obsidian ends the list there. A block belongs to the item when the list resumes after it with the item's next number, or with the same number when the gap opens with a display; a display also belongs when the item's text before it ends with a colon and the display ends the whole list. A nested list belongs to the item when its first marker sits past the item's marker but short of its text column, with another bullet or delimiter or numbered from 1 again. A listing, table or quote in the gap is not reported. A heading or rule in the gap ends the list on purpose; before it, only a display that follows the item's closing colon is reported. A list inside a quote or callout is not checked. lint_entry reports it as `9-list-indent`. |
| `item10/self` | A body or Related target resolves to the current entry through its canonical/path/`.md`/case spelling or an own alias. |
| `item10/dangling` | An actual entry-link target names no vault file after resolution checks against a complete alias inventory: no Wiki entry, alias, document or vault note outside `Wiki/`. Suppressed while alias ownership is incomplete; reported as `item10/ambiguous` instead while a vault folder outside `Wiki/` could not be read. |
| `item10/case` | An existing target needs case/Unicode normalization or unambiguous path qualification, including a bare target whose sole owner is a recognized, readable canonical MOC (discipline or misc) and must become `MOCs/<discipline>-moc` or `MOCs/misc-moc`. An entry target also gets it for an explicit `.md` suffix, or for a `Wiki/`, folder or relative path that the vault-note list shows no other file needs; the message names the one final target, bare in that case. A bare link, with or without `.md`, whose basename a vault note outside `Wiki/` shares gets the qualified path instead, as in `backfill_candidates`, keeping an unanchored body link's written name as its label. |
| `item10/alias` | A target resolves to another entry's unambiguous alias; a filename match takes precedence. |
| `item10/ambiguous` | Multiple files own the basename, multiple entries claim the alias, an alias belongs to an entry with multiple physical filename owners, or a target that names no entry may name a note in an unread vault folder outside `Wiki/`, which the message names. An exact or unique-suffix qualified path resolves one file; a qualified path matching none stays ambiguous while several basename owners remain, because the scanner cannot safely choose whether Obsidian intended one of them or a missing path. |
| `item10/unparsed` | The target file exists but did not parse as an entry; its own finding is `item0` or `item1`. |
| `item10/non-entry` | A body or Related target names a real vault note outside `Wiki/` and `MOCs/` by path or basename. It is not an entry dangler or alias, and never an `item10/dup` target; a real note outranks an alias. Report only. |
| `item10/moc` | A bare or explicit MOC navigation target is unknown, or an explicit `MOCs/` target is missing or unsafe. It is not an entry dangler or Wiki alias. |
| `item10/late-link` | A linked target's first body link follows an earlier plain mention of its title, alias, plural, or first-link display label, with the backfill masks applied. Alias-only bare nouns of qualified destinations, the word of a first-link label that is a cross-domain synonym its target introduces, a word inside a hyphen or en-dash compound (`protein` in `protein-coding`), a discipline root inside a compound ("cell biology"), a descriptor immediately followed by the link itself, part of a longer italic or bold term (*blending training set*, a bolded title, or a `- **Blending training set** —` bullet anchor), and an italic gene symbol before a link to its Gene/Protein entry are not counted. The agent judges the mention under [late first links](link-hygiene.md#backfill-add-missing-links). Suppressed while alias ownership is incomplete. |
| `item10/dup` | The same resolved entry appears more than once in actual body prose, excluding code/listings. Path/`.md`/case/Unicode spellings and an unambiguous alias collapse to their canonical owner when the inventory identifies one owner; a file outranks an alias. If a basename or alias has several Wiki or MOC owners, distinct qualified paths remain distinct and bare ambiguous occurrences do not receive a removal finding. |
| `item10/table` | A rendered wikilink appears in a parsed Markdown table cell. Every parsed row is checked, including a row with fewer cells than the header and therefore no pipe. Parsed table rows are masked from ordinary item-10 resolution and duplicate checks. |
| `item10/redundant-pipe` | An exact `[[slug|slug]]` occurs in body prose; the Related footer is excluded because its canonical-title display label is mandatory. |
| `item11` | A missing, duplicated, nonterminal, or malformed Related footer; prose after the footer; noncanonical separators; or labels that are unpiped or differ from the resolved canonical title. Unresolved and self footer targets are `item10/dangling` and `item10/self`. |
| `item12` | An unescaped literal dollar, or an Obsidian/Markdown image embed or Markdown table without an immediate italic plain-text caption. Nested italics, wikilinks, bold, and backticks are rejected in captions; LaTeX is allowed. Fenced and indented listing samples are ignored. |
| `item12/equation-typography` | Raw ℓ-norm notation in prose, a description, or a flashcard prompt, or raw `μm`/`µm` in prose or a flashcard prompt. Descriptions use plain `ell-one`/`ell-two` and may retain Unicode `μm`; prose and card prompts use inline LaTeX such as `$\ell_1$` and `$\mu\mathrm{m}$`. |
| `item12/equation-coverage-candidate` | A conservative corpus-backed cue finds an affirmative square-root-of-variance definition, a defining formula left inline, or one of several complete prose calculations without a nearby following display that contains the covering operation. An existing display counts in any delimiter form; a noncanonical one is an `item12/equation-format` finding. A defining formula left inline is always a form candidate, though an asymptotic bound such as $O(1/\epsilon)$ never counts as one, and an unrelated display does not suppress a prose cue. For a square-root cue, the root operand itself must be a variance operator, an established squared standard-deviation symbol, or a recognizable average of squared deviations; unrelated root and variance terms in one display do not count. The executing agent verifies semantic ownership and context, then typesets only the stated relationship; the scanner never generates LaTeX, and a square-root cue never chooses a population/sample denominator. |
| `item12/equation-format` | An existing display is not in canonical block form: a `$$` shares its line with the equation or with prose, or a blank line is missing above or below. The scanner finds displays by pairing unescaped `$$` in source order. The key also covers a display that uses `&`, or a `\\` followed by more math, outside every environment, which fails to render. |
| `item12/equation-split-candidate` | One existing display line holds more than one equation, such as `a = …, \qquad b = …` or `a = …, b = …`. Equations split at a top-level gap (`\quad`, `\qquad`, `\enspace`, `\hspace`), a comma or semicolon followed by another relation, a connective (`\Rightarrow`, `\Leftrightarrow` and kin), a `\text{where|with|and|so|hence|thus|therefore|i.e.}` clause, and each column pair of an aligned row. Each row of an `aligned` or `gathered` layout is its own line. A bare `\\` outside such a layout and a new source line inside one display start no new rendered line, so two equations joined by either share a line; a source line that an operator, relation or group carries on from the line above continues its equation. Conditions are not equations: an index range (`i = 1, \ldots, m` or `x = 0, 1`), a `\forall` or `\text{for|if|when|given …}` qualifier, a constraint after `\text{subject to}`, and a comma or `\text{and}` that continues a condition; a gap inside a group, an environment such as `cases`, or `\text{}` never splits. An agent-review candidate. |
| `item12/boilerplate-candidate` | Conservative well-definedness boilerplate candidates outside display blocks, captions, and tables: "nonempty" and presence guards ("requires at least one", "defined only when"), count guards such as `$m \ge 1$`, one-sided sign ranges on named strengths, rates, tolerances, and probabilities (`$\alpha \ge 0$`, "positive learning rate", `$0 < p < 1$`), nonzero-variation guards, and probabilities that sum to one. On card line 1, sums whose index bounds run over every term and restricted sums that skip undefined terms are listed too, except a sum over parameters, whose start index can exclude a bias. Ranges a definition needs (`$p \ge 1$`, `$0 \le \lambda \le 1$`, `$r \in [0,1]$`) are outside the patterns. |
| `item12/panel-composite` | The entry embeds a composite figure and a lowercase-suffixed panel of the same exhibit. |
| `item12/remote-image` | A valid remote Markdown image URL, reported as a possible localization opportunity. |
| `item12/missing-image` | An image embed has no file in the supplied `--images` directory, nor elsewhere in a known vault outside dot-folders; without that argument the check did not run. |
| `item12/image-outside-folder` | An image embed has no file in the `--images` directory but resolves by basename to a file elsewhere in a known vault, such as `Attachments/`. Obsidian renders it. The message lists the vault-relative paths. Report only: never move, rename or delete the file or the embed. |
| `item13` | A schema key, stray `---`, or standalone digit line in body prose after listings are masked. The one canonical Flashcards separator is excluded. |
| `item14` | An exact source-meta blacklist phrase outside code/listings. `authors of` an existing entry, `the source of …`, finance's `book value`/`book-to-market`, and the technical compounds `source code/domain/language/sentence/sequence/node/vertex/distribution/task/signal/term` are excluded; bare words such as “later” and “above” do not trigger it. |
| `item16` | Missing or mismatched opener emphasis, unenumerated bold, emphasis wrapped around wikilink/math/code, or a bare known bracket token/common literal extension in running prose. The opener is the first prose paragraph, so a leading heading or display block never takes the title slot. One exact exception permits outer bold around a pure inline-math title in its first opener slot (`**$R^{+}$**`); the same wrapping anywhere else remains a finding. The conservative code-shape scan excludes listings, math, link/embed syntax, tables, headings, captions, URLs, domains, decimals, and filename-attached extensions. |
| `item17/alias-candidate` | The shared builder/linter detector found an opener-bound or synonym-cued name for this subject that is absent from `aliases:` after mechanical equivalence exclusions. A word from the builder's cross-domain corpus is never a candidate. Same-entity and collision safety remain judgment. |
| `item18` | Empty or own-slug alias, alias duplication/collision/noncanonical form, display-label markup, a body-prose label with no plausible target surface, or a body-prose label that exactly names a different existing canonical entry or unique alias. A Related-footer label is checked here only for markup; its wording is item 11's canonical-title check. A body label that is a cross-domain-corpus word the target introduces in italics (`[[label-machine-learning|target]]`) has a surface. Listings and parsed tables are masked. The competing-owner case is review-only; ambiguous ownership stays silent. |
| `item18/partial-label` | A body-prose label made only of the target title's modifiers, omitting its head word (`[[greedy-algorithm|greedy]]`, `[[bias-variance-trade-off|bias/variance]]`). An inflected or derived head, an alias, and a term the target defines in italics pass; the Related footer is item 11's canonical-title check instead. |
| `item18/cross-domain-alias` | An alias that is a word or phrase of the shared cross-domain corpus (`COMMON_NOUNS` or `CROSS_DOMAIN_PHRASES`, such as `entropy` or `tree-of-life`), or its plural, which is never an alias. Task 1b removes it through the alias-removal protocol. lint_entry reports it as an `18-alias-form` error. |
| `item19` | Flashcard section and card structure, the separator, card line 1, the card set, line 3 and the primary answer ([details](#item19)). |
| `item19/brevity-candidate` | Advisory: a card's line 1 over 25 words outside inline math, a `, where` symbol glossary after math, or a semicolon clause outside math. A review candidate, never an order. |
| `item19/hedge-candidate` | Advisory: a card's line 1 carries a frequency hedge outside inline math (usually, typically, generally, often, sometimes, normally, commonly, frequently). Context-dependent words (mostly, especially), a frequency the cue measures or compares (how often, more often than) and normally distributed are left to the reviewer. A review candidate, never an order; lint_entry reports it as `19-hedge-candidate`. |
| `item19/sr-marker` | A line before the Flashcards section (the whole body when there is none; a line that starts with an HTML comment is skipped with the line after it, as the plugin does) holding the Spaced Repetition single-line separator `::` or `:::` outside a backtick span and outside a fence opened at column 0. The plugin parses the whole note, so the line becomes an extra card; so does a paragraph with a line that is only `?` or `??`, its multi-line separators, except an unindented `?` with no text before it; this case is checked only when the Flashcards section is found, since otherwise the entry's own card lies in the scanned text. A comment opened at the start of a line and not closed there, or a fence opened at column 0 that no later column-0 line closes, is reported too: the plugin skips the rest of the note, card included. lint_entry reports it as `19-sr-marker`. |
| `item0` | A file could not be read (encoding, symlink, permissions); it is absent from inventory/worklists and the scan continues with alias-dependent actions suppressed as described above. Its pathname remains occupied. |

A case variant, alias, ambiguous owner, or unparsed file is not a genuinely missing target. Body code samples and embeds are not entry links. Resolve findings with the linked action guide; never infer that an `itemN` is automatically fixable.

#### `item7`

- **Form.** Description missing, longer than 110 characters, more than one
  conservatively detected sentence, non-plain-text, missing its initial
  capital where the canonical running form does not start lowercase, missing
  its final period, or clearly starting with another subject.
- **Plain text** excludes LaTeX/dollar signs, Obsidian and Markdown
  links/images, reference links/definitions, emphasis, strikethrough,
  backticks, HTML/entities, tags, highlights, comments, footnotes, and block
  Markdown.
- **Running form.** The running form is the title's meaning-preserving
  mathematical plain form in the ordinary case and only the base term's
  mathematical plain form for a parenthetical-disambiguated title; the full
  qualified form is a finding in prose. The shared conversion unwraps
  formatting without dropping operators or indices (`$A^{*}$` → `A-star`;
  `$\ell_1$` or `ℓ₁` → `ell-one`; `$L^{-1}$` → `L-inverse`; `$x^{1/2}$` →
  `x-to-the-one-half`; `$R^{+}$` → `R-plus`; `$\chi^2$` or `χ²` →
  `chi-squared`).
- **Sentences.** The sentence counter excludes decimals, versions, initials,
  common abbreviations, and taxonomic rank abbreviations; a real boundary
  immediately after one of those may be under-counted and remains part of the
  autonomous agent review.
- **Subject.** The conservative subject check permits an article and
  first-letter case carve-out; complex grammatical heads and tense still need
  agent judgment.
- **Hedge candidate.** `item7/hedge-candidate` flags a frequency hedge
  (usually, often, typically and the rest of item 19's list) in the
  description. It is advisory: the caveat review decides whether the plain
  claim holds for the ordinary case.

#### `item19`

- **Structure.** Flashcard section and card structure, with a blank line
  after the `---` separator and the heading.
- **Separator.** `??`, or the user's `!!`.
- **Line 1.** Its capitalization, single sentence, terminal period, markup and
  normalized answer leak.
- **Card set.** The card set holds one definition card per entry; every
  further card is an extra card to remove.
- **Lines 1 and 3.** Plain line 3, and no `::` or `:::` on card line 1 or 3
  outside a backtick span, which the plugin reads as a card of its own.
- **Primary answer.** The canonical title's plain form or base term plus any
  opener-established, alias-bound
  [counterpart](../../wiki-build/references/flashcards-and-emphasis.md#line-3-the-answer).
  With several cards, when none carries it and no single card nearly does, one
  finding asks to rewrite the first card into the definition card, keeping its
  attachments, and remove the rest.
- **Discipline roots.** A discipline root (its slug is the enum value its sole
  tag names) needs no card, with or without an empty section; a card it keeps
  gets every per-card check.
- **Attachments.** The shared parser hides recognized scheduling and block-ID
  attachments from this read-only view, never rewriting them. A block that is
  not a [card](../../wiki-build/references/flashcards-and-emphasis.md#card-shape),
  such as schedule state a blank line separates from the card or the user's
  own text, is never counted or removed: its own finding says to preserve and
  report it. When it, or content after a card's line 3, holds
  [card syntax](../../wiki-build/references/flashcards-and-emphasis.md#card-set),
  the finding instead names the marker and asks to remove that content as an
  extra card.
- **Extra cards.** Once the kept card is identified (the primary card, else,
  with none, the first card, which the no-primary finding rewrites), every
  per-card finding on another card, card line 1's `item12` findings included,
  starts `extra card N (remove this extra card; it needs no other repair)`:
  the card's removal resolves it, except that content after its line 3 that is
  not a recognized attachment stays and keeps its own finding.
- **Agent checks.** On the primary card, the executing agent checks semantic
  reconstruction, missing mathematical operations, off-rule line-1 math and an
  alias pair the opener should have bound.

## Deterministic scanner and autonomous semantic pass

The scanner mechanizes deterministic conditions and emits detections;
[QC finding actions](qc-items.md#finding-actions) owns repair permission and
the full per-item rule. The output contract and item-key table above are its
complete mechanical coverage. The executing agent completes every other check
in [QC items](qc-items.md) (semantic type and home, prose, equation value and
notation, alias identity, card clarity, link closeness, hierarchy shape, and
all source-dependent facts) automatically in the same run, and applies the
resulting repairs. That includes Task 1b's source-backed and cross-entry
repairs: duplicated explanations, conflicting claims, notation across sibling
entries, synonym-duplicate entries (merges), entries that fail the atomicity
test (splits), cross-domain titles, discipline-root form and missing entries.
No user or other human must review the notes or sign off for an ordinary run
to complete.

## Before you call a finding a false positive

Several checks are deliberately loose or noisy; the reasons are code comments in `scripts/scan_vault.py` and, for the per-entry floors shared with wiki-build's `lint_entry.py` (items 5, 6, 13, 14, 16 and 18, item 7's description subject, item 9's acronym expansion and list indentation, item 17's single-word alias hint, and item 19's card set, line-3 primary answer, primary-card choice and Spaced Repetition markers), in the plugin's `shared/scripts/entry_checks.py`. Read the comment before tightening a check or overriding a flag wholesale. The **item-18 display-label subset/superset test** must keep accepting the cross-domain bare-term links wiki-build mandates; never "fix" such a finding by adding the bare term as an alias, which creates the silent collision wiki-build prevents. The **item-16b bullet term-anchor pattern** must keep accepting wiki-build's canonical definition bullet (`- **True positives** (TP) — …`). `item12/remote-image` is report-only under [QC finding actions](qc-items.md#finding-actions) because the ordinary item-12 repair would destroy an embed wiki-build mandates; never re-file it as fixable. A check that fires often on **real** issues is working; only a genuine, recurring **false** positive justifies a narrowing proposal under the [proposal process](backlogs.md#proposal-scope).
