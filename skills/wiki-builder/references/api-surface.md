# API surface in body prose

> **When to read this:** Read this before drafting or merging when the source names a software library or the candidate is `type: Software`. A grep over extracted text can double-check library mentions, but reading the source decides the gate; never grep compressed PDF bytes. The type first decides whether API identifiers may appear, then this guide decides which permitted identifiers actually serve the entry.

---

API identifiers never become entries of their own. In a non-`Software` entry they do not appear — not as content and not as a pointer. **The cap is zero.** In a `Software` entry they are eligible only when they explain the artifact's own scope or cross-cutting design; permission is not a reason to retain an identifier.

## `Software`: explain the artifact, not its reference manual

A `Software` entry may name an interface, protocol, lifecycle, composition rule, addressing convention, file format, or command shape when that detail is needed to understand how the artifact is organized or what distinguishes it. A representative API object may make such a convention concrete. Another class or method that merely instantiates the convention adds no new understanding and is omitted.

Do not turn the entry into a catalog of algorithm-specific classes, functions, parameters, defaults, return attributes, or version-by-version additions. Do not preserve a tutorial's sequence of calls or a recipe for accomplishing a task. Even accurate identifiers are off-scope when their main value is lookup or usage rather than understanding the artifact. For scikit-learn, the shared estimator/transformer contract, composition model, and learned-attribute or nested-parameter conventions can be load-bearing; an inventory of tree and ensemble classes with their defaults is not.

**The step-2 substance gate still applies.** A source that uses a library to teach another concept, or merely enumerates the library objects used to implement that concept, does not thereby teach the `Software` entity. Reject that create/merge contribution, do not append the source, and leave an already-explained interface convention unchanged. A source earns a `Software` contribution when it substantively explains the artifact's scope, architecture, interface contract, design tradeoff, or artifact-wide capability or limitation.

## The rule: API identifiers live only in `Software` entries

**A non-`Software` entry carries no backticked API identifier — none.** The library itself may be named — in plain prose ("the joblib library") or, when it has an entry, as a wikilink (`[[scikit-learn]]` — bare, because display equals slug; checklist item 10) — but its classes, functions, methods, kwargs, attributes, and module paths do not live here. A load-bearing identifier may appear in the library's `Software` entry under the selective rule above; a lookup-only identifier is simply omitted.

*(History: until 2026-08-16 this file permitted one "name-only signpost" per non-Software entry — "Implemented in [library] as `Identifier`." or the parenthetical fold "…(`Identifier` in [library])…". That allowance is retired by the user's standing decision: both shapes are now violations, and a lint pass strips them. A wikilink to the Software entry supplies artifact-level navigation; it is not a promise that the wiki catalogs every searchable identifier.)*

## The two sides of the split

- **`Software` entries:** selectively retain the API elements that explain an artifact-wide interface or design convention. The entry on scikit-learn can explain `fit()`/`transform()`, pipeline composition, the trailing-underscore convention for learned attributes, and double-underscore nested-parameter addressing. It does not need every estimator that follows those conventions. Apply the source-contribution gate above before adding either prose or a citation.
- **All other types** (`Concept`, `Person`, `Organization`, `Dataset`, `Device`, `Event`, `Standard`, `Gene/Protein`, `Organism`, `Chemical`, `Reaction`, `Place`, `Work`, `Quote`): API identifiers are **not content here at all** — zero backticked identifiers, with no signpost exception.

## Hard caps (Quality Checklist item 6 enforces)

- **Zero** library-specific signposts per non-Software entry — the signpost form itself is retired.
- **Zero** backticked API identifiers of any kind: classes, functions, methods, kwargs, attributes, module paths, calling conventions.
- **Mechanical count rule:** any backticked token in a non-Software entry that is a library identifier is a violation. Library *names* are not identifiers — they appear in plain prose or as wikilinks, never backticked. Two backticked shapes remain non-identifiers (matching the linter's scanner): a bare file extension (`.csv`) and a bracket special token (`[CLS]`).

## Forbidden shapes

- **No hyperparameter listings, no kwarg documentation, no default-value documentation, no calling-convention documentation** anywhere in a non-Software entry. These are omitted here; the Software entry retains only the artifact-wide subset that passes its own rule. The corpus failures to watch for: a `Proximal policy optimization` entry that lists seven hyperparameters with their defaults; a `Bidirectional RNN` entry with four backticked tokens spread across one paragraph; a `Beam search` entry with `generate`, `GenerationMixin`, and `num_beams`; an `Autograd` entry with five identifiers; a `Batch normalization` entry with three identifiers. Each is a violation regardless of how naturally the identifiers fit the prose.
- **No standalone paragraph** whose primary content is the library's API surface. The diagnostic: if a paragraph were retitled "How to use this in [Library]," it does not belong in a non-Software entry; do not move it wholesale into the Software note either.
- **Forbidden sentence shapes** (each is a how-to pattern that does not belong here): *"It can be built with `X`"*, *"Construct it with `X`"*, *"Use `X` to..."*, *"Created via `X`"*, *"Available through `X` and `Y`"*, *"Build one by calling `X`"*.
- **No implementation-path mentions.** *"with `X`"*, *"via `Y`"*, and every "or"-alternative (*"with `X` or via `Y`"*) are how-to content; under the zero cap the identifiers go, and if the sentence was only there to name them, the sentence goes with them.
- **Language literals in code form (`True`, `False`, `None`, backticked numeric literals).** Python and other programming-language literals backticked as code belong in `Software` entries' API discussions, not in `Concept` / `Person` / other non-Software entries. In non-Software entries, use prose form for boolean and singleton values: `true` / `false` (lowercase, plain text) for mathematical truth values, "zero" / "one" or `0` / `1` (plain text or as math objects per *prose principle 8*) for binary or numeric values when the binary representation is the point, "none" or "null" in prose for absence. The corpus failure shape: a `Causal mask` entry describing the mask as *"a square boolean matrix containing `True` above the main diagonal and `False` everywhere else"* — these are Python literals; the language-neutral version is *"a square boolean matrix with true above the main diagonal, false below"* (or the indicator-matrix version with $1$ / $0$). Backticked literals are appropriate only when the entry itself is `Software` and the representation explains that software subject, such as the `Python` entry's discussion of `None` semantics. A conceptual `Boolean type` comparison stays in plain prose or math.

## Mechanical pre-finalize scan (this is the binding check)

Run this literally before declaring a non-Software entry done. This failure mode keeps recurring across rewrites of this skill — not a coverage gap (the rule above already enumerates the forbidden shapes), but a *review-application* gap: the model writes the violation, doesn't reliably catch it on the interpretive author test below, and the entry ships. The fix is a literal string search:

- **Any backticked span.** Under the zero cap this is the whole check: grep the body for a backtick and justify every hit. The only backticked spans that survive in a non-Software entry are the two non-identifier shapes above (a bare file extension, a bracket special token); everything else is a violation.
- `"In PyTorch"` / `"In TensorFlow"` / `"In NumPy"` / `"In Hugging Face"` / `"In [Library]"` as a sentence opener — sentence openers of this shape almost always introduce how-to content. **Corpus:** *"In PyTorch a causal mask can be built with `torch.triu`, and an `is_causal` flag enables performance optimizations when the mask is known to be causal."* (`causal-mask.md`) — three independent failures in one sentence: the `"In PyTorch"` opener, the ``"built with `X`"`` form, and the `"flag enables"` kwarg documentation.
- `"[Library] implements"` / `"[Library] provides"` / `"[Library] exposes"` / `"[Library] offers"` — these verbs invite the model to describe *what* the library object does: how-to content, and under the zero cap the identifier it introduces is itself a violation.
- ``"built with `"`` / ``"built using `"`` / ``"constructed via `"`` / ``"constructed with `"`` / ``"created by `"`` / ``"Building one in [Library] uses `"`` / ``"Building one with `"`` — every variant of the "built with X" form is forbidden.
- `"flag enables"` / `"flag controls"` / `"argument controls"` / `"argument enables"` / `"kwarg"` / ``"defaults to `"`` / ``"defaults to `True`"`` / ``"defaults to `False`"`` — explicit kwarg/default-value documentation, forbidden anywhere outside Software entries.
- ``"or via `"`` / ``"or with `"`` / ``"or through `"`` / ``"or by calling `"`` — alternative implementation paths; how-to content.

For each match, the default reaction is **delete the sentence** — or, for an identifier folded into a parenthetical, delete the parenthetical and keep the explanatory sentence around it. The reader can still navigate from `[[pytorch|PyTorch]]` / `[[transformers-library|Transformers library]]` / `[[scikit-learn]]` to the artifact's Software entry; that link does not require the entry to preserve the omitted identifier. **There is no exception**: the permitted-signpost carve-out this paragraph used to state was retired on 2026-08-16.

## The author test (apply during the review pass)

For each backticked token in a non-Software entry, one question: **is this an API identifier?** If yes, it is over the line — delete it (keeping at most the library's plain name where the sentence still needs one; if the sentence existed only to name the identifier, delete the sentence). Nothing is created to house it: the identifier appears in the library's `Software` entry only if it passes that entry's selective rule; otherwise it simply goes. If the entry cannot explain its concept without the identifier, the entry is probably about the software artifact itself — reclassify `type:` to `Software` instead (the strip-vs-reclassify call, SKILL.md item 6), then apply the Software scope test rather than retaining the old body automatically.
