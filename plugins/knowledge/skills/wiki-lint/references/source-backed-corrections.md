# Source-backed corrections to an existing entry

Read this when the user asks to correct, simplify or deepen existing entries. A
correction rests on the sources each entry already cites; the request need not
name them. The corrected entry may also add accurate background that makes it
easier to understand, under the builder's
[prose principle 5(h)](../../wiki-build/references/writing.md#prose-principles);
background needs no citation. A request covering a class of defects or the whole Wiki
applies to every matching entry in that scope, not just named examples. A generic lint request does not
activate this mode. A source not already cited by the target is a new
contribution and belongs to `wiki-build`; a retitle uses the
[entry-retitle protocol](../../../shared/CONVENTIONS.md#retitling-an-existing-wiki-entry),
and a split, merge, deletion, or cross-entry redistribution uses
[source-backed refactors](refactors.md).

**Deepening.** A request to deepen, expand or enrich an entry applies the
builder's creation-time teaching rules to it: the learner arc, core-facet check
and examples of its
[prose principles](../../wiki-build/references/writing.md#prose-principles),
its [equation rules](../../wiki-build/references/equations.md) and its
[card set](../../wiki-build/references/flashcards-and-emphasis.md#card-set).
Fill gaps from the entry's cited sources and 5(h) background. Keep every
existing claim unless it is wrong, and every card and attachment byte-for-byte
and in place.

## Establish the evidence and scope

1. Run Step 0 and snapshot each affected entry. Retain its original lint findings
   as the baseline, then decode its complete current
   `sources:` list. Resolve every source needed for the requested correction as
   a durable vault file; for a PDF/summary pair, verify against the PDF. A live
   page, recollection, or a source cited only by another entry cannot overturn
   what a cited source says.
2. Locate the exact supporting and conflicting passages and, for PDFs, their
   physical pages. If the cited files do not settle the correction, preserve
   the note and report what evidence is missing. Do not turn a request to
   “correct this note” into a search for new sources. In a cleaned clipping,
   locate passages in its captured body, not in its Summary callout or other
   clipping-clean annotations
   ([rule](../../wiki-build/references/source-intake.md#read-and-classify)).
3. Keep each correction within its affected entry. If the correction reveals a distinct
   entity, changes another entry, or requires choosing which entry owns content,
   stop that part and route it to builder or the structural refactor protocol.

## Correct and publish

Apply the current builder rules for fields, prose, equations, media, links, and
flashcards. Correct the erroneous claim, remove the unnecessary caveat or add
the missing explanation, preserving essential assumptions and the ordinary
mechanism. Never remove an accurate claim
merely because the cited source does not state it. Change only the same-entry surfaces needed
to keep it coherent: for example its description, opener, equation, or primary
card. Then re-read the whole note: merge claims the change left duplicated and
restore teaching order under the builder's
[integration principle](../../wiki-build/references/merge.md#integration-principle),
losing no claim. A deepen request may restructure the whole body this way.
Preserve unrelated prose, existing source membership, `created:`,
`parents:`, user-owned fields, and protected card attachments.

If the final entry changed, set `updated:` to today's local date. Reset
`read: false` only when the correction adds or rewrites unread explanatory body
content under the builder's body-change rule; a metadata-, link-, or
format-only correction preserves it. Missing or unknown review state is never
invented.

Lint the complete private draft with
`python3 '<plugin>/skills/wiki-build/scripts/lint_entry.py' '<draft>'`. Before
publication, check every added or changed wikilink and alias against the Step 0
inventory: each target must be an existing, unambiguous entry, and a changed
alias must not collide with another entry's title or alias. Then review the
draft's source fidelity and paragraph flow. The correction must introduce no new lint
finding, and every baseline finding on a field or passage changed by this run
must be resolved. Unrelated pre-existing findings remain unchanged and are
reported; they neither widen the authorization into general cleanup nor block a
valid correction unless they prevent source ownership, safe publication, or a
coherent reading of the changed claim. An unavailable helper, crash, malformed
output, or unresolved source blocks publication; it is not a clean result.
Publish through the shared safe-write protocol against the exact original
snapshot, re-scan the entry, and verify the public bytes. Report the entry,
cited source provenance and applicable PDF page, corrected claim, dependent
same-entry changes, date/review-state decision, and final scan result.
Authorization in the user's correction request is sufficient; do not ask for a
second review.
