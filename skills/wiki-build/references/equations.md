# Equations — coverage, form, notation, normalization

Scope: equation coverage, form, vault notation and normalization; numbers in prose and literal `$` follow [writing principle 8](writing.md#prose-principles).

## 1. Coverage — explanatory value before notation

**Include an equation only when it makes the concept easier to understand.** Ask what the reader gains over a short verbal explanation: seeing a quantitative relationship, computing a named quantity, or understanding a model's structure. Count the cost of indices, indicators and operators; if they obscure a simple idea, use prose. Hard voting needs "choose the class with the most votes", not an argmax over indicator functions, in the body or on the card. This judges one concept at a time; it neither bans a topic's formulas nor asks for less mathematics.

**Start from the defining relation.** Ask which relationship defines this concept or its named quantity, and show that one first. A model's entry always shows how it makes its prediction and what its training minimizes, a display or one sentence each, even when a neighbor owns the full treatment. When displays compete, the prediction step and objective outrank gradients, update bookkeeping and threshold rules.

**Source typesetting does not decide.** Keep a source equation when it is central to the entry, not every equation the source prints. A useful calculation described completely in words may be typeset, as standardization is:

$$
x' = \frac{x - \mu}{\sigma}
$$

**A useful standard equation may be added even when the source supplies none**, as [principle 5(h)](writing.md#prose-principles) background with no citation, when it expresses this concept at this entry's scope and is a verified conventional relationship. Do not infer a population or sample denominator, a loss, or another substantive assumption from a vague mention.

**General form first.** When the source gives only a special case of a well-established general relation (one loss, one distribution), state the general formula first and present the source's case as an instance with its condition, keeping the description, opener and card at the concept's actual scope: squared-error gradient boosting fits residuals because they are that loss's negative gradient, which does not make residual fitting the definition of gradient boosting.

**Keep only the conditions without which a reader would misuse the formula in its ordinary setting:** $0 \le \lambda \le 1$ in the convexity inequality, $p \ge 1$ for an Lp norm, $y \in \{0,1\}$ in log loss, population versus sample. A property of the concept is content (softmax outputs sum to one). Do not append exhaustive domain checks, well-definedness guards ("for a nonempty cluster", $m \ge 1$, nonzero denominators or variance, probabilities that sum to one, ranges a parameter's name implies), tie-breaking, clipping tolerances, implementation alternatives, noise or independence assumptions behind a textbook decomposition (an assumption the defining relation itself rests on, such as independence making a likelihood a product, is content), notation devices ($x_0 = 1$), logarithm-base remarks, recaps of symbol conventions, or statements that two distributions range over the same outcomes. State a complexity or bound by its practical takeaway unless the formula itself teaches. Keep an exact definition distinct from numerical approximations when the source makes that distinction relevant; never turn an illustrative formula into an implementation specification.

`lint_entry.py` and wiki-lint's scanner share `equation_coverage.py`, a conservative floor of equation-coverage and boilerplate candidates; each is a review candidate, never an order.

These rules govern the body; card line 1 follows its [own rule](flashcards-and-emphasis.md#line-1-equation-coverage).

## 2. Form — defining equations are display math

**The equation that defines the entry's subject or a named quantity sits in a `$$…$$` display block**: each `$$` alone on its line, with a blank line above and below. Two genuinely different quantities get two blocks, each beside its motivating prose. **Inline `$…$` is for math woven into a sentence** (symbols such as $\sigma$, short expressions, bounds such as $0 \le p \le 1$), never the defining equation: `Min-max scaling` written inline as `$(x - \min)/(\max - \min)$` hides the key result at text height. A display may sit mid-sentence or close its sentence, right after the prose introducing the quantity. Display math uses `\frac{…}{…}`, `\left( … \right)` around tall content, `\sqrt{…}` and `\sum_{i=1}^{m}`; the slash form stays fine inline.

Display blocks appear only in body prose. `description:` is plain text; captions and card lines allow **inline** math only, and a primary card's answer line allows none ([card math](flashcards-and-emphasis.md#line-1-equation-coverage)).

### Multi-form equations

When §1 admits two or more equivalent forms of one quantity, they share one display: `\\` line breaks and `&=` alignment inside `\begin{aligned}...\end{aligned}` within the `$$` delimiters (bare `&=` and `\\` are invalid LaTeX and fail to render).

```latex
$$
\begin{aligned}
F_1 &= 2 \cdot \frac{\text{precision} \cdot \text{recall}}{\text{precision} + \text{recall}} \\
    &= \frac{\text{TP}}{\text{TP} + \frac{\text{FN} + \text{FP}}{2}}
\end{aligned}
$$
```

This is a layout rule, not an inclusion rule: keep a form only when it passes §1 (the count form above shows which confusion-matrix cells F1 ignores), never rearrangements or derivation steps because the source prints them. A single-form equation stays on one line between its `$$` lines, **without** `aligned`.

## 3. Notation — one symbol per role, vault-wide

**The same quantity wears the same symbol in every entry.** The ML and statistics core uses these symbols:

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

**Pure-statistics entries are the table's one sanctioned departure** (§4). **Outside the table, defer to the field, then to the vault:** use the discipline's standard symbol ($\lambda$ for wavelength), never the ML table, and reuse exactly the symbol a linked or sibling entry gives the quantity (open the equation-bearing ones); the entry written second matches the first, not its source.

**Typography:**

- **Instances superscript, components subscript:** $\mathbf{x}^{(i)}$ is the $i$-th instance, $x_1$ a component; never $x_i$ for an instance.
- **Vectors bold lowercase, matrices bold uppercase** (`\mathbf{v}`, `\mathbf{X}`), scalars in math italic.
- **Multi-letter names upright** via `\text{…}` ($\text{RMSE}$, $\text{precision}$); standard operators use their macros (`\min`, `\log`; $x_{\min}$).
- **Variance:** $\operatorname{Var}(X)$ and $\sigma^2$ are consistent forms, never normalized into each other.
- **Named norms** as $\ell_1$, $\ell_2$, $\ell_\infty$ (`\ell`); the general form $\|\cdot\|_p$.
- **Greek-letter units** in inline LaTeX, upright (`10 $\mu\mathrm{m}$`, not `10 μm`); the number stays plain, as do descriptions ([field rule](writing.md#description)).
- **Bind every symbol nearby, briefly.** Introduce each symbol a display uses in its lead-in or a following *where* clause, not in the opening sentence ("for $m$ instances with feature vectors $\mathbf{x}^{(i)}$ and labels $y^{(i)}$…"). Standard symbols ($\theta$, $\mathbf{x}$, $\hat{y}$, $m$) need only their role. Omit notation no display needs, and never restate a displayed quantity in a second notation. The table fixes which symbol to use, not whether to say what it means: the reader does not have the table.

**Explain each defining display in words.** Beside it, say what drives the quantity up or down, what a term contributes, or what a limiting case gives: "pairs on the same side of their means add positive terms, so $r$ rises when the variables move together." Reading the formula aloud is not this; when nearby prose already explains it, add nothing.

## 4. Normalization — the source's symbols do not survive contact

**Transcribe the math, not the typography.** A source's $N$, $f(x)$ or $a, b$ becomes vault notation ($m$, $h(\mathbf{x})$, $\theta_0, \theta_1$). **Meaning is preserved exactly:** rename and re-lay-out only, never rearrange algebra beyond the [equivalent forms](#multi-form-equations) or "simplify" what the equation states. Every prose reference to a renamed symbol changes in the same edit. **When the table and a field's convention collide, the field wins for that discipline's entries** (a pure-statistics entry may keep $n$ for sample size), reported under *Notes for the user*.

**On merge, equations behave like images and tables** ([merge](merge.md#exhibits-and-headings)): existing useful equations survive body rewrites and move with their motivating prose. Preservation protects an equation's meaning, not its position or which display leads; a merge may lead with a more general form ([integration principle](merge.md#integration-principle)). A **nonconforming existing equation is normalized** as a format fix: `updated:` bumps, `read:` does not reset. A **new equation added where the body had none is body content** and resets `read: false`, as a new figure does, on wiki-build's own merges. When `wiki-lint` retroactively inserts the same equation under its QC item 12, it writes neither `read:` nor `updated:` and names the insertion under *Notes for the user*, flagging a `read: true` entry that now predates unseen content; clearing the checkbox stays the user's call (`CONVENTIONS.md` §2c). Under an explicit simplification or source-backed correction request, remove an equation that fails the usefulness test, with its notation-only prose and card math, keeping the concept, essential conditions and all protected card state. Otherwise an existing equation changes only when the new source states the *same quantity* more clearly or correctly; an equivalent form that passes §1 joins it in one [`aligned` block](#multi-form-equations). Older entries breaking these rules are `wiki-lint`'s to fix (QC item 12).
