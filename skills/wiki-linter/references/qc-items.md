# QC items — source-independent enforcement (Task 1)

**Read this before Task 1 fixes any entry.** The numbered acceptance rules
come from wiki-builder's [Quality Checklist](../../wiki-builder/SKILL.md#quality-checklist)
and the canonical guides it links. This file does not duplicate those guides in full. It
owns wiki-linter's finding-to-action rules, source-independent review, and
repair boundaries.

All semantic-review instructions here are carried out autonomously by the executing agent.
They do not require the user or another human to inspect every
note or approve an ordinary correction. When the note and vault do not establish
a safe answer, preserve the content and report an optional source-backed or
separately scoped follow-up; that follow-up does not block the current run.

Related procedures:

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
| Ordinary `itemN` | Apply only the determinate, source-independent correction allowed by item N below. Report semantic or ownership uncertainty. |
| `item0` | Report the unreadable path and error; there is no parsed entry to repair. |
| `item1` | Repair only what the file itself establishes. Never invent title, dates, or review state, and preserve links to the real file. |
| `item2/read-type` | Normalize a recognizable answer to the equivalent bare boolean. |
| `item2/type-enum` | Write the exact enum spelling only when the body makes the intended type unambiguous; otherwise preserve and report. |
| `item2/read-missing`, `item2/read-null`, `item2/read-unknown` | Preserve and report; supplying a boolean would invent user-owned state. |
| `item2/parents-null` | Write `parents: []`; this changes only the spelling of an already empty value. |
| `item2/parents-form` | Preserve usable targets while normalizing representation and unambiguous target spelling. Re-derive invalid relationships only in Task 3's authorized closure. |
| `item2/obsidian-key` | Report and preserve exactly; it is valid user configuration. |
| `item3`, `item3/report-only` | Report date problems; wiki-linter writes neither date. |
| `item4/source-identity` | Establish provenance under item 4 before removing anything; preserve independent or uncertain citations. |
| `item9/imperative-link` | Integrate the link only when adjacent prose already states the relationship and the edit adds no claim; otherwise report a source-backed proposal. |
| `item9/duplicate-sentence` | This is a cross-entry ownership candidate. Preserve both copies and report the pair and likely owner unless the request explicitly names the consolidation or redistribution operation, or the affected entries and intended outcome. Normalized similarity alone never authorizes deletion. |
| `item10/case`, `item10/alias` | In Task 1, canonicalize the unambiguous existing target while preserving anchor and explicit display label. Never create a variant file. |
| `item10/self` | In Task 2, unlink an ordinary self-mention. Preserve real section/block navigation as a local `[[#Heading|Display]]` or `[[^block|Display]]` anchor. |
| `item10/ambiguous` | Preserve the whole link and report its competing owners. |
| `item10/unparsed` | Preserve the link; the target file's `item0` or `item1` governs repair. |
| `item10/dangling`, `item10/dup` | Use Task 2's [link protocol](link-hygiene.md), not an ordinary Task 1 repair. |
| `item10/table` | Replace only the table-cell link markup with its visible plain-text label. |
| `item10/redundant-pipe` | In Task 1, collapse exact `[[slug|slug]]` body-prose links to `[[slug]]`. Never apply this to the Related footer. |
| `item12/equation-typography` | In descriptions, replace raw ℓ-norm notation with plain `ell-one`/`ell-two` and retain Unicode `μm`. In prose and card prompts, replace raw ℓ-norm and `μm`/`µm` notation with canonical inline LaTeX. |
| `item12/equation-coverage-candidate` | Inspect the local prose or inline formula. Insert or promote an equation only when the note completely states the quantity or calculation; otherwise preserve and report the non-defining cue. |
| `item12/equation-format` | Preserve the existing equation and put its opening and closing `$$` delimiters on separate lines. Do not add a duplicate display. |
| `item12/panel-composite` | Preserve both embeds and report the duplicated exhibit until source-backed review chooses either the default composite or the subject-specific panel. |
| `item12/remote-image`, `item12/missing-image` | Report and preserve the embed and caption; repair requires work outside this entry. |
| `image_folder_findings` | Report and preserve nested, staging, unreadable, or portable-name-collision paths. Collision records retain all owner paths; an unreadable inventory also suppresses missing-image claims. |
| `item17/alias-candidate` | Apply the same-entity, collision, cross-domain, and Organism-common-name gates before adding anything. |
| `item19` | Apply the format floor only after reading [flashcard maintenance](flashcards.md). |
| `stub` | Remove a forbidden Related footer; never promote without a source. |
| `stub-one-sentence-body`, `stub-no-images` | Preserve and report; extra prose or media may be substantive user content. |
| `rename_candidates` | Propose with inbound count and collision warning; apply only with explicit authorization in the request and a complete reference rewrite. |
| `collision_candidates` | Report; routine lint never merges existing entries. |
| `hierarchy_diagnostic.parent_state_findings`, `moc_consistency_findings` | Use as report-only Task 3 inputs. Re-derive both hierarchy renderings from one authorized connected closure, never patch one edge in isolation. |
| Semantic-invalid alias | Propose the canonical owner and inbound rewrite; remove only through the approved alias-refactor protocol. |

## Source-independent item guide

For every item, first apply the canonical builder rule at the linked location,
then use only the linter-specific action stated here. The scanner's
[`problems` contract](scanner.md#item-keys-in-problems) is the source of truth
for its mechanical coverage; do not infer permission from a scanner message.

### 1. Valid YAML

Apply builder [item 1](../../wiki-builder/SKILL.md#quality-checklist) and the
[frontmatter guide](../../wiki-builder/references/writing.md#1-frontmatter-fields).
The opening fence is on file line 1; a BOM is tolerated, a leading blank is not.
Flow lists may be empty only as `[]`; leading, middle, or trailing empty
elements are invalid. Repair only values the file unambiguously establishes.

### 2. Field order and quoting

Apply the canonical [fields and quoting](../../wiki-builder/references/writing.md#1-frontmatter-fields).
Schema order is `title`, `type`, `aliases`, `sources`, `created`, `updated`, `description`, `tags`, `parents`, `read`.
Only `aliases` is optional; the other nine keys are required. Recover a
missing or valueless title only from one unambiguous canonical name evidenced
by the entry, because title-dependent checks otherwise cannot run.

Linter-specific routing:

- Normalize a type to one of the 15 enum values only when the body makes the
  semantic type clear. Otherwise preserve and report.
- Normalize empty `parents:` to `parents: []`. For a populated scalar, flow
  list, duplicate, or path/anchor/display/`.md` spelling, preserve every usable
  target and write the canonical block list. Re-derive a missing, ambiguous,
  stub, or unparsed relationship only in Task 3.
- A missing, null, or unrecognizable `read:` has no recoverable answer: report
  it and do not write one. A quoted boolean, YAML `yes`/`no`, or `0`/`1`
  carries a recognizable answer, so normalize only its representation to the
  equivalent bare boolean.
- Obsidian-owned appearance and publish properties are valid user state:
  report and preserve them. Preserve a populated legacy `importance:` without
  treating it as required or unexpected.
- A retired `roots:` with no `tags:` is an evidence-preserving roots-to-tags
  migration: convert only recognizable discipline-root targets to enum tags,
  and report any unresolved target. When `tags:` already exists, remove only
  the stale key. Never use either case to invent a discipline.

The `parents:` and `read:` empty cases intentionally differ: `[]` re-spells an
already empty list, while `false` would supply an answer the review field does
not contain.

### 3. Dates

Require valid `YYYY-MM-DD` dates with `created <= updated`, as builder
[item 3](../../wiki-builder/SKILL.md#quality-checklist) defines. The linter
writes neither field. Report invalid values, impossible ordering, and any
history-dependent question; do not guess which date is wrong or try to make
`updated:` equal a presumed merge date.

### 4. Sources

Use the canonical [source format](../../wiki-builder/references/writing.md#sources).
Remove an exact repeated list item. A same-stem PDF/Markdown pair remains
`item4/source-identity` until decoded `sources:` or legacy `source:` in the
Markdown note proves that it summarizes that PDF. Only then keep the anchored
PDF citation, remove the duplicate Markdown citation, and report the evidence.
Preserve an independent clipping and every uncertain pair. The linter checks
page-anchor form; the physical page's factual correctness needs the source.

### 5. Filename, collision, and disambiguation

Apply the canonical [naming rules](../../wiki-builder/references/writing.md#3-wikilinks-and-naming).
A title/filename mismatch is a rename proposal, never an automatic rewrite.
Report collision-probe matches as candidates; do not merge them. Whole-vault
maintenance uses slug equality, micro-sign normalization, singular/plural,
hyphen-collapse, word-order, and light stem morphology. When several probes
flag the same pair, report only the most specific probe label; no probe chooses
an entry owner. The linter deliberately omits the noisy create-time
token-superset probe. While reading, also report semantic synonym duplicates
that shape probes cannot find, including a stub that merely restates a full
entry.

### 6. Type and API surface

Apply [API surface](../../wiki-builder/references/api-surface.md) in full.
Non-`Software` entries permit no API identifiers, fenced code, Python literals
in code form, implementation signposts, recipes, or identifier catalogs.
`Software` may retain identifiers only when they explain an artifact-wide
interface or design convention; counting tokens cannot establish that scope.
Use [the strip-or-reclassify procedure](#coding-content-in-non-software-entries-item-6)
for determinate non-`Software` findings. Source-backed selection is required to
trim substantive prose from an existing `Software` entry.

### 7. Description

Apply the canonical [description rule](../../wiki-builder/references/writing.md#description)
to full entries and legacy stubs. Besides the scanner's form checks, review the
grammatical subject, current-status tense, and mathematical completeness. A
plain-language mathematical definition must retain every operation that
determines the quantity. Fix only when the note establishes the corrected
wording; otherwise report a source-backed proposal.

### 8. Tags

Use the shared discipline enum plus the canonical [tag rule](../../wiki-builder/references/writing.md#tags)
and [calibration](../../wiki-builder/references/calibration.md). Apply
unambiguous format fixes: block-list form, `#`, double quotes, exact enum case,
safe abbreviation expansion, wikilink-to-tag conversion for a known enum
member, and duplicate removal after canonicalization.

Semantic disciplinary ownership remains a judgment. Re-home or add a tag only
when the entry and vault make the canonical home unambiguous; otherwise report
the competing candidates. Blank `tags:` is valid on a full entry with no home.
A legacy stub must have at least one tag, but fill a blank only from strong,
consistent existing-vault evidence, never a mere majority or weak neighbor.

### 9. Body structure, coherence, flow, and scope

Apply builder [item 9](../../wiki-builder/SKILL.md#quality-checklist), the
[body guide](../../wiki-builder/references/writing.md#2-the-body), and the
[Person/Event date forms](../../wiki-builder/references/rare-types.md#dates-in-the-opener-person-and-event).
There is no body sentence, paragraph, word, or heading-count target.

**Coherence review.** Compare the title and qualifier with the description,
opener, equations, flashcard, and close neighbors. They must identify the same
entity and sense without incompatible scope, conditions, direction, or
notation. A conflict that requires choosing or changing a fact is a
source-backed proposal. A neighbor conflict may expose a wrong link, duplicate,
or split candidate; it does not authorize cross-entry redistribution.

**Flow and ownership review.** Give each paragraph a short purpose label,
check that every sentence advances it, and read the openings in sequence.
Inspect endings that open a new reader question after the paragraph has
finished its job. Keep real causal and contrastive bridges; a stock connector
does not repair a jump. Bullets are parallel, not sequential. Body links sit in
sentences that state their relationships. Report source/tutorial scaffolding
and application catalogs only when they do not serve the entry, and report
duplicated explanatory treatments by conceptual owner; length, list shape, or
lexical similarity alone proves nothing.

**Local apply boundary.** Item 9 permits exactly five organizational repairs:

1. Split or merge adjacent prose paragraphs without changing their sentences.
2. Move unchanged sentences only between adjacent paragraphs under one heading.
3. Convert an already explicit sequence from bullets to prose.
4. Integrate a navigation-only link when adjacent prose already states the
   relationship.
5. Within one entry, remove one exact duplicate sentence serving the same local
   semantic role.

Preserve qualifier and antecedent scope, introductions before uses, logical and
chronological order, citations, equations, and image/table-plus-caption units.
Report every repair. If the change crosses a section, changes a fact, removes
substantive content, chooses between claims, or redistributes material across
entries, preserve it and propose a source-backed follow-up. Entry splits,
merges, and redistribution also require authorization that names the operation,
or the affected entries and intended outcome. Pure renames keep their separate
approval rule.

For a missing `Person`/`Event` opener date, copy the exact date only when it is
already present elsewhere in the entry. Normalize an existing malformed date
only when all values and qualifiers are unambiguous. Otherwise report it. A
stub's one-sentence and no-image violations are report-only because deleting
content could destroy substantive work.

### 10. Wikilinks

Apply the canonical [link rules](../../wiki-builder/references/writing.md#link-form).
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
consult its [coverage contract](scanner.md#deterministic-scanner-and-autonomous-semantic-pass)
before disputing a finding or treating literal sample syntax as a link.

### 11. Related footer

Use the canonical [Related footer](../../wiki-builder/references/writing.md#the-related-footer).
Keep one ` · `-separated line and pipe every target to its canonical title,
with no slug-equal exception, including all-lowercase titles. Converting a bare
footer link to that form is determinate; inherited excess is reported rather
than pruned.

### 12. Equations, images, and tables

The equation clauses are owned by `wiki-builder/references/equations.md`; apply
that [canonical policy](../../wiki-builder/references/equations.md) rather than
reconstructing it from scanner output. Apply the separate canonical
[media rules](../../wiki-builder/references/media.md) to existing exhibits.
The adjacent [body math typography](../../wiki-builder/references/writing.md#prose-principles)
still governs plain quantities and escaped literal dollars. It also keeps
Greek-letter unit symbols in inline LaTeX: `10 $\mu\mathrm{m}$`, rather than
raw `10 μm` or `10 µm`; descriptions retain their separate plain-Unicode
allowance.

**Media and table format.** Preserve both valid embed classes: a local image is
an Obsidian embed by bare basename, while an external clipping image may remain
standard Markdown with its URL. A remote embed is report-only; converting its
syntax would break it. Report that reprocessing the source clipping with
`clipping-processor` can localize it. Every existing image or Markdown table has a brief
plain-text italic caption immediately below it; inline LaTeX is the only
caption markup. Keep exhibits beside the prose they clarify, never before the
opener, detached at the end, or grouped as a gallery; one motivating paragraph
supports at most one image or table. A clear local placement or format repair
is allowed. Ambiguous caption content or placement is proposed.

Never delete a missing embed or caption: repair belongs to extraction or an
approved source rename. Preserve a composite and lowercase-suffixed panel until
source-backed review decides whether the entry needs the default composite or
the panel-specific view. Figure selection, source fidelity, table values, and
retained rows or columns remain source-dependent.

**Equation coverage.** The scanner emits a conservative
`item12/equation-coverage-candidate`; inspect it autonomously. When the note's
own prose completely states every operand and operation of a local named
quantity or calculation, insert the canonical `$$...$$` equation immediately
after that prose. Never infer a population/sample denominator or any operation
the note does not supply. Keep restricted-case conditions in prose, and do not
turn a case-specific formula into the general concept's definition.

Every display preserves its mathematical domain and operational conditions:
positive sample/node/ensemble counts behind averages, nonzero denominators,
valid logarithm/root domains, integer and hyperparameter ranges, probability
normalization and zero-support conventions, training-fitted statistics and
their reuse, threshold equality, and tie or undefined-boundary handling.
Exact definitions remain distinct from numerical approximations such as clipping or
tolerance rules. If the note lacks an operational convention, state the
mathematical limitation and leave the implementation choice explicit.

**Equation form and notation.** Promote a defining inline equation to its own
display block; keep inline symbol references, bounds, complexity, and worked
parameter choices inline. Bind every symbol nearby. Normalize symbols to the
canonical table or a linked entry's notation for the same quantity, updating
every prose reference in the same edit. Preserve field-specific standard
notation and report genuinely ambiguous choices.

Per [Dates](../SKILL.md#dates), equation fixes write neither `created:`,
`updated:`, nor `read:`. An insertion into an entry whose `read:` is `true` is
named under *Notes for the user* with the slug and equation, so the user may
decide whether to clear their checkbox. Group every insertion, promotion, and
notation change under item 12 in the run report.

### 13. Merge integrity

In a source-independent run, apply only the structural floor of builder
[item 13](../../wiki-builder/SKILL.md#quality-checklist): one opener and no
stacked-body scars such as duplicated openings, stray frontmatter keys,
unexpected `---` fences, or standalone digit lines. Listings are excluded; a
schema-shaped line inside a `Software` example is not a repair target. Actual
source-merge integrity is not applicable without a merge.

### 14. Self-containment

Apply [prose principle 5](../../wiki-builder/references/writing.md#prose-principles).
Re-subject source-meta prose on the entity, or name people directly, only when
the surrounding sentence makes the replacement unambiguous without changing
claim, attribution, or certainty. Otherwise preserve and propose a
source-backed correction. Preserve the named-work exception: “the GPT-3 paper”
and “the authors of SGDR” identify wiki entities; bare “the paper” and “the
authors” do not.

### 15. Example discipline

Apply builder [item 15](../../wiki-builder/SKILL.md#quality-checklist) during
semantic review. Identify an unnecessary, tangential, repetitive, or overly
long example by purpose, never by sentence or note length. Trimming substantive
example content or verifying its values needs the source, so record a specific
proposal in `wiki-notes-suggestions.md`. Source/tutorial scaffolding and
application catalogs that do not serve the entry belong to item 9; `Software`
API catalogs belong to item 6.

### 16. Bold, italic, and code typography

Apply the canonical [emphasis rules](../../wiki-builder/references/flashcards-and-emphasis.md#5-bold-and-italic).
Fix unenumerated bold, emphasis wrapped around links/math/code, and missing
backticks on literal extensions or `[CLS]`/`[MASK]`/`[SEP]`/`[IMG]` tokens.
The scanner recognizes a conservative extension list; review uncommon literal
extensions too. A pure inline-math title may use outer bold in its exact first
opener slot (`**$R^{+}$**`); the same wrapping anywhere else remains misuse.
Preserve the exact special opener forms for symbols, `Work` titles, and
evidence-backed scientific `Organism` names, including plain strain/isolate/
serovar/subtype suffixes.

An ambiguous taxon-shaped, rank-marked, or genus-only title needs the source.
Record that verification proposal and leave plausible typography unchanged.
Once visible title text matches, either plausible emphasis may remain without
creating a recurring finding.

### 17. Alias identity and completeness

Use the canonical [alias rule](../../wiki-builder/references/writing.md#aliases).
The note body itself can establish a missing alternate name for its subject;
add its slug only after the same-entity, own-slug, cross-domain, Organism
common-name, and whole-vault collision gates. A semantic-invalid existing alias
is not list cleanup: preserve it during routine lint and propose the canonical
owner plus complete inbound rewrite.

### 18. Alias form, collisions, and display labels

Apply builder [item 18](../../wiki-builder/SKILL.md#quality-checklist) and the
canonical [display-label rule](../../wiki-builder/references/writing.md#display-label-casing).
Normalize determinate alias form and duplicates; report cross-entry ownership
conflicts. Never auto-retarget a display whose exact surface belongs to another
entry. Preserve the three deliberate display-label carve-outs: a
context-resolved cross-domain bare term, a natural plural or verb inflection,
and an explicitly bound Organism common name. Do not create an ambiguous alias
merely to silence a display-label finding.

### 19. Flashcards

Apply the canonical [card format](../../wiki-builder/references/flashcards-and-emphasis.md#4-flashcards)
and the linter's [bidirectional definition review](flashcards.md). Every full
entry has one card after the Related footer and separator; stubs have none. A
variant Flashcards heading is repaired in place rather than duplicated.
A missing section or empty section is repaired by writing the one primary card
from the entry's already-established main claim, with `??` and the canonical
primary answer. This restores the required card without selecting a different
tested facet; itemize the addition in the run report.

The scanner checks each card's contiguous definition / cue / answer content.
Line 1 is a self-contained, capitalized, period-ended sentence with inline
LaTeX as its only markup; it must neither expose nor semantically reconstruct
the answer and must retain defining mathematical operations. Line 2 is `??` or
the user's preserved `!!`. Line 3's content, before any protected attachment,
is the plain-text canonical title or qualified title's base/mathematical plain
form, plus
only a qualifying opener-established, alias-bound counterpart. The qualifying
classes are the canonical acronym/full-form pair, direct “short for” expansion,
and direct scientific abbreviation. The executing agent still checks whether a
qualifying pair was omitted from the opener.

The canonical card-format rule defines the protected same-line, immediately
following-line, metadata-callout, and block-ID attachments. A blank line closes
the attachment position. Preserve each recognized attachment byte-for-byte and
in place; line-3 plainness never authorizes removing a block ID. Other visible
or comment content is malformed. When legacy content has multiple cards,
identify the one satisfying the complete primary-answer contract, preserve
every card and attachment, quote each extra card verbatim in the report, and
propose a split when a cited source supports the extra term as a real entity.
Routine lint does not delete an extra card. Move or remove one only under an
explicitly authorized source-backed refactor that accounts for its claim and
attachments, or an explicit request to delete that card. Visible metadata
absence does not establish a fresh card; apply the [history-aware rewrite
bar](flashcards.md) before changing a definition.

**The checklist ends at 19.** The retired `importance:` item was last, so its
removal created no numbering gap. Legacy populated `importance:` remains valid
and preserved under item 2.

## Source-dependent and proposal-only limits

- **Item 3:** ordinary source-independent QC never chooses or rewrites a merge
  date; explicit source-backed refactor mode follows its separate date rules.
- **Item 4:** page-anchor syntax is checked; whether the physical page is
  factually correct needs the source.
- **Item 12:** entry-to-file resolution is source-independent, but figure
  selection, source fidelity, caption facts, and table contents need the
  source. An unused image file is not itself a missing-content finding.
- **Item 15:** example purpose can be assessed now, but substantive trimming
  and value verification are source-backed proposals.

## Fix discipline

- Make targeted, localized corrections. A format or schema finding usually has
  one determinate output. Semantic metadata changes apply only when
  unambiguous. Item 9 uses only its five listed operations; item 6 may remove a
  sentence whose entire function is a forbidden implementation signpost,
  recipe, identifier catalog, or listing while preserving conceptual claims.
  None grants general rewriting permission.
- Fact changes, conflict resolution, source-content selection, and substantive
  trimming need a source-backed request. A named entry may be corrected from
  sources it already cites under the
  [correction protocol](source-backed-corrections.md); a new source routes to
  builder. Cross-entry splits, merges, deletion, and redistribution use the
  refactor protocol and also need authorization; an existing request covering
  the refactor supplies it, so do not ask twice.
- A retitle or re-slug is a rename. Propose it during routine lint, with inbound
  count and collision risk. Apply only when the request explicitly authorizes
  it, using the full
  [entry-retitle protocol](../../../shared/CONVENTIONS.md#retitling-an-existing-wiki-entry).
- Semantic-invalid alias removal follows the same approved refactor: establish
  identity and owner, inventory inbound alias-target entry links, rewrite every
  resolving surface, verify, then remove the alias. Text matches in sources,
  embeds, and logs are not entry links.
- Valid blanks remain valid. Blank `tags:` may be correct on a full entry;
  `parents: []` is a valid empty hierarchy. Missing or unrecognizable `read:`
  is different because supplying a boolean would invent user-owned state.

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
`cross_val_predict`, needs a rename and conceptual restructure around the
underlying entity. Propose that approved refactor and leave the file and inbound
references intact until it runs.

When the distinction is unclear, preserve and report. Do not gut an entry or
flip its type merely to silence a mechanical finding.
