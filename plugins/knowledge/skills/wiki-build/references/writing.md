# Writing an entry — fields, body, wikilinks

> **When to read this:** before recording candidate titles (wiki-build step 2): its naming and disambiguation rules fix the titles the collision check probes, and its field, body, and link rules apply when drafting. Shared [CONVENTIONS §2](../../../shared/CONVENTIONS.md#2-frontmatter-schemas) owns schema and encoding, and [§6](../../../shared/CONVENTIONS.md#6-wikilink-forms) owns wikilink forms; this guide owns Wiki field choices, body prose, link-worthiness, and display labels. [Merge logic](merge.md) owns updates to existing entries. Read the separate [flashcard and emphasis guide](flashcards-and-emphasis.md) for card and markup rules; conditional merge, equation, and media procedures are linked at their action points in the [workflow](../SKILL.md#workflow).

Contents: [Fields](#1-frontmatter-fields) · [Body](#2-the-body) · [Links and naming](#3-wikilinks-and-naming) · [Complete example](#complete-entry-example).

---

## 1. Frontmatter fields

### title

Use the canonical entity name in natural casing, keeping the source's spelling and diacritics (`LambdaRank`, `MNIST`, `ROC curve`, `Yann LeCun`, `Aurélien Géron`, `Cross-validation`). Derive the filename from the decoded full title with `shared/scripts/slugify.py`, never an improvised pipeline; only the filename is transliterated (`aurelien-geron.md`). Qualify cross-domain terms under [§3](#cross-domain-term-disambiguation).

Plain text is the norm. A canonical mathematical name may use inline LaTeX for a load-bearing symbol, such as `"$k$-nearest neighbors"` or `"$A^{*}$ search"`; never display math or other Markdown in YAML. Follow the [quoting policy](#quoting-policy): double each LaTeX backslash in YAML source, so `"$\\chi^2$ test"` decodes to `"$\chi^2$ test"`. A single source backslash is invalid YAML.

**Acronym-vs-full-form coherence rule.** Pick one canonical running form for the description subject and body opener. Normally it is the title; parenthetical-disambiguated titles use their base term under [§3](#cross-domain-term-disambiguation). Introduce the commonly used counterpart in the opener and record it as an alias under prose principle 5(e)–(f). The filename still derives from the full title, not the acronym or base term chosen independently.

**Selection guideline.** Use the literature's frequent, distinctive form. BERT, MNIST, DBSCAN, LSTM, t-SNE, ReLU, RAG, LoRA, and GAN are acronym-titled; this explicit ruling overrides the textbook tiebreaker, including for LSTM and GAN. Otherwise a full form with substantive standalone textbook usage takes priority: `Principal component analysis` (`pca`), `Stochastic gradient descent` (`sgd`), `Markov decision process` (`mdp`), `Support vector machine` (`svm`). When both forms are common and the full form has textbook standing, default to the full form. When neither predominates and the expansion lacks that standing, default to the acronym, as with ILSVRC and DeiT.

**Task and artifact naming coherence.** Use established task/procedure names for procedures: *Masked language modeling*, *Replaced token detection*, *Next sentence prediction*. Use model-class/artifact names for their results. Title, description, and opener must identify the same kind of entity. Do not alias a task to its model, output, or classifier; a shorthand or acronym such as MLM qualifies only when its source-established sense is the same entity and collision checks pass.

### type

One of the fifteen enum values in [CONVENTIONS §2a](../../../shared/CONVENTIONS.md#2a-wiki-entry--wikimd) — no other values. The five that carry most of the classification difficulty are defined here; the remaining ten (`Device`, `Event`, `Standard`, `Gene/Protein`, `Organism`, `Chemical`, `Reaction`, `Place`, `Work`, `Quote`) are defined in `references/rare-types.md`.

- `Concept` — methods, algorithms, ideas, techniques, phenomena, **and named model architectures or specific pretrained models / research systems**. Examples: `LambdaRank`, `Photosynthesis`, `Backpropagation`, `Stochastic gradient descent`, `Random forests`, `BERT`, `ResNet`, `AlphaGo`, `AlphaFold`, `Stable Diffusion`, `CLIP`.
- `Person` — individual researchers, authors, historical figures (`Yann LeCun`, `Marie Curie`, `Rosalind Franklin`).
- `Organization` — companies, labs, institutions (`DeepMind`, `Anthropic`, `EMBL`).
- `Dataset` — named datasets and benchmarks (`ImageNet`, `MS MARCO`).
- `Software` — discrete software artifacts the user installs, deploys, runs, or interacts with through a software interface: libraries, frameworks, applications, programming languages, runtimes, operating systems, databases, IDEs, and notable deployed products. Examples: `scikit-learn`, `PyTorch`, `XGBoost`, `Jupyter`, `Obsidian`, `Python`, `ChatGPT`. The body covers the artifact's scope, design choices, and place in the broader landscape. It may name API elements only when they explain a cross-cutting interface or convention that is part of the artifact's design. Permission to name an identifier does not make per-algorithm class catalogs, parameter/default inventories, version-specific feature lists, or how-to recipes relevant. Those identifiers never get their own entries; the selective rule is in `references/api-surface.md`.

**Named ML model rule — the `Concept` / `Software` split.** A named model architecture (`BERT`, `ResNet`), a specific pretrained model (`GPT-3`), or a landmark research system (`AlphaGo`, `AlphaFold`) is a `Concept`, not a `Software`. The test is what the entity contributes: an algorithmic or architectural contribution that other entries cite, compare, or extend is `Concept`; a runnable artifact the user installs (`PyTorch`) or uses as a product (`ChatGPT`) is `Software`. AlphaGo is `Concept` even though it is also a program, because what other entries cite is the approach, not a runnable artifact. Both can coexist for one idea (`Gradient boosting` as `Concept`, `LightGBM` as `Software`); when genuinely torn, prefer `Concept`. Between `Software` and `Device`: software runs on a computer, hardware is touched (sequencer, microscope, GPU, lab instrument).

### aliases

An optional list of alternate names used by the source or directly introduced for the subject in its opener: spellings, abbreviations, and synonyms. Store each as a slug under [the shared alias contract](../../../shared/CONVENTIONS.md#4b-aliases-use-the-same-slug-rule). For `Recall (machine learning)`, for example: `aliases: ["true-positive-rate", "tpr"]`; the bare word *sensitivity* stays out because it is [cross-domain ambiguous](#cross-domain-term-disambiguation). Omit the key when no useful alias remains.

**An alias must name the same entity.** It cannot name a related, contrasting, narrower, broader, successor, or component entity. Keep grammatical role aligned: a *hard voting classifier* is an ensemble using the hard-voting rule, not an alias of `Hard voting`. Leave the rejected name out of `aliases:`; do not explain the rejection in the note. Mention or link the distinct entity only where the source substantively relates the two.

Before adding an alias, inspect the source and body's relationship to it. These are rejection grounds **when they describe the candidate's relationship to the entry's subject**:

- A variant/version or successor: “a variant of,” “a version of,” “extends,” “builds on,” “a refinement of,” or “based on” with substantive changes.
- A contrast or related technique: “the contrasting class,” “differs from,” “opposite,” “sibling approach,” or “similar to … but.”
- A component or role: “the components/parts/strategies of” or a separately identified part inside the entity.
- A special or general case: “a special case of,” “the general case of,” or “a particular instance of.”

DALL·E and DALL·E 2, Chain-of-thought and Tree-of-thoughts, and model-based and model-free reinforcement learning are distinct pairs. A separate equation, subsection, mechanism paragraph, image, or enumeration is a **prompt to inspect identity, not proof of difference**: the same entity can be explained under an alternate name. Reject the alias only when the meaning establishes a distinct subject.

**Complete the field against the body's own same-entity names** (checklist item 17): *also called/known as X*, a direct *(short for X)* expansion, the opener's acronym/full-form pair, and a directly bound scientific abbreviation such as `***Escherichia coli*** (*E. coli*)`. The body must establish the name for this subject; *dummy attributes* in a One-hot encoding entry names its output and does not qualify. `lint_entry.py` flags missing candidates for this semantic judgment.

Exclude redundant forms that slug-equal the filename or each other, including case/normalization and singular/plural equivalents. For same-surface-family aliases that still differ (`oob-evaluation`, `out-of-bag` for `out-of-bag-evaluation`), retain the literature's most distinctive form, usually the acronym. Also exclude the bare name of a [cross-domain-ambiguous term](#cross-domain-term-disambiguation), and an organism's ordinary common name when unsafe as a global alias. A directly bound organism common name may still be a display label under §3.

Check new aliases against every other entry's titles and aliases before publication. A cross-entry owner conflict blocks claiming the alias; report it in *Notes for the user* for disambiguation or a separately scoped refactor. Do not silently remove a pre-existing semantic-invalid alias or choose the first owner. When identity remains uncertain, leave the alias unclaimed; create a distinct entry only if it independently passes the normal identity and substance gates.

### sources

List the durable sources that contributed to the entry using [CONVENTIONS §7](../../../shared/CONVENTIONS.md#7-source-references). It owns literal filenames/extensions, quoting, page-anchor syntax, identity, deduplication, and representation replacement.

For a PDF, cite the **physical page where this entity is first defined or substantively introduced**, not a printed page number. Thus different entries can cite different pages of the same PDF; later discussion informs the prose without another anchor. An entity that appears only in a figure caption or table qualifies only when that exhibit explains it rather than merely labeling it; cite the physical page where the exhibit appears. Markdown sources have no page anchors.

An existing, uniquely resolved PDF and its provenance-confirmed summary are one source, cited as the PDF, never both. If a complete inventory proves the PDF missing, [source intake](source-intake.md#resolve-a-markdown-source) permits the summary as the Markdown source and requires reporting that fallback. A clipping remains independent even when an unrelated PDF shares its stem. Preserve unresolved references rather than inferring identity from a filename.

### created / updated

New entries set both bare `YYYY-MM-DD` fields to the run's local date. `created:` never changes. Existing entries advance `updated:` only for an actual change under [merge rules](merge.md#frontmatter-and-related-footer), including metadata/QC changes on source-no-ops. A byte-unchanged result preserves it. Review state uses its separate test below.

### description

One sentence of **at most 110 characters**, with the entity itself as grammatical subject in its canonical running form. Use the [base-term and mathematical plain-form rules](#cross-domain-term-disambiguation) for qualified or mathematical titles. A leading article is valid (`A cache line is …`, `The British East India Company was …`); a placeholder subject (`This method …`, `An algorithm for …`) or bare predicate (`Optimizes …`) is not.

Use present tense for extant entities and ongoing/recurring events, past tense for deceased people, defunct organizations, and completed historical events. Capitalize the first word unless the canonical subject begins lowercase (`k-fold cross-validation`, `t-SNE`, `scikit-learn`), and end with a period.

**Plain text only:** no LaTeX/dollar signs, links/images, emphasis, strikethrough, code, HTML/entities, tags, highlights, comments, footnotes, or block Markdown. Unicode such as `α`, `≤`, `×`, and `→` is fine, but spell ℓ-norms in words (`ell-one norm`, not `ℓ1 norm`). Paraphrase a formula as a definition: “Precision is the fraction of a classifier's positive predictions that are correct.” Preserve every defining operation; describing an Lp norm's sum of powers without its root defines a different quantity.

**Count before publication, for every drafted or revised description.** Use [step 4's description gate](../SKILL.md#4-create-new-entries), including descriptions created during missed-entity recovery or a merge. If too long, remove nonessential modifiers/parentheticals and redundant wording first. Preserve all conditions that change when the claim holds; if they cannot fit, choose a narrower accurate main claim and keep the qualified detail in the body. Never estimate the count by eye.

On merge, change a description only for a meaningfully more accurate, informative, or grammatically clear result, or a concrete defect such as vagueness, factual error, wrong subject, excess length, or formatting. Different phrasing alone is insufficient. [Source-no-op rules](merge.md#source-no-op-merges) distinguish defect repairs from new-content-driven rewriting.

### tags

Use exactly one quoted, `#`-prefixed discipline-enum value in a block list,
under [CONVENTIONS §3](../../../shared/CONVENTIONS.md#3-the-discipline-tag-enum).
Choose the entry's best disciplinary home; express other relationships through
prose and links. Use `"#misc"` only when no specific discipline fits.

```yaml
tags:
  - "#machine-learning"
```

The quotes are required because an unquoted `#` begins a YAML comment.
Tags are not wikilinks. Every active discipline has a corresponding Wiki root
entry; wiki-lint owns those roots, the MOCs, and parent placement. This skill
creates entries with `parents: []` and preserves parents on merge.

**Choose by the concept's meaning.** Predictive models, regression and
classification methods, fitting, losses, evaluation, and model components
belong to `#machine-learning`, including classical statistical models.
General descriptive statistics, sampling methods, and inference that does not
fit a predictive model (hypothesis tests, confidence intervals, ANOVA) belong
to `#statistics`; universal mathematical structures belong to `#mathematics`. A decision-tree
leaf belongs with decision trees, while a general data-structure entry may
belong to computer science. General computing tools such as NumPy and Jupyter
remain `#computer-science`. Do not add tags for every application or prerequisite.
Use [calibration](calibration.md) for unresolved boundary cases.

On merge, follow [tag reconciliation](merge.md#frontmatter-and-related-footer):
retain one supported home, repair clearly incorrect or multiple homes, and
report the old/new groups for wiki-lint's hierarchy refresh.

### parents

On creation write `parents: []`, never bare `parents:` (YAML null). Wiki-lint later populates the list from its hierarchy; this skill preserves existing parents on merge.

### read

Write bare `read: false` on creation. The user checks it after reading. Apply [CONVENTIONS §2c](../../../shared/CONVENTIONS.md#2c-read--the-users-review-checkbox) to its type and ownership; missing, null, or unknown existing state stays unchanged and is reported, never inferred. A known value resets only under the [unread-body-content test](merge.md#the-read-reset), independently of `updated:`. A recognizable misspelled boolean can be normalized without changing its meaning.

### Quoting policy

Apply [CONVENTIONS §2](../../../shared/CONVENTIONS.md#2-frontmatter-schemas): double-quote newly written title/description/alias strings and every source/tag/parent item; keep type, dates, and booleans bare. Preserve unchanged safe plain title/description/alias values rather than rewriting for quote style. Escape literal quotes and YAML backslashes, including the [mathematical-title case](#title).

---

## 2. The body

### Body structure

- **Scope, not size.** Write enough to give a reader a correct working understanding of **one entity**. There is no note-level sentence, paragraph, or word target, and length alone is neither a defect nor an exception to justify. Keep the mechanisms, essential conditions, and limitations a reader needs, and other inherent facets, even when they require several paragraphs. Remove repetition; source/tutorial scaffolding, application catalogs, and examples that do not serve the entry; implementation recipes; and passages whose real subject is a neighboring concept. If a draft feels long, audit its atomic scope and repetition; do not compress a definition or necessary qualification to hit a size target. Equations, images, tables, and captions still need to serve this entity, but they do not create a hidden length quota.

- **Headings.** Flat prose is the default when the explanation has one continuous flow. **Use ATX `##` headings when several genuine sub-aspects of the same entity need named treatment; note length alone does not decide.** This is the *only* way to introduce named sub-sections; Setext underlines and bolded paragraph-leads (`**Architecture.**`) are **forbidden as section headers** under the [bold and italic rules](flashcards-and-emphasis.md#5-bold-and-italic). The entry always opens with a prose paragraph stating the main claim; headings divide what follows. **Use `##` only** — wanting `###` under `##` prompts the atomicity test again, though inherent facets still stay in the same entry. Heading text is Sentence case (`## Algorithm and convergence`) and plain: no bold, no LaTeX, no wikilinks (entities named in a heading appear as bare words, wikilinked at their first occurrence in the prose). Headings help in a `BERT` entry (`## Encoder stack`, `## Input representation`, `## Output representations`); they don't help in a `Classification (machine learning)` entry split across `## Binary classification` / `## Multiclass classification` — those are separate entries.

- **The atomicity test.** Each note has one durable entity or concept as its subject, as defined by the naming, type, and same-entity rules; type-specific conceptual units remain intact. Partition source material into separate entries when each part has its own stable identity and enough support to explain what it is, how it works, or why it matters independently. Keep only the concise relationship needed for orientation in the original entry and link the notes to each other. Binary, multiclass, and multilabel classification therefore become their own entries once the source gives each substantive treatment; an umbrella `Classification (machine learning)` entry exists only when the source also explains that broader concept, not merely as an index page. **Do not split to make a note shorter.** Alternative names, properties, conditions, stages, mechanisms, and components that cannot stand alone are facets of the same entity; thin mentions remain plain text under the substance filter. For a pre-existing mixed entry encountered during a merge, create any independently supported new-source candidate normally, but do not redistribute or delete the old body without a separate refactoring request; report the proposed split instead (see *Wiki refactoring is out of scope* in [edge cases](edge-cases.md)).

- **Bullets vs prose.** Apply the atomicity test before turning named concepts into a list. Bullets are allowed when the remaining content is genuinely list-shaped: dependent variants, discrete components, or properties whose meaning is exhausted by their role in this entity. Source-supported standalone concepts become linked entries instead. **Don't use bullets** to break up expository or argumentative content that flows naturally as prose — the most common misuse, and it makes entries feel like fragmented notes rather than wiki articles. Quick test: if connecting the items with "and," "then," or "because" makes them read as one paragraph, use prose; if they're parallel items sharing a parent category, use bullets. **Mechanical detection of the most common failure shape — sequential steps bulleted as if parallel:** scan each list for sequencing markers (*"first"*, *"then"*, *"next"*, *"subsequently"*, *"finally"*, ordinal openings) or any bullet whose content depends on the prior bullet completing. Chained bullets convert to prose.

- **Markdown tables.** When the source presents data as a table and that form genuinely serves the entry (a comparison of methods across metrics, a parameter table, a small lookup), **recreate the table in Markdown**. Tables are identified while reading the source; they are not pre-extracted into `Sources/Images/` (only figures are). **Recreate, don't transcribe verbatim:** drop columns and rows that don't earn their place, rename headers to match the entry's terminology, simplify cells for clarity. **The cells that survive keep the source's numbers** — prose principle 7's example-data rule does not reach a recreated table, whose values are its content; see the carve-out stated there. **Tables are never embedded as images**, and **don't introduce a table** for content the source doesn't already present tabularly — that's prose or bullets. **Table cells allow LaTeX and markdown formatting** — `$O(n \log n)$`, `**bold**`, `*italic*`, and backtick code only where *Inline formatting* below allows it; wikilinks are not (see §3). **Placement** follows the image rule: inline next to the prose it illustrates, with an italic caption on the line immediately below. One motivating paragraph supports at most one exhibit total, so do not pair a table and an image with the same paragraph.

- **Images are selected for explanatory value**, under the [selection rule](media.md#selection). Place each selected image **immediately after the specific sentence or paragraph it illustrates**, not at the top of the entry or detached at the end. Do not expand the entry to accommodate an optional figure; [media placement](media.md#placement-and-embed-syntax) follows the prose's needs.

- **Inline formatting.** Backtick `` `code` `` for literal identifiers (class/function names, kwargs, module paths, command syntax) only in `Software` entries and only when the identifier is load-bearing under `references/api-surface.md`; the type is not a license for an API inventory. Non-`Software` entries carry zero API identifiers, and library *names* stay unbackticked, in plain prose or as a wikilink. A bare file extension (`.csv`, or a compound such as `.tar.gz` or `.nii.gz`) and a bracket special token (`[CLS]`) are the two backticked shapes allowed in any entry type. Bold and italic usage follows the [bold and italic rules](flashcards-and-emphasis.md#5-bold-and-italic) — mechanical, audit-friendly rules, not stylistic latitude. **LaTeX inside bold spans needs explicit math-mode bold.** Markdown's `**...**` does not propagate into math mode — `**$k$-nearest neighbors**` renders the surrounding text bold but leaves the `k` non-bold. Wrap the math in `\boldsymbol{}` for italic-bold (variables, the default for letter variables) or `\mathbf{}` for upright bold (operators, constants): write `**$\boldsymbol{k}$-nearest neighbors**` so the `k` renders bold along with the rest. Applies anywhere bold and math meet.

### The Related footer

Write one line above the Flashcards separator, with links separated by ` · ` and no trailing separator or heading:

```markdown
**Related:** [[confusion-matrix|Confusion matrix]] · [[f1-score|F1 score]] · [[roc-curve|ROC curve]]
```

Every link is **piped to the target's canonical readable title**, including `[[arxiv|arxiv]]` when title and slug match. The bare form `[[slug]]` is wrong in the footer. Mathematical titles use their plain display form under §3. The footer has its own link slot: a target linked once in body prose may also appear here.

Select the entity's most useful navigation neighbors: important body links and, when warranted, one or two unmentioned siblings, predecessors/successors, or parent concepts. No minimum applies; do not pad or copy every body link. With no eligible neighbor, write the bare `**Related:**` label on its own line. Roughly eight is a soft fresh-entry upper bound. Merge growth up to roughly twelve is fine; report more rather than pruning unilaterally. Follow [merge rules](merge.md#frontmatter-and-related-footer) for source-driven additions and preservation, and their separate targeted-QC exception.

### Prose principles

These are the shared body-writing standards for `wiki-build` and `wiki-lint`. Write new source-derived prose in the model's own words; maintenance improves a concrete defect without rewriting already clear prose. The standards describe the desired result, not permission to alter every part of an existing entry: merges follow `merge.md`, and source-independent repairs follow linter [QC item 9](../../wiki-lint/references/qc-items.md#9-body-structure-coherence-flow-and-scope). [Flashcards](flashcards-and-emphasis.md#4-flashcards) follow their own principles.

**Explain the concept before cataloging qualifications.** Include a caveat
only when omitting it would materially mislead the reader about the definition
or ordinary mechanism. Prefer a short, scoped claim to an absolute claim
followed by a paragraph of exceptions, and repair an overbroad claim by
narrowing its own wording (*can*, *often*, *under squared-error loss*). Do not
append denials of stronger claims (*…does not guarantee…*, *…alone is not
enough*), well-definedness conditions
([equations §1](equations.md#1-coverage--explanatory-value-before-notation)),
implementation edge cases or failure handling, defensive terminology
distinctions, background clarifications absent from the source, rare failure
modes, or troubleshooting tails about neighboring concepts. Source support is necessary but does not by
itself make a detail useful. Keep essential assumptions and uncertainty; the
test is explanatory value, not maximal completeness.

**Operating principle: brief, clear, and atomic.** Give readers fast, accurate orientation to one durable subject. Each sentence should define it, explain how it works, distinguish it, or supply a necessary condition, qualification, or consequence. Keep the shortest wording that preserves understanding; extra words can be necessary to make a relationship or limitation clear. Brevity is not a word-count target or a reason to delete a substantive distinction. A neighboring subject that needs its own explanation belongs in a linked note under the atomicity and refactor rules.

Use a neutral encyclopedic register: direct, precise, and free of conversational address, hype, punchlines, or decorative metaphors. A source-established name or analogy may remain when it carries technical meaning; do not coin colorful labels or turn the source's rhetoric into the wiki's voice. Neutrality never means deleting attribution, conditions, or uncertainty that limit a claim.

**1. Main claim first.** The opening sentence names what the entity *is* — the core definition or central claim. Not biographical preamble ("LambdaRank was introduced by Burges in 2005..."), not motivation ("Learning to rank is an important problem..."), not buildup ("Before discussing the algorithm, recall that..."). The thesis itself, stated directly: "LambdaRank is a learning-to-rank method that optimizes ranking metrics by scaling pairwise gradients by the change in NDCG from swapping two items." It is also the entry's stand-alone hook — a reader who has never seen the source still gets the gist. If a reader read only the opening sentence of every entry in the wiki, they would have a usable mental map. **Self-check before saving:** read just the first sentence and ask whether it's the main claim or merely a lead-in. If it's a lead-in, demote or cut it and promote the actual claim.

  **Person and Event entries: dates in the opener.** For `type: Person` or `type: Event`, include the relevant date parenthetical immediately after the bolded title. When the active source omits it, follow [rare-types.md](rare-types.md#dates-in-the-opener-person-and-event): cite another durable source already in the vault, or defer a new candidate or report an inherited gap as that section specifies. A transient lookup or memory never changes the note. That section also owns the exact forms, qualifiers, era markers, spacing, placement, and worked examples; read it whenever the entry is a Person or Event rather than restating its grammar here.

  **Words before symbols.** Explain the idea in plain language before introducing notation; the opening paragraph should make sense to a reader who skips its math. Bind only the symbols a display uses, where [equations §3](equations.md#3-notation--one-symbol-per-role-vault-wide) places bindings, and omit notation conventions no displayed relationship needs.

**2. Paraphrase, don't extract.** When drafting from a source, write a connected explanation rather than trimming isolated source sentences until their relationships disappear. Preserve exact technical content where needed: equations, formal definitions, and literal identifiers. This drafting rule does not require stylistic rewrites of conforming existing prose.

**3. Preserve technical precision.** Every claim is technically accurate. Numbers are exact, conditional statements keep their conditions, definitions are not softened. Paraphrasing must not introduce ambiguity or weaken claims. If a source says "X is sample-efficient *when* the discriminator is larger than the generator," the entry does not drop the conditional. Precision narrows the claims the entry makes; it does not call for appended qualifications (see *Explain the concept before cataloging qualifications* above).

   Preserve evidence-bearing uncertainty with the same care. *May*, *can*, *is associated with*, *is estimated to*, and confidence or range qualifiers cannot become *does*, *causes*, or a point claim. State the narrowest clear qualified claim the evidence supports. Remove only rhetorical padding such as "it might seem at first glance," not epistemic limits on the result.

   **Check the scope of new claims before making them canonical.** A textbook's worked case or informal explanation is not automatically a universal property of the entry's subject. Check words such as *always*, *only*, *guaranteed*, and *requires* against the surrounding assumptions, definitions, and equations. If a new claim remains inconsistent or unsupported, retain only what the source establishes; otherwise defer that clause and report the conflict with its page. Do not copy a suspect guarantee into the description or flashcard, or silently replace it with background knowledge. For a conflict with existing entry content, follow `references/merge.md`'s conflict-handling rule. Source fidelity does not settle factual accuracy.

   Treat priority and superlative wording the same way. Claims such as *first*,
   *only*, *best*, *largest*, and *leading* need independent support from a second
   reliable source or narrow attribution to the active source or named report.
   If independent support changes the published note, it must be a durable vault
   source listed in `sources:`; process an existing capture through
   `clipping-clean`, or acquire it through `wiki-add`'s research-source
   workflow when the request is in its scope. A transient check may
   justify omitting a ranking, but never adding or
   broadening one. Without support, omit the ranking while preserving the
   source-backed descriptive claim. Scope software behavior to the version or time period the
   source establishes, and replace reader-relative words such as *currently*,
   *recently*, and *today* with that durable version or date.

   **Check the entry against itself.** Compare claims that describe the same
   effect, condition, or quantity across the paragraph and the full note. If one
   sentence says a method reduces both bias and variance while the next says it
   preserves similar bias and reduces variance, the prose has not expressed a
   coherent qualified claim. Reconcile the scope or conditions from the source;
   when the source does not resolve the conflict, report it rather than choosing
   the more convenient sentence.

**4. Coherent prose, with one local purpose per paragraph.** The body reads as a unified explanation, not a stack of relevant but disconnected facts. Each paragraph answers one discernible reader question or develops one controlling idea. Its sentences may define, explain, support, qualify, contrast, exemplify, or draw a consequence from that idea; sharing the entry's subject is not enough. A causal chain can therefore remain one paragraph even when it moves from mechanism to condition to immediate consequence.

  **Paragraph-flow test.** Give every paragraph a short job label, then ask whether each sentence advances that job. Inspect the final sentence especially: if the preceding sentences already form a complete paragraph and the ending introduces a new history point, statistic, application, limitation, comparison, or API family, move it beside the material it develops, start a new paragraph, or omit it when it does not earn a place. Then read only the paragraphs' opening sentences and verify that the note progresses in a useful order, establishing ideas before relying on them and keeping qualifications near the claims they constrain. A label that needs two unrelated clauses signals reorganization.

  When the reader's frame genuinely changes, use the right boundary: a new paragraph for another inherent facet, a `##` heading when that facet needs several paragraphs, or a separate linked note when the new subject passes the atomicity test. A real causal, conditional, sequential, or contrastive relationship can bridge two ideas without a break. Stock connectors such as *also*, *however*, and *meanwhile* do not repair an unrelated jump. Do not force a topic sentence into every paragraph, fragment a continuous explanation into one-sentence blocks, or infer flow from paragraph length. Bullets remain reserved for the genuinely list-shaped content described under *Bullets vs prose* above.

  **Transitions carry meaning.** Move from an established idea to the next, naming their relationship when it would otherwise be unclear. Adjacency or a repeated key term may be enough; a transition word is not mandatory. Add *therefore*, *because*, or *in contrast* only when the evidence establishes that relationship. If an abrupt change has no supported bridge, reorganize rather than invent one.

**5. Self-contained.** Explain the subject to a reader who has never seen the sources. Define terms on first use and avoid document navigation such as “recall from the source.” The following sub-rules govern attribution, internal references, and acronym introduction.

  **(a) Source-meta phrasing.** Do not refer to unnamed *the paper/chapter/book/article/author(s)/source*, *this source*, *as mentioned/discussed/noted/shown above/below/earlier/later*, *the previous section*, *as we saw*, or *the figure above/below*. Replace document-dependent framing with the subject, a named person, or a specific work treated as an entity. “The authors of SGDR recommend …” and “the GPT-3 paper” are valid named attribution; bare “the authors” or “the paper” leaves the reader without a referent.

  **(b) Biographical-attribution drift.** Keep real attribution but avoid drifting from a named person into “the authors.” Use “CLIP uses ResNet …” for the architecture, “Loshchilov and Hutter recommend …” for their recommendation, and “introduced by Gupta et al. in 2018” for origin, without an unnecessary “in a paper.”

  **(c) Framing-attribution drift.** “In Géron's framing …” or “Prince's book groups …” describes an exposition rather than the concept. State the supported relationship directly. Attribution for who did the work remains valid; when expositions differ, choose the clearest scope-preserving framing. Factual disagreement follows [conflict handling](merge.md#conflict-handling).

  **(d) Source-internal references.** “The case study,” “the experiment described above,” or “the OECD life-satisfaction example” assumes context the reader lacks. An example that earns its place under principle 7 needs a brief inline introduction; otherwise omit it. A definite phrase such as “the dataset” is valid only after its referent has been established in this entry.

  **(e) Acronyms are introduced in parentheses after the full form on first use, then used in the acronym form thereafter.** Write "the **$\boldsymbol{k}$-nearest neighbors** algorithm (KNN)..." on first mention, then "KNN" subsequently: the full form comes first, the parenthetical establishes the binding. This applies to any acronym, abbreviation, or short form the body uses after first mention — including the entry's own aliases when the body uses one rather than repeating the title. The YAML `aliases:` field does not introduce an acronym to the reader; the body prose has to do it explicitly. **The entry's own subject always shows its acronym ↔ full-form counterpart on first mention** whenever a commonly-used acronym exists — `**Machine learning** (ML)`, `**Principal component analysis** (PCA)` — whether or not the body uses the short form again, since the binding is useful identification for a reader looking the entity up. Do the same for other terms the body introduces; omit only obscure acronyms, or a short form for a term mentioned once and never reused, where the parenthetical is clutter. The parenthetical sits **outside** any bold span around the title (`**…neighbors** (KNN)`, not `**…neighbors (KNN)**`): the title is the bolded element, the binding is annotation.

  **(f) Acronym-titled entries invert the (e) pattern.** When the entry's canonical title is itself an acronym, open with `**ACRONYM** (Full Expansion) is...` so the bolded title still comes first and the expansion follows as annotation. Examples: `**DBSCAN** (Density-Based Spatial Clustering of Applications with Noise) is a clustering algorithm...`; `**t-SNE** (t-distributed stochastic neighbor embedding) is a dimensionality-reduction method...`; `**MLOps** (machine learning operations) is the practice of deploying, monitoring, and maintaining machine learning systems...`. For a `Person` or `Event`, the mandatory date occupies the first parenthetical slot and the expansion follows it: `**ILSVRC** (2010–2017) (ImageNet Large Scale Visual Recognition Challenge) was an annual competition.` The choice between (e) and (f) is determined by the title field — whichever form the canonical title takes is the form bolded first in the body; the other form is the parenthetical annotation.

  **(g) Contested-topic exemption.** Entries on genuinely contested topics (philosophical positions, historical interpretations, religious doctrines) may present competing views as parallel positions with light attribution like "the materialist reading argues …" — see the *Contested-topic exemption* under [conflict handling](merge.md#conflict-handling) for when this applies. The (a)–(d) prohibitions otherwise apply.

**6. Remove padding without compressing away meaning.** Cut empty lead-ins, reader commentary, rhetorical hedging, and repetition that adds no distinction. Prefer a direct statement to praise or an elaborate metaphor. Keep useful signposting, technical terms, and evidence-bearing qualifiers; two sentences about the same subject may express different conditions or claims. Shorter is better only when equally clear and precise.

  Keep the entry focused: omit source recaps, tangential motivation, unrelated anecdotes, and the source author's preferences. **Implementation recipes and how-to detail** belong in the source; a `Software` entry may explain an artifact-wide interface without cataloging classes, defaults, or version-specific features. **Neighboring concepts** get the relationship needed for orientation and a wikilink, with the full explanation in their own entries. Principle 7 governs the rare example that stays. Selecting or removing substantive content in an existing note still follows the merge or source-backed repair boundary; editorial concision alone does not authorize it.

**7. Examples must earn their space.** **Default to no example.** Add one only when it clarifies this entity's own definition, mechanism, or an important distinction more effectively than a shorter direct explanation. An interesting application or an example copied from the source is not sufficient. If removing it leaves the concept just as clear, remove it. Neighboring concepts get a clause and a wikilink, not an example that teaches the neighbor.

  **Usually one compact illustration, in at most ~2 sentences woven into the prose.** Treat that as a strong default, not a quota to fill or an automatic cutoff. A rare second illustration or slightly longer one must resolve a specific remaining misunderstanding about this same entity that shorter prose cannot resolve; record that reason in one line in the run report. This does not permit multi-paragraph walkthroughs, repeated examples, unrelated application stories, or a narrative with its own figures. Keep the example focused even when an exception earns its place.

  **Keep only the concrete detail that makes the point clearer.** Omit incidental names, dataset rows, fitted parameters, intermediate calculations, and exact results. Keep a minimal source-provided value when the reader needs that value to see the definition, mechanism, or distinction; abstracting it must not make the example harder to understand. For a nearest-neighbor illustration, $k=3$ may explain the three-neighbor average without a roster of countries, GDPs, satisfaction scores, and a fitted result. Retained numbers and claims keep the source's exact values, scope, and conditions under principle 3; do not invent data or generalize a worked case into a universal claim. Introduce any necessary scenario inline under 5(d), without its backstory.

  **One canonical owner per explanatory treatment.** When this run creates or merges a more specific entry whose subject is the example or explanation, give that entry the full treatment. Related entries retain only the concise relationship needed to orient the reader and a wikilink. This does not forbid a brief reciprocal contrast that is necessary to understand each subject; the final run-level sweep in `references/review.md` judges duplicated explanatory work rather than matching words.

  **Recreated tables keep their source values** under [Body structure](#body-structure). The prose-example rule does not abstract away table findings. This exception does not permit turning a worked example's intermediate steps into an invented table: only source-presented tabular material qualifies.

**8. Mathematics earns its place by explaining the concept.** Include equations that make a quantitative relationship, model, or calculation clearer than prose alone. Do not translate an easily understood verbal rule into complicated notation merely because that is possible: hard voting needs “choose the class with the most votes,” not an argmax over indicators. A useful standard equation may be included even when absent from the source, provided its meaning, assumptions, and conventional status are verified and supported through the normal source workflow. Conversely, a source equation or a fully described calculation is not automatically required. Apply the explanatory-value and evidence tests in `references/equations.md` before adding or retaining math. When warranted, defining equations use `$$...$$` display blocks, symbols use inline LaTeX, notation is consistent, and every symbol is bound nearby. YAML descriptions and other fields remain plain; only `title:` permits narrow inline LaTeX for a load-bearing canonical-name symbol.

  **Numbers in body prose: LaTeX for math, plain text for everyday quantities.** Use LaTeX when the number is a math object — class labels in a binary convention (`$\{-1, +1\}$`), indices and subscripted values (`$x_1$`, `$\sigma^2$`), numbers in or referencing an equation, and bounds (`$0 \le p \le 1$`). Use plain text when it's a plain quantity — counts ("5 trials"), dates ("1975"), page numbers, informally reported parameter values ("learning rate of 0.001"), everyday percentages, currency. Named-digit metrics keep the digit plain and spell the name as the field writes it (`F1 score` — the `1` sits directly after the `F` with no hyphen, and is a name fragment rather than a variable, so it is plain text, not `$F_1$`; the subscript form belongs only inside equations, and spellings like `F-measure` go in `aliases:`), while `$k$-fold` keeps the `k` in LaTeX because it is a variable. Test: if you could substitute a variable, it's math; if it's a fixed real-world quantity, it's plain. **Decorative `$...$` wrapping is wrong** — don't wrap plain numbers in math delimiters because nearby numbers happen to be in LaTeX; every `$...$` pair opens a math region and contributes to parser collisions.

  **Literal `$` characters need escaping.** When `$` appears in body prose as a currency sign or any other literal-dollar use, write `\$`. Otherwise Obsidian's parser pairs unescaped `$` characters as math delimiters — a single unescaped `$33` followed later by another unescaped `$` will mathify everything between them, garbling the rendering with italicized text, lost dollar glyphs, and dropped punctuation. Write `the OECD lists Poland at \$32,238 GDP per capita`. The same applies to regex anchors, shell prompts, and environment variables.

**9. Clear sentences — one main idea when possible.** Use concrete subjects and precise verbs. Make the referent of *this*, *it*, or *the former* unambiguous; repeating a short technical term can be clearer than a pronoun. Split or restructure an overloaded sentence where the thought divides, while keeping conditions and exceptions attached to the claims they limit. A clear longer sentence is acceptable: there is no word-count target, mechanical length finding, or exception to report. Read equation lead-ins and continuations as part of the sentence so a display does not leave a fragment or a broken grammatical join.

### Editorial reread

After drafting or editing, read the finished passage and its neighbors as a
continuous explanation. Check clear referents, useful order, natural
transitions, and concise wording, including sentences around equations and
exhibits. Then compare against the source or pre-edit text for changed meaning:
did an illustration become a general rule, a small effect lose its degree, or
a qualifier drift onto a different claim? Then check the opposite direction:
did the draft or edit add a caveat, edge case, or clarification the reader
does not need to understand the concept? Remove it, but keep conditions that
limit a stated claim. Fix any regression before saving.
Editorial standards do not independently authorize changes to existing cards
or review state; apply the workflow's existing card, date, and review-state
rules and preserve other protected content under its merge or repair rules.
Do not rewrite a clear passage merely to make the wording different.

---

## 3. Wikilinks and naming

### Link form

In body prose, use `[[slug|Display text]]` when the displayed form differs from the target slug (case, spacing, alias, or other rendering). Use `[[slug]]` only when the strings are identical. The [Related footer](#the-related-footer) always uses a pipe, including identical forms.

Use the actual extensionless vault-relative Wiki path when the bare filename
has another real owner, including a MOC: `[[Wiki/statistics|Statistics]]` links
the entry while `[[MOCs/statistics]]` navigates to its MOC. Apply folder
overrides and intended public paths, not scratch-tree paths. Inspect real MOC
ownership separately from the Wiki-only index, and preserve required path
qualification when canonicalizing an existing link. A bare Wiki/MOC collision
stays ambiguous until its intended owner is established; never guess from an
alias or drop it as a dangler. Existing MOC navigation remains outside this
skill's entry-link creation/pruning scope.

Hidden HTML (`<!-- … -->`) and Obsidian (`%% … %%`) comments are editor annotations, not rendered body prose or link candidates. Preserve them; do not treat their headings, template footers, or links as live entry structure. Escaped wikilink examples are literal text. Code samples likewise remain outside linking and orphan checks. Flashcard content and recognized review attachments keep their separate card-format rules.

**First eligible occurrence only in body prose.** Apply [link-worthiness](#what-earns-a-wikilink) first; link only the first eligible mention of another entity, leaving later body mentions plain. **Possessive and partitive references count as mentions.** A body that says "scikit-learn transformers" or "Obama's first term" or "Python's dictionary type" is mentioning the entity — wikilink the first such occurrence: `[[scikit-learn]] transformers`, `[[barack-obama|Obama]]'s first term`, `[[python|Python]]'s dictionary type`. The rule's intuition is *any naming of the entity*, not just "the entity as a standalone noun phrase." Entities mentioned inside LaTeX math (e.g., `$\Delta\text{NDCG}$`) can't be wikilinked from inside the math, so the first **prose** occurrence outside math gets the wikilink.

**Integrate a body link into the sentence that explains the relationship.** Do not use navigation-only directions such as `see [[…]]`, `(see [[…]])`, `refer to [[…]]`, or `consult [[…]]`. State the connection in ordinary prose, or leave a purely navigational link in the Related footer. `To see how the error changes, vary $k$` is ordinary prose and is not this failure shape; the banned cue points directly at a wikilink instead of explaining why it matters.

**Wikilinks do not appear in image captions, in table captions, or in table cells** — none of those zones allow wikilink syntax. An entity worth navigation gets wikilinked in the surrounding prose that motivates the table, not in a cell.

**No self-links.** An entry never wikilinks to its own title — mentions of the entry's own subject appear as bare text (the LambdaRank entry writes "LambdaRank", not `[[lambdarank|LambdaRank]]`), since a self-link is circular and Obsidian renders it as a redundant tag pointing at the current file. **Exception:** the first appearance of the title in the body is **bolded** per Bold Pattern 1 of the [bold and italic rules](flashcards-and-emphasis.md#5-bold-and-italic) — bolded, but still not wikilinked. Subsequent mentions are bare.

### Display-label casing

Display-label casing follows standard English:

- **Proper nouns and acronyms** keep canonical case everywhere: `[[mnist|MNIST]]`, `[[lambdarank|LambdaRank]]`, `[[catboost|CatBoost]]`, `[[yann-lecun|Yann LeCun]]`.
- **Common nouns mid-sentence** are lowercase: `...counts read off the [[confusion-matrix|confusion matrix]]...`, `...tuning the [[decision-threshold|decision threshold]]...`.
- **Common nouns at the start of a sentence** are Sentence case: `[[cross-validation|Cross-validation]] estimates how well...`.
- **In the Related footer**, Sentence case for common nouns and canonical case for proper nouns and acronyms: `**Related:** [[confusion-matrix|Confusion matrix]] · [[roc-curve|ROC curve]] · [[mnist|MNIST]]`.
- **When the source uses an alias form, preserve that form in the display label.** A source saying "TPR" becomes `[[recall-machine-learning|TPR]]`, not `[[recall-machine-learning|recall]]`; a source saying "Lambda Rank" becomes `[[lambdarank|Lambda Rank]]`, not `[[lambdarank|LambdaRank]]`. The slug points to the canonical entry; the rendered text stays faithful to the source's vocabulary while still consolidating to a single entry.
- **A display label normally must be a surface form the target's `title:` or `aliases:` claims.** Apply [§6's three carve-outs](../../../shared/CONVENTIONS.md#6-wikilink-forms): a context-resolved cross-domain bare term (`[[information-entropy|entropy]]`), a natural plural or verb inflection, and an Organism's complete common name that the target's description or opening sentence explicitly binds to its canonical title (`[[mus-musculus|mouse]]`, but never `fly` from `fruit fly`). Never add a common name as a global alias just to permit a link. Reword any other invented, subset, or superset label to a claimed form, or add a genuine unambiguous alias. A label that exactly names a different existing title or unambiguous alias is a target conflict; review the sentence and ownership rather than silently retargeting it.
- **Display labels are plain text — no LaTeX, no markdown formatting.** Obsidian renders the text after the pipe as plain text in link styling; it does not interpret `$...$` math, `**bold**`, `*italic*`, or backtick code inside display labels. When an entity's canonical name contains mathematical notation (e.g., "$k$-nearest neighbors", "$A^{*}$ search", or "$\chi^2$ test"), the display label uses its meaning-preserving plain form (`k-nearest neighbors`, `A-star search`, or `chi-squared test`); if the variable matters typographically, set it in LaTeX in the surrounding prose, separate from the wikilink. Example: write "the [[k-nearest-neighbors|k-nearest neighbors]] algorithm uses $k$ training examples" rather than "the [[k-nearest-neighbors|$k$-nearest neighbors]] algorithm." Unicode characters render fine in display labels, but use the same semantic plain form for a mathematical title so Unicode `χ² test` and LaTeX `$\chi^2$ test` do not create divergent answer or label text.

### What earns a wikilink

**The wikilinking decision uses the same substance bar as entry creation.** A mention is worth wikilinking only if the entity itself is worth being a navigable node — would the reader genuinely benefit from jumping to an entry for this thing? Passing mentions, glancing references, and bare name-drops do not qualify, even when the slug happens to exist. Wikilink only what deserves to be looked up; leave the rest as bare text.

**Positive trigger — when a body paragraph attributes mechanism, architecture, or method to a named entity, that entity has cleared the substance bar and should be a step-2 candidate.** Phrase signals: *"X's architecture is…"*, *"X works by…"*, *"X introduced [mechanism]"*, *"X uses [technique]"*, *"X's objective is…"*, *"X solves [problem] by…"* — followed by enough mechanism-level detail for a self-contained atomic entry, not just the fact that the entity exists. Create the entry from that coverage and wikilink it. If the coverage genuinely cannot support an entry, the mention stays plain text and the entity is reported under *Entities deferred* — never a placeholder file.

**A bare list of names is not a trigger, however major the names are.** A `Gradient boosting` entry ending "popular implementations include XGBoost, CatBoost, and LightGBM" teaches the reader nothing about any of the three, so all three stay bare text. Naming a thing is not teaching about it, and only the second earns a node. What flips such a list into trigger territory is the source going on to say *how* one of them differs: "CatBoost handles categorical features with ordered target statistics rather than one-hot encoding" is mechanism, and that name earns a node.

**Every entry wikilink target in body prose and the Related footer must be a real file in `Wiki/`** — an entry that already existed, or one this run writes. An entity worth linking that has no entry either becomes an entry (the positive trigger above) or stays bare text; **no placeholder files, ever**. Existing MOC navigation keeps the separate preservation rule above. Frontmatter wikilinks in `parents:` follow their own field definition. Update or create the `**Related:**` footer per §2; new footer links name only entries that exist.

### Cross-domain term disambiguation

Many terms have well-known, substantively different meanings across disciplines: `entropy` → `Information entropy` / `Thermodynamic entropy`; `transformer` → `Transformer architecture` / `Electrical transformer`; `vector` → `Mathematical vector` / `Cloning vector` / `Attack vector` / `Disease vector`; `domain` → `Function domain` / `Protein domain` / `Internet domain`; `bias` → `Statistical bias` / `Cognitive bias` / `Voltage bias`; `kernel` → `OS kernel` / `Kernel method` / `Convolution kernel`. The finite corpus named in test (c) is the canonical mechanical floor: `find_collisions.py` marks a candidate with such a bare slug `naming: ["bare-common-noun"]`, `lint_entry.py` reports it as `5-bare-common-noun` before publication, and wiki-lint's scanner reports it and blocks automatic backfill to it. **It is not exhaustive** — the same qualifying rule applies to *any* term that meets the recognition tests.

**How to recognize a cross-domain-ambiguous term.** Apply these tests *before* writing the title for any candidate that is a single common word or a short common-word noun phrase:

- **(a) Dictionary / Wikipedia test.** Search the term as a Wikipedia article. If the canonical landing is a *disambiguation page* — "Tensor (disambiguation)", "Policy (disambiguation)" — the term is cross-domain ambiguous. (Wikipedia disambiguation is the broadest available proxy for "this word means different things in different fields.") The bias is to **qualify even when in doubt**: a borderline candidate that turns out to be unambiguous costs nothing to qualify, but an unqualified bare slug that turns out to be ambiguous causes silent cross-domain collisions later.
- **(b) Drafting test.** If you find yourself wanting to write the description as "In machine learning, X is …" / "In biology, X is …" — that "in $DISCIPLINE" hedge is the skill *sensing* the ambiguity. Strip the hedge and qualify the title instead: `Tensor` → `Machine learning tensor`, `Policy` → `Reinforcement learning policy`, `Return` → `Reinforcement learning return`. The description then reads unhedged: "A reinforcement learning return is …"
- **(c) Common-noun test.** Single common English nouns (`activation`, `agent`, `attention`, `bias`, `cell`, `classification`, `clustering`, `domain`, `ensemble`, `entropy`, `feature`, `field`, `filter`, `function`, `gradient`, `inertia`, `kernel`, `label`, `model`, `normalization`, `policy`, `regression`, `return`, `shrinkage`, `temperature`, `tensor`, `transformer`, `vector`) are almost always polysemous across disciplines and are qualified by default. The exception is rare — a common noun whose discipline-specific sense has so eclipsed the others that no qualifier is needed (`Logistic regression` is unambiguous as-is, because the phrase doesn't appear in other disciplines under that name).
- **(d) Compound-noun escape hatch.** Two-or-more-word compounds that already include a discipline-specific qualifier (`Linear regression`, `Decision tree`, `Random forest`, `Neural network`) are typically NOT ambiguous — the compound disambiguates itself. Apply (a)–(c) to the head noun, not the modifier: `regression` alone is flagged; `linear regression` is not.

**The rule: qualify proactively on first creation.** When (a), (b), or (c) fires, the title must be qualified — never claim the bare slug for a single sense, even if the current source uses the bare term throughout. The disambiguating qualifier is part of the title. **Prefer the most natural English noun- or adjective-form compound** (`Thermodynamic entropy`, `Transformer architecture`) over a terse parenthetical tag like `Transformer (ML)`; a descriptive compound reads better in running prose and as a slug. **The compound must *add a qualifier to the candidate term*, not *replace it with a different name*** — `Thermodynamic entropy` adds `thermodynamic` to `entropy`, and the candidate word stays in the title. **A recognized alternative name for the same concept — the kind of surface form you would otherwise record as an *alias* — is not a qualifier-compound, so don't promote it to the title to dodge the parenthetical** (`Cluster analysis` for `clustering`, `Categorization` for `classification`); the alternative name goes in `aliases:`. **Parenthetical disambiguation is the form for terms with no graceful compound:** common nouns like `feature`, `label`, `filter`, and `clustering` have none (`Machine learning feature` is awkward and arguably wrong), so a *descriptive* parenthetical is correct — `Feature (machine learning)`, `Filter (convolution kernel)`, `Clustering (machine learning)` (with `cluster-analysis` as an alias). The parenthetical names the sense; it is never a terse abbreviation like `(ML)`. **The bare slug is reserved and unused** — never `entropy.md`, `transformer.md`, `vector.md`, `feature.md`.

**Base-term and mathematical plain-form rules.** When a title carries a parenthetical disambiguator, the **base term** — the title with the parenthetical removed (`Feature` for `Feature (machine learning)`) — is what gets used by: the body's bolded opener, the description's grammatical subject, the item-7 / item-16 title-coherence checks, and the flashcard answer (line 3, along with its line-1 leak check). A title with permitted inline LaTeX uses its rendered mathematical form in the body and its meaning-preserving plain form in `description:` and flashcard line 3. Formatting commands unwrap, Greek symbols take readable names, and common scripts retain their operation or index (`$A^{*}$ search` → `A-star search`; `$\ell_1$ norm` → `ell-one norm`; `$L^{-1}$` → `L-inverse`; `$x^{1/2}$` → `x-to-the-one-half`; `$R^{+}$` → `R-plus`; `$\chi^2$ test` or `χ² test` → `chi-squared test`). A chemical charge reads as a charge (`Ca²⁺` → `Ca2-plus`), and a Unicode formula with two or more element symbols keeps its subscript digits (`H₂O` → `H2O`); a single-symbol subscript is still spoken (`L₂` → `L-two`, `O₂` → `O-two`). The parenthetical disambiguates the filename and the entry's identity; it does not appear as the running-prose subject. The slug still derives from the *full* title (`Feature (machine learning)` → `feature-machine-learning`: the main pipeline maps the parentheses to `-` and collapses the run), so the filename is unaffected. Compound qualifiers like `Information entropy` are *not* affected — there the opener bolds the full compound, which already equals the title.

**Canonical name is the contextually-resolved sense, not the source's literal wording.** When a source uses a bare ambiguous term, decide which sense it means from context and record the *qualified* form as the candidate's canonical name: a deep-learning paper writing "the entropy of the predictive distribution" produces a candidate named `Information entropy`. Resolution and creation then proceed against the qualified slug, and the body wikilink uses that slug with the source's wording as the display label — `[[information-entropy|entropy]]` in an ML context, `[[thermodynamic-entropy|entropy]]` in a thermodynamics one. **Never add the bare term as an alias to any entry**, since that would silently capture every other discipline's use of the word. Corpus failure: an entry titled `Transformer architecture` aliasing `transformer`, or `Filter (convolution kernel)` aliasing `kernel` and `filter`, claims the bare term across disciplines. If such an alias already exists, report it as a semantic-invalid removal proposal and preserve it until an approved vault-wide pass rewrites every inbound resolving link under the [shared alias-refactor protocol](../../../shared/CONVENTIONS.md#4b-aliases-use-the-same-slug-rule). Distinct concepts sharing linguistic roots (`Cross-entropy` vs `Information entropy`) get their own entries and ordinary wikilinks.

**Keep every claim on the selected sense.** Qualification controls the entry's
scope, not just its filename. Do not transfer another sense's origin, definition,
or properties to the qualified subject merely because both share the bare word;
for example, do not say that *Information entropy* originated in thermodynamics.
If the historical or mathematical relationship matters and the source supports
it, state that relationship precisely and link the other sense.

**Wikilink between connected senses where the connection is substantive.** Information entropy and thermodynamic entropy share mathematical roots in Boltzmann's statistical mechanics; an entry on `Information entropy` discussing that lineage should wikilink to `Thermodynamic entropy`. A math vector and a virology vector share only a word — entries don't cross-link.

---

## Complete entry example

File: `lambdarank.md`. This is an illustrative entry; actual sources and image names come from the selected vault.


```markdown
---
title: "LambdaRank"
type: Concept
aliases:
  - "lambda-rank"
sources:
  - "[[Burges_LearningToRank_2010.pdf#page=4]]"
  - "[[Liu_LambdaRank_2021.md]]"
created: 2026-05-13
updated: 2026-05-14
description: "LambdaRank optimizes ranking metrics by scaling pairwise gradients by the change in NDCG from item swaps."
tags:
  - "#machine-learning"
parents: []
read: false
---
**LambdaRank** is a [[learning-to-rank|learning to rank]] method that sidesteps the non-differentiability of ranking metrics by defining gradients directly, scaled by the change in the target metric from swapping a pair of items.

It starts from [[ranknet|RankNet]]'s pairwise cross-entropy loss. For items $i$ and $j$, it multiplies RankNet's gradient $\lambda_{ij}^{\text{RankNet}}$ by the absolute change in [[ndcg|normalized discounted cumulative gain]] (NDCG) from swapping the two items in the current ranking, $|\Delta\text{NDCG}_{ij}|$, giving the LambdaRank gradient $\lambda_{ij}$:

$$
\lambda_{ij} = \lambda_{ij}^{\text{RankNet}} \cdot |\Delta\text{NDCG}_{ij}|
$$

![[Burges_LearningToRank_2010_fig_3.png]]
*The gradient is scaled by the NDCG change from swapping a pair of items.*

Swaps involving top positions, where NDCG is most sensitive, change the metric more, so those pairs receive larger updates than pairs deep in the list. LambdaRank defines only these gradients and never writes down an explicit loss.

**Related:** [[ranknet|RankNet]] · [[lambdaloss|LambdaLoss]] · [[ndcg|NDCG]] · [[pairwise-ranking|Pairwise ranking]] · [[learning-to-rank|Learning to rank]]

---

## Flashcards

A learning-to-rank method that scales each item pair's RankNet gradient by $|\Delta\text{NDCG}_{ij}|$, the NDCG change from swapping items $i$ and $j$.
??
LambdaRank
```
