# Writing an entry — fields, body, wikilinks

Scope: Wiki field choices, body prose, the Related footer and links.
[CONVENTIONS §2](../../../shared/CONVENTIONS.md#2-frontmatter-schemas) owns
schema and encoding, [merge logic](merge.md) owns updates to existing entries,
and the [flashcard and emphasis guide](flashcards-and-emphasis.md) owns cards
and markup.

- [1. Frontmatter fields](#1-frontmatter-fields): every key from `title` to `issues`, and the quoting policy
- [2. The body](#2-the-body): structure, the Related footer, prose principles and the editorial reread
- [3. Wikilinks and naming](#3-wikilinks-and-naming): link form, display labels and what earns a link
- [Complete entry example](#complete-entry-example): one finished entry

---

## 1. Frontmatter fields

### title

Use the canonical entity name in natural casing with the source's spelling and diacritics (`Gaussian mixture model`, `Aurélien Géron`); only the filename is transliterated (`aurelien-geron.md`), derived from the decoded full title with `<plugin>/shared/scripts/slugify.py`, never an improvised pipeline. A common word or short common-word phrase, or the urge to write "In machine learning, X is …", signals a [cross-domain term](special-titles.md#cross-domain-term-disambiguation) to qualify; a parenthetical or inline LaTeX follows the [plain-form rules](special-titles.md#base-term-and-mathematical-plain-forms).

**Acronym or full form.** BERT, MNIST, DBSCAN, LSTM, t-SNE, ReLU, RAG, LoRA and GAN are acronym-titled, even where the full form has standalone textbook usage (LSTM, GAN); only these listed acronyms override that usage. Any other entity whose full form has standalone textbook usage takes the full form, even when the literature mostly writes the acronym (`Principal component analysis`, `Proximal policy optimization`, `Direct preference optimization`), and an expansion without that usage yields to the acronym (ILSVRC, DeiT). Description and opener use one running form, and the opener introduces the counterpart under principle 5(e)–(f), supplying it as 5(h) background when the source never prints it (`**MNIST** (Modified National Institute of Standards and Technology)`).

**Tasks and artifacts.** Procedures take established task names (*Masked language modeling*), results their model-class or artifact names; title, description and opener name the same kind of entity. A task is never aliased to its model, output or classifier, and a shorthand (MLM) only when its source sense is the same entity and collision checks pass.

### type

One of the fifteen enum values in [CONVENTIONS §2a](../../../shared/CONVENTIONS.md#2a-wiki-entry--wikimd) — no other values. The five common ones are defined here; the other ten, in [rare types](rare-types.md).

- `Concept` — methods, algorithms, ideas, techniques, phenomena **and named models and research systems** (`LambdaRank`, `BERT`, `AlphaFold`).
- `Person`; `Organization` — companies, labs, institutions; `Dataset` — named datasets and benchmarks (`ImageNet`).
- `Software` — artifacts the user installs, deploys, runs or uses through a software interface: libraries, frameworks, languages, runtimes, operating systems, databases, IDEs and deployed products (`scikit-learn`, `ChatGPT`); scope and identifiers follow [API surface](api-surface.md#software-explain-the-artifact-not-its-reference-manual).

**Named-model rule.** A named architecture (`ResNet`), pretrained model (`GPT-3`) or landmark research system (`AlphaGo`) is a `Concept` even when it is also a program, because other entries cite, compare or extend its approach; an artifact the user installs (`PyTorch`) or uses as a product (`ChatGPT`) is `Software`. One idea can have both (`Gradient boosting`, `LightGBM`); when torn, prefer `Concept`. Hardware (a sequencer, microscope or GPU) is a `Device`.

### aliases

An optional list of the subject's alternate names that the source uses or the opener introduces (spellings, abbreviations, synonyms), each a slug under [the shared alias contract](../../../shared/CONVENTIONS.md#4b-aliases-use-the-same-slug-rule): `Recall (machine learning)` takes `["true-positive-rate", "tpr"]`. Bare [cross-domain](special-titles.md#cross-domain-term-disambiguation) terms (*sensitivity*, introduced in italics) and organism common names unsafe as global aliases stay out, though they may still be display labels. Omit the key when no useful alias remains.

**An alias names the same entity, in the same grammatical role**, never a related, contrasting, narrower, broader, successor or component one (a *hard voting classifier* is an ensemble, not an alias of `Hard voting`). Reject a variant, version or successor ("extends", "builds on"), a contrasting technique ("differs from", "similar to … but"), a component or role, or a special or general case (DALL·E and DALL·E 2). A separate equation, subsection or mechanism only prompts that inspection, since one entity can be explained under an alternate name. Leave a rejected name out unexplained; link the distinct entity only where the source relates them.

**Complete the field** (item 17) with the body's own same-entity names: *also called/known as X*, a direct *(short for X)*, the opener's acronym/full-form pair, and a directly bound scientific abbreviation (`***Escherichia coli*** (*E. coli*)`). The body must bind the name to this subject (*dummy attributes* names a One-hot encoding's output); `lint_entry.py` flags candidates. An acronym the opener binds to this subject is its alias even when it has other expansions elsewhere (SD, CI), unless it spells a cross-domain-corpus term or an ordinary English word. Exclude forms that slug-equal the filename or each other (case, normalization, plural); among differing same-family forms (`oob-evaluation`, `out-of-bag`), keep the most distinctive, usually the acronym.

Check new aliases against every other entry's titles and aliases before publication; step 7's review tree flags a conflict as `18-alias-collision`. A cross-entry owner conflict blocks the claim and goes under *Notes for the user*; never silently remove a pre-existing semantic-invalid alias or choose the first owner. Leave an alias of uncertain identity unclaimed; a distinct entry passes its own identity and substance gates.

### sources

List the durable sources that contributed to the entry under [CONVENTIONS §7](../../../shared/CONVENTIONS.md#7-source-references), which owns filenames, quoting, anchor syntax, identity and deduplication. The builder cites only vault documents it read and never writes a URL item; wiki-add cites an inspected web page by its verified URL, and a merge keeps an existing URL item unless an active source proven to be the same document replaces it ([merge rule 1](merge.md#frontmatter-and-related-footer)).

For a PDF, cite the entity's introducing page once: the **physical page** (`#page=N`, never the printed page number) where the source's main explanation of the entity begins. That is the first page of its dedicated section when it has one, and otherwise the page of its defining passage. A section shared by several entities is each one's dedicated section unless a later section treats one alone. An entity that only a figure or table explains cites that exhibit's page; one it merely labels does not qualify. Markdown sources have no anchor. A PDF and its confirmed summary are one source, cited as the PDF ([source cases](source-cases.md#resolve-a-markdown-source)).

### created / updated

New entries set both bare `YYYY-MM-DD` fields to the run's local date. `created:` never changes. On merge, `updated:` follows the [actual-change test](merge.md#frontmatter-and-related-footer), and review state its [separate test](#read).

### description

One sentence of **at most 110 characters**, with the entity as grammatical subject in its canonical running form (the [base term or plain form](special-titles.md#base-term-and-mathematical-plain-forms) of a qualified or mathematical title). A leading article is valid (`A cache line is …`); a placeholder subject (`This method …`) or bare predicate (`Optimizes …`) is not. Use present tense for extant entities and ongoing events, past tense for deceased people, defunct organizations and completed events. Capitalize the first word unless the subject begins lowercase (`t-SNE`), and end with a period.

**Plain text only:** no LaTeX or dollar signs, links, images, emphasis, strikethrough, code, HTML or entities, tags, highlights, comments, footnotes or block Markdown. Unicode (`α`, `≤`, `→`) is fine, but spell ℓ-norms in words (`ell-one norm`). Paraphrase a formula as a definition, keeping every defining operation: an Lp norm's sum of powers without its root is a different quantity.

[Step 4](../SKILL.md#4-create-new-entries) counts every drafted or revised description. To shorten one, drop nonessential modifiers, parentheticals and redundancy first; keep every condition that changes when the claim holds, or narrow the main claim and keep the detail in the body. On merge, change it only under [merge rule 6](merge.md#frontmatter-and-related-footer).

### tags

Use exactly one quoted, `#`-prefixed discipline-enum value in a block list,
under [CONVENTIONS §3](../../../shared/CONVENTIONS.md#3-the-discipline-tag-enum); unquoted, `#` begins a
YAML comment. Use `"#misc"` alone only when no specific
discipline fits.

```yaml
tags:
  - "#machine-learning"
```

**Tag where a learner meets the entity as a primary topic.** Predictive
models and their fitting, losses (including cross entropy), metrics,
evaluation, model components and named reinforcement-learning formalisms are
`#machine-learning`, even when they came from statistics or mathematics. That
includes linear, polynomial, ridge, lasso, elastic-net, logistic and softmax
regression, maximum likelihood estimation, least squares, residuals and the
bias–variance trade-off. `#statistics` holds descriptive statistics, sampling
and inference that fits no predictive model (hypothesis tests, confidence
intervals, analysis of variance, the Pearson correlation coefficient).
`#mathematics` holds structures taught across many fields as primary topics
(random variable, Gaussian distribution, central limit theorem, Markov chain,
information entropy, dot product). A method that also has an independent
classical identity (principal component analysis, cosine similarity) takes the
tag its vault neighbors use, `#machine-learning` for both, and the run report
names the alternative. A decision-tree leaf belongs with decision trees, while
a general data-structure entry or computing tool (NumPy, Jupyter) is
`#computer-science`. Other boundaries are in [calibration](calibration.md).

Every active discipline has a Wiki root entry; wiki-lint adds missing roots
and owns MOCs and parent placement. A new entry that is itself a discipline
(`Wiki/<discipline>.md` tagged only `#<discipline>`) is that discipline's root:
write it in the [root form](../../wiki-lint/references/hierarchy.md#establish-discipline-roots),
a short field overview that defines the field, states its method of inquiry
(how the field gains and tests knowledge: proof in mathematics, clinical
observation and controlled trials in medicine) and names its main branches as
subfields, not subject matter (algebra, analysis, geometry), linking each that
has an entry, with `parents: []` and no Flashcards section. On merge, follow
[tag reconciliation](merge.md#frontmatter-and-related-footer).

### parents

On creation write `parents: []`, never bare `parents:` (YAML null). Wiki-lint later populates the list from its hierarchy; merges preserve it.

### read

Write bare `read: false` on creation; the user checks it after reading. Apply [CONVENTIONS §2c](../../../shared/CONVENTIONS.md#2c-read--the-users-review-checkbox) to its type and ownership: missing, null or unknown existing state stays unchanged and is reported, never inferred. A known value resets only under the [unread-body-content test](merge.md#the-read-reset), independently of `updated:`. A recognizable misspelled boolean can be normalized without changing its meaning.

### issues

Write `issues: ""` directly after `read:` on creation. The field is the user's issue inbox under [CONVENTIONS §2d](../../../shared/CONVENTIONS.md#2d-issues--the-users-issue-inbox): the user describes problems there, and wiki-lint fixes them. Its value is user text, outside the quoting policy below; a merge follows [merge rule 9](merge.md#frontmatter-and-related-footer), and a builder never acts on, edits or clears a non-blank value.

### Quoting policy

Apply [CONVENTIONS §2](../../../shared/CONVENTIONS.md#2-frontmatter-schemas): double-quote newly written title, description and alias strings and every source, tag and parent item; keep type, dates and booleans bare. Preserve unchanged safe plain values rather than requoting them. Escape literal quotes and YAML backslashes, including the [mathematical-title case](special-titles.md#base-term-and-mathematical-plain-forms).

---

## 2. The body

### Body structure

- **Headings.** Flat prose is the default. **Use ATX `##` headings only when several genuine sub-aspects of the entity need named treatment**, never for length alone; they are the *only* sub-section form, so Setext underlines and bolded paragraph-leads (`**Architecture.**`) are **forbidden as section headers** ([bold and italic](flashcards-and-emphasis.md#5-bold-and-italic)), and wanting `###` prompts the atomicity test again. Headings are plain Sentence case (`## Encoder stack`) without bold, LaTeX or wikilinks; `## Binary classification` inside `Classification (machine learning)` signals a separate entry. The body has no `#` heading. A heading that repeats the entry title is deleted, never demoted, because Obsidian shows the filename as the inline title.

- **The atomicity test.** Each note has one durable entity or concept as its subject; type-specific conceptual units stay intact. Split source material into separate, linked entries when each part has a stable identity and enough support to explain on its own what it is, how it works or why it matters; each keeps only the relationship needed for orientation. **Link, don't re-explain.** A concept that has its own entry is linked and never re-defined here: say only what role it plays in this entry (“each step moves the parameters by the [[learning-rate|learning rate]] times the gradient”), and let its entry say what it is. Nor is an argument, worked example or property with its justification that another entry already gives repeated here: state its consequence for this subject and link that entry. Add at most one clause of reason or key value, and only when the consequence would otherwise leave an open question here. That clause takes the shortest form: about 68% of values lie within one standard deviation of the mean, not the whole 68-95-99.7 rule; a shrinking learning rate lets SGD settle, not why large early steps escape local minima. The owner keeps its derivation, conditions, full rule and supporting argument: never restate them, its discovery history or figure description here, nor display its formula unless this entry's own prediction, objective or defining relation is built from it ([equations §1](equations.md#1-coverage--explanatory-value-before-notation)). A neighbor with no entry keeps at most one brief defining clause, and only when this entry uses its term. When it deserves an entry of its own (a stable identity that the active source teaches), wiki-build creates that entry and links it instead of explaining it here, always for a [load-bearing term](../SKILL.md#2-extract-entities), unless a [named-entity request](../SKILL.md#named-entity-requests) leaves it unnamed: a named-entity request builds only the entities it names. Otherwise, and always in wiki-add, the clause glosses it and the run reports it as a missing-entry candidate (under *Entities not requested* in a named-entity run), which wiki-lint's next ordinary run creates. A variant with no identity apart from this entity (a solver option, a special case taught only here) is a facet. An umbrella such as `Classification (machine learning)` exists only when the source explains the broader concept, never as an index page. **Do not split to make a note shorter:** names, properties, conditions, stages, mechanisms and components that cannot stand alone are facets, and thin mentions stay plain text. An explanation, argument or worked example belongs to the entry whose subject it is about, the most specific such entry (a loss's convexity to the loss, not to each model trained with it; a trained tree's prediction cost to Decision tree, not CART); a family entry gives each member one role clause and a link. A property every member of a family shares belongs to the family's entry (weight penalties' scale sensitivity to Regularization, not Ridge regression), and an argument about how a metric behaves to that metric (the rare-positive argument to False positive rate; a plot built on the metric keeps the consequence and a link). Related entries keep the relationship, its consequence for them, a link and any one-clause reciprocal contrast ([overlap audit](review.md#overlapownership-audit-this-runs-entries-and-their-relevant-neighbors)). A pre-existing mixed entry met during a merge keeps its body: create any independently supported new-source candidate and report a proposed split, which wiki-lint's ordinary run makes once its proof holds; wiki-build never redistributes or deletes its content ([scope](../SKILL.md#scope-and-files)).

- **Bullets, numbered lists and prose.** Body content takes one of three forms, chosen by its shape. A list never replaces explanation: each item keeps its why.
  - **Bullets** suit genuinely list-shaped content: parallel items under one category, such as dependent variants, discrete components, or properties exhausted by their role here; standalone concepts become linked entries under the atomicity test. Parallel facts about several items (the same gene in three organisms, one property per variant, the cell changes in each age window) read best as one self-contained bullet per item, not woven into long sentences. Parallel bullets state the same property for each item (each lineage's cell-wall material), not a different incidental source detail per item. The entry's own subject is never one of its parallel bullets.
  - **A numbered list** suits an ordered procedure or sequence: an algorithm's steps, a protocol, a pipeline or the ordered stages of one process. It needs three or more discrete steps, where order matters and a reader may follow the steps or refer to one of them. Introduce the list with one prose sentence; a step count it states matches the list. Notation and conditions that hold for every step go in the prose before the list, which ends with the introducing sentence. Each item is one step: it opens with its action, in the same grammatical form across the list, and keeps its reason (what the step achieves or why), plus any display equation and that display's explanation. A loop ends with a "Repeat from step N until …" item, which counts as one of the steps; step N begins the repeated work, and an earlier step sets the starting state. What happens after the procedure, such as prediction after training, follows the list in prose. Time order alone does not make a causal chain: time-ordered stages of one process that each carry their own facts take a numbered list, one item per stage, each opened by its stage name when the source names the stages, and otherwise by its actor and verb (cGAS binds DNA; cGAMP activates STING), in the same form across the list. A stage item states what it triggers when the next stage depends on it (ATP binding releases the myosin head from the actin filament). Parallel facts by period or age window stay bullets.
  - **Prose** carries a causal chain (mechanism, then condition, then consequence) and an argument, where the connecting words carry the explanation. A sequence of fewer than three steps is prose too, as is a plain-words summary of a procedure the entry gives in full elsewhere, such as the opener's overview. **Don't list expository or argumentative content**, the most common misuse: if "because", "so" or "therefore" would join the items into one paragraph, write prose.
  - **Markdown form.** Number the items with sequential markers (`1.`, `2.`, `3.`). Indent a display equation, an extra paragraph or a nested list inside a step to the item's text column (3 spaces after `1. `, 4 after `10. `), with a blank line above and below a display; a block left at the margin ends the list there in Obsidian. Nest at most one level. A step opens with its action, actor or stage name, never a bold lead word or label; a stage name keeps its first-mention wikilink, or its italics under [Italic Pattern 1](flashcards-and-emphasis.md#5-bold-and-italic). One equation per display line still applies, and each display is explained in words inside the same item ([display inside a list item](equations.md#2-form--defining-equations-are-display-math)).

- **Tables and images.** Recreate a source table that serves the entry under [tables](media.md#tables), never as an image. Images earn a place under [selection](media.md#selection) and sit right after what they illustrate ([placement](media.md#placement-and-embed-syntax)); never expand the entry to fit an optional figure.

- **Inline code.** Backticks mark load-bearing API identifiers only in `Software` entries ([API surface](api-surface.md)); other entries carry none, and library names are never backticked. Any entry may backtick a bare file extension (`.csv`) or a bracket special token (`[CLS]`). Bold and italic follow the [emphasis rules](flashcards-and-emphasis.md#5-bold-and-italic); LaTeX inside bold needs [math-mode bold](special-titles.md#base-term-and-mathematical-plain-forms).

### The Related footer

Write one line above the Flashcards separator, with a blank line on each side, links separated by ` · ` and no trailing separator or heading:

```markdown
**Related:** [[confusion-matrix|Confusion matrix]] · [[f1-score|F1 score]] · [[decision-threshold|Decision threshold]]
```

Every link is **piped to the target's canonical readable title**, including `[[scikit-learn|scikit-learn]]` when title and slug match. The bare form `[[slug]]` is wrong in the footer. Mathematical titles use their [plain display form](special-titles.md#base-term-and-mathematical-plain-forms).

List the reader's next steps in this priority, whether or not the body links them: the nearest sibling or contrast, prerequisites this explanation relies on, direct children or next-step concepts, then the parent. Leave out general vocabulary that most entries in the field use (the training set, labels, genes, DNA) unless it is this entry's sibling, contrast, parent or child. No minimum applies; do not pad. With no eligible neighbor, write the bare `**Related:**` label on its own line. About eight links suit a fresh entry and growth to about twelve is fine; report more rather than prune. Merges follow the [merge rules](merge.md#frontmatter-and-related-footer).

### Prose principles

These standards serve `wiki-build` and `wiki-lint`. They describe the result, not permission to alter an existing entry: maintenance fixes a concrete defect without rewriting clear prose, merges follow `merge.md`, source-independent repairs follow linter [QC item 9](../../wiki-lint/references/qc-items.md#9-body-structure-coherence-flow-and-scope), and repairs from an entry's cited sources or 5(h) background follow wiki-lint's [content repair](../../wiki-lint/SKILL.md#task-1b--content-repair). [Flashcards](flashcards-and-emphasis.md#4-flashcards) follow their own format.

**Operating principle.** Give a learner a correct working understanding of one durable subject, as briefly as that allows. Each sentence defines it, explains how it works or why it matters, distinguishes it, or states a needed condition or consequence. Length is never a target, defect or reportable exception; never compress a definition or necessary condition to save words.

**Teach in the order a learner needs.** After the opener, give the idea in plain words (the problem it solves or why it matters), then how it works, then any formal statement, then consequences, the main limitation and the nearest contrast. This is a default order, not a template: skip a step the subject lacks, and never add one to fill it. A subject defined against a sibling (online versus batch learning) always has a nearest contrast: name and link that sibling in the body, not only in the Related footer, and when the sibling's own nearest contrast is this entry, the sibling returns it in one clause with a link, which wiki-lint adds when wiki-build may not edit that sibling. When the opener's definition would also fit a term the card's [sibling check](flashcards-and-emphasis.md#line-1-the-cue) names as confusable, the opener or the next sentence states the property that separates them (each predictor's feature subset is fixed, unlike random forest's per-split sampling).

**Core-facet check.** Before finishing, name the two to four points a standard reference's introductory section on the subject always covers, whatever the source's own section includes (an actin filament is a polymer of actin; k-nearest neighbors needs a distance measure and depends on $k$). Supply each missing one in one to three sentences, as principle 5(h) background when the source lacks it. Some facets are always core: a model or ensemble says how it predicts and how it trains, naming the objective its training minimizes when it has one (AdaBoost takes a weighted vote of its predictors and minimizes the exponential loss), while an instance-based model says that training stores the data and an ensemble whose members train independently (bagging, pasting, random forests, voting, stacking) names and links its members' training algorithm; when naming that objective or algorithm would need a neighbor's internals or notation the source lacks, one sentence and a link do it. A category concept (a class whose members are entities in their own right, such as model organism, organelle or a taxon such as Bacteria) names at least three canonical members a learner would recognize rather than broad groups, linking each that has an entry and placing them where they illustrate the property the note teaches, never as a roster in an unrelated sentence; an unfamiliar member gets its distinguishing clause or gives way to a familiar one. A discipline root takes the [root form](#tags).

Use a neutral encyclopedic register: direct, precise, free of conversational address, hype, punchlines or decorative metaphors. A source-established name or analogy may stay when it carries technical meaning; never coin colorful labels or adopt the source's rhetoric. A definition is never written as instructions; imperatives appear only in numbered-list steps. Neutrality never deletes attribution, conditions or evidence-bearing uncertainty that limit a claim (principle 3).

**1. Main claim first.** The opening sentence states what the entity *is*: its core definition or central claim, not biography ("LambdaRank was introduced by Burges in 2005…"), motivation or buildup. "LambdaRank is a learning-to-rank method that optimizes ranking metrics by scaling pairwise gradients by the change in NDCG from swapping two items." A reader of only the first sentence of every entry should get a usable map of the wiki. Self-check: read the first sentence alone. It passes the [card test](flashcards-and-emphasis.md#line-1-the-cue), reading naturally after `<term> is` and naming the kind and the essential property, or its verb states the defining action and so makes the kind plain (Gini impurity measures how mixed a node's classes are). A lead-in fails, as does a definition by exclusion, contrast, goal, name origin, appearance, location, member list or another property (its selectivity, regulation, distribution or a consequence) in place of the kind; promote the real claim. Such a definition states a wrong sense, even when the source's sentence is phrased that way: gene expression is the process by which a gene's information makes RNA and protein, and differential expression follows in the body.

  **Lead with the prototype.** Define the case a learner meets first (oxygenic photosynthesis; genes as DNA) and name variants, secondary senses of the name and other applications later in the body, once, never in the opening paragraph, description or primary card.

  **Frame the entry in its own field.** Explain the subject as a standard reference in its own discipline would, with its general definition and formula, even when the source meets it inside one application: cross entropy compares two distributions before it is softmax regression's cost. The source's application gets at most one sentence after the general explanation, with a link, is never the entry's only example, and never supplies the defining equation's notation when a general form exists: a general concept's display never borrows one application's parameters (cross entropy is not written with softmax regression's $\boldsymbol{\Theta}$; a generic model's $\boldsymbol{\theta}$ in a cost, as in $J(\boldsymbol{\theta})$, is not one application's parameters), and that application's entry owns its parameterized form.

  Person and Event openers carry a date parenthetical ([rare-types](rare-types.md#dates-in-the-opener-person-and-event)).

  **Words before symbols.** Explain the idea in plain language before notation; the opening paragraph should make sense to a reader who skips its math.

**2. Paraphrase, don't extract.** When drafting from a source, write a connected explanation, not trimmed source sentences whose relationships have disappeared. Keep equations, formal definitions and literal identifiers exact. Conforming existing prose needs no stylistic rewrite.

**3. Precise, plain and confident.** State the ordinary case plainly: "raising the threshold raises precision and lowers recall." Never weaken a plainly stated source or textbook claim with a hedge (*generally*, *usually*, *typically*, *normally*, *often*, *largely*, *mostly*, *classic*, *usual*, *can*, *may*, *possible*; the last three only when they weaken a claim that holds in the ordinary case, never when they state a capability, option or real possibility the source teaches), nor strengthen one the source limits for the ordinary case (*some models*, *in most cases*). Qualify only when the plain claim is false for the ordinary case, and then name the condition ("under squared-error loss"; what a choice depends on, such as rare positives or the cost of false positives) rather than add a hedge word. A hedge or caveat that covers only an edge case goes even when the source makes it: Géron's "in general" before the precision rule rests only on precision dipping as the threshold rises, so the entry states the plain rule. The [hedge sweep](#editorial-reread) checks every draft, captions included. Keep numbers exact, definitions unsoftened, and each condition or cause attached to the claim it governs, as the source states it.

  Research findings are the exception: evidence-bearing uncertainty (*may*, *is associated with*, *is estimated to*, a confidence range) never becomes *does*, *causes* or a point claim.

  Add a caveat only when leaving it out would mislead the reader about the definition or the ordinary mechanism; a limitation or contrast the source teaches is explanation (accuracy misleads on skewed classes). Leave out formula bookkeeping ([equations §1](equations.md#1-coverage--explanatory-value-before-notation)), implementation and numerical details, rare failure modes, edge cases the source mentions only in passing (precision dipping briefly as the threshold rises), defensive terminology distinctions, availability hedges ("varies by lab", "with interface and runtime differences") and troubleshooting about neighbors. Deny a stronger claim ("…does not guarantee…") only when the source makes that point or a common misconception holds it.

  **Check scope before a claim becomes canonical.** A worked case is not a universal property, nor is a claim taken from one figure or caption, one model's or organism's section, or one configured library example: state the general fact from standard references, or that scope when no general fact holds. Test *always*, *only*, *guaranteed* and *requires* against the source's assumptions, state the accurate scope, and never copy a suspect guarantee into the description or card. Keep a well-established superlative the source states (the thinnest cytoskeletal filament) or attribute it; drop an unsupported one. Tie software behavior to the version or date the source establishes, never *currently* or *recently*; a progress or trend claim ("is becoming", "are being extended") gives way to the settled fact standard references confirm, or goes. Claims agree across the note and with linked neighbors ([contradiction check](#editorial-reread)). Source fidelity does not settle factual accuracy.

**4. Coherent prose, with one local purpose per paragraph.** The body reads as a unified explanation, not a stack of related facts. Each paragraph answers one reader question or develops one controlling idea, and each of its sentences defines, explains, supports, qualifies, contrasts, exemplifies or draws a consequence from that idea; sharing the entry's subject is not enough. A causal chain from mechanism to condition to consequence can remain one paragraph. Run the [flow sweep](#editorial-reread) on every paragraph.

  When the reader's frame genuinely changes, use the right boundary: a new paragraph for another inherent facet, a `##` heading when it needs several paragraphs, a linked note when the new subject passes the atomicity test.

  **Transitions carry meaning.** Name the relationship between ideas when adjacency or a repeated key term leaves it unclear. Add *therefore*, *because* or *in contrast* only when the evidence establishes that relationship; stock connectors (*also*, *however*, *meanwhile*) never repair an unrelated jump, so with no supported bridge, reorganize.

**5. Self-contained, with no open questions.** Explain the subject to a reader who has never seen the sources, and leave no open question: every term, claim, number, complexity or equation the entry states is explained, here or in a linked entry. Define a term on first use unless it has its own entry; then link it instead of re-explaining it. A complexity, iteration bound or derivation result carries its reason, and a formula the entry names is given ([equations §1](equations.md#1-coverage--explanatory-value-before-notation)). A reason for why a result holds is one sentence of intuition; a restated claim is not a reason, and no proof sketch is required. A term that would need its own explanation and has no entry gets its own entry (or a missing-entry report), not a digression here. Avoid document navigation such as “recall from the source.”

  **(a) Source-meta phrasing.** Never refer to an unnamed *paper/chapter/book/article/author(s)/source*, *this source*, *as mentioned/discussed/shown above/below/earlier*, *the previous section*, *as we saw* or *the figure above/below*. Name the subject, a person or a work treated as an entity instead: “the authors of SGDR recommend …” and “the GPT-3 paper” have a referent; bare “the authors” does not.

  **(b) Biographical-attribution drift.** Keep real attribution (“Loshchilov and Hutter recommend …”, “introduced by Gupta et al. in 2018”) without drifting from a named person into “the authors”.

  **(c) Framing-attribution drift.** “In Géron's framing …” or “Prince's book groups …” describes an exposition, not the concept: state the supported relationship directly, keeping attribution for who did the work, and choose the clearest scope-preserving framing when expositions differ. Factual disagreement follows [conflict handling](merge.md#conflict-handling).

  **(d) Source-internal references.** “The case study” or “the OECD life-satisfaction example” assumes context the reader lacks: introduce an example that passes principle 7 briefly inline, or omit it. “The dataset”, “the districts”, “the detector” or “the valley” is valid only after this entry establishes its referent.

  **(e) Acronyms are introduced in parentheses after the full form on first use, then used thereafter:** "the **$\boldsymbol{k}$-nearest neighbors** algorithm (KNN)…", then "KNN". This covers every short form the body reuses, the entry's own aliases included (`aliases:` introduces nothing to the reader). **The subject always shows its common acronym ↔ full-form counterpart on first mention** (`**Principal component analysis** (PCA)`, `**standard deviation** (SD)`), reused or not and whether or not the source prints it; other terms get one unless obscure or never reused. The parenthetical sits **outside** the title's bold span.

  **(f) Acronym-titled entries invert (e):** `**DBSCAN** (Density-Based Spatial Clustering of Applications with Noise) is…`. A `Person` or `Event` puts its date first: `**ILSVRC** (2010–2017) (ImageNet Large Scale Visual Recognition Challenge) was…`. Whichever form the title takes is bolded first; the other is annotation.

  **(g) Contested topics.** Competing views on a genuinely contested topic follow the [contested-topic exemption](merge.md#conflict-handling); (a)–(d) otherwise apply.

  **(h) Background beyond the source is welcome when it helps.** Add accurate information the source does not state whenever it makes the entry easier to understand: a definition or expansion the source assumes, a standard formula or its common variant, a well-known fact or date, or the context that connects the idea to its field. A distinction the note never uses, or background that needs more than one new term with no entry, is reduced to its point or left out. Keep it at the level of standard references and leave out anything speculative, disputed or uncertain; when unsure whether it is accurate, omit it. Background needs no citation and does not change `sources:`. What the entry takes from its source (claims, conditions, numbers and scope) must still match it unless [conflict handling](merge.md#conflict-handling) (in wiki-lint's content repair, its [Conflicts](../../wiki-lint/references/source-backed-corrections.md#correct-and-publish) rule) shows it wrong, and an accurate claim is never removed merely because a cited source does not state it. It invites explanation, never the caveats principle 3 excludes.

**6. Remove padding without compressing away meaning.** Cut empty lead-ins, reader commentary, rhetorical hedging and repetition that adds no distinction; prefer a direct statement to praise or metaphor. Keep useful signposting, technical terms and evidence-bearing qualifiers. Keep the entry on its subject: omit source recaps and scaffolding, tangential motivation, application catalogs, anecdotes, the author's preferences and implementation recipes ([API surface](api-surface.md) governs Software). A neighboring concept gets its relationship and a link. Discovery history, the experiment that revealed the subject and the instrument through which the source met it stay only when they explain what it is or how it works; otherwise keep one clause at most, and never repeat the same history in a sibling entry (Person, Event and Work entries are exempt); an argument or worked example likewise lives only in its owner under the atomicity test. Concision alone never authorizes removing substantive content from an existing note; the merge, ownership-handoff and source-backed repair rules govern that.

**7. One concrete case when it makes the idea click.** For an abstract, quantitative or procedural concept, add one compact example of one to three sentences after the mechanism it illustrates: small numbers put through the defining formula, a two- or three-step trace, or one familiar instance (the webbing between developing fingers, for apoptosis). Prefer the source's own worked values when they illustrate the subject itself and one clause can set them up; otherwise, as when they need the source's dataset columns, preprocessing or library configuration explained, use a standard textbook case, or round numbers whose every result you have checked, never presented as a measurement. Skip the example only when the definition already names a concrete instance; a second example must show a different facet, and an example that only restates the definition with a number (a fraction of 0.25 means 25%) is left out. Quantitative facts that characterize the phenomenon (random points in a unit square lie about 0.52 apart, in a million dimensions about 408) and what a parameter does at its extremes (a predictor no better than chance gets zero weight in the vote) are explanation, not examples. A category concept names its canonical members instead, under the core-facet check. Never write a multi-paragraph walkthrough, an application story, a roster of source data, or an example that mostly teaches a neighbor. An example uses only steps the note or a linked entry explains; when it needs another, choose a simpler case rather than teach the step.

**8. Mathematics earns its place by explaining the concept.** Equations follow [equations.md](equations.md): math appears only when it explains better than prose, the defining relation comes first, and each defining display is explained in words.

  **Numbers in body prose: LaTeX for math, plain text for everyday quantities.** A math object takes LaTeX: class labels (`$\{-1, +1\}$`), indices and subscripted values (`$x_1$`, `$\sigma^2$`), numbers in or referring to an equation, and bounds (`$0 \le p \le 1$`); if you could substitute a variable, it is math. Counts, dates, page numbers, informally reported parameter values ("learning rate of 0.001"), everyday percentages and currency stay plain, as does a named-digit metric's digit (`F1 score`, never `$F_1$` outside an equation), while `$k$-fold` keeps its variable in LaTeX. **Decorative `$...$` wrapping is wrong:** every pair opens a math region and invites parser collisions.

  **Escape literal `$`** as `\$` in body prose (currency, regex anchors, shell prompts, environment variables); Obsidian pairs unescaped `$` characters as math and garbles the text between them.

**9. Clear sentences — one main idea when possible.** Use concrete subjects and precise verbs. Make the referent of *this*, *these*, *such*, *it* or *the former* unambiguous, within its own or the previous sentence; repeating a short technical term can beat a pronoun. Split an overloaded sentence where the thought divides: reread at reading speed any sentence carrying two or more inserted asides (appositives, dash pairs, parentheticals) or more than one *which* or *where* clause, and if a reader must reread it, give the inserted definition or reason its own sentence. A single one-clause gloss of a term is no overload, and a clear longer sentence is fine. A garden path is a defect. Read equation lead-ins and continuations as part of the sentence, so a display leaves no fragment or broken join.

### Editorial reread

After drafting or editing, reread the passage and its neighbors as one
continuous explanation: clear referents, useful order, natural transitions and
concise wording, around equations and exhibits too. After a removal or move,
reread the whole note against its pre-edit text; wiki-lint's Task 1b does
this once per changed entry, in its
[final reread](../../wiki-lint/SKILL.md#task-1b--content-repair). Nothing may
point at a deleted passage (a referent, a caption, the names an example
kept), a moved passage leaves both places in order (a worked result stays
after its setup), and an added sentence says nothing an adjacent sentence
already says. Then run these sweeps on the description, body, captions and
card of each entry drafted or changed, and fix regressions before saving:

- **Scope check.** Compare against the source or pre-edit text for changed
  meaning (an illustration turned general rule, a cause or actor swapped, a
  small effect that lost its degree, a qualifier drifted onto another claim)
  under [principle 3](#prose-principles).
- **Contradiction check.** Compare each claim with every other claim in the
  note, and with each linked neighbor that states the same defining sense,
  name, relationship, direction, number, unit, count, scope or preference
  (open it to compare), and reconcile them; a part, quantity or relation
  takes a name its owner entry or the field uses (intercept, not height), and
  a value its owner's unit (200 nm, not 0.2 µm). A source's own tension (a tip against its
  body text) becomes one claim with the condition that decides between them;
  when no condition decides, it is a conflict, never two rules. Report a
  conflict you cannot resolve, with its page; a conflict with existing
  content, a neighbor's included, follows
  [conflict handling](merge.md#conflict-handling).
- **Hedge sweep.** Find each hedge [principle 3](#prose-principles) lists and
  each caveat or clarification it excludes (edge cases, availability hedges,
  defensive distinctions). Keep one only where the plain claim is false for
  the ordinary case, and then name the condition; drop one that covers only
  an edge case, even when the source or its caption makes it ("precision
  generally rises" becomes "precision rises"). `lint_entry.py` flags common frequency hedges in the description
  and card line 1 as review candidates (`7-hedge-candidate`,
  `19-hedge-candidate`); the sweep still reads the rest.
- **Flow sweep.** Label each paragraph's job in a few words, one-paragraph
  bodies included, and check that each sentence advances it and passes
  [principle 9](#prose-principles)'s reading-speed test. A label that
  needs "and" between unrelated jobs means the paragraph splits, or the stray
  sentence moves beside the material it develops or goes. Never force topic
  sentences, fragment a continuous explanation into one-sentence blocks, or
  judge flow by paragraph length. The note ends on a consequence, the main
  limitation or the nearest contrast when the subject has one; never add one
  to end on. Any other closing sentence or final one-sentence paragraph that
  opens a new point (a history point, statistic, application or API family)
  is a stray, which moves or goes. Material that
  [principles 6 and 7](#prose-principles) leave out (a second example of the
  same facet, an application list, a data roster, an anecdote, an instrument
  view, a library recipe) goes whatever its source support, as does a
  sentence that would not be there had the subject come from another
  textbook. A passage whose subject is a linked entry's (its mechanism,
  worked example or exhibit, or a segue into its topic) goes too, leaving
  only what the [atomicity test](#body-structure) keeps here. When that entry
  clearly owns it and lacks it, the passage moves there; wiki-build moves it
  only into this run's entries and otherwise logs a
  [proposal](review.md#overlapownership-audit-this-runs-entries-and-their-relevant-neighbors).
  No claim recurs, within a sentence or across sentences and paragraphs:
  outside the opener and the plain-words summary that teaching order calls
  for, a sentence that only previews claims the following sentences explain
  goes.
  A caption follows [captions](media.md#captions) instead: it never restates
  the sentence it follows. Then read only the opening sentences and check
  that each idea is established before use.
- **Term audit.** Every technical term, number, causal or comparative claim,
  complexity, iteration bound and derivation result is defined, linked to an
  entry that states it (open the target when the sentence leaves the reason
  to the link), or given its reason ([principle 5](#prose-principles)), terms
  in background or corrections the builder added included, and every example
  states the point it shows. A first mention of an entry's concept in a form
  no claimed surface names (a verb or derived form, a head noun, a
  paraphrase) is a [link candidate](#what-earns-a-wikilink), on Task 2's
  worklist in wiki-lint; one that clears the bar links its first later
  claimed form, or is reworded under the
  [label rules](#display-label-casing). A result no accurate reason supports is suspect, not
  unexplained: never invent a reason. Resolve it as a conflict
  between its source and the other evidence under
  [conflict handling](merge.md#conflict-handling) (in wiki-lint's content
  repair, its [Conflicts](../../wiki-lint/references/source-backed-corrections.md#correct-and-publish) rule, which also reads standard
  references online), keeping the source's figure
  only within the scope that makes it true, stated in one clause (with each
  feature presorted), never with an alternative implementation's cost; while
  the evidence settles
  nothing, omit the figure, keep its practical takeaway, and report and log
  it there.
- **Opener check.** The opener shows the subject's acronym ↔ full-form
  counterpart (5(e)–(f)). Description, opener and card state what the subject
  is, in one sense that the body and linked neighbors using the term share (a
  disagreement is a [neighbor conflict](merge.md#conflict-handling)); the
  opener's kind, named or made plain by its verb, matches card line 1's, and
  the opening paragraph names no variant, secondary sense or other
  application ([principle 1](#prose-principles)). Every idea the opening
  paragraph introduces is explained by the end of the next paragraph (a term
  is still defined or linked on first use), and the property or benefit the
  description and card define the subject by appears in the opening
  paragraph.

Editorial standards never independently authorize changes to cards, dates,
review state or other protected content, or rewording a clear passage.

---

## 3. Wikilinks and naming

### Link form

In body prose, use `[[slug|Display text]]` when the display differs from the slug (case, spacing, alias or other rendering) and `[[slug]]` only when they are identical; the [Related footer](#the-related-footer) always pipes. [CONVENTIONS §6](../../../shared/CONVENTIONS.md#6-wikilink-forms) owns the forms. In body prose:

- **First eligible occurrence only.** After [link-worthiness](#what-earns-a-wikilink), link only the first eligible mention of each entity. **Possessive, partitive and modifier references count** (`[[barack-obama|Barack Obama]]'s first term`, `the [[percentile]] interval`); a mention inside LaTeX cannot carry a link, so the first **prose** occurrence outside math gets it. A word inside a compound that is itself another entry's title or alias belongs to that entry: link the compound, never its head or modifier (`[[messenger-rna|messenger RNA]]`, not `messenger [[rna|RNA]]`). Count by the entry a link resolves to, not its spelling: `[[label-machine-learning|labels]]` then `[[label-machine-learning|target]]` is one entry twice, as are path, explicit-`.md`, case/Unicode variants and an unambiguous alias beside its canonical slug. Collapse path spellings only when the vault inventory proves one owner; when several files share a basename, distinct qualified paths stay distinct and repeated bare or ambiguous-alias links are kept until ownership is resolved. Keep the first resolved occurrence and unlink the rest to bare text; the Related footer is a separate slot and is exempt.
- **Integrate the link into the sentence that explains the relationship,** never a navigation-only `see [[…]]`, `(see [[…]])`, `refer to [[…]]` or `consult [[…]]`; a purely navigational link belongs in the Related footer.
- **No wikilinks in image captions, table captions or table cells**, and **no self-links**: the entry's own subject is **bolded** at its first body appearance ([Bold Pattern 1](flashcards-and-emphasis.md#5-bold-and-italic)), never linked.
- **Path qualification.** Use the extensionless vault-relative public path only when another real file, including one outside the Wiki index, owns the bare name ([§6](../../../shared/CONVENTIONS.md#6-wikilink-forms)): `[[Wiki/statistics|Statistics]]` beside a previous-layout `MOCs/statistics.md`, never a scratch path; keep a required qualification, and never guess an ambiguous owner or drop it as a dangler.
- **Annotations and code are not prose.** Preserve hidden HTML (`<!-- … -->`) and Obsidian (`%% … %%`) comments; they, escaped wikilink examples and code samples are never link candidates or orphan-check material, and cards keep their own format rules.

### Display-label casing

Labels follow standard English: proper nouns and acronyms keep canonical case (`[[mnist|MNIST]]`); in body prose, common nouns are lowercase mid-sentence and Sentence case at a sentence start. A [Related-footer](#the-related-footer) label is always the target's canonical title verbatim, in its plain form for a mathematical title (`[[k-nearest-neighbors|k-nearest neighbors]]`, never `K-nearest neighbors`). **A source's alias form stays in the label** ("TPR" becomes `[[recall-machine-learning|TPR]]`).

**A label must be a surface form the target's `title:` or `aliases:` claims,** apart from four carve-outs that must not be "fixed":

- A context-resolved [cross-domain](special-titles.md#cross-domain-term-disambiguation) bare term: the title's head word (`[[information-entropy|entropy]]`), or a modifier or synonym the target introduces in italics (`[[transformer-architecture|transformer]]` once its opener says *transformer*). The checkers recognize a synonym only for words in the cross-domain corpus.
- A natural plural or verb inflection.
- A derived adjective or agent noun of the title's head word that keeps its other words (`[[eukaryote|eukaryotic]]`, `[[binary-classification|binary classifier]]`).
- An Organism's complete common name that the target's description or opener binds to its title (`[[mus-musculus|mouse]]`, never `fly` from `fruit fly`).

Never add a common name as a global alias just to permit a link. Reword any other invented, subset or superset label to a claimed form, or add a genuine alias; a label keeping only the title's modifiers (`[[greedy-algorithm|greedy]]`) is a subset unless the target defines that word as a term. A label naming another entry's title or unambiguous alias signals a target conflict: review it, never silently retarget.

**Display labels are plain text** (no LaTeX, bold, italic or backticks); a mathematical title's label uses its [plain form](special-titles.md#base-term-and-mathematical-plain-forms).

### What earns a wikilink

**The wikilinking decision uses the same substance bar as entry creation.** Link a mention only when the reader would genuinely benefit from jumping to that entry; passing mentions and bare name-drops stay plain even when the slug exists, while a named entity whose mechanism the source teaches is a candidate under the [positive trigger](../SKILL.md#2-extract-entities).

**A discipline root is rarely a body link.** It is already each member's ancestor through `parents:` and the MOC; link it only where the passage discusses the field itself. Naming the entry's own field as its setting or genus ("in machine learning, …") is a passing mention, and a compound ("molecular biology") does not name the root.

**Every entry wikilink target in body prose and the Related footer must be a real file in `Wiki/`**, existing or written this run; otherwise the mention stays bare text, with **no placeholder files, ever**. Existing MOC navigation and `parents:` follow their own rules.

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
issues: ""
---
**LambdaRank** is a [[learning-to-rank|learning to rank]] method that sidesteps the non-differentiability of ranking metrics by defining gradients directly, scaled by the change in the target metric from swapping a pair of items.

It starts from [[ranknet|RankNet]]'s pairwise cross-entropy loss. For items $i$ and $j$, it multiplies RankNet's gradient $\lambda_{ij}^{\text{RankNet}}$ by the absolute change in [[ndcg|normalized discounted cumulative gain]] (NDCG) from swapping the two items in the current ranking, $|\Delta\text{NDCG}_{ij}|$, giving the LambdaRank gradient $\lambda_{ij}$:

$$
\lambda_{ij} = \lambda_{ij}^{\text{RankNet}} \cdot |\Delta\text{NDCG}_{ij}|
$$

![[Burges_LearningToRank_2010_fig_3.png]]
*Pairwise gradients on one ranked list, before (left) and after (right) scaling by $|\Delta\text{NDCG}|$.*

Swaps involving top positions, where NDCG is most sensitive, change the metric more, so those pairs receive larger updates than pairs deep in the list. LambdaRank defines only these gradients and never writes down an explicit loss.

**Related:** [[ranknet|RankNet]] · [[lambdaloss|LambdaLoss]] · [[ndcg|NDCG]] · [[pairwise-ranking|Pairwise ranking]] · [[learning-to-rank|Learning to rank]]

---

## Flashcards

The learning-to-rank method that multiplies each item pair's RankNet gradient by the NDCG change their swap would cause.
??
LambdaRank
```
