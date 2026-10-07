# API surface in body prose

Scope: which API identifiers may appear in an entry, and what a `Software` entry covers. Reading the source decides the gate; a grep over extracted text only double-checks library mentions, and never grep compressed PDF bytes. The type first decides whether identifiers may appear; this guide then decides which permitted ones serve the entry.

---

API identifiers never become entries of their own. In a non-`Software` entry they do not appear — not as content and not as a pointer. **The cap is zero.** In a `Software` entry they are eligible only when they explain the artifact's own scope or cross-cutting design; permission is not a reason to retain an identifier.

## `Software`: explain the artifact, not its reference manual

A `Software` entry covers the artifact's scope, design choices and place in the broader landscape. It may name an interface, protocol, lifecycle, composition rule, addressing convention, file format, or command shape when that detail is needed to understand how the artifact is organized or what distinguishes it. A representative API object may make such a convention concrete. Another class or method that merely instantiates the convention adds no new understanding and is omitted.

Do not turn the entry into a catalog of algorithm-specific classes, functions, parameters, defaults, return attributes, or version-by-version additions. Do not preserve a tutorial's sequence of calls or a recipe for accomplishing a task. Even accurate identifiers are off-scope when their main value is lookup or usage rather than understanding the artifact. For scikit-learn, the shared estimator/transformer contract, composition model, and learned-attribute or nested-parameter conventions can be load-bearing; an inventory of tree and ensemble classes with their defaults is not.

**The step-2 substance gate still applies.** A source that uses a library to teach another concept, or merely enumerates the library objects used to implement that concept, does not thereby teach the `Software` entity. Reject that create/merge contribution, do not append the source, and leave an already-explained interface convention unchanged. A source earns a `Software` contribution when it substantively explains the artifact's scope, architecture, interface contract, design tradeoff, or artifact-wide capability or limitation.

A version-specific behavior claim needs a durable source that establishes that version: the active source, or a vault source that a Wiki entry already cites (a confirmed [prior-coverage](source-intake.md#check-prior-coverage) match), such as the project's versioned documentation or release notes, cited in `sources:` only when it contributes substantively. A source no entry cites, an `Inbox/` capture included, is unbuilt: do not cite it, and report `<source> also covers <claim>: run wiki-build on it` (after `clipping-clean` for a capture). wiki-add may instead cite the versioned documentation page it inspected by its URL (§7). A floating “latest” page does not establish an older version's behavior. Otherwise omit the claim and report it rather than leaving a documentation URL in the entry's prose.

## The rule: API identifiers live only in `Software` entries

**A non-`Software` entry carries no backticked API identifier and no library-specific signpost** (Quality Checklist item 6). It may name the library in plain prose ("the joblib library") or, when it has an entry, as a wikilink (`[[scikit-learn]]`), but never its classes, functions, methods, kwargs, attributes, module paths or calling conventions. Library names are not identifiers and are never backticked. Only two backticked shapes are not identifiers (matching `lint_entry.py` and wiki-lint's scanner): a bare file extension (`.csv`, `.tar.gz`, `.nii.gz`) and a bracket special token (`[CLS]`). A load-bearing identifier may appear in the library's `Software` entry under the selective rule above; a lookup-only identifier is omitted.

## Forbidden shapes

- **No hyperparameter listings, kwarg, default-value or calling-convention documentation** anywhere in a non-Software entry; the Software entry keeps only the artifact-wide subset its own rule passes. Corpus failures: a `Proximal policy optimization` entry listing seven hyperparameters with defaults, a `Beam search` entry with `generate`, `GenerationMixin` and `num_beams`, and `Autograd` or `Batch normalization` entries with several identifiers. Each is a violation however naturally the identifiers fit the prose.
- **No standalone paragraph** whose primary content is the library's API surface. The diagnostic: if a paragraph were retitled "How to use this in [Library]," it does not belong in a non-Software entry; do not move it wholesale into the Software note either.
- **Language literals in code form** (`True`, `False`, `None`, backticked numbers) belong only in a `Software` entry whose subject the representation explains (the `Python` entry on `None`). Elsewhere use prose or math: *true*/*false* for truth values, zero/one or $0$/$1$ under prose principle 8 when the binary value is the point, "none" or "null" for absence. A `Causal mask` entry writes "a square boolean matrix with true above the main diagonal and false on and below it", not `True` and `False`; a conceptual `Boolean type` comparison stays in plain prose or math.

## Mechanical pre-finalize scan (this is the binding check)

`lint_entry.py` reports most of these shapes as `6-api-surface` (backticked spans and fenced code as errors, framings as warnings). Resolve every hit with the author test below, and search the body by hand for the phrasings listed here, because the helper does not check all of them:

- **Any backticked span** other than the two non-identifier shapes above is a violation.
- `"In PyTorch"` / `"In TensorFlow"` / `"In NumPy"` / `"In Hugging Face"` / `"In [Library]"` as a sentence opener almost always introduces how-to content, as in *"In PyTorch a causal mask can be built with `torch.triu`, and an `is_causal` flag enables…"*: an opener, a "built with" form and kwarg documentation in one sentence.
- `"[Library] implements"` / `"[Library] provides"` / `"[Library] exposes"` / `"[Library] offers"` — these verbs invite the model to describe *what* the library object does: how-to content, and under the zero cap the identifier it introduces is itself a violation.
- `"flag enables"` / `"flag controls"` / `"argument controls"` / `"argument enables"` / `"kwarg"` / `"defaults to"` — explicit kwarg/default-value documentation, forbidden anywhere outside Software entries.

For each match, the default is to **delete the sentence**, or, for an identifier folded into a parenthetical, the parenthetical. Keep a conceptual claim stripped of its API detail only when the source supports it independently of the named artifact. Library-specific behavior keeps a plain library attribution or goes entirely; never promote an implementation's behavior into a property of the underlying concept. A link such as `[[pytorch|PyTorch]]` still lets the reader reach the Software entry without the omitted identifier.

## The author test (apply during the review pass)

For each backticked token in a non-Software entry, ask: **is this an API identifier?** If yes, delete it, keeping at most the library's plain name where the sentence still needs one, or the whole sentence when it existed only to name the identifier. Nothing is created to house it: it appears in the library's `Software` entry only if it passes that entry's selective rule. If the entry cannot explain its concept without the identifier, it is probably about the software artifact itself: reclassify `type:` to `Software`, then apply the Software scope test rather than keeping the old body automatically. Such a determinate `type:` correction is ordinary QC, not a refactor.
