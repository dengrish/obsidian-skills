# Equations — coverage, form, notation, normalization

> **When to read this:** the source states **or describes in words** any equation, calculation, or symbolically defined quantity, and this run will write or merge an entry that covers it — **or the run merges into an entry whose body already carries an equation**, which must be preserved, moved, or normalized under §4 whatever the new source brings. Read it before typesetting the first equation of the run. A run whose sources carry no math, merging into no entry that does, never needs this file.

This file owns four rules: **coverage** (when an entry gets an equation), **form** (display vs inline), **notation** (the vault's symbol standard), and **normalization** (rewriting a source's equation into that standard). Prose principle 8 in `references/writing.md` §2 carries the summary; this file is the full rule. Two neighboring rules deliberately stay where they are and are not restated here: the numbers-in-prose rule and literal-`$` escaping live in `writing.md` §2 (under principle 8), and the multi-form `\begin{aligned}` layout lives in [edge cases](edge-cases.md#multi-form-equations).

## 1. Coverage — a described calculation is a provided equation

**The source need not typeset a calculation for the coverage rule to fire.** When the source defines, characterizes, or quantifies a concept with an equation, the body includes that equation (principle 8). The same holds when the source only *describes* the calculation in prose: "subtract the mean and divide by the standard deviation" states the standardization formula as fully as any typeset line, and the entry must render it as one:

$$
x' = \frac{x - \mu}{\sigma}
$$

Leaving it as prose ships the observed corpus failure: a `Standardization (machine learning)` entry that walks through the computation in words and shows no equation, sitting beside `RMSE` and `MAE` entries that typeset theirs — the vault's math coverage tracking each source's typesetting habits instead of its content.

The same rule covers a source saying that standard deviation is the square root of variance:

$$
\sigma = \sqrt{\operatorname{Var}(X)}
$$

Bind $X$ and $\operatorname{Var}(X)$ in the nearby prose. Do not expand the variance into a denominator the source does not choose: a general statement of this relationship does not by itself say whether the context uses a population or sample variance.

**The bar: the source's words must determine the equation.** Every operand and operation is recoverable from what the source says — the words pin down the math, and the equation states exactly what the words state, in the vault's notation. What the source leaves genuinely underdetermined is not filled in from background knowledge: a source saying only that "a correction factor is applied" or that "the score balances precision against recall" has gestured at math, not stated it, and a gesture gets no equation. (Choosing the standard *symbols* for quantities the source names is notation, not imported content — §3 exists precisely so that choice is not re-made per entry.)

**A special-case equation keeps its conditions attached.** A source may explain a general concept through one loss function, distribution, or other restricted case. State that condition in the sentence introducing the display and keep the description, opener, and flashcard at the concept's actual scope. For example, squared-error gradient boosting fits residuals because those residuals are the negative loss gradient in that case; residual fitting must not become the unqualified definition of gradient boosting. If the source supplies only the special case, present it explicitly as an example or qualified case rather than silently generalizing it.

**A formula keeps the conditions that make it defined.** Bind domains and boundary cases beside the display: counts behind averages and empirical ratios must be positive; other denominators must be nonzero; logarithm arguments and bases must be valid; roots and powers keep their real-domain conditions; integer indices, class counts, and hyperparameters state the ranges the formula assumes; probabilities state normalization and what happens when positive target mass receives zero estimated probability; fitted normalization statistics say which data estimates them and how later data reuse them; threshold and piecewise rules say where equality goes; and an `argmax` or `argmin` that can tie names a deterministic or implementation-defined rule. Keep an exact mathematical definition distinct from a numerical approximation: if software replaces a singular value, zero probability, or other boundary with a tolerance or clipping rule, name that rule as implementation handling rather than silently building it into the definition. If the source does not choose an operational convention for an undefined boundary, state the mathematical limitation and leave the implementation choice explicit rather than inventing one. These qualifications are part of the equation's meaning, not optional commentary.

The post-write linter and the whole-vault scanner share `shared/scripts/equation_coverage.py`, a conservative mechanical candidate floor built from corpus failures. It recognizes affirmative square-root-of-variance definitions; defining equalities or substantive expressions left inline after cues such as “written as,” “similarity is,” or “starts with weight”; and a short list of complete prose calculations such as averaging probabilities, taking a named fraction, normalizing by a row total, or decomposing a quantity into a sum. A prose cue is cleared only by a nearby following display block that contains the covering operation — an unrelated equation does not suppress it — while an inline defining formula is reported for its placement even if the note has other displays. For the square-root cue, variance itself must be the root operand, either as `\operatorname{Var}(X)`, an established squared standard-deviation symbol, or a recognizable average of squared deviations; merely placing unrelated root and variance terms in one display is not coverage. Every result remains an agent-review candidate: the helper never generates LaTeX, decides semantic ownership, or replaces the full semantic coverage pass. In particular, the square-root cue never licenses choosing a population or sample denominator.

The rule reaches every formal definition, named quantity, metric, loss function, probability law, rate, or fraction the source states by either route. A concept the source treats purely qualitatively takes no equation — this file adds no math the sources don't carry.

## 2. Form — defining equations are display math

**The equation that defines the entry's subject or a named quantity sits in a `$$…$$` display block**: `$$` alone on a line, the equation on the line(s) between, `$$` closing, and a blank line above and below the block. Obsidian renders the block centered on its own line — the required presentation for anything a reader would call the entry's key result. Multiple equivalent forms of one quantity share one block under the `\begin{aligned}` rule in `references/edge-cases.md`; two genuinely different quantities get two blocks, each beside the prose that motivates it.

**Inline `$…$` is for math woven into a sentence** — symbol references ($\sigma$, $m$), short expressions ($p \ge 1$, $O(n \log n)$), sets and bounds ($\{-1, +1\}$, $0 \le p \le 1$) — never for the defining equation itself. The corpus failure this closes: a `Min-max scaling` entry carrying its definition as `$(x - \min)/(\max - \min)$` mid-sentence — informal, rendered at text height, and easy to read past even though it is the entry's one piece of math. The definition belongs in a display block:

$$
x' = \frac{x - x_{\min}}{x_{\max} - x_{\min}}
$$

A display block may sit mid-sentence — "…it is the [[cost-function|cost function]] *[block]* measured over the whole set of examples." reads fine — or close its sentence. Either way it sits immediately after the prose that introduces the quantity, exactly as images sit next to their motivating prose.

**Structure the layout in display math:** `\frac{…}{…}` rather than the inline slash, `\left( … \right)` around tall content, `\sqrt{…}`, `\sum_{i=1}^{m}`. The slash form stays fine *inline*, where a stacked fraction would break line height.

Display blocks appear only in body prose. `description:` is plain text (writing.md §1); captions and flashcard line 1 allow **inline** math only; flashcard line 3 is plain (`references/flashcards-and-emphasis.md` §4). A display block inside a flashcard would break the card's three-contiguous-line structure — the card's line 1 states its definition with inline math or plain words.

## 3. Notation — one symbol per role, vault-wide

**Consistency is the point: the same quantity wears the same symbol in every entry.** A reader moving between `RMSE`, `MAE`, and `Standardization` never re-learns what $m$ means. Two mechanisms deliver it:

**(a) The canonical table.** For the ML/statistics core — where sources vary most, and where the vault's existing entries already agree — the symbols are fixed:

| Symbol | Role |
|---|---|
| $m$ | number of instances in a dataset |
| $n$ | number of features; a vector's component count |
| $\mathbf{x}^{(i)}$ | feature vector of the $i$-th instance |
| $x$ | a single feature value (scalar) |
| $y^{(i)}$ | label / target of the $i$-th instance |
| $\hat{y}^{(i)}$ | the model's prediction for the $i$-th instance |
| $\mathbf{X}$ | the feature matrix, one row per instance |
| $\mathbf{y}$ | the vector of labels |
| $h$ | the hypothesis — the model's prediction function |
| $\theta$ | a model parameter ($\boldsymbol{\theta}$ for the parameter vector) |
| $\mu$ | mean |
| $\sigma$ | standard deviation |
| $\sigma^2$ | variance paired with an already established standard deviation $\sigma$ |
| $\operatorname{Var}(X)$ | variance operator applied to a nearby-bound quantity $X$ |
| $\bar{x}$ | sample mean of $x$ |
| $x'$ | the transformed (rescaled, encoded) value of $x$ |

This is the notation the vault's equation-bearing entries already use — Géron's *Hands-On Machine Learning* conventions — which is why it is the standard: it was adopted from the corpus, not imposed on it. Inside the table's nominal domain, **pure-statistics entries are the one sanctioned departure**: §4's field-over-table rule lets a statistics entry keep its field's $n$ for sample size where $m$ would read as foreign — reported either way.

**(b) Everything else defers to the field, then to the vault.** Outside the table, use the discipline's own standard symbol — $\lambda$ for wavelength, $K_m$ for the Michaelis constant, $\Delta G$ for free-energy change — never the ML table forced onto another field. Before introducing a symbol, check the entries this entry wikilinks (they are on disk — open the equation-bearing ones): if a linked or sibling entry already renders the quantity, reuse its symbol exactly. When two entries come to need the same quantity, the one written second matches the one written first, not the source in front of it.

**Typography, uniformly:**

- **Instances superscript, components subscript.** $\mathbf{x}^{(i)}$ is the $i$-th instance; $v_j$ (or $x_1$) is a component. Never $x_i$ for an instance.
- **Vectors bold lowercase, matrices bold uppercase** — `\mathbf{v}`, `\mathbf{X}`; scalars in default math italic. (Making math bold *inside a bolded prose span* needs `\boldsymbol{}`/`\mathbf{}` — that is writing.md §2's *Inline formatting* rule about markdown, not this one.)
- **Multi-letter names upright** via `\text{…}`: $\text{RMSE}(\mathbf{X}, \mathbf{y}, h)$, $\text{MAE}$, $\text{precision}$. Single-letter quantities stay italic. Standard operators use their macros — `\min`, `\max`, `\log`, `\exp` — and as subscripts, $x_{\min}$, $x_{\max}$.
- **Variance uses the form the relationship needs.** Write $\operatorname{Var}(X)$ when applying the variance operator to a bound quantity $X$; write $\sigma^2$ for the scalar variance paired with an already established standard deviation $\sigma$. These are consistent forms of the same quantity, not competing notation to normalize away.
- **Named norms** as $\ell_1$, $\ell_2$, $\ell_\infty$ (`\ell`); the general form $\|\cdot\|_p$.
- **Every symbol is bound in nearby prose.** Each symbol a display equation uses is introduced in the sentences around it — "For a dataset of $m$ instances with feature vectors $\mathbf{x}^{(i)}$ and labels $y^{(i)}$, and a prediction function $h$…" is the worked pattern (the vault's `RMSE` entry). The table standardizes *which* symbol to pick; it does not excuse the entry from saying what the symbol means, because entries are self-contained (prose principle 5) and the table is not in front of the reader.

## 4. Normalization — the source's symbols do not survive contact

**Transcribe the math, not the typography.** A source writing $N$ for the sample count, $f(x)$ for the prediction function, or $a, b$ for parameters contributes its *content*; the entry renders that content in vault notation — $m$, $h(\mathbf{x})$, $\theta_0, \theta_1$. Layout normalizes the same way: an inline-slash fraction becomes `\frac` in display form, a source's ad-hoc shorthand becomes the table's symbols. **Meaning is preserved exactly** — renaming and re-laying-out only; never algebraic rearrangement beyond the equivalent forms *Multi-form equations* already covers, and never a "simplification" that changes what the equation states.

**The prose moves with the equation.** Every prose reference to a renamed symbol updates in the same edit — an entry must never define $N$ in a sentence above an equation that says $m$. This is why normalization happens at writing time, not as a repair afterwards.

**When the table and a field's own convention collide, the field wins for that discipline's entries** — a statistics source's $n$ for sample size may stay $n$ in a pure-statistics entry where $m$ would read as foreign — but say so in the run report (*Notes for the user*): the call should be visible either way. Within one entry there is no compromise: one symbol per role, bound once.

**On merge, equations behave like images and tables** (`references/merge.md`): existing equations are preserved across body rewrites and move with their motivating prose. Two points are equation-specific. A **nonconforming existing equation is normalized to this file's rules** — a format fix, like re-piping a link: `updated:` bumps, `read:` does not reset. A **new equation added where the body had none is body content** and resets `read: false`, exactly as a new figure does. That reset is wiki-builder's, on its own merges. When `wiki-linter` retroactively inserts the same equation under its QC item 12, it writes neither `read:` nor `updated:` — its Dates policy — and instead names the insertion under *Notes for the user*, flagging any entry whose `read: true` now predates content the user has not seen; clearing the checkbox stays the user's call (`CONVENTIONS.md` §2d). Replacing an existing equation happens only when the new source states the *same quantity* more completely (more equivalent forms — fold them into one `aligned` block); different quantities get their own blocks, both kept.

**Retroactive reach.** Entries already in the vault that violate these rules — a described calculation never typeset, a defining equation carried inline, off-standard symbols — are `wiki-linter`'s to fix vault-wide (its QC item 12 carries the enforcement bounds); this skill applies the rules to the entries it writes and merges this run, like every other rule it owns.
