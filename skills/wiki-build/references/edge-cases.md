# Edge cases

> **When to read this:** Read this when any one of these is true — each is checkable before you write the entry, from a command, a script's output, or a fact about the request:
>
> - the run was pointed at a folder, not a single file (`ls '<source-folder>'` returns more than one source);
> - a candidate title contains a non-ASCII character (`python3 -c 'import sys; print(any(ord(c) > 126 for c in sys.argv[1]))' '<title>'` — the title as its own argv element, single-quoted, per `CONVENTIONS.md` §1b);
> - the entity appears only in a figure caption or table;
> - the user says they hand-edited an entry since the last run;
> - the request asks to rename, split, or merge existing entries — i.e. refactoring;
> - `find_collisions.py` returns `adjudicate` on probe (c), (e) or (f) for two candidates that are genuinely different techniques (the same-surface-form case — the section's own detection signal includes plural/singular pairs, which fire probe (c));
> - the source presents one quantity in two or more equivalent equation forms.

---

- **Multiple sources processed in one run** — if the user points the skill at a folder of sources rather than a single file, process them sequentially, one at a time, so that an entity introduced by source A and elaborated by source B gets a private draft-then-merge sequence rather than two simultaneous creates. **Workflow execution:** steps 1–6 run per source (read → extract → resolve → draft → merge → interlink) against the accumulated staged working set. Step 7 (Review, publish when authorized, and report) runs **once at the end of the run**, covering all entries drafted, promoted, or merged across all sources, with a single consolidated report — not one report per source. Source order within the folder should be deterministic (alphabetical by filename) so reruns are reproducible. Step 2's filters remain per-source in an ordinary folder run: thin mentions do not silently combine. If the union may be substantive, report the entity and contributing files as a deferred cross-source candidate. A later request that explicitly names both uses [candidate-specific multi-source synthesis](multi-source-synthesis.md), which tests same-entity identity, combined substance, and each contribution's durability without reopening unrelated entities.
- **Ambiguous entity name** — see the "Cross-domain term disambiguation" section. The short version: qualify proactively (`Information entropy`, `Transformer architecture`); never claim the bare slug for a single sense.
- **The source uses non-English terms or names with accents** — the **title** keeps the source's exact casing, spelling, and diacritics (e.g., `title: "Aurélien Géron"`, `title: "Schrödinger equation"`); the **filename** is the ASCII-transliterated slug (`aurelien-geron.md`, `schrodinger-equation.md`) per the slug rule; **aliases** can include any Anglicized variant the source occasionally uses.
- **Entity is only mentioned in a figure caption or table** — apply the substance test strictly. If the caption explains the entity, that counts. If it just labels a column, it does not. **Page anchor for figure-caption-only entities:** point at the physical PDF page where the figure (and its caption) appears, not the page where the figure is referenced in the prose — when the user clicks the anchor in Obsidian, they should land on the figure itself.
- **Hand-edited entries remain merge input.** Read the current body, preserve
  every substantive claim and deliberate structure, and integrate the active
  source around that content under the ordinary Integration principle. A hand
  edit does not need a protected-region marker or a second source note to
  survive. If it conflicts with the active or cited sources, use *Conflict
  handling*; when the available evidence cannot settle the disagreement,
  preserve the edit and report the unresolved conflict. A source-no-op merge
  leaves conforming prose byte-for-byte unchanged, while targeted step-7 QC may
  still repair a current-rule defect. The exact snapshot guard in the main
  workflow separately protects an editor save that lands while the merge is in
  progress: re-read and rebuild rather than publishing the stale draft.
- **Wiki refactoring is out of scope for this skill** — partitioning the current source into atomic candidates *before creation* is normal extraction; splitting a pre-existing file is refactoring. A new source correcting one existing entry is an ordinary builder merge. A correction using only that entry's already-cited sources uses wiki-lint's [source-backed correction mode](../../wiki-lint/references/source-backed-corrections.md). wiki-build does not rename existing slugs and update every wikilink that points at them, redistribute a mixed entry into multiple files after the fact, or merge two existing entries into one. Route those structural operations to wiki-lint's refactor mode, which inventories the affected vault-wide reference surfaces before writing. Determinate `type:` corrections under [item 6's API-surface rule](api-surface.md#the-author-test-apply-during-the-review-pass) remain ordinary QC. **The orphan-link audit (step 7) is not a refactoring exception** — it repairs body/Related links in this run's created or merged entries, using the normal gates for any missed full entry. It does not authorize renaming, splitting, or merging pre-existing files, redistributing their earlier content, or editing unrelated entries.

## Same-surface-form, different-technique

**Same-surface-form, different-technique.** Distinct from cross-*domain* ambiguity (which is across disciplines), this is two techniques **inside the same discipline** that the field happens to refer to with nearly identical surface forms. Example from the corpus: `Weight tying` (the language-model technique that reuses an embedding matrix as the output-layer weights; Press & Wolf 2016) and `Tying weights` (the autoencoder technique that reuses the transposed encoder weights in the symmetric decoder) — two different techniques, two different papers, two different sub-fields, but the noun phrase someone uses for either reads as a near-paraphrase of the other. When this pattern is detected:

- **Both entries take qualified titles** so the slugs are distinguishable. Prefer the natural compound form: `Embedding–output weight tying` → `embedding-output-weight-tying.md` and `Autoencoder weight tying` → `autoencoder-weight-tying.md`. A descriptive parenthetical works too where no compound reads well — `Weight tying (language model embedding sharing)` → `weight-tying-language-model-embedding-sharing.md` — but note that the slug derives from the **full** title including the parenthetical, so a long parenthetical buys a long filename. What is *not* available is abbreviating the parenthetical to keep the slug short (`weight-tying-lm.md`): the slug must re-derive from `title:` exactly, or item 5's mechanical check fails and every later collision probe looks in the wrong place. The rule is otherwise the same as cross-domain: never claim a bare ambiguous form for one sense.
- **The two entries wikilink to each other in body prose** with a one-clause acknowledgement of the homonym: *"Not to be confused with [[autoencoder-weight-tying|weight tying]] in autoencoders, where..."* — placed near the top of each entry, so a reader who lands on the wrong one immediately sees the pointer. (This applies when both entries exist; while only one is on disk, the acknowledgement stays plain text, and the link is backfilled on a later maintenance pass once the counterpart is created.)
- **Surface-form aliases are forbidden across the two.** Neither entry lists `tied-weights` (or any other form that resolves naturally to either technique) as an alias — that would re-create the collision the qualified titles were introduced to prevent. The Quality Checklist's alias-collision check (item 18) catches this.

The detection signal during a run: when two candidate entities emerge from different sources or different sections of one source with titles that differ only by word-order permutation, plural/singular, or noun/verb form, and the body text would land on the *same slug* under the slug rule, that's the moment to apply the qualified-titles rule above — even if only one of the two is being created in this run. The second is *not* created (no placeholder files): qualify the title of the one you are writing, and record the counterpart's reserved qualified title in *Notes for the user*, so a future source creates it at the right slug.

## Multi-form equations

**Multi-form equations split across lines, aligned at `=`.** When a display equation expresses the same quantity in two or more equivalent forms (e.g., a definition that has a closed form, a simplified form, and a count-based form), break it across lines using `\\` and align the `=` signs with `&=`, wrapped in a `\begin{aligned}...\end{aligned}` environment inside the `$$...$$` delimiters. The `aligned` environment is required — bare `&=` and `\\` outside an alignment environment are invalid LaTeX and will fail to render. The pattern:

```latex
$$
\begin{aligned}
F_1 &= \frac{2}{\frac{1}{\text{precision}} + \frac{1}{\text{recall}}} \\
    &= 2 \cdot \frac{\text{precision} \cdot \text{recall}}{\text{precision} + \text{recall}} \\
    &= \frac{TP}{TP + \frac{FN + FP}{2}}
\end{aligned}
$$
```

This is the default form for any equation with multiple equivalent expressions, derivation steps, or simplifications. A single-form equation keeps its equation content on one line inside a display block whose opening and closing `$$` delimiters each occupy their own line (`references/equations.md` §2), and does **not** use `aligned`. The rule is: one line per *form*, not one form per equation — if the source presents three equivalent expressions of the same quantity, the entry shows all three, vertically aligned inside `\begin{aligned}...\end{aligned}`.

This section owns only the multi-form layout. Literal-`$` escaping and numbers
in prose stay in [writing.md](writing.md#prose-principles); whether an equation
is written at all (including from a calculation the source only describes in
words), the display-vs-inline call, the vault notation standard, and the
normalization of off-standard source equations are governed by
[equations.md](equations.md).
