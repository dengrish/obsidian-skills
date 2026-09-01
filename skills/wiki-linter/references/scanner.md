# The scanner — CLI, output contract, and what it does not check

Read this when a scan exits non-zero, a JSON field/finding is unfamiliar, or an `item16`/`item18` result needs interpretation. Those checks have intentional allowances described under [Before you call a finding a false positive](#before-you-call-a-finding-a-false-positive). Run the helper at [Step 0](../SKILL.md#step-0--inventory-the-vault); use [QC actions](qc-items.md#finding-actions) to decide what may be changed.

Contents: [CLI](#cli) · [Output contract](#output-contract) · [Item keys](#item-keys-in-problems) · [Coverage limits](#floor-not-ceiling).

The scanner is `scripts/scan_vault.py`, a read-only stdlib Python helper. Its JSON describes detections, not permission to edit the vault.

## CLI

```
python3 scripts/scan_vault.py WIKI [--images DIR] [--out FILE] [--indent N]
```

- `WIKI` — the vault's **`Wiki/` folder**, not the vault root. MOCs (`*-moc.md`) and the three suggestion logs (`*-suggestions.md`) live in the root, which is why they are never linted and never listed inside a MOC: the scanner never walks them.
- `--images DIR` — the vault's flat **`Sources/Images/`** folder. With it, every `![[…png]]` embed in every entry is checked to name a file that is really there, emitted as `item12/missing-image`. **Pass it on every real run.** `CONVENTIONS.md` §1 makes this skill that folder's embed validator and nothing else in the plugin walks `Wiki/`, so without the argument that check silently does not run at all and an entry embedding a figure that is not on disk — the state §1a's rename hazard leaves behind — scans clean. It also emits report-only `image_folder_findings` for nested files/directories and recognizable staging residue; the intentional `.figure-manifest.tsv` and `.figure-review.txt` sidecars and `.DS_Store` are quiet. Matched on the **basename**, case- and normalization-folded (Obsidian resolves an embed by basename, and the documented vault's volume is insensitive to both), so a path-qualified `![[Sources/Images/X.png]]`, a case variant, and a legacy nested file can still resolve even while the nested path is reported. Embeds inside fenced code are skipped: a listing showing embed syntax is not an embed. Folder findings never authorize moving or deleting a file.
- `--out FILE` — write the JSON to `FILE` instead of stdout. Use this on any real vault and read the file in slices (filter by `item`, by slug, by key) rather than pulling the whole object into context.
- `--indent N` — JSON indent, default `2`; `--indent 0` emits one compact line.
- Exit status `2` with a usage error if `WIKI` is not a directory, or if `--images` is given and is not a directory. The second guard is deliberate: a mistyped image folder that read as "empty" would report **every** embed in the vault as naming a missing file, and nothing in the output would distinguish that from a genuinely broken vault. Every other failure is a genuine crash worth reporting as execution friction (SKILL.md, *Closing the loop*).

The scanner **never writes to the vault.** It reads `Wiki/*.md` and prints; every fix, MOC, `parents:` value, and log append is the model's own edit.

## Output contract

One JSON object with these keys.

| key | type | contents |
| --- | --- | --- |
| `run_timestamp` | string | `YYYY-MM-DD HH:MM` at scan time. This is the stamp for the suggestion-log dated blocks — use it, do not re-derive a time. |
| `wiki_path` | string | absolute path actually scanned (confirms an overridden path took effect) |
| `inventory` | object | `entries`, `full`, `stubs` (counts) and `full_slugs`, `stub_slugs` (sorted slug lists). A slug is the filename without `.md`. |
| `discipline_tags` | object | valid enum slug → `{"full": N, "stub": N}`. The keys are the disciplines **in use** — exactly the MOCs Task 3 builds (a discipline needs ≥1 **non-stub** entry, so a key whose `full` is `0` gets no MOC). |
| `off_enum_tags` | object | malformed / off-enum tag slug → the entries carrying it. Every one of these is an item-8 finding too; this key groups them by bad slug so a vault-wide pattern is visible at a glance. |
| `untagged_full` | array | full entries whose `tags:` key is present but empty. **Not a violation** — they are *unplaced*: no MOC, no `parents:`. |
| `problems` | array | `{"slug", "item", "message"}`, sorted. The deterministic violations. See *Item keys* below. |
| `problem_tally` | array | per item: `{"item", "entries", "pct_of_full", "issues"}`, ranked by entries affected. `pct_of_full` is the share of **full** entries touched — the recurrence evidence a wiki-builder proposal cites. |
| `collision_candidates` | array | `{"a", "b", "probe", "detail"}` — two slugs the item-5 probes matched. `probe` ∈ `exact`, `plural`, `hyphenation`, `word-order`, `word-order-singular`, `µ-variant`, `stem-morphology`; `detail` is the two colliding identifiers. `word-order-singular` sorts the tokens *after* singularising each one, which is what catches `weight-tying` against `tying-weights` — a pair a raw token sort misses on `weights` ≠ `weight`. It has to be here because wiki-builder runs the same two-key probe on every candidate (`wiki-builder/SKILL.md`, step 3 probe (e)) and CONVENTIONS §9 makes whole-vault dedup detection this skill's alone: a pair already sitting in the vault is seen by nothing else. `stem-morphology` is create-time probe (f), using the shared light-stem key, and is emitted only when an earlier, more specific probe has not already covered the pair. Unordered pairs are de-duplicated per probe. **Review only — never merged.** wiki-builder's create-time probe (g), token-superset, is deliberately **not** mirrored in this vault-wide sweep — qualified-vs-base pairs (`feature-machine-learning` beside `machine-learning`) are exactly what the disambiguation rules produce on purpose, so a whole-vault pass would flood on legitimate pairs; its absence from this probe list is by design (`wiki-builder/SKILL.md`, step 3). |
| `rename_candidates` | array | `{"slug", "new_slug", "inbound_links", "target_exists"}` — entries whose filename ≠ `slug(title)`. `inbound_links` is how many wikilinks a rename would have to rewrite; `target_exists: true` means the destination is already taken — either an existing file **(whether or not it parsed as an entry: a file with no frontmatter is absent from `inventory` and still occupies its name, and the approved `mv` would destroy it)**, **or a second candidate in this same list proposing the same `new_slug`** — so this is a likely duplicate/disambiguation and must **not** be renamed into (applying both of a colliding pair in sequence would have the second silently overwrite the first). `new_slug` is never empty: a title that reduces to the empty slug (CJK, all-symbol) is reported as an `item5` problem instead, because renaming to it would produce a file literally called `.md`. **Propose for approval — never auto-applied.** |
| `backfill_candidates` | array | `{"slug", "target", "surface", "bare_noun_alias"}` — a bare-text mention of `target`'s title/alias (or its plural) found in `slug`'s prose. Existing links, embeds, ambiguous title/alias surfaces, duplicate-basename destinations, targets already linked in that entry, and designated common-noun surfaces/destinations are excluded; stubs are not scanned. Other single lowercase aliases of qualified destinations remain candidates and carry `bare_noun_alias: true`; batch-review them under the closeness bar rather than treating the flag as an automatic decision. **Three line kinds are masked out** because an unlinkable first occurrence would hide a linkable one below it: whole-line italic captions, Markdown table rows, and fenced code blocks. The plural form inflects the title's head token, so irregular forms such as `Confusion matrices` and `Hypotheses` are matched. |
| `image_folder_findings` | array | `{"path", "kind", "message"}` for a nested directory, nested file, or recognizable temporary/staging artifact found under the supplied `--images` directory. The flat-folder and publish-only-finished-files rules come from `CONVENTIONS.md` §8. These are folder-level, report-only observations kept outside `problems`, so they do not inflate entry tallies or authorize moving/deleting user files. The two PDF sidecars and `.DS_Store` are omitted. Empty when `--images` is not supplied or the folder conforms. |
| `hierarchy_diagnostic` | object | `full_entries`; `self_parented` (slugs whose existing `parents:` points at themselves); `parent_cycles` (cycles of length ≥2, each listed once and rotated to start at its alphabetically first slug); and `per_discipline`: `{"discipline", "self_parent", "full", "check_rooting"}` for disciplines with at least one self-parent. `check_rooting` becomes true at the first self-parent. These values describe the **previously written state** and never authorize edits. Under MOC rooting, every listed self-parent or cycle is stale, but Task 3 rewrites it only inside an authorized transitive closure. After a narrowed run, global lists may still contain skipped disciplines; after a completed full-vault Task 3 pass, `self_parented`, `parent_cycles`, and `per_discipline` are empty. |

### Item keys in `problems`

`item1` … `item19` map to the builder's [numbered checklist](../../wiki-builder/SKILL.md#quality-checklist). There is no `item20`; existing `importance:` is preserved and not flagged. The complete repair/report routing is in [QC finding actions](qc-items.md#finding-actions), rather than a second action list here.

| Key | Detected condition |
| --- | --- |
| `item2/type-enum` | `type:` is blank, non-scalar, or outside the 15 canonical values. This detects spelling, not the semantic choice of type. |
| `item2/read-missing` | No `read:` key. |
| `item2/read-null` | Present but valueless: bare `read:`, null, or `~`. |
| `item2/read-type` | A recognizable boolean answer in another spelling, such as quoted `"false"`, `yes`/`no`, or `0`/`1`. |
| `item2/read-unknown` | No recognizable boolean meaning, including arbitrary strings and lists. |
| `item2/parents-null` | YAML null where the empty parents list belongs. |
| `item2/obsidian-key` | A valid Obsidian-owned appearance/publish key, not a schema violation. |
| `item3/user-action` | `created` is later than `updated`; ordinary `item3` also detects date format/calendar problems. |
| `item4/source-identity` | PDF and Markdown references share a normalized stem; this does not prove they are one source. |
| `item7` | Description missing, longer than 110 characters, non-plain-text, missing its initial capital where the canonical title does not start lowercase, or missing its final period. Entity-as-subject and tense still need judgment. |
| `item10/dangling` | An actual entry-link target is absent after resolution checks. |
| `item10/case` | A target resolves only after case or Unicode-normalization matching. |
| `item10/alias` | A target resolves to another entry's unambiguous alias; a filename match takes precedence. |
| `item10/ambiguous` | Multiple files own the basename or multiple entries claim the alias. |
| `item10/unparsed` | The target file exists but did not parse as an entry; its own finding is `item0` or `item1`. |
| `item10/dup` | The same resolved entry appears more than once in actual body prose, excluding code/listings. Path/`.md`/case/Unicode spellings and an unambiguous alias collapse to their canonical owner when the inventory identifies one owner; a file outranks an alias. If a basename or alias has several owners, distinct qualified paths remain distinct and bare ambiguous occurrences do not receive a removal finding. |
| `item12/remote-image` | A valid remote Markdown image URL, reported as a possible localization opportunity. |
| `item12/missing-image` | An image embed has no file in the supplied `--images` directory; without that argument the check did not run. |
| `item18` | Alias duplication/collision, noncanonical slug form, display-label markup, or a label with no plausible target surface. Same-entity alias meaning remains judgment. |
| `item19` | Flashcard section/card structure, cue, line-1 markup/leak, line-3 plainness, exact-one-card rule, or a primary line 3 that departs from the exact canonical title/base term and any acronym/full-form counterpart established in both opener and aliases. The scanner does not infer that an alias pair should have been bound in the opener; the model checks that omission and definition quality. |
| `item0` | A file could not be read (encoding, symlink, permissions); it is absent from inventory/worklists and the scan continues. |
| `stub` | A legacy stub carries a forbidden Related footer. |
| `stub-one-sentence-body` | A legacy stub's body is not exactly one prose sentence. Report and preserve; the extra content may be substantive or user-authored. |
| `stub-no-images` | A legacy stub embeds an image. Report and preserve; deleting content or promoting the stub requires a source-backed request. |

A case variant, alias, ambiguous owner, or unparsed file is not a genuinely missing target. Body code samples and embeds are not entry links. Resolve findings with the linked action guide; never infer that an `itemN` is automatically fixable.

## Floor, not ceiling

The scanner is a **floor, not the whole audit**. It mechanizes deterministic
conditions and emits detections; [QC finding actions](qc-items.md#finding-actions)
owns repair permission and the full per-item rule. Its mechanical coverage is:

- **Items 1–2:** frontmatter position/fences and parseable lines; mandatory-key
  presence/order/quoting; canonical `type:` enum; duplicate/unexpected keys;
  `read:` state-shape variants; null `parents:`; and report-only Obsidian keys.
- **Items 3–8:** date spelling, calendar validity, and ordering; source-reference
  form and same-stem identity candidates; filename/slug and collision probes;
  non-`Software` API/code patterns; description presence, length, plainness,
  capitalization, and terminal period; and tag form, enum, aliases, casing,
  duplicates, and stub cardinality.
- **Items 9–14 and 16:** opener and legacy-stub structure; actual entry-link
  resolution and duplicate targets with listings masked; Related-footer link
  form; image/table caption form, remote-image observation, and optional local
  image existence; stray frontmatter-key merge scars; source-meta phrases; and
  opener/emphasis formatting.
- **Items 18–19:** alias slug form, within/cross-entry collisions, and the
  display-label mechanical floor; plus Flashcards section/card structure, cue,
  line-1 markup and answer leaks, line-3 plainness, exact canonical/base term,
  any opener-and-alias-established counterpart, and exact-one-card count. The
  model still decides whether an alias pair should have been bound in the
  opener and therefore made a required counterpart.
- **Worklists and diagnostics:** collision/rename candidates, eligible backfill
  surfaces, inventory/tag counts, and existing self-parent/cycle diagnostics.

The model still reads the entries for semantic type and disciplinary-home calls,
paragraph unity/progression, list shape, sentence clarity, atomic scope,
stacked-body meaning, equation coverage/form/notation, introduced-alias
completeness and same-entity meaning, flashcard bidirectional clarity, link
closeness, and hierarchy shape. The scanner
also cannot establish source-dependent facts: citation-page correctness, figure
selection, exhibit/source fidelity, or example support. Those boundaries are
spelled out once in [QC items](qc-items.md), rather than repeated here as a
second repair standard.

## Before you call a finding a false positive

Several checks are deliberately loose or deliberately noisy, and the reasons are recorded as comments in `scripts/scan_vault.py` next to the code. Read the comment before "tightening" anything or overriding a flag wholesale — two of them exist because an earlier stricter version produced false positives at scale, and each re-breaks something wiki-builder mandates if re-tightened: the **item-18 display-label subset/superset test** (an exact-match version false-flagged the cross-domain bare-term links wiki-builder mandates — 108 of 110 findings on a real run — and the tempting "fix", adding the bare term as an alias, is the silent collision wiki-builder exists to prevent) and the **item-16b bullet term-anchor pattern** (a stricter version flagged wiki-builder's own canonical definition bullet, `- **True positives** (TP) — …`, which it then re-emitted every run). A third is the report-only `item12/remote-image` key, which was an ordinary `item12` violation until it turned out to prescribe destroying an embed wiki-builder mandates — don't re-file it as a fixable finding. A check that fires often on **real** issues is the check working; only a genuine, recurring **false** positive is grounds for a proposal to narrow it (SKILL.md, *Closing the loop*).

**These two checks are why this file has a mechanical trigger.** `item16` and `item18` are the only findings whose looseness is deliberate and documented, so they are the only ones with a recorded reason to be second-guessed — and both are greppable in the scan JSON. The third loose case, `item12/remote-image`, needs no lookup: it is fully specified in the Step 0 finding taxonomy and in item 12 of `references/qc-items.md`, and it is report-only either way.
