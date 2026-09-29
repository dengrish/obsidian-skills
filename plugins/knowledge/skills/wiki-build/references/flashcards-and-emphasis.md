# Writing an entry — flashcards, bold and italic

> Scope: the card format and card set (§4) and bold and italic (§5). Rewrite bars for existing cards belong to wiki-lint's [flashcard maintenance](../../wiki-lint/references/flashcards.md).

---

## 4. Flashcards

### Card shape

The `## Flashcards` section ends the entry. After the Related footer come a blank line, `---`, a blank line, the heading and a blank line, then the card:

```markdown
**Related:** [[…]] · [[…]] · [[…]]

---

## Flashcards

<line 1: the cue>
??
<line 3: the answer>
```

A card is three content lines with no blank line between them. The vault's Spaced Repetition community plugin reads these cards, so the format is a contract with that plugin; no skill runs it or can check that it ran. Its deck setup is in the plugin README under *Reviewing flashcards*. The plugin parses the whole note, so no line of the entry, card lines included, holds its single-line card separator `::` (or `:::`) outside code, or is only `?` or `??`, which would turn that line or its paragraph into a card of its own: keep code in a backtick span or a fence opened and closed at the start of its lines, and write a math `::` as `\mathbin{:}\mathbin{:}`.

### Line 1: the cue

Line 1 is the definition a learner recalls from the term and the cue that leads back to exactly one term. It is one sentence with a capitalized first word and a final period, about 20 words outside math.

**Kind plus essential property.** Line 1 reads naturally after `<term> is`: it names the kind of thing (method, metric, organelle, model organism) and the one property that sets it apart, such as its mechanism, function, defining relation or significance. A Person's cue states the contribution; an Organism's, what it is and why it is studied; a Device's, how it works; a Dataset's, what it contains and benchmarks. Never discriminate by a measurement, date, count, etymology or anecdote unless that number is the identity (MNIST's 28×28 digit images). State the ordinary case plainly under [principle 3](writing.md#prose-principles): no hedge, exception, minority case or trailing semicolon clause. When the plain property is false for the typical case, choose another essential property.

**Sibling check.** Before finalizing line 1, read line 1 of the closest existing cards: the entry's Related targets and the other members of its family. Confirm that the new cue fits none of them; a Bagging cue must not also fit Boosting. Do not name the neighbours. Within a family of variants, reuse the family's lead phrase and put the one differing property early: "The gradient descent variant that computes each update from a single randomly picked training instance."

**Leak-free.** Line 1 never contains the answer: the title or its base term, an alias, or the line-3 counterpart, compared after normalizing Unicode, case, punctuation and whitespace. Component words of a compound title stay allowed; a Key-value cache cue may say "keys and values". A cue also leaks when it rebuilds the name by expanding an acronym ("machine learning operations practice" for MLOps), reordering all its words, or swapping a synonym into each word of the title or an alias; state the cause or mechanism instead. When the name is itself the definition (Mean absolute error), an easy cue is acceptable.

**Markup.** No Markdown or HTML: inline LaTeX is the only markup line 1 accepts, under [line-1 equation coverage](#line-1-equation-coverage).

### Line 2: the separator

Line 2 is exactly one of two values, alone on its line:

- `??`: the plugin's reversed card, reviewed from cue to answer and from answer to cue, with one schedule per side. Never simplify a card's `??` to `?`, which the plugin reviews in one direction only; that halves the card and strands its second schedule.
- `!!` on a card the user has disabled. Only the user writes `!!` or restores `??`, and every workflow preserves it.

wiki-build writes `??` and never writes `!!`. When the primary card carries any other line 2, such as `?`, restoring its `??` is the one change to a separator a workflow makes; a legacy extra card keeps its separator (see [card set](#card-set)).

### Line 3: the answer

Line 3 is the entry's canonical title as plain text: `title:` verbatim, the base term of a parenthetical-disambiguated title (`Feature`, not `Feature (machine learning)`), or the meaning-preserving plain form of a mathematical title (`k-nearest neighbors` for `$k$-nearest neighbors`; see [plain forms](special-titles.md#base-term-and-mathematical-plain-forms)). It takes no markup of any kind, LaTeX included. Attachments are not answer markup; plainness never removes them.

Append one counterpart in parentheses only when the opener binds it directly to the title and its slug is in `aliases:`. Three bindings qualify: an acronym and its full form (`**Principal component analysis** (PCA)` gives `Principal component analysis (PCA)`), a `(short for *…*)` expansion (`AdaBoost (adaptive boosting)`), and an italic scientific abbreviation (`Escherichia coli (E. coli)`). Nothing else goes in parentheses: not a spelling variant, plural or related form, and not a synonym's abbreviation (`Precision` stays `Precision` although `ppv` abbreviates *positive predictive value*).

### Card set

Every entry has exactly one card: the reversed `??` definition card, testing the entity's main claim (the scope of the body's opening sentence). A [discipline root](../../wiki-lint/references/hierarchy.md#establish-discipline-roots) needs none, and an existing root card stays.

A second card never belongs to an entry: a second source-supported entity earns its own entry, and a further claim about this one belongs in the body. The **primary card** is the entry's only card or, when it holds several, the one whose line 3 meets the [answer contract](#line-3-the-answer) (else its one near miss), wherever it sits. Any other card an entry already holds, such as a second definition card or a question card from an earlier card set, is a **legacy extra**. Every workflow preserves it byte-for-byte, attachments included, and reports it, and the linters mark its findings report-only; only an authorized refactor or a request naming it for deletion removes it ([flashcard maintenance](../../wiki-lint/references/flashcards.md#card-set)).

### Line-1 equation coverage

**Line 1 is verbal by default.** It carries math only when the definition itself is a short standard expression a learner should memorize, such as $\text{TP}/(\text{TP}+\text{FP})$ or $\sqrt{\operatorname{Var}(X)}$. Write it inline in the body's notation or an equivalent compact form with `$…$` on the same physical line, name its symbols with role words in the same phrase rather than a *where …* glossary, and drop an answer-name left side such as `\text{precision} =`, keeping a neutral symbolic left side only when it does not reveal the answer:

```text
The share $\text{TP}/(\text{TP}+\text{FP})$ of true positives among all positive predictions.
```

A lone symbol never substitutes for the relationship being tested. The expression is complete (an Lp norm keeps its p-th root) and carries only the conditions that define the concept, without well-definedness boilerplate or index bounds that run over every term; card lines are exempt from the equation guide's condition list. A defining formula too long for one line stays in the body, and line 1 states its verbal core.

An existing card's long formula may give way to its verbal core when the formula stays in the body; the tested concept is unchanged.

### Scheduling attachments

wiki-build writes only the three content lines. After review, the plugin may attach scheduling state to any card in one of three recognized forms:

- on line 3, after the answer: `<answer> <!--SR:…-->`;
- starting on the line directly after line 3: one or more whole-line `<!--SR:…-->` blocks, each ending at a line-final `-->`;
- starting there: the exact callout `> [!sr|card-metadata]`, whose quoted body holds the `<!--SR:…-->` schedule.

A card may also carry a trailing Obsidian block ID such as `^roc-card`, an inbound-link anchor: after a same-line or callout schedule, or after the answer when the schedule follows separately. **Every recognized schedule and block ID is user-owned: preserve its bytes and position verbatim, and never move it between cards.** A blank line ends the attachment position, so an SR-looking block after it stays visible for repair; other content after line 3 is malformed. The plugin may store schedules outside the note, so absence of attachments alone proves nothing about a card's history. The shared parser `entry_structure.py` hides attachments only from its read-only lint view and never rewrites them.

---

## 5. Bold and italic

Bold and italic carry meaning, not decoration, and the rules are mechanical so a reviewer can audit them. **The reviewer test:** if the answer to "why is this bold/italic?" is not one of the patterns below, the styling is decoration and goes. Inside a Markdown table cell, `**bold**` and `*italic*` are ordinary formatting and are not audited; the patterns govern body prose.

**Bold (`**...**`) is reserved for these uses, no others:**

1. **The entry's title on its first body appearance**, in its canonical form verbatim. A parenthetical-disambiguated title bolds its [base term](special-titles.md#base-term-and-mathematical-plain-forms), and a symbol-bearing title bolds its math form under the [math-bold rule](special-titles.md#base-term-and-mathematical-plain-forms). **A determiner or short lead-in may precede the bolded span** (`An **attention mechanism** is…`, `In vertebrates, **hemoglobin** carries…`): grammar wins over position, so `**Attention mechanism** is a dictionary lookup…` is wrong, and the lead-in never licenses the preamble principle 1 bans. Acronym-titled entries follow principle 5(f). `Work` titles and evidence-backed scientific `Organism` titles combine this bold with italics under the [typography rules](rare-types.md#typography-for-works-organisms-and-genes); other titles are bold-only (`**LambdaRank**`, `**Yann LeCun**`).
2. **Bullet-list term anchors** in the `- **Term** — definition` pattern, where the bolded term is the subject the bullet defines.
3. **The `**Related:**` footer label**, always.

**Synonyms are italicized, never bolded** (Italic Pattern 8); only the canonical title is bolded. Italicize an alternate name that a synonym trigger introduces for this entry's subject: "also called X", "known as X", "(short for X)", "or X" ("**Normal distribution**, also called the *Gaussian distribution*…"; "**Bagging** (short for *bootstrap aggregating*) is…"). An annotation stays plain: a bare acronym parenthetical, or the expansion of an acronym-titled entry ("**LSTM** (long short-term memory) is…", "**Mean squared error** (MSE) is…"). Later uses of an introduced alias are bare. **Every synonym this pattern introduces is an `aliases:` candidate**; one missing from the YAML is a checklist item 17 violation under the [alias completeness rule](writing.md#aliases).

**Bolded paragraph-leads are not section signals.** Paragraphs opening with `**Architecture.**`, `**Pretraining.**` or a named variant such as `**ResNet v1**` or `**Stage 1**` are de-facto headings. Run the atomicity test instead: a source-supported concept with its own identity becomes a linked entry, an inherent facet becomes a `##` heading under [body structure](writing.md#body-structure), and a term one clause can explain is introduced inline in italics.

**Vocabulary-introduction bolding is never allowed.** A newly introduced term takes italics (Italic Pattern 1) when it has no entry and a wikilink when it does: `**weight sharing**` becomes `*weight sharing*`, and `**softmax function**` becomes `[[softmax-function|softmax function]]`. A bolded span that is not Pattern 1, 2 or 3 is decoration.

***Italic (`*...*`) is reserved for these uses, no others:***

1. **Defining a vocabulary term inline**, the first time the entry names a term it then uses unannotated ("points lying in dense neighborhoods, called *core points*"). Terms with their own entries are wikilinked, not italicized.
2. **Named heuristics, rules or principles** referenced inline rather than used as a structural anchor (`*regression to the mean*`, `*68-95-99.7 rule*`).
3. **Source-established named phrases and expressions cited rather than used** ("the *AlexNet moment* for NLP" when the source itself presents that wording as a name, or a sentence discussed as a sentence). Direct attributed quotations stay in double quotes, a writer's paraphrase stays plain, and a colorful label is never invented or italicized to enliven the entry.
4. **Image and table captions in their entirety.**
5. **Titles of works without their own entries** (`*Hands-On Machine Learning*`); works with entries are wikilinked, and a Work entry's own title follows the [typography rules](rare-types.md#typography-for-works-organisms-and-genes).
6. **Emphasis on a single critical word** that changes a sentence's meaning ("evaluate *only once*"), used sparingly.
7. **Scientific binomials and unranked lowercase trinomials** (*Escherichia coli*, *Homo sapiens*), while strain suffixes, common names and descriptors stay plain (`*E. coli* K-12`). The Organism self-title forms and the evidence test are in the [typography rules](rare-types.md#typography-for-works-organisms-and-genes).
8. **Aliases or alternate names of *this* entry introduced inline as synonyms**, as above.
9. **Gene and allele symbols** only where the organism's nomenclature authority requires italics; when the identity or convention is unresolved, keep the existing styling and report it ([gene symbols](rare-types.md#typography-for-works-organisms-and-genes)).

**What never gets bold or italic:**

- **Mathematical symbols, variables and Greek letters used as symbols:** use LaTeX (`$k$`, `$\theta_0$`), never `*k*` or `**k**`. A Greek letter inside an ordinary name (`α helix`) is plain Unicode text and takes the name's own styling.
- **Library, API, file-format and code identifiers:** backticks (`` `Pipeline` ``, `` `.ipynb` ``), and only where the identifier may appear at all: API identifiers live only in `Software` entries, and library names are never backticked ([API surface](api-surface.md)). Bracket special tokens (`` `[CLS]` ``, `` `[MASK]` ``, `` `[SEP]` ``, `` `[IMG]` ``) are always backticked in body prose, because bare brackets collide with Obsidian's wikilink syntax.
- **Wikilinks:** the link is the styling, so `*[[entry-name|Display Label]]*` is forbidden.

**Bold versus italic for named patterns.** A named pattern, heuristic or rule that anchors a paragraph or sub-block gets a `##` heading (`## 68-95-99.7 rule`); one referenced in passing is italic (Italic Pattern 2); bold is never an option. The same rule styled differently in two entries means one is wrong: the `68-95-99.7 rule` is inline in `normal-distribution`, so the mention in `standard-deviation` should match.
