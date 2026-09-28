# Named-entity requests

Read this when the user asks to build one or several named entities from
identified durable sources, such as "PCA and the curse of dimensionality from
chapter 7", including acceptance of a prior run's deferred candidate or a
wiki-lint missing-entry candidate. Apply it to each named entity. A folder
request alone does not activate this mode, and it never combines thin mentions
by default.

## Resolve and test the evidence

1. Resolve every named source through normal source intake, canonical PDF
   identity, and prior-coverage checks. Extract only the named entities; do
   not extract other entities, even ones the new prose leans on (for example,
   LLE mentioned in a PCA entry). List those under
   [*Entities not requested*](review.md#run-report) instead of creating them.
   If every source is already cited by an existing target and the request is to
   correct that target, use wiki-lint's source-backed correction mode instead.
2. With several sources, prove that every passage names the same contextually
   resolved entity. An ambiguous surface, homonym, or two related concepts
   cannot be joined to make the substance test pass.
3. Apply the ordinary substance and durability tests. With several sources,
   the union must explain what the entity is, how it works, what it contrasts
   with, or why it matters well enough for one self-contained atomic entry.
   Every retained source must contribute a specific verifiable claim,
   condition, equation, date, or limitation; two passing mentions do not become
   substance. A secondary source contributes only durable material.

If the evidence still fails, preserve plain-text mentions and report what
support is missing. Do not expand the source set through memory or web search.
A web reference that will change the note must first become a durable clipping.

## Build the named entities

Record each retained claim against its source. For a PDF, also record the
physical page; for a clipping, use the anchorless Markdown citation required by
the ordinary source-reference rules. Then run the ordinary collision,
create-or-merge, interlink, review, and publication gates for the named
entities only; the step-7 missed-entity audit is likewise limited to them. List
every contributing source in `sources:`; omit a named source whose text added
no selected claim. Integrate each result as one coherent entry rather than
stacking one paragraph per source.

Report each named entity, sources considered and retained, substance and
identity decisions, create/merge/no-op result, citations, and all ordinary
review outcomes. Name any retained source that had no prior coverage: once an
entry cites it, a folder run skips it, and a later request naming the source
[fills in](source-intake.md#check-prior-coverage) its other entities. The
request is rerun authority for the named entities and their sources only; it is
not authority for unrelated extraction or a structural refactor of pre-existing
entries.
