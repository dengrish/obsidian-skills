# Source-backed corrections to an existing entry

Read this only when the user asks to correct one named existing entry from
sources that entry already cites. A generic lint request does not
activate this mode. A source not already cited by the target is a new
contribution and belongs to `wiki-builder`; a split, merge, retitle, deletion,
or cross-entry redistribution uses [source-backed refactors](refactors.md).

## Establish the evidence and scope

1. Run Step 0 and snapshot the named entry. Retain its original lint findings
   as the baseline, then decode its complete current
   `sources:` list. Resolve every source needed for the requested correction as
   a durable vault file; for a PDF/summary pair, verify against the PDF. A live
   page, memory, or a source cited only by another entry is not evidence for
   this mode.
2. Locate the exact supporting and conflicting passages and, for PDFs, their
   physical pages. If the cited files do not settle the correction, preserve
   the note and report what evidence is missing. Do not turn a request to
   “correct this note” into a search for new sources.
3. Keep the edit within the named entry. If the correction reveals a distinct
   entity, changes another entry, or requires choosing which entry owns content,
   stop that part and route it to builder or the structural refactor protocol.

## Correct and publish

Apply the current builder rules for fields, prose, equations, media, links, and
flashcards. Change the erroneous claim and only the same-entry surfaces needed
to keep it coherent: for example its description, opener, equation, or primary
card. Preserve unrelated prose, existing source membership, `created:`,
`parents:`, user-owned fields, and protected card attachments.

If the final entry changed, set `updated:` to today's local date. Reset
`read: false` only when the correction adds or rewrites unread explanatory body
content under the builder's body-change rule; a metadata-, link-, or
format-only correction preserves it. Missing or unknown review state is never
invented.

Lint the complete private draft with builder's `lint_entry.py`, then review its
source fidelity and paragraph flow. The correction must introduce no new lint
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
