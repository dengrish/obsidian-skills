# Quality Checklist

Apply these gates in [step 7](../SKILL.md#7-review-and-report), to audit-created entries too. Numbers match `lint_entry.py` and wiki-lint; judge helper warnings, and read for semantic checks, under each linked rule. The [lint dispositions](review.md#lint-dispositions) say how step 7 handles each lint result, report-only findings included.

| # | Gate | Rule |
|---|---|---|
| 1 | Valid YAML, fenced from line 1 | [fields](writing.md#1-frontmatter-fields) |
| 2 | Field order, keys, quoting, type enum value; new `parents: []`, bare `read: false`, `issues: ""` last; an existing `issues:` value byte-for-byte | [type](writing.md#type), [quoting](writing.md#quoting-policy), [issues](writing.md#issues), [merge](merge.md#frontmatter-and-related-footer) |
| 3 | Valid dates; `created:` fixed; `updated:` and `read:` per merge tests | [dates](writing.md#created--updated), [reset](merge.md#the-read-reset) |
| 4 | PDFs cite the introducing physical `#page=N`; Markdown unanchored; a URL item is one verified http(s) address per page, kept as found (a plain URL conforms under [§2a](../../../shared/CONVENTIONS.md#2a-wiki-entry--wikimd)), and stays on merge unless an active source proven to be the same document replaces it ([merge rule 1](merge.md#frontmatter-and-related-footer)); a split book is cited as its whole book or its chapters, never both; unresolved pairs stay | [sources](writing.md#sources), [pairs](source-cases.md#resolve-a-markdown-source) |
| 5 | Filename is the step-3 slug; probes resolved; cross-domain nouns and phrases qualified, including a term whose bare Wikipedia article is another sense | [naming](writing.md#title), [qualifiers](special-titles.md#cross-domain-term-disambiguation), [collisions](merge.md#collision-decisions) |
| 6 | Type fits the entity; no code-identifier entries; named models `Concept`; API identifiers only in `Software` | [type](writing.md#type), [API](api-surface.md) |
| 7 | One plain sentence, at most 110 characters, counted after every edit | [description](writing.md#description) |
| 8 | Exactly one quoted discipline tag, `"#misc"` alone when none fits | [tags](writing.md#tags) |
| 9 | **Opener:** main claim first, stating what the subject is in its prototype sense, with variants and other senses later, once; Person/Event dates | [body](writing.md#2-the-body), [principles](writing.md#prose-principles), [dates](rare-types.md#dates-in-the-opener-person-and-event) |
| 9 | **Scope and order:** one subject; teaching order, naming the nearest contrast | [body](writing.md#2-the-body), [principles](writing.md#prose-principles) |
| 9 | **Prose:** connected prose, no navigation-only link cues; linked concepts, arguments and examples not re-explained; parallel per-item facts as bullets | [principles](writing.md#prose-principles), [link form](writing.md#link-form) |
| 9 | **Claims:** scoped claims stated plainly, hedges swept; claims agree with linked neighbors | [principles](writing.md#prose-principles), [reread](writing.md#editorial-reread) |
| 9 | **Completeness:** core facets present (core-facet check); a reader can explain how a Concept works; no open questions (term audit) | [principles](writing.md#prose-principles), [reread](writing.md#editorial-reread) |
| 9 | **Discipline root:** defines the field, states its method of inquiry and names its main branches | [root form](writing.md#tags) |
| 10 | First eligible link per real target; none in captions or cells; merge provenance | [links](writing.md#link-form), [provenance](merge.md#integration-principle) |
| 11 | One piped ` · ` Related line within soft bounds | [footer](writing.md#the-related-footer) |
| 12 | Equations, figures and tables serve the entry; exhibits opened and captioned; defining relation first, in a display block with one equation per display line; every display understandable (terms and why it holds); complexities, iteration bounds and derivation results explained; symbols follow the notation table | [equations](equations.md), [media](media.md) |
| 13 | One integrated body, each sense and fact stated once; protected content preserved | [prototype](writing.md#prose-principles), [merge](merge.md#merge-logic) |
| 14 | Every term defined on first use, linked, or glossed in one clause; no source-meta framing or source-internal back-references | [principle 5](writing.md#prose-principles) |
| 15 | One compact example where it makes an abstract, quantitative or procedural idea click; a category concept's [canonical members](writing.md#prose-principles) (core-facet check) instead; no walkthroughs or stories | [principle 7](writing.md#prose-principles) |
| 16 | Enumerated bold and italic roles only; required opener forms, including the subject's acronym ↔ full-form counterpart | [emphasis](flashcards-and-emphasis.md#5-bold-and-italic), [acronyms](writing.md#prose-principles) (5(e)–(f)), [typography](rare-types.md#typography-for-works-organisms-and-genes), [math](special-titles.md#base-term-and-mathematical-plain-forms) |
| 17 | Aliases name this entity; body-introduced names listed | [aliases](writing.md#aliases) |
| 18 | Alias form and collisions; labels name the target | [aliases](writing.md#aliases), [labels](writing.md#display-label-casing) |
| 19 | One `??` definition card and no other, with a short verbal cue; the kept card's pre-existing separator and attachments byte-for-byte, in place, except [`??` restoration](flashcards-and-emphasis.md#line-2-the-separator) | [flashcards](flashcards-and-emphasis.md#4-flashcards) |
