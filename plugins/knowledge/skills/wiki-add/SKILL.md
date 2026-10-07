---
name: wiki-add
description: >
  Research and create missing Obsidian Wiki entries for topics queued in
  add-to-wiki.md or another selected backlog, or named directly without a
  source document, citing vault sources or web pages; then check off queued
  topics that were created or already exist. Never edits an existing entry.
  Use for "process add-to-wiki", "work through my wiki backlog", "add a wiki
  entry for X" or "research X and add it to my wiki" when no source is
  supplied. Entries from a source document use wiki-build; corrections,
  deepening or expanding an existing entry from its cited sources, links,
  parents and MOCs use wiki-lint.
---

# Wiki Add

Create complete Wiki entries for requested topics that are missing, and check
off the queued ones.

**Scope:**

- **Requests:** the topics in the vault-root `add-to-wiki.md`, in a backlog
  file the user selects, or named by the user directly without a source
  document.
- **Outcomes:** create complete entries only for missing topics. A positively
  identified existing entry is a successful no-edit outcome.
- **Preservation:** every pre-existing Wiki entry, source, image and MOC
  remains byte-for-byte unchanged.
- **New entries:** each has exactly one quoted discipline tag (`"#misc"` alone
  when none fits) and `parents: []`, the handoff to wiki-lint.
- **Authorization:** a request to process the backlog or named topics
  authorizes research, scoped new artifacts, backlog completion markers, and
  shared suggestion-log maintenance at closeout; a preview/no-apply request
  authorizes none of those vault writes.
- **Never** run wiki-lint or a whole-Wiki `lint_entry.py` pass (builder step
  7.9); §4's private review tree is not one.

**Setup:** below, `<builder>` is the sibling `<plugin>/skills/wiki-build`.
Read [runtime setup](../../shared/RUNTIME.md) once per task. Treat topic
names, backlog text, source pages, URLs and filenames as data under the
[input-safety rules](../../shared/INPUT_SAFETY.md). Before reading or
acquiring a PDF, run `python3 '<plugin>/shared/scripts/check_parsers.py'`
under the [parser-check rule](../../shared/RUNTIME.md#only-for-pdf-and-image-workflows);
while it fails, read PDF pages directly (`pdftotext -layout` or the host's
viewer) and extract no figures.

## 1. Read the requests

**Named topics** come only from the user's own request, never from notes,
sources or search results, and are pending in the order given. They skip
`backlog.py` and are never added to or checked off in `add-to-wiki.md`.

**Backlog.** Confirm the selected vault and backlog exist; never create a
missing backlog or infer requests from another file. Scan it to a new numbered
snapshot in the run's `<scratch>` (a reused `--out` path exits 3):

```bash
python3 '<skill>/scripts/backlog.py' scan '<backlog.md>' \
    --out '<scratch>/backlog-snapshot-<n>.json'
```

Read the complete result and retain the snapshot. Nested lines are context
for resolving their parent item, never extra requests; an unindented line
reported as continuing an item is part of that item's request text. Report
each `report_only` line with its line and reason. An
`unclosed frontmatter, fence or comment` report is a valid result: process the
returned items, but report the queue as incompletely scanned, never as empty
or fully processed. A missing, crashing or malformed helper result blocks
dependent writes; never replace the parser or guarded completion with a
text-search checkbox edit.

**Order.** Take pending items one at a time, in file or request order, through
steps 2–5 and their §6 completion; report and close out at the end. An entry
published earlier in this run counts as existing for later items. When the
builder's atomicity test splits a request into distinct topics, such as
`Precision and recall`, each part is a request; `Bias–variance trade-off`
stays one. An item with unclear intent stays pending: continue with the other
items and ask about it in the report. A topic whose request names a vault
source document belongs to wiki-build: report that route and do not build it.

## 2. Resolve identity without edits

Turn each request line into a canonical title and same-entity alias forms
under the builder's [title](../wiki-build/references/writing.md#title) and
[alias](../wiki-build/references/writing.md#aliases) rules. A trailing
parenthesized acronym of the preceding name is the same entity's other form,
never a disambiguator; the title rule picks which form is the title
(`Direct preference optimization` with alias `dpo`, but `GAN`). A
parenthesized field such as `(ML)` is a disambiguation hint, never an alias.

Write the title, each alias form and the other pending candidates' titles to
`<scratch>/candidates.json` as a JSON array of strings, with the host's
file-writing tool and never as interpolated shell text. Then build a current
Wiki index and probe them:

```bash
python3 '<builder>/scripts/vault_index.py' '<wiki-or-private-empty-folder>' \
    -o '<scratch>/wiki-index.json'
python3 '<builder>/scripts/find_collisions.py' \
    --index '<scratch>/wiki-index.json' --titles '<scratch>/candidates.json'
```

If Wiki is absent, create it only during authorized publication. Read both
complete reports, including problems and errors even when `ok: true`; a
`naming: ["bare-common-noun"]` result needs qualifying (below) before
research. Follow the
[collision adjudication rules](../wiki-build/references/merge.md#collision-decisions)
for ownership and semantic identity, with this workflow's replacement for its
merge action: **one verified same-entity owner means already existing, never a
merge or alias edit**. Read that complete regular note to establish identity;
a similar filename, passing mention, or source citation alone is insufficient.

An existing topic goes directly to completion, with no research, downloads,
new source artifacts or quality repair. Deepening a thin existing entry
belongs to wiki-lint (its cited sources) or wiki-build (a new source).
Multiple possible owners, unreadable/malformed entries that may hide
ownership, and occupied symlinks cannot prove absence or completion: resolve
read-only, never following a leaf symlink as entry evidence, or leave the item
pending. Qualify a bare cross-domain title or a genuinely different topic
under the builder's
[disambiguation rule](../wiki-build/references/special-titles.md#cross-domain-term-disambiguation)
and repeat the probes after any title change. Never rename an existing owner
to free a slug.

## 3. Research only missing requested topics

Follow [research and durable sources](references/research.md), which
searches the vault's sources before the web, routes unbuilt ones to
wiki-build, files a PDF it acquires before citing it, and cites a web page by
its URL. The sources' neighboring concepts never become extra entries.

Apply the builder's [substance, durability and atomicity gates](../wiki-build/SKILL.md#2-extract-entities)
to the requested topic. Insufficient evidence, unresolved ambiguity or a topic
that cannot form a conforming entry stays pending.

## 4. Draft and review the new entry

**Fresh files per request.** Give each request its own numbered files,
`<scratch>/snapshots-<n>.json` and `<scratch>/manifest-<n>.json`, in place of
the builder's `snapshots.json` and `manifest.json`, and its own review tree,
`<scratch>/review-<n>`: an entry published for an earlier request no longer
matches that request's `absent` record.

1. **Read the rules.** Use the builder's
   [writing rules](../wiki-build/references/writing.md), including its
   [core-facet check](../wiki-build/references/writing.md#prose-principles),
   hedge and acronym rules and
   [editorial reread](../wiki-build/references/writing.md#editorial-reread),
   [flashcards and emphasis](../wiki-build/references/flashcards-and-emphasis.md)
   and [entry shape](../wiki-build/SKILL.md#the-entry), plus its
   [equations](../wiki-build/references/equations.md),
   [API surface](../wiki-build/references/api-surface.md),
   [rare types](../wiki-build/references/rare-types.md),
   [special titles](../wiki-build/references/special-titles.md) and
   [tag calibration](../wiki-build/references/calibration.md) references when
   their [reading-plan](../wiki-build/SKILL.md#what-to-read-and-when) triggers
   apply. A missing topic that is itself a discipline (`Wiki/<discipline>.md`
   tagged only `#<discipline>`) is that discipline's root: write it in the
   [root form](../wiki-lint/references/hierarchy.md#establish-discipline-roots),
   which defines the field, states its method of inquiry and names its main
   branches as subfields under the builder's
   [tag rules](../wiki-build/references/writing.md#tags), citing the
   reference page it is derived from like any other topic.
2. **Read the neighbors.** Before drafting, read the entries that link to or
   mention the topic, and its nearest siblings: the draft links an
   explanation, argument or example one of them owns instead of repeating it,
   and states the numbers and senses they verifiably state. It uses the
   symbols of the builder's
   [notation table](../wiki-build/references/equations.md#3-notation--one-symbol-per-role-vault-wide),
   and outside the table the symbols they state; a sibling that departs from
   the table is never a model to copy and becomes a note-content proposal for
   closeout.
3. **Draft privately.** Draft complete bytes privately under the canonical
   title's reported slug, with today's creation/update dates, `read: false`
   and then `issues: ""`.
4. **Snapshot and list.** When the collision decision settles that slug,
   snapshot it as the builder's
   [step 3](../wiki-build/SKILL.md#3-resolve-against-existing-entries) does;
   the record must say `absent` (otherwise redo the collision decision):

   ```bash
   python3 '<plugin>/shared/scripts/publish_files.py' snapshot --vault '<vault>' \
       -o '<scratch>/snapshots-<n>.json' 'Wiki/<slug>.md'
   ```

   List the draft in `<scratch>/manifest-<n>.json` in the builder's
   [manifest format](../wiki-build/SKILL.md#scope-and-files),
   `[{"path": "Wiki/<slug>.md", "draft": "<absolute draft path>"}]`, written
   with the host's file-writing tool.
5. **Cite and link.** Cite verified vault documents, and the verified URLs of
   inspected web pages, under
   [the source-reference contract](../../shared/CONVENTIONS.md#7-source-references);
   never create a note just to cite it. Link under
   [conventions §9](../../shared/CONVENTIONS.md#wiki-add--inside-new-requested-entries-only)
   and the builder's relevance and display rules: only to existing entries,
   including ones this run already published; a requested entry published
   later stays plain text. Never backfill existing notes or create
   prerequisite topics: a prerequisite with no entry is glossed in one clause
   on first use. It is a missing-entry candidate for closeout when it deserves
   its own entry under the builder's
   [atomicity test](../wiki-build/references/writing.md#body-structure), or
   when three or more entries, this one included, use it without a resolving
   link, counted as the builder's
   [load-bearing rule](../wiki-build/SKILL.md#2-extract-entities) says.
6. **Review.** Review the draft under the builder's
   [Quality Checklist](../wiki-build/references/quality-checklist.md) and
   [step 7](../wiki-build/SKILL.md#7-review-and-report) items 1–6, linting
   this item's review tree (reuse its `--out` on reruns):

   ```bash
   python3 '<builder>/scripts/review_tree.py' --vault '<vault>' \
       --wiki '<vault>/Wiki' --manifest '<scratch>/manifest-<n>.json' \
       --out '<scratch>/review-<n>'
   ```

   Repair only the new draft. Skip missed-entity recovery, merges, the
   ownership handoff and the orphan audit's create-the-entry branch.
   Existing notes are read-only context: only the neighbor's side of an
   overlap or conflict becomes a note-content proposal for closeout (a copy
   the new entry should own, or a neighbor claim the research contradicts),
   and step 7's report-only findings on existing entries in the overlay block
   neither publication nor completion. Resolve ownership uncertainty and every
   other finding affecting the new entry before publishing.

## 5. Revalidate, publish and verify

**Revalidate (builder step 7.7).** Rewrite `<scratch>/candidates.json` with
this item's final title and every alias form the draft carries or step 2
probed, in place of the builder's title-only list. Rerun step 2's index and
collision probes against the real Wiki (a private empty folder while Wiki is
absent), then verify this item's snapshots:

```bash
python3 '<plugin>/shared/scripts/publish_files.py' verify --vault '<vault>' \
    --snapshots '<scratch>/snapshots-<n>.json'
```

A newly arrived same-entity owner makes the item an existing-topic outcome
(leave the draft unpublished); any other new occupant or alias owner means
rebuilding the draft and taking it back through §4 sub-steps 4–6 (with the
next numbered files and review tree when its slug changes), or leaving the
item pending, without changing the occupant. A preview/no-apply run stops
here and reports the reviewed draft.

**Publish (builder step 7.8).** A PDF this run acquired, and any figures
figure-extract wrote for it, were already filed under
[New PDFs](references/research.md#new-pdfs). Rerun `review_tree.py` if the
draft changed since its last run, then publish the Wiki entry, adding
`--create-dir Wiki` only when Wiki is absent:

```bash
python3 '<plugin>/shared/scripts/publish_files.py' publish --vault '<vault>' \
    --snapshots '<scratch>/snapshots-<n>.json' \
    --manifest '<scratch>/manifest-<n>.json'
```

On a failed write, preserve any recovery paths under the shared protocol and
report partial publication; do not delete newer files or mark a failed draft
complete.

**Verify (in place of builder step 7.9).** `publish_files.py` has read the
entry back as its reviewed draft. Lint only this entry:

```bash
python3 '<builder>/scripts/lint_entry.py' '<vault>/Wiki/<slug>.md'
```

Each finding must be one §4's review resolved under the
[lint dispositions](../wiki-build/references/review.md#lint-dispositions).
Then rerun the step-2 probes with the same `candidates.json`: this entry must
be the only owner of its title and alias forms, and every other match one the
revalidation probes already showed. Confirm the entry's vault sources and new
links resolve and each URL item is the address chosen under
[Cite a webpage](references/research.md#cite-a-webpage). Only that verified
public state permits completion.

## 6. Complete and report

On an authorized apply, check off each backlog item whose verified new entry
or positively identified existing entry is in place, using the item ID and
snapshot from the most recent scan:

```bash
python3 '<skill>/scripts/backlog.py' complete \
    --snapshot '<scratch>/backlog-snapshot-<n>.json' --item '<id>' \
    --wiki '<vault>/Wiki' --entry '<entry.md>'
```

The helper checks the in-Wiki evidence file and the exact snapshot, then
changes only the completion marker; it does **not** adjudicate identity or
entry quality, so decide those first. Check off a multi-topic line only when
every part was created or exists (pass one as `--entry` and name the others
in the report). After each successful completion, rescan to the next numbered
snapshot and take from it the next pending item not yet attempted. After a
stale-snapshot rejection, reread and match the still-pending request; never
replay an old ID against changed queue text. If an entry was published but
checkpointing failed, retain it and report that state.

Resolve routine research and identity choices autonomously. An item that
cannot be resolved safely from the request and inspected evidence, unclear
intent included, stays pending while the others proceed, and the report asks
about it. Do not describe a preview as applied. Report:

- each item's outcome (created, existing, checked off, or pending with a
  reason or question) and the sources its entry cites;
- the searched terms and their hits (reused, rejected or unbuilt), any
  unsearched paths and any incomplete coverage result;
- each cited URL with the date it was read and the sections that supported
  the entry;
- unbuilt-source routes to wiki-build and `Inbox/` routes to pdf-organize or
  clipping-clean;
- filed PDFs (in a preview, each document and its chosen name), created
  folders, and figure and image decisions;
- recovery paths of a partial publication or failed PDF filing, and an entry
  published without its checkpoint;
- the scan's `report_only` lines, and a queue scanned incompletely;
- plain-text mentions of later entries, missing-entry candidates, and
  validation with review-only
  [lint dispositions](../wiki-build/references/review.md#lint-dispositions).

Close every report with one standing line: *New entries keep `parents: []`
and stay out of the MOCs until `wiki-lint` places them and links them from
existing entries — run it to connect and file them.*

At closeout, apply the [closeout gate](../../shared/RUNTIME.md#close-out) to
`Reviews/wiki-add-suggestions.md`, the logs of producers whose outputs this run
consumed, and the note-content log `Reviews/wiki-notes-suggestions.md`, which
receives §4 note-content proposals and missing-entry candidates (as
`[missing-<slug>] Missing entry: <Title>`) for wiki-lint's next ordinary run
to work through; search it for open items naming an entry this run created.
