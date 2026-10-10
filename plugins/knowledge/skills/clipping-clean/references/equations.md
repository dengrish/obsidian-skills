# Equations and typographic super/subscripts

- [Normalize math delimiters](#normalize-math-delimiters) — MathJax delimiters,
  equations captured as images, bare LaTeX
- [Rebuild flattened formulas](#rebuild-flattened-formulas) — `<sup>`/`<sub>`,
  Unicode super/subscripts and operators that were a formula
- [Leave non-math notation alone](#leave-non-math-notation-alone) — prices,
  ordinals, date ranges, chemical names, prose notation

Read only when the clipping body has math delimiters, LaTeX commands such as
`\frac`, an equation image whose alt text holds LaTeX, `<sup>`/`<sub>` tags,
Unicode super- or subscripts or formula operators. These rules extend the
[body-cleaning rules](body-cleaning.md#repair-structure-and-markup): they apply
to rendered prose, never to fenced or inline code, and every detector match is a
candidate to confirm against the source. Literal currency dollars follow the
[currency rule](body-cleaning.md#repair-structure-and-markup) whether or not the
note has math.

## Normalize math delimiters

Obsidian renders `$...$` (inline) and `$$...$$` (display) but does **not**
render MathJax's `\(...\)` and `\[...\]` delimiters, which is what most clipped
articles ship with. Convert:

- `\(<latex>\)` → `$<latex>$` (inline, mid-sentence).
- `\[<latex>\]` → `$$<latex>$$` on its own line, with a blank line above and
  below (display, between paragraphs).
- Already-correct `$...$` and `$$...$$` stay as-is.
- **Equation captured as an image** (Web Clipper sometimes grabs a
  MathJax/KaTeX-rendered SVG or PNG; the LaTeX source is usually in the
  `<img>`'s `alt` attribute or `data-original`). Replace the image reference
  with `$...$` or `$$...$$` form, picking inline vs display by the original's
  placement (mid-sentence → inline, own line → display). If no LaTeX is
  recoverable from the image, leave the image reference alone and [image
  handling](images.md) treats it as a normal figure.
- Bare LaTeX source pasted as plain text without delimiters (rare; e.g.,
  `\frac{a}{b}` sitting in a paragraph with no `$` around it). Wrap it in
  `$...$` if it's clearly meant to render as math.

## Rebuild flattened formulas

**Formulas flattened to typographic plain text — convert these to LaTeX.** This
is the common case the clip *doesn't* arrive in LaTeX form at all: a real
equation that the page typeset as a formula, but Web Clipper captured as plain
text carrying only its typographic structure. The tells that it was a formula:
HTML `<sup>…</sup>`/`<sub>…</sub>` used as exponents/subscripts, Unicode
super/subscripts (`²³`, `₁₂`, `⁻`), and/or linear math operators in an
expression (`×`, `⋅`, `·`, `√`, `≤`, `≥`, `≈`, `≠`, `±`, `∑`, `∫`, `→`, an `=`
relating mathematical quantities). Rebuild the LaTeX and wrap it — inline `$…$`
mid-sentence, display `$$…$$` on its own line — writing an exponential as a
power of $e$ (`exp(−x²)` → `$e^{-x^{2}}$`), never `\exp`. Worked examples from
a real clip:

- `log <sub>2</sub> (10) = 3.32` → `$\log_2(10) = 3.32$`
- `2.57 × (3.64 × 10 <sup>3</sup>) <sup>−0.048</sup>` →
  `$2.57 \times (3.64 \times 10^{3})^{-0.048}$`
- `8×10 <sup>9</sup> / 9.7×10 <sup>12</sup> = 8×10 <sup>−4</sup>` →
  `$8 \times 10^{9} / (9.7 \times 10^{12}) = 8 \times 10^{-4}$`
- `2.57 ⋅ (3.64 ⋅ (10 <sup>3</sup> ⋅ *x*)) <sup>-0.048</sup> = 0.86` →
  `$2.57 \cdot (3.64 \cdot (10^{3} \cdot x))^{-0.048} = 0.86$` (the `*x*`
  italic-emphasis is a variable — fold it into the math, don't keep the markdown
  asterisks)

## Leave non-math notation alone

**But typographic sup/sub is heavily overloaded — confirm it's actually a
formula before converting, or the conversion mangles prose.** `<sup>`/`<sub>`
appear on plenty of non-math things. Convert non-math sup/sub to plain text or
Unicode when an exact equivalent exists, never to LaTeX; keep the tag (Obsidian
renders it natively) only when no plain form preserves the meaning, and report
it. Common cases:

- *Currency with inflation annotations* — Gwern's
  `$6.29 <sup>$5</sup> <sub>2020</sub> m` means "$6.29m (≈$5 in 2020 dollars)",
  not an equation. The giveaway is a `$` in the base and/or the superscript and
  a year in the subscript. Render it as readable prose (e.g. `$6.29m` with the
  inflation note in parentheses, or keep Gwern's compact `$6.29 ($5 in 2020) m`
  form) — never `$…$` math. Escape each currency `$` as `\$`
  (`\$6.29m (\$5 in 2020)`) under the currency rule.
- *Ordinal suffixes* — `100 <sup>th</sup>` → `100th`; `1⁄100 <sup>th</sup>` →
  `1/100th`.
- *Date ranges / years* — `2004 <sup>–</sup> 2010` → `2004–2010` (the dash got
  wrapped in `<sup>` as a clip artifact).
- *Chemical formulae* — `CO <sub>2</sub>` → `CO₂` (Unicode subscript), not
  `$\mathrm{CO}_2$`, unless it sits inside an actual chemical *equation* with
  reaction arrows/operators.

**Don't LaTeX-ify natural-language math in prose** ("runtime is O(n log n)",
"α-helix", "the half-life is ~24h", "a 100× improvement", "GPT-2-1.5b"). The
principle across all of the above: convert what was a *formula* in the source
(even when it arrived as typographic plain text — the sup/sub/operator structure
is the evidence), and leave what was *prose notation*, a *unit*, a
*ratio/multiplier*, a *price*, or a *name*. If writing the LaTeX would mean
reverse-engineering the math from English, it wasn't a formula — leave it alone.
When a sup/sub expression is genuinely ambiguous between formula and annotation,
prefer cleaning it to readable plain text/Unicode and **flag it in the report**
rather than guessing at math mode.
