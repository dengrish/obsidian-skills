# Equations — coverage, form, notation, normalization

Scope: equation coverage, form, vault notation and normalization; numbers in prose and literal `$` follow [writing principle 8](writing.md#prose-principles).

## 1. Coverage — explanatory value before notation

**Include an equation only when it makes the concept easier to understand.** Ask what the reader gains over a short verbal explanation: seeing a quantitative relationship, computing a named quantity, or understanding a model's structure. Count the cost of indices, indicators and operators; if they obscure a simple idea, use prose. Hard voting needs "choose the class with the most votes", not an argmax over indicator functions, in the body or on the card. This judges one concept at a time; it neither bans a topic's formulas nor asks for less mathematics.

**Start from the defining relation.** Ask which relationship defines this concept or its named quantity, and show that one first. A model's entry, an ensemble's included, always shows how it makes its prediction and, when its training minimizes an objective, that objective, one sentence each, or a display when the source prints one or it can be explained simply, even when a neighbor owns the full treatment (AdaBoost predicts by a weighted vote and minimizes the exponential loss; an instance-based model or an ensemble of independently trained members states how it trains instead, as the [core-facet check](writing.md#prose-principles) says). When displays compete, the prediction step and objective outrank gradients, update bookkeeping and threshold rules.

**Source typesetting does not decide.** Keep a source equation when it is central to the entry, not every equation the source prints. A useful calculation described completely in words may be typeset, as standardization is:

$$
x' = \frac{x - \mu}{\sigma}
$$

**A useful standard equation may be added even when the source supplies none**, as [principle 5(h)](writing.md#prose-principles) background with no citation, when it expresses this concept at this entry's scope and is a verified conventional relationship. An entry that names a formula gives it (a confidence interval is the estimate plus or minus a critical value times its standard error). Do not infer a population or sample denominator, a loss, or another substantive assumption from a vague mention.

**General form first.** When the source gives only a special case of a well-established general relation (one loss, one distribution), state the general formula first and present the source's case as an instance with its condition, keeping the description, opener and card at the concept's actual scope: squared-error gradient boosting fits residuals because they are that loss's negative gradient, which does not make residual fitting the definition of gradient boosting. A loss, metric or divergence several models share is written over its own quantities (targets and estimated probabilities; RMSE over $y^{(i)}$ and $\hat{y}^{(i)}$, not $\text{RMSE}(\mathbf{X}, h)$), never one model's parameters ($\boldsymbol{\Theta}$); that model's entry owns its parameterized cost. This rule orders displays, not the opener: the plain-words idea precedes the general form.

**Keep only the conditions without which a reader would misuse the formula in its ordinary setting:** $0 \le \lambda \le 1$ in the convexity inequality, $p \ge 1$ for an Lp norm, $y \in \{0,1\}$ in log loss, population versus sample. A property of the concept is content (softmax outputs sum to one). Do not append exhaustive domain checks, well-definedness guards ("for a nonempty cluster", $m \ge 1$, nonzero denominators or variance, probabilities that sum to one, ranges a parameter's name implies), tie-breaking, clipping tolerances, implementation alternatives, noise or independence assumptions the relation's explanation does not use, such as Gaussian or constant-variance noise behind a decomposition that needs neither, notation devices ($x_0 = 1$), logarithm-base remarks (a base that defines the unit, such as bits, is stated once in prose under [§3](#3-notation--one-symbol-per-role-vault-wide)), recaps of symbol conventions, or statements that two distributions range over the same outcomes. An assumption the relation rests on is content: state it in the display's explanation, where the reasoning uses it (independence makes a likelihood a product, and zero-mean noise independent of the learned model makes the bias–variance decomposition's cross terms vanish). State a complexity or bound by its practical takeaway unless the formula itself teaches, and always say in one sentence why it has that form, using the intuition the source gives (each split compares every feature over the node's sorted instances, so training cost grows with features times instances times their logarithm). An iteration bound gets the same one-sentence reason. A comparison of two costs gives the practical takeaway and one sentence of intuition. When only a proof explains a bound (a convergence rate, a combinatorial count, an algorithm's internals) and no one-sentence intuition exists, state the takeaway and omit the bound. When no sound reason accounts for a factor, the stated cost is suspect: never invent a reason; state the accurate cost once [conflict handling](merge.md#conflict-handling) settles it, and until then give only the practical takeaway. Keep an exact definition distinct from numerical approximations when the source makes that distinction relevant; never turn an illustrative formula into an implementation specification.

`lint_entry.py` and wiki-lint's scanner share `equation_coverage.py`, a conservative floor of equation-coverage, boilerplate and two-relations-in-one-display candidates; each is a review candidate, never an order.

These rules govern the body; card line 1 follows its [own rule](flashcards-and-emphasis.md#line-1-equation-coverage).

## 2. Form — defining equations are display math

**The equation that defines the entry's subject or a named quantity sits in a `$$…$$` display block**: each `$$` alone on its line, with a blank line above and below. **One equation per line:** never set two equations side by side in one display line (`a = …, \qquad b = …`, `a = …, b = …`, `a = … \text{ and } b = …`, a derivation joined by `\Rightarrow`, or a `\text{where}` clause defining another quantity). Give each its own line: a separate display beside the prose that introduces it, or a row of an `aligned` or `gathered` display. A second source line inside one display is not a new line; it renders beside the first. A condition such as an index range (`i = 1, \ldots, m` or `x = 0, 1`) or `\text{for } i = 1` is not a second equation. **Inline `$…$` is for math woven into a sentence** (symbols such as $\sigma$, short expressions, bounds such as $0 \le p \le 1$), never the defining equation: `Min-max scaling` written inline as `$(x - \min)/(\max - \min)$` hides the key result at text height. A display may sit mid-sentence or close its sentence, right after the prose introducing the quantity. Display math uses `\frac{…}{…}`, `\left( … \right)` around tall content, `\sqrt{…}` and `\sum_{i=1}^{m}`; the slash form stays fine inline.

Display blocks appear only in the body, in prose or inside a list item. `description:` is plain text; captions and card line 1 allow **inline** math only, and card line 3 (the answer) allows none ([card math](flashcards-and-emphasis.md#line-1-equation-coverage)).

**A display inside a list item belongs to that item.** A step of a [numbered list](writing.md#body-structure) keeps its display and the display's explanation inside the item. Indent both `$$` lines, the math between them and the explanation to the item's text column: 3 spaces after `1. `, 4 after `10. `. Leave a blank line above and below the display. Every rule in this section still applies there, one equation per line included. A display or paragraph left at the margin ends the list in Obsidian, and the following steps start a new list.

```markdown
Gradient descent lowers a cost by repeated small steps downhill:

1. Initialize the parameter vector $\boldsymbol{\theta}$, for example with small random values, so the search has a starting point.
2. Compute the gradient $\nabla_{\boldsymbol{\theta}} J(\boldsymbol{\theta})$ on the training set, which points in the direction of steepest increase of the cost.
3. Move the parameters a small step against the gradient, which lowers the cost:

   $$
   \boldsymbol{\theta} \leftarrow \boldsymbol{\theta} - \eta \nabla_{\boldsymbol{\theta}} J(\boldsymbol{\theta})
   $$

   The learning rate $\eta$ sets the step size: a small enough step against the gradient lowers $J(\boldsymbol{\theta})$, and a step too large overshoots the minimum.
4. Repeat from step 2 until the cost stops decreasing.
```

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

**The same quantity wears the same symbol in every entry.** The ML, statistics and information-theory core uses these symbols, whichever discipline tag the entry carries, apart from the one `#statistics` departure below:

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
| $J(\boldsymbol{\theta})$ | a cost averaged over the training set, as a function of a generic model's parameter vector |
| $\mu$ | mean |
| $\sigma$ | standard deviation |
| $\sigma^2$ | variance paired with an already established standard deviation $\sigma$ |
| $\operatorname{Var}(X)$ | variance operator applied to a nearby-bound quantity $X$ |
| $\bar{x}$ | sample mean of $x$ |
| $x'$ | the transformed (rescaled, encoded) value of $x$ |
| $H(p)$ | entropy of distribution $p$ |
| $H(p, q)$ | cross entropy of $q$ relative to $p$ |
| $D_{\text{KL}}(p \parallel q)$ | Kullback–Leibler divergence of $q$ from $p$ |

The information-theory symbols always carry their distribution arguments, binding $p$ to the outcome probabilities $p_k$: never bare $H$ for a distribution's entropy (a decision-tree node's impurity $H_i$ stays as its entry binds it). They hold whatever the logarithm's base; where the base defines the unit (base 2 gives bits), state it once in prose, never as a subscript on $H$.

**Entries tagged `#statistics` are the table's one sanctioned departure** (§4). **Outside the table, defer to the field, then to the vault:** use the discipline's standard symbol ($\lambda$ for wavelength), never the ML table, and reuse exactly the symbol a linked or sibling entry gives the quantity (open the equation-bearing ones); the entry written second matches the first, not its source. **When siblings disagree, the table wins;** outside it the field's standard symbol, then the notation of the most-linked sibling. This run's entries follow that symbol, and wiki-lint normalizes the minority siblings.

**Typography:**

- **Instances superscript, components subscript:** $\mathbf{x}^{(i)}$ is the $i$-th instance, $x_1$ a component; never $x_i$ for an instance.
- **Vectors bold lowercase, matrices bold uppercase** (`\mathbf{v}`, `\mathbf{X}`), scalars in math italic.
- **Multi-letter names upright** via `\text{…}` ($\text{RMSE}$, $\text{precision}$); an existing `\mathrm{…}` spelling is the same symbol and is never renamed. Standard operators use their macros (`\min`, `\log`; $x_{\min}$).
- **Variance:** $\operatorname{Var}(X)$ and $\sigma^2$ are consistent forms, never normalized into each other.
- **Named norms** as $\ell_1$, $\ell_2$, $\ell_\infty$ (`\ell`); the general form $\|\cdot\|_p$.
- **Greek-letter units** in inline LaTeX, upright (`10 $\mu\mathrm{m}$`, not `10 μm`); the number stays plain, as do descriptions ([field rule](writing.md#description)).
- **Bind every symbol nearby, briefly.** Introduce each symbol a display uses in its lead-in or a following *where* clause, not in the opening sentence ("for $m$ instances with feature vectors $\mathbf{x}^{(i)}$ and labels $y^{(i)}$…"). Standard symbols ($\theta$, $\mathbf{x}$, $\hat{y}$, $m$) need only their role. Omit notation no display needs, and never restate a displayed quantity in a second notation. The table fixes which symbol to use, not whether to say what it means: the reader does not have the table.

**Every display must be understandable from the entry.** Beside it, say what each term means and why the relation holds, by an intuitive account of where it comes from; give a derivation only when it fits in one or two sentences. Say what drives the quantity up or down, what a term contributes, or what a limiting case gives: "pairs on the same side of their means add positive terms, so $r$ rises when the variables move together." Reading the formula aloud is not this; when nearby prose already explains it, add nothing, and a ratio or average the opening sentence already defines in words needs only its symbols bound. A mathematical result stated only in prose, such as a derivation's outcome or what a method returns in the case it is said to handle, gets the same one-line reason. An equation the source does not print that cannot be explained this simply is left out, and the idea stays in prose.

## 4. Normalization — the source's symbols do not survive contact

**Transcribe the math, not the typography.** A source's $N$, $f(x)$ or $a, b$ becomes vault notation ($m$, $h(\mathbf{x})$, $\theta_0, \theta_1$). **Meaning is preserved exactly:** rename and re-lay-out only, never rearrange algebra beyond the [equivalent forms](#multi-form-equations) or "simplify" what the equation states. Every prose reference to a renamed symbol changes in the same edit. **Statistics is the table's one departure ([§3](#3-notation--one-symbol-per-role-vault-wide)):** an entry tagged `#statistics` writes a sample's or dataset's size as $n$, and its statistics siblings follow it; entries under every other tag keep the table's symbol for each role it lists. Report the departure under *Notes for the user*.

**On merge, equations behave like images and tables** ([merge](merge.md#exhibits-and-headings)): existing useful equations survive body rewrites and move with their motivating prose. Preservation protects an equation's meaning, not its position or which display leads; a merge may lead with a more general form ([integration principle](merge.md#integration-principle)). A **nonconforming existing equation is normalized** as a format fix: `updated:` bumps, `read:` does not reset. A **new equation added where the body had none is body content** and resets `read: false`, as a new figure does, on wiki-build's own merges. When `wiki-lint` retroactively inserts the same equation under its QC item 12 in Task 1, it writes neither `read:` nor `updated:` and names the insertion under *Notes for the user*, flagging a `read: true` entry that now predates unseen content; clearing the checkbox stays the user's call (`CONVENTIONS.md` §2c). An equation wiki-lint inserts during its [content repair](../../wiki-lint/SKILL.md#task-1b--content-repair) instead follows the [body-change rule](merge.md#the-read-reset). In that content repair, or under an explicit simplification or source-backed correction request, remove an equation that fails the usefulness test, with its notation-only prose and card math, keeping the concept, essential conditions and all protected card state. Otherwise an existing equation changes only when the new source states the *same quantity* more clearly or correctly; an equivalent form that passes §1 joins it in one [`aligned` block](#multi-form-equations). Older entries breaking these rules are `wiki-lint`'s to fix (QC item 12).
