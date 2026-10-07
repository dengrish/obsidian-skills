# QC items — enforcement and routing (Tasks 1 and 1b)

**Read this before Task 1 or Task 1b fixes any entry.** The numbered acceptance rules
come from wiki-build's [Quality Checklist](../../wiki-build/references/quality-checklist.md)
and the canonical guides it links. This file does not duplicate those guides in full. It
owns wiki-lint's finding-to-action rules, source-independent review, the
hand-off to Task 1b, and repair boundaries.

All semantic-review instructions here are carried out autonomously by the executing agent.
They do not require the user or another human to inspect every
note or approve an ordinary correction. Task 1 repairs what the note and vault
establish. A semantic finding they do not settle goes to
[Task 1b](../SKILL.md#task-1b--content-repair), which repairs it in the same
run from the entry's cited sources or accurate background, merges and splits
included. Only a deletion, a split or merge that is a close call or that a
refactor blocker stops, a conflict no evidence settles, or a user-owned state
decision stays a report, and it does not block the current run.

Related procedures:

- [Content repair (Task 1b)](../SKILL.md#task-1b--content-repair) and its
  [source-backed correction protocol](source-backed-corrections.md)
- [Scanner keys and coverage](scanner.md#item-keys-in-problems)
- [Flashcard definition review](flashcards.md#flashcard-definition-review-item-19)
- [Dangling-link protocol](link-hygiene.md#dangling-links-target-missing)
- [Date and review-state ownership](../SKILL.md#dates)
- [Reports and backlogs](backlogs.md)

## Finding actions

Route a finding before editing. A finding identifies a condition; it never
expands the requested scope or authorizes a change beyond this skill's
ownership.

| Finding or worklist | Action |
| --- | --- |
| Ordinary `itemN` | Apply the determinate, source-independent correction allowed by item N below. Hand a finding that needs the entry's sources, accurate background or a coordinated cross-entry change to Task 1b; report only what Task 1b cannot settle, such as ambiguous ownership. |
| `item0` | Report the unreadable path and error; there is no parsed entry to repair. Its unknown aliases suppress dependent link actions until readability is restored and the vault is rescanned; direct-filename checks remain usable. |
| `item1` | Repair only what the file itself establishes. Never invent title, dates, or review state, and preserve links to the real file. The lines of an `issues:` value are never an item-1 repair ([item 2](#2-field-order-and-quoting)). |
| `item2/read-type` | Task 1 repair: [item 2](#2-field-order-and-quoting). |
| `item2/type-enum` | Write the exact enum spelling only when the body makes the intended type unambiguous; otherwise preserve and report. |
| `item2/read-missing`, `item2/read-null`, `item2/read-unknown` | Report only: [item 2](#2-field-order-and-quoting). |
| `item2/issues-missing` | Task 1 repair: [item 2](#2-field-order-and-quoting). |
| `item2/issues-malformed` | Report only and preserve: [item 2](#2-field-order-and-quoting). |
| `item2/parents-null` | Task 1 repair: [item 2](#2-field-order-and-quoting). |
| `item2/parents-form` | Preserve usable targets while normalizing representation and unambiguous target spelling. A parent that resolves to a MOC is report-only here and never respelled; Task 3 replaces it (`moc-parent`). Re-derive invalid relationships only in Task 3's authorized closure. |
| `item2/obsidian-key` | Report and preserve exactly; it is valid user configuration. |
| `item2/provenance` | Preserve the record and report malformed, duplicate or misplaced attribution. Legacy metadata is read-only compatibility data; do not add or refresh it or infer a historical creator. |
| `item3`, `item3/report-only` | Report only: [item 3](#3-dates). |
| `item4/source-identity` | Task 1 repair only once [item 4](#4-sources)'s provenance test proves one source; otherwise report. |
| `item9/imperative-link` | Integrate the link when adjacent prose already states the relationship and the edit adds no claim. Otherwise Task 1b states the relationship from the entry's or the linked entry's cited source, or accurate background, and integrates the link. |
| `item9/duplicate-sentence` | A cross-entry ownership candidate. Task 1b consolidates it into its owner under [item 9](#9-body-structure-coherence-flow-and-scope). Normalized similarity alone proves neither copy wrong and never chooses the owner. |
| `item9/acronym-expansion` | Task 1b adds the full form in a parenthetical directly after the bolded title, from the cited source or accurate background, under [item 14](#14-self-containment); item 17's alias gates and item 19's line-3 counterpart follow in the same edit. A title whose letters stand for no established full form keeps its opener. |
| `item10/case`, `item10/alias` | In Task 1, canonicalize the unambiguous existing target while preserving anchor and explicit display label. A real MOC filename outranks a Wiki alias, but only a recognized, readable canonical MOC (discipline or misc) with sole filename ownership gets an `item10/case` repair adding `MOCs/`. Unknown MOC owners are report-only. Keep required Wiki qualification when the target is an entry. Never create a variant file. |
| `item10/self` | In Task 2, unlink an ordinary self-mention. Preserve real section/block navigation as a local `[[#Heading|Display]]` or `[[^block|Display]]` anchor. |
| `item10/ambiguous` | Preserve the whole link and report its competing owners. |
| `item10/unparsed` | Report only: [item 10](#10-wikilinks); the target file's `item0` or `item1` governs repair. |
| `item10/moc` | Preserve the original bare or explicit destination for an unknown MOC target, and preserve missing/unsafe explicit `MOCs/` targets. Report and route resolution to authorized Task 3 work; never automatically qualify an unknown owner, unlink it as an entry dangler, or redirect it to a Wiki alias. |
| `item10/dangling` | Task 1b first settles the target under its [dangler hand-off](refactors.md#dangling-link-hand-off): the entry the [missing-entry rule](refactors.md#create-a-missing-entry) allows, or a gloss for each mention that needs the term; Task 2 resolves the rest under its [dangler protocol](link-hygiene.md#dangling-links-target-missing), which leaves a link to a missing root for Task 3. |
| `item10/dup`, `item10/late-link` | Use Task 2's [link protocol](link-hygiene.md), not an ordinary Task 1 repair. |
| `item10/table`, `item10/redundant-pipe` | Task 1 repair: [item 10](#10-wikilinks). |
| `item12/equation-typography` | In descriptions, replace raw ℓ-norm notation with plain `ell-one`/`ell-two` and retain Unicode `μm`. In prose and card prompts, replace raw ℓ-norm and `μm`/`µm` notation with canonical inline LaTeX. |
| `item12/equation-coverage-candidate` | Inspect the local prose or inline formula. Apply the explanatory-value test; add math only when it clarifies the concept and the note supplies the relationship. Clear prose may be the correct outcome. |
| `item12/equation-format` | Preserve the existing equation and put its opening and closing `$$` delimiters on separate lines. Do not add a duplicate display. |
| `item12/equation-split-candidate` | When the flagged line really holds two equations, give each its own line under the [equation guide](../../wiki-build/references/equations.md#2-form--defining-equations-are-display-math): a separate display beside the prose that introduces it, or a row of an `aligned` or `gathered` display. Keep the math unchanged; this formatting repair changes no dates or review state. |
| `item12/boilerplate-candidate` | Remove each listed condition the formula already presupposes, under item 12's well-definedness rule, and report the removal. Keep a range the definition needs. On card line 1, shorten the math, or replace it with its verbal core, only when the tested claim is unchanged, preserving the cue, answer line, and attachments. |
| `item12/panel-composite`, `item12/remote-image`, `item12/missing-image` | Report only: [item 12](#12-equations-images-and-tables). |
| `image_folder_findings` | Report and preserve nested, staging, unreadable, or portable-name-collision paths. Collision records retain all owner paths; an unreadable inventory also suppresses missing-image claims. |
| `item17/alias-candidate` | Apply the same-entity, collision, cross-domain, and Organism-common-name gates before adding anything. |
| `item18/partial-label` | Task 1 repair; a label naming another entity goes to Task 1b: [item 18](#18-alias-form-collisions-and-display-labels). |
| `item18/cross-domain-alias` | The alias is a bare cross-domain term, which is never an alias. Task 1b removes it through the [alias-removal protocol](refactors.md#remove-a-semantic-invalid-alias). |
| `item19` | Apply the format floor only after reading [flashcard maintenance](flashcards.md). Remove each extra card under the [card set](flashcards.md#card-set) rule; a finding on an extra card, its line-1 `item12` findings included, needs no repair beyond that removal. Content after a card's line 3 that is not a recognized attachment is report-only. |
| `item19/brevity-candidate` | Review the cue (line 1) under [flashcard maintenance](flashcards.md#improving-the-card) and shorten it when the shorter cue is clearer and still rules out its rivals; the candidate alone is never an order. |
| `item19/hedge-candidate` | Review the cue under [flashcard maintenance](flashcards.md#improving-the-card): drop a hedge whose plain claim the note establishes for the ordinary case, and keep a word that states the definition itself; the candidate alone is never an order. |
| `item19/sr-marker` | Reword the line so it holds no `::` or `:::` outside a backtick span, and join a line that is only `?` or `??` to its neighbor, preserving its claim: write a math `::` as `\mathbin{:}\mathbin{:}`, and keep code in a backtick span or an unindented fence. For an HTML comment left open at the start of a line, indent its `<!--` by one space, keeping the comment unchanged; for a fence line no later column-0 line closes, indent that line by one space or start its closing fence at column 0. Never add or change a card for it. |
| `card_rivals` | Use as the forward check's rival list: could a rival's term answer this cue? A yes is an ambiguity defect under [flashcard maintenance](flashcards.md#flashcard-definition-review-item-19). The list is a floor, not an exhaustive rival set. |
| `rename_candidates` | When `target_exists` is false and [item 5](#5-filename-collision-and-disambiguation) makes the canonical name determinate, Task 1b retitles the entry through the [entry-retitle protocol](refactors.md#retitle-an-entry) and reports the inbound links it rewrote. An occupied destination is never retitled into: a same-entity occupant goes to Task 1b's [merge check](#5-filename-collision-and-disambiguation), and any other stays a disambiguation report with its collision warning. |
| `collision_candidates` | Task 1b's [merge check](#5-filename-collision-and-disambiguation): merge the pair through the [refactor protocol](refactors.md) only when it is one entity under alternate names; a probe match alone never activates a merge. |
| `hierarchy_diagnostic` (every field) | Use as report-only Task 3 inputs. Re-derive whole generated MOCs and complete parent unions from one authorized connected closure; unsafe paths, legacy vault-root MOCs, and unknown files remain protected. Actions are in [hierarchy](hierarchy.md#read-diagnostics-and-verify-completion). |
| Semantic-invalid alias | Task 1b removes it through the [alias-removal protocol](refactors.md#remove-a-semantic-invalid-alias) when the canonical owner is unambiguous; ambiguous ownership is reported. |

## Item guide

For every item, first apply the canonical builder rule at the linked location,
then use only the linter-specific action stated here: Task 1 makes the
source-independent repairs, and each item names what it hands to Task 1b. The scanner's
[`problems` contract](scanner.md#item-keys-in-problems) is the source of truth
for its mechanical coverage; do not infer permission from a scanner message.

### 1. Valid YAML

Apply builder [item 1](../../wiki-build/references/quality-checklist.md) and the
[frontmatter guide](../../wiki-build/references/writing.md#1-frontmatter-fields).
The opening fence is on file line 1; a BOM is tolerated, a leading blank is not.
Flow lists may be empty only as `[]`. One trailing comma after the last item
is valid YAML; any other empty element is invalid. Repair only values the file
unambiguously establishes.

### 2. Field order and quoting

Apply the canonical [fields and quoting](../../wiki-build/references/writing.md#1-frontmatter-fields).
Schema order is `title`, `type`, `aliases`, `sources`, `created`, `updated`, `description`, `tags`, `parents`, `read`, `issues`.
Only `aliases` is optional; the other ten keys are required. Recover a
missing or valueless title only from one unambiguous canonical name evidenced
by the entry, because title-dependent checks otherwise cannot run.

Linter-specific routing:

- Normalize a type to one of the 15 enum values only when the body makes the
  semantic type clear. Otherwise preserve and report.
- Normalize empty `parents:` to `parents: []`. For a populated scalar, flow
  list, duplicate, or path/anchor/display/`.md` spelling, preserve every usable
  target and write the canonical block list. Re-derive a missing, ambiguous,
  or unparsed relationship only in Task 3.
- A missing, null, or unrecognizable `read:` has no recoverable answer: report
  it and do not write one. A quoted boolean, YAML `yes`/`no`, or `0`/`1`
  carries a recognizable answer, so normalize only its representation to the
  equivalent bare boolean. A [resolved user issue](../SKILL.md#user-issues)
  is the one exception: it sets `read: false`, inserting a missing key
  directly before `issues:`.
- For `item2/issues-missing`, insert `issues: ""` directly after `read:`, or,
  when `read:` is absent, after the last schema key that precedes it. This is
  a format repair: dates and `read:` stay unchanged. Every blank spelling
  [§2d](../../../shared/CONVENTIONS.md#2d-issues--the-users-issue-inbox)
  lists conforms and stays as written. A non-blank value is the user's text,
  kept byte-for-byte and handled under [User issues](../SKILL.md#user-issues);
  a malformed one (`item2/issues-malformed`) is reported and never rewritten.
  Task 1 never quotes, re-indents, joins or otherwise repairs a line of an
  `issues:` value; the scanner reports a bad one only as
  `item2/issues-malformed`.
- Obsidian-owned appearance and publish properties are valid user state:
  report and preserve them. Preserve a populated legacy `importance:` without
  treating it as required or unexpected.
- Preserve and report unexpected frontmatter properties. A schema mismatch
  alone does not authorize deleting or repurposing user metadata; determine
  required tags from the entry under the ordinary tag rules.

### 3. Dates

Require valid `YYYY-MM-DD` dates with `created <= updated`, as builder
[item 3](../../wiki-build/references/quality-checklist.md) and the
[date fields](../../wiki-build/references/writing.md#created--updated) define. The linter
writes neither field. Report invalid values, impossible ordering, and any
history-dependent question; do not guess which date is wrong or try to make
`updated:` equal a presumed merge date.

### 4. Sources

Use the canonical [source format](../../wiki-build/references/writing.md#sources).
Every entry, a [discipline root](hierarchy.md#establish-discipline-roots)
included, cites at least one source; an empty `sources:` is reported, never
filled from memory. An online page's URL item is valid as a quoted,
full http(s) address. Task 1 never fetches it; Task 1b may read the page to
verify a repair under the [source-backed correction protocol](source-backed-corrections.md).
Lint never converts it to or from a vault citation, and reports a malformed one
without guessing a repair.
Remove an exact repeated list item, URL items included. A same-stem PDF/Markdown pair remains
`item4/source-identity` until decoded `sources:` or legacy `source:` in the
Markdown note proves that it summarizes that PDF. Only then keep the anchored
PDF citation, remove the duplicate Markdown citation, and report the evidence.
Preserve an independent clipping and every uncertain pair. The linter checks
page-anchor form; the physical page's factual correctness needs the source.

### 5. Filename, collision, and disambiguation

Apply the canonical [naming rules](../../wiki-build/references/writing.md#3-wikilinks-and-naming).
Task 1 never renames. A title/filename mismatch goes to Task 1b, which
retitles the entry through the [entry-retitle protocol](refactors.md#retitle-an-entry)
when the canonical name is determinate and its slug is free.
If the slug is occupied, preserve both files: a same-entity occupant goes to
the merge check below, and any other is reported with both paths as an
unresolved disambiguation; the lint run still completes.
Whole-vault maintenance uses slug equality, micro-sign normalization,
singular/plural, hyphen-collapse, word-order, and light stem morphology. When
several probes flag the same pair, report only the most specific probe label;
no probe chooses an entry owner. The linter deliberately omits the noisy
create-time token-superset probe. While reading, also note semantic synonym
duplicates that shape probes cannot find.

**Merge check.** Collision-probe matches and synonym duplicates are Task 1b's
merge candidates. Task 1b merges two or more entries through the
[refactor protocol](refactors.md) only when their definitions, cited sources
and accurate background verify one entity under alternate names
([step 2](refactors.md#establish-evidence-and-complete-scope)). Related
concepts, overlapping wording or a probe match alone never activate a merge.
A close call stays unapplied under
[Task 1b's rule](../SKILL.md#task-1b--content-repair).

A bare cross-domain title is retitled the same way. The scanner flags a slug
that is a word or phrase of the builder's corpus (`tree-of-life`); the semantic
pass tests every other bare title against the
[cross-domain naming rule](../../wiki-build/references/special-titles.md#cross-domain-term-disambiguation),
whose test (a) also fires when the bare encyclopedia landing is another sense
(Tree of life lands on the mythological motif). When that rule makes the
qualified title determinate and its slug is free, Task 1b retitles the entry;
the old bare slug never stays as an alias. A slug the same entity occupies
goes to the merge check above; one another entity occupies, or an
indeterminate qualifier, stays a report. Report an unsluggable title with a
representable alternative.

### 6. Type and API surface

Apply [API surface](../../wiki-build/references/api-surface.md) in full.
Non-`Software` entries permit no API identifiers, fenced code, Python literals
in code form, implementation signposts, recipes, or identifier catalogs.
`Software` may retain identifiers only when they explain an artifact-wide
interface or design convention; counting tokens cannot establish that scope.
Use [the strip-or-reclassify procedure](#coding-content-in-non-software-entries-item-6)
for determinate non-`Software` findings. Trimming substantive prose from an
existing `Software` entry needs source-backed selection, which Task 1b makes
from the entry's cited source.

### 7. Description

Apply the canonical [description rule](../../wiki-build/references/writing.md#description)
to every entry. Besides the scanner's form checks, review the
grammatical subject, current-status tense, precise phrasing, mathematical
completeness, and whether it describes the prototype rather than a variant
([lead with the prototype](../../wiki-build/references/writing.md#prose-principles)).
Repair awkward wording or empty framing only when it is a
concrete clarity defect; do not rewrite an already clear description. A
plain-language mathematical definition must retain every operation that
determines the quantity. Task 1 fixes it when the note establishes the
corrected wording. Otherwise Task 1b corrects a variant, a wrong sense or a
wrong fact from the entry's cited source or accurate background, leading with
the prototype, and keeps the description, opener and card aligned in the same
edit. A wrong sense includes a definition that leads with a property of the
subject, such as its selectivity, regulation, distribution or a consequence,
instead of what the subject is, even when the source's sentence is phrased
that way; the property moves to the body (gene expression is the process by
which a gene's information makes RNA and protein, and differential expression
follows in the body). So is a definition by exclusion
([principle 1](../../wiki-build/references/writing.md#prose-principles)): a
rule stated as a prohibition leads with what it allows.

### 8. Tags

Use the shared discipline enum plus the canonical [tag rule](../../wiki-build/references/writing.md#tags)
and [calibration](../../wiki-build/references/calibration.md). Apply
unambiguous format fixes: block-list form, `#`, double quotes, exact enum case,
safe abbreviation expansion, wikilink-to-tag conversion for a known enum
member, and duplicate removal after canonicalization.

Semantic disciplinary ownership remains a judgment; Wiki tags hold exactly
one home. Re-home a single-tag entry only when the entry and vault make the
canonical home unambiguous; otherwise report the competing candidates. Reduce
a legacy multi-tag list to one of its tags using the entry's main treatment
and the calibration's governing test and defaults, reporting a close call with
its two-option framing. Leave multiple tags only when the entry's identity is
unresolved (for example, it conflates two concepts); Task 1b's
[split](#9-body-structure-coherence-flow-and-scope) then tags each result, and
a split it does not apply leaves that blocker reported. For a genuinely blank key or empty list, inspect the note and assign its
best supported specific discipline, or `"#misc"` alone if none fits. Never combine
misc with specific tags. Missing, malformed, mixed, or uncertain metadata
requires its own evidence-based resolution, not blind replacement with misc.
When retagging, keep the old group as prior-group evidence for Task 3's closure.
A [user issue](../SKILL.md#user-issues) about an entry's tag or placement is
evidence for this check and for Task 3's placement review, which resolve it
under these rules or report its blocker.

### 9. Body structure, coherence, flow, and scope

Apply builder [item 9](../../wiki-build/references/quality-checklist.md), the
[body guide](../../wiki-build/references/writing.md#2-the-body), and the
[Person/Event date forms](../../wiki-build/references/rare-types.md#dates-in-the-opener-person-and-event).
There is no body sentence, paragraph, word, or heading-count target.

**Coherence review.** Compare the title and qualifier with the description,
opener, equations, flashcard, and the neighbors the builder's
[overlap audit](../../wiki-build/references/review.md#overlapownership-audit-this-runs-entries-and-their-relevant-neighbors)
names: body and Related link targets, backlinkers, entries citing the same
source, and family members. They must identify the same
entity and sense without incompatible scope, conditions, direction, or
notation. A conflict that requires choosing or changing a fact goes to
Task 1b, which corrects every affected entry under the correction protocol's
[*Conflicts*](source-backed-corrections.md#correct-and-publish) rule. State
the plain claim under principle 3 (a hedge or caveat that covers only an edge
case goes even when the source makes it; evidence-bearing uncertainty stays),
or trim a neighbor's detail to the relationship and a wikilink, rather than
appending qualifications. The
description, opening paragraph and primary card lead with the prototype, never
a variant: a variant, a secondary sense of the name or another application is
named once, later in the body, after the general explanation. When the body
already states the prototype, Task 1 repairs the description under item 7 and
the card under item 19; moving an opening-paragraph mention is Task 1b's,
which folds it, with its link, into the later passage (Learning rate's
boosting clause), applying builder
[item 13](../../wiki-build/references/quality-checklist.md)'s each-sense-once rule
outside merges too. When the prototype is missing, Task 1b writes it from the
cited source or accurate background and keeps the variant as one linked
example. Task 1b likewise frames an entry in its
[own field](../../wiki-build/references/writing.md#prose-principles): a
general concept's display never borrows one application's parameter notation,
and the entry names and links its nearest contrast when the subject has one. A
neighbor conflict may also expose a wrong link, a duplicated explanation
(consolidated below), or an atomicity failure (split below).

**Atomicity review.** An entry that independently defines several durable
subjects fails the builder's
[atomicity test](../../wiki-build/references/writing.md#body-structure).
Task 1b splits it through the [refactor protocol](refactors.md) when each
split-off subject passes the substance test with support in the entry's cited
sources or accurate background
([step 2](refactors.md#establish-evidence-and-complete-scope)). A long note,
several headings or several sources alone never activate a split; inherent
mechanisms, stages, conditions and limitations stay with their subject. A
close call stays unapplied under
[Task 1b's rule](../SKILL.md#task-1b--content-repair).

**Editorial and ownership review.** Apply the shared
[prose principles](../../wiki-build/references/writing.md#prose-principles)
to phrasing, sentence clarity, paragraph focus, transitions, and succinctness.
Judge a concrete defect, not a preference for different wording. Inspect
equation lead-ins and paragraph endings as well as the opening sentences.
Bullets are parallel, not sequential; body links sit in sentences that state
their relationships. Task 1b trims source/tutorial scaffolding and
application catalogs that do not serve the entry, after checking the cited
source. It consolidates a definition, explanation, argument, worked example
or property with its justification duplicated across entries into its owner
under the [consolidation rule](refactors.md#build-the-refactored-entries);
every such trim follows [Dates](../SKILL.md#dates).

A statement the entry leaves unexplained, such as an equation without its
meaning, a complexity without its reason, a derivation step or a result, gets
its reason in Task 1b, in one sentence from the cited source or accurate
background; a term with neither definition nor link follows
[item 14](#14-self-containment). When no accurate reason exists because the
stated result is itself wrong or imprecise, the defect is a conflict between
the cited source and standard references, resolved as in the coherence review:
Task 1b corrects the result, keeping the source's figure only within the scope
that makes it true, and never invents a reason. Length, a missing transition
word, list shape, or lexical similarity alone proves nothing.

**Caveat review.** Inspect qualifications, final paragraphs, captions and the
description for the hedges and caveats
[principle 3](../../wiki-build/references/writing.md#prose-principles)
excludes, including a claim hedged below its source; card line 1 follows
[item 19](#19-flashcards). Never add caveats from memory; a main limitation
the source teaches is explanation. Task 1 removes empty rhetoric and repetition
(the local repairs below) and well-definedness boilerplate (item 12). Task 1b
removes every hedge and caveat principle 3 excludes, its full "Leave out" list
included (defensive terminology distinctions, implementation and numerical
details such as a routine's tolerance, rare failure modes, troubleshooting
about neighbors), under
[*Hedges*](source-backed-corrections.md#correct-and-publish). It keeps a limit
only when the plain claim is false for the ordinary case, naming the condition
instead of a hedge word, and keeps evidence-bearing uncertainty in research
findings; a source-supported detail can still be unnecessary.

**Depth review.** Apply the builder's
[core-facet check](../../wiki-build/references/writing.md#prose-principles) to
every in-scope entry, whatever its type and however detailed it already is.
Task 1b supplies each missing facet: a model's or ensemble's prediction step
and how it trains, a display's verbal reading, a concrete case, a
category's canonical members (at least three) that have entries, or a discipline
root's form. For a Concept, it then applies the builder's
[row-9 test](../../wiki-build/references/quality-checklist.md) (could a reader
explain how it works from the note alone?) and supplies only what that test or
principle 5's [term audit](../../wiki-build/references/writing.md#editorial-reread)
names as missing. Both work under the source-backed
[*Deepening*](source-backed-corrections.md) rules, from the entry's cited
sources and accurate background. A gap that only an unbuilt source would fill
waits for that source's whole build under those rules and is not proposed.

**Local editorial repairs.** Apply these autonomously when the existing entry
establishes an unambiguous meaning:

- Repair grammar, fragments, awkward phrasing, or an unclear pronoun with a
  known referent; split or recombine overloaded sentences without changing
  their claims.
- Replace opaque or decorative wording with its direct equivalent. Remove
  empty framing or consolidate repetition only when it adds no distinct
  claim, condition, emphasis needed for interpretation, or explanatory step.
- Reorder sentences within a paragraph or between adjacent paragraphs under
  one heading; split or merge adjacent paragraphs to restore focus and useful
  progression. Keep definitions before uses and qualifiers beside their claims.
- Clarify a transition only from a relationship already established in the
  entry. Do not infer causation, contrast, chronology, or generality from
  proximity; use a paragraph boundary when no bridge is supported.
- Convert an already explicit sequence from bullets to prose, or integrate a
  navigation-only link when adjacent prose already states the relationship.
- Rewrite parallel facts about several items (the same gene in several
  organisms, one property per variant) as one bullet per item, keeping every
  claim.

**Preservation and verification.** Task 1's local repairs change prose expression, not
the knowledge recorded. Preserve every substantive claim, condition, degree,
uncertainty, attribution, and scenario boundary. An illustrative example must
remain an example; a small improvement must not become an unqualified one.
Nor may an edit add a caveat, exception, or clarification the explanation
does not need. Keep existing link tokens, citations, math spans and numerical values,
image/table-plus-caption units, the complete flashcard section, and frontmatter
verbatim during a Task 1 item 9 edit. Do not drop a link or a qualifier when removing
repetition. After any removal, including item 12's boilerplate removals,
re-read the whole note and repair what it left behind: a connective or
referent that now points at nothing ("still", "this"), or a claim now stated
twice. Descriptions follow item 7; links, equations, exhibits, and cards
may change only under their own authorized checks, recorded separately.
Task 1's editorial changes never advance dates or reset review state; Task 1b's
changes follow [Dates](../SKILL.md#dates).

Compare protected content before and after the edit and apply the shared
[editorial reread](../../wiki-build/references/writing.md#editorial-reread)
to the finished passage. Repair any regression and re-run the per-entry lint
before publication. Leave conforming prose untouched and report the defect and
repair for each changed entry; there is no shortening quota.

If the change crosses a section, changes a fact, removes substantive content,
chooses between claims, or redistributes material across entries, Task 1
preserves it and hands it to Task 1b. Task 1b verifies the change against
every affected entry's cited sources or accurate background, changes a degree,
number, caption or math span only to match them or to drop a hedge or caveat
the caveat review excludes, and touches only the
surfaces the repair needs. Every Task 1b repair fixes a concrete defect a
builder rule names; it never rewrites conforming prose, so a rerun on
unchanged evidence changes nothing.

For a missing `Person`/`Event` opener date, copy the exact date only when it is
already present elsewhere in the entry. Normalize an existing malformed date
only when all values and qualifiers are unambiguous. Otherwise report it.

### 10. Wikilinks

Apply [CONVENTIONS §6](../../../shared/CONVENTIONS.md#6-wikilink-forms) and the
builder's [link form guidance](../../wiki-build/references/writing.md#link-form).
Judge first occurrence by resolved entry, not raw spelling; a real file outranks
an alias, while ambiguous basename or alias ownership stays unresolved. In
Task 1, canonicalize unambiguous case, Unicode, path, `.md`, or alias variants
without changing display text or anchors. Replace table-cell links with visible
plain text. In body prose, collapse an exact `[[slug|slug]]` to `[[slug]]`;
do not apply that cleanup to the Related footer, whose canonical-title pipe is
mandatory even when the title text equals the slug. Preserve unparsed and
ambiguous targets.

Self-links, duplicate resolving links, and dangling targets use Task 2's
[link protocol](link-hygiene.md). Preserve genuine local section/block
navigation. The scanner masks listings and parsed tables and excludes embeds;
consult its [item keys](scanner.md#item-keys-in-problems) and
[false-positive notes](scanner.md#before-you-call-a-finding-a-false-positive)
before disputing a finding or treating literal sample syntax as a link.

### 11. Related footer

Use the canonical [Related footer](../../wiki-build/references/writing.md#the-related-footer).
Keep one ` · `-separated line and pipe every target to its canonical title,
with no slug-equal exception, including all-lowercase titles. Converting a bare
footer link to that form is determinate. A footer with more than roughly 12
links, the guide's merge-growth bound, is reported rather than pruned.

### 12. Equations, images, and tables

The equation clauses are owned by `wiki-build/references/equations.md`; apply
that [canonical policy](../../wiki-build/references/equations.md) rather than
reconstructing it from scanner output. Apply the separate canonical
[media rules](../../wiki-build/references/media.md) to existing exhibits.
The adjacent [body math typography](../../wiki-build/references/writing.md#prose-principles)
still governs plain quantities and escaped literal dollars.

**Media and table format.** Preserve both valid embed classes: a local image is
an Obsidian embed by bare basename, while an external clipping image may remain
standard Markdown with its URL. A remote embed is report-only; converting its
syntax would break it. Report that reprocessing the source clipping with
`clipping-clean` can localize it. Every existing image or Markdown table has a brief
plain-text italic caption immediately below it; inline LaTeX is the only
caption markup. Keep exhibits beside the prose they clarify, never before the
opener, detached at the end, or grouped as a gallery; one motivating paragraph
supports at most one image or table. A clear local placement or format repair
is allowed. Task 1b corrects caption content against the cited figure or page,
whose numbers a caption matches exactly; a caption drops a hedge principle 3
excludes even when the source's own caption carries it. An ambiguous placement
is reported.

Never delete a missing embed or caption: repair belongs to extraction or
pdf-organize's source rename. Preserve a composite and lowercase-suffixed panel
until source-backed review decides whether the entry needs the default
composite or the panel-specific view. Figure selection, source fidelity,
table values, and retained rows or columns remain source-dependent: Task 1b
checks them against the cited source when a repair depends on them. An unused
image file is not itself a missing-content finding.

**Equation coverage and usefulness.** The scanner emits a conservative
`item12/equation-coverage-candidate`; inspect it autonomously rather than treating
it as a command to add math. Apply the canonical explanatory-value test first.
A simple verbal rule such as hard voting can remain prose-only even when every
operation is specified. Do not manufacture an argmax/indicator formalism for
it. Task 1 inserts a useful equation only when the note's own
prose supplies every operand, operation, and essential assumption. A verified
standard equation absent from that prose, such as a confidence interval's
estimate plus or minus a critical value times its standard error, is Task 1b's
to add from the cited source or accurate background, with every symbol bound
and the relation explained. Never invent a denominator or generalize a
restricted case without a source or standard form.

Preserve assumptions that determine the mathematical claim, following the
[equation guide](../../wiki-build/references/equations.md#1-coverage--explanatory-value-before-notation).
Do not add exhaustive boundary handling from memory or turn an explanatory
formula into an implementation specification. Task 1b verifies and removes
unhelpful equations, notation-only prose, symbols no display uses,
corresponding card math, and unnecessary caveats through source-backed
correction, reporting each removal; no substantive condition is removed
silently. The
well-definedness boilerplate that guide lists for body prose is not a
substantive condition: ordinary lint removes it, including from symbol
bindings, and reports the removal. The scanner's
`item12/boilerplate-candidate` lists the common shapes (nonempty and count
guards, sign ranges on named strengths or rates, probabilities summing to one,
and card sums over every term); the agent still reads every binding, since the
floor is conservative and a listed range can be one the definition needs.
Flashcard line 1 follows [flashcard maintenance](flashcards.md).

**Equation form and notation.** Promote a defining inline equation to its own
display block; keep inline symbol references, bounds, complexity, and worked
parameter choices inline. Bind every symbol nearby. Task 1 normalizes only
typography within one entry (bold vectors, `\text{}` names, the
instance/component index form). Renaming a symbol to the
[canonical table](../../wiki-build/references/equations.md)'s,
to the field's standard or to a linked entry's notation for the same quantity,
and normalizing the minority of disagreeing siblings, is Task 1b's; it updates
every display and prose reference in the same edit. When siblings disagree,
the table wins (entropy $H(p)$,
cross entropy $H(p, q)$, Kullback–Leibler divergence
$D_{\text{KL}}(p \parallel q)$); outside the table, the field's standard
symbol wins, then the notation the most-linked entry uses. A logarithm base
that defines the unit is stated once in prose (bits), not as a subscript on
the symbol. Preserve field-specific standard notation, and report a choice
only when none of these rules decides.

Per [Dates](../SKILL.md#dates), Task 1's equation fixes write neither `created:`,
`updated:`, nor `read:`. An insertion into an entry whose `read:` is `true` is
named under *Notes for the user* with the slug and equation, so the user may
decide whether to clear their checkbox. In Task 1b an inserted equation
follows wiki-build's [body-change rule](../../wiki-build/references/merge.md#the-read-reset)
instead, and a notation rename advances `updated:` and keeps `read:`. Group
every insertion, promotion, removal, and notation change under item 12 in the
run report.

### 13. Merge integrity

In a source-independent run, apply only the structural floor of builder
[item 13](../../wiki-build/references/quality-checklist.md) and its
[merge logic](../../wiki-build/references/merge.md#merge-logic): one opener and no
stacked-body scars such as duplicated openings, stray frontmatter keys,
unexpected `---` fences, or standalone digit lines. Listings are excluded; a
schema-shaped line inside a `Software` example is not a repair target. Actual
source-merge integrity is not applicable without a merge.

### 14. Self-containment

Apply [prose principle 5](../../wiki-build/references/writing.md#prose-principles)
in full. Task 1 re-subjects source-meta prose on the entity, or names people
directly, when the surrounding sentence makes the replacement unambiguous
without changing claim, attribution, or certainty; otherwise Task 1b corrects
it from the cited source. Task 1b completes the rest of principle 5 from the
cited source or accurate background:

- A term the entry uses with neither definition nor resolving link is linked
  when its entry exists, and otherwise gets a brief defining clause; a
  dangling link's term follows the
  [dangler hand-off](refactors.md#dangling-link-hand-off). A term that meets
  the [missing-entry rule](refactors.md#create-a-missing-entry) gets its own
  entry instead, which Task 2 then links.
- The subject shows its acronym ↔ full-form counterpart on first mention under
  5(e)–(f): `the **standard deviation** (SD)`,
  `**MNIST** (Modified National Institute of Standards and Technology)`.
  Item 17's alias gates and item 19's line-3 counterpart follow in the same
  edit.

Preserve the named-work exception: “the GPT-3 paper”
and “the authors of SGDR” identify wiki entities; bare “the paper” and “the
authors” do not.

### 15. Example discipline

Apply builder [item 15](../../wiki-build/references/quality-checklist.md) and
[prose principle 7](../../wiki-build/references/writing.md#prose-principles)
during semantic review, judging an example by purpose, never by length.
Trimming an unnecessary, tangential or repetitive example needs the source, so
Task 1b does it after reading the cited source. A worked example lives in one
entry, its owner under item 9's consolidation; the others state the
consequence and link the owner. A Concept that is abstract, quantitative or
procedural (a task such as binary classification, a method, a model, a
quantity or a process) and whose body names no concrete instance gets one in
Task 1b, from the cited source or accurate background. Scaffolding and application catalogs belong to item 9,
`Software` API catalogs to item 6.

### 16. Bold, italic, and code typography

Apply the canonical [emphasis rules](../../wiki-build/references/flashcards-and-emphasis.md#5-bold-and-italic), [typography for works, organisms and genes](../../wiki-build/references/rare-types.md#typography-for-works-organisms-and-genes) and [mathematical title forms](../../wiki-build/references/special-titles.md#base-term-and-mathematical-plain-forms).
Fix unenumerated bold, emphasis wrapped around links/math/code, and missing
backticks on literal extensions or `[CLS]`/`[MASK]`/`[SEP]`/`[IMG]` tokens.
The scanner recognizes a conservative extension list; review uncommon literal
extensions too. A pure inline-math title may use outer bold in its exact first
opener slot (`**$R^{+}$**`); the same wrapping anywhere else remains misuse.
Preserve the exact special opener forms for symbols, `Work` titles, and
evidence-backed scientific `Organism` names, including plain strain/isolate/
serovar/subtype suffixes.

An ambiguous taxon-shaped, rank-marked, or genus-only title needs the source:
Task 1b verifies it against the cited source, and plausible typography stays
unchanged when the source does not settle it.
Once visible title text matches, either plausible emphasis may remain without
creating a recurring finding.

### 17. Alias identity and completeness

Use the canonical [alias rule](../../wiki-build/references/writing.md#aliases).
The note body itself can establish a missing alternate name for its subject;
add its slug only after the same-entity, own-slug, cross-domain, Organism
common-name, and whole-vault collision gates. A word from the builder's
[cross-domain corpus](../../wiki-build/references/special-titles.md#cross-domain-term-disambiguation)
never becomes an alias, so the scanner does not propose one; its italic
introduction stays in the body. A semantic-invalid existing alias
is not list cleanup: Task 1 preserves it, and Task 1b removes it through the
[alias-removal protocol](refactors.md#remove-a-semantic-invalid-alias), with
the canonical owner and complete inbound rewrite. Ambiguous ownership is
reported.

### 18. Alias form, collisions, and display labels

Apply builder [item 18](../../wiki-build/references/quality-checklist.md) and the
[display-label rule](../../wiki-build/references/writing.md#display-label-casing),
including its four carve-outs, which lint preserves. Normalize determinate
alias form and duplicates; report cross-entry ownership conflicts. Never
auto-retarget a display whose exact surface belongs to another entry. Do not
create an ambiguous alias merely to silence a display-label finding. When an `item18` label is a
cross-domain synonym its target does not introduce, reword the label to a
claimed form, or let Task 1b add the synonym's italic introduction to the
target when its cited source or standard usage gives the target that name. A
recurring finding on a cross-domain word outside the corpus is a
[proposal](backlogs.md#proposal-scope) to extend the corpus.

An `item18/partial-label` keeps only the target title's modifiers
(`[[greedy-algorithm|greedy]]`). When the sentence already refers to the
target, reword it so the label is the title, an alias, an inflection, or a
derived form, preserving the claim (`CART's greedy choices` → `CART is a
greedy algorithm: its choices`). When the label names a different entity
(`[[feature-engineering|features]]` for input features), Task 1 leaves the
link, and Task 1b settles from the sentence and the cited source which entity
it means. It rewords the sentence so the label names the target when the
target is meant, retargets the link to the meant entity's existing entry with
the label kept, or unlinks the label to plain text when that entity has no
entry. A surface match alone never retargets a link.

### 19. Flashcards

Apply the canonical [card format](../../wiki-build/references/flashcards-and-emphasis.md#4-flashcards)
and [flashcard maintenance](flashcards.md). Every entry except a discipline
root, which needs no card ([hierarchy](hierarchy.md#establish-discipline-roots)),
has a Flashcards section after the Related footer and separator, holding its
one `??` definition card. Repair a variant heading in place rather than adding
a section. Repair a missing or empty section by writing the card from the
entry's already-established main claim, with `??` and the canonical primary
answer, and itemize the addition. Routine lint never adds a second card.

Inspect the definition card semantically: leaks and reconstructions, a
primary answer that omits a qualifying opener binding, and any line-1 math,
even when the scanner is silent. [Improve](flashcards.md#improving-the-card)
its line 1, up to a complete rewrite, whenever the result is clearer, more
precise, more concise or a fairer definition; a card that already meets the
guide stays byte-for-byte. Keep its separator, apart from the one
[`??` restoration](../../wiki-build/references/flashcards-and-emphasis.md#line-2-the-separator),
and every recognized scheduling or block-ID attachment byte-for-byte and in
place. Remove every [other card](flashcards.md#card-set) and quote it
verbatim, attachments included, in the report. When a Task 1b repair changes
the claim the definition card tests, the card follows in the same edit.

## Coding content in non-Software entries (item 6)

The rule is type-based: a non-`Software` entry permits zero API identifiers or
code listings, even as a supposedly helpful signpost. The scanner's mechanical
floor does not decide why the code is present. Choose between two actions:

- **Conceptual entry with stray implementation detail:** remove only the
  parenthetical or sentence whose whole function is to name the API, recipe,
  default, or listing. Keep the surrounding conceptual claim and plain library
  name when it still matters. Do not create an entry for the identifier.
- **Software artifact with the wrong type:** when artifact identity is
  unambiguous, reclassify it to `Software`, then review the whole body under the
  selective Software rule. Installable or runnable artifacts such as PyTorch,
  scikit-learn, and Jupyter are `Software`; algorithmic or architectural
  contributions such as BERT, AlphaGo, and ResNet remain `Concept` even when
  their prose contains code.

A title that is itself an API identifier, such as `SGDClassifier` or
`cross_val_predict`, is a wrong title. When the underlying entity's conceptual
title is determinate and its slug is free, Task 1b retitles the entry through
the [entry-retitle protocol](refactors.md#retitle-an-entry) and strips the
remaining API detail as for a conceptual entry above. A slug occupied by the
same entity goes to the [merge check](#5-filename-collision-and-disambiguation);
an indeterminate entity, or a slug another entity occupies, is reported with
the file and inbound references left intact.

When the distinction is unclear, preserve and report. Do not gut an entry or
flip its type merely to silence a mechanical finding.
