# Edge cases

> **When to read this:** Read this when any one of these is true — each is checkable before you write the entry, from a command, a script's output, or a fact about the request:
>
> - the request asks to rename, split, or merge existing entries — i.e. refactoring;
> - `find_collisions.py` returns `adjudicate` on probe (c), (e) or (f) for two candidates that are genuinely different techniques (the same-surface-form case — the section's own detection signal includes plural/singular pairs, which fire probe (c));
> - an entry keeps two or more equivalent equation forms of one quantity.

---

- **Wiki refactoring is out of scope for this skill** — partitioning the current source into atomic candidates *before creation* is normal extraction; splitting a pre-existing file is refactoring. A new source correcting one existing entry is an ordinary builder merge. A correction using only that entry's already-cited sources uses wiki-lint's [source-backed correction mode](../../wiki-lint/references/source-backed-corrections.md). wiki-build does not rename existing slugs and update every wikilink that points at them, redistribute a mixed entry into multiple files after the fact, or merge two existing entries into one. Route those structural operations to wiki-lint's refactor mode, which inventories the affected vault-wide reference surfaces before writing. Determinate `type:` corrections under [item 6's API-surface rule](api-surface.md#the-author-test-apply-during-the-review-pass) remain ordinary QC. **The orphan-link audit (step 7) is not a refactoring exception** — it repairs body/Related links in this run's created or merged entries, using the normal gates for any missed entry. It does not authorize renaming, splitting, or merging pre-existing files, redistributing their earlier content, or editing unrelated entries.

## Same-surface-form, different-technique

**Same-surface-form, different-technique.** Distinct from cross-*domain* ambiguity (which is across disciplines), this is two techniques **inside the same discipline** that the field happens to refer to with nearly identical surface forms. Example from the corpus: `Weight tying` (the language-model technique that reuses an embedding matrix as the output-layer weights; Press & Wolf 2016) and `Tying weights` (the autoencoder technique that reuses the transposed encoder weights in the symmetric decoder) — two different techniques, two different papers, two different sub-fields, but the noun phrase someone uses for either reads as a near-paraphrase of the other. When this pattern is detected:

- **Both entries take qualified titles** so the slugs are distinguishable. Prefer the natural compound form: `Embedding–output weight tying` → `embedding-output-weight-tying.md` and `Autoencoder weight tying` → `autoencoder-weight-tying.md`. A descriptive parenthetical works too where no compound reads well — `Weight tying (language model embedding sharing)` → `weight-tying-language-model-embedding-sharing.md` — but note that the slug derives from the **full** title including the parenthetical, so a long parenthetical buys a long filename. What is *not* available is abbreviating the parenthetical to keep the slug short (`weight-tying-lm.md`): the slug must re-derive from `title:` exactly, or item 5's mechanical check fails and every later collision probe looks in the wrong place. The rule is otherwise the same as cross-domain: never claim a bare ambiguous form for one sense.
- **Qualified titles do the disambiguating.** Do not add a sentence whose only purpose is to say the entry is distinct from its namesake. Link the other entry in body prose only where the source substantively relates the two techniques, under [link-worthiness](writing.md#what-earns-a-wikilink), with a display label that the target's title or aliases claim, never the bare shared phrase. Once both exist, each lists the other in its Related footer; for a counterpart this run does not write, report the missing reciprocal item under *Notes for the user*.
- **Surface-form aliases are forbidden across the two.** Neither entry lists `tied-weights` (or any other form that resolves naturally to either technique) as an alias — that would re-create the collision the qualified titles were introduced to prevent. The Quality Checklist's alias-collision check (item 18) catches this.

The detection signal during a run: when two candidate entities emerge from different sources or different sections of one source with titles that differ only by word-order permutation, plural/singular, or noun/verb form, and the body text would land on the *same slug* under the slug rule, that's the moment to apply the qualified-titles rule above — even if only one of the two is being created in this run. The second is *not* created (no placeholder files): qualify the title of the one you are writing, and record the counterpart's reserved qualified title in *Notes for the user*, so a future source creates it at the right slug.

## Multi-form equations

**Multi-form equations split across lines, aligned at `=`.** When a display keeps two or more equivalent forms of the same quantity, break it across lines using `\\` and align the `=` signs with `&=`, wrapped in a `\begin{aligned}...\end{aligned}` environment inside the `$$...$$` delimiters. The `aligned` environment is required — bare `&=` and `\\` outside an alignment environment are invalid LaTeX and will fail to render. The pattern:

```latex
$$
\begin{aligned}
F_1 &= 2 \cdot \frac{\text{precision} \cdot \text{recall}}{\text{precision} + \text{recall}} \\
    &= \frac{\text{TP}}{\text{TP} + \frac{\text{FN} + \text{FP}}{2}}
\end{aligned}
$$
```

This is a layout rule, not an inclusion rule. Keep a form only when it passes the [explanatory-value test](equations.md#1-coverage--explanatory-value-before-notation), as the count form above does by showing which confusion-matrix cells F1 ignores; do not transcribe rearrangements or derivation steps merely because the source prints them. A single-form equation keeps its equation content on one line inside a display block whose opening and closing `$$` delimiters each occupy their own line (`references/equations.md` §2), and does **not** use `aligned`.
